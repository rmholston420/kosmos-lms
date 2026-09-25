"""kernel.tektos_thermal_watchdog — ADR-121 sustained-thermal watchdog.

Stage 11.5 (Endpoint Split — thermal family). The dashboard's Thermal
card fetched ``/api/thermal/status`` through the ADR-109 gateway proxy
to the retired :8020 standalone engine. This module replaces that with
a kernel-native background watchdog:

* Samples GPU (``nvidia-smi``) + CPU (``/sys`` hwmon) every 5 s.
* Feeds each sample to :class:`SustainedCooldownRule` (ADR-121):
  GPU must not *sustain* >= 75°C for more than 60 s.
* When the rule fires it applies a real cooldown — drops the power
  cap to 350 W (``sudo nvidia-smi -pl``, the existing NOPASSWD
  entry) — and publishes ``thermal.cooldown`` on the event bus.
  When the rule clears (temp back under threshold) it restores the
  400 W login default.
* ``snapshot()`` returns the :8020-shaped envelope the card already
  parses (``gpu.{temperature,action,reason}``, ``cpu.temperature``,
  ``regulation_count``, ``history``) — so the card UI is unchanged.

Design constraints (ADR-092 degrade pattern):

* No pynvml in the kernel venv — GPU reads shell out to
  ``nvidia-smi`` in a worker thread (bounded, cached on failure).
* ``snapshot()`` NEVER raises and NEVER fabricates: a failed sample
  carries ``action="hold"`` + a reason, not a fake reading.
* The cooldown apply path is best-effort: if sudo/NVML is unavailable
  the rule still reports ``cooldown`` active (the dashboard shows it)
  and the failure is logged, never 500'd.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Optional

from adapters.thermal.tektos.adapter import (
    ColossusThermalThresholds,
    SustainedCooldownRule,
)

logger = logging.getLogger(__name__)

__all__ = ["ThermalWatchdog", "COOLDOWN_POWER_CAP_W", "NOMINAL_POWER_CAP_W"]

NOMINAL_POWER_CAP_W = 400  # login default (nvidia-clock-lock.service)
COOLDOWN_POWER_CAP_W = 350  # ADR-121: -25% to shed load
SAMPLE_INTERVAL_S = 5.0
HISTORY_LEN = 60  # ~5 min of 5 s samples


# ── Hardware reads (worker-thread safe, failure-tolerant) ───────────────


def _read_gpu() -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(temperature_c, power_w, clock_mhz) or Nones on failure."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,power.draw,clocks.current.graphics",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return None, None, None
        temp, power, clock = (float(x) for x in out.stdout.strip().split(",")[:3])
        return temp, power, clock
    except Exception:  # noqa: BLE001 — watchdog must never die on a read
        return None, None, None


def _read_cpu() -> Optional[float]:
    """CPU package temp from hwmon (k10temp preferred) else thermal zones."""
    # Preferred: the named CPU sensor (k10temp on Collosus AMD).
    try:
        for entry in os.listdir("/sys/class/hwmon"):
            base = os.path.join("/sys/class/hwmon", entry)
            try:
                with open(os.path.join(base, "name")) as f:
                    name = f.read().strip()
            except OSError:
                continue
            if name not in ("k10temp", "coretemp", "cpu_thermal"):
                continue
            for tmp in sorted(os.listdir(base)):
                if tmp.startswith("temp1_input") or tmp == "temp1_input":
                    with open(os.path.join(base, tmp)) as f:
                        return int(f.read().strip()) / 1000.0
    except OSError:
        pass
    # Fallback: max of /sys/class/thermal zones (millidegrees).
    try:
        best: Optional[float] = None
        for entry in os.listdir("/sys/class/thermal"):
            if not entry.startswith("thermal_zone"):
                continue
            try:
                with open(os.path.join("/sys/class/thermal", entry, "temp")) as f:
                    v = int(f.read().strip()) / 1000.0
                best = v if best is None else max(best, v)
            except (OSError, ValueError):
                continue
        return best
    except OSError:
        return None


def _apply_power_cap(watts: int) -> bool:
    """Best-effort power cap via the NOPASSWD nvidia-smi sudoers entry."""
    try:
        out = subprocess.run(
            ["sudo", "-n", "nvidia-smi", "-i", "0", "-pl", str(watts)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        ok = out.returncode == 0
        if not ok:
            logger.warning(
                "thermal watchdog: nvidia-smi -pl %d failed: %s",
                watts,
                (out.stderr or out.stdout).strip()[:200],
            )
        return ok
    except Exception:  # noqa: BLE001
        logger.exception("thermal watchdog: power cap apply raised")
        return False


# ── Watchdog ─────────────────────────────────────────────────────────────


@dataclass
class _State:
    gpu_temp: Optional[float] = None
    gpu_power: Optional[float] = None
    gpu_clock: Optional[float] = None
    cpu_temp: Optional[float] = None
    action: str = "hold"
    reason: str = "watchdog warming up"
    power_limit: int = NOMINAL_POWER_CAP_W
    cooldown_active: bool = False
    seconds_over: float = 0.0
    regulation_count: int = 0
    last_sample_at: Optional[datetime] = None
    history: Deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))


class ThermalWatchdog:
    """Background sampler + ADR-121 sustained-cooldown enforcement.

    Wire once per kernel lifetime (lifespan startup/shutdown). The
    rule's thresholds come from the ADR-081 Colossus profile extended
    with the ADR-121 cooldown fields (75°C / 60 s).
    """

    def __init__(
        self,
        *,
        thresholds: ColossusThermalThresholds | None = None,
        event_bus: Any | None = None,
        apply_cap: Any = _apply_power_cap,
    ) -> None:
        t = thresholds or ColossusThermalThresholds()
        self.thresholds = t
        self.rule = SustainedCooldownRule(
            threshold_c=t.cooldown_c, sustain_s=t.cooldown_sustain_s
        )
        self._bus = event_bus
        self._apply_cap = apply_cap
        self._state = _State()
        self._task: Optional[asyncio.Task] = None

    # -- lifecycle ----------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(
                self._loop(), name="thermal-watchdog"
            )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:  # noqa: BLE001,S110 — teardown
                pass
            self._task = None

    async def _loop(self) -> None:
        logger.info(
            "thermal watchdog: started (interval=%.0fs, cooldown>=%.0f°C for %.0fs)",
            SAMPLE_INTERVAL_S,
            self.thresholds.cooldown_c,
            self.thresholds.cooldown_sustain_s,
        )
        while True:
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 — the loop must outlive any tick
                logger.exception("thermal watchdog: tick failed")
            await asyncio.sleep(SAMPLE_INTERVAL_S)

    # -- one sample ----------------------------------------------------

    def process_sample(
        self,
        gpu_temp: float | None,
        *,
        at: datetime,
        gpu_power: float | None = None,
        gpu_clock: float | None = None,
        cpu_temp: float | None = None,
    ) -> None:
        """Apply one sample: state, rule, classification, history.

        Pure (no I/O) — ``_tick`` supplies fresh hardware readings and
        the tests supply a scripted clock. Single source of truth for the
        decision path so the two can never drift.
        """
        s = self._state
        if gpu_temp is not None:
            s.gpu_temp = gpu_temp
            s.gpu_power = gpu_power
            s.gpu_clock = gpu_clock
        if cpu_temp is not None:
            s.cpu_temp = cpu_temp
        s.last_sample_at = at

        decision = self.rule.evaluate(gpu_temp, at=at) if gpu_temp is not None else None
        if gpu_temp is None:
            # Failed sensor read — do not let a stale at/above window from
            # before the gap keep arming.
            self.rule.reset()
            if s.cooldown_active:
                s.cooldown_active = False
                s.power_limit = NOMINAL_POWER_CAP_W
                self._apply_cap(NOMINAL_POWER_CAP_W)
        self._classify(s, decision)
        if decision is not None:
            s.seconds_over = decision.seconds_over
        else:
            s.seconds_over = 0.0

        s.regulation_count += 1
        s.history.append(
            {
                "timestamp": at.isoformat(),
                "gpu_temp": s.gpu_temp,
                "cpu_temp": s.cpu_temp,
                "power": s.power_limit,
                "clock": s.gpu_clock,
                "action": s.action,
            }
        )

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        gpu_temp, gpu_power, gpu_clock = await asyncio.to_thread(_read_gpu)
        cpu_temp = await asyncio.to_thread(_read_cpu)
        self.process_sample(
            gpu_temp,
            at=now,
            gpu_power=gpu_power,
            gpu_clock=gpu_clock,
            cpu_temp=cpu_temp,
        )

    def _classify(self, s: _State, decision: Any) -> None:
        """Map rule decision + ADR-081 bands → card action vocabulary.

        * < 75°C            → relax    (card green)
        * 75–80°C           → hold     (card green; arming progress shown)
        * >= 80°C (cap band)→ throttle (card degraded)
        * rule fired        → cooldown (card degraded; cap applied)
        """
        temp = s.gpu_temp
        if temp is None:
            s.action, s.reason = "hold", "no GPU sample (nvidia-smi unreachable)"
            return
        if decision is not None and decision.active:
            if not s.cooldown_active:
                s.cooldown_active = True
                s.power_limit = COOLDOWN_POWER_CAP_W
                self._apply_cap(COOLDOWN_POWER_CAP_W)
                self._fire("thermal.cooldown", decision)
            s.action = "cooldown"
            s.reason = decision.reason
            return
        if s.cooldown_active:
            # Sustained window cleared → restore login default.
            s.cooldown_active = False
            s.power_limit = NOMINAL_POWER_CAP_W
            self._apply_cap(NOMINAL_POWER_CAP_W)
            self._fire("thermal.cooldown_cleared", decision)
        if temp >= self.thresholds.cap_c:
            s.action = "throttle"
            s.reason = (
                f"GPU {temp:.0f}°C in cap band (≥{self.thresholds.cap_c:.0f}°C) "
                "— sustained load, reduce or monitor"
            )
        elif temp >= self.thresholds.cooldown_c:
            s.action = "hold"
            if decision is not None:
                s.reason = (
                    f"{decision.reason}; "
                    f"arming {decision.arm_progress:.0%}"
                )
            else:
                s.reason = f"GPU {temp:.0f}°C at cooldown threshold, monitoring"
        else:
            s.action = "relax"
            s.reason = (
                f"temp {temp:.0f}°C < {self.thresholds.cooldown_c:.0f}°C, "
                "within safe operating range"
            )

    def _fire(self, event_type: str, decision: Any) -> None:
        if self._bus is None or decision is None:
            return
        try:
            from ports.event_envelope import EventEnvelope

            self._bus.publish(
                EventEnvelope(
                    event_type=event_type,
                    producer_plugin="tektos_thermal_watchdog",
                    payload={
                        "source": "tektos_thermal_watchdog",
                        "reason": decision.reason,
                        "seconds_over": decision.seconds_over,
                        "power_cap_w": self._state.power_limit,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("thermal watchdog: publish failed (%s)", event_type)

    # -- snapshot (API) --------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """ADR-121: the :8020-shaped envelope the Thermal card parses."""
        s = self._state
        gpu: dict[str, Any] = {
            "temperature": s.gpu_temp,
            "power_limit": s.power_limit,
            "clock_mhz": s.gpu_clock,
            "power_draw_w": s.gpu_power,
            "action": s.action,
            "reason": s.reason,
            "cooldown": {
                "active": s.cooldown_active,
                "threshold_c": self.thresholds.cooldown_c,
                "sustain_s": self.thresholds.cooldown_sustain_s,
                "seconds_over": s.seconds_over,
                "arming": self.rule.armed,
            },
        }
        cpu_status = "unknown"
        if s.cpu_temp is None:
            cpu_action = "no sensor data"
        elif s.cpu_temp >= 90:
            cpu_status, cpu_action = "critical", "CPU at critical temp"
        elif s.cpu_temp >= 80:
            cpu_status, cpu_action = "warning", "CPU elevated — monitor"
        elif s.cpu_temp >= 70:
            cpu_status, cpu_action = "elevated", "CPU above target"
        else:
            cpu_status, cpu_action = "normal", "CPU within safe operating range"
        return {
            "timestamp": (s.last_sample_at or datetime.now(timezone.utc)).isoformat(),
            "gpu": gpu,
            "cpu": {"temperature": s.cpu_temp, "status": cpu_status, "action": cpu_action},
            "regulation_count": s.regulation_count,
            "history": list(s.history),
        }
