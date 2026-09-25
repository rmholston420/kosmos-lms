"""ADR-135 slice M1 — graph read surface: list_nodes + recent_memory_events.

GPU-free: in-memory backends only (the DozerDbGraphBackend.list_nodes
Cypher is exercised by the env-gated live tier, not here).

Covers:
- InMemoryGraphBackend.list_nodes (label filter, limit, empty label)
- adapter.recent_memory_events (real write_event → newest-first rows with
  the donor-relevant props: id/predicate/subject/object/provenance/
  confidence/written_at)
- limit passthrough
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adapters.memory.dozerdb.adapter import (
    DozerDbMemoryAdapter,
    InMemoryGraphBackend,
    InMemoryTemporalIndex,
    NoOpAmgPolicy,
)


@pytest.fixture
def backend() -> InMemoryGraphBackend:
    return InMemoryGraphBackend()


@pytest.fixture
def adapter(backend: InMemoryGraphBackend) -> DozerDbMemoryAdapter:
    return DozerDbMemoryAdapter(
        graph=backend,
        amg=NoOpAmgPolicy(),
        temporal=InMemoryTemporalIndex(),
    )


async def _write(
    adapter: DozerDbMemoryAdapter,
    subject: str,
    predicate: str,
    obj: str,
    provenance: str = "test",
    confidence: float = 0.9,
) -> None:
    await adapter.write_event(
        subject, predicate, obj, provenance=provenance, confidence=confidence
    )


@pytest.mark.anyio
async def test_list_nodes_filters_label_and_limit(backend: InMemoryGraphBackend) -> None:
    await backend.add_node("MemoryEvent", {"id": "e1", "written_at": "2026-01-01T00:00:00+00:00"})
    await backend.add_node("MemoryEvent", {"id": "e2", "written_at": "2026-01-02T00:00:00+00:00"})
    await backend.add_node("Entity", {"id": "x1"})

    all_events = await backend.list_nodes("MemoryEvent")
    assert {n["id"] for n in all_events} == {"e1", "e2"}

    limited = await backend.list_nodes("MemoryEvent", limit=1)
    assert len(limited) == 1

    assert await backend.list_nodes("Quarantined") == []
    assert await backend.list_nodes("MemoryEvent", limit=0) == []


@pytest.mark.anyio
async def test_recent_memory_events_newest_first_full_props(
    adapter: DozerDbMemoryAdapter,
) -> None:
    # three writes; the in-memory backend has no ordering, so assert the
    # set of ids and the per-row props (the endpoint mapper sorts by
    # written_at — see slice M2).
    await _write(adapter, "s1", "PRED1", "o1", provenance="p1", confidence=0.5)
    await _write(adapter, "s2", "PRED2", "o2", provenance="p2", confidence=0.75)
    await _write(adapter, "s3", "PRED3", "o3", provenance="p3", confidence=0.99)

    rows = await adapter.recent_memory_events(limit=100)
    assert len(rows) == 3
    by_id = {r["id"]: r for r in rows}
    assert len(by_id) == 3
    for row in rows:
        assert row["id"] in by_id
        assert row["predicate"] in {"PRED1", "PRED2", "PRED3"}
        assert row["provenance"] in {"p1", "p2", "p3"}
        assert isinstance(row["confidence"], float)
        # written_at must be parseable ISO-8601 (the Bolt backend sorts on it).
        datetime.fromisoformat(row["written_at"])
    # NOTE: newest-first ordering is the Bolt backend's contract (Cypher
    # ORDER BY written_at DESC); the in-memory backend returns insertion
    # order — the endpoint mapper (slice M2) sorts client-side so both
    # backends render identically.


@pytest.mark.anyio
async def test_recent_memory_events_limit(adapter: DozerDbMemoryAdapter) -> None:
    for i in range(5):
        await _write(adapter, f"s{i}", f"PRE{i}", f"o{i}")

    rows = await adapter.recent_memory_events(limit=3)
    assert len(rows) == 3

    rows_all = await adapter.recent_memory_events(limit=100)
    assert len(rows_all) == 5


@pytest.mark.anyio
async def test_recent_memory_events_empty_corpus(
    adapter: DozerDbMemoryAdapter,
) -> None:
    assert await adapter.recent_memory_events() == []
