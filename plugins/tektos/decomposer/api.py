"""FastAPI router factory for the Tektos task-decomposer engine (ADR-106 D8).

Mounts under ``/tektos/api/decomposer`` in the Kosmos kernel. When the engine
is unwired (env-gate off or degraded), every route returns
``503 {"detail": "ADR-106 degrade: decomposer not wired", "adr": "ADR-106"}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import TaskDecomposer


class _DecomposeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    task: str = Field(min_length=1, max_length=32768)
    task_id: str | None = Field(default=None, max_length=256)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def build_decomposer_router(engine: TaskDecomposer | None) -> APIRouter:
    router = APIRouter(tags=["tektos.decomposer"])

    def _guard() -> TaskDecomposer:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-106 degrade: decomposer not wired",
                    "adr": "ADR-106",
                },
            )
        return engine

    @router.post("/decompose")
    async def decompose(request: _DecomposeRequest) -> dict[str, Any]:
        eng = _guard()
        plan, narrative_id = await eng.decompose(
            session_id=request.session_id,
            task=request.task,
            task_id=request.task_id,
            confidence=request.confidence,
        )
        return {
            "plan_id": plan.id,
            "narrative_id": narrative_id,
            "phase": plan.phase,
            "sub_task_count": len(plan.sub_tasks),
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
            "formatted_prompt": TaskDecomposer.format_for_prompt(plan),
        }

    @router.get("/recent")
    async def recent(limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        items = eng.list_recent(limit=limit)
        return {
            "count": len(items),
            "items": [
                {
                    "plan_id": item.id,
                    "phase": item.phase,
                    "sub_task_count": len(item.sub_tasks),
                    "original_task": item.original_task,
                }
                for item in items
            ],
        }

    return router


__all__ = ["build_decomposer_router"]
