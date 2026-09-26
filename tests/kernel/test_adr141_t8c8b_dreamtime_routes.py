"""ADR-141 T8c-8b — dreamtime routes (donor paths, donor shapes).

Donor referents (tektos-ultima-v1 main.py:2365-2425):
  GET  /api/dreamtime/summary  → engine.get_summary()
  GET  /api/dreamtime/history  → {"dreams": [DreamResult wire]}
  POST /api/dreamtime/run      → full contemplation cycle (body:
                                 max_memories=50, focus_area=None)

These ride ``registry.tektos_dreamtime`` — the donor DreamtimeEngine
(verbatim, T8c-8a) booted over the T6 3-tier store (same
KOSMOS_TEKTOS_MEMORY gate, same db). One module-scoped lifespan boot with
the gate on + a tmp db proves the real boot path (gate → store → engine)
end-to-end. The degraded shape ({"error": "Dreamtime engine not
initialized"}, 200 — the donor's own fail shape) is exercised by swapping
the registry slot to None.

The fourth donor route (trigger-skill-generation) is T8c-8c (needs a
skill-store referent).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import kernel.app as ka  # noqa: E402


@pytest.fixture(scope="module")
def tc(tmp_path_factory):
    """Real lifespan boot with the gate on + a tmp cognitive-memory db."""
    tmp = tmp_path_factory.mktemp("t8c8b")
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
        ka.registry.tektos_dreamtime = None


def _seed_long_term(content: str, what: str, hemisphere: str = "left"):
    store = ka.registry.tektos_memory_persistence
    assert store is not None, "memory persistence did not boot"
    store.save_long_term({
        "id": f"seed-{abs(hash(content)) % 10**8:08d}",
        "content": content,
        "hemisphere": hemisphere,
        "is_novel": False,
        "novelty_score": 0.0,
        "timestamp": "2026-09-26T00:00:00+00:00",
        "who": "", "what": what, "where": "", "when": "", "why": "", "how": "",
        "metadata": {},
    })


def test_boot_wires_dreamtime_engine_over_t6_store(tc):
    engine = ka.registry.tektos_dreamtime
    assert engine is not None, "tektos_dreamtime did not boot"
    from plugins.tektos.memory.dreamtime import DreamtimeEngine

    assert isinstance(engine, DreamtimeEngine)
    # The engine's store is the SAME object as the T6 store's adapter —
    # one store, two consumers (documented in the boot function).
    assert engine.memory._mem is ka.registry.tektos_memory_persistence


def test_summary_empty_engine_donor_shape(tc):
    r = tc.get("/api/dreamtime/summary")
    assert r.status_code == 200
    body = r.json()
    for key in ("state", "total_dreams", "total_insights", "recent_dreams"):
        assert key in body, f"summary missing donor key {key}: {body}"
    assert body["state"] == "idle"


def test_history_empty_donor_shape(tc):
    r = tc.get("/api/dreamtime/history")
    assert r.status_code == 200
    body = r.json()
    assert "dreams" in body
    assert isinstance(body["dreams"], list)


def test_run_full_cycle_donor_wire(tc):
    _seed_long_term("billing refactor unknown?", "billing refactor")
    _seed_long_term("billing rules right-brain", "billing rules", "right")
    _seed_long_term("emergent billing insight", "billing insight")

    r = tc.post("/api/dreamtime/run", json={"max_memories": 10})
    assert r.status_code == 200
    body = r.json()
    for key in ("id", "source_count", "insight_count", "is_novel",
                "novelty_score", "insights", "timestamp"):
        assert key in body, f"run missing donor key {key}: {body}"
    assert body["source_count"] >= 1
    assert body["insight_count"] >= 1
    assert isinstance(body["insights"], list) and body["insights"]

    # The cycle persisted back into the shared T6 store (insights →
    # long-term or procedural by novelty score).
    store = ka.registry.tektos_memory_persistence
    total = len(store.load_long_term(limit=1000)) + len(store.load_procedural(limit=1000))
    assert total >= 4, f"insights not persisted: {total} entries"

    # History now reflects the dream with the donor wire shape.
    h = tc.get("/api/dreamtime/history").json()
    assert len(h["dreams"]) == 1
    d = h["dreams"][0]
    assert d["id"] == body["id"]
    assert d["source_count"] == body["source_count"]
    assert d["insights"] == body["insights"]

    # Summary advanced.
    s = tc.get("/api/dreamtime/summary").json()
    assert s["total_dreams"] == 1
    assert s["total_insights"] >= 1


def test_run_focus_area_filters(tc):
    _seed_long_term("about cooking pasta", "cooking")
    r = tc.post("/api/dreamtime/run", json={
        "max_memories": 10, "focus_area": "cooking",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["source_count"] == 1


def test_degraded_shape_when_engine_absent(tc):
    saved = ka.registry.tektos_dreamtime
    ka.registry.tektos_dreamtime = None
    try:
        for method, path in (
            ("get", "/api/dreamtime/summary"),
            ("get", "/api/dreamtime/history"),
        ):
            r = getattr(tc, method)(path)
            assert r.status_code == 200
            assert r.json() == {"error": "Dreamtime engine not initialized"}
        r = tc.post("/api/dreamtime/run")
        assert r.status_code == 200
        assert r.json() == {"error": "Dreamtime engine not initialized"}
    finally:
        ka.registry.tektos_dreamtime = saved
