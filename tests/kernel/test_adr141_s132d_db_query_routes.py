"""ADR-141 Stage 13.2d — /api/db/* query/DML/transaction/explain routes.

Four donor routes (donor main.py:3599–3655) + the two donor Pydantic
bodies (3365–3374) over the 13.2a substrate (registry.tektos_db).
Wires are donor-verbatim: gate-off → {"error": "Database manager not
initialized"} 200; ValueError → 400; other Exception → 500 (both
carried by the route's own try/except, so no TestClient re-raise).

DONOR BEHAVIORS preserved 1:1 (locked here):
- query: non-SELECT → 400 (donor ValueError); malformed SQL / missing
  table → 500 (donor unhandled sqlite3 error → route 500).
- dml: UPDATE/DELETE without WHERE + require_confirmation=True → 400;
  INSERT → {"rows_affected": n}.
- transaction: BARE BaseModel body (no schema) — **DONOR LATENT BUG
  preserved 1:1**: pydantic 2.13 refuses to instantiate bare BaseModel,
  so EVERY request 500s with "Pydantic models should inherit from
  BaseModel, BaseModel cannot be instantiated directly". Proven against
  the live donor at :8020 (same detail, same versions: fastapi 0.141.1 /
  pydantic 2.13.4) — the route is broken in BOTH environments. Same
  class as the 13.1c apply placeholder-SQL bug.
- explain: non-SELECT → 400; SELECT → {plan, estimated_rows,
  uses_index} (plan rows: id/parent/notused/detail).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ["KOSMOS_TEKTOS_DB"] = "on"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import kernel.app as ka  # noqa: E402


@pytest.fixture(scope="module")
def tc(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("s132d")
    os.environ["KOSMOS_TEKTOS_DB_PATH"] = str(tmp / "tektos.db")
    client = TestClient(ka.app)
    with client:
        mgr = ka.registry.tektos_db
        assert mgr is not None
        mgr.create_table(
            "probe_qdml",
            columns={"id": "INTEGER PRIMARY KEY", "name": "TEXT", "score": "INTEGER"},
        )
        for i in range(4):
            mgr.execute_dml(
                "INSERT INTO probe_qdml (name, score) VALUES (?, ?)",
                [f"n{i}", i],
            )
        yield client
    ka.registry.tektos_db = None
    os.environ.pop("KOSMOS_TEKTOS_DB_PATH", None)


def test_db_query_select(tc):
    r = tc.post("/api/db/query", json={"sql": "SELECT name, score FROM probe_qdml ORDER BY id", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == 2
    assert len(body["data"]) == 2
    assert body["data"][0]["name"] == "n0"


def test_db_query_non_select_400(tc):
    r = tc.post("/api/db/query", json={"sql": "DELETE FROM probe_qdml WHERE id=1"})
    assert r.status_code == 400
    assert "only allows SELECT" in r.json()["detail"]


def test_db_query_missing_table_500(tc):
    # Donor: unhandled sqlite3.OperationalError → route 500 (not 400).
    r = tc.post("/api/db/query", json={"sql": "SELECT * FROM does_not_exist"})
    assert r.status_code == 500
    assert "no such table" in r.json()["detail"]


def test_db_dml_insert(tc):
    r = tc.post("/api/db/dml", json={"sql": "INSERT INTO probe_qdml (name, score) VALUES (?, ?)", "params": ["x", 99]})
    assert r.status_code == 200
    assert r.json()["rows_affected"] == 1
    # cleanup
    tc.post("/api/db/dml", json={"sql": "DELETE FROM probe_qdml WHERE name='x'", "params": []})


def test_db_dml_update_without_where_400(tc):
    r = tc.post("/api/db/dml", json={"sql": "UPDATE probe_qdml SET score=0", "require_confirmation": True})
    assert r.status_code == 400
    assert "WHERE" in r.json()["detail"]


def test_db_dml_update_with_where(tc):
    r = tc.post("/api/db/dml", json={"sql": "UPDATE probe_qdml SET score=1 WHERE id=1", "require_confirmation": True})
    assert r.status_code == 200
    assert r.json()["rows_affected"] == 1


def test_db_transaction_donor_latent_bug_500(tc):
    # DONOR LATENT BUG (preserved 1:1, proven against live :8020): the
    # donor route takes a BARE BaseModel; pydantic 2.13 refuses to
    # instantiate it, so EVERY request — valid, empty, or malformed —
    # 500s with the identical detail. Same class as 13.1c's placeholder
    # SQL bug. The underlying db_manager.execute_transaction works
    # (covered by the 13.2a substrate smoke test); the route is what's
    # broken in both environments (fastapi 0.141.1 / pydantic 2.13.4).
    expected_detail = (
        "Pydantic models should inherit from BaseModel, BaseModel "
        "cannot be instantiated directly"
    )
    for payload in (
        {"statements": [{"sql": "SELECT 1", "params": []}]},
        {},
        {"statements": []},
    ):
        r = tc.post("/api/db/transaction", json=payload)
        assert r.status_code == 500, payload
        assert expected_detail in r.json()["detail"], payload


def test_db_explain_select(tc):
    r = tc.post("/api/db/explain", json={"sql": "SELECT * FROM probe_qdml WHERE id=1"})
    assert r.status_code == 200
    plan = r.json()
    assert isinstance(plan["plan"], list) and len(plan["plan"]) >= 1
    assert "estimated_rows" in plan
    assert "uses_index" in plan
    assert plan["plan"][0].keys() >= {"id", "parent", "notused", "detail"}


def test_db_explain_non_select_400(tc):
    r = tc.post("/api/db/explain", json={"sql": "UPDATE probe_qdml SET score=0 WHERE id=1"})
    assert r.status_code == 400
    assert "only works with SELECT" in r.json()["detail"]
