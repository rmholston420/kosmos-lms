"""PostgresRelationalMemoryAdapter — asyncpg + pgvector (ADR-102 D2/D3).

Production adapter for the 5th memory layer. Follows the `DozerDbGraphBackend`
pattern (ADR-100 D1): lazy driver creation, per-call session, `_init_error`
capture, sync non-throwing `is_healthy`, idempotent async `close`.

Schema is owned by Alembic migrations at
``adapters/relational_memory/postgres/migrations/`` — see ``001_initial.py``.
This adapter does NOT auto-migrate on boot (ADR-063 no-implicit-schema-changes
rule + ADR-102 D7).

Hybrid narrative search (per ADR-102 D5):

- Query with ``embedding=None`` -> pure ``ts_rank_cd(body_tsv, plainto_tsquery(...))``.
- Query with ``embedding=(...)`` -> RRF fusion (k=60) of ts_rank_cd and
  ``1 - (embedding <=> query_embedding)`` (cosine similarity via pgvector).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

try:
    import asyncpg
except ImportError as _e:  # pragma: no cover — Colossus-side
    asyncpg = None  # type: ignore
    _ASYNCPG_IMPORT_ERROR: Exception | None = _e
else:
    _ASYNCPG_IMPORT_ERROR = None

try:
    from pgvector.asyncpg import register_vector
except ImportError:  # pragma: no cover
    register_vector = None  # type: ignore

from ports.relational_memory import (
    LedgerRow,
    NarrativeHit,
    validate_confidence,
    validate_provenance,
)

__all__ = ["PostgresRelationalMemoryAdapter"]

_LOG = logging.getLogger(__name__)

_MAX_LIMIT_EVENTS = 1000
_MAX_LIMIT_NARRATIVES = 200
_RRF_K = 60


class _PgTx:
    """Real asyncpg-backed transaction handle (ADR-102 D1)."""

    def __init__(self, connection: Any, adapter: "PostgresRelationalMemoryAdapter") -> None:
        self._conn = connection
        self._adapter = adapter

    async def record_event(self, **kwargs: Any) -> str:
        return await self._adapter._record_event_on(self._conn, **kwargs)

    async def write_narrative(self, **kwargs: Any) -> str:
        return await self._adapter._write_narrative_on(self._conn, **kwargs)


class PostgresRelationalMemoryAdapter:
    """asyncpg + pgvector backend for RelationalMemoryPort.

    Args:
        dsn: postgres:// URI (e.g. ``postgres://kosmos@localhost:5432/kosmos``).
        embedding_dim: dimension of the ``narratives.embedding`` column.
            Must match the deployed Alembic migration. Default 1536.
        min_pool_size: asyncpg pool min. Default 2.
        max_pool_size: asyncpg pool max. Default 10.
    """

    def __init__(
        self,
        *,
        dsn: str,
        embedding_dim: int = 1536,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._embedding_dim = embedding_dim
        self._min_pool = min_pool_size
        self._max_pool = max_pool_size
        self._pool: Any | None = None
        self._init_error: Exception | None = None
        if _ASYNCPG_IMPORT_ERROR is not None:
            self._init_error = _ASYNCPG_IMPORT_ERROR

    # ── Pool lifecycle ─────────────────────────────────────────────────────

    async def _init_pgvector_conn(self, conn: Any) -> None:
        """Per-connection init: register pgvector types.

        Called by asyncpg for every new connection acquired into the pool.
        """
        if register_vector is not None:
            try:
                await register_vector(conn)
            except Exception as exc:  # pragma: no cover — env-gated live tier
                _LOG.warning(
                    "PostgresRelationalMemoryAdapter: pgvector register failed: %s",
                    exc,
                )

    async def _ensure_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        if _ASYNCPG_IMPORT_ERROR is not None:
            raise RuntimeError(
                "asyncpg import failed; PostgresRelationalMemoryAdapter unusable"
            ) from _ASYNCPG_IMPORT_ERROR
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_pool,
                max_size=self._max_pool,
                init=self._init_pgvector_conn,
            )
        except Exception as exc:
            self._init_error = exc
            self._pool = None
            raise
        return self._pool

    # ── Transaction ────────────────────────────────────────────────────────

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_PgTx]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield _PgTx(conn, self)

    # ── Ledger surface (R1) ────────────────────────────────────────────────

    async def _record_event_on(
        self,
        conn: Any,
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

        # UUIDv7 preferred (pg_uuidv7 extension); fallback to gen_random_uuid.
        # The Alembic migration installs pg_uuidv7 and sets the column
        # default. We reuse the default rather than compute UUIDs client-side.
        row = await conn.fetchrow(
            "INSERT INTO ledger_events "
            "(kind, session_id, agent_id, payload, confidence, provenance) "
            "VALUES ($1, $2, $3, $4::jsonb, $5, $6) "
            "RETURNING event_id::text",
            kind,
            session_id,
            agent_id,
            _json_dumps(payload),
            float(confidence),
            provenance,
        )
        return row["event_id"]

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
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await self._record_event_on(
                conn,
                kind=kind,
                session_id=session_id,
                agent_id=agent_id,
                payload=payload,
                confidence=confidence,
                provenance=provenance,
            )

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

        clauses: list[str] = []
        params: list[Any] = []

        def _next() -> str:
            return f"${len(params) + 1}"

        if kind_prefix is not None:
            # ESCAPE-safe: use LIKE with \ escape for user-supplied % / _.
            escaped = kind_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(f"kind LIKE {_next()} ESCAPE '\\'")
            params.append(f"{escaped}%")
        if session_id is not None:
            clauses.append(f"session_id = {_next()}")
            params.append(session_id)
        if agent_id is not None:
            clauses.append(f"agent_id = {_next()}")
            params.append(agent_id)
        if since is not None:
            clauses.append(f"created_at >= {_next()}")
            params.append(since if since.tzinfo else since.replace(tzinfo=timezone.utc))
        if until is not None:
            clauses.append(f"created_at < {_next()}")
            params.append(until if until.tzinfo else until.replace(tzinfo=timezone.utc))

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        sql = (
            f"SELECT event_id::text AS event_id, kind, session_id, agent_id, "
            f"payload, confidence, provenance, created_at "
            f"FROM ledger_events {where} "
            f"ORDER BY created_at DESC LIMIT ${len(params)}"
        )

        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return tuple(
            LedgerRow(
                event_id=r["event_id"],
                kind=r["kind"],
                session_id=r["session_id"],
                agent_id=r["agent_id"],
                payload=_json_loads(r["payload"]),
                confidence=float(r["confidence"]),
                provenance=r["provenance"],
                created_at=r["created_at"],
            )
            for r in rows
        )

    # ── Narrative surface (R2) ─────────────────────────────────────────────

    async def _write_narrative_on(
        self,
        conn: Any,
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
                raise ValueError(
                    "write_narrative: embedding must be tuple[float, ...] or None"
                )
            if len(embedding) != self._embedding_dim:
                raise ValueError(
                    f"write_narrative: embedding dim {len(embedding)} "
                    f"does not match adapter dim {self._embedding_dim}"
                )

        row = await conn.fetchrow(
            "INSERT INTO narratives "
            "(session_id, agent_id, title, body, tags, embedding, confidence, provenance) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "RETURNING narrative_id::text",
            session_id,
            agent_id,
            title,
            body,
            list(tags),
            list(embedding) if embedding is not None else None,
            float(confidence),
            provenance,
        )
        return row["narrative_id"]

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
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await self._write_narrative_on(
                conn,
                session_id=session_id,
                agent_id=agent_id,
                title=title,
                body=body,
                tags=tags,
                embedding=embedding,
                confidence=confidence,
                provenance=provenance,
            )

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
        pool = await self._ensure_pool()

        # Build filters common to both branches.
        filter_clauses: list[str] = []
        filter_params: list[Any] = []

        def _next() -> str:
            return f"${len(filter_params) + 1}"

        if session_id is not None:
            filter_clauses.append(f"session_id = {_next()}")
            filter_params.append(session_id)
        if agent_id is not None:
            filter_clauses.append(f"agent_id = {_next()}")
            filter_params.append(agent_id)
        if tags:
            # GIN-indexed array contains-all check
            filter_clauses.append(f"tags @> {_next()}::text[]")
            filter_params.append(list(tags))

        if embedding is not None and len(embedding) != self._embedding_dim:
            raise ValueError(
                f"search_narratives: embedding dim {len(embedding)} "
                f"does not match adapter dim {self._embedding_dim}"
            )

        if embedding is None:
            # Pure tsvector branch.
            # ts_rank_cd is bounded [0, 1] with normalization=32 (log-length norm).
            q_param = f"${len(filter_params) + 1}"
            filter_params.append(query)
            filter_params.append(limit)
            limit_param = f"${len(filter_params)}"
            where = filter_clauses + [f"body_tsv @@ plainto_tsquery('english', {q_param})"]
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            sql = (
                f"SELECT narrative_id::text, session_id, agent_id, title, body, "
                f"tags, confidence, provenance, created_at, "
                f"ts_rank_cd(body_tsv, plainto_tsquery('english', {q_param}), 32) AS score "
                f"FROM narratives {where_sql} "
                f"ORDER BY score DESC LIMIT {limit_param}"
            )
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *filter_params)
        else:
            # Hybrid RRF branch. Two subqueries ranked separately, fused
            # by 1/(k + rank) per ADR-099 pattern.
            q_param = f"${len(filter_params) + 1}"
            filter_params.append(query)
            e_param = f"${len(filter_params) + 1}"
            filter_params.append(list(embedding))
            filter_params.append(limit)
            limit_param = f"${len(filter_params)}"

            base_where = list(filter_clauses)
            filter_sql = ("AND " + " AND ".join(base_where)) if base_where else ""
            sql = f"""
                WITH lex AS (
                    SELECT narrative_id,
                           ROW_NUMBER() OVER (
                               ORDER BY ts_rank_cd(body_tsv, plainto_tsquery('english', {q_param}), 32) DESC
                           ) AS rank
                    FROM narratives
                    WHERE body_tsv @@ plainto_tsquery('english', {q_param})
                    {filter_sql}
                    LIMIT 200
                ),
                sem AS (
                    SELECT narrative_id,
                           ROW_NUMBER() OVER (
                               ORDER BY embedding <=> {e_param}::vector ASC
                           ) AS rank
                    FROM narratives
                    WHERE embedding IS NOT NULL
                    {filter_sql}
                    LIMIT 200
                ),
                fused AS (
                    SELECT COALESCE(lex.narrative_id, sem.narrative_id) AS narrative_id,
                           COALESCE(1.0/({_RRF_K} + lex.rank), 0.0)
                             + COALESCE(1.0/({_RRF_K} + sem.rank), 0.0) AS score
                    FROM lex FULL OUTER JOIN sem USING (narrative_id)
                )
                SELECT n.narrative_id::text, n.session_id, n.agent_id, n.title,
                       n.body, n.tags, n.confidence, n.provenance, n.created_at,
                       f.score
                FROM fused f JOIN narratives n USING (narrative_id)
                ORDER BY f.score DESC LIMIT {limit_param}
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *filter_params)

        return tuple(
            NarrativeHit(
                narrative_id=r["narrative_id"],
                session_id=r["session_id"],
                agent_id=r["agent_id"],
                title=r["title"],
                body=r["body"],
                tags=tuple(r["tags"] or ()),
                confidence=float(r["confidence"]),
                provenance=r["provenance"],
                created_at=r["created_at"],
                score=float(r["score"]),
            )
            for r in rows
        )

    # ── Health / lifecycle ─────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Non-throwing sync check.

        Considers the adapter healthy if asyncpg imported cleanly and no
        init_error has been captured. The pool is opened lazily on first
        async call; live-tier tests exercise the connection path.
        """
        return self._init_error is None

    async def close(self) -> None:
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception as exc:  # pragma: no cover
                _LOG.warning(
                    "PostgresRelationalMemoryAdapter.close: swallowed %s: %s",
                    type(exc).__name__,
                    exc,
                )
            finally:
                self._pool = None


# ---------------------------------------------------------------------------
# JSON helpers — asyncpg needs str, not bytes; pgvector round-trip is bytes.
# ---------------------------------------------------------------------------


def _json_dumps(obj: Any) -> str:
    import json as _json

    return _json.dumps(obj, sort_keys=True, default=str)


def _json_loads(payload: Any) -> dict[str, Any]:
    import json as _json

    if isinstance(payload, str):
        try:
            return _json.loads(payload)
        except _json.JSONDecodeError:
            return {}
    if isinstance(payload, dict):
        return payload
    return {}
