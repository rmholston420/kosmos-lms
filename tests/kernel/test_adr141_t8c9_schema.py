"""ADR-141 T8c-9 — GET /api/schema (donor path + wire, main.py:4747).

Composite referent:
  schema half        → registry.tektos_schema_evolution (donor
                       SchemaEvolutionEngine verbatim →
                       kernel/schema_evolution.py), booted over the T6
                       memory-store SQLite (donor's data/tektos.db
                       retired with main.py, ADR-137).
  self_improvement   → registry.tektos_learning (ADR-143 T3, same
                       method names get_experience / get_learning_metrics).

One module-scoped lifespan boot with KOSMOS_TEKTOS_MEMORY=on + a tmp db
proves the real boot path (gate → store → engine) end-to-end. The
degraded shape ({"error": "Schema evolution engine not initialized"}, 200
— the donor's own fail shape, main.py:4751) is exercised by swapping the
registry slot to None.
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
    tmp = tmp_path_factory.mktemp("t8c9")
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
        ka.registry.tektos_schema_evolution = None
        ka.registry.tektos_dreamtime = None


def test_boot_wires_schema_engine_over_t6_store(tc):
    engine = ka.registry.tektos_schema_evolution
    assert engine is not None, "tektos_schema_evolution did not boot"
    from kernel.schema_evolution import SchemaEvolutionEngine

    assert isinstance(engine, SchemaEvolutionEngine)
    # Same db file as the T6 store — one store, one introspector.
    store = ka.registry.tektos_memory_persistence
    assert str(engine.db_path) == str(store.db_path)


def test_schema_donor_wire_keys(tc):
    r = tc.get("/api/schema")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "version",
        "schema",
        "evolution_history",
        "introspection",
        "self_improvement",
    ):
        assert key in body, f"/api/schema missing donor key {key}: {list(body)}"
    assert isinstance(body["version"], int)
    assert isinstance(body["evolution_history"], list)


def test_schema_introspects_real_t6_tables(tc):
    body = tc.get("/api/schema").json()
    tables = set(body["schema"]["tables"].keys())
    # The 4 T6 store tables must be visible through the introspector
    # (plus the engine's own _schema_evolution_log).
    for expected in ("working", "long_term", "procedural", "transfer_log"):
        assert expected in tables, f"T6 table {expected} not introspected: {tables}"
    # Introspection half carries the SchemaSnapshot metadata (donor wire:
    # metadata.introspected_at / db_path).
    snap = body["introspection"]
    assert "tables" in snap and "metadata" in snap
    assert "introspected_at" in snap["metadata"]


def test_schema_self_improvement_half(tc):
    body = tc.get("/api/schema").json()
    si = body["self_improvement"]
    for key in (
        "experiences_tracked",
        "total_tasks",
        "total_improvements",
        "learning_velocity",
        "best_model",
    ):
        assert key in si, f"self_improvement missing donor key {key}: {si}"
    # Learning substrate may be env-gated off — then the honest zero shape.
    if ka.registry.tektos_learning is None:
        assert si == {
            "experiences_tracked": 0,
            "total_tasks": 0,
            "total_improvements": 0,
            "learning_velocity": 0.0,
            "best_model": None,
        }
    else:
        assert isinstance(si["experiences_tracked"], int)


def test_degraded_shape_when_engine_absent(tc):
    saved = ka.registry.tektos_schema_evolution
    ka.registry.tektos_schema_evolution = None
    try:
        r = tc.get("/api/schema")
        assert r.status_code == 200
        assert r.json() == {"error": "Schema evolution engine not initialized"}
    finally:
        ka.registry.tektos_schema_evolution = saved
