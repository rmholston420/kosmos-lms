"""ADR-141 Stage 13.2b — /api/db/* READ routes (schema / sample / analyze).

Four donor GET routes (donor main.py:3414/3447/3459/3479) over the 13.2a
substrate (registry.tektos_db). NOTE: the donor's `GET /api/db` (stats) is
deliberately NOT re-added — that path is the kernel's ops lane-status surface
(ADR-137); the ADR-141 audit records it P there, and first-registered-wins
would make a duplicate dead shadow code.

Donor wires are verbatim; the one documented divergence is the referent:
donor used an ad-hoc DatabaseManager(db_path) for stats/schema and a
module-global for the rest — the kernel wires all to registry.tektos_db.
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
    tmp = tmp_path_factory.mktemp("s132b")
    os.environ["KOSMOS_TEKTOS_DB_PATH"] = str(tmp / "tektos.db")
    client = TestClient(ka.app)
    with client:
        mgr = ka.registry.tektos_db
        assert mgr is not None
        # Seed a deterministic table for the read routes to operate on.
        mgr.create_table(
            "probe_read",
            columns={"id": "INTEGER PRIMARY KEY", "val": "TEXT", "num": "INTEGER"},
        )
        for i in range(5):
            mgr.execute_dml(
                "INSERT INTO probe_read (val, num) VALUES (?, ?)", [f"v{i}", i]
            )
        yield client
    ka.registry.tektos_db = None
    os.environ.pop("KOSMOS_TEKTOS_DB_PATH", None)


def test_db_schema_route(tc):
    r = tc.get("/api/db/schema")
    assert r.status_code == 200
    body = r.json()
    assert "error" not in body
    tables = body["tables"]
    assert "probe_read" in tables
    t = tables["probe_read"]
    cols = {c["name"]: c for c in t["columns"]}
    assert cols["id"]["type"] == "INTEGER"
    assert cols["id"]["pk"] in (1, True)
    assert t["row_count"] == 5


def test_db_table_sample_route(tc):
    r = tc.get("/api/db/tables/probe_read/sample", params={"limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["table"] == "probe_read"
    assert body["count"] == 3
    assert len(body["data"]) == 3


def test_db_table_sample_bad_identifier_404(tc):
    # Donor: ValueError (from _safe_identifier) → 404, only for malformed
    # identifiers. "1bad" fails the [a-zA-Z_]^[a-zA-Z0-9_]{0,63}$ check.
    r = tc.get("/api/db/tables/1bad/sample")
    assert r.status_code == 404


def test_db_table_sample_missing_table_donor_500(tc):
    # DONOR BEHAVIOR (preserved 1:1): a well-formed but missing table name
    # raises sqlite3.OperationalError (no such table) inside the donor's
    # SELECT — the donor route only catches ValueError, so it is UNHANDLED
    # → 500 under a real server (confirmed live). TestClient re-raises
    # server exceptions by default, so we catch the same exception here.
    import sqlite3

    with pytest.raises(sqlite3.OperationalError):
        tc.get("/api/db/tables/does_not_exist/sample")


def test_db_table_analyze_route(tc):
    r = tc.get("/api/db/tables/probe_read/analyze")
    assert r.status_code == 200
    body = r.json()
    assert body["table"] == "probe_read"
    assert body["row_count"] == 5
    for key in ("column_stats", "missing_indexes", "suggestions", "data_quality_issues"):
        assert key in body


def test_db_table_analyze_unknown_404(tc):
    r = tc.get("/api/db/tables/does_not_exist/analyze")
    assert r.status_code == 404


def test_db_analyze_all_route(tc):
    r = tc.get("/api/db/analyze")
    assert r.status_code == 200
    body = r.json()
    assert "probe_read" in body
    assert body["probe_read"]["row_count"] == 5
    for key in ("suggestions", "data_quality_issues"):
        assert key in body["probe_read"]
