"""ADR-141 Stage 13.1b — POST /api/schema/propose (donor main.py:3265).

Dry-run schema-change proposal: build a SchemaProposal from a detected
pattern, validate against the current schema, return the proposed SQL
WITHOUT executing it (no DDL). Engine referent:
registry.tektos_schema_evolution (T8c-9 verbatim port). Documented
divergence: body `table` default "working" (donor "sessions" — tektos.db
retired, ADR-137). Wire shape donor-verbatim: {reason, proposed_sql,
valid, errors}.

Mirrors the T8c-8b / 13.1a harness: env set at module import before
kernel.app, then a module-scoped TestClient with the gate on + a tmp
memory db.
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
    tmp = tmp_path_factory.mktemp("s131b")
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


def test_propose_dry_run_valid_table(tc):
    """Proposing a new column on a REAL T6 table yields valid + SQL, and
    does NOT modify the schema (pure dry-run)."""
    r = tc.post("/api/schema/propose", json={
        "field_name": "priority",
        "table": "working",
        "pattern_type": "repeated_metadata",
        "suggested_type": "TEXT",
        "confidence": 0.8,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Donor wire shape (main.py:3288-3293)
    assert set(body) == {"reason", "proposed_sql", "valid", "errors"}
    assert body["valid"] is True
    assert body["errors"] == []
    assert "priority" in body["proposed_sql"]
    assert "working" in body["proposed_sql"]

    # Dry-run: the schema is unchanged — `priority` is NOT a column now.
    engine = ka.registry.tektos_schema_evolution
    cols = {c.name for c in engine.introspect().tables["working"].columns}
    assert "priority" not in cols, "propose must NOT apply DDL"


def test_propose_invalid_table_reports_error(tc):
    """Proposing on a non-existent table → valid:False + error message."""
    r = tc.post("/api/schema/propose", json={
        "field_name": "foo",
        "table": "__no_such_table__",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False
    assert any("does not exist" in e for e in body["errors"])


def test_propose_default_table_is_working(tc):
    """Documented divergence: donor defaulted table to "sessions"; the
    kernel default is the T6 store's "working"."""
    r = tc.post("/api/schema/propose", json={"field_name": "note"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "working" in body["proposed_sql"]
    assert body["valid"] is True


def test_propose_engine_none_degrades_503(tc):
    saved = ka.registry.tektos_schema_evolution
    ka.registry.tektos_schema_evolution = None
    try:
        r = tc.post("/api/schema/propose", json={"field_name": "x"})
        assert r.status_code == 503
        assert "not initialized" in r.json()["error"]
    finally:
        ka.registry.tektos_schema_evolution = saved
