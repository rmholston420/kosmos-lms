"""ADR-141 Stage 13.2c — /api/db/* DDL routes (tables / columns / indexes).

Eight donor routes (donor main.py:3495–3597) + the four donor Pydantic
bodies (3335–3363) over the 13.2a substrate (registry.tektos_db).
Wires are donor-verbatim: gate-off → {"error": "Database manager not
initialized"} 200; ValueError → 400 with the donor's {"detail": ...}.

DONOR BEHAVIORS preserved 1:1 (locked here):
- create_table: bad table name → 400; existing table (if_not_exists=True
  donor default) → {"created": false} 200.
- drop_table: missing table → {"dropped": false} 200 (if_exists=True);
  malformed identifier ALSO → {"dropped": false} 200 (existence check
  runs before _safe_identifier — the 400 path is unreachable, locked).
- add_column: existing column → {"added": false} 200.
- drop_column: missing column → {"dropped": false} 200.
- rename_table / rename_column: missing source table → 400 ValueError.
- create_index: bad table identifier → 400; existing index →
  {"created": false} 200.
- drop_index: missing index → {"dropped": false} 200.
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
    tmp = tmp_path_factory.mktemp("s132c")
    os.environ["KOSMOS_TEKTOS_DB_PATH"] = str(tmp / "tektos.db")
    client = TestClient(ka.app)
    with client:
        mgr = ka.registry.tektos_db
        assert mgr is not None
        # Deterministic probe table for the DDL routes.
        mgr.create_table(
            "probe_ddl",
            columns={"id": "INTEGER PRIMARY KEY", "v": "TEXT", "num": "INTEGER"},
        )
        yield client
    ka.registry.tektos_db = None
    os.environ.pop("KOSMOS_TEKTOS_DB_PATH", None)


def test_db_create_table(tc):
    r = tc.post(
        "/api/db/tables",
        json={"table_name": "t132c_a", "columns": {"id": "INTEGER", "name": "TEXT"}, "primary_key": "id"},
    )
    assert r.status_code == 200
    assert r.json() == {"created": True, "table": "t132c_a"}
    # Donor: if_not_exists=True default → existing table → created False, 200.
    r2 = tc.post("/api/db/tables", json={"table_name": "t132c_a", "columns": {"id": "INTEGER"}})
    assert r2.status_code == 200
    assert r2.json()["created"] is False
    tc.delete("/api/db/tables/t132c_a")


def test_db_create_table_bad_name_400(tc):
    r = tc.post("/api/db/tables", json={"table_name": "1bad", "columns": {"id": "INTEGER"}})
    assert r.status_code == 400
    assert "Invalid table name" in r.json()["detail"]


def test_db_drop_table(tc):
    r = tc.delete("/api/db/tables/probe_ddl")
    assert r.status_code == 200
    assert r.json() == {"dropped": True, "table": "probe_ddl"}
    # Recreate for the later tests.
    tc.post(
        "/api/db/tables",
        json={"table_name": "probe_ddl", "columns": {"id": "INTEGER", "v": "TEXT", "num": "INTEGER"}, "primary_key": "id"},
    )
    # Donor: missing table (if_exists=True) → dropped False, 200.
    r2 = tc.delete("/api/db/tables/t132c_missing")
    assert r2.status_code == 200
    assert r2.json()["dropped"] is False


def test_db_drop_table_bad_identifier_donor_200(tc):
    # DONOR BEHAVIOR (preserved 1:1): drop_table's existence check runs
    # BEFORE _safe_identifier, so a malformed name never matches →
    # {"dropped": false} 200. The 400 path is unreachable for drop_table.
    r = tc.delete("/api/db/tables/1bad")
    assert r.status_code == 200
    assert r.json() == {"dropped": False, "table": "1bad"}


def test_db_add_column(tc):
    r = tc.post(
        "/api/db/tables/probe_ddl/columns",
        json={"table_name": "probe_ddl", "column_name": "extra", "column_type": "REAL", "default": 0.0, "notnull": False},
    )
    assert r.status_code == 200
    assert r.json() == {"added": True, "table": "probe_ddl", "column": "extra"}
    # Donor: existing column → added False, 200.
    r2 = tc.post(
        "/api/db/tables/probe_ddl/columns",
        json={"table_name": "probe_ddl", "column_name": "extra", "column_type": "REAL"},
    )
    assert r2.status_code == 200
    assert r2.json()["added"] is False


def test_db_drop_column(tc):
    r = tc.delete("/api/db/tables/probe_ddl/columns/extra")
    assert r.status_code == 200
    assert r.json() == {"dropped": True, "table": "probe_ddl", "column": "extra"}
    # Donor: missing column → dropped False, 200.
    r2 = tc.delete("/api/db/tables/probe_ddl/columns/nope")
    assert r2.status_code == 200
    assert r2.json()["dropped"] is False


def test_db_rename_table(tc):
    tc.post("/api/db/tables", json={"table_name": "t132c_r", "columns": {"id": "INTEGER"}})
    r = tc.patch("/api/db/tables/t132c_r/rename", json={"new_name": "t132c_r2"})
    assert r.status_code == 200
    assert r.json() == {"renamed": True, "old": "t132c_r", "new": "t132c_r2"}
    # Donor: missing source table → 400 ValueError.
    r2 = tc.patch("/api/db/tables/t132c_missing/rename", json={"new_name": "t132c_x"})
    assert r2.status_code == 400
    assert "does not exist" in r2.json()["detail"]
    tc.delete("/api/db/tables/t132c_r2")


def test_db_rename_column(tc):
    r = tc.patch("/api/db/tables/probe_ddl/columns/v/rename", json={"new_name": "v2"})
    assert r.status_code == 200
    assert r.json() == {"renamed": True, "old": "v", "new": "v2"}
    # Rename back so later tests see the original schema.
    r2 = tc.patch("/api/db/tables/probe_ddl/columns/v2/rename", json={"new_name": "v"})
    assert r2.status_code == 200
    assert r2.json()["renamed"] is True
    # Donor: missing source table → 400 ValueError.
    r3 = tc.patch("/api/db/tables/t132c_missing/columns/v/rename", json={"new_name": "x"})
    assert r3.status_code == 400


def test_db_create_index(tc):
    r = tc.post(
        "/api/db/indexes",
        json={"index_name": "idx_t132c", "table_name": "probe_ddl", "columns": ["v"], "unique": False},
    )
    assert r.status_code == 200
    assert r.json() == {"created": True, "index": "idx_t132c"}
    # Donor: existing index → created False, 200.
    r2 = tc.post("/api/db/indexes", json={"index_name": "idx_t132c", "table_name": "probe_ddl", "columns": ["v"]})
    assert r2.status_code == 200
    assert r2.json()["created"] is False
    # Donor: bad table identifier → 400 ValueError.
    r3 = tc.post("/api/db/indexes", json={"index_name": "idx_bad", "table_name": "1bad", "columns": ["v"]})
    assert r3.status_code == 400
    tc.delete("/api/db/indexes/idx_t132c")


def test_db_drop_index(tc):
    tc.post("/api/db/indexes", json={"index_name": "idx_t132c_gone", "table_name": "probe_ddl", "columns": ["v"]})
    r = tc.delete("/api/db/indexes/idx_t132c_gone")
    assert r.status_code == 200
    assert r.json() == {"dropped": True, "index": "idx_t132c_gone"}
    # Donor: missing index → dropped False, 200.
    r2 = tc.delete("/api/db/indexes/idx_t132c_missing")
    assert r2.status_code == 200
    assert r2.json()["dropped"] is False
