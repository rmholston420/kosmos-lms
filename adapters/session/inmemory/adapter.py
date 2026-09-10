"""InMemorySessionAdapter — port-clean SessionPort implementation (ADR-103 D2).

Zero coupling to donor code, EventBusPort, or RelationalMemoryPort.
Required for CI and for downstream slices (Stage 8.2 turn loop, etc.)
that need to bind against ``SessionPort`` without pulling in the tektos
donor tree.

Concurrency: a single :class:`asyncio.Lock` guards mutations to the
session dict + FSM state + history. Read paths that do not mutate
(``get_session``, ``get_state``, ``get_history``, ``list_sessions``,
``search_sessions``) copy or snapshot under the lock and release
before returning, so callers observe consistent snapshots without the
adapter holding the lock across await boundaries.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ports.session import (
    InvalidTransitionError,
    LiveSession,
    SessionState,
    StateTransition,
    VALID_TRANSITIONS,
    is_valid_transition,
)

__all__ = ["InMemorySessionAdapter"]

log = logging.getLogger(__name__)


class InMemorySessionAdapter:
    """SessionPort adapter backed entirely by in-process dicts."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}
        self._states: dict[str, SessionState] = {}
        self._history: dict[str, list[StateTransition]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._closed = False

    # ── Internal FSM helper ──────────────────────────────────────────────

    def _transition(
        self,
        session_id: str,
        to_state: SessionState,
        reason: str,
    ) -> StateTransition:
        """Internal FSM edge. Caller MUST hold ``self._lock``."""
        current = self._states.get(session_id, SessionState.CREATED)
        if not is_valid_transition(current, to_state):
            raise InvalidTransitionError(
                f"Invalid transition for session {session_id}: "
                f"{current.value} → {to_state.value} (reason: {reason})"
            )
        change = StateTransition(
            session_id=session_id,
            from_state=current.value,
            to_state=to_state.value,
            reason=reason,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            timestamp_mono=time.monotonic(),
        )
        self._states[session_id] = to_state
        self._history[session_id].append(change)
        session = self._sessions.get(session_id)
        if session is not None:
            session.status = to_state.value
            session.updated_at = time.monotonic()
        return change

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
        session_id = str(uuid.uuid4())
        try:
            resolved_cwd = str(Path(cwd).expanduser().resolve())
        except Exception:
            resolved_cwd = cwd
        now = time.monotonic()
        session = LiveSession(
            id=session_id,
            model=model,
            cwd=resolved_cwd,
            permission_mode=permission_mode,
            status=SessionState.CREATED.value,
            root_session_id=fork_session_id or resume_session_id,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._sessions[session_id] = session
            self._states[session_id] = SessionState.CREATED
            self._transition(session_id, SessionState.READY, "session created")
        return session

    async def get_session(self, session_id: str) -> LiveSession | None:
        return self._sessions.get(session_id)

    async def list_sessions(self, *, archived: bool = False) -> list[LiveSession]:
        async with self._lock:
            sessions = list(self._sessions.values())
        filtered = [
            s
            for s in sessions
            if (s.is_archived if archived else not s.is_archived)
        ]
        return sorted(filtered, key=lambda s: s.updated_at, reverse=True)

    # ── Client attach / detach ───────────────────────────────────────────

    async def attach_client(self, session_id: str, client_id: str) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.attached_clients.add(client_id)
            current = self._states.get(session_id, SessionState.CREATED)
            # Idempotent: only transition if not already READY.
            if current == SessionState.IDLE:
                self._transition(session_id, SessionState.READY, "client attached")
            elif current != SessionState.READY:
                # A CREATED session that never landed READY somehow — defensive.
                if is_valid_transition(current, SessionState.READY):
                    self._transition(
                        session_id, SessionState.READY, "client attached"
                    )
            session.updated_at = time.monotonic()
        return True

    async def detach_client(self, session_id: str, client_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.attached_clients.discard(client_id)
            current = self._states.get(session_id, SessionState.CREATED)
            if not session.attached_clients and current == SessionState.READY:
                self._transition(session_id, SessionState.IDLE, "no clients attached")
            session.updated_at = time.monotonic()

    # ── Turn FSM edges ───────────────────────────────────────────────────

    async def start_turn(self, session_id: str, *, reason: str = "") -> StateTransition:
        async with self._lock:
            return self._transition(session_id, SessionState.RUNNING, reason or "turn started")

    async def complete_turn(
        self, session_id: str, *, reason: str = ""
    ) -> StateTransition:
        async with self._lock:
            return self._transition(
                session_id, SessionState.READY, reason or "turn completed"
            )

    async def fail_turn(self, session_id: str, *, reason: str = "") -> StateTransition:
        async with self._lock:
            return self._transition(
                session_id, SessionState.FAILED, reason or "turn failed"
            )

    async def interrupt_turn(
        self, session_id: str, *, reason: str = ""
    ) -> StateTransition:
        async with self._lock:
            return self._transition(
                session_id, SessionState.INTERRUPTED, reason or "turn interrupted"
            )

    # ── Housekeeping ─────────────────────────────────────────────────────

    async def archive_session(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"Session {session_id} not found")
            session.attached_clients.clear()
            self._transition(session_id, SessionState.ARCHIVED, "archived")

    async def fork_session(
        self,
        source_session_id: str,
        *,
        model: str,
        cwd: str = ".",
    ) -> LiveSession:
        source = self._sessions.get(source_session_id)
        if source is None:
            raise KeyError(f"Source session {source_session_id} not found")
        new_session = await self.create_session(
            model=model, cwd=cwd, fork_session_id=source_session_id
        )
        async with self._lock:
            new_session.title = f"fork of {source.title or source_session_id[:8]}"
            new_session.tag = source.tag
            new_session.updated_at = time.monotonic()
        return new_session

    async def resume_session(self, session_id: str) -> LiveSession:
        source = self._sessions.get(session_id)
        if source is None:
            raise KeyError(f"Session {session_id} not found")
        if not source.is_archived:
            raise ValueError(f"Session {session_id} is not archived")
        new_session = await self.create_session(
            model=source.model, cwd=source.cwd, resume_session_id=session_id
        )
        async with self._lock:
            new_session.title = f"resume of {source.title or session_id[:8]}"
            new_session.updated_at = time.monotonic()
        return new_session

    async def rename_session(self, session_id: str, new_title: str) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"Session {session_id} not found")
            session.title = new_title
            session.updated_at = time.monotonic()

    async def tag_session(self, session_id: str, tag: str) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"Session {session_id} not found")
            session.tag = tag
            session.updated_at = time.monotonic()

    async def delete_session(self, session_id: str) -> int:
        async with self._lock:
            if session_id not in self._sessions:
                return 0
            self._sessions.pop(session_id, None)
            self._states.pop(session_id, None)
            self._history.pop(session_id, None)
        # Stage 8.1: event-store purge deferred to Stage 13 (ADR-103 D3).
        return 0

    async def reap_failed_sessions(self, *, timeout: float = 300.0) -> int:
        now = time.monotonic()
        async with self._lock:
            to_delete = [
                sid
                for sid, session in self._sessions.items()
                if session.is_failed and (now - session.updated_at) > timeout
            ]
            for sid in to_delete:
                self._sessions.pop(sid, None)
                self._states.pop(sid, None)
                self._history.pop(sid, None)
        return len(to_delete)

    async def search_sessions(
        self,
        *,
        query: str,
        sort: str = "updated_at",
        order: str = "desc",
    ) -> list[LiveSession]:
        async with self._lock:
            sessions = list(self._sessions.values())
        if query:
            q = query.lower()
            sessions = [
                s
                for s in sessions
                if q in (s.title or "").lower()
                or q in (s.tag or "").lower()
                or q in s.id.lower()
                or q in (s.root_session_id or "").lower()
            ]
        reverse = order == "desc"
        key_fn = {
            "updated_at": lambda s: s.updated_at,
            "created_at": lambda s: s.created_at,
            "title": lambda s: s.title or "",
            "tag": lambda s: s.tag or "",
            "root": lambda s: s.root_session_id or "",
        }.get(sort, lambda s: s.updated_at)
        sessions.sort(key=key_fn, reverse=reverse)
        return sessions

    # ── FSM introspection ────────────────────────────────────────────────

    def get_state(self, session_id: str) -> SessionState:
        return self._states.get(session_id, SessionState.CREATED)

    def get_history(self, session_id: str) -> list[StateTransition]:
        return list(self._history.get(session_id, []))

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
        # Deliberate: retain sessions/history in memory so `is_healthy`
        # remains a pure closed-flag check and repeated `close()` calls
        # are idempotent (ADR-103 D1).
