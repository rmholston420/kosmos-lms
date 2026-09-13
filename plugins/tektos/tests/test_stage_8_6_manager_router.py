"""Stage 8.6 · ADR-108 tests — :func:`build_manager_router`."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.tektos.manager import TektosManager
from plugins.tektos.manager.api import build_manager_router


def _client(engine: TektosManager | None) -> TestClient:
    app = FastAPI()
    app.include_router(build_manager_router(engine), prefix="/tektos/api/manager")
    return TestClient(app)


# ── Router shape ──────────────────────────────────────────────────────────


def test_router_has_all_seven_routes():
    router = build_manager_router(None)
    paths = {(tuple(sorted(r.methods)), r.path) for r in router.routes}
    assert (("POST",), "/task-start") in paths
    assert (("POST",), "/task-complete") in paths
    assert (("POST",), "/error") in paths
    assert (("POST",), "/spiral-update") in paths
    assert (("POST",), "/rhythm") in paths
    assert (("GET",), "/health") in paths
    assert (("GET",), "/recent") in paths


def test_router_tags_are_tektos_manager():
    router = build_manager_router(None)
    # APIRouter sets tags on the router; every route inherits them.
    for r in router.routes:
        assert "tektos.manager" in getattr(r, "tags", [])


# ── Unwired degrade (503) ─────────────────────────────────────────────────


def test_all_endpoints_return_503_when_engine_unwired():
    client = _client(None)
    # POST endpoints require some body — send minimal valid shape or empty.
    r = client.post(
        "/tektos/api/manager/task-start",
        json={"session_id": "s", "task_id": "t"},
    )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["detail"] == "ADR-108 degrade: manager not wired"
    assert detail["adr"] == "ADR-108"

    r = client.get("/tektos/api/manager/health")
    assert r.status_code == 503


# ── Wired paths ───────────────────────────────────────────────────────────


def test_task_start_returns_state_and_radius():
    client = _client(TektosManager())
    r = client.post(
        "/tektos/api/manager/task-start",
        json={"session_id": "s", "task_id": "t", "spec_id": "spec-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "active"
    assert body["spiral_radius"] == 1.0


def test_task_complete_transitions_to_idle():
    engine = TektosManager()
    client = _client(engine)
    r = client.post(
        "/tektos/api/manager/task-complete",
        json={
            "session_id": "s",
            "task_id": "t",
            "success": True,
            "tokens_used": 100,
            "tools_used": 5,
            "elapsed_seconds": 1.5,
        },
    )
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


def test_error_below_threshold_returns_null_feedback():
    client = _client(TektosManager(archetype_threshold=5))
    r = client.post(
        "/tektos/api/manager/error",
        json={
            "session_id": "s",
            "category": "rare_error",
            "description": "one-off",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"] is None
    assert body["narrative_id"] is None
    assert body["recovery_strategy"] == "skip"


def test_error_hits_threshold_returns_archetype_feedback():
    client = _client(TektosManager(archetype_threshold=2))
    for _ in range(2):
        r = client.post(
            "/tektos/api/manager/error",
            json={
                "session_id": "s",
                "category": "timeout_error",
                "description": "d",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"] is not None
    assert body["feedback"]["type"] == "archetype_recognized"
    assert body["recovery_strategy"] == "retry"


def test_spiral_update_expanding_returns_warning():
    client = _client(TektosManager())
    r = client.post(
        "/tektos/api/manager/spiral-update",
        json={
            "session_id": "s",
            "new_radius": 2.0,
            "description": "wider scope",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"] is not None
    assert body["feedback"]["type"] == "spiral_warning"
    assert body["spiral_radius"] == 2.0


def test_rhythm_endpoint_returns_feedback():
    client = _client(TektosManager())
    r = client.post(
        "/tektos/api/manager/rhythm",
        json={"session_id": "s", "rhythm_name": "daily", "description": "roll up"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"]["type"] == "rhythm_triggered"
    assert body["feedback"]["category"] == "rhythm.daily"


def test_health_endpoint_returns_snapshot():
    engine = TektosManager()
    client = _client(engine)
    r = client.get("/tektos/api/manager/health")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "idle"
    assert body["spiral_radius"] == 1.0
    assert body["feedback_total"] == 0
    assert body["active_archetypes"] == []


def test_recent_endpoint_returns_last_n_items():
    engine = TektosManager(archetype_threshold=1)
    client = _client(engine)
    for i in range(3):
        client.post(
            "/tektos/api/manager/error",
            json={"session_id": "s", "category": f"cat_{i}", "description": "d"},
        )
    r = client.get("/tektos/api/manager/recent?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["items"][-1]["category"] == "cat_2"
