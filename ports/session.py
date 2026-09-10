"""SessionPort — the 24th formal Kosmos port (ADR-103).

Substrate for Stages 8.1–8.7: the session-lifecycle FSM that the Tektos
turn loop, reflection/synthesis, planner, executor, manager, and
multi-agent slices all coordinate against.

Design rules (per ADR-103):

1. **Transport-neutral.** The port takes no assumption about *what* is
   attached to a live session — WebSocket, SSE, HTTP long-poll, or an
   in-process test harness. Hence ``attach_client`` / ``detach_client``
   in place of the donor's ``add_ws_connection`` / ``remove_ws_connection``.

2. **FSM is authoritative.** ``SessionState`` is a first-class enum with
   an explicit transition table. Invalid transitions raise
   :class:`InvalidTransitionError`. There is no raw-string status field
   on the port contract — string status only survives inside the
   ``LiveSession.status`` field for donor-compat wire shapes.

3. **Zero coupling to EventBusPort in the Protocol.** Adapters that
   emit events do so through an ``EventBusPort`` injected at
   construction. The port itself is a plain lifecycle contract.

4. **Optional RelationalMemoryPort mirror.** Adapters MAY accept an
   optional ``RelationalMemoryPort`` and mirror every StateTransition
   into the Stage 8.0 audit ledger with
   ``provenance="tektos.session"`` and ``confidence=1.0`` (ADR-008
   parity). Mirror failures MUST NOT roll back the FSM transition —
   the FSM is the source of truth, the ledger is derived audit.

5. ``is_healthy()`` MUST be sync + non-throwing (ADR-022 rule 3;
   ADR-100 D1).

6. ``close()`` MUST be async + idempotent.

Adapters live under ``adapters/session/<backend>/`` and MUST implement
this Protocol in full.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "SessionState",
    "InvalidTransitionError",
    "StateTransition",
    "LiveSession",
    "Transition",
    "VALID_TRANSITIONS",
    "is_valid_transition",
    "SessionPort",
    "SESSION_PROVENANCE",
    "SESSION_MIRROR_CONFIDENCE",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_PROVENANCE: str = "tektos.session"
"""Locked ``provenance`` string for every RelationalMemoryPort mirror
write emitted by a session adapter (ADR-103 D2)."""

SESSION_MIRROR_CONFIDENCE: float = 1.0
"""Locked ``confidence`` value for every RelationalMemoryPort mirror
write (ADR-103 D2). State transitions are ground truth from the FSM's
perspective, not inferred claims."""


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------


class SessionState(str, Enum):
    """First-class session lifecycle states (ADR-103 D1).

    Renamed from donor ``State`` to avoid collision with donor
    ``session_state.SessionState`` (a distinct progress-snapshot
    dataclass out of Stage 8.1 scope; ADR-103 D7 records the future
    rename obligation).

    ``ARCHIVED`` is a first-class enum member — the donor uses the raw
    string ``"archived"`` for archival transitions; the port lifts it
    into the enum so the transition table is explicit.
    """

    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    IDLE = "idle"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when an FSM transition is not in :data:`VALID_TRANSITIONS`."""


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transition:
    """A single allowed FSM edge (frozen for hashing)."""

    from_state: SessionState
    to_state: SessionState
    description: str = ""


VALID_TRANSITIONS: tuple[Transition, ...] = (
    # 7 donor transitions (verbatim from tektos-ultima state_machine.py).
    Transition(SessionState.CREATED, SessionState.READY, "Session initialized"),
    Transition(SessionState.READY, SessionState.RUNNING, "Turn started"),
    Transition(SessionState.READY, SessionState.IDLE, "No connections"),
    Transition(SessionState.RUNNING, SessionState.READY, "Turn completed normally"),
    Transition(SessionState.RUNNING, SessionState.FAILED, "Turn failed"),
    Transition(SessionState.RUNNING, SessionState.INTERRUPTED, "Turn interrupted"),
    Transition(SessionState.INTERRUPTED, SessionState.READY, "Interrupted, returned to ready"),
    # Kosmos delta transitions (ADR-103 D1).
    Transition(SessionState.IDLE, SessionState.READY, "Client reattached to idle session"),
    Transition(SessionState.READY, SessionState.ARCHIVED, "Archived from ready"),
    Transition(SessionState.IDLE, SessionState.ARCHIVED, "Archived from idle"),
    Transition(SessionState.INTERRUPTED, SessionState.ARCHIVED, "Archived from interrupted"),
)


def is_valid_transition(
    from_state: SessionState | str,
    to_state: SessionState | str,
) -> bool:
    """Return ``True`` when the edge appears in :data:`VALID_TRANSITIONS`.

    Accepts either enum members or their string values for
    donor-compat call sites.
    """
    if isinstance(from_state, str) and not isinstance(from_state, SessionState):
        from_state = SessionState(from_state)
    if isinstance(to_state, str) and not isinstance(to_state, SessionState):
        to_state = SessionState(to_state)
    return any(
        t.from_state == from_state and t.to_state == to_state
        for t in VALID_TRANSITIONS
    )


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateTransition:
    """A record of a single FSM transition.

    Emitted by every successful :meth:`SessionPort.transition`-style
    call. Frozen so downstream consumers (e.g. the RelationalMemoryPort
    mirror) can capture it without defensive copies.
    """

    session_id: str
    from_state: str  # SessionState.value
    to_state: str  # SessionState.value
    reason: str
    timestamp_iso: str  # UTC ISO-8601
    timestamp_mono: float  # `time.monotonic()`


@dataclass(slots=True)
class LiveSession:
    """A single active or archived session.

    Kept mutable (not frozen) because adapters update
    ``updated_at`` / ``seq`` / ``status`` / ``title`` / ``tag`` /
    ``attached_clients`` in place. The port's public API returns
    ``LiveSession`` instances by reference — callers MUST treat them
    as read-only snapshots.
    """

    id: str
    model: str
    cwd: str
    permission_mode: str = "auto"  # "auto" | "manual"
    status: str = SessionState.CREATED.value
    title: str = ""
    tag: str = ""
    root_session_id: str | None = None
    created_at: float = 0.0  # monotonic — adapter fills at construction
    updated_at: float = 0.0  # monotonic — adapter fills at construction
    seq: int = 0
    attached_clients: set[str] = field(default_factory=set)

    @property
    def is_active(self) -> bool:
        return self.status in (
            SessionState.READY.value,
            SessionState.RUNNING.value,
            SessionState.IDLE.value,
        )

    @property
    def is_failed(self) -> bool:
        return self.status == SessionState.FAILED.value

    @property
    def is_archived(self) -> bool:
        return self.status == SessionState.ARCHIVED.value

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionPort(Protocol):
    """Formal contract for Kosmos session lifecycle management."""

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        model: str,
        cwd: str = ".",
        permission_mode: str = "auto",
        resume_session_id: str | None = None,
        fork_session_id: str | None = None,
    ) -> LiveSession:
        """Create a new session. Transitions ``CREATED → READY``."""
        ...

    async def get_session(self, session_id: str) -> LiveSession | None:
        """Return the ``LiveSession`` for ``session_id``, or ``None``."""
        ...

    async def list_sessions(self, *, archived: bool = False) -> list[LiveSession]:
        """List live sessions (or archived when ``archived=True``).

        Ordered by ``updated_at`` descending.
        """
        ...

    # ── Client attach / detach (transport-neutral) ────────────────────────

    async def attach_client(self, session_id: str, client_id: str) -> bool:
        """Attach an opaque client id to a session.

        Returns ``False`` when the session does not exist. On success
        the session transitions toward READY if it was IDLE, and its
        ``attached_clients`` set gains ``client_id``.
        """
        ...

    async def detach_client(self, session_id: str, client_id: str) -> None:
        """Detach a client id. Silent on unknown sessions or client ids.

        When the last client detaches and the session is READY, the
        adapter transitions the session to IDLE.
        """
        ...

    # ── Turn FSM edges ────────────────────────────────────────────────────

    async def start_turn(self, session_id: str, *, reason: str = "") -> StateTransition:
        """Drive ``READY → RUNNING``."""
        ...

    async def complete_turn(
        self, session_id: str, *, reason: str = ""
    ) -> StateTransition:
        """Drive ``RUNNING → READY``."""
        ...

    async def fail_turn(self, session_id: str, *, reason: str = "") -> StateTransition:
        """Drive ``RUNNING → FAILED``."""
        ...

    async def interrupt_turn(
        self, session_id: str, *, reason: str = ""
    ) -> StateTransition:
        """Drive ``RUNNING → INTERRUPTED``."""
        ...

    # ── Housekeeping ──────────────────────────────────────────────────────

    async def archive_session(self, session_id: str) -> None:
        """Archive a session. Transitions ``READY|IDLE|INTERRUPTED → ARCHIVED``."""
        ...

    async def fork_session(
        self,
        source_session_id: str,
        *,
        model: str,
        cwd: str = ".",
    ) -> LiveSession:
        """Create a fork of an existing session.

        The new session's ``root_session_id`` is set to
        ``source_session_id``; its title defaults to
        ``"fork of <source title or shortid>"``.
        """
        ...

    async def resume_session(self, session_id: str) -> LiveSession:
        """Resume an archived session as a new live session.

        Raises :class:`ValueError` if the session is not archived.
        """
        ...

    async def rename_session(self, session_id: str, new_title: str) -> None:
        """Update the session title. No FSM transition."""
        ...

    async def tag_session(self, session_id: str, tag: str) -> None:
        """Update the session tag. No FSM transition."""
        ...

    async def delete_session(self, session_id: str) -> int:
        """Delete a session and its events. Returns count of events purged.

        At Stage 8.1 the event-store deletion path is deferred to
        Stage 13 (ADR-103 D3); adapters MAY return 0 with an INFO log
        until then.
        """
        ...

    async def reap_failed_sessions(self, *, timeout: float = 300.0) -> int:
        """Reap failed sessions idle for more than ``timeout`` seconds.

        Returns count reaped.
        """
        ...

    async def search_sessions(
        self,
        *,
        query: str,
        sort: str = "updated_at",
        order: str = "desc",
    ) -> list[LiveSession]:
        """Search sessions by title / tag / id / root id substring."""
        ...

    # ── FSM introspection ─────────────────────────────────────────────────

    def get_state(self, session_id: str) -> SessionState:
        """Return the current FSM state. Defaults to CREATED for unknown ids."""
        ...

    def get_history(self, session_id: str) -> list[StateTransition]:
        """Return the ordered transition history for ``session_id``."""
        ...

    def get_allowed_transitions(
        self, current_state: SessionState | str
    ) -> tuple[SessionState, ...]:
        """Return the tuple of allowed next states from ``current_state``."""
        ...

    # ── Health + lifecycle ────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Sync, non-throwing (ADR-022 rule 3; ADR-100 D1)."""
        ...

    async def close(self) -> None:
        """Idempotent shutdown."""
        ...


# ---------------------------------------------------------------------------
# Any-typed re-exports for adapters that hold optional dependencies
# ---------------------------------------------------------------------------

# Kept intentionally as Any: adapters that accept optional
# EventBusPort / RelationalMemoryPort dependencies avoid importing
# those ports at adapter-module scope so the port contract stays
# minimal. Adapters do their own runtime isinstance checks.
_OptionalDep = Any
