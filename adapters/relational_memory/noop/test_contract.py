"""Contract tests for NoOpRelationalMemoryAdapter (ADR-102 Stage 8.0).

Fast-tier: uses aiosqlite in-memory, no external dependencies. Runs in the
standard baseline suite (targets: 1462 -> 1462+N passed, 0 failed).

Coverage:

1. Protocol conformance — the adapter satisfies isinstance(...,
   RelationalMemoryPort) at runtime.
2. Zero-trust write contract — invalid confidence + provenance are rejected
   at the port layer per ADR-102 D4.
3. Ledger round-trip — record_event -> query_events with each filter dim.
4. Narrative round-trip — write_narrative -> search_narratives with each
   filter dim + honest-degrade on embedding.
5. Transaction atomicity — an exception inside transaction() rolls back.
6. Health + close idempotency.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from adapters.relational_memory.noop import NoOpRelationalMemoryAdapter
from ports.relational_memory import (
    LedgerRow,
    NarrativeHit,
    RelationalMemoryPort,
    validate_confidence,
    validate_provenance,
)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_adapter_satisfies_port_protocol():
    """isinstance check against runtime_checkable Protocol (ADR-102)."""
    adapter = NoOpRelationalMemoryAdapter()
    assert isinstance(adapter, RelationalMemoryPort)


# ---------------------------------------------------------------------------
# Zero-trust write contract (ADR-102 D4)
# ---------------------------------------------------------------------------


class TestValidators:
    def test_confidence_below_zero_rejects(self):
        with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
            validate_confidence(-0.01)

    def test_confidence_above_one_rejects(self):
        with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
            validate_confidence(1.5)

    def test_confidence_string_rejects(self):
        with pytest.raises(ValueError, match=r"numeric"):
            validate_confidence("0.5")  # type: ignore[arg-type]

    def test_confidence_int_accepted_as_bound(self):
        validate_confidence(1)   # OK
        validate_confidence(0)   # OK

    def test_provenance_empty_rejects(self):
        with pytest.raises(ValueError, match=r"non-empty"):
            validate_provenance("")

    def test_provenance_whitespace_rejects(self):
        with pytest.raises(ValueError, match=r"non-empty"):
            validate_provenance("   ")

    def test_provenance_non_string_rejects(self):
        with pytest.raises(ValueError, match=r"str"):
            validate_provenance(42)  # type: ignore[arg-type]


class TestRecordEventValidation:
    def _adapter(self):
        return NoOpRelationalMemoryAdapter()

    def test_record_event_rejects_bad_confidence(self):
        adapter = self._adapter()

        async def go():
            with pytest.raises(ValueError):
                await adapter.record_event(
                    kind="test.kind",
                    session_id=None,
                    agent_id=None,
                    payload={},
                    confidence=2.0,
                    provenance="test",
                )

        asyncio.run(go())

    def test_record_event_rejects_empty_provenance(self):
        adapter = self._adapter()

        async def go():
            with pytest.raises(ValueError):
                await adapter.record_event(
                    kind="test.kind",
                    session_id=None,
                    agent_id=None,
                    payload={},
                    confidence=0.5,
                    provenance="",
                )

        asyncio.run(go())

    def test_record_event_rejects_empty_kind(self):
        adapter = self._adapter()

        async def go():
            with pytest.raises(ValueError):
                await adapter.record_event(
                    kind="",
                    session_id=None,
                    agent_id=None,
                    payload={},
                    confidence=0.5,
                    provenance="test",
                )

        asyncio.run(go())


# ---------------------------------------------------------------------------
# Ledger round-trip
# ---------------------------------------------------------------------------


class TestLedgerRoundTrip:
    def test_record_and_query_by_kind_prefix(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            eid1 = await adapter.record_event(
                kind="tool.invoked",
                session_id="s1",
                agent_id="a1",
                payload={"tool": "file_read"},
                confidence=1.0,
                provenance="tektos_tool",
            )
            eid2 = await adapter.record_event(
                kind="tool.approved",
                session_id="s1",
                agent_id="a1",
                payload={"tool": "file_write"},
                confidence=1.0,
                provenance="tektos_tool",
            )
            eid3 = await adapter.record_event(
                kind="immune.verdict.block",
                session_id="s1",
                agent_id="a1",
                payload={"detector": "SecretExposureDetector"},
                confidence=1.0,
                provenance="immune_verdict",
            )
            assert isinstance(eid1, str) and len(eid1) > 0
            assert eid1 != eid2 != eid3

            # kind_prefix filter
            tool_rows = await adapter.query_events(kind_prefix="tool.")
            assert len(tool_rows) == 2
            assert all(r.kind.startswith("tool.") for r in tool_rows)
            assert all(isinstance(r, LedgerRow) for r in tool_rows)

            immune_rows = await adapter.query_events(kind_prefix="immune.")
            assert len(immune_rows) == 1
            assert immune_rows[0].kind == "immune.verdict.block"
            assert immune_rows[0].payload["detector"] == "SecretExposureDetector"

            await adapter.close()

        asyncio.run(go())

    def test_query_events_time_range(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            t0 = datetime.now(timezone.utc)
            await adapter.record_event(
                kind="k",
                session_id=None,
                agent_id=None,
                payload={},
                confidence=1.0,
                provenance="t",
            )
            t1 = datetime.now(timezone.utc) + timedelta(seconds=1)
            past = await adapter.query_events(until=t0)
            future = await adapter.query_events(since=t1)
            assert past == ()
            assert future == ()
            all_rows = await adapter.query_events()
            assert len(all_rows) == 1
            await adapter.close()

        asyncio.run(go())

    def test_query_events_session_and_agent_filter(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            await adapter.record_event(
                kind="k",
                session_id="s1",
                agent_id="a1",
                payload={},
                confidence=1.0,
                provenance="t",
            )
            await adapter.record_event(
                kind="k",
                session_id="s2",
                agent_id="a2",
                payload={},
                confidence=1.0,
                provenance="t",
            )
            s1 = await adapter.query_events(session_id="s1")
            a2 = await adapter.query_events(agent_id="a2")
            assert len(s1) == 1 and s1[0].session_id == "s1"
            assert len(a2) == 1 and a2[0].agent_id == "a2"
            await adapter.close()

        asyncio.run(go())

    def test_query_events_limit_cap(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            for i in range(5):
                await adapter.record_event(
                    kind=f"k{i}",
                    session_id=None,
                    agent_id=None,
                    payload={},
                    confidence=1.0,
                    provenance="t",
                )
            rows = await adapter.query_events(limit=3)
            assert len(rows) == 3
            zero = await adapter.query_events(limit=0)
            assert zero == ()
            await adapter.close()

        asyncio.run(go())


# ---------------------------------------------------------------------------
# Narrative round-trip
# ---------------------------------------------------------------------------


class TestNarrativeRoundTrip:
    def test_write_and_search_by_body(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            nid = await adapter.write_narrative(
                session_id="s1",
                agent_id="a1",
                title="Refactor auth module",
                body="Split auth.py into token.py and session.py; added tests.",
                tags=("refactor", "auth"),
                embedding=None,
                confidence=0.9,
                provenance="tektos_reflection",
            )
            assert isinstance(nid, str)

            hits = await adapter.search_narratives(query="refactor")
            assert len(hits) == 1
            assert isinstance(hits[0], NarrativeHit)
            assert hits[0].title == "Refactor auth module"
            assert hits[0].tags == ("refactor", "auth")
            assert hits[0].confidence == 0.9
            assert hits[0].provenance == "tektos_reflection"

            miss = await adapter.search_narratives(query="nonexistent")
            assert miss == ()

            await adapter.close()

        asyncio.run(go())

    def test_search_narratives_embedding_honest_degrade(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter(embedding_dim=4)
            await adapter.write_narrative(
                session_id="s1",
                agent_id=None,
                title="X",
                body="hello world",
                tags=(),
                embedding=(0.1, 0.2, 0.3, 0.4),
                confidence=0.5,
                provenance="test",
            )
            # Passing embedding is IGNORED per ADR-098-style honest degrade;
            # the search still succeeds using pure lexical.
            hits = await adapter.search_narratives(
                query="hello", embedding=(0.9, 0.8, 0.7, 0.6)
            )
            assert len(hits) == 1
            await adapter.close()

        asyncio.run(go())

    def test_write_narrative_embedding_dim_mismatch(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter(embedding_dim=4)
            with pytest.raises(ValueError, match=r"embedding dim"):
                await adapter.write_narrative(
                    session_id="s1",
                    agent_id=None,
                    title="X",
                    body="",
                    tags=(),
                    embedding=(0.1, 0.2, 0.3),  # wrong dim
                    confidence=0.5,
                    provenance="test",
                )
            await adapter.close()

        asyncio.run(go())

    def test_search_narratives_tags_filter(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            await adapter.write_narrative(
                session_id="s",
                agent_id=None,
                title="A",
                body="apple",
                tags=("fruit", "red"),
                embedding=None,
                confidence=1.0,
                provenance="t",
            )
            await adapter.write_narrative(
                session_id="s",
                agent_id=None,
                title="B",
                body="banana",
                tags=("fruit", "yellow"),
                embedding=None,
                confidence=1.0,
                provenance="t",
            )
            red_hits = await adapter.search_narratives(query="", tags=("red",))
            assert len(red_hits) == 1 and red_hits[0].title == "A"
            fruit_hits = await adapter.search_narratives(query="", tags=("fruit",))
            assert len(fruit_hits) == 2
            await adapter.close()

        asyncio.run(go())


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactionAtomicity:
    def test_transaction_rolls_back_on_exception(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            with pytest.raises(RuntimeError, match="boom"):
                async with adapter.transaction() as tx:
                    await tx.record_event(
                        kind="tx.test",
                        session_id="s1",
                        agent_id=None,
                        payload={},
                        confidence=1.0,
                        provenance="test",
                    )
                    raise RuntimeError("boom")
            # After rollback, the event should NOT be visible.
            rows = await adapter.query_events(kind_prefix="tx.")
            assert rows == ()
            await adapter.close()

        asyncio.run(go())

    def test_transaction_commits_on_success(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            async with adapter.transaction() as tx:
                await tx.record_event(
                    kind="tx.commit",
                    session_id="s1",
                    agent_id=None,
                    payload={},
                    confidence=1.0,
                    provenance="test",
                )
            rows = await adapter.query_events(kind_prefix="tx.")
            assert len(rows) == 1
            await adapter.close()

        asyncio.run(go())


# ---------------------------------------------------------------------------
# Health + close
# ---------------------------------------------------------------------------


class TestHealthAndClose:
    def test_is_healthy_true(self):
        adapter = NoOpRelationalMemoryAdapter()
        assert adapter.is_healthy() is True

    def test_close_idempotent(self):
        async def go():
            adapter = NoOpRelationalMemoryAdapter()
            await adapter.record_event(
                kind="k",
                session_id=None,
                agent_id=None,
                payload={},
                confidence=1.0,
                provenance="t",
            )
            await adapter.close()
            await adapter.close()  # idempotent

        asyncio.run(go())
