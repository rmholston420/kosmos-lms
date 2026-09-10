"""Tektos-Ultima v1 — Session State Machine

Explicit state machine for session lifecycle.
Replaces the ad-hoc status field in LiveSession with a proper FSM.

State transitions:
  created → ready
  ready → running
  running → ready | interrupted | failed
  interrupted → ready
  failed → (removed from system)

Safety:
- Invalid transitions raise InvalidTransitionError
- Each transition emits a state_change event to the event bus
- S3 (Manager) can subscribe to all state transitions and intervene
- Transition history is recorded for replay/debugging

VSM Mapping:
- S3 (Manager) monitors all transitions via event bus
- S2 (Event Stream) records every state_change event
- S4 (Planner) can be triggered on repeated failed transitions
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from adapters.session.tektos.vendor_bindings import get_event_bus  # ADR-103 D2 rewrite

log = logging.getLogger("tektos.state_machine")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class State(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    IDLE = "idle"


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    pass


# ---------------------------------------------------------------------------
# Transition definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transition:
    """Defines an allowed state transition."""

    from_state: State
    to_state: State
    description: str = ""


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

# All valid transitions (source → target → description)
VALID_TRANSITIONS = [
    Transition(State.CREATED, State.READY, "Session initialized, ready for connections"),
    Transition(State.READY, State.RUNNING, "Processing prompt"),
    Transition(State.RUNNING, State.READY, "Completed normally"),
    Transition(State.RUNNING, State.FAILED, "Execution failed"),
    Transition(State.RUNNING, State.INTERRUPTED, "Manually interrupted"),
    Transition(State.INTERRUPTED, State.READY, "Interrupted, returned to ready"),
    Transition(State.READY, State.IDLE, "No connections, going idle"),
]


class StateMachine:
    """Explicit state machine for session lifecycle.

    Public API:
      - transition(session_id, new_state, reason) -> StateChange
      - get_state(session_id) -> State
      - get_history(session_id) -> list[StateChange]
      - is_valid_transition(from_state, to_state) -> bool
    """

    def __init__(self) -> None:
        self._states: dict[str, State] = {}
        self._history: dict[str, list[StateChange]] = defaultdict(list)
        self._transitions_completed: int = 0
        self._invalid_attempts: int = 0

    def transition(
        self,
        session_id: str,
        new_state: State | str,
        reason: str = "",
    ) -> StateChange:
        """Transition a session to a new state.

        Raises InvalidTransitionError if the transition is not allowed.
        Emits a state_change event to the event bus.
        Returns the StateChange record.
        """
        if isinstance(new_state, str):
            new_state = State(new_state)

        current = self._states.get(session_id)

        if current is None:
            # First time seeing this session — default to CREATED
            current = State.CREATED

        # Validate transition
        if not self.is_valid_transition(current, new_state):
            self._invalid_attempts += 1
            raise InvalidTransitionError(
                f"Invalid transition for session {session_id}: "
                f"{current.value} → {new_state.value} "
                f"(reason: {reason})"
            )

        old_state = current
        self._states[session_id] = new_state

        change = StateChange(
            session_id=session_id,
            from_state=old_state.value,
            to_state=new_state.value,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
            timestamp_mono=time.monotonic(),
        )

        self._history[session_id].append(change)
        self._transitions_completed += 1

        log.info(f"Session {session_id[:8]}: {old_state.value} → {new_state.value} ({reason})")

        # Emit state_change event to event bus
        try:
            get_event_bus().publish(
                "session.state_change",
                session_id,
                {
                    "from_state": old_state.value,
                    "to_state": new_state.value,
                    "reason": reason,
                },
            )
        except Exception:
            log.exception("Failed to emit state_change event")

        return change

    def get_state(self, session_id: str) -> State:
        """Get the current state of a session."""
        return self._states.get(session_id, State.CREATED)

    def get_history(self, session_id: str) -> list[StateChange]:
        """Get the transition history for a session."""
        return list(self._history.get(session_id, []))

    @staticmethod
    def is_valid_transition(from_state: State | str, to_state: State | str) -> bool:
        """Check if a transition is allowed."""
        if isinstance(from_state, str):
            from_state = State(from_state)
        if isinstance(to_state, str):
            to_state = State(to_state)

        return any(t.from_state == from_state and t.to_state == to_state for t in VALID_TRANSITIONS)

    def get_stats(self) -> dict[str, Any]:
        """Return state machine statistics."""
        state_counts: dict[str, int] = {}
        for s in self._states.values():
            state_counts[s.value] = state_counts.get(s.value, 0) + 1

        return {
            "total_sessions": len(self._states),
            "state_distribution": state_counts,
            "transitions_completed": self._transitions_completed,
            "invalid_attempts": self._invalid_attempts,
        }

    def get_allowed_transitions(self, current_state: State | str) -> list[str]:
        """Get list of allowed next states for a given state."""
        if isinstance(current_state, str):
            current_state = State(current_state)

        return [t.to_state.value for t in VALID_TRANSITIONS if t.from_state == current_state]


@dataclass
class StateChange:
    """Record of a state transition."""

    session_id: str
    from_state: str
    to_state: str
    reason: str
    timestamp: str
    timestamp_mono: float


# Global singleton
_state_machine: StateMachine | None = None


def get_state_machine() -> StateMachine:
    """Get or create the global StateMachine singleton."""
    global _state_machine
    if _state_machine is None:
        _state_machine = StateMachine()
    return _state_machine


def reset_state_machine() -> None:
    """Reset the global StateMachine (for testing)."""
    global _state_machine
    _state_machine = None
