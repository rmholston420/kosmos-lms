"""FastAPI router factory for the Tektos Orchestrator (Stage 8.7 · ADR-114 D8).

Single factory :func:`build_orchestrator_router` returning an ``APIRouter``
with ``tags=["tektos.orchestrator"]`` and no internal prefix. Mount-time
prefix per the Stage 8.3/8.5/8.6 pattern (kernel wiring mounts under
``/tektos/api/orchestrator``).

When the engine family is unwired, every route returns
``503 {"detail": "ADR-114 degrade: orchestrator not wired", "adr": "ADR-114"}``
(ADR-101 degrade shape).
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import OrchestratorBundle
from .hierarchical import TektosHierarchicalAgent
from .long_running import TektosLongRunningAgent


# ── Request bodies ─────────────────────────────────────────────────────────


class _TaskCreateRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4096)
    priority: int = Field(default=0, ge=0)
    dependencies: list[str] = Field(default_factory=list)


class _TaskAssignRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=64)


class _ParallelRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=50)


class _HierTaskRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=4096)
    dependencies: list[str] = Field(default_factory=list)


class _PlanRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=50)


class _CheckpointRequest(BaseModel):
    session_id: str = Field(default="", max_length=256)
    next_action: str = Field(default="", max_length=1024)


# ── Serialisation helpers ──────────────────────────────────────────────────


def _batch_to_dict(batch: Any) -> dict[str, Any]:
    return {
        "id": batch.id,
        "tasks_completed": batch.tasks_completed,
        "tasks_failed": batch.tasks_failed,
        "total_duration_seconds": batch.total_duration_seconds,
        "agent_utilization": batch.agent_utilization,
        "errors": list(batch.errors),
        "when": batch.when,
    }


def _result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "role": result.role,
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "id": result.id,
        "when": result.when,
    }


def _checkpoint_to_dict(ckpt: Any) -> dict[str, Any]:
    d = ckpt.to_dict()
    d["event_id"] = ckpt.event_id
    return d


# ── Router factory ─────────────────────────────────────────────────────────


def build_orchestrator_router(
    bundle: OrchestratorBundle | None,
    *,
    hierarchical: TektosHierarchicalAgent | None = None,
    long_running: TektosLongRunningAgent | None = None,
    coding: Any | None = None,
) -> APIRouter:
    """Build the orchestrator router (ADR-114 D8).

    ``bundle`` is the orchestrator engine family bundle (may be ``None``
    when the kernel gate is off); the sibling singletons may also be
    ``None`` when only the orchestrator sub-engine is wired. ``coding``
    is the ADR-107 spec-executor (donor coding-agent referent; ADR-141
    T1) — consumed only by the donor-fidelity ``/status`` + ``/agents``
    routes.
    """
    router = APIRouter(tags=["tektos.orchestrator"])

    def _degrade(name: str) -> NoReturn:
        raise HTTPException(
            status_code=503,
            detail={"detail": f"ADR-114 degrade: {name} not wired", "adr": "ADR-114"},
        )

    def _guard_bundle() -> OrchestratorBundle:
        if bundle is None:
            _degrade("orchestrator")
        return bundle

    def _guard_hier() -> TektosHierarchicalAgent:
        if hierarchical is None:
            _degrade("hierarchical")
        return hierarchical

    def _guard_lr() -> TektosLongRunningAgent:
        if long_running is None:
            _degrade("long-running")
        return long_running

    # ── Orchestrator ───────────────────────────────────────────────────────

    @router.get("/status")
    async def status() -> dict[str, Any]:
        """Wiring report (ADR-141 T1 — donor-fidelity port of the donor's
        ``GET /api/multi-agent-orchestrator/status`` on :8020).

        Donor shape: ``{status, hierarchical_agent, long_running_agent,
        coding_executor}`` booleans. Kernel deviation (honest degrade): when
        NO engine family is wired the ``status`` field reports ``"unwired"``
        instead of the donor's unconditional ``"initialized"`` — a status
        endpoint must report reality, not 503 (the 503 degrade shape in this
        file applies to action endpoints). The kernel's coding referent is the
        ADR-107 spec-executor (``registry.tektos_executor``), which this
        router receives as the ``coding`` kwarg.
        """
        wired = [bundle is not None, hierarchical is not None, coding is not None]
        return {
            "status": "initialized" if any(wired) else "unwired",
            "hierarchical_agent": hierarchical is not None,
            "long_running_agent": long_running is not None,
            "coding_executor": coding is not None,
        }

    @router.get("/agents")
    async def agents() -> list[dict[str, Any]]:
        """Registered sub-agents with live state (ADR-141 T1 — donor-fidelity
        port of the donor's ``GET /api/multi-agent-orchestrator/agents``).

        Donor shape: list of ``{id, name, role, status, active_tasks}`` —
        display strings preserved verbatim for UI fidelity. ``active_tasks``
        reads the engine's active-task/sessions bookkeeping via defensive
        getattr (kernel engines do not expose ``_active_tasks``; falls back
        to 0 rather than fabricating a count). Only WIRED agents are listed
        (donor semantics — an agent that was never booted is not listed).
        """
        out: list[dict[str, Any]] = []
        if hierarchical is not None:
            out.append({
                "id": "hierarchical",
                "name": "Hierarchical Planner",
                "role": "planner",
                "status": "ready",
                "active_tasks": len(getattr(hierarchical, "_active_tasks", []) or []),
            })
        if long_running is not None:
            out.append({
                "id": "long_running",
                "name": "Long-Running Executor",
                "role": "executor",
                "status": "ready",
                "active_tasks": len(getattr(long_running, "_active_tasks", []) or []),
            })
        if coding is not None:
            out.append({
                "id": "coding",
                "name": "Coding Agent",
                "role": "executor",
                "status": "ready",
                "active_tasks": len(getattr(coding, "_active_sessions", []) or []),
            })
        return out

    @router.post("/tasks")
    async def create_task(body: _TaskCreateRequest) -> dict[str, Any]:
        eng = _guard_bundle()
        task_id = eng.orchestrator.create_task(
            body.description, priority=body.priority, dependencies=tuple(body.dependencies)
        )
        return {"task_id": task_id, "status": "pending"}

    @router.post("/tasks/{task_id}/assign")
    async def assign_task(task_id: str, body: _TaskAssignRequest) -> dict[str, Any]:
        eng = _guard_bundle()
        ok = eng.orchestrator.assign_task(task_id, body.agent_id)
        return {"task_id": task_id, "assigned": ok}

    @router.post("/tasks/{task_id}/execute")
    async def execute_task(task_id: str) -> dict[str, Any]:
        eng = _guard_bundle()
        return await eng.orchestrator.execute_task(task_id)

    @router.post("/parallel")
    async def execute_parallel(body: _ParallelRequest) -> dict[str, Any]:
        eng = _guard_bundle()
        batch = await eng.orchestrator.execute_parallel(body.task_ids)
        return _batch_to_dict(batch)

    @router.get("/stats")
    async def stats() -> dict[str, Any]:
        eng = _guard_bundle()
        s = eng.orchestrator.get_orchestration_stats()
        s["recent_batches"] = len(eng.orchestrator.recent)
        return s

    @router.get("/recent")
    async def recent() -> dict[str, Any]:
        eng = _guard_bundle()
        return {"batches": [_batch_to_dict(b) for b in eng.orchestrator.recent]}

    # ── Hierarchical ───────────────────────────────────────────────────────

    @router.post("/hierarchical/tasks")
    async def hier_create_task(body: _HierTaskRequest) -> dict[str, Any]:
        eng = _guard_hier()
        if body.role not in eng.roles:
            raise HTTPException(status_code=422, detail=f"unknown role: {body.role}")
        task_id = eng.create_task(
            body.role, body.description, dependencies=tuple(body.dependencies)
        )
        return {"task_id": task_id, "status": "pending"}

    @router.post("/hierarchical/plan")
    async def hier_execute_plan(body: _PlanRequest) -> dict[str, Any]:
        eng = _guard_hier()
        try:
            results = await eng.execute_plan(body.task_ids)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {
            "results": [_result_to_dict(r) for r in results],
            "succeeded": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
        }

    @router.get("/hierarchical/recent")
    async def hier_recent() -> dict[str, Any]:
        eng = _guard_hier()
        return {"results": [_result_to_dict(r) for r in eng.recent]}

    # ── Long-running ───────────────────────────────────────────────────────

    @router.get("/long-running/status")
    async def lr_status() -> dict[str, Any]:
        eng = _guard_lr()
        p = eng.progress
        return {
            "session_id": eng.session_id,
            "state": eng.state,
            "wired_memory": eng.wired,
            "checkpoint_count": eng.checkpoint_count,
            "heartbeat_count": eng.heartbeat_count,
            "progress_percent": round(p.progress_percent, 1),
            "current_step": p.current_step,
            "last_checkpoint": (
                _checkpoint_to_dict(eng.last_checkpoint) if eng.last_checkpoint else None
            ),
        }

    @router.post("/long-running/heartbeat")
    async def lr_heartbeat() -> dict[str, Any]:
        eng = _guard_lr()
        await eng.heartbeat()
        return {
            "heartbeat_count": eng.heartbeat_count,
            "wired_memory": eng.wired,
        }

    @router.post("/long-running/checkpoint")
    async def lr_checkpoint(body: _CheckpointRequest) -> dict[str, Any]:
        eng = _guard_lr()
        if body.session_id and body.session_id != eng.session_id:
            raise HTTPException(
                status_code=409,
                detail=f"session mismatch: engine={eng.session_id}",
            )
        ckpt = await eng._create_checkpoint(next_action=body.next_action or None)
        return {"checkpoint": _checkpoint_to_dict(ckpt) if ckpt else None}

    return router


__all__ = ["build_orchestrator_router"]
