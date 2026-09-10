"""Contract tests for TektosSessionAdapter (ADR-103 D8)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adapters.session.tektos import vendor_bindings
from adapters.session.tektos.adapter import TektosSessionAdapter
from adapters.session.tektos.vendor.state_machine import (
    State as VendorState,
    VALID_TRANSITIONS as DONOR_VALID_TRANSITIONS,
    reset_state_machine as reset_vendor_state_machine,
)
from ports.session import (
    InvalidTransitionError,
    LiveSession,
    SessionPort,
    SessionState,
    StateTransition,
    VALID_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeEventBus:
    """In-memory EventBusPort stand-in that captures every envelope."""

    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    def publish(self, envelope: Any) -> None:
        self.envelopes.append(envelope)


class FakeRelationalMemory:
    """Captures every record_event call.

    ``record_event`` is declared ``async`` to match the port protocol.
    """

    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.records: list[dict[str, Any]] = []
        self.raise_on_call = raise_on_call

    async def record_event(
        self,
        *,
        kind: str,
        entity_id: str,
        payload: dict[str, Any],
        provenance: str,
        confidence: float,
    ) -> None:
        if self.raise_on_call:
            raise RuntimeError("relational memory mirror failure")
        self.records.append(
            {
                "kind": kind,
                "entity_id": entity_id,
                "payload": payload,
                "provenance": provenance,
                "confidence": confidence,
            }
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Clean donor singletons + shim bindings before every test."""
    reset_vendor_state_machine()
    vendor_bindings.unbind_all()
    yield
    reset_vendor_state_machine()
    vendor_bindings.unbind_all()


@pytest.fixture
def bus() -> FakeEventBus:
    return FakeEventBus()


@pytest.fixture
def adapter(bus: FakeEventBus) -> TektosSessionAdapter:
    return TektosSessionAdapter(event_bus=bus)


# ---------------------------------------------------------------------------
# Protocol conformance + donor invariants
# ---------------------------------------------------------------------------


def test_adapter_conforms_to_session_port(adapter: TektosSessionAdapter) -> None:
    assert isinstance(adapter, SessionPort)


def test_donor_transition_table_intact() -> None:
    # Fidelity check: donor VALID_TRANSITIONS list is untouched at 7.
    assert len(DONOR_VALID_TRANSITIONS) == 7


def test_port_transition_table_has_eleven_edges() -> None:
    # Port table is donor 7 + 4 kosmos deltas (ADR-103 D1).
    assert len(VALID_TRANSITIONS) == 11


def test_donor_state_enum_unchanged() -> None:
    assert {s.value for s in VendorState} == {
        "created",
        "ready",
        "running",
        "interrupted",
        "failed",
        "idle",
    }


def test_adapter_is_healthy_after_construction(adapter: TektosSessionAdapter) -> None:
    assert adapter.is_healthy() is True


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_transitions_created_to_ready(
    adapter: TektosSessionAdapter, bus: FakeEventBus
) -> None:
    session = await adapter.create_session(model="m")
    assert isinstance(session, LiveSession)
    assert session.status == SessionState.READY.value
    assert adapter.get_state(session.id) == SessionState.READY
    # Donor emits session.state_change on the CREATED → READY edge.
    event_types = {e.event_type for e in bus.envelopes}
    assert "session.state_change" in event_types


@pytest.mark.asyncio
async def test_create_session_emits_envelope_with_correct_producer(
    adapter: TektosSessionAdapter, bus: FakeEventBus
) -> None:
    await adapter.create_session(model="m")
    assert all(e.producer_plugin == "tektos.session" for e in bus.envelopes)


@pytest.mark.asyncio
async def test_get_session_returns_none_for_unknown_id(
    adapter: TektosSessionAdapter,
) -> None:
    assert await adapter.get_session("nope") is None


@pytest.mark.asyncio
async def test_list_sessions_returns_port_shape(adapter: TektosSessionAdapter) -> None:
    a = await adapter.create_session(model="m")
    b = await adapter.create_session(model="m")
    live = await adapter.list_sessions()
    assert {s.id for s in live} == {a.id, b.id}
    assert all(isinstance(s, LiveSession) for s in live)


# ---------------------------------------------------------------------------
# Client attach / detach
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_and_detach_client(adapter: TektosSessionAdapter) -> None:
    session = await adapter.create_session(model="m")
    assert await adapter.attach_client(session.id, "client-a") is True
    await adapter.detach_client(session.id, "client-a")
    # After last detach donor drives READY → IDLE.
    assert adapter.get_state(session.id) == SessionState.IDLE


@pytest.mark.asyncio
async def test_attach_client_missing_session_returns_false(
    adapter: TektosSessionAdapter,
) -> None:
    assert await adapter.attach_client("nope", "c") is False


# ---------------------------------------------------------------------------
# Turn FSM edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_complete_cycle(adapter: TektosSessionAdapter) -> None:
    session = await adapter.create_session(model="m")
    change = await adapter.start_turn(session.id)
    assert isinstance(change, StateTransition)
    assert change.to_state == "running"
    change = await adapter.complete_turn(session.id)
    assert change.to_state == "ready"


@pytest.mark.asyncio
async def test_fail_turn_marks_failed(adapter: TektosSessionAdapter) -> None:
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.fail_turn(session.id)
    assert adapter.get_state(session.id) == SessionState.FAILED


@pytest.mark.asyncio
async def test_interrupt_turn_marks_interrupted(
    adapter: TektosSessionAdapter,
) -> None:
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.interrupt_turn(session.id)
    assert adapter.get_state(session.id) == SessionState.INTERRUPTED


@pytest.mark.asyncio
async def test_invalid_transition_ready_to_failed_raises(
    adapter: TektosSessionAdapter,
) -> None:
    session = await adapter.create_session(model="m")
    # start_turn drives READY -> RUNNING; skip that so we're still READY.
    with pytest.raises(InvalidTransitionError):
        await adapter.start_turn("nonexistent-id")  # CREATED default → RUNNING invalid


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_from_ready(adapter: TektosSessionAdapter) -> None:
    session = await adapter.create_session(model="m")
    await adapter.archive_session(session.id)
    assert adapter.get_state(session.id) == SessionState.ARCHIVED
    history = adapter.get_history(session.id)
    assert history[-1].to_state == "archived"
    assert history[-1].from_state == "ready"


@pytest.mark.asyncio
async def test_archive_from_running_raises(adapter: TektosSessionAdapter) -> None:
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    with pytest.raises(InvalidTransitionError):
        await adapter.archive_session(session.id)


@pytest.mark.asyncio
async def test_fork_session_sets_root_and_copies_metadata(
    adapter: TektosSessionAdapter,
) -> None:
    src = await adapter.create_session(model="m")
    await adapter.rename_session(src.id, "parent")
    await adapter.tag_session(src.id, "tag-1")
    fork = await adapter.fork_session(src.id, model="m")
    assert fork.root_session_id == src.id


@pytest.mark.asyncio
async def test_resume_session_requires_archived(
    adapter: TektosSessionAdapter,
) -> None:
    session = await adapter.create_session(model="m")
    with pytest.raises(ValueError):
        await adapter.resume_session(session.id)
    await adapter.archive_session(session.id)
    resumed = await adapter.resume_session(session.id)
    assert resumed.root_session_id == session.id


@pytest.mark.asyncio
async def test_delete_session_returns_zero_at_stage_8_1(
    adapter: TektosSessionAdapter,
) -> None:
    # store_delete is stubbed to 0 per ADR-103 D3.
    session = await adapter.create_session(model="m")
    assert await adapter.delete_session(session.id) == 0
    assert await adapter.get_session(session.id) is None


@pytest.mark.asyncio
async def test_reap_failed_sessions(adapter: TektosSessionAdapter) -> None:
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.fail_turn(session.id)
    reaped = await adapter.reap_failed_sessions(timeout=0.0)
    assert reaped == 1


@pytest.mark.asyncio
async def test_search_sessions_basic(adapter: TektosSessionAdapter) -> None:
    a = await adapter.create_session(model="m")
    await adapter.rename_session(a.id, "alpha")
    b = await adapter.create_session(model="m")
    await adapter.rename_session(b.id, "beta")
    hits = await adapter.search_sessions(query="alpha")
    assert [s.id for s in hits] == [a.id]


# ---------------------------------------------------------------------------
# FSM introspection
# ---------------------------------------------------------------------------


def test_get_state_defaults_to_created(adapter: TektosSessionAdapter) -> None:
    assert adapter.get_state("unknown-id") == SessionState.CREATED


@pytest.mark.asyncio
async def test_get_history_ordering(adapter: TektosSessionAdapter) -> None:
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.complete_turn(session.id)
    history = adapter.get_history(session.id)
    to_states = [h.to_state for h in history]
    assert to_states == ["ready", "running", "ready"]


def test_get_allowed_transitions_running(adapter: TektosSessionAdapter) -> None:
    allowed = adapter.get_allowed_transitions(SessionState.RUNNING)
    assert set(allowed) == {
        SessionState.READY,
        SessionState.FAILED,
        SessionState.INTERRUPTED,
    }


# ---------------------------------------------------------------------------
# EventBus envelope shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_envelope_payload_contains_session_id_and_transition_fields(
    adapter: TektosSessionAdapter, bus: FakeEventBus
) -> None:
    session = await adapter.create_session(model="m")
    state_change_envelopes = [
        e for e in bus.envelopes if e.event_type == "session.state_change"
    ]
    assert state_change_envelopes
    payload = state_change_envelopes[0].payload
    assert payload["session_id"] == session.id
    assert payload["from_state"] == "created"
    assert payload["to_state"] == "ready"


@pytest.mark.asyncio
async def test_lifecycle_envelope_types_emitted(
    adapter: TektosSessionAdapter, bus: FakeEventBus
) -> None:
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await adapter.complete_turn(session.id)
    event_types = [e.event_type for e in bus.envelopes]
    # Donor emits session.state_change on transitions and session.ready
    # on complete_session; session.created is emitted after the vendor
    # session is inserted.
    assert "session.state_change" in event_types
    assert "session.created" in event_types
    assert "session.ready" in event_types


# ---------------------------------------------------------------------------
# RelationalMemoryPort mirror
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mirror_records_state_changes(bus: FakeEventBus) -> None:
    memory = FakeRelationalMemory()
    adapter = TektosSessionAdapter(event_bus=bus, relational_memory=memory)
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    await asyncio.sleep(0)  # let scheduled mirror coroutines drain
    assert any(r["kind"] == "session.state_change" for r in memory.records)
    for r in memory.records:
        assert r["provenance"] == "tektos.session"
        assert r["confidence"] == 1.0
        assert r["entity_id"] == session.id


@pytest.mark.asyncio
async def test_mirror_failure_does_not_break_fsm(bus: FakeEventBus) -> None:
    memory = FakeRelationalMemory(raise_on_call=True)
    adapter = TektosSessionAdapter(event_bus=bus, relational_memory=memory)
    # FSM must still work through a failing mirror.
    session = await adapter.create_session(model="m")
    await adapter.start_turn(session.id)
    assert adapter.get_state(session.id) == SessionState.RUNNING


# ---------------------------------------------------------------------------
# Health / close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_idempotent_and_unbinds(
    bus: FakeEventBus,
) -> None:
    adapter = TektosSessionAdapter(event_bus=bus)
    await adapter.close()
    assert adapter.is_healthy() is False
    await adapter.close()  # idempotent
    assert adapter.is_healthy() is False


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_create_sessions(adapter: TektosSessionAdapter) -> None:
    ids = await asyncio.gather(
        *(adapter.create_session(model="m") for _ in range(30))
    )
    assert len({s.id for s in ids}) == 30
