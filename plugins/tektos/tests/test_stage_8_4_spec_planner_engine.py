"""Stage 8.4 · ADR-106 contract tests — ``TektosSpecPlanner`` engine.

Covers unbound (in-memory ring buffer), bound (RelationalMemoryPort stub),
EventBus publish shape, and fail-open behaviour when the port raises.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from plugins.tektos.planner import (
    TEKTOS_SPEC_PLANNER_PREDICATE,
    TEKTOS_SPEC_PLANNER_PROVENANCE,
    LanguageGame,
    TektosSpecPlanner,
)
from ports.event_envelope import EventEnvelope


class _StubRMem:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

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
        self.writes.append(
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "title": title,
                "body": body,
                "tags": tags,
                "embedding": embedding,
                "confidence": confidence,
                "provenance": provenance,
            }
        )
        return f"nar-{len(self.writes)}"


class _StubRMemRaise(_StubRMem):
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


def test_unbound_engine_populates_ring_buffer_and_returns_none_narrative_id() -> None:
    engine = TektosSpecPlanner()
    out, nid = _run(
        engine.generate_spec(session_id="s1", prompt="build me a fast api with auth")
    )
    assert nid is None
    assert engine.is_persistence_bound is False
    assert out.spec.description
    assert out.language_game_detected == LanguageGame.SOFTWARE_ENGINEERING
    recent = engine.list_recent(limit=5)
    assert len(recent) == 1
    assert recent[0].spec.id == out.spec.id


def test_bound_engine_persists_via_write_narrative_with_locked_provenance() -> None:
    rmem = _StubRMem()
    engine = TektosSpecPlanner(relational_memory=rmem)
    out, nid = _run(
        engine.generate_spec(
            session_id="s42",
            prompt="create a scalable microservice with authentication",
        )
    )
    assert nid == "nar-1"
    assert len(rmem.writes) == 1
    w = rmem.writes[0]
    assert w["session_id"] == "s42"
    assert w["provenance"] == TEKTOS_SPEC_PLANNER_PROVENANCE
    assert w["agent_id"] == TEKTOS_SPEC_PLANNER_PROVENANCE
    assert w["title"].startswith(f"{TEKTOS_SPEC_PLANNER_PREDICATE}:")
    assert 0.0 < w["confidence"] <= 1.0
    body = json.loads(w["body"])
    assert body["spec_id"] == out.spec.id
    assert body["spec"]["language_game"] == out.spec.language_game.value


def test_bound_engine_publishes_event_envelope_with_locked_predicate() -> None:
    bus = _StubBus()
    engine = TektosSpecPlanner(relational_memory=_StubRMem(), event_bus=bus)
    _run(engine.generate_spec(session_id="s7", prompt="build me an api"))
    assert len(bus.published) == 1
    env = bus.published[0]
    assert env.event_type == TEKTOS_SPEC_PLANNER_PREDICATE
    assert env.producer_plugin == TEKTOS_SPEC_PLANNER_PROVENANCE
    assert env.payload["session_id"] == "s7"


def test_write_narrative_failure_kept_in_memory_buffer_fail_open() -> None:
    """ADR-106 D9: engine never raises; narrative_id becomes None on failure."""
    engine = TektosSpecPlanner(relational_memory=_StubRMemRaise())
    out, nid = _run(engine.generate_spec(session_id="s1", prompt="write a function"))
    assert nid is None
    assert engine.list_recent(limit=1)[0].spec.id == out.spec.id


@pytest.mark.parametrize(
    "prompt,expected_game",
    [
        ("build an api endpoint with authentication", LanguageGame.SOFTWARE_ENGINEERING),
        (
            "design a viable system model with s3 control and s4 intelligence",
            LanguageGame.SYSTEMS_ARCHITECTURE,
        ),
        (
            "explain the dharma and dependent origination in madhyamaka",
            LanguageGame.BUDDHIST_PHILOSOPHY,
        ),
        ("what is the weather today", LanguageGame.GENERAL),
    ],
)
def test_language_game_classification_routes_pipeline(
    prompt: str, expected_game: LanguageGame
) -> None:
    engine = TektosSpecPlanner()
    out, _ = _run(engine.generate_spec(session_id="s1", prompt=prompt))
    assert out.language_game_detected == expected_game
