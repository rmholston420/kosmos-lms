"""FastAPI router factories for the Tektos executor + tool-router (ADR-107 D8).

Two factories:

* :func:`build_spec_executor_router` — mounts under ``/tektos/api/executor``.
* :func:`build_tool_router_router` — mounts under ``/tektos/api/tool-router``.

When the corresponding engine is unwired, every route returns
``503 {"detail": "ADR-107 degrade: <engine> not wired", "adr": "ADR-107"}``.

Routers use ``APIRouter(tags=[...])`` with NO internal prefix; mount-time
prefix per Stage 8.3 pattern.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import TektosSpecExecutor, TektosToolRouter


# ── Spec Executor router ───────────────────────────────────────────────────


class _SpecPhaseRequest(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2048)
    deliverables: list[str] = Field(default_factory=list, max_length=64)


class _BuildSpecRequest(BaseModel):
    """Minimal BuildSpec shape accepted by the executor router.

    Matches ``plugins.tektos.planner.spec_models.BuildSpec`` structurally
    (see ADR-107 engine protocol) — kept minimal at 8.5 to keep the router
    free of a hard dependency on the planner package.
    """

    id: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4096)
    phases: list[_SpecPhaseRequest] = Field(default_factory=list, max_length=32)
    tech_stack: list[str] = Field(default_factory=list, max_length=64)


class _ExecuteRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    spec: _BuildSpecRequest
    agent_id: str | None = Field(default=None, max_length=256)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class _StructuralSpec:
    """Tiny bag with the ``_BuildSpecLike`` attributes the engine reads."""

    __slots__ = ("id", "description", "phases", "tech_stack")

    def __init__(self, req: _BuildSpecRequest) -> None:
        self.id = req.id
        self.description = req.description
        self.phases = tuple(_StructuralPhase(p) for p in req.phases)
        self.tech_stack = tuple(req.tech_stack)


class _StructuralPhase:
    __slots__ = ("id", "description", "deliverables")

    def __init__(self, req: _SpecPhaseRequest) -> None:
        self.id = req.id
        self.description = req.description
        self.deliverables = tuple(req.deliverables)


def build_spec_executor_router(engine: TektosSpecExecutor | None) -> APIRouter:
    router = APIRouter(tags=["tektos.executor"])

    def _guard() -> TektosSpecExecutor:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-107 degrade: executor not wired",
                    "adr": "ADR-107",
                },
            )
        return engine

    @router.post("/execute")
    async def execute(request: _ExecuteRequest) -> dict[str, Any]:
        eng = _guard()
        spec = _StructuralSpec(request.spec)
        record, narrative_id = await eng.execute_spec(
            session_id=request.session_id,
            spec=spec,
            agent_id=request.agent_id,
            confidence=request.confidence,
        )
        return {
            "execution_id": record.id,
            "spec_id": record.spec_id,
            "status": record.status,
            "narrative_id": narrative_id,
            "artifact_count": len(record.artifacts),
            "step_count": len(record.steps),
            "test_pass_count": sum(
                1 for t in record.test_results if t.status == "passed"
            ),
            "test_fail_count": sum(
                1 for t in record.test_results if t.status == "failed"
            ),
            "total_duration_seconds": record.total_duration_seconds,
            "error_summary": record.error_summary,
        }

    @router.get("/recent")
    async def recent(limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        items = eng.list_recent(limit=limit)
        return {
            "count": len(items),
            "items": [
                {
                    "execution_id": r.id,
                    "spec_id": r.spec_id,
                    "status": r.status,
                    "artifact_count": len(r.artifacts),
                    "step_count": len(r.steps),
                    "started_at": r.started_at,
                    "completed_at": r.completed_at,
                }
                for r in items
            ],
        }

    return router


# ── Tool Router router ─────────────────────────────────────────────────────


class _RouteRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    tools_needed: list[str] = Field(default_factory=list, max_length=64)
    task_description: str = Field(default="", max_length=8192)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def build_tool_router_router(engine: TektosToolRouter | None) -> APIRouter:
    router = APIRouter(tags=["tektos.tool_router"])

    def _guard() -> TektosToolRouter:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-107 degrade: tool_router not wired",
                    "adr": "ADR-107",
                },
            )
        return engine

    @router.post("/route")
    async def route(request: _RouteRequest) -> dict[str, Any]:
        eng = _guard()
        result, narrative_id = await eng.route_for_tools(
            session_id=request.session_id,
            tools_needed=tuple(request.tools_needed),
            task_description=request.task_description,
            confidence=request.confidence,
        )
        return {
            "route_id": result.id,
            "primary_tool": result.primary_tool,
            "fallback_tools": list(result.fallback_tools),
            "category": result.category,
            "reason": result.reason,
            "matched_tools": list(result.matched_tools),
            "unrouted_tools": list(result.unrouted_tools),
            "narrative_id": narrative_id,
        }

    @router.get("/recent")
    async def recent(limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        items = eng.list_recent(limit=limit)
        return {
            "count": len(items),
            "items": [
                {
                    "route_id": r.id,
                    "primary_tool": r.primary_tool,
                    "category": r.category,
                    "matched_tools": list(r.matched_tools),
                    "unrouted_tools": list(r.unrouted_tools),
                    "created_at": r.created_at,
                }
                for r in items
            ],
        }

    return router


__all__ = ["build_spec_executor_router", "build_tool_router_router"]
