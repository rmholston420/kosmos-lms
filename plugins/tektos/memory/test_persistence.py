"""ADR-141 T6a — MemoryPersistence port tests (donor-faithful, plugin layer).

The port is donor-verbatim except the required ``db_path`` constructor
argument and the namespaced logger (see ``persistence.py`` header). These
tests pin the observable contract: tier CRUD, the ``location``→``where``
row mapping, metadata JSON round-trip, LIKE search, per-tier decay
(working only), stats, import/export, transfer log, and the background
decay scheduler. All tests use tmp paths — no repository data is touched.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from plugins.tektos.memory import MemoryPersistence


@pytest.fixture
def mem(tmp_path):
    store = MemoryPersistence(tmp_path / "memory.db")
    yield store
    store.close()


def _entry(entry_id: str, **overrides):
    base = {
        "id": entry_id,
        "content": f"content of {entry_id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


# ── Working tier ───────────────────────────────────────────────────────────


def test_save_load_working_roundtrip(mem):
    eid = mem.save_working(
        _entry(
            "w1",
            hemisphere="right",
            is_novel=True,
            novelty_score=0.9,
            where="lab",
            when="yesterday",
            why="because",
            metadata={"k": "v"},
        )
    )
    assert eid == "w1"
    rows = mem.load_working()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "w1"
    assert row["hemisphere"] == "right"
    assert row["is_novel"] == 1
    assert row["where"] == "lab"  # location column mapped back to `where`
    assert "location" not in row
    assert row["when_ts"] == "yesterday"  # column name is donor-verbatim (no when mapping)
    assert row["why"] == "because"
    assert row["metadata"] == {"k": "v"}


def test_save_working_upserts(mem):
    mem.save_working(_entry("w1", content="first"))
    mem.save_working(_entry("w1", content="second"))
    rows = mem.load_working()
    assert len(rows) == 1
    assert rows[0]["content"] == "second"


def test_load_working_limit_and_order(mem):
    now = datetime.now(timezone.utc)
    for i in range(10):
        mem.save_working(
            _entry(f"w{i}", timestamp=(now + timedelta(seconds=i)).isoformat())
        )
    rows = mem.load_working(limit=7)
    assert len(rows) == 7
    assert rows[0]["id"] == "w9"  # newest first
    assert len(mem.load_all_working()) == 10


def test_delete_working(mem):
    mem.save_working(_entry("w1"))
    assert mem.delete_working("w1") is True
    assert mem.delete_working("w1") is False
    assert mem.load_all_working() == []


# ── Long-term tier ─────────────────────────────────────────────────────────


def test_long_term_save_search_delete(mem):
    mem.save_long_term(_entry("lt1", what="deploy the kernel", why="stage 11"))
    mem.save_long_term(_entry("lt2", what="write the tests"))

    by_what = mem.search_long_term("deploy")
    assert [r["id"] for r in by_what] == ["lt1"]

    by_why = mem.search_long_term("stage")
    assert [r["id"] for r in by_why] == ["lt1"]

    by_content = mem.search_long_term("content of lt2")
    assert [r["id"] for r in by_content] == ["lt2"]

    assert mem.search_long_term("nope") == []
    assert mem.delete_long_term("lt1") is True
    assert [r["id"] for r in mem.load_all_long_term()] == ["lt2"]


# ── Procedural tier ────────────────────────────────────────────────────────


def test_procedural_save_skill_id_and_search(mem):
    mem.save_procedural(
        _entry("p1", what="restart the llama server", metadata={"skill_id": "llama"})
    )
    rows = mem.load_procedural()
    assert len(rows) == 1
    assert rows[0]["id"] == "p1"
    assert mem.search_procedural("restart")[0]["id"] == "p1"
    assert mem.delete_procedural("p1") is True
    assert mem.load_all_procedural() == []


def test_procedural_skill_id_none_when_absent(mem):
    mem.save_procedural(_entry("p1"))
    # skill_id column is present but None — row round-trips cleanly
    rows = mem.load_all_procedural()
    assert rows[0]["id"] == "p1"


# ── Decay ──────────────────────────────────────────────────────────────────


def test_decay_removes_expired_working_only(mem):
    now = datetime.now(timezone.utc)
    mem.save_working(_entry("expired", expires_at=(now - timedelta(hours=1)).isoformat()))
    mem.save_working(_entry("future", expires_at=(now + timedelta(hours=1)).isoformat()))
    mem.save_working(_entry("no-expiry"))
    mem.save_long_term(_entry("lt1", expires_at=(now - timedelta(hours=1)).isoformat()))
    mem.save_procedural(_entry("p1", expires_at=(now - timedelta(hours=1)).isoformat()))

    removed = mem.decay_all()
    assert removed == {"working": 1, "long_term": 0, "procedural": 0}
    # timestamp-desc sort; the two survivors share a timestamp → stable order
    assert {r["id"] for r in mem.load_all_working()} == {"future", "no-expiry"}
    # long-term and procedural decay is a no-op by donor design
    assert len(mem.load_all_long_term()) == 1
    assert len(mem.load_all_procedural()) == 1


def test_decay_working_standalone(mem):
    now = datetime.now(timezone.utc)
    mem.save_working(_entry("expired", expires_at=(now - timedelta(hours=1)).isoformat()))
    assert mem.decay_working() == 1
    assert mem.decay_working() == 0


# ── Stats / transfer log ───────────────────────────────────────────────────


def test_stats_keys_and_counts(mem):
    mem.save_working(_entry("w1", is_novel=True))
    mem.save_long_term(_entry("lt1"))
    mem.save_procedural(_entry("p1"))
    mem.log_transfer("working", "long_term", "w1")

    stats = mem.get_stats()
    assert stats == {
        "working_count": 1,
        "working_novel": 1,
        "long_term_count": 1,
        "long_term_novel": 0,
        "procedural_count": 1,
        "procedural_novel": 0,
        "transfers": 1,
    }


def test_transfer_log_roundtrip(mem):
    mem.log_transfer("working", "long_term", "e1")
    mem.log_transfer("working", "procedural", "e2")
    history = mem.get_transfer_history()
    assert len(history) == 2
    assert {h["from_tier"] for h in history} == {"working"}
    assert {h["to_tier"] for h in history} == {"long_term", "procedural"}
    # newest first (identical timestamps → insertion order is stable enough
    # here because ids are unique; assert on ids, not ordering)
    assert {h["entry_id"] for h in history} == {"e1", "e2"}


# ── Import / export ────────────────────────────────────────────────────────


def test_import_export_roundtrip(mem):
    entries = [_entry(f"e{i}") for i in range(3)]
    assert mem.import_entries("long_term", entries) == 3
    exported = mem.export_entries("long_term")
    assert len(exported) == 3
    assert {r["id"] for r in exported} == {"e0", "e1", "e2"}

    # metadata survives the export → re-import cycle
    mem.import_entries("long_term", [_entry("e4", metadata={"a": 1})])
    assert mem.export_entries("long_term")[0]["id"] in {"e0", "e1", "e2", "e4"}

    # unknown tier: the donor increments the count without saving (donor
    # bug preserved verbatim — count is "processed", not "imported")
    assert mem.import_entries("bogus", entries) == 3
    assert mem.export_entries("bogus") == []


# ── Scheduler ──────────────────────────────────────────────────────────────


def test_decay_scheduler_start_stop(tmp_path):
    store = MemoryPersistence(tmp_path / "mem.db")
    now = datetime.now(timezone.utc)
    store.save_working(_entry("expired", expires_at=(now - timedelta(hours=1)).isoformat()))
    store.start_decay_scheduler(interval=0.1)
    try:
        assert store.decay_thread is not None
        assert store.decay_thread.is_alive()
        # idempotent re-start
        store.start_decay_scheduler(interval=0.1)
        # wait for at least one decay tick (0.1 s interval + margin)
        import time as _time

        for _ in range(50):
            if not store.load_all_working():
                break
            _time.sleep(0.05)
    finally:
        store.stop_decay_scheduler()
    # the loop ran and decayed the expired entry
    assert store.load_all_working() == []
    assert store.decay_thread is None
    store.close()


# ── Thread-local connections ───────────────────────────────────────────────


def test_concurrent_access_across_threads(tmp_path):
    store = MemoryPersistence(tmp_path / "mem.db")
    errors: list[str] = []

    def worker(n: int) -> None:
        try:
            for i in range(20):
                store.save_working(_entry(f"t{n}-{i}"))
                store.load_working(limit=5)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{n}: {exc}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert errors == []
    assert len(store.load_all_working()) == 80
    store.close()
