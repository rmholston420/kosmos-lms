"""Stage 8.3 · ADR-105 contract tests — synthesis engine."""

from __future__ import annotations

import dataclasses

import pytest

from plugins.tektos.synthesis import (
    TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE,
    TEKTOS_SYNTHESIS_PREDICATE,
    TEKTOS_SYNTHESIS_PROVENANCE,
    SynthesisEngine,
    SynthesisResult,
)


class _FakeRelMem:
    def __init__(self, *, raise_on: str | None = None) -> None:
        self.calls: list[dict] = []
        self.raise_on = raise_on

    async def write_narrative(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_on == "write":
            raise RuntimeError("boom")
        return f"nar-{len(self.calls)}"

    async def search_narratives(self, **_kwargs):
        return ()


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


def test_synthesis_locked_constants_have_locked_values():
    assert TEKTOS_SYNTHESIS_PROVENANCE == "tektos.synthesis"
    assert TEKTOS_SYNTHESIS_PREDICATE == "tektos.synthesis.completed"
    assert TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE == 0.75


# ---------------------------------------------------------------------------
# Dataclass + construction


def test_synthesis_result_is_frozen_and_slotted():
    r = SynthesisResult(spec_id="x", synthesis="y")
    assert dataclasses.is_dataclass(r)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.synthesis = "z"  # type: ignore[misc]


def test_synthesis_engine_unbound_and_bound_construction():
    assert SynthesisEngine().is_persistence_bound is False
    assert (
        SynthesisEngine(relational_memory=_FakeRelMem(), event_bus=_FakeBus()).is_persistence_bound
        is True
    )


# ---------------------------------------------------------------------------
# Rule-based classification


@pytest.mark.asyncio
async def test_synthesis_error_yields_error_pattern_and_high_priority():
    eng = SynthesisEngine()
    result, _ = await eng.synthesize(
        session_id="s1",
        spec={"id": "sp1", "description": "do x"},
        execution_feedback={"stop_reason": "llm_error", "error": "boom"},
    )
    assert result.insight_type == "error_pattern"
    assert result.priority == "high"
    assert result.is_actionable is True
    assert result.confidence == pytest.approx(TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE)


@pytest.mark.asyncio
async def test_synthesis_governance_rejection_yields_lesson_and_recommendation():
    eng = SynthesisEngine()
    result, _ = await eng.synthesize(
        session_id="s1",
        spec={"id": "sp2", "description": "wide edits"},
        execution_feedback={
            "stop_reason": "immune_reject",
            "tool_outcomes": [
                {"accepted": False},
                {"accepted": False},
                {"accepted": True},
            ],
        },
    )
    assert result.lessons
    assert result.recommendations
    assert any("governance" in ln.lower() or "rejected" in ln.lower() for ln in result.lessons)


@pytest.mark.asyncio
async def test_synthesis_clean_run_yields_positive_confirmation():
    eng = SynthesisEngine()
    result, _ = await eng.synthesize(
        session_id="s1",
        spec={"id": "sp3", "description": "small change"},
        execution_feedback={
            "stop_reason": "ok",
            "tool_outcomes": [{"accepted": True}],
        },
    )
    assert result.insight_type == "positive_confirmation"
    assert result.priority == "normal"


# ---------------------------------------------------------------------------
# Persistence + event-bus wiring


@pytest.mark.asyncio
async def test_synthesis_writes_narrative_with_locked_provenance():
    rmem = _FakeRelMem()
    bus = _FakeBus()
    eng = SynthesisEngine(relational_memory=rmem, event_bus=bus)
    result, nid = await eng.synthesize(
        session_id="s1",
        spec={"id": "sp4", "description": "x"},
        execution_feedback={"stop_reason": "ok", "tool_outcomes": [{"accepted": True}]},
    )
    assert nid == "nar-1"
    call = rmem.calls[0]
    assert call["provenance"] == TEKTOS_SYNTHESIS_PROVENANCE
    assert call["agent_id"] == TEKTOS_SYNTHESIS_PROVENANCE
    assert call["title"].startswith(f"{TEKTOS_SYNTHESIS_PREDICATE}:")
    assert TEKTOS_SYNTHESIS_PROVENANCE in call["tags"]
    env = bus.published[0]
    assert env.event_type == TEKTOS_SYNTHESIS_PREDICATE
    assert env.producer_plugin == TEKTOS_SYNTHESIS_PROVENANCE
    assert env.payload["spec_id"] == "sp4"
    assert env.payload["narrative_id"] == "nar-1"


@pytest.mark.asyncio
async def test_synthesis_fail_open_when_write_narrative_raises():
    rmem = _FakeRelMem(raise_on="write")
    bus = _FakeBus()
    eng = SynthesisEngine(relational_memory=rmem, event_bus=bus)
    result, nid = await eng.synthesize(
        session_id="s1",
        spec={"id": "sp5", "description": "x"},
        execution_feedback={"stop_reason": "ok"},
    )
    assert result is not None
    assert nid is None
    assert bus.published and bus.published[0].payload["narrative_id"] is None


@pytest.mark.asyncio
async def test_synthesis_fail_open_when_event_bus_raises():
    rmem = _FakeRelMem()
    bus = _FakeBus(raise_on_publish=True)
    eng = SynthesisEngine(relational_memory=rmem, event_bus=bus)
    result, nid = await eng.synthesize(
        session_id="s1",
        spec={"id": "sp6", "description": "x"},
        execution_feedback={"stop_reason": "ok", "tool_outcomes": [{"accepted": True}]},
    )
    assert result is not None
    assert nid == "nar-1"


def test_synthesis_recent_returns_ring_buffer_contents():
    eng = SynthesisEngine(max_records=3)
    # populate manually via internal buffer to avoid coroutines
    eng._recent.append(SynthesisResult(spec_id="a", synthesis="s"))  # type: ignore[attr-defined]
    eng._recent.append(SynthesisResult(spec_id="b", synthesis="s"))  # type: ignore[attr-defined]
    assert [r.spec_id for r in eng.recent(limit=10)] == ["a", "b"]
