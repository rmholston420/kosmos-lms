"""FastAPI router factory for the Stage 8.3 synthesis engine (ADR-105 D8).

Exposes ``POST /synthesize`` and ``GET /recent``. Mount under
``/tektos/api/synthesis``. Same ADR-101 request-time degrade shape as
the reflection router.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import SynthesisEngine


class SynthesizeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    spec: dict[str, Any] = Field(default_factory=dict)
    execution_feedback: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def build_synthesis_router(engine: SynthesisEngine | None) -> APIRouter:
    router = APIRouter(tags=["tektos.synthesis"])

    def _guard() -> SynthesisEngine:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-105 degrade: synthesis not wired",
                    "adr": "ADR-105",
                },
            )
        return engine

    @router.post("/synthesize")
    async def _synthesize(req: SynthesizeRequest) -> dict[str, Any]:
        eng = _guard()
        result, narrative_id = await eng.synthesize(
            session_id=req.session_id,
            spec=req.spec,
            execution_feedback=req.execution_feedback,
            confidence=req.confidence,
        )
        return {
            "result": {
                "id": result.id,
                "spec_id": result.spec_id,
                "source": result.source,
                "insight_type": result.insight_type,
                "what_happened": result.what_happened,
                "what_was_expected": result.what_was_expected,
                "synthesis": result.synthesis,
                "lessons": list(result.lessons),
                "recommendations": list(result.recommendations),
                "is_actionable": result.is_actionable,
                "priority": result.priority,
                "confidence": result.confidence,
                "timestamp": result.timestamp,
                "metadata": result.metadata,
            },
            "narrative_id": narrative_id,
        }

    @router.get("/recent")
    async def _recent(limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        recents = eng.recent(limit=limit)
        return {
            "results": [
                {
                    "id": r.id,
                    "spec_id": r.spec_id,
                    "insight_type": r.insight_type,
                    "synthesis": r.synthesis,
                    "priority": r.priority,
                    "confidence": r.confidence,
                    "timestamp": r.timestamp,
                }
                for r in recents
            ]
        }

    return router


__all__ = ["SynthesizeRequest", "build_synthesis_router"]
