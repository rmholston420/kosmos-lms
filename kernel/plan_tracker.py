"""kernel.plan_tracker — the plan-lifecycle tracker (ADR-141 T4b).

Donor-faithful port of ``tektos-ultima/src/tektos/runtime/planner_orchestrator.py``
(~130 LOC). The donor's ``PlannerOrchestrator`` is pure in-memory
plan-tracking machinery — dataclasses + a dict of plans, no LLM, no plugin
behavior — so per the porting layering rule it is ELEVATED to the kernel
(the same class as the other generic runtime substrate), not to
``plugins/tektos/``. The Tektos-specific bit — *creating* a plan at task
start and broadcasting ``plan.*`` WS events (donor ``runtime/sdk.py:889``)
— rides with the ADR-140 WebSocket work; this module only tracks.

Wire referent: ``GET /api/planner/status`` (donor ``main.py:4650``) returns
``{"status": "initialized", "stats": get_plan_stats()}``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in a plan.

    Donor-faithful fields (donor ``runtime/planner_orchestrator.py:21``):
    ``step_id/description/status/result/error``.
    """

    step_id: str
    description: str
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: str = ""


@dataclass
class Plan:
    """A plan with steps.

    Donor-faithful fields (donor ``runtime/planner_orchestrator.py:33``):
    ``plan_id/description/steps/status/created_at/completed_at``.
    """

    plan_id: str
    description: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "draft"  # draft, active, completed, failed
    created_at: str = ""
    completed_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


class PlanTracker:
    """Coordinates the planning lifecycle: create, track, stats.

    Verbatim port of the donor ``PlannerOrchestrator`` (renamed for its
    kernel role — it *tracks* plans; the *planning* is the Stage 8.4
    spec planner). ``create_plan`` semantics: one step per description
    when no explicit steps are given; plan ids are ``plan_1``, ``plan_2``,
    …; steps are ``step_1``, ``step_2``, … (donor-faithful).
    """

    def __init__(self) -> None:
        """Initialize the plan tracker."""
        self._plans: dict[str, Plan] = {}
        self._active_plan_id: str | None = None

    def create_plan(self, description: str, steps: list[str] | None = None) -> str:
        """Create a new plan from a description and optional steps."""
        plan_id = f"plan_{len(self._plans) + 1}"
        plan_steps = [
            PlanStep(step_id=f"step_{i + 1}", description=desc)
            for i, desc in enumerate(steps or [description])
        ]
        plan = Plan(plan_id=plan_id, description=description, steps=plan_steps)
        self._plans[plan_id] = plan
        return plan_id

    def get_plan(self, plan_id: str) -> Plan | None:
        """Get a plan by ID."""
        return self._plans.get(plan_id)

    def get_active_plan(self) -> Plan | None:
        """Get the currently active plan."""
        if self._active_plan_id:
            return self._plans.get(self._active_plan_id)
        return None

    def get_plan_stats(self) -> dict[str, Any]:
        """Get statistics about plans (donor wire: /api/planner/status)."""
        total = len(self._plans)
        active = sum(1 for p in self._plans.values() if p.status == "active")
        completed = sum(1 for p in self._plans.values() if p.status == "completed")
        failed = sum(1 for p in self._plans.values() if p.status == "failed")
        return {
            "total_plans": total,
            "active": active,
            "completed": completed,
            "failed": failed,
            "active_plan_id": self._active_plan_id,
        }

    async def start(self) -> None:
        """Initialize the plan tracker (donor lifecycle no-op, kept for
        interface parity with the donor ``PlannerOrchestrator.start``)."""
        logger.info("Plan tracker initialized")

    async def stop(self) -> None:
        """Clean up the plan tracker (donor lifecycle no-op)."""
        logger.info("Plan tracker stopped")


__all__ = ["Plan", "PlanStep", "PlanTracker"]
