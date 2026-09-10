"""Stage 8.5 · ADR-107 contract tests — ``TektosToolRouter`` engine."""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from plugins.tektos.executor import (
    TEKTOS_TOOL_ROUTER_DEFAULT_CONFIDENCE,
    TEKTOS_TOOL_ROUTER_PREDICATE,
    TEKTOS_TOOL_ROUTER_PROVENANCE,
    TektosToolRouter,
    ToolRoute,
)
from plugins.tektos.executor.engine import _CAPABILITY_TABLE, _keyword_route
from ports.event_envelope import EventEnvelope


# ── Test doubles ───────────────────────────────────────────────────────────


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


# ── Keyword-match routing (verbatim donor branches) ───────────────────────


@pytest.mark.parametrize(
    "desc,primary,category",
    [
        ("run the shell command now", "bash", "terminal"),
        ("read the config file", "file_read", "file_operations"),
        ("write a new module", "file_write", "file_operations"),
        ("search all python files", "search_files", "search"),
        ("look up something on the web", "web_search", "web"),
        ("delegate this subagent", "delegate_task", "delegation"),
        ("do something unknown", "bash", "terminal"),  # fallback default
    ],
)
def test_keyword_route_covers_all_donor_branches(
    desc: str, primary: str, category: str
) -> None:
    r = _keyword_route(desc)
    assert r.primary_tool == primary
    assert r.category == category


# ── route() surface ────────────────────────────────────────────────────────


def test_route_unbound_returns_none_narrative_id_and_populates_ring_buffer() -> None:
    router = TektosToolRouter()
    route, nid = _run(
        router.route(session_id="s1", task_description="run a shell command")
    )
    assert nid is None
    assert router.is_persistence_bound is False
    assert route.category == "terminal"
    recent = router.list_recent(limit=5)
    assert len(recent) == 1
    assert recent[0].id == route.id


def test_route_bound_persists_via_write_narrative_with_locked_provenance() -> None:
    rmem = _StubRMem()
    router = TektosToolRouter(relational_memory=rmem)
    route, nid = _run(
        router.route(session_id="s1", task_description="write a file")
    )
    assert nid == "nar-1"
    w = rmem.writes[0]
    assert w["provenance"] == TEKTOS_TOOL_ROUTER_PROVENANCE
    assert w["agent_id"] == TEKTOS_TOOL_ROUTER_PROVENANCE
    assert w["title"].startswith(f"{TEKTOS_TOOL_ROUTER_PREDICATE}:")
    assert 0.0 < w["confidence"] <= 1.0
    assert w["confidence"] == pytest.approx(TEKTOS_TOOL_ROUTER_DEFAULT_CONFIDENCE)
    body = json.loads(w["body"])
    assert body["id"] == route.id
    assert body["primary_tool"] == route.primary_tool


def test_route_bound_publishes_event_envelope_with_locked_predicate() -> None:
    bus = _StubBus()
    router = TektosToolRouter(relational_memory=_StubRMem(), event_bus=bus)
    route, _ = _run(
        router.route(session_id="s1", task_description="search for something")
    )
    env = bus.published[0]
    assert env.event_type == TEKTOS_TOOL_ROUTER_PREDICATE
    assert env.producer_plugin == TEKTOS_TOOL_ROUTER_PROVENANCE
    assert env.payload["primary_tool"] == route.primary_tool
    assert env.payload["category"] == route.category


def test_write_narrative_failure_kept_in_ring_buffer_fail_open() -> None:
    router = TektosToolRouter(relational_memory=_StubRMemRaise())
    route, nid = _run(
        router.route(session_id="s1", task_description="run something")
    )
    assert nid is None
    assert router.list_recent(limit=1)[0].id == route.id


# ── route_for_tools() surface ──────────────────────────────────────────────


def test_route_for_tools_partitions_known_and_unknown_tools() -> None:
    router = TektosToolRouter()
    route, _ = _run(
        router.route_for_tools(
            session_id="s1",
            tools_needed=("bash", "read_file", "totally_made_up_tool"),
        )
    )
    assert "bash" in route.matched_tools
    assert "read_file" in route.matched_tools
    assert route.unrouted_tools == ("totally_made_up_tool",)


def test_route_for_tools_without_description_uses_first_tool_as_primary() -> None:
    router = TektosToolRouter()
    route, _ = _run(
        router.route_for_tools(session_id="s1", tools_needed=("web_fetch", "web_extract"))
    )
    assert route.primary_tool == "web_fetch"
    assert route.category == "web"


def test_route_for_tools_empty_falls_back_to_bash_unknown_category() -> None:
    router = TektosToolRouter()
    route, _ = _run(router.route_for_tools(session_id="s1", tools_needed=()))
    assert route.primary_tool == "bash"
    # ``bash`` is a known capability entry so category collapses to terminal
    # when task description is empty and tools_needed is empty.
    assert route.category in {"terminal", "unknown"}


def test_route_for_tools_with_description_prefers_keyword_route() -> None:
    router = TektosToolRouter()
    route, _ = _run(
        router.route_for_tools(
            session_id="s1",
            tools_needed=("read_file",),
            task_description="search for foo across files",
        )
    )
    # Description keyword ('search') wins over tools_needed hint.
    assert route.primary_tool == "search_files"


# ── Capability table integrity ────────────────────────────────────────────


def test_capability_table_matches_donor_categories() -> None:
    assert _CAPABILITY_TABLE["bash"] == "terminal"
    assert _CAPABILITY_TABLE["read_file"] == "file_operations"
    assert _CAPABILITY_TABLE["web_search"] == "web"
    assert _CAPABILITY_TABLE["delegate_task"] == "delegation"


# ── Ring buffer / immutability ────────────────────────────────────────────


def test_list_recent_zero_or_negative_returns_empty_tuple() -> None:
    router = TektosToolRouter()
    _run(router.route(session_id="s1", task_description="x"))
    assert router.list_recent(limit=0) == ()
    assert router.list_recent(limit=-1) == ()


def test_tool_route_is_frozen_dataclass() -> None:
    router = TektosToolRouter()
    route, _ = _run(router.route(session_id="s1", task_description="x"))
    assert isinstance(route, ToolRoute)
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        route.primary_tool = "changed"  # type: ignore[misc]


def test_ring_buffer_respects_max_records_cap() -> None:
    router = TektosToolRouter(max_records=2)
    for i in range(4):
        _run(router.route(session_id=f"s{i}", task_description="x"))
    assert len(router.list_recent(limit=10)) == 2
