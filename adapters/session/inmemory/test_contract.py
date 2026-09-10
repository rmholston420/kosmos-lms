"""Contract tests for InMemorySessionAdapter (ADR-103 D8)."""

from __future__ import annotations

import asyncio

import pytest

from adapters.session.inmemory.adapter import InMemorySessionAdapter
from ports.session import (
    InvalidTransitionError,
    LiveSession,
    SessionPort,
    SessionState,
    StateTransition,
    VALID_TRANSITIONS,
    is_valid_transition,
)


# ---------------------------------------------------------------------------
# Protocol conformance + basic construction
# ---------------------------------------------------------------------------


def test_adapter_conforms_to_session_port() -> None:
    adapter = InMemorySessionAdapter()
    assert isinstance(adapter, SessionPort)


def test_adapter_is_healthy_after_construction() -> None:
    adapter = InMemorySessionAdapter()
    assert adapter.is_healthy() is True


def test_valid_transitions_eleven_edges_locked() -> None:
    # ADR-103 D1: 7 donor transitions + 4 delta transitions
    # (IDLE→READY reattach + 3 ARCHIVED entry edges).
    assert len(VALID_TRANSITIONS) == 11
    to_archived = [t for t in VALID_TRANSITIONS if t.to_state == SessionState.ARCHIVED]
    assert {t.from_state for t in to_archived} == {
        SessionState.READY,
        SessionState.IDLE,
        SessionState.INTERRUPTED,
    }
    assert any(
        t.from_state == SessionState.IDLE and t.to_state == SessionState.READY
        for t in VALID_TRANSITIONS
    )


def test_is_valid_transition_accepts_str_and_enum() -> None:
    assert is_valid_transition(SessionState.CREATED, SessionState.READY) is True
    assert is_valid_transition("created", "ready") is True
    assert is_valid_transition(SessionState.CREATED, SessionState.RUNNING) is False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_transitions_created_to_ready() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="qwen3-coder:30b-fp16")
    assert isinstance(session, LiveSession)
    assert session.id
    assert session.status == SessionState.READY.value
    assert adapter.get_state(session.id) == SessionState.READY
    history = adapter.get_history(session.id)
    assert len(history) == 1
    assert history[0].from_state == "created"
    assert history[0].to_state == "ready"


@pytest.mark.asyncio
async def test_create_session_resolves_cwd() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m", cwd="/tmp")
    assert session.cwd == "/tmp"


@pytest.mark.asyncio
async def test_create_session_records_fork_and_resume_root_ids() -> None:
    adapter = InMemorySessionAdapter()
    forked = await adapter.create_session(model="m", fork_session_id="src-1")
    assert forked.root_session_id == "src-1"
    resumed = await adapter.create_session(model="m", resume_session_id="src-2")
    assert resumed.root_session_id == "src-2"


@pytest.mark.asyncio
async def test_get_session_returns_none_for_unknown_id() -> None:
    adapter = InMemorySessionAdapter()
    assert await adapter.get_session("does-not-exist") is None


@pytest.mark.asyncio
async def test_list_sessions_orders_by_updated_at_desc() -> None:
    adapter = InMemorySessionAdapter()
    s1 = await adapter.create_session(model="m")
    await asyncio.sleep(0)
    s2 = await adapter.create_session(model="m")
    live = await adapter.list_sessions()
    assert [s.id for s in live][:2] == [s2.id, s1.id]


@pytest.mark.asyncio
async def test_list_sessions_archived_flag() -> None:
    adapter = InMemorySessionAdapter()
    live = await adapter.create_session(model="m")
    archived = await adapter.create_session(model="m")
    await adapter.archive_session(archived.id)
    live_list = await adapter.list_sessions()
    archived_list = await adapter.list_sessions(archived=True)
    assert live.id in {s.id for s in live_list}
    assert archived.id not in {s.id for s in live_list}
    assert archived.id in {s.id for s in archived_list}


# ---------------------------------------------------------------------------
# Client attach / detach
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_client_returns_false_for_unknown_session() -> None:
    adapter = InMemorySessionAdapter()
    assert await adapter.attach_client("nope", "client-a") is False


@pytest.mark.asyncio
async def test_attach_and_detach_client_updates_state() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    assert adapter.get_state(session.id) == SessionState.READY
    assert await adapter.attach_client(session.id, "client-a") is True
    assert "client-a" in session.attached_clients
    # Detaching last client transitions READY → IDLE.
    await adapter.detach_client(session.id, "client-a")
    assert adapter.get_state(session.id) == SessionState.IDLE


@pytest.mark.asyncio
async def test_re_attach_after_idle_returns_to_ready() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    await adapter.attach_client(session.id, "c1")
    await adapter.detach_client(session.id, "c1")
    assert adapter.get_state(session.id) == SessionState.IDLE
    await adapter.attach_client(session.id, "c1")
    assert adapter.get_state(session.id) == SessionState.READY


# ---------------------------------------------------------------------------
# Turn FSM edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_turn_cycle_ready_running_ready() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    change = await adapter.start_turn(session.id, reason="processing")
    assert isinstance(change, StateTransition)
    assert change.to_state == "running"
    change = await adapter.complete_turn(session.id, reason="done")
    assert change.to_state == "ready"


@pytest.mark.asyncio
async def test_fail_turn_transitions_to_failed() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.fail_turn(session.id, reason="boom")
    assert adapter.get_state(session.id) == SessionState.FAILED


@pytest.mark.asyncio
async def test_interrupt_turn_transitions_to_interrupted_then_ready() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.interrupt_turn(session.id)
    assert adapter.get_state(session.id) == SessionState.INTERRUPTED
    await adapter.complete_turn(session.id, reason="recovered")
    assert adapter.get_state(session.id) == SessionState.READY


@pytest.mark.asyncio
async def test_invalid_transition_raises() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    # READY → FAILED is NOT a valid direct transition.
    with pytest.raises(InvalidTransitionError):
        await adapter.fail_turn(session.id, reason="illegal")


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_session_transitions_to_archived_and_clears_clients() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    await adapter.attach_client(session.id, "c")
    await adapter.archive_session(session.id)
    assert adapter.get_state(session.id) == SessionState.ARCHIVED
    assert session.attached_clients == set()
    assert session.is_archived


@pytest.mark.asyncio
async def test_fork_session_copies_title_and_tag_and_sets_root_id() -> None:
    adapter = InMemorySessionAdapter()
    src = await adapter.create_session(model="m")
    await adapter.rename_session(src.id, "parent")
    await adapter.tag_session(src.id, "tag-1")
    fork = await adapter.fork_session(src.id, model="m")
    assert fork.root_session_id == src.id
    assert fork.title.startswith("fork of parent")
    assert fork.tag == "tag-1"


@pytest.mark.asyncio
async def test_fork_session_missing_source_raises_keyerror() -> None:
    adapter = InMemorySessionAdapter()
    with pytest.raises(KeyError):
        await adapter.fork_session("nope", model="m")


@pytest.mark.asyncio
async def test_resume_session_requires_archived() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    with pytest.raises(ValueError):
        await adapter.resume_session(session.id)
    await adapter.archive_session(session.id)
    resumed = await adapter.resume_session(session.id)
    assert resumed.root_session_id == session.id
    assert resumed.title.startswith("resume of")


@pytest.mark.asyncio
async def test_rename_and_tag_missing_session_raises() -> None:
    adapter = InMemorySessionAdapter()
    with pytest.raises(KeyError):
        await adapter.rename_session("nope", "x")
    with pytest.raises(KeyError):
        await adapter.tag_session("nope", "x")


@pytest.mark.asyncio
async def test_delete_session_returns_zero_at_stage_8_1() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    # ADR-103 D3 event-store deletion deferred to Stage 13.
    assert await adapter.delete_session(session.id) == 0
    assert await adapter.get_session(session.id) is None


@pytest.mark.asyncio
async def test_delete_session_unknown_returns_zero() -> None:
    adapter = InMemorySessionAdapter()
    assert await adapter.delete_session("nope") == 0


@pytest.mark.asyncio
async def test_reap_failed_sessions_respects_timeout() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.fail_turn(session.id)
    # timeout=0 → immediate reap.
    reaped = await adapter.reap_failed_sessions(timeout=0.0)
    assert reaped == 1
    assert await adapter.get_session(session.id) is None


@pytest.mark.asyncio
async def test_reap_failed_sessions_leaves_recent_failures() -> None:
    adapter = InMemorySessionAdapter()
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.fail_turn(session.id)
    # Very large timeout → nothing reaped.
    reaped = await adapter.reap_failed_sessions(timeout=1e9)
    assert reaped == 0
    assert await adapter.get_session(session.id) is not None


@pytest.mark.asyncio
async def test_search_sessions_filters_and_sorts() -> None:
    adapter = InMemorySessionAdapter()
    a = await adapter.create_session(model="m")
    await adapter.rename_session(a.id, "alpha planning")
    b = await adapter.create_session(model="m")
    await adapter.rename_session(b.id, "beta execution")
    hits = await adapter.search_sessions(query="alpha")
    assert [s.id for s in hits] == [a.id]
    both = await adapter.search_sessions(query="")
    assert {s.id for s in both} == {a.id, b.id}
    sorted_by_title = await adapter.search_sessions(query="", sort="title", order="asc")
    assert [s.title for s in sorted_by_title] == ["alpha planning", "beta execution"]


# ---------------------------------------------------------------------------
# FSM introspection
# ---------------------------------------------------------------------------


def test_get_state_defaults_to_created_for_unknown_id() -> None:
    adapter = InMemorySessionAdapter()
    assert adapter.get_state("nope") == SessionState.CREATED


def test_get_history_empty_for_unknown_id() -> None:
    adapter = InMemorySessionAdapter()
    assert adapter.get_history("nope") == []


def test_get_allowed_transitions_ready() -> None:
    adapter = InMemorySessionAdapter()
    allowed = adapter.get_allowed_transitions(SessionState.READY)
    assert set(allowed) == {
        SessionState.RUNNING,
        SessionState.IDLE,
        SessionState.ARCHIVED,
    }


def test_get_allowed_transitions_idle_includes_ready_reattach() -> None:
    adapter = InMemorySessionAdapter()
    allowed = adapter.get_allowed_transitions(SessionState.IDLE)
    assert set(allowed) == {SessionState.READY, SessionState.ARCHIVED}


def test_get_allowed_transitions_accepts_str() -> None:
    adapter = InMemorySessionAdapter()
    allowed = adapter.get_allowed_transitions("running")
    assert set(allowed) == {
        SessionState.READY,
        SessionState.FAILED,
        SessionState.INTERRUPTED,
    }


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_create_sessions_are_isolated() -> None:
    adapter = InMemorySessionAdapter()

    async def make() -> str:
        s = await adapter.create_session(model="m")
        return s.id

    ids = await asyncio.gather(*(make() for _ in range(50)))
    assert len(set(ids)) == 50
    live = await adapter.list_sessions()
    assert len(live) == 50


# ---------------------------------------------------------------------------
# Health / close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_idempotent_and_flips_health() -> None:
    adapter = InMemorySessionAdapter()
    assert adapter.is_healthy() is True
    await adapter.close()
    assert adapter.is_healthy() is False
    await adapter.close()  # No-op.
    assert adapter.is_healthy() is False
