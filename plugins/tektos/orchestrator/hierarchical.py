"""plugins.tektos.orchestrator.hierarchical — Tektos hierarchical agent.

Rewrite of donor ``tektos-ultima/src/tektos/runtime/hierarchical_agent.py``
(347 lines) per ADR-114 D2. What is preserved verbatim from the donor:

* Six-role roster (architect / planner / coder / reviewer / tester /
  deployer) and the dependency-gated batch execution loop
  (``_run_batched``: pending tasks whose dependencies are all complete
  run concurrently via ``asyncio.gather`` — the donor's real concurrency).
* Role handler *structure*: each role is a separate handler producing a
  markdown document (donor ``to_markdown`` shape preserved in
  ``AgentResult.to_markdown``).

What changes (ADR-114 D2):

* Donor role handlers were LLM stubs returning the literal template
  string ``f"<Role> design/plan/implementation for: {description}"``.
  The rewrite calls ``LLMPort.chat`` when a port is bound; when unwired,
  the **donor template string is the verbatim deterministic fallback**
  (so offline behaviour is bit-identical to the donor).
* The donor's module-level ``_agents`` singleton is rejected (R4);
  state lives on the instance, one engine per kernel registry slot.
* Every completed role task publishes ``tektos.hierarchical.role_completed``
  (fail-open) and appends to the ring buffer.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Any, Protocol

from ports.event_envelope import EventEnvelope

from . import (
    TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE,
    TEKTOS_ORCHESTRATOR_EVENT_ROLE,
    TEKTOS_ORCHESTRATOR_PROVENANCE,
)
from .models import AgentResult, AgentTask, HierRole

log = logging.getLogger(__name__)

_ROLES: tuple[HierRole, ...] = (
    "architect",
    "planner",
    "coder",
    "reviewer",
    "tester",
    "deployer",
)

# Donor template strings (verbatim fallback when LLMPort is unwired).
_ROLE_TEMPLATES: dict[HierRole, str] = {
    "architect": "Architecture design for: {description}",
    "planner": "Implementation plan for: {description}",
    "coder": "Implementation for: {description}",
    "reviewer": "Review findings for: {description}",
    "tester": "Test plan for: {description}",
    "deployer": "Deployment plan for: {description}",
}


class _LLMLike(Protocol):
    """Structural type for the LLMPort surface used here (D2)."""

    async def chat(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]: ...


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


def _extract_text(response: dict[str, Any]) -> str:
    """Best-effort text extraction from an LLMPort chat response."""
    if not isinstance(response, dict):
        return str(response)
    for key in ("response", "content", "text", "output"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return str(response)


class TektosHierarchicalAgent:
    """Hierarchical multi-role execution engine (donor ``HierarchicalAgent``)."""

    def __init__(
        self,
        *,
        llm: _LLMLike | None = None,
        event_bus: _EventBusLike | None = None,
        max_records: int = 100,
        max_concurrency: int = 4,
    ) -> None:
        self._llm = llm
        self._event_bus = event_bus
        self._buffer: deque[AgentResult] = deque(maxlen=max_records)
        self._tasks: dict[str, AgentTask] = {}
        self._max_concurrency = max_concurrency
        self.results: list[AgentResult] = []

    @property
    def roles(self) -> tuple[HierRole, ...]:
        return _ROLES

    def create_task(
        self,
        role: HierRole,
        description: str,
        dependencies: tuple[str, ...] = (),
        context: dict[str, Any] | None = None,
    ) -> str:
        """Create an agent task (donor ``create_task``)."""
        task_id = f"hier_{len(self._tasks) + 1}"
        self._tasks[task_id] = AgentTask(
            task_id=task_id,
            role=role,
            description=description,
            context=dict(context or {}),
            dependencies=tuple(dependencies),
        )
        return task_id

    async def execute_task(self, task_id: str) -> AgentResult:
        """Execute one role task (donor handler dispatch, async)."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        if task.status == "completed":
            return AgentResult(
                task_id=task_id,
                role=task.role,
                success=True,
                output=task.result or "",
                metadata={"cached": True},
            )
        if task.status == "failed":
            return AgentResult(
                task_id=task_id,
                role=task.role,
                success=False,
                output="",
                error=task.error or "Previously failed",
            )

        task.status = "running"
        task.started_at = time.time()
        try:
            output = await self._run_role(task)
            task.status = "completed"
            task.result = output
            task.completed_at = time.time()
            result = AgentResult(
                task_id=task_id,
                role=task.role,
                success=True,
                output=output,
                metadata={"duration_seconds": round(task.duration, 3)},
            )
        except Exception as e:  # noqa: BLE001
            task.status = "failed"
            task.error = str(e)
            task.completed_at = time.time()
            result = AgentResult(
                task_id=task_id,
                role=task.role,
                success=False,
                output="",
                error=str(e),
            )

        self._buffer.append(result)
        self.results.append(result)
        await self._publish_role(task, result)
        return result

    async def _run_role(self, task: AgentTask) -> str:
        """Dispatch a role task to its handler (donor table, async)."""
        if self._llm is not None:
            try:
                response = await self._llm.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                f"You are the {task.role} agent in a hierarchical "
                                f"software team. Produce the {task.role} artifact "
                                f"for the assigned task."
                            ),
                        },
                        {"role": "user", "content": task.description},
                    ]
                )
                text = _extract_text(response).strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001 — LLM failure → deterministic fallback
                log.exception(
                    "tektos.orchestrator: LLM role handler failed; "
                    "using deterministic fallback"
                )
        return _ROLE_TEMPLATES[task.role].format(description=task.description)

    async def execute_plan(self, task_ids: list[str]) -> list[AgentResult]:
        """Dependency-gated batched execution (donor ``_run_batched``).

        Tasks whose dependencies are all completed run concurrently
        (real ``asyncio.gather`` under a semaphore); the loop repeats
        until every task is terminal.
        """
        pending = set(task_ids)
        unknown = pending - set(self._tasks)
        if unknown:
            raise KeyError(f"Unknown tasks: {sorted(unknown)}")
        semaphore = asyncio.Semaphore(self._max_concurrency)
        outcomes: dict[str, AgentResult] = {}

        async def _guarded(task_id: str) -> tuple[str, AgentResult]:
            async with semaphore:
                return task_id, await self.execute_task(task_id)

        while pending:
            ready = [
                tid
                for tid in pending
                if all(dep in outcomes for dep in self._tasks[tid].dependencies)
            ]
            if not ready:
                # Dependency cycle or unmet external deps — fail the rest.
                for tid in pending:
                    self._tasks[tid].status = "failed"
                    self._tasks[tid].error = "Dependencies unresolvable"
                    outcomes[tid] = AgentResult(
                        task_id=tid,
                        role=self._tasks[tid].role,
                        success=False,
                        output="",
                        error="Dependencies unresolvable",
                    )
                pending.clear()
                break
            results = await asyncio.gather(*(_guarded(tid) for tid in ready))
            for tid, result in results:
                outcomes[tid] = result
            pending -= set(ready)

        return [outcomes[tid] for tid in task_ids if tid in outcomes]

    def get_status(self, task_id: str) -> dict[str, Any]:
        """Task status snapshot (donor ``get_status`` shape)."""
        task = self._tasks.get(task_id)
        if task is None:
            return {"task_id": task_id, "status": "unknown"}
        return {
            "task_id": task_id,
            "role": task.role,
            "description": task.description,
            "status": task.status,
            "dependencies": list(task.dependencies),
            "error": task.error,
            "duration_seconds": round(task.duration, 3),
        }

    @property
    def recent(self) -> list[AgentResult]:
        return list(self._buffer)

    async def _publish_role(self, task: AgentTask, result: AgentResult) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(
                EventEnvelope(
                    event_type=TEKTOS_ORCHESTRATOR_EVENT_ROLE,
                    producer_plugin=TEKTOS_ORCHESTRATOR_PROVENANCE,
                    payload={
                        "task_id": task.task_id,
                        "role": task.role,
                        "success": result.success,
                        "result_id": result.id,
                        "output_chars": len(result.output),
                    },
                )
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.orchestrator: EventBus publish role_completed failed (fail-open)"
            )


__all__ = ["TektosHierarchicalAgent"]
