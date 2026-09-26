"""ADR-141 T6b — memory action routes (donor paths, donor shapes).

Donor referents (tektos-ultima-v1 main.py:2324-2349):
  POST   /api/memory/decay              → {"working": N, "long_term": 0,
                                           "procedural": 0}
  DELETE /api/memory/{tier}/{entry_id}  → {"deleted": bool} | 400 unknown
                                           tier | {"error": ...} degraded

The routes operate on ``registry.tektos_memory_persistence`` (the 3-tier
cognitive store, plugins/tektos/memory), NOT on ``registry.memory``
(DozerDB MemoryEvent graph — the ADR-135 referent).

One module-scoped lifespan boot with KOSMOS_TEKTOS_MEMORY=on + a tmp db
path proves the real boot path (gate, MemoryPersistence construction,
decay scheduler start) end-to-end. The degraded shape is exercised by
swapping the registry slot to None (restored in the test).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import kernel.app as ka  # noqa: E402


@pytest.fixture(scope="module")
def tc(tmp_path_factory):
    """Real lifespan boot with the gate on + a tmp cognitive-memory db."""
    tmp = tmp_path_factory.mktemp("t6b")
    env = {
        "KOSMOS_TEKTOS_MEMORY": "on",
        "KOSMOS_MEMORY_DB_PATH": str(tmp / "memory.db"),
        "KOSMOS_MEMORY_DECAY_INTERVAL": "300",
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        client = TestClient(ka.app)
        with client:
            yield client
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _store(tc: TestClient):
    store = ka.registry.tektos_memory_persistence
    assert store is not None, (
        "cognitive memory store not booted — "
        f"boot error: {ka.registry.errors.get('tektos_memory_persistence')!r}"
    )
    return store


def test_boot_wired(tc: TestClient) -> None:
    """The gate booted the real store with the scheduler running."""
    store = _store(tc)
    assert store.decay_thread is not None
    assert store.decay_thread.is_alive()


def test_decay_route_shape_and_effect(tc: TestClient) -> None:
    store = _store(tc)
    now = datetime.now(timezone.utc)
    store.save_working(
        {
            "id": "t6b-expired",
            "content": "expired working entry",
            "timestamp": now.isoformat(),
            "expires_at": (now - timedelta(hours=1)).isoformat(),
        }
    )
    store.save_working(
        {
            "id": "t6b-alive",
            "content": "alive working entry",
            "timestamp": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )

    r = tc.post("/api/memory/decay")
    assert r.status_code == 200
    body = r.json()
    # Donor shape: per-tier counts, long-term/procedural always 0.
    assert set(body) == {"working", "long_term", "procedural"}
    assert body["working"] >= 1
    assert body["long_term"] == 0
    assert body["procedural"] == 0

    ids = {row["id"] for row in store.load_all_working()}
    assert "t6b-expired" not in ids
    assert "t6b-alive" in ids
    # tidy up
    store.delete_working("t6b-alive")


def test_delete_route_roundtrip(tc: TestClient) -> None:
    store = _store(tc)
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    store.save_long_term({"id": "t6b-lt", "content": "x", "timestamp": ts})
    store.save_procedural({"id": "t6b-p", "content": "y", "timestamp": ts})

    r = tc.delete("/api/memory/long_term/t6b-lt")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    r = tc.delete("/api/memory/procedural/t6b-p")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    # absent id → donor shape: {"deleted": false} at 200
    r = tc.delete("/api/memory/long_term/t6b-lt")
    assert r.status_code == 200
    assert r.json() == {"deleted": False}


def test_delete_unknown_tier_400(tc: TestClient) -> None:
    r = tc.delete("/api/memory/bogus/whatever")
    assert r.status_code == 400
    assert "Unknown tier: bogus" in r.json()["detail"]


def test_degraded_shape_when_slot_none(tc: TestClient) -> None:
    original = ka.registry.tektos_memory_persistence
    ka.registry.tektos_memory_persistence = None
    try:
        # Donor's own fail shape, at 200 (ops tab renders it as n/a).
        r = tc.post("/api/memory/decay")
        assert r.status_code == 200
        assert r.json() == {"error": "Memory persistence not initialized"}

        r = tc.delete("/api/memory/working/xyz")
        assert r.status_code == 200
        assert r.json() == {"error": "Memory persistence not initialized"}
    finally:
        ka.registry.tektos_memory_persistence = original


def test_coexistence_with_adr135_read_routes(tc: TestClient) -> None:
    """GET /api/memory + /api/memory/stats (graph referent) still work
    alongside the new action routes."""
    r = tc.get("/api/memory")
    assert r.status_code == 200
    assert "entries" in r.json()

    r = tc.get("/api/memory/stats")
    assert r.status_code == 200
    assert "backend" in r.json()


def test_decay_is_idempotent_noop(tc: TestClient) -> None:
    r = tc.post("/api/memory/decay")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"working", "long_term", "procedural"}
    # prior tests cleaned up; a second immediate call must not count more
    r2 = tc.post("/api/memory/decay")
    assert r2.json()["working"] <= body["working"]
    assert r2.json()["long_term"] == 0
    assert r2.json()["procedural"] == 0
