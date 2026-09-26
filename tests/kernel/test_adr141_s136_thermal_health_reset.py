"""ADR-141 Stage 13.6 — /api/thermal/health + /api/thermal/reset.

Two donor routes (donor main.py:3122/3130) over the ADR-121
ThermalWatchdog — the kernel's thermal referent (same class as the
donor's ThermalMonitor; `registry.thermal_watchdog`). The watchdog
already serves /api/thermal/status (Stage 11.5); this adds the
donor's `get_health_score()` (donor monitor.py:174, pure temp bands)
and `reset()` (donor monitor.py:218, regulator → optimal) surface.

Gate-off (watchdog None) returns the donor-verbatim
`{"error": "Thermal monitor not initialized"}` at 200 (13.2e
convention).
"""

from __future__ import annotations

import kernel.app as ka
from fastapi.testclient import TestClient
import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(ka.app) as tc:
        yield tc


def test_thermal_health_route(client):
    """GET /api/thermal/health → 200, health_score float in [0, 1]."""
    r = client.get("/api/thermal/health")
    assert r.status_code == 200
    body = r.json()
    assert "health_score" in body
    score = body["health_score"]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_thermal_reset_route(client):
    """POST /api/thermal/reset → 200, status 'reset' + snapshot envelope."""
    r = client.post("/api/thermal/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reset"
    snap = body["snapshot"]
    assert "timestamp" in snap
    assert "gpu" in snap
    assert "regulation_count" in snap


def test_health_score_bands():
    """Unit: donor get_health_score temp bands verbatim (monitor.py:174)."""
    from kernel.tektos_thermal_watchdog import ThermalWatchdog

    wd = ThermalWatchdog(apply_cap=lambda _w: True)

    def score_for(temp: float | None) -> float:
        wd._state.gpu_temp = temp
        return wd.get_health_score()

    assert score_for(None) == 1.0   # no data — assume healthy
    assert score_for(0.0) == 1.0    # donor zero case
    assert score_for(59.9) == 1.0
    assert score_for(65.0) == 0.9
    assert score_for(71.0) == 0.8
    assert score_for(74.9) == 0.7
    assert score_for(79.9) == 0.5
    assert score_for(84.9) == 0.3
    assert score_for(90.0) == 0.1


def test_reset_clears_cooldown_and_restores_cap():
    """Unit: reset() clears cooldown window + restores nominal cap.

    Kernel-side equivalent of the donor's `regulator.reset()`:
    clears the SustainedCooldownRule at/above window and, when
    cooldown is active, restores NOMINAL_POWER_CAP_W via apply_cap.
    """
    from kernel.tektos_thermal_watchdog import (
        NOMINAL_POWER_CAP_W,
        ThermalWatchdog,
    )

    applied: list[int] = []
    wd = ThermalWatchdog(apply_cap=lambda w: applied.append(w) or True)

    # Simulate an active cooldown.
    wd.rule._over_since = wd.rule._clock()
    wd._state.cooldown_active = True
    wd._state.power_limit = 350
    wd._state.action = "cooldown"

    wd.reset()

    assert wd.rule._over_since is None          # rule window cleared
    assert wd._state.cooldown_active is False
    assert wd._state.power_limit == NOMINAL_POWER_CAP_W
    assert wd._state.action == "relax"
    assert applied == [NOMINAL_POWER_CAP_W]     # cap re-applied once


def test_reset_noop_when_not_in_cooldown():
    """Unit: reset() outside cooldown clears the rule but never touches the cap."""
    from kernel.tektos_thermal_watchdog import ThermalWatchdog

    applied: list[int] = []
    wd = ThermalWatchdog(apply_cap=lambda w: applied.append(w) or True)
    wd.rule._over_since = wd.rule._clock()
    wd._state.cooldown_active = False

    wd.reset()

    assert wd.rule._over_since is None
    assert applied == []                        # no cap write when not cooling
