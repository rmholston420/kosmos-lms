"""Stage 8.3 · ADR-105 contract tests — reflection engine.

Covers:
- locked-constant values (D4)
- ``ReflectionInsight`` / ``ReflectionState`` frozen invariants
- engine construction with / without ports
- rule-based ``_generate_insight_for_turn`` classification
- ``reflect_on_turn`` write-narrative + event-bus wiring
- fail-open persistence + event-bus (ADR-101)
- ``examine_direct_experience`` + ``check_for_biases`` preservation
"""

from __future__ import annotations

import dataclasses

import pytest

from plugins.tektos.reflection import (
    TEKTOS_REFLECTION_DEFAULT_CONFIDENCE,
    TEKTOS_REFLECTION_PREDICATE,
    TEKTOS_REFLECTION_PROVENANCE,
    ReflectionEngine,
    ReflectionInsight,
    ReflectionState,
)


# ---------------------------------------------------------------------------
# Fakes


class _FakeRelMem:
    def __init__(self, *, raise_on: str | None = None) -> None:
        self.calls: list[dict] = []
        self.raise_on = raise_on

    async def write_narrative(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_on == "write":
            raise RuntimeError("boom-write")
        return f"nar-{len(self.calls)}"

    async def search_narratives(self, **_kwargs):
        return ()


class _FakeBus:
    def __init__(self, *, raise_on_publish: bool = False) -> None:
        self.published: list = []
        self.raise_on_publish = raise_on_publish

    async def publish(self, envelope):
        if self.raise_on_publish:
            raise RuntimeError("boom-publish")
        self.published.append(envelope)
        return "ev-1"


# ---------------------------------------------------------------------------
# ADR-105 D4 locked constants


def test_reflection_locked_constants_have_locked_values():
    assert TEKTOS_REFLECTION_PROVENANCE == "tektos.reflection"
    assert TEKTOS_REFLECTION_PREDICATE == "tektos.reflection.completed"
    assert TEKTOS_REFLECTION_DEFAULT_CONFIDENCE == 0.75


# ---------------------------------------------------------------------------
# Dataclass invariants


def test_reflection_insight_is_frozen_and_slotted():
    insight = ReflectionInsight(content="x")
    assert dataclasses.is_dataclass(insight)
    with pytest.raises(dataclasses.FrozenInstanceError):
        insight.content = "y"  # type: ignore[misc]


def test_reflection_state_is_frozen_and_slotted():
    state = ReflectionState()
    assert dataclasses.is_dataclass(state)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.insights_generated = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Engine construction


def test_reflection_engine_construction_with_no_ports_is_unbound():
    eng = ReflectionEngine()
    assert eng.is_persistence_bound is False


def test_reflection_engine_construction_with_ports_is_bound():
    eng = ReflectionEngine(relational_memory=_FakeRelMem(), event_bus=_FakeBus())
    assert eng.is_persistence_bound is True


# ---------------------------------------------------------------------------
# Rule-based classification


@pytest.mark.asyncio
async def test_reflection_llm_error_yields_failure_pattern():
    eng = ReflectionEngine()
    insight, nid = await eng.reflect_on_turn(
        session_id="s1", turn_outcome={"stop_reason": "llm_error", "error": "boom"}
    )
    assert insight.insight_type == "failure_pattern"
    assert insight.trust_score == pytest.approx(0.95)
    assert nid is None


@pytest.mark.asyncio
async def test_reflection_resource_exhausted_yields_resource_pressure():
    eng = ReflectionEngine()
    insight, _ = await eng.reflect_on_turn(
        session_id="s1",
        turn_outcome={"stop_reason": "resource_pressure", "resource_exhausted": True},
    )
    assert insight.insight_type == "resource_pressure"


@pytest.mark.asyncio
async def test_reflection_all_rejected_yields_tool_gating_pattern():
    eng = ReflectionEngine()
    insight, _ = await eng.reflect_on_turn(
        session_id="s1",
        turn_outcome={
            "stop_reason": "immune_reject",
            "tool_outcomes": [
                {"accepted": False},
                {"accepted": False},
                {"accepted": False},
            ],
        },
    )
    assert insight.insight_type == "tool_gating_pattern"


@pytest.mark.asyncio
async def test_reflection_clean_completion_yields_clean_completion():
    eng = ReflectionEngine()
    insight, _ = await eng.reflect_on_turn(
        session_id="s1",
        turn_outcome={"stop_reason": "ok", "tool_outcomes": [{"accepted": True}]},
    )
    assert insight.insight_type == "clean_completion"


# ---------------------------------------------------------------------------
# Persistence + event-bus wiring


@pytest.mark.asyncio
async def test_reflection_writes_narrative_with_locked_provenance_and_confidence():
    rmem = _FakeRelMem()
    bus = _FakeBus()
    eng = ReflectionEngine(relational_memory=rmem, event_bus=bus)
    insight, nid = await eng.reflect_on_turn(
        session_id="s1", turn_outcome={"stop_reason": "ok"}
    )
    assert nid == "nar-1"
    assert len(rmem.calls) == 1
    call = rmem.calls[0]
    assert call["provenance"] == TEKTOS_REFLECTION_PROVENANCE
    assert call["agent_id"] == TEKTOS_REFLECTION_PROVENANCE
    assert call["confidence"] == pytest.approx(insight.trust_score)
    assert call["title"].startswith(f"{TEKTOS_REFLECTION_PREDICATE}:")
    assert TEKTOS_REFLECTION_PROVENANCE in call["tags"]
    assert len(bus.published) == 1
    env = bus.published[0]
    assert env.event_type == TEKTOS_REFLECTION_PREDICATE
    assert env.producer_plugin == TEKTOS_REFLECTION_PROVENANCE
    assert env.payload["narrative_id"] == "nar-1"


@pytest.mark.asyncio
async def test_reflection_fail_open_when_write_narrative_raises():
    rmem = _FakeRelMem(raise_on="write")
    bus = _FakeBus()
    eng = ReflectionEngine(relational_memory=rmem, event_bus=bus)
    insight, nid = await eng.reflect_on_turn(
        session_id="s1", turn_outcome={"stop_reason": "ok"}
    )
    # Insight still produced; narrative_id None; event still published.
    assert insight is not None
    assert nid is None
    assert len(bus.published) == 1
    assert bus.published[0].payload["narrative_id"] is None


@pytest.mark.asyncio
async def test_reflection_fail_open_when_event_bus_raises():
    rmem = _FakeRelMem()
    bus = _FakeBus(raise_on_publish=True)
    eng = ReflectionEngine(relational_memory=rmem, event_bus=bus)
    insight, nid = await eng.reflect_on_turn(
        session_id="s1", turn_outcome={"stop_reason": "ok"}
    )
    # Narrative still written; publish failure swallowed.
    assert nid == "nar-1"
    assert insight is not None


# ---------------------------------------------------------------------------
# Donor-preserved rule paths


def test_reflection_examine_direct_experience_flags_failure_content():
    insights = ReflectionEngine.examine_direct_experience(
        (
            {"content": "tool call failed with error", "source": "exec"},
        )
    )
    assert any(i.insight_type == "failure_pattern" for i in insights)
    assert all(i.is_direct_experience is True for i in insights)


def test_reflection_check_for_biases_flags_speculation_when_right_heavy():
    obs = tuple([{"hemisphere": "right"}] * 9 + [{"hemisphere": "left"}])
    insights = ReflectionEngine.check_for_biases(obs)
    assert insights and insights[0].bias_detected == "speculation_bias"
