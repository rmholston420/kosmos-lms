"""ports.relational_memory — RelationalMemoryPort Protocol (ADR-102).

Formal Kosmos port for the 5th memory layer: relational-metadata + episodic-narrative
store. Backed by Postgres 18 + pgvector 0.8.1 + pg_uuidv7 in production; aiosqlite
in-memory for CI / dev.

Combines two roles per ADR-102 D1:

- **R1 — Audit ledger.** Sessions, approvals, tool-invocation audit trail,
  ADR-088 read-only budget history, ADR-092 immune events — written via
  ``record_event`` and queried via ``query_events``.
- **R2 — Episodic-narrative store.** Retrievable narratives of past sessions
  with rich time/tag/agent-scoped queries + optional pgvector semantic recall
  over narrative text. Written via ``write_narrative`` and queried via
  ``search_narratives`` (hybrid tsvector + hnsw when embedding provided and
  adapter supports it).

**R3 — pgvector as EmbeddingsPort alternative** is intentionally NOT part of
this port; deferred to a future ADR.

Enforcement rules (per ADR-102 D4 + spec §25.4, parity with ADR-008):

1. Every ``record_event`` call MUST carry ``provenance: str`` (non-empty) and
   ``confidence: float`` in ``[0.0, 1.0]``. Protocol-layer validation is
   the adapter's responsibility (via ``_validate_write``).
2. Every ``write_narrative`` call has the same requirement.
3. Adapters SHOULD emit ``EventBusPort`` envelopes on their own; the port
   does not require it (unlike ``MemoryPort``).

The port surface is transaction-aware via ``transaction()`` for atomic
multi-write sequences (e.g. propose an approval + record its ledger event
in one transaction).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "LedgerRow",
    "NarrativeHit",
    "RelationalMemoryPort",
    "RelationalTx",
    "validate_confidence",
    "validate_provenance",
]


# ---------------------------------------------------------------------------
# Validation helpers (protocol-layer, non-bypassable per ADR-102 D4)
# ---------------------------------------------------------------------------


def validate_confidence(confidence: float) -> None:
    """Raise ValueError if confidence is outside ``[0.0, 1.0]`` (ADR-102 D4)."""
    if not isinstance(confidence, (int, float)):
        raise ValueError(
            f"RelationalMemoryPort: confidence must be numeric, got {type(confidence).__name__}"
        )
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError(
            f"RelationalMemoryPort: confidence must be in [0.0, 1.0], got {confidence!r}"
        )


def validate_provenance(provenance: str) -> None:
    """Raise ValueError if provenance is empty or not a str (ADR-102 D4)."""
    if not isinstance(provenance, str):
        raise ValueError(
            f"RelationalMemoryPort: provenance must be str, got {type(provenance).__name__}"
        )
    if not provenance.strip():
        raise ValueError("RelationalMemoryPort: provenance must be non-empty")


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One row from the audit ledger (R1). Immutable.

    Returned by ``query_events``. ``event_id`` is a UUIDv7 string (or a
    ``gen_random_uuid()`` fallback when ``pg_uuidv7`` is unavailable).
    ``created_at`` is the server-side insertion timestamp (UTC).
    """

    event_id: str
    kind: str
    session_id: str | None
    agent_id: str | None
    payload: dict[str, Any]
    confidence: float
    provenance: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NarrativeHit:
    """One hit from ``search_narratives`` (R2). Immutable.

    ``score`` is a normalized rank score:

    - When only tsvector matched: ``ts_rank_cd`` normalized to ``[0, 1]``.
    - When both tsvector + pgvector matched: RRF fusion of the two ranks
      (k=60 by default; adapters may tune).
    - When only pgvector matched: ``1.0 - cosine_distance`` clamped to
      ``[0, 1]``.
    """

    narrative_id: str
    session_id: str
    agent_id: str | None
    title: str
    body: str
    tags: tuple[str, ...]
    confidence: float
    provenance: str
    created_at: datetime
    score: float


# ---------------------------------------------------------------------------
# Transaction handle
# ---------------------------------------------------------------------------


@runtime_checkable
class RelationalTx(Protocol):
    """Handle returned from ``RelationalMemoryPort.transaction()``.

    All ``record_event`` / ``write_narrative`` calls made on the ``tx``
    handle inside the ``async with`` block are atomic. Reads use the same
    transaction snapshot. Exiting normally commits; exiting with an
    exception rolls back.
    """

    async def record_event(
        self,
        *,
        kind: str,
        session_id: str | None,
        agent_id: str | None,
        payload: dict[str, Any],
        confidence: float,
        provenance: str,
    ) -> str: ...

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
    ) -> str: ...


# ---------------------------------------------------------------------------
# The port
# ---------------------------------------------------------------------------


@runtime_checkable
class RelationalMemoryPort(Protocol):
    """Formal Kosmos contract for the 5th memory layer (ADR-102).

    Adapters:

    - ``NoOpRelationalMemoryAdapter`` (``adapters/relational_memory/noop/``)
      — aiosqlite in-memory backend; pgvector shape stored as JSON blob
      (search falls back to full-text-scan). Required for CI.
    - ``PostgresRelationalMemoryAdapter``
      (``adapters/relational_memory/postgres/``) — asyncpg + pgvector + Alembic
      migrations. Production backend.
    """

    # ── Transaction ────────────────────────────────────────────────────────

    def transaction(self) -> AbstractAsyncContextManager[RelationalTx]:
        """Begin a transaction.

        Usage::

            async with port.transaction() as tx:
                await tx.record_event(...)
                await tx.write_narrative(...)
            # commits on normal exit; rolls back on exception
        """
        ...

    # ── Audit ledger surface (R1) ──────────────────────────────────────────

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
        """Append one audit-ledger row. Returns event_id (UUIDv7 string).

        Zero-trust write contract (ADR-102 D4): ``confidence`` must be in
        ``[0.0, 1.0]`` and ``provenance`` must be non-empty.
        """
        ...

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
        """Query the audit ledger with optional filters.

        - ``kind_prefix``: matches ``kind LIKE 'prefix%'`` (SQL-injection
          hardened by adapter).
        - ``session_id`` / ``agent_id``: exact match.
        - ``since`` / ``until``: half-open ``[since, until)`` on ``created_at``.
        - ``limit``: capped at 1000 by adapters; default 100.

        Returns rows sorted by ``created_at DESC``.
        """
        ...

    # ── Episodic-narrative surface (R2) ────────────────────────────────────

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
        """Persist one narrative. Returns narrative_id (UUIDv7 string).

        ``embedding`` is optional. If provided, its dimension MUST match the
        adapter's configured ``embedding_dim`` (default 1536 per ADR-102 D3).
        ``ValueError`` on mismatch. Adapters without pgvector support store
        ``embedding`` in a JSON column and only use ``body`` for search.

        Zero-trust write contract (ADR-102 D4): ``confidence`` must be in
        ``[0.0, 1.0]`` and ``provenance`` must be non-empty.
        """
        ...

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
        """Search narratives; hybrid tsvector + pgvector when both provided.

        - ``query``: full-text query (adapter-specific tokenization; the
          Postgres adapter uses ``plainto_tsquery('english', query)``).
        - ``embedding``: if provided AND adapter supports pgvector, fuses
          tsvector rank with pgvector distance via RRF (k=60).
        - ``session_id`` / ``agent_id`` / ``tags``: optional filters.
        - ``limit``: capped at 200; default 20.

        Returns hits sorted by ``score DESC``.
        """
        ...

    # ── Health / lifecycle ─────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Non-throwing sync health check (ADR-101 D3 pattern).

        Returns ``False`` when the adapter is misconfigured, the backing
        store is unreachable, or migrations are behind. Kernel boot uses
        this to decide whether to wire the port or fall through to
        ``registry.relational_memory = None``.
        """
        ...

    async def close(self) -> None:
        """Idempotent async close.

        Cleanly disposes of connection pools. Safe to call multiple times.
        Adapters swallow driver errors into a warning log (per ADR-100 D1
        precedent).
        """
        ...
