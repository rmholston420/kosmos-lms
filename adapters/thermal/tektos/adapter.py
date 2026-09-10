"""adapters.thermal.tektos — TektosThermalAdapter.

Reference implementation of ``ports.thermal.ThermalPort`` wrapping the
vendored donor ``MetricsCollector`` (ADR-092 §2).

Responsibilities:

* ``sample()`` — runs the vendored blocking NVML/psutil collector in a
  worker thread via ``asyncio.to_thread`` and returns a normalised
  ``ThermalSample``. Caches the last successful sample.
* ``pressure()`` — sync + non-throwing (ADR-081 rule 3). Returns the
  ``ThermalPressure`` computed from the last cached sample using the
  ADR-081 Colossus RTX 5090 thresholds. If no sample has been taken
  returns the port's documented default
  (``level="green"``, temp 0.0, cap None).
* ``apply_power_cap`` / ``release_power_cap`` — idempotent state
  transitions that publish envelopes and update the cached pressure's
  ``power_cap_w`` value. **Stubbed** per ADR-092 §4 — they do NOT shell
  out to ``nvidia-smi``. Real capping lands with the full
  ``ThermalRegulator`` port-in later.
* Threshold crossings (green ↔ yellow ↔ cap ↔ red) publish
  ``thermal.<level>`` on the injected ``EventBusPort``. Red-level
  transitions additionally write a ``MemoryPort`` event with
  ``provenance="thermal"``, ``confidence=1.0`` (ADR-081 rule 2).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ports.event_envelope import EventEnvelope
from ports.thermal import ThermalLevel, ThermalPressure, ThermalSample

from .vendor.thermal_donor import MetricsCollector, ThermalSnapshot

logger = logging.getLogger(__name__)

__all__ = ["TektosThermalAdapter", "ColossusThermalThresholds"]


# ── Port dependency Protocols ────────────────────────────────────────────


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class _MemoryLike(Protocol):
    async def write_event(  # pragma: no cover
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict | None = None,
    ) -> str: ...


# ── Threshold config (ADR-081 §"Colossus RTX 5090") ──────────────────────


@dataclass(frozen=True, slots=True)
class ColossusThermalThresholds:
    """Thresholds for the ADR-081 four-level classifier. Immutable.

    Defaults match the Colossus RTX 5090 liquid-cooled profile in
    ADR-081. Callers may override for other hardware.
    """

    yellow_c: float = 51.0
    cap_c: float = 80.0
    red_c: float = 88.0
    default_power_cap_w: int = 400


class _NoOpCollector:
    """Fallback used when NVML is unavailable (CI Cloud sandbox).

    ``MetricsCollector.collect()`` returns zero-filled telemetry when the
    donor can't reach NVML/psutil; this class is only wired if the donor
    itself raises at import time.
    """

    @staticmethod
    def collect() -> ThermalSnapshot:
        # Re-use the donor's real dataclasses so downstream typing is honest.
        from .vendor.thermal_donor import (
            CPUTelemetry,
            GPUTelemetry,
            ThermalSnapshot as _TS,
        )

        return _TS(gpu=GPUTelemetry(), cpu=CPUTelemetry())


def _level_from_temp(
    temp_c: float, thresholds: ColossusThermalThresholds
) -> ThermalLevel:
    """Classify a temperature into one of the four ADR-081 levels.

    ADR-081 bands (ascending):
    * green: below yellow_c
    * yellow: [yellow_c, cap_c)
    * cap:    [cap_c, red_c)
    * red:    >= red_c
    """
    if temp_c >= thresholds.red_c:
        return "red"
    if temp_c >= thresholds.cap_c:
        return "cap"
    if temp_c >= thresholds.yellow_c:
        return "yellow"
    return "green"


class TektosThermalAdapter:
    """ThermalPort adapter wrapping the vendored MetricsCollector."""

    def __init__(
        self,
        *,
        thresholds: ColossusThermalThresholds | None = None,
        event_bus: _EventBusLike | None = None,
        memory: _MemoryLike | None = None,
        collector=None,
    ) -> None:
        self._thresholds = thresholds or ColossusThermalThresholds()
        self._event_bus = event_bus
        self._memory = memory
        # Injectable for tests; falls back to donor MetricsCollector.
        self._collector = collector or MetricsCollector()
        self._closed = False
        self._last_pressure: ThermalPressure = ThermalPressure(
            level="green",
            gpu_temp_c=0.0,
            power_cap_w=None,
        )
        self._active_cap_w: int | None = None

    async def sample(self) -> ThermalSample:
        if self._closed:
            raise RuntimeError("TektosThermalAdapter is closed.")
        try:
            snapshot: ThermalSnapshot = await asyncio.to_thread(self._collector.collect)
        except Exception:  # noqa: BLE001
            logger.exception("thermal collector raised; falling back to no-op sample")
            snapshot = _NoOpCollector.collect()

        sample = ThermalSample(
            sampled_at=datetime.now(timezone.utc),
            gpu_temp_c=float(snapshot.gpu.temperature_gpu or 0.0),
            power_w=float(snapshot.gpu.power_draw or 0.0),
            fan_pct=(
                int(snapshot.gpu.fan_speed)
                if snapshot.gpu.fan_speed is not None
                else None
            ),
        )
        await self._update_pressure(sample)
        return sample

    def pressure(self) -> ThermalPressure:
        # ADR-081 rule 3 — MUST NOT raise. Return current cached snapshot.
        try:
            return self._last_pressure
        except Exception:  # noqa: BLE001 — defensive
            return ThermalPressure(level="green", gpu_temp_c=0.0, power_cap_w=None)

    async def apply_power_cap(self, watts: int) -> None:
        if self._closed:
            raise RuntimeError("TektosThermalAdapter is closed.")
        if watts <= 0:
            raise ValueError("power cap must be > 0")
        if self._active_cap_w == watts:
            return  # idempotent
        self._active_cap_w = watts
        self._last_pressure = ThermalPressure(
            level=self._last_pressure.level,
            gpu_temp_c=self._last_pressure.gpu_temp_c,
            power_cap_w=watts,
        )
        await self._publish("thermal.power_cap.applied", {"watts": watts})

    async def release_power_cap(self) -> None:
        if self._closed:
            raise RuntimeError("TektosThermalAdapter is closed.")
        if self._active_cap_w is None:
            return  # idempotent
        prev = self._active_cap_w
        self._active_cap_w = None
        self._last_pressure = ThermalPressure(
            level=self._last_pressure.level,
            gpu_temp_c=self._last_pressure.gpu_temp_c,
            power_cap_w=None,
        )
        await self._publish("thermal.power_cap.released", {"previous_watts": prev})

    def is_healthy(self) -> bool:
        try:
            return not self._closed
        except Exception:  # noqa: BLE001 — ADR-023 rule 5
            return False

    async def close(self) -> None:
        self._closed = True

    # ── Internal ──────────────────────────────────────────────────────

    async def _update_pressure(self, sample: ThermalSample) -> None:
        new_level = _level_from_temp(sample.gpu_temp_c, self._thresholds)
        old = self._last_pressure
        self._last_pressure = ThermalPressure(
            level=new_level,
            gpu_temp_c=sample.gpu_temp_c,
            power_cap_w=self._active_cap_w,
        )
        if new_level != old.level:
            await self._publish(
                f"thermal.{new_level}",
                {
                    "gpu_temp_c": sample.gpu_temp_c,
                    "previous_level": old.level,
                    "power_cap_w": self._active_cap_w,
                },
            )
            if new_level == "red":
                await self._record_red_memory(sample)

    async def _publish(self, event_type: str, extra: dict) -> None:
        if self._event_bus is None:
            return
        try:
            envelope = EventEnvelope(
                event_type=event_type,
                producer_plugin="tektos_thermal_adapter",
                payload={"source": "tektos_thermal", **extra},
            )
            await self._event_bus.publish(envelope)
        except Exception:  # noqa: BLE001
            logger.exception("thermal publish failed (event_type=%s)", event_type)

    async def _record_red_memory(self, sample: ThermalSample) -> None:
        if self._memory is None:
            return
        try:
            await self._memory.write_event(
                subject="thermal:gpu",
                predicate="crossed_red_at",
                object=f"{sample.gpu_temp_c:.1f}C",
                provenance="thermal",
                confidence=1.0,
                attributes={
                    "power_w": sample.power_w,
                    "power_cap_w": self._active_cap_w,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("thermal red memory write failed")
