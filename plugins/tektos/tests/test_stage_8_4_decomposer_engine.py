"""Stage 8.4 · ADR-106 contract tests — ``TaskDecomposer`` engine."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from plugins.tektos.decomposer import (
    TEKTOS_DECOMPOSER_PREDICATE,
    TEKTOS_DECOMPOSER_PROVENANCE,
    DecompositionPlan,
    TaskDecomposer,
)
from ports.event_envelope import EventEnvelope


class _StubRMem:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write_narrative(self, **kwargs: Any) -> str:  # noqa: ANN401
        self.writes.append(kwargs)
        return f"nar-{len(self.writes)}"


class _StubRMemRaise:
    async def write_narrative(self, **kwargs: Any) -> str:  # noqa: ANN401
        raise RuntimeError("kaboom")


class _StubBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return "evt-1"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.mark.parametrize(
    "task,expected_count",
    [
        ("build the chess engine with cmake", 6),
        ("write a function that adds two numbers", 3),
        ("build chess move generator via regex", 6),  # 'build' matches first
        ("generate a regex parser for FEN notation", 3),
        ("download and build the source from git clone", 6),  # 'build' first
        ("clone the repo and tarball it", 6),  # 'download_build' via clone
        ("what is the weather", 4),  # generic
    ],
)
def test_branch_routing_produces_expected_subtask_count(
    task: str, expected_count: int
) -> None:
    dec = TaskDecomposer()
    plan, _ = _run(dec.decompose(session_id="s1", task=task))
    assert len(plan.sub_tasks) == expected_count


def test_unbound_engine_populates_ring_buffer_and_returns_none_narrative_id() -> None:
    dec = TaskDecomposer()
    plan, nid = _run(dec.decompose(session_id="s1", task="write hello world"))
    assert nid is None
    assert dec.is_persistence_bound is False
    recent = dec.list_recent(limit=5)
    assert len(recent) == 1
    assert recent[0].id == plan.id


def test_bound_engine_persists_via_write_narrative_with_locked_provenance() -> None:
    rmem = _StubRMem()
    dec = TaskDecomposer(relational_memory=rmem)
    plan, nid = _run(dec.decompose(session_id="s1", task="write hello world"))
    assert nid == "nar-1"
    w = rmem.writes[0]
    assert w["provenance"] == TEKTOS_DECOMPOSER_PROVENANCE
    assert w["agent_id"] == TEKTOS_DECOMPOSER_PROVENANCE
    assert w["title"].startswith(f"{TEKTOS_DECOMPOSER_PREDICATE}:")
    assert 0.0 < w["confidence"] <= 1.0
    body = json.loads(w["body"])
    assert body["id"] == plan.id
    assert len(body["sub_tasks"]) == len(plan.sub_tasks)


def test_bound_engine_publishes_event_envelope_with_locked_predicate() -> None:
    bus = _StubBus()
    dec = TaskDecomposer(relational_memory=_StubRMem(), event_bus=bus)
    plan, _ = _run(dec.decompose(session_id="s1", task="write hello world"))
    env = bus.published[0]
    assert env.event_type == TEKTOS_DECOMPOSER_PREDICATE
    assert env.producer_plugin == TEKTOS_DECOMPOSER_PROVENANCE
    assert env.payload["plan_id"] == plan.id


def test_write_narrative_failure_kept_in_memory_buffer_fail_open() -> None:
    dec = TaskDecomposer(relational_memory=_StubRMemRaise())
    plan, nid = _run(dec.decompose(session_id="s1", task="write hello world"))
    assert nid is None
    assert dec.list_recent(limit=1)[0].id == plan.id


def test_format_for_prompt_contains_task_and_steps() -> None:
    dec = TaskDecomposer()
    plan, _ = _run(dec.decompose(session_id="s1", task="write hello world"))
    prompt = TaskDecomposer.format_for_prompt(plan)
    assert "TASK DECOMPOSITION" in prompt
    assert plan.original_task in prompt
    assert "Step 1" in prompt
    assert "IMPORTANT RULES" in prompt


def test_sub_tasks_are_immutable_frozen_dataclasses() -> None:
    dec = TaskDecomposer()
    plan, _ = _run(dec.decompose(session_id="s1", task="write hello world"))
    with pytest.raises((AttributeError, TypeError, Exception)):
        plan.sub_tasks[0].status = "complete"  # type: ignore[misc]
    assert isinstance(plan, DecompositionPlan)
