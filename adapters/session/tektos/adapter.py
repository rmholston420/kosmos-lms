"""TektosSessionAdapter — fidelity port of tektos-ultima session runtime.

Per ADR-103 D2:

- Donor ``state_machine.py`` and ``runtime/session.py`` are copied verbatim
  under ``adapters/session/tektos/vendor/``; only three import lines were
  rewritten to retarget the vendored sibling + the ``vendor_bindings``
  shim (event-bus routing + Stage 13 deferrals).
- This adapter is a **façade** that satisfies :class:`SessionPort` by
  delegating every method to the vendored donor code, applying the
  transport-neutral rename (``attach_client``/``detach_client`` at the
  port, ``add_ws_connection``/``remove_ws_connection`` in the vendor),
  and threading the FSM introspection helpers on top.
- The RelationalMemoryPort mirror is bound once at construction — every
  successful event publish in the vendor code fans out to the audit
  ledger through ``vendor_bindings._maybe_mirror`` without the vendor
  code needing to know Stage 8.0 exists.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from adapters.session.tektos import vendor_bindings
from adapters.session.tektos.vendor.session import (
    LiveSession as _VendorLiveSession,
    SessionManager as _VendorSessionManager,
)
from adapters.session.tektos.vendor.state_machine import (
    State as _VendorState,
    get_state_machine as _get_vendor_state_machine,
    reset_state_machine as _reset_vendor_state_machine,
)
from ports.session import (
    InvalidTransitionError,
    LiveSession,
    SessionState,
    StateTransition,
    VALID_TRANSITIONS,
    is_valid_transition,
)

__all__ = ["TektosSessionAdapter"]

log = logging.getLogger(__name__)


def _to_port_session(v: _VendorLiveSession) -> LiveSession:
    """Convert a vendor ``LiveSession`` into a port ``LiveSession``.

    The two share every field except the connection set — donor calls
    it ``ws_connections`` (set of opaque WebSocket handles); the port
    calls it ``attached_clients`` (set of opaque str client ids).
    """
    return LiveSession(
        id=v.id,
        model=v.model,
        cwd=v.cwd,
        permission_mode=v.permission_mode,
        status=v.status,
        title=v.title,
        tag=v.tag,
        root_session_id=v.root_session_id,
        created_at=v.created_at,
        updated_at=v.updated_at,
        seq=v.seq,
        attached_clients={
            c if isinstance(c, str) else str(getattr(c, "client_id", id(c)))
            for c in v.ws_connections
        },
    )


class TektosSessionAdapter:
    """SessionPort adapter backed by the vendored donor runtime.

    Construction wires the injected ``event_bus`` and optional
    ``relational_memory`` into the module-level bindings in
    :mod:`adapters.session.tektos.vendor_bindings`. Multiple concurrent
    adapter instances in one process is out of scope at Stage 8.1 (the
    donor is a singleton by design).
    """

    def __init__(
        self,
        *,
        event_bus: Any,
        relational_memory: Any | None = None,
    ) -> None:
        vendor_bindings.bind_event_bus(event_bus)
        vendor_bindings.bind_relational_memory(relational_memory)
        self._manager = _VendorSessionManager()
        self._closed = False
        # ARCHIVED is a port-level state not modeled in the donor FSM,
        # so archival transitions are recorded in a parallel history
        # that ``get_history`` splices onto the end of donor history.
        self._archive_history: dict[str, list[StateTransition]] = {}

    # ── FSM helpers ──────────────────────────────────────────────────────

    def _sm(self) -> Any:
        return _get_vendor_state_machine()

    def _to_state_transition(self, sm_change: Any) -> StateTransition:
        """Convert a donor ``StateChange`` dataclass into port
        :class:`StateTransition`. Handles field-name drift defensively."""
        session_id = getattr(sm_change, "session_id", "")
        from_state = getattr(sm_change, "from_state", None)
        to_state = getattr(sm_change, "to_state", None)
        reason = getattr(sm_change, "reason", "")
        return StateTransition(
            session_id=session_id,
            from_state=(
                from_state.value
                if isinstance(from_state, _VendorState)
                else str(from_state or "")
            ),
            to_state=(
                to_state.value
                if isinstance(to_state, _VendorState)
                else str(to_state or "")
            ),
            reason=reason,
            timestamp_iso=getattr(
                sm_change,
                "timestamp_iso",
                datetime.now(timezone.utc).isoformat(),
            ),
            timestamp_mono=getattr(sm_change, "timestamp_mono", time.monotonic()),
        )

    def _drive(
        self,
        session_id: str,
        target: _VendorState,
        reason: str,
    ) -> StateTransition:
        """Wrap the vendor state-machine transition into a port StateTransition."""
        # Guard on the port-level table so ARCHIVED-related edges are
        # enforced even though the donor table doesn't list them.
        port_target = SessionState(target.value)
        current = self.get_state(session_id)
        if not is_valid_transition(current, port_target):
            raise InvalidTransitionError(
                f"Invalid transition for session {session_id}: "
                f"{current.value} → {port_target.value} (reason: {reason})"
            )
        sm_change = self._sm().transition(session_id, target, reason)
        return self._to_state_transition(sm_change)

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        model: str,
        cwd: str = ".",
        permission_mode: str = "auto",
        resume_session_id: str | None = None,
        fork_session_id: str | None = None,
    ) -> LiveSession:
        v = await self._manager.create_session(
            model=model,
            cwd=cwd,
            permission_mode=permission_mode,
            resume_session_id=resume_session_id,
            fork_session_id=fork_session_id,
        )
        # Donor create_session drives the FSM to READY but does NOT
        # write the string back onto the vendor session object;
        # reflect the actual FSM state on the returned port snapshot.
        v.status = self.get_state(v.id).value
        return _to_port_session(v)

    async def get_session(self, session_id: str) -> LiveSession | None:
        v = await self._manager.get_session(session_id)
        return _to_port_session(v) if v is not None else None

    async def list_sessions(self, *, archived: bool = False) -> list[LiveSession]:
        vs = await self._manager.list_sessions(archived=archived)
        return [_to_port_session(v) for v in vs]

    # ── Client attach / detach (transport-neutral) ───────────────────────

    async def attach_client(self, session_id: str, client_id: str) -> bool:
        # Donor add_ws_connection expects a WebSocket handle; we pass
        # the opaque client_id string — the donor stores whatever we
        # hand it and treats it as opaque.
        return await self._manager.add_ws_connection(session_id, client_id)

    async def detach_client(self, session_id: str, client_id: str) -> None:
        await self._manager.remove_ws_connection(session_id, client_id)

    # ── Turn FSM edges ───────────────────────────────────────────────────

    async def start_turn(self, session_id: str, *, reason: str = "") -> StateTransition:
        # Donor has no explicit start_turn; drive the FSM directly and
        # also update the vendor session's raw-string status so donor
        # methods like interrupt_session (which gate on status ==
        # "running") behave correctly.
        change = self._drive(session_id, _VendorState.RUNNING, reason or "turn started")
        v = self._manager._sessions.get(session_id)
        if v is not None:
            v.status = "running"
            v.updated_at = time.monotonic()
        return change

    async def complete_turn(
        self, session_id: str, *, reason: str = ""
    ) -> StateTransition:
        await self._manager.complete_session(session_id, status="ready")
        return self._to_state_transition(
            self._sm().get_history(session_id)[-1]
        )

    async def fail_turn(self, session_id: str, *, reason: str = "") -> StateTransition:
        await self._manager.complete_session(session_id, status="failed")
        return self._to_state_transition(
            self._sm().get_history(session_id)[-1]
        )

    async def interrupt_turn(
        self, session_id: str, *, reason: str = ""
    ) -> StateTransition:
        await self._manager.interrupt_session(session_id)
        return self._to_state_transition(
            self._sm().get_history(session_id)[-1]
        )

    # ── Housekeeping ─────────────────────────────────────────────────────

    async def archive_session(self, session_id: str) -> None:
        # Donor archive_session sets status="archived" as a raw string
        # and does NOT drive the state machine. Port lifts this into
        # an explicit FSM transition + synthetic history entry so
        # ``get_state`` and ``get_history`` remain truthful.
        current = self.get_state(session_id)
        if not is_valid_transition(current, SessionState.ARCHIVED):
            raise InvalidTransitionError(
                f"Cannot archive session {session_id} from {current.value}"
            )
        await self._manager.archive_session(session_id)
        change = StateTransition(
            session_id=session_id,
            from_state=current.value,
            to_state=SessionState.ARCHIVED.value,
            reason="archived",
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            timestamp_mono=time.monotonic(),
        )
        self._archive_history.setdefault(session_id, []).append(change)

    async def fork_session(
        self,
        source_session_id: str,
        *,
        model: str,
        cwd: str = ".",
    ) -> LiveSession:
        v = await self._manager.fork_session(source_session_id, model=model, cwd=cwd)
        return _to_port_session(v)

    async def resume_session(self, session_id: str) -> LiveSession:
        v = await self._manager.resume_session(session_id)
        return _to_port_session(v)

    async def rename_session(self, session_id: str, new_title: str) -> None:
        await self._manager.rename_session(session_id, new_title)

    async def tag_session(self, session_id: str, tag: str) -> None:
        await self._manager.tag_session(session_id, tag)

    async def set_session_model(self, session_id: str, new_model: str) -> str:
        """Switch a session's model (ADR-132 slice E). Returns old model."""
        return await self._manager.switch_model(session_id, new_model)

    async def delete_session(self, session_id: str) -> int:
        return await self._manager.delete_session(session_id)

    async def reap_failed_sessions(self, *, timeout: float = 300.0) -> int:
        return await self._manager.reap_failed_sessions(timeout=timeout)

    async def search_sessions(
        self,
        *,
        query: str,
        sort: str = "updated_at",
        order: str = "desc",
    ) -> list[LiveSession]:
        vs = await self._manager.search_sessions(query=query, sort=sort, order=order)
        return [_to_port_session(v) for v in vs]

    # ── FSM introspection ────────────────────────────────────────────────

    def get_state(self, session_id: str) -> SessionState:
        v_state = self._sm().get_state(session_id)
        # Donor state enum has no ARCHIVED; check the vendor session dict.
        v_session = self._manager._sessions.get(session_id)
        if v_session is not None and v_session.status == SessionState.ARCHIVED.value:
            return SessionState.ARCHIVED
        return SessionState(v_state.value)

    def get_history(self, session_id: str) -> list[StateTransition]:
        history = [
            self._to_state_transition(c)
            for c in self._sm().get_history(session_id)
        ]
        history.extend(self._archive_history.get(session_id, []))
        return history

    def get_allowed_transitions(
        self, current_state: SessionState | str
    ) -> tuple[SessionState, ...]:
        if isinstance(current_state, str) and not isinstance(current_state, SessionState):
            current_state = SessionState(current_state)
        return tuple(
            t.to_state for t in VALID_TRANSITIONS if t.from_state == current_state
        )

    # ── Health / lifecycle ───────────────────────────────────────────────

    def is_healthy(self) -> bool:
        # Sync + non-throwing per ADR-022 rule 3.
        return not self._closed

    async def close(self) -> None:
        self._closed = True
        vendor_bindings.unbind_all()
        _reset_vendor_state_machine()
