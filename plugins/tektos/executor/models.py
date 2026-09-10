"""plugins.tektos.executor.models — frozen slotted dataclasses.

Rewrite of donor ``tektos-ultima/src/tektos/agents/coding_agent/models.py``
per ADR-107 D2. Pydantic ``BaseModel`` → ``@dataclass(frozen=True, slots=True)``;
enums preserved as ``Literal`` unions matching ADR-105/106 shape; the donor's
W5H1M metadata block is dropped at 8.5 (Kosmos already carries provenance +
confidence through every ``RelationalMemoryPort`` write per ADR-008, and
audit fields live in the ``StateTransition`` / ``EventEnvelope`` layer).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# ── Enums (Literal unions per ADR-105/106 pattern) ─────────────────────────

ExecutionStatus = Literal[
    "pending",
    "executing",
    "completed",
    "failed",
    "aborted",
    "sandbox_unavailable",
]
"""Execution status. ``sandbox_unavailable`` added per ADR-107 D9 fail-open
for environments where no ``SandboxPort`` is wired at boot."""

ArtifactType = Literal[
    "source_code",
    "test_code",
    "config",
    "documentation",
    "other",
]
"""Kind of artifact produced. ``migration`` from donor collapsed into
``source_code`` (Stage 8.5 does not produce Alembic migrations)."""

TestReportStatus = Literal["passed", "failed", "skipped", "error"]


# ── Frozen slotted dataclasses ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExecutionTestReport:
    """Result of running tests during a phase (donor ``ExecutionTestReport``)."""

    name: str
    status: TestReportStatus
    passed: int = 0
    failed: int = 0
    output: str = ""
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionArtifact:
    """A file produced by the executor (donor ``ExecutionArtifact``)."""

    path: str
    artifact_type: ArtifactType
    content_hash: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ExecutionStep:
    """A single step of an execution run (donor ``ExecutionStep``)."""

    step_number: int
    action: str
    target: str
    success: bool
    output: str = ""
    error_message: str = ""
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Complete trace of executing one ``BuildSpec`` (donor ``ExecutionRecord``).

    Frozen and slotted; downstream code must construct a new record when
    updating fields (see engine helper functions in :mod:`.engine`).
    """

    spec_id: str
    status: ExecutionStatus
    steps: tuple[ExecutionStep, ...] = ()
    artifacts: tuple[ExecutionArtifact, ...] = ()
    test_results: tuple[ExecutionTestReport, ...] = ()
    error_summary: str = ""
    total_duration_seconds: float = 0.0
    id: str = field(default_factory=lambda: f"exec-{uuid.uuid4().hex[:8]}")
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""


# ── Tool router models ─────────────────────────────────────────────────────


ToolCategory = Literal[
    "terminal",
    "file_operations",
    "search",
    "delegation",
    "web",
    "unknown",
]
"""Category assigned to a ``ToolRoute`` (donor ``ToolCategory`` enum)."""


@dataclass(frozen=True, slots=True)
class ToolRoute:
    """Routing decision for a task or tool-need spec (donor ``ToolRoute``).

    Routing-only at Stage 8.5 per ADR-107 D9 — no execution or recovery
    state machine landed at this stage.
    """

    primary_tool: str
    fallback_tools: tuple[str, ...] = ()
    category: ToolCategory = "unknown"
    reason: str = ""
    matched_tools: tuple[str, ...] = ()
    unrouted_tools: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: f"route-{uuid.uuid4().hex[:8]}")
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


__all__ = [
    "ArtifactType",
    "ExecutionArtifact",
    "ExecutionRecord",
    "ExecutionStatus",
    "ExecutionStep",
    "ExecutionTestReport",
    "TestReportStatus",
    "ToolCategory",
    "ToolRoute",
]
