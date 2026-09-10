"""FastAPI router factory for the Stage 8.3 reflection engine (ADR-105 D8).

Exposes ``POST /reflect`` and ``GET /recent``. The router is designed to
be mounted under ``/tektos/api/reflection`` by any FastAPI application
(the Stage 3.11 Tektos UI app being the canonical mount host at Stage
8.4+ per ADR-105 §D8).

Missing / unwired engine → the factory returns a router whose every
endpoint responds ``503 {"detail": "ADR-105 degrade: reflection not
wired", "adr": "ADR-105"}`` — matches the ADR-101 request-time degrade
shape.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import ReflectionEngine


class ReflectRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    turn_outcome: dict[str, Any] = Field(default_factory=dict)
    focus: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def build_reflection_router(engine: ReflectionEngine | None) -> APIRouter:
    """Build the reflection FastAPI router.

    Passing ``engine=None`` yields a router whose endpoints degrade to
    ``503`` — this is the ADR-101 request-time contract; the router is
    always constructable so route enumeration works regardless of
    engine wiring.
    """
    router = APIRouter(tags=["tektos.reflection"])

    def _guard() -> ReflectionEngine:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-105 degrade: reflection not wired",
                    "adr": "ADR-105",
                },
            )
        return engine

    @router.post("/reflect")
    async def _reflect(req: ReflectRequest) -> dict[str, Any]:
        eng = _guard()
        insight, narrative_id = await eng.reflect_on_turn(
            session_id=req.session_id,
            turn_outcome=req.turn_outcome,
            focus=req.focus,
            confidence=req.confidence,
        )
        return {
            "insight": {
                "id": insight.id,
                "source": insight.source,
                "content": insight.content,
                "is_direct_experience": insight.is_direct_experience,
                "trust_score": insight.trust_score,
                "bias_detected": insight.bias_detected,
                "correction": insight.correction,
                "is_novel": insight.is_novel,
                "novelty_score": insight.novelty_score,
                "insight_type": insight.insight_type,
                "timestamp": insight.timestamp,
                "metadata": insight.metadata,
            },
            "narrative_id": narrative_id,
        }

    @router.get("/recent")
    async def _recent(limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        recents = eng.recent(limit=limit)
        return {
            "insights": [
                {
                    "id": i.id,
                    "insight_type": i.insight_type,
                    "content": i.content,
                    "trust_score": i.trust_score,
                    "timestamp": i.timestamp,
                }
                for i in recents
            ]
        }

    return router


__all__ = ["ReflectRequest", "build_reflection_router"]
