"""ADR-141 Stage 13.2e — /api/db/* export/import/backup/restore/optimization.

Six donor routes (donor main.py:3656–3754) + the four donor Pydantic
bodies (3377–3399) over the 13.2a substrate (registry.tektos_db).
Wires are donor-verbatim: gate-off → {"error": "Database manager not
initialized"} 200; donor ValueError → 400; restore FileNotFoundError
→ 400; other Exception → 500.

DONOR BEHAVIORS preserved 1:1 (locked here):
- export: returns {"exported": true, path, format}; writes file to the
  CWD-relative default path when body.path omitted (test passes an
  explicit tmp path; donor ValueError surface for empty/malformed tables
  is via the internal execute_query — missing table → 500 like 13.2d).
- import: {"imported": true, rows: n}; unsupported format → 400
  (donor ValueError); missing input file → FileNotFoundError → 500
  (donor route only catches ValueError — donor-verbatim, preserved).
- backup: {"backup": true, path, size_bytes, tables, rows, checksum};
  writes into <db>/backups/.
- restore: missing backup → 400 (FileNotFoundError); happy path →
  {"restored": true, path}.
- GET /api/db/backups: {"backups": [...]} (empty list before any
  backup in the test db).
- optimize: {"vacuum", "analyze", tables_analyzed, total_rows,
  suggestions, normalization_issues, relationships_detected,
  health_score, evolution_suggestions}.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ["KOSMOS_TEKTOS_DB"] = "on"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import kernel.app as ka  # noqa: E402


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("s132e")
    db_path = tmp / "tektos.db"
    os.environ["KOSMOS_TEKTOS_DB_PATH"] = str(db_path)
    client = TestClient(ka.app)
    with client:
        mgr = ka.registry.tektos_db
        assert mgr is not None
        mgr.create_table(
            "probe_eio",
            columns={"id": "INTEGER PRIMARY KEY", "name": "TEXT", "score": "INTEGER"},
        )
        for i in range(3):
            mgr.execute_dml(
                "INSERT INTO probe_eio (name, score) VALUES (?, ?)",
                [f"e{i}", i],
            )
        yield {"client": client, "tmp": tmp, "db_path": db_path}
    ka.registry.tektos_db = None
    os.environ.pop("KOSMOS_TEKTOS_DB_PATH", None)


def test_db_export_json(env):
    out = env["tmp"] / "exported.json"
    r = env["client"].post(
        "/api/db/export",
        json={"table_name": "probe_eio", "format": "json", "path": str(out)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exported"] is True
    assert body["format"] == "json"
    assert body["path"] == str(out)
    data = json.loads(out.read_text())
    assert len(data) == 3
    assert data[0]["name"] == "e0"


def test_db_export_csv(env):
    out = env["tmp"] / "exported.csv"
    r = env["client"].post(
        "/api/db/export",
        json={"table_name": "probe_eio", "format": "csv", "path": str(out)},
    )
    assert r.status_code == 200
    assert r.json()["exported"] is True
    lines = out.read_text().strip().splitlines()
    assert lines[0] == "id,name,score"
    assert len(lines) == 4  # header + 3 rows


def test_db_export_sql(env):
    out = env["tmp"] / "exported.sql"
    r = env["client"].post(
        "/api/db/export",
        json={"table_name": "probe_eio", "format": "sql", "path": str(out)},
    )
    assert r.status_code == 200
    content = out.read_text()
    assert "INSERT" in content


def test_db_export_missing_table_donor_500(env):
    # DONOR VERBATIM (preserved 1:1): export's internal SELECT hits an
    # unhandled sqlite3.OperationalError for a missing table — the route
    # only catches ValueError, so real uvicorn → 500 (TestClient re-raises).
    # Same class as the 13.2b missing-table sample 500; live-confirmed on :8000.
    import sqlite3

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        env["client"].post(
            "/api/db/export",
            json={"table_name": "does_not_exist", "format": "json", "path": str(env["tmp"] / "x.json")},
        )


def test_db_import_json(env):
    src = env["tmp"] / "import_src.json"
    src.write_text(json.dumps([{"id": 10, "name": "im0", "score": 100}, {"id": 11, "name": "im1", "score": 101}]))
    r = env["client"].post(
        "/api/db/import",
        json={"table_name": "probe_eio", "format": "json", "path": str(src)},
    )
    assert r.status_code == 200
    assert r.json() == {"imported": True, "rows": 2}
    # verify rows landed
    q = env["client"].post("/api/db/query", json={"sql": "SELECT COUNT(*) AS c FROM probe_eio", "limit": 1})
    assert q.json()["data"][0]["c"] == 5
    # cleanup: restore to 3 rows
    env["client"].post("/api/db/dml", json={"sql": "DELETE FROM probe_eio WHERE id >= 10", "require_confirmation": True})


def test_db_import_bad_format_400(env):
    src = env["tmp"] / "bad.txt"
    src.write_text("anything")
    r = env["client"].post(
        "/api/db/import",
        json={"table_name": "probe_eio", "format": "xml", "path": str(src)},
    )
    assert r.status_code == 400
    assert "Unsupported format" in r.json()["detail"]


def test_db_import_missing_file_donor_500(env):
    # DONOR VERBATIM (preserved 1:1): route catches only ValueError; the
    # FileNotFoundError from Path(path).read_text() is unhandled → 500
    # on real uvicorn (TestClient re-raises). Same class as 13.2b/13.2d
    # donor-500 locks; live-confirmed on :8000.
    with pytest.raises(FileNotFoundError):
        env["client"].post(
            "/api/db/import",
            json={"table_name": "probe_eio", "format": "json", "path": str(env["tmp"] / "nope.json")},
        )


def test_db_backup_and_list(env):
    r = env["client"].post("/api/db/backup", json={"compress": False})
    assert r.status_code == 200
    body = r.json()
    assert body["backup"] is True
    assert body["size_bytes"] > 0
    assert body["tables"] == 1  # only probe_eio exists yet
    # DONOR QUERK preserved 1:1: the route's `rows` field comes from a
    # cartesian-join SQL (sqlite_master × table list, no per-table
    # COUNT) → equals len(sqlite_master) × table_count, NOT the real row
    # total (1 for a 1-table db even with 3 rows). Byte-identical to
    # donor db_manager.py:820; reproduced standalone.
    assert body["rows"] == 1
    assert body["checksum"]
    assert os.path.exists(body["path"])

    # list_backups now includes it
    r2 = env["client"].get("/api/db/backups")
    assert r2.status_code == 200
    names = [b["path"] for b in r2.json()["backups"]]
    assert body["path"] in names


def test_db_backup_missing_backups_dir_shape(env):
    # list_backups always returns {"backups": [...]} — shape locked.
    r = env["client"].get("/api/db/backups")
    assert r.status_code == 200
    assert isinstance(r.json()["backups"], list)


def test_db_restore_missing_400(env):
    r = env["client"].post("/api/db/restore", json={"backup_path": str(env["tmp"] / "no_backup.db"), "verify": True})
    assert r.status_code == 400
    assert "Backup not found" in r.json()["detail"]


def test_db_restore_roundtrip(env):
    # backup → delete a row → restore → row is back
    client = env["client"]
    b = client.post("/api/db/backup", json={}).json()
    client.post("/api/db/dml", json={"sql": "DELETE FROM probe_eio WHERE id=1", "require_confirmation": True})
    q = client.post("/api/db/query", json={"sql": "SELECT COUNT(*) AS c FROM probe_eio", "limit": 1})
    before = q.json()["data"][0]["c"]
    r = client.post("/api/db/restore", json={"backup_path": b["path"], "verify": True})
    assert r.status_code == 200
    assert r.json() == {"restored": True, "path": b["path"]}
    q2 = client.post("/api/db/query", json={"sql": "SELECT COUNT(*) AS c FROM probe_eio", "limit": 1})
    after = q2.json()["data"][0]["c"]
    assert after > before  # restored row came back


def test_db_optimize(env):
    r = env["client"].post("/api/db/optimize", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["vacuum"] == "completed"
    assert body["analyze"] == "completed"
    assert body["tables_analyzed"] >= 1
    assert body["total_rows"] >= 3
    assert "health_score" in body
    assert "normalization_issues" in body
    assert "relationships_detected" in body
    assert "evolution_suggestions" in body
    assert "suggestions" in body


def test_db_gate_off_503(env):
    # Gate-off → donor-verbatim 200 {"error": ...} (matches 13.2b/c/d).
    # NOTE: FastAPI validates body models BEFORE the route runs, so the
    # bodies must be minimally valid — the gate check is what fires.
    ka.registry.tektos_db = None
    # (method, path, body) — POSTs with no required body send body=None;
    # the gate check runs after FastAPI validation.
    calls = (
        ("POST", "/api/db/export", {"table_name": "probe_eio"}),
        ("POST", "/api/db/import", {"table_name": "probe_eio", "path": str(env["tmp"] / "x.json")}),
        ("POST", "/api/db/backup", {}),
        ("POST", "/api/db/restore", {"backup_path": str(env["tmp"] / "x.db")}),
        ("GET", "/api/db/backups", None),
        ("POST", "/api/db/optimize", None),
    )
    try:
        for method, path_, body in calls:
            r = env["client"].request(method, path_, json=body)
            assert r.status_code == 200, (path_, r.status_code)
            assert r.json() == {"error": "Database manager not initialized"}, path_
    finally:
        # re-wire for any later tests
        from kernel.db_manager import DatabaseManager
        ka.registry.tektos_db = DatabaseManager(str(env["db_path"]))
