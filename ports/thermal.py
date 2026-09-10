"""ports.thermal — ThermalPort Protocol (ADR-081).

Formal Kosmos port for thermal telemetry + power capping. Locked at Stage 3.13.
First adapter (Tektos-Ultima donor: nvidia-smi + PID loop for RTX 5090
liquid-cooled) lands under ``adapters/thermal/tektos/``. ``NoOpThermalAdapter``
under ``adapters/thermal/noop/`` for CI.

Enforcement rules (per ADR-081 + spec §25.7):

1. Every threshold crossing (green ↔ yellow ↔ cap ↔ red) MUST publish
   ``thermal.<level>`` on ``EventBusPort``.
2. Every red-level transition MUST write a ``MemoryPort`` event with
   ``provenance="thermal"`` and ``confidence=1.0``.
3. ``pressure()`` is sync + non-throwing so hot-path callers (``LLMPort``
   adapters, ``ResourcePort``) can consult it without ``await``.
4. ``apply_power_cap()`` is idempotent; calling with the current cap is a no-op.

Colossus RTX 5090 thresholds (adapter-configured, not port-hardcoded):

| Threshold | Value | Action |
|---|---|---|
| Yellow | 51 °C | ``thermal.pressure`` envelope; ResourcePort back-pressure |
| Cap | 80 °C | 400 W GPU power cap engaged |
| Red | 88 °C | Emergency throttle; ``LLMPort`` refuses new inference |
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "ThermalLevel",
    "ThermalPort",
    "ThermalPressure",
    "ThermalSample",
]


ThermalLevel = Literal["green", "yellow", "cap", "red"]
"""Adapter-computed thermal level — see ADR-081."""


@dataclass(frozen=True, slots=True)
class ThermalSample:
    """One thermal telemetry sample. Immutable."""

    sampled_at: datetime
    gpu_temp_c: float
    power_w: float
    fan_pct: int | None = None


@dataclass(frozen=True, slots=True)
class ThermalPressure:
    """Cached pressure snapshot returned from ``pressure()``. Immutable.

    Reflects the last ``sample()`` result; callers on the hot path can consult
    this without awaiting a fresh sample.
    """

    level: ThermalLevel
    gpu_temp_c: float
    power_cap_w: int | None


@runtime_checkable
class ThermalPort(Protocol):
    """Formal Kosmos contract for thermal telemetry + power capping."""

    # ── Telemetry ─────────────────────────────────────────────────────────

    async def sample(self) -> ThermalSample:
        """Take a fresh telemetry sample. Backend-touching (``async``)."""
        ...

    def pressure(self) -> ThermalPressure:  # sync + non-throwing (hot path)
        """Return cached pressure snapshot.

        MUST NOT raise; if no sample has been taken yet, return
        ``ThermalPressure(level="green", gpu_temp_c=0.0, power_cap_w=None)``.
        """
        ...

    # ── Power capping ─────────────────────────────────────────────────────

    async def apply_power_cap(self, watts: int) -> None:
        """Engage a power cap. Idempotent — calling with the current cap
        is a no-op. Publishes ``thermal.power_cap.applied`` on transition.
        """
        ...

    async def release_power_cap(self) -> None:
        """Release any active power cap. Idempotent.
        Publishes ``thermal.power_cap.released`` on transition."""
        ...

    # ── Health & lifecycle ────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Return True iff the adapter can read telemetry. Non-throwing."""
        ...

    async def close(self) -> None:
        """Release adapter resources. Idempotent."""
        ...
