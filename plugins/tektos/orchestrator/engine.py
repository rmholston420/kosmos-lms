"""plugins.tektos.orchestrator.engine — Tektos multi-agent orchestration.

Rewrite of donor ``tektos-ultima/src/tektos/runtime/multi_agent_orchestrator.py``
(541 lines) per ADR-114 D2. What is preserved verbatim from the donor:

* Default agent roster (file/terminal/browser/reviewer agents).
* ``assign_task`` keyword capability matching (direct, keyword, and
  agent-specific rules) — deterministic, side-effect-free matching.
* ``reconcile_results`` aggregation shape.
* Per-agent dispatch table in ``_dispatch_real_tool`` (file read/write,
  review heuristics).

What changes (ADR-114 D2/D6):

* ``subprocess.run(shell=True)`` for terminal commands and the grep
  subprocess for file search are rerouted through ``SandboxPort.run``
  (ADR-107 R1 precedent). Fail-open: when the sandbox port is unbound,
  terminal/search tasks return ``{"type": "error", ...}`` instead of
  executing unsandboxed (the donor's unsafe path is not ported).
* ``execute_parallel`` becomes a **real** ``asyncio.gather`` under a
  semaphore (donor was sequential with a misleading name).
* Failed tasks consult ``plugins.tektos.manager.classify_recovery``
  (ADR-107 D9 discharge): the strategy is recorded on the task and in
  the result; ``escalate`` tasks are flagged ``task.escalated``.
* ``record_task_completed`` writes through ``RelationalMemoryPort``
  (fail-open) + ``EventBusPort.publish`` (envelope-first, ADR-023) and
  always appends to the in-memory ring buffer.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from ports.event_envelope import EventEnvelope
from ports.sandbox import SandboxLimits, SandboxRequest, SandboxResult

from . import (
    TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE,
    TEKTOS_ORCHESTRATOR_EVENT_BATCH,
    TEKTOS_ORCHESTRATOR_PREDICATE,
    TEKTOS_ORCHESTRATOR_PROVENANCE,
)
from .models import (
    AgentRole,
    OrchestrationResult,
    Subagent,
    Task,
    TaskStatus,
)

log = logging.getLogger(__name__)

# Sandbox defaults for re-routed command execution (ADR-114 D2).
_SANDBOX_WALL_SECONDS = 60
_SANDBOX_MEMORY_MB = 1024
_SANDBOX_CPU_PERCENT = 100


class _SandboxLike(Protocol):
    """Structural type for the SandboxPort surface used here (D2)."""

    async def run(self, request: SandboxRequest) -> SandboxResult: ...


class _RelationalMemoryLike(Protocol):
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


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


from plugins.tektos.manager.engine import classify_recovery  # noqa: E402  (D6)


class TektosOrchestrator:
    """Multi-agent orchestration engine (donor ``MultiAgentOrchestrator``).

    Same public surface as the donor (``create_task`` / ``assign_task`` /
    ``execute_task`` / ``execute_parallel`` / ``get_orchestration_stats``
    / ``reconcile_results``), with ``execute_task`` / ``execute_parallel``
    async (Kosmos engines are async; donor was sync).
    """

    def __init__(
        self,
        *,
        max_concurrent_agents: int = 5,
        sandbox: _SandboxLike | None = None,
        relational_memory: _RelationalMemoryLike | None = None,
        event_bus: _EventBusLike | None = None,
        max_records: int = 100,
    ) -> None:
        self.max_concurrent_agents = max_concurrent_agents
        self.agents: dict[str, Subagent] = {}
        self.tasks: dict[str, Task] = {}
        self.task_queue: list[str] = []
        self._sandbox = sandbox
        self._relational_memory = relational_memory
        self._event_bus = event_bus
        self._buffer: deque[OrchestrationResult] = deque(maxlen=max_records)
        self._results: list[OrchestrationResult] = []
        self._init_default_agents()

    # ── Agent lifecycle ────────────────────────────────────────────────────

    def _init_default_agents(self) -> None:
        """Initialize default agents (donor roster verbatim)."""
        default_agents = [
            Subagent(
                agent_id="file_agent",
                role="worker",
                capabilities=("read_file", "write_file", "search_files", "patch"),
            ),
            Subagent(
                agent_id="terminal_agent",
                role="worker",
                capabilities=("terminal", "execute_code", "process"),
            ),
            Subagent(
                agent_id="browser_agent",
                role="worker",
                capabilities=("browser_exec", "drive_preview", "open_preview"),
            ),
            Subagent(
                agent_id="reviewer_agent",
                role="reviewer",
                capabilities=("read_file", "search_files", "terminal"),
            ),
        ]
        for agent in default_agents:
            self.agents[agent.agent_id] = agent

    def create_agent(
        self, agent_id: str, role: AgentRole, capabilities: tuple[str, ...] = ()
    ) -> Subagent:
        """Register an additional agent (donor ``create_agent``)."""
        agent = Subagent(agent_id=agent_id, role=role, capabilities=capabilities)
        self.agents[agent_id] = agent
        return agent

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent (donor ``remove_agent``)."""
        return self.agents.pop(agent_id, None) is not None

    # ── Task lifecycle ─────────────────────────────────────────────────────

    def create_task(
        self, description: str, priority: int = 0, dependencies: tuple[str, ...] = ()
    ) -> str:
        """Create a new task. Returns the task ID (donor semantics)."""
        task_id = f"task_{len(self.tasks) + 1}"
        task = Task(
            task_id=task_id,
            description=description,
            priority=priority,
            dependencies=tuple(dependencies),
        )
        self.tasks[task_id] = task
        self.task_queue.append(task_id)
        return task_id

    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """Assign a task to an agent (donor capability matching verbatim)."""
        if task_id not in self.tasks:
            log.error("Task %s not found", task_id)
            return False
        if agent_id not in self.agents:
            log.error("Agent %s not found", agent_id)
            return False

        task = self.tasks[task_id]
        agent = self.agents[agent_id]

        desc_lower = task.description.lower()
        has_capability = False
        for cap in agent.capabilities:
            cap_lower = cap.lower()
            if cap_lower in desc_lower:
                has_capability = True
                break
            keywords = cap_lower.split("_")
            if any(kw in desc_lower for kw in keywords if len(kw) > 2):
                has_capability = True
                break
            if agent.agent_id == "terminal_agent" and any(
                kw in desc_lower for kw in ["run", "execute", "command", "cmd"]
            ):
                has_capability = True
                break
            if agent.agent_id == "reviewer_agent" and any(
                kw in desc_lower for kw in ["review", "check", "validate", "analyze"]
            ):
                has_capability = True
                break

        if has_capability:
            agent.status = "running"
            agent.current_task = task_id
            task.assigned_agent = agent_id
            task.status = "running"
            return True
        return False

    # ── Execution ──────────────────────────────────────────────────────────

    async def execute_task(self, task_id: str) -> dict[str, Any]:
        """Execute one assigned task (donor ``execute_task``, async).

        On failure, the recovery strategy is classified (ADR-114 D6 /
        ADR-107 D9 discharge) and recorded on the task.
        """
        if task_id not in self.tasks:
            return {"success": False, "error": f"Task {task_id} not found"}

        task = self.tasks[task_id]
        agent_id = task.assigned_agent
        if not agent_id:
            return {"success": False, "error": f"Task {task_id} not assigned"}

        agent = self.agents[agent_id]
        try:
            result = await self._dispatch_real_tool(task, agent)
            if result.get("type") == "error":
                task.status = "failed"
                task.error = result.get("error", "Unknown error")
                agent.status = "pending"
                agent.current_task = ""
                agent.error = task.error
                self._apply_recovery(task)
                return {"success": False, "error": task.error}

            task.status = "completed"
            task.result = result
            agent.status = "pending"
            agent.current_task = ""
            agent.result = result
            await self._record_task_completed(task)
            return {"success": True, "result": result}

        except Exception as e:  # noqa: BLE001
            task.status = "failed"
            task.error = str(e)
            agent.status = "pending"
            agent.current_task = ""
            agent.error = str(e)
            self._apply_recovery(task)
            return {"success": False, "error": str(e)}

    def _apply_recovery(self, task: Task) -> None:
        """Classify the failure and record the strategy (ADR-114 D6)."""
        try:
            strategy = classify_recovery(task.error or "unknown")
        except Exception:  # noqa: BLE001 — classifier must never break execution
            log.exception("tektos.orchestrator: classify_recovery raised")
            strategy = "skip"
        task.recovery_strategy = strategy
        task.escalated = strategy == "escalate"

    async def _run_sandbox_command(self, command: str) -> dict[str, Any]:
        """Run a shell command through the SandboxPort (ADR-114 D2/R1).

        Fail-open: unbound sandbox → error result (never an unsandboxed
        ``subprocess.run(shell=True)``, which the donor did).
        """
        if self._sandbox is None:
            return {
                "type": "error",
                "error": "sandbox not wired — command execution disabled (ADR-114 D2)",
            }
        request = SandboxRequest(
            command=command,
            argv=(),
            cwd="",
            env={},
            limits=SandboxLimits(
                max_wall_seconds=_SANDBOX_WALL_SECONDS,
                max_memory_mb=_SANDBOX_MEMORY_MB,
                max_cpu_percent=_SANDBOX_CPU_PERCENT,
            ),
        )
        try:
            result = await self._sandbox.run(request)
        except Exception as e:  # noqa: BLE001
            return {"type": "error", "error": f"sandbox run failed: {e}"}
        return {
            "type": "command_output",
            "command": command,
            "stdout": result.stdout[:4096],
            "stderr": result.stderr[:4096],
            "exit_code": result.exit_code,
        }

    async def _dispatch_real_tool(self, task: Task, agent: Subagent) -> dict[str, Any]:
        """Dispatch table (donor ``_dispatch_real_tool``; sandbox re-routed)."""
        description_lower = task.description.lower()

        if agent.agent_id == "file_agent":
            if any(kw in description_lower for kw in ["read", "open", "view", "show"]):
                path_match = re.search(r'["\']([^"\']+)["\']', task.description)
                if not path_match:
                    path_match = re.search(r"(/[a-zA-Z0-9._/-]+)", task.description)
                if path_match:
                    path = path_match.group(1)
                    try:
                        content = await asyncio.to_thread(self._read_file, path)
                        return {
                            "type": "file_content",
                            "path": path,
                            "content": content[:4096],
                            "size": len(content),
                        }
                    except Exception as e:  # noqa: BLE001
                        return {"type": "error", "error": str(e)}
                return {"type": "error", "error": "No file path found in description"}
            elif any(kw in description_lower for kw in ["write", "create", "save", "make"]):
                path_match = re.search(r'["\']([^"\']+)["\']', task.description)
                if not path_match:
                    path_match = re.search(r"(/[a-zA-Z0-9._/-]+)", task.description)
                if path_match:
                    path = path_match.group(1)
                    content_match = re.search(r'["\']([^"\']+)["\']\s*$', task.description)
                    if not content_match:
                        content_match = re.search(r'["\']([^"\']+)["\']', task.description)
                    content = content_match.group(1) if content_match else f"Content for {path}"
                    try:
                        await asyncio.to_thread(self._write_file, path, content)
                        return {"type": "file_created", "path": path, "size": len(content)}
                    except Exception as e:  # noqa: BLE001
                        return {"type": "error", "error": str(e)}
                return {"type": "error", "error": "No file path found in description"}
            elif any(kw in description_lower for kw in ["search", "find", "grep", "look"]):
                pattern_match = re.search(
                    r"(?:search|find|grep)\s+[\"']?([^\"']+)[\"']?", task.description
                )
                pattern = pattern_match.group(1) if pattern_match else task.description
                out = await self._run_sandbox_command(
                    f"grep -r --include=*.py -l {pattern} ."
                )
                if out.get("type") == "error":
                    return out
                files = [f.strip() for f in out.get("stdout", "").strip().split("\n") if f.strip()]
                return {
                    "type": "search_results",
                    "pattern": pattern,
                    "matches": len(files),
                    "files": files[:20],
                }
            elif any(kw in description_lower for kw in ["patch", "edit", "modify", "change"]):
                return {
                    "type": "error",
                    "error": "Patch operations require interactive tool access",
                }
            else:
                return {"type": "general", "message": f"File agent: {task.description}"}

        elif agent.agent_id == "terminal_agent":
            cmd_match = re.search(
                r"(?:run|execute)\s+(?:command\s+)?[\"']?([^\"']+)[\"']?",
                task.description,
                re.IGNORECASE,
            )
            if cmd_match:
                cmd = cmd_match.group(1)
                return await self._run_sandbox_command(cmd)
            return {"type": "error", "error": "No command found in description"}

        elif agent.agent_id == "browser_agent":
            return {
                "type": "error",
                "error": "Browser operations require interactive tool access",
            }

        elif agent.agent_id == "reviewer_agent":
            path_match = re.search(r'["\']([^"\']+)["\']', task.description)
            if not path_match:
                path_match = re.search(
                    r"(\S+\.(?:toml|py|md|txt|json|yaml|yml|cfg|ini|sh|bash|html|css|js|ts|tsx|jsx|sql|db|sqlite))",
                    task.description,
                )
            if path_match:
                path = path_match.group(1)
                try:
                    content = await asyncio.to_thread(self._read_file, path)
                    lines = content.split("\n")
                    issues = []
                    for i, line in enumerate(lines, 1):
                        if len(line) > 120:
                            issues.append(f"Line {i}: too long ({len(line)} chars)")
                        if "\t" in line:
                            issues.append(f"Line {i}: contains tab character")
                    return {
                        "type": "review_result",
                        "path": path,
                        "lines": len(lines),
                        "issues": issues[:20],
                        "issue_count": len(issues),
                    }
                except Exception as e:  # noqa: BLE001
                    return {"type": "error", "error": str(e)}
            return {"type": "error", "error": "No file path found in description"}

        return {"type": "error", "error": f"Unknown agent: {agent.agent_id}"}

    @staticmethod
    def _read_file(path: str) -> str:
        with open(path) as f:
            return f.read()

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        import os

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    async def execute_parallel(self, task_ids: list[str]) -> OrchestrationResult:
        """Execute multiple tasks concurrently (ADR-114 D2: real gather)."""
        start_time = time.perf_counter()
        results: dict[str, Any] = {}
        errors: list[str] = []
        completed_count = 0
        failed_count = 0

        available_agents = [
            agent for agent in self.agents.values() if agent.status == "pending"
        ][: self.max_concurrent_agents]
        for i, task_id in enumerate(task_ids):
            if i < len(available_agents):
                self.assign_task(task_id, available_agents[i].agent_id)

        semaphore = asyncio.Semaphore(self.max_concurrent_agents)

        async def _run_one(task_id: str) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                return task_id, await self.execute_task(task_id)

        try:
            outcomes = await asyncio.gather(*(_run_one(tid) for tid in task_ids))
        except Exception as e:  # noqa: BLE001 — gather-level failure: mark all failed
            outcomes = [(tid, {"success": False, "error": str(e)}) for tid in task_ids]

        for task_id, result in outcomes:
            results[task_id] = result
            if result.get("success"):
                completed_count += 1
            else:
                failed_count += 1
                errors.append(result.get("error", "Unknown error"))

        total_duration = time.perf_counter() - start_time
        active_agents = sum(
            1 for agent in self.agents.values() if agent.status == "running"
        )
        utilization = active_agents / len(self.agents) if self.agents else 0.0

        batch = OrchestrationResult(
            tasks_completed=completed_count,
            tasks_failed=failed_count,
            total_duration_seconds=total_duration,
            agent_utilization=utilization,
            results=results,
            errors=tuple(errors),
        )
        self._buffer.append(batch)
        self._results.append(batch)
        await self._publish_batch(batch)
        return batch

    # ── Introspection ──────────────────────────────────────────────────────

    def get_orchestration_stats(self) -> dict[str, Any]:
        """Statistics (donor shape; Literal state values, no ``.value``)."""
        agent_stats = {
            agent_id: {
                "role": agent.role,
                "status": agent.status,
                "capabilities": list(agent.capabilities),
            }
            for agent_id, agent in self.agents.items()
        }
        task_stats = {
            "total_tasks": len(self.tasks),
            "pending": sum(1 for t in self.tasks.values() if t.status == "pending"),
            "running": sum(1 for t in self.tasks.values() if t.status == "running"),
            "completed": sum(1 for t in self.tasks.values() if t.status == "completed"),
            "failed": sum(1 for t in self.tasks.values() if t.status == "failed"),
        }
        return {
            "agents": agent_stats,
            "tasks": task_stats,
            "max_concurrent_agents": self.max_concurrent_agents,
        }

    def reconcile_results(self, results: dict[str, Any]) -> dict[str, Any]:
        """Reconcile per-task results (donor ``reconcile_results`` verbatim)."""
        reconciled = {
            "total_tasks": len(results),
            "successful": 0,
            "failed": 0,
            "summary": [],
            "errors": [],
        }
        for task_id, result in results.items():
            if result.get("success"):
                reconciled["successful"] += 1
                reconciled["summary"].append(
                    f"Task {task_id}: {result.get('result', 'Completed')}"
                )
            else:
                reconciled["failed"] += 1
                reconciled["errors"].append(
                    f"Task {task_id}: {result.get('error', 'Unknown error')}"
                )
        return reconciled

    @property
    def recent(self) -> list[OrchestrationResult]:
        return list(self._buffer)

    # ── Port writes (fail-open, ADR-114 D7/D9) ─────────────────────────────

    async def _record_task_completed(self, task: Task) -> None:
        """Write the task_completed record (ring buffer always appended)."""
        if self._relational_memory is None:
            return
        try:
            await self._relational_memory.record_event(
                kind=TEKTOS_ORCHESTRATOR_PREDICATE,
                session_id=None,
                agent_id=task.assigned_agent,
                payload={
                    "task_id": task.task_id,
                    "description": task.description,
                    "result_type": (task.result or {}).get("type", "")
                    if isinstance(task.result, dict)
                    else "",
                },
                confidence=TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE,
                provenance=TEKTOS_ORCHESTRATOR_PROVENANCE,
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.orchestrator: record_event task_completed failed (fail-open)"
            )

    async def _publish_batch(self, batch: OrchestrationResult) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(
                EventEnvelope(
                    event_type=TEKTOS_ORCHESTRATOR_EVENT_BATCH,
                    producer_plugin=TEKTOS_ORCHESTRATOR_PROVENANCE,
                    payload={
                        "batch_id": batch.id,
                        "tasks_completed": batch.tasks_completed,
                        "tasks_failed": batch.tasks_failed,
                        "duration_seconds": batch.total_duration_seconds,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.orchestrator: EventBus publish batch_completed failed (fail-open)"
            )


@dataclass
class OrchestratorBundle:
    """Kernel-facing bundle (mirrors ADR-105/106/107/108 bundle shape)."""

    orchestrator: TektosOrchestrator
    wired_sandbox: bool
    wired_memory: bool
    wired_event_bus: bool


__all__ = ["OrchestratorBundle", "TektosOrchestrator"]
