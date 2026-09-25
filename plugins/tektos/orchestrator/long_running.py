"""plugins.tektos.orchestrator.long_running — Tektos long-running agent.

Rewrite of donor ``tektos-ultima/src/tektos/runtime/long_running_agent.py``
(492 lines) per ADR-114 D2/D3. What is preserved verbatim from the donor:

* State machine surface (``start`` / ``stop`` / ``pause`` / ``resume``),
  progress tracking (``update_progress``), context bag
  (``set_context`` / ``get_context``), tool-result ring
  (``add_tool_result``), ``to_memory_entry`` serialization shape, and
  the checkpoint interval policy (``checkpoint_if_needed``).
* ``AgentCheckpoint`` / ``AgentProgress`` dataclasses (moved to
  ``models.py``; ``to_dict`` / ``from_dict`` / ``to_markdown`` kept).

What changes (ADR-114 D2/D3, R3):

* Donor persistence was ``CheckpointManager`` writing raw JSON files to
  ``./checkpoints/`` (rejected per R3 — kernel state must not touch the
  working tree). The rewrite persists through
  ``RelationalMemoryPort.record_event`` with locked kinds
  ``tektos.long_running.checkpoint`` / ``tektos.long_running.heartbeat``
  and resumes via ``RelationalMemoryPort.query_events``.
* Fail-open (ADR-101): when the memory port is unbound or a write
  fails, checkpoints/heartbeats are kept in the in-memory ring buffer so
  the agent keeps functioning; ``wired`` reflects the live state.
* Donor module-level ``_agents`` singleton rejected (R4); the kernel
  owns one engine instance per registry slot.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from typing import Any, Protocol

from . import (
    TEKTOS_LONG_RUNNING_CHECKPOINT_KIND,
    TEKTOS_LONG_RUNNING_HEARTBEAT_KIND,
    TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE,
    TEKTOS_ORCHESTRATOR_PROVENANCE,
)
from .models import AgentCheckpoint, AgentProgress, LongRunningState

log = logging.getLogger(__name__)

# Donor policy constants (verbatim).
_CHECKPOINT_INTERVAL_SECONDS = 30.0
_MAX_TOOL_RESULTS = 50
_MAX_CONTEXT_KEYS = 200


class _RelationalMemoryLike(Protocol):
    """Structural type for the RelationalMemoryPort surface used here (D3)."""

    async def record_event(
        self,
        *,
        kind: str,
        session_id: str | None,
        agent_id: str | None,
        payload: dict[str, Any],
        confidence: float,
        provenance: str,
    ) -> str: ...

    async def query_events(
        self,
        *,
        kind_prefix: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> tuple[Any, ...]: ...


class TektosLongRunningAgent:
    """Long-running checkpoint/resume agent (donor ``LongRunningAgent``)."""

    def __init__(
        self,
        *,
        relational_memory: _RelationalMemoryLike | None = None,
        session_id: str | None = None,
        checkpoint_interval: float = _CHECKPOINT_INTERVAL_SECONDS,
        max_checkpoints: int = 100,
    ) -> None:
        self.session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self._memory = relational_memory
        self._checkpoint_interval = checkpoint_interval
        self._state: LongRunningState = "idle"
        self._context: dict[str, Any] = {}
        self._tool_results: deque[dict[str, Any]] = deque(maxlen=_MAX_TOOL_RESULTS)
        self._error: str | None = None
        self._last_checkpoint_at: float = time.time()
        self._checkpoints: deque[AgentCheckpoint] = deque(maxlen=max_checkpoints)
        self.progress = AgentProgress(
            session_id=self.session_id,
            started_at=time.time(),
            last_checkpoint_at=time.time(),
        )
        self.checkpoint_count: int = 0
        self.heartbeat_count: int = 0

    # ── Introspection ──────────────────────────────────────────────────────

    @property
    def state(self) -> LongRunningState:
        return self._state

    @property
    def wired(self) -> bool:
        return self._memory is not None

    @property
    def last_checkpoint(self) -> AgentCheckpoint | None:
        return self._checkpoints[0] if self._checkpoints else None

    @property
    def recent_checkpoints(self) -> list[AgentCheckpoint]:
        return list(self._checkpoints)

    # ── Lifecycle (donor surface) ──────────────────────────────────────────

    async def start(self) -> None:
        """Start the agent (donor ``start``)."""
        self._state = "running"
        self.progress.status = "running"
        self.progress.started_at = time.time()

    async def stop(self, reason: str = "completed") -> None:
        """Stop the agent, writing a final checkpoint (donor ``stop``)."""
        self._state = "completed" if reason == "completed" else "failed"
        self.progress.status = self._state
        await self._create_checkpoint(next_action=None)

    async def pause(self) -> None:
        """Pause the agent (donor ``pause``)."""
        if self._state != "running":
            return
        self._state = "paused"
        self.progress.status = "paused"

    async def resume(self) -> bool:
        """Resume from the most recent checkpoint (donor ``resume``).

        A locally-paused/checkpointed agent resumes in place; an ``idle``
        agent (e.g. after a kernel restart) may resume *if* the memory
        port has a checkpoint for its session.
        """
        if self._state not in ("paused", "checkpointed"):
            if not (self._state == "idle" and self._memory is not None):
                return False
        if self._memory is not None and not self._checkpoints:
            await self._restore_from_memory()
        if not self._checkpoints and self._state != "paused":
            return False
        self._state = "running"
        self.progress.status = "running"
        return True

    # ── Context / progress / tool results (donor surface) ─────────────────

    def update_progress(
        self, current_step: str, completed: bool = False, total: int | None = None
    ) -> None:
        """Update progress tracking (donor ``update_progress``)."""
        self.progress.current_step = current_step
        if total is not None:
            self.progress.total_steps = total
        if completed:
            self.progress.completed_steps += 1
        self.progress.last_checkpoint_at = time.time()

    def set_context(self, key: str, value: Any) -> None:
        """Set a context value (donor ``set_context``; bounded per R3)."""
        if len(self._context) >= _MAX_CONTEXT_KEYS and key not in self._context:
            log.warning("tektos.long_running: context full (%d keys)", _MAX_CONTEXT_KEYS)
            return
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """Get a context value (donor ``get_context``)."""
        return self._context.get(key, default)

    def add_tool_result(self, tool_name: str, result: dict[str, Any]) -> None:
        """Record a tool result (donor ``add_tool_result``; bounded ring)."""
        self._tool_results.append(
            {"tool": tool_name, "result": result, "at": time.time()}
        )

    def set_error(self, error: str) -> None:
        """Record an error (donor ``set_error``)."""
        self._error = error
        self.progress.error = error

    def to_memory_entry(self) -> dict[str, Any]:
        """Serialize agent state to a memory entry (donor shape)."""
        return {
            "session_id": self.session_id,
            "state": self._state,
            "context": dict(self._context),
            "tool_results": list(self._tool_results),
            "progress": {
                "current_step": self.progress.current_step,
                "progress_percent": round(self.progress.progress_percent, 1),
                "elapsed_minutes": round(self.progress.elapsed_minutes, 2),
            },
            "error": self._error,
            "checkpoint_count": self.checkpoint_count,
        }

    # ── Checkpoints / heartbeats (ADR-114 D3) ──────────────────────────────

    async def _create_checkpoint(self, next_action: str | None) -> AgentCheckpoint | None:
        """Create a checkpoint (donor ``_create_checkpoint``; memory port)."""
        now = time.time()
        checkpoint = AgentCheckpoint(
            checkpoint_id=f"ckpt-{uuid.uuid4().hex[:8]}",
            session_id=self.session_id,
            state=self._state,
            timestamp=now,
            context=dict(self._context),
            memory=self.to_memory_entry(),
            tool_results=tuple(self._tool_results),
            next_action=next_action,
            error=self._error,
        )
        self._checkpoints.appendleft(checkpoint)
        self._last_checkpoint_at = now
        self.progress.last_checkpoint_at = now
        memory = self._memory
        if memory is not None:
            try:
                event_id = await memory.record_event(
                    kind=TEKTOS_LONG_RUNNING_CHECKPOINT_KIND,
                    session_id=self.session_id,
                    agent_id=self.session_id,
                    payload=checkpoint.to_dict(),
                    confidence=TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE,
                    provenance=TEKTOS_ORCHESTRATOR_PROVENANCE,
                )
                checkpoint = _replace_event_id(checkpoint, event_id)
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.long_running: record_event checkpoint failed (fail-open)"
                )
        self.checkpoint_count += 1
        return checkpoint

    async def checkpoint_if_needed(self) -> bool:
        """Checkpoint if the interval has elapsed (donor policy verbatim)."""
        if self._state != "running":
            return False
        if time.time() - self._last_checkpoint_at < self._checkpoint_interval:
            return False
        await self._create_checkpoint(next_action=self.progress.current_step or None)
        return True

    async def heartbeat(self, note: str = "") -> None:
        """Emit a heartbeat through the memory port (Plan v2 line 102)."""
        memory = self._memory
        if memory is None:
            return
        try:
            await memory.record_event(
                kind=TEKTOS_LONG_RUNNING_HEARTBEAT_KIND,
                session_id=self.session_id,
                agent_id=self.session_id,
                payload={
                    "state": self._state,
                    "current_step": self.progress.current_step,
                    "progress_percent": round(self.progress.progress_percent, 1),
                    "note": note,
                },
                confidence=TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE,
                provenance=TEKTOS_ORCHESTRATOR_PROVENANCE,
            )
            self.heartbeat_count += 1
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.long_running: record_event heartbeat failed (fail-open)"
            )

    async def _restore_from_memory(self) -> int:
        """Load the session's checkpoints from the memory port (resume path)."""
        if self._memory is None:
            return 0
        restored = 0
        try:
            rows = await self._memory.query_events(
                kind_prefix=TEKTOS_LONG_RUNNING_CHECKPOINT_KIND,
                session_id=self.session_id,
                limit=10,
            )
        except Exception:  # noqa: BLE001
            log.exception("tektos.long_running: query_events restore failed (fail-open)")
            return 0
        for row in reversed(rows):  # rows are DESC; restore oldest→newest
            try:
                checkpoint = AgentCheckpoint.from_dict(row.payload)
            except Exception:  # noqa: BLE001
                continue
            checkpoint = _replace_event_id(checkpoint, row.event_id)
            self._checkpoints.appendleft(checkpoint)
            restored += 1
        if restored:
            newest = self._checkpoints[0]
            self._context = dict(newest.context)
            self._error = newest.error
            if newest.state in ("paused", "checkpointed", "running"):
                self._state = "paused"
        return restored


def _replace_event_id(checkpoint: AgentCheckpoint, event_id: str) -> AgentCheckpoint:
    """Return a copy of the checkpoint with the ledger ``event_id`` set."""
    return AgentCheckpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        session_id=checkpoint.session_id,
        state=checkpoint.state,
        timestamp=checkpoint.timestamp,
        context=checkpoint.context,
        memory=checkpoint.memory,
        tool_results=checkpoint.tool_results,
        next_action=checkpoint.next_action,
        error=checkpoint.error,
        event_id=event_id,
    )


__all__ = ["TektosLongRunningAgent"]
