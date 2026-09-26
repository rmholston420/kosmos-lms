"""ADR-141 Stage 13.1c — POST /api/schema/apply (donor main.py:3297).

The DDL-executing schema-evolution route: builds a SchemaProposal from the
body, validates against the current schema, and — only if valid — executes
the DDL through engine.apply_proposal (bumps schema version + logs a
rollback-bearing row to _schema_evolution_log). Engine referent =
registry.tektos_schema_evolution (T8c-9 verbatim port).

Documented divergences / known issues:
  * body `table` default "working" (donor "sessions" — tektos.db retired,
    ADR-137).
  * DONOR LATENT BUG (reproduced, NOT fixed — verbatim fidelity): the donor's
    default body (no `proposed_sql`) executes the literal string
    "ALTER TABLE placeholder" because
        proposed_sql=body.proposed_sql or "ALTER TABLE placeholder"
    is always truthy, so the donor's own fallback line
        if not proposal.proposed_sql: build real ALTER TABLE ...
    is DEAD CODE. Confirmed by driving the donor's own engine (tektos.db):
    validate→True, then conn.execute("ALTER TABLE placeholder") →
    sqlite3.OperationalError. Only an EXPLICIT `proposed_sql` works in the
    donor. This port reproduces that 1:1; the happy path therefore posts an
    explicit proposed_sql (the donor's only working path).

Mirrors the 13.1b harness: env at module import before kernel.app, then a
module-scoped TestClient (entered via `with` so the lifespan boot runs) with
the gate on + a tmp memory db, so the DDL applies to a throwaway file — never
the live data/memory.db.
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
    tmp = tmp_path_factory.mktemp("s131c")
    env = {
        "KOSMOS_TEKTOS_MEMORY": "on",
        "KOSMOS_MEMORY_DB_PATH": str(tmp / "memory.db"),
        "KOSMOS_MEMORY_DECAY_INTERVAL": "300",
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        client = TestClient(ka.app, raise_server_exceptions=False)
        with client:
            yield client
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ka.registry.tektos_schema_evolution = None


def _cols(engine, table):
    return {c.name for c in engine.introspect().tables[table].columns}


def test_apply_explicit_sql_adds_column_and_bumps_version(tc):
    """The donor's ONLY working path: caller supplies explicit proposed_sql."""
    engine = ka.registry.tektos_schema_evolution
    assert engine is not None, "engine must boot (KOSMOS_TEKTOS_MEMORY=on)"

    v_before = engine.get_current_version()
    assert "applied_col" not in _cols(engine, "long_term")

    r = tc.post("/api/schema/apply", json={
        "action": "add_column", "table": "long_term",
        "column": "applied_col", "column_type": "TEXT",
        "proposed_sql": "ALTER TABLE long_term ADD COLUMN applied_col TEXT",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True, body
    assert isinstance(body["version"], int)
    # DDL really executed + version bumped:
    assert "applied_col" in _cols(engine, "long_term")
    assert engine.get_current_version() > v_before


def test_apply_invalid_table_returns_failure(tc):
    r = tc.post("/api/schema/apply", json={
        "action": "add_column", "table": "no_such_table", "column": "x",
        "proposed_sql": "ALTER TABLE no_such_table ADD COLUMN x TEXT",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert any("does not exist" in e for e in body["errors"]), body


def test_apply_duplicate_column_rejected(tc):
    engine = ka.registry.tektos_schema_evolution
    # applied_col was added by the first test — re-adding must FAIL
    # validation, not re-execute DDL.
    r = tc.post("/api/schema/apply", json={
        "action": "add_column", "table": "long_term",
        "column": "applied_col", "column_type": "TEXT",
        "proposed_sql": "ALTER TABLE long_term ADD COLUMN applied_col TEXT",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert any("already exists" in e for e in body["errors"]), body


def test_apply_route_stores_no_rollback_sql_donor_behavior(tc):
    engine = ka.registry.tektos_schema_evolution
    # DONOR BEHAVIOR (verbatim): the apply route constructs SchemaProposal
    # directly, so rollback_sql stays "" (unlike engine.propose_from_pattern,
    # which DOES set it). rollback_last() therefore returns False —
    # "Cannot rollback ...: no rollback SQL stored". Locked in here so a
    # future "fix" is a conscious decision, not a silent drift.
    ok = engine.rollback_last()
    assert ok is False
    assert "applied_col" in _cols(engine, "long_term")


def test_apply_default_body_reproduces_donor_placeholder_bug(tc):
    """Locks in the donor's latent behavior (verbatim fidelity): a default
    body with NO proposed_sql hits the dead-fallback placeholder and 500s —
    exactly as the donor does. See module docstring + ADR-141."""
    r = tc.post("/api/schema/apply", json={
        "action": "add_column", "table": "working", "column": "z",
        "column_type": "TEXT",
    })
    # raise_server_exceptions=False → the OperationalError surfaces as 500.
    assert r.status_code == 500


def test_apply_503_when_engine_none(tc):
    saved = ka.registry.tektos_schema_evolution
    ka.registry.tektos_schema_evolution = None
    try:
        r = tc.post("/api/schema/apply", json={
            "action": "add_column", "table": "working", "column": "z",
            "proposed_sql": "ALTER TABLE working ADD COLUMN z TEXT",
        })
        assert r.status_code == 503
        assert "not initialized" in r.json()["error"]
    finally:
        ka.registry.tektos_schema_evolution = saved
