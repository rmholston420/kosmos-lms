"""plugins.tektos.orchestrator.models — frozen slotted dataclasses.

Rewrite of donor ``tektos-ultima/src/tektos/runtime/{multi_agent_orchestrator,hierarchical_agent,long_running_agent}.py``
per ADR-114 D2/D4. Conventions per ADR-105/106/107/108:

* Result records (``OrchestrationResult``, ``AgentResult``,
  ``AgentCheckpoint``, ``AgentProgress``) are ``@dataclass(frozen=True,
  slots=True)`` value objects; ``replace()`` produces new records.
* Lifecycle state machines (``Subagent``, ``Task``, ``AgentTask``) stay
  **mutable** dataclasses (ADR-114 R4) — they carry per-task state that
  transitions in place, mirroring the donor's shape.
* Enum surfaces become ``Literal`` unions (donor ``Enum.value`` was
  already lowercase-string, so JSON stability is preserved).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# ── Literal unions (donor Enum surfaces, ADR-105/106/107/108 pattern) ─────


AgentRole = Literal["worker", "coordinator", "reviewer", "specialist"]
"""Orchestrator agent roles (donor ``AgentRole`` enum, 4 members)."""

HierRole = Literal[
    "architect",
    "planner",
    "coder",
    "reviewer",
    "tester",
    "deployer",
]
"""Hierarchical agent roles (donor ``AgentRole`` enum, 6 members)."""

TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
"""Task lifecycle status (donor ``TaskStatus`` enum)."""

LongRunningState = Literal[
    "idle",
    "running",
    "paused",
    "completed",
    "failed",
    "checkpointed",
]
"""Long-running agent state (donor ``AgentState`` enum)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Orchestrator: mutable lifecycle dataclasses (ADR-114 R4) ──────────────


@dataclass
class Subagent:
    """An agent that can execute tasks (donor ``Subagent``, mutable)."""

    agent_id: str
    role: AgentRole
    capabilities: tuple[str, ...] = ()
    status: TaskStatus = "pending"
    current_task: str = ""
    result: Any = None
    error: str = ""
    created_at: str = field(default_factory=_now_iso)
    completed_at: str = ""


@dataclass
class Task:
    """A task to be executed by a subagent (donor ``Task``, mutable)."""

    task_id: str
    description: str
    assigned_agent: str | None = None
    status: TaskStatus = "pending"
    priority: int = 0  # Higher = more important
    dependencies: tuple[str, ...] = ()
    result: Any = None
    error: str = ""
    escalated: bool = False  # ADR-114 D9: classify_recovery → "escalate"
    recovery_strategy: str = ""  # ADR-107 D9 discharge: strategy actually applied
    created_at: str = field(default_factory=_now_iso)
    completed_at: str = ""


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Result of an orchestration operation (donor ``OrchestrationResult``)."""

    tasks_completed: int
    tasks_failed: int
    total_duration_seconds: float
    agent_utilization: float
    results: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: f"orch-{uuid.uuid4().hex[:8]}")
    when: str = field(default_factory=_now_iso)


# ── Hierarchical: mutable task + frozen result ────────────────────────────


@dataclass
class AgentTask:
    """A task assigned to a hierarchical agent (donor ``AgentTask``, mutable).

    ``duration`` mirrors the donor property (seconds between start and
    completion, or now).
    """

    task_id: str
    role: HierRole
    description: str
    context: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    status: TaskStatus = "pending"
    result: str | None = None
    error: str | None = None
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def duration(self) -> float:
        end = self.completed_at or time.time()
        return end - self.started_at


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Result from a hierarchical agent execution (donor ``AgentResult``)."""

    task_id: str
    role: HierRole
    success: bool
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    id: str = field(default_factory=lambda: f"hier-{uuid.uuid4().hex[:8]}")
    when: str = field(default_factory=_now_iso)

    def to_markdown(self) -> str:
        """Convert to markdown for display (donor ``to_markdown`` verbatim)."""

        status = "✓" if self.success else "✗"
        role_title = self.role.title()
        err = f"\n\n**Error**: {self.error}" if self.error else ""
        return (
            f"## {status} {role_title} Agent\n\n"
            f"**Task**: {self.task_id}\n\n"
            f"**Output**:\n```\n{self.output[:500]}\n```\n{err}"
        )


# ── Long-running: frozen checkpoint + progress ────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentCheckpoint:
    """A checkpoint of agent state (donor ``AgentCheckpoint``).

    Serialized through ``RelationalMemoryPort.record_event`` with kind
    ``tektos.long_running.checkpoint`` (ADR-114 D2/D3; donor's JSON-file
    persistence REJECTED per R3).
    """

    checkpoint_id: str
    session_id: str
    state: LongRunningState
    timestamp: float
    context: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    tool_results: tuple[dict[str, Any], ...] = ()
    next_action: str | None = None
    error: str | None = None
    event_id: str | None = None  # RelationalMemoryPort ledger row, when bound

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "state": self.state,
            "timestamp": self.timestamp,
            "context": self.context,
            "memory": self.memory,
            "tool_results": list(self.tool_results),
            "next_action": self.next_action,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCheckpoint:
        """Create checkpoint from dict (donor ``from_dict``; tolerant reads)."""

        return cls(
            checkpoint_id=data["checkpoint_id"],
            session_id=data["session_id"],
            state=data["state"],
            timestamp=data["timestamp"],
            context=dict(data.get("context", {})),
            memory=dict(data.get("memory", {})),
            tool_results=tuple(data.get("tool_results", [])),
            next_action=data.get("next_action"),
            error=data.get("error"),
            event_id=data.get("event_id"),
        )


@dataclass
class AgentProgress:
    """Progress tracking for long-running agents (donor ``AgentProgress``).

    Mutable by design — it is a live gauge, not a value object.
    """

    session_id: str
    started_at: float
    last_checkpoint_at: float
    total_steps: int = 0
    completed_steps: int = 0
    current_step: str = ""
    status: str = "running"
    error: str | None = None

    @property
    def progress_percent(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.started_at

    @property
    def elapsed_minutes(self) -> float:
        return self.elapsed_seconds / 60

    def to_markdown(self) -> str:
        """Convert to markdown for display (donor ``to_markdown`` verbatim)."""

        err = f"\n**Error**: {self.error}" if self.error else ""
        return (
            f"**Session**: {self.session_id}\n"
            f"**Status**: {self.status}\n"
            f"**Progress**: {self.progress_percent:.1f}% "
            f"({self.completed_steps}/{self.total_steps} steps)\n"
            f"**Current Step**: {self.current_step}\n"
            f"**Elapsed**: {self.elapsed_minutes:.1f} minutes\n"
            f"**Last Checkpoint**: {self.last_checkpoint_at}\n"
            f"{err}"
        )


__all__ = [
    "AgentCheckpoint",
    "AgentProgress",
    "AgentResult",
    "AgentRole",
    "AgentTask",
    "HierRole",
    "LongRunningState",
    "OrchestrationResult",
    "Subagent",
    "Task",
    "TaskStatus",
]
