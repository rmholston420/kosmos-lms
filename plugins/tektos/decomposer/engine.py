"""Kosmos-native ``TaskDecomposer`` (Stage 8.4 · ADR-106).

Rewrite of ``tektos-ultima/src/tektos/runtime/task_decomposer.py`` per ADR-106
D2. Rule-based branch predicates and per-branch ``SubTask`` sequences preserved
verbatim; the donor's in-memory ``_plans`` dict is replaced by persistence
through ``RelationalMemoryPort.write_narrative`` with an in-process ring-buffer
fallback (ADR-106 D3).

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

from ports.event_envelope import EventEnvelope

from . import (
    TEKTOS_DECOMPOSER_DEFAULT_CONFIDENCE,
    TEKTOS_DECOMPOSER_PREDICATE,
    TEKTOS_DECOMPOSER_PROVENANCE,
)
from .models import DecompositionPlan, SubTask

log = logging.getLogger(__name__)


@runtime_checkable
class _RelationalMemoryLike(Protocol):
    async def write_narrative(
        self,
        *,
        session_id: str,
        agent_id: str | None,
        title: str,
        body: str,
        tags: tuple[str, ...],
        embedding: tuple[float, ...] | None,
        confidence: float,
        provenance: str,
    ) -> str: ...


@runtime_checkable
class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


# ── Branch predicates (verbatim from donor) ─────────────────────────────────


def _is_build_task(task: str) -> bool:
    return any(kw in task for kw in ("build", "compile", "make", "cmake", "ccomp"))


def _is_code_generation_task(task: str) -> bool:
    return any(kw in task for kw in ("write", "create", "implement", "generate"))


def _is_regex_or_pattern_task(task: str) -> bool:
    return any(kw in task for kw in ("regex", "pattern", "chess", "fen", "re.json"))


def _is_download_build_task(task: str) -> bool:
    return any(
        kw in task for kw in ("download", "fetch", "clone", "git clone", "tar", "tarball")
    )


# ── Branch bodies (verbatim from donor) ─────────────────────────────────────


def _decompose_build_task(task: str) -> DecompositionPlan:
    return DecompositionPlan(
        original_task=task,
        sub_tasks=(
            SubTask(1, "Check available tools: gcc, g++, make, cmake, python3, etc.",
                    "List of available build tools and their versions", ("bash",)),
            SubTask(2, "Download or clone source code to /tmp/",
                    "Source code extracted in /tmp/<project>/",
                    ("web_fetch", "bash")),
            SubTask(3, "Read README/INSTALL for build instructions",
                    "Build instructions identified", ("file_read",)),
            SubTask(4, "Configure the build (./configure, cmake, etc.)",
                    "Build system configured successfully", ("bash",)),
            SubTask(5, "Build the project (make, cmake --build, etc.)",
                    "Binary/executable produced", ("bash",)),
            SubTask(6, "Verify the build output exists and works",
                    "Binary runs successfully or produces expected output", ("bash",)),
        ),
    )


def _decompose_code_generation(task: str) -> DecompositionPlan:
    return DecompositionPlan(
        original_task=task,
        sub_tasks=(
            SubTask(1, "Create the file with complete implementation. Write ALL code "
                       "now — do not plan or research first.",
                    "File created with full working implementation", ("file_write",)),
            SubTask(2, "Test the implementation with sample inputs using bash",
                    "Test runs successfully, output matches expectations", ("bash",)),
            SubTask(3, "Fix any issues and verify final output",
                    "Final file is correct and complete", ("file_write", "bash")),
        ),
    )


def _decompose_regex_task(task: str) -> DecompositionPlan:
    return DecompositionPlan(
        original_task=task,
        sub_tasks=(
            SubTask(1, "Write the complete Python script that implements the regex "
                       "transformations. Write ALL code now.",
                    "Python script created with full implementation",
                    ("file_write",)),
            SubTask(2, "Test the script with sample inputs using bash",
                    "Script runs correctly on test inputs", ("bash",)),
            SubTask(3, "Fix any issues and verify final output",
                    "Final script is correct and complete", ("file_write", "bash")),
        ),
    )


def _decompose_download_build(task: str) -> DecompositionPlan:
    return DecompositionPlan(
        original_task=task,
        sub_tasks=(
            SubTask(1, "Find the download URL for the source code",
                    "Download URL identified", ("web_search",)),
            SubTask(2, "Download and extract the source code to /tmp/",
                    "Source code extracted in /tmp/<project>/",
                    ("web_fetch", "bash")),
            SubTask(3, "Read build instructions (README, INSTALL, Makefile)",
                    "Build process understood", ("file_read",)),
            SubTask(4, "Install any missing dependencies",
                    "All dependencies installed", ("bash",)),
            SubTask(5, "Build the project", "Build succeeds, binary produced", ("bash",)),
            SubTask(6, "Verify the build output", "Binary works correctly", ("bash",)),
        ),
    )


def _decompose_generic(task: str) -> DecompositionPlan:
    return DecompositionPlan(
        original_task=task,
        sub_tasks=(
            SubTask(1, "Understand the task: identify inputs, outputs, and constraints",
                    "Clear task requirements documented",
                    ("web_search", "web_extract")),
            SubTask(2, "Plan the approach: identify tools and steps needed",
                    "Implementation plan with numbered steps", ("bash",)),
            SubTask(3, "Implement the solution: write code/files as needed",
                    "Implementation files created", ("file_write", "bash")),
            SubTask(4, "Test and verify the solution",
                    "Solution produces correct output", ("bash",)),
        ),
    )


def _plan_to_body(plan: DecompositionPlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "original_task": plan.original_task,
        "phase": plan.phase,
        "created_at": plan.created_at,
        "sub_tasks": [
            {
                "step_number": st.step_number,
                "description": st.description,
                "expected_output": st.expected_output,
                "tools_needed": list(st.tools_needed),
                "status": st.status,
            }
            for st in plan.sub_tasks
        ],
    }


class TaskDecomposer:
    """Kosmos Tektos task-decomposer engine (ADR-106 D1)."""

    def __init__(
        self,
        *,
        relational_memory: _RelationalMemoryLike | None = None,
        event_bus: _EventBusLike | None = None,
        max_records: int = 100,
    ) -> None:
        self._relational_memory = relational_memory
        self._event_bus = event_bus
        self._buffer: deque[DecompositionPlan] = deque(maxlen=max_records)

    @property
    def is_persistence_bound(self) -> bool:
        return self._relational_memory is not None

    async def decompose(
        self,
        *,
        session_id: str,
        task: str,
        task_id: str | None = None,  # noqa: ARG002 — reserved for caller correlation
        confidence: float | None = None,
    ) -> tuple[DecompositionPlan, str | None]:
        """Decompose ``task`` into a sequenced plan.

        Never raises (fail-open). Returns ``(plan, narrative_id)`` — the id is
        ``None`` when persistence is unbound or the port call fails.
        """
        try:
            task_lower = (task or "").lower()
            if _is_build_task(task_lower):
                plan = _decompose_build_task(task)
            elif _is_code_generation_task(task_lower):
                plan = _decompose_code_generation(task)
            elif _is_regex_or_pattern_task(task_lower):
                plan = _decompose_regex_task(task)
            elif _is_download_build_task(task_lower):
                plan = _decompose_download_build(task)
            else:
                plan = _decompose_generic(task)
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.decomposer: decomposition failed; producing minimal plan"
            )
            plan = _decompose_generic(task)

        self._buffer.append(plan)

        eff_conf = (
            float(confidence)
            if confidence is not None
            else TEKTOS_DECOMPOSER_DEFAULT_CONFIDENCE
        )

        narrative_id: str | None = None
        if self._relational_memory is not None:
            try:
                narrative_id = await self._relational_memory.write_narrative(
                    session_id=session_id,
                    agent_id=TEKTOS_DECOMPOSER_PROVENANCE,
                    title=f"{TEKTOS_DECOMPOSER_PREDICATE}:{plan.id}",
                    body=json.dumps(_plan_to_body(plan), default=str),
                    tags=(TEKTOS_DECOMPOSER_PROVENANCE, plan.phase, session_id),
                    embedding=None,
                    confidence=eff_conf,
                    provenance=TEKTOS_DECOMPOSER_PROVENANCE,
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.decomposer: write_narrative failed; kept in memory-only "
                    "buffer (ADR-106 D9 fail-open)"
                )
                narrative_id = None

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    EventEnvelope(
                        event_type=TEKTOS_DECOMPOSER_PREDICATE,
                        producer_plugin=TEKTOS_DECOMPOSER_PROVENANCE,
                        payload={
                            "session_id": session_id,
                            "plan_id": plan.id,
                            "sub_task_count": len(plan.sub_tasks),
                            "narrative_id": narrative_id,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.decomposer: EventBus publish failed; continuing (fail-open)"
                )

        return plan, narrative_id

    def list_recent(self, limit: int = 10) -> tuple[DecompositionPlan, ...]:
        if limit <= 0:
            return ()
        return tuple(list(self._buffer)[-limit:])

    @staticmethod
    def format_for_prompt(plan: DecompositionPlan) -> str:
        """Format the plan for system-prompt injection.

        Verbatim port of donor ``format_for_prompt`` — same heading, same
        research-warning heuristics, same rules block.
        """
        lines: list[str] = [
            "## TASK DECOMPOSITION — FOLLOW THESE STEPS IN ORDER",
            "",
            f"Original task: {plan.original_task}",
            "",
            "You MUST complete each step before moving to the next. After completing "
            "each step,",
            "verify the expected output exists before proceeding.",
            "",
            "⚠️  CRITICAL: You may call web_search AT MOST ONCE across ALL steps.",
            "After that single search, you MUST write code. No more searching.",
            "",
        ]

        for i, sub_task in enumerate(plan.sub_tasks, 1):
            tools = (
                ", ".join(sub_task.tools_needed)
                if sub_task.tools_needed
                else "bash, file_write"
            )
            lines.append(f"### Step {i}: {sub_task.description}")
            lines.append(f"- Expected output: {sub_task.expected_output}")
            lines.append(f"- Recommended tools: {tools}")
            lines.append(
                "- DO NOT skip this step. DO NOT proceed to the next step until this "
                "one is complete."
            )
            if i == 1 and any(t in tools for t in ("web_search", "web_extract")):
                lines.append(
                    "- ⚠️  THIS IS YOUR ONLY RESEARCH STEP. Search ONCE, then move to "
                    "Step 2 immediately."
                )
                lines.append(
                    "- ⚠️  DO NOT call web_search again after this step. DO NOT go "
                    "back to research."
                )
            lines.append("")

        lines.append("## IMPORTANT RULES")
        lines.append("- Write files IMMEDIATELY after researching — don't keep searching.")
        lines.append("- After each step, verify the expected output exists before proceeding.")
        lines.append("- If a step fails, fix the issue and retry — don't skip it.")
        lines.append("- The FINAL deliverable is the output file specified in the task.")
        lines.append("- Make sure the output file exists at the EXACT path specified.")
        lines.append("- RESEARCH LIMIT: Max 1 web_search call total. After that, WRITE CODE.")
        lines.append("- It is better to write imperfect code than to research forever.")

        return "\n".join(lines)


__all__ = ["TaskDecomposer"]
