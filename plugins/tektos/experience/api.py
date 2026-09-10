"""FastAPI router factory for the Stage 8.3 experience-replay engine (ADR-105 D8).

Exposes ``GET /recent`` (context-filtered recall) and ``POST /record``.
Mount under ``/tektos/api/experience``. Same ADR-101 request-time
degrade shape as the reflection + synthesis routers.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .replay import ExperienceReplay


class RecordRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    synthesis: dict[str, Any] = Field(default_factory=dict)
    context: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def build_experience_router(engine: ExperienceReplay | None) -> APIRouter:
    router = APIRouter(tags=["tektos.experience"])

    def _guard() -> ExperienceReplay:
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "ADR-105 degrade: experience not wired",
                    "adr": "ADR-105",
                },
            )
        return engine

    @router.get("/recent")
    async def _recent(context: str, limit: int = 10) -> dict[str, Any]:
        eng = _guard()
        records = await eng.recall(context=context, limit=limit)
        return {
            "records": [
                {
                    "id": r.id,
                    "cycle_id": r.cycle_id,
                    "insight_type": r.insight_type,
                    "guidance": r.guidance,
                    "context": r.context,
                    "confidence": r.confidence,
                    "priority": r.priority,
                    "timestamp": r.timestamp,
                    "summary": r.summary,
                }
                for r in records
            ]
        }

    @router.post("/record")
    async def _record(req: RecordRequest) -> dict[str, Any]:
        eng = _guard()
        record, narrative_id = await eng.record(
            session_id=req.session_id,
            synthesis=req.synthesis,
            context=req.context,
            confidence=req.confidence,
        )
        return {
            "record": {
                "id": record.id,
                "cycle_id": record.cycle_id,
                "insight_type": record.insight_type,
                "what_happened": record.what_happened,
                "what_was_expected": record.what_was_expected,
                "guidance": record.guidance,
                "context": record.context,
                "confidence": record.confidence,
                "priority": record.priority,
                "timestamp": record.timestamp,
                "tags": list(record.tags),
                "summary": record.summary,
            },
            "narrative_id": narrative_id,
        }

    return router


__all__ = ["RecordRequest", "build_experience_router"]
