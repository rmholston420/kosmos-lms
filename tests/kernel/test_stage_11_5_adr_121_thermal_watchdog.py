"""ADR-121 — ThermalWatchdog tests (no GPU: faked reads + faked cap apply).

Verifies the sustained-cooldown decision path end-to-end:
* 75°C for <60s  → hold/arming, no cap change
* 75°C for ≥60s  → cooldown, 350W cap applied, event published
* drop below     → cooldown cleared, 400W restored
* nvidia-smi down → hold + reason, never raises, never fabricates
* snapshot() shape mirrors the :8020 envelope the card parses
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kernel.tektos_thermal_watchdog import (
    COOLDOWN_POWER_CAP_W,
    NOMINAL_POWER_CAP_W,
    ThermalWatchdog,
)

_T0 = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[str] = []

    def publish(self, envelope) -> str:
        self.events.append(envelope.event_type)
        return "ok"


def _wd(gpu_temp: float | None, *, bus: _FakeBus | None = None, applied: list | None = None):
    applied = applied if applied is not None else []
    return ThermalWatchdog(
        event_bus=bus,
        apply_cap=lambda w: (applied.append(w), True)[1],
    ), applied


def _drive(wd, temps: list[float | None]) -> None:
    """Feed samples through the real ``process_sample`` decision path.

    Uses a scripted 5 s clock (no waiting, no GPU) — the exact path the
    background loop runs, minus the I/O.
    """
    t = _T0
    for temp in temps:
        wd.process_sample(temp, at=t, gpu_power=400.0, gpu_clock=2400.0, cpu_temp=55.0)
        t += timedelta(seconds=5)


def test_stays_under_threshold_never_arms() -> None:
    wd, applied = _wd(60.0)
    _drive(wd, [60.0, 61.0, 59.0, 62.0])
    s = wd._state
    assert s.action == "relax"
    assert s.cooldown_active is False
    assert applied == []


def test_arms_under_60s_then_holds() -> None:
    wd, applied = _wd(78.0)
    _drive(wd, [78.0] * 10)  # 50s at >= 75 — under the 60s window
    s = wd._state
    assert s.action == "hold"
    assert s.cooldown_active is False
    assert applied == []
    assert wd.rule.armed is True


def test_sustains_60s_fires_cooldown_applies_cap() -> None:
    bus = _FakeBus()
    wd, applied = _wd(78.0, bus=bus)
    _drive(wd, [78.0] * 13)  # 60s+ at >= 75
    s = wd._state
    assert s.action == "cooldown"
    assert s.cooldown_active is True
    assert s.power_limit == COOLDOWN_POWER_CAP_W
    assert applied == [COOLDOWN_POWER_CAP_W]
    assert "thermal.cooldown" in bus.events
    assert "cooldown required" in s.reason


def test_cooldown_cleared_restores_nominal_cap() -> None:
    bus = _FakeBus()
    wd, applied = _wd(78.0, bus=bus)
    _drive(wd, [78.0] * 13)  # fire
    _drive(wd, [65.0])       # drops below → clear
    s = wd._state
    assert s.action == "relax"
    assert s.cooldown_active is False
    assert s.power_limit == NOMINAL_POWER_CAP_W
    assert applied == [COOLDOWN_POWER_CAP_W, NOMINAL_POWER_CAP_W]
    assert "thermal.cooldown_cleared" in bus.events


def test_burst_spikes_dont_fire() -> None:
    wd, applied = _wd(90.0)
    # Spike to 90 for 10s, drop, spike again — each burst < 60s.
    _drive(wd, [90.0, 90.0, 55.0, 55.0, 90.0, 90.0])
    s = wd._state
    assert s.cooldown_active is False
    assert applied == []


def test_gpu_unreadable_holds_without_fabricating() -> None:
    wd, _ = _wd(None)
    _drive(wd, [None, None, None])
    s = wd._state
    assert s.gpu_temp is None
    assert s.action == "hold"
    assert "no GPU sample" in s.reason


def test_snapshot_shape_matches_card_envelope() -> None:
    wd, _ = _wd(60.0)
    _drive(wd, [60.0, 58.0])
    snap = wd.snapshot()
    assert snap["gpu"]["temperature"] == 58.0
    assert snap["gpu"]["action"] == "relax"
    assert snap["gpu"]["reason"]
    assert snap["gpu"]["power_limit"] == NOMINAL_POWER_CAP_W
    assert snap["gpu"]["cooldown"]["threshold_c"] == 75.0
    assert snap["gpu"]["cooldown"]["sustain_s"] == 60.0
    assert snap["cpu"]["temperature"] == 55.0
    assert snap["cpu"]["status"] == "normal"
    assert isinstance(snap["regulation_count"], int)
    assert len(snap["history"]) == 2
    assert snap["history"][-1]["gpu_temp"] == 58.0


def test_sensor_gap_resets_arming_window() -> None:
    wd, applied = _wd(78.0)
    # Arm: 50s at >=75, then a failed read (None) must clear the window.
    _drive(wd, [78.0] * 10 + [None])
    assert wd.rule.armed is False
    # Even a long good reading afterwards starts a *fresh* window.
    _drive(wd, [78.0] * 11)  # 55s — still under 60s
    s = wd._state
    assert s.cooldown_active is False
    assert applied == []


def test_thresholds_come_from_adr_081_profile() -> None:
    wd, _ = _wd(60.0)
    assert wd.thresholds.cooldown_c == 75.0
    assert wd.thresholds.cooldown_sustain_s == 60.0
    assert wd.rule.threshold_c == 75.0
    assert wd.rule.sustain_s == 60.0
