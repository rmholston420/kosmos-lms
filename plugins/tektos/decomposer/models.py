"""plugins.tektos.decomposer.models — frozen slotted dataclasses.

Rewrite of donor ``SubTask`` and ``DecompositionPlan`` from
``tektos-ultima/src/tektos/runtime/task_decomposer.py`` as (frozen=True,
slots=True) dataclasses per ADR-106 D2. Immutable and hashable — matches
the ADR-105 experience-record shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

SubTaskStatus = Literal["pending", "complete"]
DecompositionPhase = Literal["research", "scaffold", "implement", "verify"]


@dataclass(frozen=True, slots=True)
class SubTask:
    """A single decomposed sub-task."""

    step_number: int
    description: str
    expected_output: str
    tools_needed: tuple[str, ...] = ()
    status: SubTaskStatus = "pending"


@dataclass(frozen=True, slots=True)
class DecompositionPlan:
    """A complete task decomposition plan."""

    original_task: str
    sub_tasks: tuple[SubTask, ...] = ()
    phase: DecompositionPhase = "research"
    id: str = field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:8]}")
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


__all__ = ["DecompositionPhase", "DecompositionPlan", "SubTask", "SubTaskStatus"]
