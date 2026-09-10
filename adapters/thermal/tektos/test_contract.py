"""Contract test for TektosThermalAdapter (ADR-081, ADR-092)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from adapters.thermal.tektos.adapter import (
    ColossusThermalThresholds,
    TektosThermalAdapter,
    _level_from_temp,
)
from adapters.thermal.tektos.vendor.thermal_donor import (
    CPUTelemetry,
    GPUTelemetry,
    ThermalSnapshot,
)
from ports.event_envelope import EventEnvelope
from ports.thermal import ThermalPort


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return envelope.event_id


@dataclass
class _MemoryCall:
    subject: str
    predicate: str
    object: str
    provenance: str
    confidence: float
    attributes: dict


class _RecordingMemory:
    def __init__(self) -> None:
        self.writes: list[_MemoryCall] = []

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict | None = None,
    ) -> str:
        self.writes.append(
            _MemoryCall(
                subject=subject,
                predicate=predicate,
                object=object,
                provenance=provenance,
                confidence=confidence,
                attributes=attributes or {},
            )
        )
        return f"mem-{len(self.writes)}"


class _FakeCollector:
    """Injectable collector that returns a scripted GPU temperature."""

    def __init__(self, temp_c: float, power_w: float = 250.0, fan_pct: int | None = 45) -> None:
        self.temp_c = temp_c
        self.power_w = power_w
        self.fan_pct = fan_pct

    def collect(self) -> ThermalSnapshot:
        return ThermalSnapshot(
            gpu=GPUTelemetry(
                temperature_gpu=self.temp_c,
                power_draw=self.power_w,
                fan_speed=self.fan_pct,
            ),
            cpu=CPUTelemetry(),
        )


# ── Protocol conformance ─────────────────────────────────────────────────


def test_adapter_satisfies_thermal_port_protocol() -> None:
    adapter = TektosThermalAdapter(collector=_FakeCollector(25.0))
    assert isinstance(adapter, ThermalPort)


# ── ADR-081 level classification ─────────────────────────────────────────


@pytest.mark.parametrize(
    "temp,expected",
    [
        (25.0, "green"),
        (50.9, "green"),
        (51.0, "yellow"),
        (79.9, "yellow"),
        (80.0, "cap"),
        (87.9, "cap"),
        (88.0, "red"),
        (95.0, "red"),
    ],
)
def test_level_from_temp_matches_adr_081_bands(temp: float, expected: str) -> None:
    thresholds = ColossusThermalThresholds()
    assert _level_from_temp(temp, thresholds) == expected


# ── pressure() default before any sample ─────────────────────────────────


def test_pressure_defaults_to_green_before_any_sample() -> None:
    adapter = TektosThermalAdapter(collector=_FakeCollector(25.0))
    p = adapter.pressure()
    assert p.level == "green"
    assert p.gpu_temp_c == 0.0
    assert p.power_cap_w is None


# ── ADR-081 rule 1 + 2: threshold crossing publishes + red writes memory ─


@pytest.mark.asyncio
async def test_red_transition_publishes_and_writes_memory() -> None:
    bus = _RecordingBus()
    memory = _RecordingMemory()
    collector = _FakeCollector(temp_c=25.0)
    adapter = TektosThermalAdapter(
        event_bus=bus, memory=memory, collector=collector
    )
    # Start green → sample green (no transition envelope on same-level).
    await adapter.sample()
    assert adapter.pressure().level == "green"

    # Cross to yellow.
    collector.temp_c = 60.0
    await adapter.sample()
    assert adapter.pressure().level == "yellow"
    assert any(env.event_type == "thermal.yellow" for env in bus.published)

    # Cross to red.
    collector.temp_c = 90.0
    await adapter.sample()
    assert adapter.pressure().level == "red"
    assert any(env.event_type == "thermal.red" for env in bus.published)

    # Rule 2: red transition writes MemoryPort with provenance=thermal, conf=1.0.
    red_mem = [w for w in memory.writes if w.provenance == "thermal"]
    assert len(red_mem) == 1
    assert red_mem[0].confidence == 1.0
    assert "90" in red_mem[0].object


# ── Power cap idempotence (ADR-081 rule 4) ───────────────────────────────


@pytest.mark.asyncio
async def test_apply_power_cap_is_idempotent() -> None:
    bus = _RecordingBus()
    adapter = TektosThermalAdapter(event_bus=bus, collector=_FakeCollector(25.0))
    await adapter.apply_power_cap(400)
    await adapter.apply_power_cap(400)  # idempotent no-op
    applied = [env for env in bus.published if env.event_type == "thermal.power_cap.applied"]
    assert len(applied) == 1
    assert adapter.pressure().power_cap_w == 400


@pytest.mark.asyncio
async def test_release_power_cap_is_idempotent() -> None:
    bus = _RecordingBus()
    adapter = TektosThermalAdapter(event_bus=bus, collector=_FakeCollector(25.0))
    await adapter.release_power_cap()  # never applied → no-op
    await adapter.apply_power_cap(300)
    await adapter.release_power_cap()
    await adapter.release_power_cap()  # idempotent no-op
    released = [
        env for env in bus.published if env.event_type == "thermal.power_cap.released"
    ]
    assert len(released) == 1
    assert adapter.pressure().power_cap_w is None


# ── Health & close ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_flips_health() -> None:
    adapter = TektosThermalAdapter(collector=_FakeCollector(25.0))
    assert adapter.is_healthy() is True
    await adapter.close()
    await adapter.close()  # idempotent
    assert adapter.is_healthy() is False
    with pytest.raises(RuntimeError):
        await adapter.sample()


@pytest.mark.asyncio
async def test_pressure_never_raises_even_when_closed() -> None:
    adapter = TektosThermalAdapter(collector=_FakeCollector(25.0))
    await adapter.close()
    # ADR-081 rule 3: sync + non-throwing hot path.
    p = adapter.pressure()
    assert p.level in ("green", "yellow", "cap", "red")
