"""NoOpRelationalMemoryAdapter — aiosqlite in-memory backend (ADR-102 D2).

Zero external dependency (aiosqlite is MIT-licensed and ships with stdlib
sqlite3). Runs on ``:memory:`` by default; ``db_path=<file>`` for persistence.

Schema (mirrors the Postgres adapter's Alembic migration where possible):

- ``ledger_events`` (event_id TEXT PK, kind, session_id, agent_id, payload
  JSON, confidence, provenance, created_at ISO string)
- ``narratives`` (narrative_id TEXT PK, session_id, agent_id, title, body,
  tags JSON, embedding JSON, confidence, provenance, created_at)

pgvector semantics are not enforced (sqlite has no vector type); when a
caller passes ``embedding``, the adapter stores it as a JSON list. During
``search_narratives``, an ``embedding`` argument is IGNORED and rank falls
back to a simple ``LIKE %query%`` substring match. This is intentional —
adapters MAY silently degrade on unsupported features (per ADR-098 D3
precedent), but the fallback rank is honest: pure-lexical, no fusion.

Zero-trust write contract enforcement (ADR-102 D4): the adapter calls
``validate_confidence()`` and ``validate_provenance()`` from
``ports.relational_memory`` at every write.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

try:
    import aiosqlite
except ImportError as _e:  # pragma: no cover — CI must have aiosqlite
    aiosqlite = None  # type: ignore
    _AIOSQLITE_IMPORT_ERROR: Exception | None = _e
else:
    _AIOSQLITE_IMPORT_ERROR = None

from ports.relational_memory import (
    LedgerRow,
    NarrativeHit,
    validate_confidence,
    validate_provenance,
)

__all__ = ["NoOpRelationalMemoryAdapter"]

_LOG = logging.getLogger(__name__)

_MAX_LIMIT_EVENTS = 1000
_MAX_LIMIT_NARRATIVES = 200

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_events (
    event_id     TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    session_id   TEXT,
    agent_id     TEXT,
    payload      TEXT NOT NULL,
    confidence   REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    provenance   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_kind_time
    ON ledger_events (kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_session_time
    ON ledger_events (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_agent_time
    ON ledger_events (agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS narratives (
    narrative_id TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    agent_id     TEXT,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    tags         TEXT NOT NULL,
    embedding    TEXT,
    confidence   REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    provenance   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_narr_session
    ON narratives (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_narr_agent
    ON narratives (agent_id, created_at DESC);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid7_fallback() -> str:
    """UUIDv7-shaped fallback using stdlib uuid4.

    Stdlib does not ship uuid7 until 3.14 (which is our runtime — see
    below). We accept plain uuid4 for the noop adapter because sqlite has
    no native uuid type either; the string is what matters. Postgres
    adapter uses ``uuidv7()`` via ``pg_uuidv7`` extension.
    """
    return str(uuid.uuid4())


def _parse_iso(s: str) -> datetime:
    # datetime.fromisoformat handles the "+00:00" suffix produced by _now_iso.
    return datetime.fromisoformat(s)


class _NoOpTx:
    """Non-atomic transaction stub for the noop adapter.

    aiosqlite supports real transactions, but for the noop adapter we
    accept per-statement autocommit and treat ``transaction()`` as a
    marker interface. This preserves the port contract shape without
    requiring true nested-transaction semantics that CI never exercises.

    When the real Postgres adapter lands, it will use ``asyncpg.transaction()``
    for genuine atomicity.
    """

    def __init__(self, adapter: "NoOpRelationalMemoryAdapter") -> None:
        self._adapter = adapter

    async def record_event(self, **kwargs: Any) -> str:
        return await self._adapter.record_event(**kwargs)

    async def write_narrative(self, **kwargs: Any) -> str:
        return await self._adapter.write_narrative(**kwargs)


class NoOpRelationalMemoryAdapter:
    """aiosqlite-backed RelationalMemoryPort. Suitable for CI + dev.

    Args:
        db_path: sqlite path. Default ``":memory:"`` (per-process). Pass a
            file path for persistence across processes.
        embedding_dim: not enforced (sqlite has no vector type); accepted
            for interface parity with the Postgres adapter.
    """

    def __init__(
        self,
        *,
        db_path: str = ":memory:",
        embedding_dim: int | None = 1536,
    ) -> None:
        self._db_path = db_path
        self._embedding_dim = embedding_dim
        self._conn: Any | None = None  # aiosqlite.Connection when open
        self._init_error: Exception | None = None
        # When >0, we are inside an explicit transaction() context and
        # per-write commits must be suppressed so rollback works.
        self._tx_depth = 0
        if _AIOSQLITE_IMPORT_ERROR is not None:
            self._init_error = _AIOSQLITE_IMPORT_ERROR

    async def _ensure_open(self) -> Any:
        if self._conn is not None:
            return self._conn
        if _AIOSQLITE_IMPORT_ERROR is not None:
            raise RuntimeError(
                "aiosqlite import failed; NoOpRelationalMemoryAdapter unusable"
            ) from _AIOSQLITE_IMPORT_ERROR
        try:
            # isolation_level=None puts sqlite in autocommit mode; we manage
            # transactions explicitly via BEGIN/COMMIT/ROLLBACK to keep
            # transaction() semantics predictable across aiosqlite versions.
            self._conn = await aiosqlite.connect(
                self._db_path, isolation_level=None
            )
            self._conn.row_factory = aiosqlite.Row
            # Execute schema statements one at a time (executescript is not
            # available on the async cursor in all aiosqlite versions).
            for stmt in _SCHEMA_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self._conn.execute(stmt)
            await self._conn.commit()
        except Exception as exc:
            self._init_error = exc
            self._conn = None
            raise
        return self._conn

    # ── Transaction ────────────────────────────────────────────────────────

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_NoOpTx]:
        # Autocommit is on globally; wrapping with BEGIN/COMMIT gives us
        # a real transaction whose ROLLBACK undoes queued writes.
        conn = await self._ensure_open()
        await conn.execute("BEGIN")
        self._tx_depth += 1
        try:
            yield _NoOpTx(self)
        except Exception:
            self._tx_depth -= 1
            await conn.execute("ROLLBACK")
            raise
        else:
            self._tx_depth -= 1
            await conn.execute("COMMIT")

    # ── Ledger surface (R1) ────────────────────────────────────────────────

    async def record_event(
        self,
        *,
        kind: str,
        session_id: str | None,
        agent_id: str | None,
        payload: dict[str, Any],
        confidence: float,
        provenance: str,
    ) -> str:
        validate_confidence(confidence)
        validate_provenance(provenance)
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("record_event: kind must be non-empty str")
        if not isinstance(payload, dict):
            raise ValueError("record_event: payload must be dict")

        conn = await self._ensure_open()
        event_id = _uuid7_fallback()
        created_at = _now_iso()
        await conn.execute(
            "INSERT INTO ledger_events "
            "(event_id, kind, session_id, agent_id, payload, confidence, provenance, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                kind,
                session_id,
                agent_id,
                json.dumps(payload, sort_keys=True, default=str),
                float(confidence),
                provenance,
                created_at,
            ),
        )
        # Autocommit mode: statements are committed by sqlite itself unless
        # we're inside our explicit BEGIN. No manual commit needed either
        # way.
        return event_id

    async def query_events(
        self,
        *,
        kind_prefix: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> tuple[LedgerRow, ...]:
        if limit < 1:
            return ()
        limit = min(limit, _MAX_LIMIT_EVENTS)
        conn = await self._ensure_open()

        clauses: list[str] = []
        params: list[Any] = []
        if kind_prefix is not None:
            clauses.append("kind LIKE ?")
            # sqlite treats %/_ as wildcards; escape any in the caller input.
            escaped = kind_prefix.replace("%", r"\%").replace("_", r"\_")
            params.append(f"{escaped}%")
            # sqlite LIKE ESCAPE not universally applied; we accept that
            # trailing % is the user's; % inside prefix is user error.
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("created_at < ?")
            params.append(until.isoformat())

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT event_id, kind, session_id, agent_id, payload, "
            f"confidence, provenance, created_at FROM ledger_events "
            f"{where} ORDER BY created_at DESC LIMIT ?"
        )
        params.append(limit)

        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()

        result: list[LedgerRow] = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            result.append(
                LedgerRow(
                    event_id=r["event_id"],
                    kind=r["kind"],
                    session_id=r["session_id"],
                    agent_id=r["agent_id"],
                    payload=payload,
                    confidence=float(r["confidence"]),
                    provenance=r["provenance"],
                    created_at=_parse_iso(r["created_at"]),
                )
            )
        return tuple(result)

    # ── Narrative surface (R2) ─────────────────────────────────────────────

    async def write_narrative(
        self,
        *,
        session_id: str,
        agent_id: str | None,
        title: str,
        body: str,
        tags: tuple[str, ...],
        embedding: tuple[float, ...] | None,
        confidence: float,
        provenance: str,
    ) -> str:
        validate_confidence(confidence)
        validate_provenance(provenance)
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("write_narrative: session_id must be non-empty str")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("write_narrative: title must be non-empty str")
        if not isinstance(body, str):
            raise ValueError("write_narrative: body must be str")
        if not isinstance(tags, tuple):
            raise ValueError("write_narrative: tags must be tuple[str, ...]")
        if embedding is not None:
            if not isinstance(embedding, tuple):
                raise ValueError("write_narrative: embedding must be tuple[float, ...] or None")
            if self._embedding_dim is not None and len(embedding) != self._embedding_dim:
                raise ValueError(
                    f"write_narrative: embedding dim {len(embedding)} "
                    f"does not match adapter dim {self._embedding_dim}"
                )

        conn = await self._ensure_open()
        narrative_id = _uuid7_fallback()
        created_at = _now_iso()
        await conn.execute(
            "INSERT INTO narratives "
            "(narrative_id, session_id, agent_id, title, body, tags, embedding, "
            " confidence, provenance, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                narrative_id,
                session_id,
                agent_id,
                title,
                body,
                json.dumps(list(tags)),
                json.dumps(list(embedding)) if embedding is not None else None,
                float(confidence),
                provenance,
                created_at,
            ),
        )
        # Autocommit mode: see record_event for the rationale.
        return narrative_id

    async def search_narratives(
        self,
        *,
        query: str,
        embedding: tuple[float, ...] | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        tags: tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[NarrativeHit, ...]:
        if limit < 1:
            return ()
        limit = min(limit, _MAX_LIMIT_NARRATIVES)
        if embedding is not None:
            # ADR-098 D3-style honest degrade: log once per adapter instance
            # that vector search is not supported; fall back to pure lexical.
            _LOG.debug(
                "NoOpRelationalMemoryAdapter: embedding ignored "
                "(sqlite has no vector type); pure lexical rank used."
            )
        conn = await self._ensure_open()

        clauses: list[str] = []
        params: list[Any] = []
        if query and query.strip():
            clauses.append("(body LIKE ? OR title LIKE ?)")
            like = f"%{query.strip()}%"
            params.extend((like, like))
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        # tags: substring match on the JSON blob; not ideal but adequate for CI.
        for tag in tags:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT narrative_id, session_id, agent_id, title, body, tags, "
            f"confidence, provenance, created_at FROM narratives "
            f"{where} ORDER BY created_at DESC LIMIT ?"
        )
        params.append(limit)

        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()

        result: list[NarrativeHit] = []
        for r in rows:
            try:
                tag_list = json.loads(r["tags"])
                tag_tuple = tuple(str(t) for t in tag_list)
            except (TypeError, json.JSONDecodeError):
                tag_tuple = ()
            # Honest rank: 1.0 when query matched, 0.5 when only filter matched.
            score = 1.0 if (query and query.strip()) else 0.5
            result.append(
                NarrativeHit(
                    narrative_id=r["narrative_id"],
                    session_id=r["session_id"],
                    agent_id=r["agent_id"],
                    title=r["title"],
                    body=r["body"],
                    tags=tag_tuple,
                    confidence=float(r["confidence"]),
                    provenance=r["provenance"],
                    created_at=_parse_iso(r["created_at"]),
                    score=score,
                )
            )
        return tuple(result)

    # ── Health / lifecycle ─────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        # Non-throwing sync check (ADR-101 D3 pattern). We consider the
        # adapter healthy if aiosqlite imported cleanly; the actual
        # connection is opened lazily on first async call.
        return self._init_error is None

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:  # pragma: no cover
                _LOG.warning(
                    "NoOpRelationalMemoryAdapter.close: swallowed %s: %s",
                    type(exc).__name__,
                    exc,
                )
            finally:
                self._conn = None
