"""Tektos cognitive memory — 3-tier SQLite persistence (ADR-141 T6a).

Donor-faithful port of Tektos-Ultima's `MemoryPersistence`
(`src/tektos/memory/persistence.py`, 526 LOC) — the working / long_term /
procedural tier store with transfer log, per-tier decay, and the background
decay scheduler.

Layering (ADR-135 user decision, 2026-09-25): the 4-tier store is **Tektos
cognitive policy**, NOT neutral kernel substrate — the kernel's
`registry.memory` is a MemoryEvent graph (no tiers, no decay value
function). It therefore lives in the plugin layer; `kernel/app.py` boots
it in the composition root and owns the two action routes (ADR-141 T6).

Divergences from the donor (documented, all deliberate):
- `db_path` is a **required** constructor argument. The donor fell back to
  `Path(__file__).parents[3] / "data" / "memory.db"` — a path that depends
  on the file's location in the donor's `src/tektos/memory/` tree. The
  composition root passes the explicit location; tests pass tmp paths.
- `log` namespaced `kosmos.plugins.tektos.memory.persistence`.
- Everything else (schema, thread-local connections, WAL pragmas, save /
  load / search / delete / decay / stats / import-export, `_row_to_dict`
  `location`→`where` mapping, scheduler start/stop) is donor-verbatim.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("kosmos.plugins.tektos.memory.persistence")

# ── SQL Schema (donor-verbatim) ────────────────────────────────────────────

CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS working (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    hemisphere TEXT NOT NULL DEFAULT 'left',
    is_novel INTEGER NOT NULL DEFAULT 0,
    novelty_score REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL,
    expires_at TEXT,
    source_tier TEXT,
    destination_tier TEXT,
    who TEXT DEFAULT '',
    what TEXT DEFAULT '',
    location TEXT DEFAULT '',
    when_ts TEXT,
    why TEXT DEFAULT '',
    how TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS long_term (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    hemisphere TEXT NOT NULL DEFAULT 'left',
    is_novel INTEGER NOT NULL DEFAULT 0,
    novelty_score REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL,
    expires_at TEXT,
    source_tier TEXT,
    destination_tier TEXT,
    who TEXT DEFAULT '',
    what TEXT DEFAULT '',
    location TEXT DEFAULT '',
    when_ts TEXT,
    why TEXT DEFAULT '',
    how TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS procedural (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    hemisphere TEXT NOT NULL DEFAULT 'left',
    is_novel INTEGER NOT NULL DEFAULT 0,
    novelty_score REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL,
    expires_at TEXT,
    source_tier TEXT,
    destination_tier TEXT,
    who TEXT DEFAULT '',
    what TEXT DEFAULT '',
    location TEXT DEFAULT '',
    when_ts TEXT,
    why TEXT DEFAULT '',
    how TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    skill_id TEXT
);

CREATE TABLE IF NOT EXISTS transfer_log (
    id TEXT PRIMARY KEY,
    from_tier TEXT NOT NULL,
    to_tier TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_working_expires ON working(expires_at);
CREATE INDEX IF NOT EXISTS idx_long_term_what ON long_term(what);
CREATE INDEX IF NOT EXISTS idx_procedural_what ON procedural(what);
CREATE INDEX IF NOT EXISTS idx_long_term_timestamp ON long_term(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_procedural_timestamp ON procedural(timestamp DESC);
"""

# ── MemoryPersistence ──────────────────────────────────────────────────────


class MemoryPersistence:
    """SQLite-backed persistence for working, long-term, and procedural memory tiers.

    Attributes:
        db_path: Path to the SQLite database file.
        decay_thread: Background thread for periodic decay.
        decay_interval: Seconds between decay cycles (default 60).
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self.decay_thread: threading.Thread | None = None
        self.decay_interval: float = 60.0
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local SQLite connection for thread safety."""
        # Use threading.local() to ensure each thread has its own connection
        if not hasattr(self, "_thread_local"):
            self._thread_local = threading.local()
        conn = getattr(self._thread_local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._thread_local.conn = conn
        return conn

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._cursor() as cursor:
            for stmt in CREATE_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cursor.execute(stmt)

    # ── Working Memory ───────────────────────────────────────────────────

    def save_working(self, entry: dict[str, Any]) -> str:
        """Save a memory entry to the working tier."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO working
                       (id, content, hemisphere, is_novel, novelty_score,
                        timestamp, expires_at, source_tier, destination_tier,
                        who, what, location, when_ts, why, how, metadata, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["id"],
                    entry["content"],
                    entry.get("hemisphere", "left"),
                    1 if entry.get("is_novel") else 0,
                    entry.get("novelty_score", 0.0),
                    entry["timestamp"],
                    entry.get("expires_at"),
                    entry.get("source_tier"),
                    entry.get("destination_tier"),
                    entry.get("who", ""),
                    entry.get("what", ""),
                    entry.get("where", ""),
                    entry.get("when", ""),
                    entry.get("why", ""),
                    entry.get("how", ""),
                    json.dumps(entry.get("metadata", {})),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return entry["id"]

    def load_working(self, limit: int = 7) -> list[dict[str, Any]]:
        """Load working memory entries."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM working ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def load_all_working(self) -> list[dict[str, Any]]:
        """Load all working memory entries."""
        with self._lock, self._cursor() as cursor:
            cursor.execute("SELECT * FROM working ORDER BY timestamp DESC")
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def delete_working(self, entry_id: str) -> bool:
        """Delete a working memory entry. Returns True if deleted."""
        with self._lock, self._cursor() as cursor:
            cursor.execute("DELETE FROM working WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    # ── Long-Term Memory ─────────────────────────────────────────────────

    def save_long_term(self, entry: dict[str, Any]) -> str:
        """Save a memory entry to the long-term tier."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO long_term
                       (id, content, hemisphere, is_novel, novelty_score,
                        timestamp, expires_at, source_tier, destination_tier,
                        who, what, location, when_ts, why, how, metadata, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["id"],
                    entry["content"],
                    entry.get("hemisphere", "left"),
                    1 if entry.get("is_novel") else 0,
                    entry.get("novelty_score", 0.0),
                    entry["timestamp"],
                    entry.get("expires_at"),
                    entry.get("source_tier"),
                    entry.get("destination_tier"),
                    entry.get("who", ""),
                    entry.get("what", ""),
                    entry.get("where", ""),
                    entry.get("when", ""),
                    entry.get("why", ""),
                    entry.get("how", ""),
                    json.dumps(entry.get("metadata", {})),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return entry["id"]

    def load_long_term(self, limit: int = 20) -> list[dict[str, Any]]:
        """Load long-term memory entries."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM long_term ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def load_all_long_term(self) -> list[dict[str, Any]]:
        """Load all long-term memory entries."""
        with self._lock, self._cursor() as cursor:
            cursor.execute("SELECT * FROM long_term ORDER BY timestamp DESC")
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_long_term(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search long-term memory by content/what/why using LIKE."""
        pattern = f"%{query}%"
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                """SELECT * FROM long_term
                       WHERE content LIKE ? OR what LIKE ? OR why LIKE ?
                       ORDER BY timestamp DESC LIMIT ?""",
                (pattern, pattern, pattern, limit),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def delete_long_term(self, entry_id: str) -> bool:
        """Delete a long-term memory entry."""
        with self._lock, self._cursor() as cursor:
            cursor.execute("DELETE FROM long_term WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    # ── Procedural Memory ────────────────────────────────────────────────

    def save_procedural(self, entry: dict[str, Any]) -> str:
        """Save a memory entry to the procedural tier."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                """INSERT OR REPLACE INTO procedural
                       (id, content, hemisphere, is_novel, novelty_score,
                        timestamp, expires_at, source_tier, destination_tier,
                        who, what, location, when_ts, why, how, metadata, created_at,
                        skill_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["id"],
                    entry["content"],
                    entry.get("hemisphere", "left"),
                    1 if entry.get("is_novel") else 0,
                    entry.get("novelty_score", 0.0),
                    entry["timestamp"],
                    entry.get("expires_at"),
                    entry.get("source_tier"),
                    entry.get("destination_tier"),
                    entry.get("who", ""),
                    entry.get("what", ""),
                    entry.get("where", ""),
                    entry.get("when", ""),
                    entry.get("why", ""),
                    entry.get("how", ""),
                    json.dumps(entry.get("metadata", {})),
                    datetime.now(timezone.utc).isoformat(),
                    entry.get("metadata", {}).get("skill_id"),
                ),
            )
        return entry["id"]

    def load_procedural(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Load procedural memory entries."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM procedural ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def load_all_procedural(self) -> list[dict[str, Any]]:
        """Load all procedural memory entries."""
        with self._lock, self._cursor() as cursor:
            cursor.execute("SELECT * FROM procedural ORDER BY timestamp DESC")
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_procedural(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search procedural memory by content/what/why using LIKE."""
        pattern = f"%{query}%"
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                """SELECT * FROM procedural
                       WHERE content LIKE ? OR what LIKE ? OR why LIKE ?
                       ORDER BY timestamp DESC LIMIT ?""",
                (pattern, pattern, pattern, limit),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def delete_procedural(self, entry_id: str) -> bool:
        """Delete a procedural memory entry."""
        with self._lock, self._cursor() as cursor:
            cursor.execute("DELETE FROM procedural WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    # ── Transfer Logging ─────────────────────────────────────────────────

    def log_transfer(self, from_tier: str, to_tier: str, entry_id: str) -> None:
        """Log a memory transfer between tiers."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                """INSERT INTO transfer_log (id, from_tier, to_tier, entry_id, timestamp)
                       VALUES (?, ?, ?, ?, ?)""",
                (
                    f"tfr-{entry_id}",
                    from_tier,
                    to_tier,
                    entry_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_transfer_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent transfer log entries."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM transfer_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    # ── Decay ────────────────────────────────────────────────────────────

    def decay_working(self) -> int:
        """Remove expired working memory entries. Returns count removed."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM working WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
            return cursor.rowcount

    def decay_all(self) -> dict[str, int]:
        """Run decay on all tiers. Returns count removed per tier."""
        with self._lock, self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM working WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
            working = cursor.rowcount

            # Long-term and procedural have no decay
            return {
                "working": working,
                "long_term": 0,
                "procedural": 0,
            }

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get memory system statistics."""
        with self._lock, self._cursor() as cursor:
            stats: dict[str, Any] = {}
            for tier in ("working", "long_term", "procedural"):
                cursor.execute(f"SELECT COUNT(*) as cnt FROM {tier}")
                stats[f"{tier}_count"] = cursor.fetchone()["cnt"]

                # Count novel entries
                cursor.execute(f"SELECT COUNT(*) as cnt FROM {tier} WHERE is_novel = 1")
                stats[f"{tier}_novel"] = cursor.fetchone()["cnt"]

            # Transfer log count
            cursor.execute("SELECT COUNT(*) as cnt FROM transfer_log")
            stats["transfers"] = cursor.fetchone()["cnt"]

            return stats

    # ── Import/Export ────────────────────────────────────────────────────

    def import_entries(self, tier: str, entries: list[dict[str, Any]]) -> int:
        """Import a batch of entries into the specified tier. Returns count imported."""
        with self._lock:
            count = 0
            for entry in entries:
                try:
                    if tier == "working":
                        self.save_working(entry)
                    elif tier == "long_term":
                        self.save_long_term(entry)
                    elif tier == "procedural":
                        self.save_procedural(entry)
                    count += 1
                except Exception as e:
                    log.warning(f"Failed to import {tier} entry {entry.get('id')}: {e}")
            return count

    def export_entries(self, tier: str) -> list[dict[str, Any]]:
        """Export all entries from a tier."""
        if tier == "working":
            return self.load_all_working()
        elif tier == "long_term":
            return self.load_all_long_term()
        elif tier == "procedural":
            return self.load_all_procedural()
        else:
            return []

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start_decay_scheduler(self, interval: float | None = None) -> None:
        """Start background decay scheduler."""
        if self.decay_thread is not None and self.decay_thread.is_alive():
            return

        interval = interval or self.decay_interval

        def _decay_loop() -> None:
            while not self._stop_event.wait(interval):
                try:
                    removed = self.decay_all()
                    if removed["working"] > 0:
                        log.info(f"Decay removed {removed['working']} working memories")
                except Exception as e:
                    log.error(f"Decay scheduler error: {e}")

        self.decay_thread = threading.Thread(target=_decay_loop, daemon=True, name="memory-decay")
        self.decay_thread.start()
        log.info(f"Decay scheduler started (interval={interval}s)")

    def stop_decay_scheduler(self) -> None:
        """Stop background decay scheduler."""
        self._stop_event.set()
        if self.decay_thread is not None:
            self.decay_thread.join(timeout=5)
            self.decay_thread = None

    def close(self) -> None:
        """Close the database connection."""
        self.stop_decay_scheduler()
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception as e:
            log.warning("Persistence operation failed: %s", e)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a sqlite3.Row to a dict."""
        d = dict(row)
        # Map 'location' (DB) back to 'where' (API) for compatibility
        if "location" in d:
            d["where"] = d.pop("location")
        # Parse metadata JSON
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        else:
            d["metadata"] = {}
        return d
