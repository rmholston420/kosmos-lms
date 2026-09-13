"""FastAPI router factory for the Tektos S3 Manager (Stage 8.6 · ADR-108 D8).

Single factory :func:`build_manager_router` returning an ``APIRouter`` with
``tags=["tektos.manager"]`` and no internal prefix. Mount-time prefix
per the Stage 8.3/8.5 pattern (kernel wiring will mount under
``/tektos/api/manager``).

When the engine is unwired, every route returns
``503 {"detail": "ADR-108 degrade: manager not wired", "adr": "ADR-108"}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import TektosManager


# ── Request bodies ─────────────────────────────────────────────────────────


class _TaskStartRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    task_id: str = Field(min_length=1, max_length=256)
    spec_id: str = Field(default="", max_length=256)


class _TaskCompleteRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    task_id: str = Field(min_length=1, max_length=256)
    success: bool
    tokens_used: int = Field(default=0, ge=0)
    tools_used: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)


class _ErrorRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4096)
    severity: str = Field(default="warning", max_length=32)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class _SpiralUpdateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    new_radius: float = Field(ge=0.0, le=10.0)
    description: str = Field(default="", max_length=1024)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class _RhythmRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    rhythm_name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=1024)


# ── Serialisation helper ───────────────────────────────────────────────────


def _feedback_to_dict(feedback: Any) -> dict[str, Any]:
    return {
        "id": feedback.id,
        "type": feedback.type,
        "severity": feedback.severity,
        "what": feedback.what,
        "why": feedback.why,
        "how": feedback.how,
        "what_happened": feedback.what_happened,
        "what_should_happen": feedback.what_should_happen,
        "try_this": feedback.try_this,
        "session_id": feedback.session_id,
        "category": feedback.category,
    }


# ── Router factory ─────────────────────────────────────────────────────────


def build_manager_router(engine: TektosManager | None) -> APIRouter:
    """Build the S3 Manager router (ADR-108 D8)."""

    router = APIRouter(tags=["tektos.manager"])

    def _guard() -> TektosManager:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-108 degrade: manager not wired",
                    "adr": "ADR-108",
                },
            )
        return engine

    @router.post("/task-start")
    async def task_start(request: _TaskStartRequest) -> dict[str, Any]:
        eng = _guard()
        await eng.on_task_start(
            session_id=request.session_id,
            task_id=request.task_id,
            spec_id=request.spec_id,
        )
        return {"state": eng.state, "spiral_radius": eng.spiral_radius}

    @router.post("/task-complete")
    async def task_complete(request: _TaskCompleteRequest) -> dict[str, Any]:
        eng = _guard()
        await eng.on_task_complete(
            session_id=request.session_id,
            task_id=request.task_id,
            success=request.success,
            tokens_used=request.tokens_used,
            tools_used=request.tools_used,
            elapsed_seconds=request.elapsed_seconds,
        )
        return {"state": eng.state}

    @router.post("/error")
    async def error(request: _ErrorRequest) -> dict[str, Any]:
        eng = _guard()
        feedback, narrative_id = await eng.on_error(
            session_id=request.session_id,
            category=request.category,
            description=request.description,
            severity=request.severity,
            confidence=request.confidence,
        )
        return {
            "feedback": _feedback_to_dict(feedback) if feedback is not None else None,
            "narrative_id": narrative_id,
            "recovery_strategy": eng.classify_recovery(request.category),
        }

    @router.post("/spiral-update")
    async def spiral_update(request: _SpiralUpdateRequest) -> dict[str, Any]:
        eng = _guard()
        feedback, narrative_id = await eng.on_spiral_update(
            session_id=request.session_id,
            new_radius=request.new_radius,
            description=request.description,
            confidence=request.confidence,
        )
        return {
            "feedback": _feedback_to_dict(feedback) if feedback is not None else None,
            "narrative_id": narrative_id,
            "spiral_radius": eng.spiral_radius,
        }

    @router.post("/rhythm")
    async def rhythm(request: _RhythmRequest) -> dict[str, Any]:
        eng = _guard()
        feedback = eng.on_rhythm_event(
            session_id=request.session_id,
            rhythm_name=request.rhythm_name,
            description=request.description,
        )
        return {"feedback": _feedback_to_dict(feedback)}

    @router.get("/health")
    async def health() -> dict[str, Any]:
        eng = _guard()
        report = eng.get_health_report()
        return {
            "state": report.state,
            "spiral_radius": report.spiral_radius,
            "feedback_total": report.feedback_total,
            "active_archetypes": [
                {"category": c, "count": n, "threshold": t}
                for (c, n, t) in report.active_archetypes
            ],
            "timestamp": report.timestamp,
        }

    @router.get("/recent")
    async def recent(limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        items = eng.list_recent(limit=limit)
        return {
            "count": len(items),
            "items": [_feedback_to_dict(f) for f in items],
        }

    return router


__all__ = ["build_manager_router"]
