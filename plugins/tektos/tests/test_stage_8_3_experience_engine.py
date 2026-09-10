"""Stage 8.3 · ADR-105 contract tests — experience-replay engine."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from plugins.tektos.experience import (
    TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE,
    TEKTOS_EXPERIENCE_PREDICATE,
    TEKTOS_EXPERIENCE_PROVENANCE,
    ExperienceRecord,
    ExperienceReplay,
)


class _FakeRelMem:
    def __init__(
        self,
        *,
        raise_on: str | None = None,
        search_hits: tuple = (),
    ) -> None:
        self.writes: list[dict] = []
        self.raise_on = raise_on
        self.search_hits = search_hits

    async def write_narrative(self, **kwargs):
        self.writes.append(kwargs)
        if self.raise_on == "write":
            raise RuntimeError("boom")
        return f"nar-{len(self.writes)}"

    async def search_narratives(self, **_kwargs):
        if self.raise_on == "search":
            raise RuntimeError("boom-search")
        return self.search_hits


class _FakeBus:
    def __init__(self, *, raise_on_publish: bool = False) -> None:
        self.published: list = []
        self.raise_on_publish = raise_on_publish

    async def publish(self, envelope):
        if self.raise_on_publish:
            raise RuntimeError("boom")
        self.published.append(envelope)
        return "ev-1"


# ---------------------------------------------------------------------------
# ADR-105 D4 locked constants


def test_experience_locked_constants_have_locked_values():
    assert TEKTOS_EXPERIENCE_PROVENANCE == "tektos.experience"
    assert TEKTOS_EXPERIENCE_PREDICATE == "tektos.experience.recorded"
    assert TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE == 0.75


# ---------------------------------------------------------------------------
# Dataclass + construction


def test_experience_record_is_frozen_and_slotted_with_summary():
    r = ExperienceRecord(insight_type="failure", guidance="try smaller batches")
    assert dataclasses.is_dataclass(r)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.guidance = "x"  # type: ignore[misc]
    assert r.summary.startswith("[failure]")
    assert r.id.startswith("exp-")


def test_experience_engine_unbound_and_bound_construction():
    assert ExperienceReplay().is_persistence_bound is False
    assert (
        ExperienceReplay(relational_memory=_FakeRelMem(), event_bus=_FakeBus()).is_persistence_bound
        is True
    )


# ---------------------------------------------------------------------------
# Record path


@pytest.mark.asyncio
async def test_experience_record_writes_narrative_with_locked_provenance():
    rmem = _FakeRelMem()
    bus = _FakeBus()
    eng = ExperienceReplay(relational_memory=rmem, event_bus=bus)
    rec, nid = await eng.record(
        session_id="s1",
        synthesis={"spec_id": "sp1", "synthesis": "try smaller", "context": "coding"},
    )
    assert nid == "nar-1"
    call = rmem.writes[0]
    assert call["provenance"] == TEKTOS_EXPERIENCE_PROVENANCE
    assert call["agent_id"] == TEKTOS_EXPERIENCE_PROVENANCE
    assert call["title"].startswith(f"{TEKTOS_EXPERIENCE_PREDICATE}:")
    assert TEKTOS_EXPERIENCE_PROVENANCE in call["tags"]
    assert "coding" in call["tags"]
    # Body is JSON-serialized record
    payload = json.loads(call["body"])
    assert payload["cycle_id"] == "sp1"
    assert payload["guidance"] == "try smaller"
    # Event
    env = bus.published[0]
    assert env.event_type == TEKTOS_EXPERIENCE_PREDICATE
    assert env.producer_plugin == TEKTOS_EXPERIENCE_PROVENANCE
    assert env.payload["cycle_id"] == "sp1"
    assert env.payload["narrative_id"] == "nar-1"
    assert rec.cycle_id == "sp1"


@pytest.mark.asyncio
async def test_experience_record_fail_open_when_write_narrative_raises():
    rmem = _FakeRelMem(raise_on="write")
    bus = _FakeBus()
    eng = ExperienceReplay(relational_memory=rmem, event_bus=bus)
    rec, nid = await eng.record(
        session_id="s1",
        synthesis={"spec_id": "sp2", "synthesis": "x", "context": "coding"},
    )
    assert nid is None
    assert rec is not None
    assert bus.published and bus.published[0].payload["narrative_id"] is None


@pytest.mark.asyncio
async def test_experience_record_fail_open_when_event_bus_raises():
    rmem = _FakeRelMem()
    bus = _FakeBus(raise_on_publish=True)
    eng = ExperienceReplay(relational_memory=rmem, event_bus=bus)
    rec, nid = await eng.record(
        session_id="s1",
        synthesis={"spec_id": "sp3", "synthesis": "x", "context": "coding"},
    )
    assert nid == "nar-1"
    assert rec is not None


# ---------------------------------------------------------------------------
# Recall path


@pytest.mark.asyncio
async def test_experience_recall_from_port_reconstructs_records_from_body():
    body = json.dumps(
        {
            "id": "exp-abc",
            "cycle_id": "sp1",
            "insight_type": "synthesis",
            "what_happened": "wh",
            "what_was_expected": "we",
            "guidance": "avoid X",
            "context": "coding",
            "confidence": 0.8,
            "priority": "high",
            "timestamp": "2026-09-10T00:00:00+00:00",
            "tags": ["tektos.experience", "coding"],
        }
    )
    hit = SimpleNamespace(
        narrative_id="n1",
        session_id="s1",
        agent_id="tektos.experience",
        title="tektos.experience.recorded:exp-abc",
        body=body,
        tags=("tektos.experience", "coding"),
        confidence=0.8,
        provenance="tektos.experience",
        score=1.0,
    )
    rmem = _FakeRelMem(search_hits=(hit,))
    eng = ExperienceReplay(relational_memory=rmem)
    recalled = await eng.recall(context="coding", limit=5)
    assert len(recalled) == 1
    assert recalled[0].cycle_id == "sp1"
    assert recalled[0].guidance == "avoid X"
    assert recalled[0].confidence == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_experience_recall_falls_back_to_buffer_when_port_raises():
    rmem = _FakeRelMem(raise_on="search")
    eng = ExperienceReplay(relational_memory=rmem)
    # Populate buffer directly via record (fail-open write also OK — buffer always populated)
    await eng.record(
        session_id="s1",
        synthesis={"spec_id": "sp7", "synthesis": "x", "context": "coding"},
    )
    recalled = await eng.recall(context="coding", limit=5)
    assert len(recalled) == 1
    assert recalled[0].cycle_id == "sp7"


@pytest.mark.asyncio
async def test_experience_recall_memory_only_context_filter():
    eng = ExperienceReplay()
    await eng.record(session_id="s1", synthesis={"spec_id": "a", "context": "coding"})
    await eng.record(session_id="s1", synthesis={"spec_id": "b", "context": "planning"})
    coding = await eng.recall(context="coding", limit=10)
    planning = await eng.recall(context="planning", limit=10)
    assert [r.cycle_id for r in coding] == ["a"]
    assert [r.cycle_id for r in planning] == ["b"]


@pytest.mark.asyncio
async def test_experience_recall_limit_zero_returns_empty():
    eng = ExperienceReplay()
    await eng.record(session_id="s1", synthesis={"spec_id": "a", "context": "coding"})
    assert await eng.recall(context="coding", limit=0) == ()


def test_experience_recent_returns_buffer_regardless_of_context():
    eng = ExperienceReplay()
    eng._buffer.append(ExperienceRecord(cycle_id="a", context="coding"))  # type: ignore[attr-defined]
    eng._buffer.append(ExperienceRecord(cycle_id="b", context="planning"))  # type: ignore[attr-defined]
    assert [r.cycle_id for r in eng.recent(limit=5)] == ["a", "b"]
