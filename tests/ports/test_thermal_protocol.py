"""Protocol conformance test for ThermalPort (ADR-081).

Any adapter satisfying ``ThermalPort`` MUST pass this test. Fast tier —
no live nvidia-smi. Uses a stub adapter with a settable temperature so we
exercise the Protocol shape.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ports.thermal import (
    ThermalPort,
    ThermalPressure,
    ThermalSample,
)


class _StubThermalAdapter:
    """Minimal ThermalPort implementation used only for protocol tests."""

    def __init__(self, temp_c: float = 40.0) -> None:
        self._temp = temp_c
        self._power_cap: int | None = None
        self._closed = False
        self._last_sample: ThermalSample | None = None

    def set_temp(self, temp_c: float) -> None:
        self._temp = temp_c

    async def sample(self) -> ThermalSample:
        s = ThermalSample(
            sampled_at=datetime.now(timezone.utc),
            gpu_temp_c=self._temp,
            power_w=200.0,
            fan_pct=45,
        )
        self._last_sample = s
        return s

    def pressure(self) -> ThermalPressure:  # sync + non-throwing
        try:
            if self._last_sample is None:
                return ThermalPressure(level="green", gpu_temp_c=0.0, power_cap_w=None)
            t = self._last_sample.gpu_temp_c
            if t >= 88.0:
                level = "red"
            elif t >= 80.0:
                level = "cap"
            elif t >= 51.0:
                level = "yellow"
            else:
                level = "green"
            return ThermalPressure(level=level, gpu_temp_c=t, power_cap_w=self._power_cap)
        except Exception:  # pragma: no cover — pressure MUST NOT raise
            return ThermalPressure(level="green", gpu_temp_c=0.0, power_cap_w=None)

    async def apply_power_cap(self, watts: int) -> None:
        self._power_cap = watts  # idempotent by value

    async def release_power_cap(self) -> None:
        self._power_cap = None  # idempotent

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True


def test_stub_adapter_satisfies_protocol_runtime_checkable() -> None:
    assert isinstance(_StubThermalAdapter(), ThermalPort)


def test_pressure_before_first_sample_is_green() -> None:
    adapter = _StubThermalAdapter()
    p = adapter.pressure()
    assert p.level == "green"
    assert p.gpu_temp_c == 0.0
    assert p.power_cap_w is None


def test_pressure_reflects_last_sample_thresholds() -> None:
    adapter = _StubThermalAdapter(temp_c=40.0)

    async def _run() -> str:
        await adapter.sample()
        return adapter.pressure().level

    assert asyncio.run(_run()) == "green"

    adapter.set_temp(60.0)
    asyncio.run(adapter.sample())
    assert adapter.pressure().level == "yellow"

    adapter.set_temp(82.0)
    asyncio.run(adapter.sample())
    assert adapter.pressure().level == "cap"

    adapter.set_temp(90.0)
    asyncio.run(adapter.sample())
    assert adapter.pressure().level == "red"


def test_pressure_is_sync_non_throwing() -> None:
    # ADR-081 rule 3 (mirrors ADR-023 rule 5): pressure() MUST NOT raise.
    adapter = _StubThermalAdapter()
    # Never awaited a sample; still safe.
    assert adapter.pressure().level == "green"


def test_apply_and_release_power_cap_reflected_in_pressure() -> None:
    adapter = _StubThermalAdapter(temp_c=82.0)

    async def _run() -> tuple[int | None, int | None]:
        await adapter.sample()
        await adapter.apply_power_cap(400)
        capped = adapter.pressure().power_cap_w
        await adapter.release_power_cap()
        await adapter.apply_power_cap(400)  # idempotent — no error
        await adapter.release_power_cap()
        await adapter.release_power_cap()  # idempotent
        released = adapter.pressure().power_cap_w
        return capped, released

    capped, released = asyncio.run(_run())
    assert capped == 400
    assert released is None


def test_is_healthy_never_raises() -> None:
    adapter = _StubThermalAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False


def test_close_is_idempotent() -> None:
    adapter = _StubThermalAdapter()

    async def _run() -> None:
        await adapter.close()
        await adapter.close()

    asyncio.run(_run())
