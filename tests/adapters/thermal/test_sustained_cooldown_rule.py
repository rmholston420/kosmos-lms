"""ADR-121 — SustainedCooldownRule unit tests.

Pure sustained-temperature rule: fire when GPU >= threshold_c for
>= sustain_s continuously. Injected clock; no GPU needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from adapters.thermal.tektos.adapter import SustainedCooldownRule

_T0 = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return _T0 + timedelta(seconds=seconds)


def test_below_threshold_is_clear() -> None:
    rule = SustainedCooldownRule(threshold_c=75.0, sustain_s=60.0)
    d = rule.evaluate(70.0, at=_at(0))
    assert d.active is False
    assert d.arm_progress == 0.0
    assert d.seconds_over == 0.0
    assert not rule.armed


def test_sustains_over_window_then_fires() -> None:
    rule = SustainedCooldownRule(threshold_c=75.0, sustain_s=60.0)
    # t=0: 76°C — arming begins
    d0 = rule.evaluate(76.0, at=_at(0))
    assert d0.active is False
    assert rule.armed
    # t=30: still over, half window — arming, progress ~0.5
    d30 = rule.evaluate(78.0, at=_at(30))
    assert d30.active is False
    assert d30.arm_progress == pytest.approx(0.5)
    # t=60: full window elapsed — COOLDOWN active
    d60 = rule.evaluate(77.0, at=_at(60))
    assert d60.active is True
    assert d60.arm_progress == 1.0
    assert "cooldown required" in d60.reason


def test_one_second_over_is_not_enough() -> None:
    rule = SustainedCooldownRule(threshold_c=75.0, sustain_s=60.0)
    d = rule.evaluate(90.0, at=_at(1))
    assert d.active is False  # even a spike to 90 doesn't fire in 1 s


def test_drop_below_threshold_resets_clock() -> None:
    rule = SustainedCooldownRule(threshold_c=75.0, sustain_s=60.0)
    rule.evaluate(80.0, at=_at(0))    # arming
    rule.evaluate(80.0, at=_at(40))   # 40 s in
    rule.evaluate(60.0, at=_at(41))   # drops below → reset
    assert not rule.armed
    # Re-arm from zero: 40 s later still not active
    rule.evaluate(80.0, at=_at(42))
    d = rule.evaluate(80.0, at=_at(82))  # only 40 s of the NEW window
    assert d.active is False
    assert d.seconds_over == pytest.approx(40.0)


def test_exact_boundary_fires_at_sustain() -> None:
    rule = SustainedCooldownRule(threshold_c=75.0, sustain_s=60.0)
    rule.evaluate(75.0, at=_at(0))
    d = rule.evaluate(75.0, at=_at(60))
    assert d.active is True  # >= threshold, >= sustain window


def test_uses_injected_clock_when_no_at() -> None:
    now = _T0
    rule = SustainedCooldownRule(
        threshold_c=75.0, sustain_s=10.0, clock=lambda: now
    )
    rule.evaluate(80.0)  # t=0
    now = _T0 + timedelta(seconds=10)
    d = rule.evaluate(80.0)
    assert d.active is True
