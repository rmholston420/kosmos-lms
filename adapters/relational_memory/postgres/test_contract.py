"""Contract tests for PostgresRelationalMemoryAdapter (ADR-102 Stage 8.0).

Two tiers:

1. **Import-only tier** — always runs. Verifies the adapter imports
   cleanly and satisfies the Protocol (isinstance check). Catches shape
   regressions without needing a live Postgres.

2. **Live tier** — gated on ``KOSMOS_STAGE_80_REAL_POSTGRES=1`` +
   ``KOSMOS_POSTGRES_URI=...``. Exercises the real
   record_event/query_events/write_narrative/search_narratives round-trips
   against a running Postgres 18 + pgvector + pg_uuidv7 instance. Run by
   the user on Colossus after `alembic upgrade head`.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from adapters.relational_memory.postgres import PostgresRelationalMemoryAdapter
from ports.relational_memory import (
    LedgerRow,
    NarrativeHit,
    RelationalMemoryPort,
)

_LIVE = (
    os.environ.get("KOSMOS_STAGE_80_REAL_POSTGRES") == "1"
    and bool(os.environ.get("KOSMOS_POSTGRES_URI"))
)


# ---------------------------------------------------------------------------
# Import-only tier (always runs)
# ---------------------------------------------------------------------------


def test_adapter_import_ok():
    """The adapter class imports without needing a live database."""
    assert PostgresRelationalMemoryAdapter is not None


def test_adapter_satisfies_port_protocol_shape():
    """Instance satisfies runtime_checkable RelationalMemoryPort.

    NB: we do NOT call _ensure_pool() here — protocol check is pure shape.
    """
    adapter = PostgresRelationalMemoryAdapter(
        dsn="postgres://placeholder@localhost:5432/placeholder"
    )
    assert isinstance(adapter, RelationalMemoryPort)


def test_is_healthy_without_pool():
    """is_healthy() returns True on a fresh adapter (pool is lazy).

    is_healthy() is a sync non-throwing check — it does not attempt a
    connection. Live-tier tests exercise the actual pool.
    """
    adapter = PostgresRelationalMemoryAdapter(
        dsn="postgres://placeholder@localhost:5432/placeholder"
    )
    assert adapter.is_healthy() is True


# ---------------------------------------------------------------------------
# Live tier (env-gated — Colossus only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIVE, reason="KOSMOS_STAGE_80_REAL_POSTGRES=1 not set")
class TestLivePostgres:
    """Live round-trip tests. Require:

    - Postgres 18 running and reachable via ``KOSMOS_POSTGRES_URI``.
    - ``alembic -c adapters/relational_memory/postgres/migrations/alembic.ini
      upgrade head`` already applied.
    - ``pgvector`` + (ideally) ``pg_uuidv7`` extensions installed.

    Each test uses a unique session_id namespace so parallel runs do not
    interfere.
    """

    def _adapter(self):
        return PostgresRelationalMemoryAdapter(
            dsn=os.environ["KOSMOS_POSTGRES_URI"]
        )

    def _ns(self) -> str:
        return f"contract-{uuid.uuid4().hex[:12]}"

    def test_record_and_query_events(self):
        async def go():
            adapter = self._adapter()
            ns = self._ns()
            try:
                eid = await adapter.record_event(
                    kind="live.test",
                    session_id=ns,
                    agent_id="a1",
                    payload={"marker": ns},
                    confidence=1.0,
                    provenance="pytest",
                )
                assert isinstance(eid, str) and len(eid) == 36
                rows = await adapter.query_events(session_id=ns)
                assert len(rows) == 1
                assert isinstance(rows[0], LedgerRow)
                assert rows[0].payload["marker"] == ns
            finally:
                await adapter.close()

        asyncio.run(go())

    def test_zero_trust_write_contract(self):
        async def go():
            adapter = self._adapter()
            try:
                with pytest.raises(ValueError):
                    await adapter.record_event(
                        kind="live.bad",
                        session_id=self._ns(),
                        agent_id=None,
                        payload={},
                        confidence=2.0,
                        provenance="pytest",
                    )
                with pytest.raises(ValueError):
                    await adapter.record_event(
                        kind="live.bad",
                        session_id=self._ns(),
                        agent_id=None,
                        payload={},
                        confidence=0.5,
                        provenance="",
                    )
            finally:
                await adapter.close()

        asyncio.run(go())

    def test_write_narrative_and_lexical_search(self):
        async def go():
            adapter = self._adapter()
            ns = self._ns()
            try:
                nid = await adapter.write_narrative(
                    session_id=ns,
                    agent_id="a1",
                    title="Refactor session FSM",
                    body="Split state_machine.py into StateGraph and "
                    "TransitionValidator; added property tests.",
                    tags=("refactor", "fsm"),
                    embedding=None,
                    confidence=0.9,
                    provenance="tektos_reflection",
                )
                assert isinstance(nid, str) and len(nid) == 36
                hits = await adapter.search_narratives(
                    query="refactor state_machine", session_id=ns
                )
                assert len(hits) == 1
                assert isinstance(hits[0], NarrativeHit)
                assert hits[0].tags == ("refactor", "fsm")
                assert hits[0].score > 0.0
            finally:
                await adapter.close()

        asyncio.run(go())

    def test_write_narrative_with_embedding_and_hybrid_search(self):
        async def go():
            adapter = self._adapter(embedding_dim=1536) if False else self._adapter()
            ns = self._ns()
            emb = tuple([0.01] * 1536)
            try:
                await adapter.write_narrative(
                    session_id=ns,
                    agent_id="a1",
                    title="Hybrid demo",
                    body="pgvector hnsw plus tsvector fusion via RRF.",
                    tags=("hybrid",),
                    embedding=emb,
                    confidence=1.0,
                    provenance="pytest",
                )
                hits = await adapter.search_narratives(
                    query="pgvector fusion",
                    embedding=emb,
                    session_id=ns,
                )
                assert len(hits) == 1
                assert hits[0].score > 0.0
            finally:
                await adapter.close()

        asyncio.run(go())

    def test_transaction_rollback(self):
        async def go():
            adapter = self._adapter()
            ns = self._ns()
            try:
                with pytest.raises(RuntimeError, match="boom"):
                    async with adapter.transaction() as tx:
                        await tx.record_event(
                            kind="live.tx",
                            session_id=ns,
                            agent_id=None,
                            payload={},
                            confidence=1.0,
                            provenance="pytest",
                        )
                        raise RuntimeError("boom")
                rows = await adapter.query_events(session_id=ns, kind_prefix="live.tx")
                assert rows == ()
            finally:
                await adapter.close()

        asyncio.run(go())
