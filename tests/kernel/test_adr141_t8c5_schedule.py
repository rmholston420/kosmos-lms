"""T8c-5 — donor GET /api/schedule → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:5266.

Donor defect (T8c-2 class, documented): the donor built a FRESH
``BackupScheduler()`` per request — its in-memory ``backup_records``
starts ``[]``, so the route always returned ``[]``. The kernel referent
scans the REAL on-disk backup dir (``KOSMOS_BACKUP_DIR``, default
``~/.tektos/backups``) for the donor's own
``{postgresql,redis,sqlite,neo4j}_{ts}.{ext}`` artifacts.

Wire preserved: ``[{id, name, type, status, last_run, next_run,
interval, enabled}]``, newest first; ``[]`` on failure (donor degrade,
never an HTTP error).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kernel import app as kapp


@pytest.fixture()
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # seed a realistic donor backup dir
    for name, delay in [
        ("postgresql_20260901_010000.sql.gz", 3),
        ("redis_20260902_020000.rdb", 2),
        ("sqlite_20260903_030000.db", 1),
        ("notes.txt", 0),  # not a backup artifact — must be ignored
    ]:
        f = tmp_path / name
        f.write_bytes(b"x")
        ts = time.time() - delay
        os.utime(f, (ts, ts))
    monkeypatch.setenv("KOSMOS_BACKUP_DIR", str(tmp_path))
    client = TestClient(kapp.app)
    return client, tmp_path


def test_schedule_donor_wire_shape(harness):
    client, _ = harness
    r = client.get("/api/schedule")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 3  # notes.txt excluded
    for k in ("id", "name", "type", "status", "last_run", "next_run",
              "interval", "enabled"):
        assert k in rows[0], f"missing donor key {k}"
    by_type = {row["type"]: row for row in rows}
    assert set(by_type) == {"postgresql", "redis", "sqlite"}
    assert by_type["postgresql"]["status"] == "completed"
    assert by_type["postgresql"]["interval"] == "daily"
    assert by_type["postgresql"]["enabled"] is True
    assert by_type["postgresql"]["name"] == "postgresql_20260901_010000.sql.gz"


def test_schedule_newest_first(harness):
    client, _ = harness
    rows = client.get("/api/schedule").json()
    # mtimes: postgresql oldest → sqlite newest
    assert rows[0]["type"] == "sqlite"
    assert rows[-1]["type"] == "postgresql"


def test_schedule_missing_dir_empty_list(harness, tmp_path, monkeypatch):
    client, _ = harness
    monkeypatch.setenv("KOSMOS_BACKUP_DIR", str(tmp_path / "nope"))
    r = client.get("/api/schedule")
    assert r.status_code == 200
    assert r.json() == []


def test_schedule_unreadable_dir_degrades_empty(harness, monkeypatch):
    # donor degrade: any failure → [] at 200, never an HTTP error
    client, _ = harness
    monkeypatch.setenv("KOSMOS_BACKUP_DIR", str(Path.home() / "x" / "y" / "z"))
    r = client.get("/api/schedule")
    assert r.status_code == 200
    assert r.json() == []
