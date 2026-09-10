"""FastAPI router factory for the Tektos spec-planner engine (ADR-106 D8).

Mounts under ``/tektos/api/spec-planner`` in the Kosmos kernel. When the
engine is unwired (env-gate off or degraded), every route returns
``503 {"detail": "ADR-106 degrade: spec_planner not wired", "adr": "ADR-106"}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .spec_planner import TektosSpecPlanner


class _PlanRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    prompt: str = Field(min_length=1, max_length=32768)
    context: dict[str, Any] | None = None
    user_preference: str | None = Field(default=None, max_length=128)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def build_spec_planner_router(engine: TektosSpecPlanner | None) -> APIRouter:
    """Return a router that exposes the spec-planner engine."""
    router = APIRouter(tags=["tektos.spec_planner"])

    def _guard() -> TektosSpecPlanner:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-106 degrade: spec_planner not wired",
                    "adr": "ADR-106",
                },
            )
        return engine

    @router.post("/plan")
    async def plan(request: _PlanRequest) -> dict[str, Any]:
        eng = _guard()
        output, narrative_id = await eng.generate_spec(
            session_id=request.session_id,
            prompt=request.prompt,
            context=request.context,
            user_preference=request.user_preference,
            confidence=request.confidence,
        )
        spec = output.spec
        return {
            "spec_id": spec.id,
            "narrative_id": narrative_id,
            "language_game": spec.language_game.value,
            "language_game_detected": output.language_game_detected.value,
            "description": spec.description,
            "translated_prompt": spec.translated_prompt,
            "architecture": {
                "selected": spec.architecture.selected,
                "reason": spec.architecture.reason,
                "is_user_choice": spec.architecture.is_user_choice,
            },
            "requirements": list(spec.requirements),
            "constraints": list(spec.constraints),
            "phases": [
                {
                    "id": phase.id,
                    "description": phase.description,
                    "deliverables": list(phase.deliverables),
                    "acceptance_criteria": list(phase.acceptance_criteria),
                    "estimated_effort": phase.estimated_effort,
                }
                for phase in spec.phases
            ],
            "clarifying_questions": [
                {
                    "question": q.question,
                    "options": list(q.options),
                    "default": q.default,
                    "reason": q.reason,
                }
                for q in output.clarifying_questions_asked
            ],
            "notes": list(spec.notes),
        }

    @router.get("/recent")
    async def recent(limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        items = eng.list_recent(limit=limit)
        return {
            "count": len(items),
            "items": [
                {
                    "spec_id": item.spec.id,
                    "language_game": item.spec.language_game.value,
                    "description": item.spec.description,
                    "architecture": item.spec.architecture.selected,
                }
                for item in items
            ],
        }

    return router


__all__ = ["build_spec_planner_router"]
