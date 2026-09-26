"""ADR-141 Stage 13.1a — GET /api/schema/patterns (donor main.py:3229).

Read-only column-pattern detection over the introspected T6 memory store.
Engine referent: registry.tektos_schema_evolution (T8c-9 verbatim port of
donor SchemaEvolutionEngine). Documented divergence: the donor defaulted
`table` to "sessions" (donor tektos.db event store, retired in ADR-137);
the kernel introspects the T6 store, whose default table is "working".

Wire shape is donor-verbatim: a BARE LIST of pattern dicts with keys
{field, table, percentage, confidence, suggested_type, pattern_type,
example_values} (main.py:3245-3255). Engine-absent degrades to the
donor's {error: "not initialized"} shape (503 in the kernel, since the
engine is env-gated with KOSMOS_TEKTOS_MEMORY).

Mirrors the T8c-8b harness: env set at module import before kernel.app,
then a module-scoped TestClient with the gate on + a tmp memory db.
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
    tmp = tmp_path_factory.mktemp("s131a")
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


def test_engine_boots_over_t6_store(tc):
    engine = ka.registry.tektos_schema_evolution
    assert engine is not None, "tektos_schema_evolution did not boot"
    # The engine introspects the SAME db as the T6 memory store.
    store = ka.registry.tektos_memory_persistence
    assert store is not None
    assert engine.db_path == store.db_path


def test_patterns_route_returns_bare_list(tc):
    r = tc.get("/api/schema/patterns")
    assert r.status_code == 200, r.text
    body = r.json()
    # Donor wire shape (main.py:3245): a bare list, not a wrapper dict.
    assert isinstance(body, list)


def test_patterns_item_keys_match_donor(tc):
    r = tc.get("/api/schema/patterns")
    body = r.json()
    assert isinstance(body, list)
    for item in body:
        assert set(item) == {
            "field",
            "table",
            "percentage",
            "confidence",
            "suggested_type",
            "pattern_type",
            "example_values",
        }


def test_patterns_default_table_is_working(tc):
    """Documented divergence: donor defaulted to "sessions"; kernel
    introspects the T6 memory store whose default table is "working"."""
    r = tc.get("/api/schema/patterns")
    assert r.status_code == 200
    body = r.json()
    for item in body:
        assert item["table"] == "working"


def test_patterns_explicit_table_top_k(tc):
    """Donor param is `top_k` (main.py:3230), and `table` is per-call."""
    r = tc.get("/api/schema/patterns?table=long_term&top_k=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) <= 2
    for item in body:
        assert item["table"] == "long_term"


def test_patterns_unknown_table_degrades(tc):
    """Donor's honest-degrade: unknown table → {error, table} 200 shape."""
    r = tc.get("/api/schema/patterns?table=__no_such_table__")
    assert r.status_code == 200
    body = r.json()
    # Either an empty list (no patterns) or the donor's {error, table}
    # degrade — both are donor-faithful outcomes.
    assert isinstance(body, (list, dict))
    if isinstance(body, dict):
        assert "table" in body


def test_patterns_engine_none_degrades_503(tc):
    """With the engine unbooted, the route degrades to 503 with the
    donor's honest 'not initialized' shape."""
    saved = ka.registry.tektos_schema_evolution
    ka.registry.tektos_schema_evolution = None
    try:
        r = tc.get("/api/schema/patterns")
        assert r.status_code == 503
        assert "not initialized" in r.json()["error"]
    finally:
        ka.registry.tektos_schema_evolution = saved
