"""ADR-141 Stage 13.7 — metabolism substrate port + 4 routes.

Donor `tektos/metabolism.py` (572 LOC, stdlib-only) → `kernel/metabolism.py`
byte-verbatim (governing layering rule: generic resource-monitoring
substrate → kernel; it carries no Tektos-specific data). Four donor
routes (main.py:2961/2970/2978/4432) over `registry.tektos_metabolism`,
booted at the composition root with a 3-arg→envelope publish adapter
(ADR-007; substrate stays verbatim).

Gate-off (engine None) → donor-verbatim
`{"error": "Metabolism engine not initialized"}` at 200 (13.2e
convention) — the `/api/context/status` route instead returns
`{"status": "not_initialized"}` (donor main.py:4458).
"""

from __future__ import annotations

import kernel.app as ka
from fastapi.testclient import TestClient
import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(ka.app) as tc:
        yield tc


def test_metabolism_full_assessment(client):
    """GET /api/metabolism → 200, donor MetabolismState envelope."""
    r = client.get("/api/metabolism")
    assert r.status_code == 200
    body = r.json()
    for key in ("timestamp", "overall_health", "gpu", "system", "context_budget"):
        assert key in body, key
    assert body["overall_health"] in ("normal", "warning", "critical", "emergency")
    assert body["gpu"]["vram_total_mb"] > 0  # real nvidia-smi read on Collosus
    assert body["system"]["memory_total_mb"] > 0
    assert body["context_budget"]["max_tokens"] == 262144


def test_metabolism_context_stats(client):
    """GET /api/metabolism/context → 200, donor get_stats() fields."""
    r = client.get("/api/metabolism/context")
    assert r.status_code == 200
    body = r.json()
    for key in ("max_tokens", "current_tokens", "token_pct", "tool_calls", "sessions", "metrics_history_count"):
        assert key in body, key
    assert body["max_tokens"] == 262144


def test_metabolism_history(client):
    """GET /api/metabolism/history → 200, list; each assess_health()
    call (this test's own /api/metabolism probe) appends a snapshot to
    the engine's bounded history (metabolism.py:536-539)."""
    client.get("/api/metabolism")  # guarantee ≥1 history entry
    r = client.get("/api/metabolism/history", params={"limit": 100})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert "overall_health" in body[0]


def test_context_status_active(client):
    """GET /api/context/status → 200, status active (engine booted)."""
    r = client.get("/api/context/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert body["overall_health"] in ("normal", "warning", "critical", "emergency")
    assert body["context_budget"] is not None
    assert body["context_budget"]["remaining_tokens"] > 0


# ── Substrate unit tests (pure logic, GPU-free) ─────────────────────────


def test_context_budget_bands_verbatim():
    """Donor ContextBudget alert/action bands (metabolism.py:183-211)."""
    from kernel.metabolism import ContextAction, ContextBudget, ResourceAlert

    def band(tokens: int):
        b = ContextBudget(max_tokens=100, current_tokens=tokens)
        return b.alert_level, b.recommended_action

    assert band(79) == (ResourceAlert.NORMAL, ContextAction.NONE)
    assert band(80) == (ResourceAlert.WARNING, ContextAction.TRIM)
    assert band(89) == (ResourceAlert.WARNING, ContextAction.TRIM)
    assert band(90) == (ResourceAlert.CRITICAL, ContextAction.COMPRESS)
    assert band(94) == (ResourceAlert.CRITICAL, ContextAction.COMPRESS)
    assert band(95) == (ResourceAlert.EMERGENCY, ContextAction.REJECT)


def test_engine_without_bus_stays_verbatim():
    """Donor engine with event_bus=None: no publish, counters + history
    still accumulate (metabolism.py:545-571 lifecycle surface)."""
    from kernel.metabolism import MetabolismEngine

    eng = MetabolismEngine(event_bus=None, max_tokens=262144)
    eng.record_tool_call()
    eng.update_session_count(3)
    eng.record_tokens(1234)
    stats = eng.get_stats()
    assert stats["tool_calls"] == 1
    assert stats["sessions"] == 3
    assert stats["current_tokens"] == 1234

    budget = eng.update_context_budget(300000)  # > max → EMERGENCY, no bus to publish to
    assert budget.alert_level.value == "emergency"
    assert budget.recommended_action.value == "reject_new_prompt"
