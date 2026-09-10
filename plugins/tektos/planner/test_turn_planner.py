"""Contract tests for ``TektosTurnPlanner`` (Stage 4.7 DoD, ADR-093).

DoD verb: "a scripted plan node round-trips through EventBusPort."
"""

from __future__ import annotations

import asyncio

import pytest

from plugins.tektos.planner import Plan, PlanNode, TektosTurnPlanner
from ports.event_envelope import EventEnvelope


class _RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return f"evt-{len(self.published)}"


def test_plan_returns_frozen_shape() -> None:
    planner = TektosTurnPlanner()
    plan = asyncio.run(planner.plan("hello"))
    assert isinstance(plan, Plan)
    assert isinstance(plan.nodes, tuple)
    assert len(plan) == 3
    for node in plan:
        assert isinstance(node, PlanNode)


def test_plan_shape_read_analyze_summarize() -> None:
    planner = TektosTurnPlanner()
    plan = asyncio.run(planner.plan("what is 2+2?"))
    kinds = [n.kind for n in plan]
    assert kinds == ["read", "analyze", "summarize"]
    # Linear dependency chain.
    assert plan.nodes[0].depends_on == ()
    assert plan.nodes[1].depends_on == (plan.nodes[0].node_id,)
    assert plan.nodes[2].depends_on == (plan.nodes[1].node_id,)


def test_plan_publishes_started_nodes_completed() -> None:
    bus = _RecordingEventBus()
    planner = TektosTurnPlanner(event_bus=bus)
    plan = asyncio.run(planner.plan("hi"))
    event_types = [env.event_type for env in bus.published]
    assert event_types[0] == "tektos.plan.started"
    assert event_types[-1] == "tektos.plan.completed"
    node_events = [env for env in bus.published if env.event_type == "tektos.plan.node"]
    assert len(node_events) == len(plan)
    for env in bus.published:
        assert env.producer_plugin == "tektos_planner"
        assert env.payload["source"] == "tektos_planner"
        assert env.payload["plan_id"] == plan.plan_id
        assert env.payload["correlation_id"] == plan.plan_id


def test_plan_empty_prompt_rejected() -> None:
    planner = TektosTurnPlanner()
    with pytest.raises(ValueError):
        asyncio.run(planner.plan("   "))
