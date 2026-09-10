"""Kosmos-native ``SynthesisEngine`` (Stage 8.3 · ADR-105).

Takes a spec dict (thesis) and an execution-feedback dict (antithesis)
and produces a ``SynthesisResult`` (the new state). Persists via
``RelationalMemoryPort.write_narrative`` when a port is bound; publishes
``tektos.synthesis.completed`` envelopes when the ``EventBus`` is bound.

Rule-based analytic core preserves the donor's ``_extract_lessons`` /
``_generate_recommendations`` shape:

- Lessons are extracted from the mismatch between ``spec.description``
  and ``execution_feedback.what_happened`` — any explicit ``error`` /
  ``failed`` / ``rejected`` signal in feedback yields a "lesson"
  string; any ``resource_exhausted`` / ``budget_exceeded`` yields a
  capacity lesson; any successful ``tool_outcomes`` count > 0 with a
  clean stop-reason yields a "confirmation" lesson.
- Recommendations mirror lessons but phrase them as forward-looking
  guidance ("next time, ...").

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

from ports.event_envelope import EventEnvelope

from . import (
    TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE,
    TEKTOS_SYNTHESIS_PREDICATE,
    TEKTOS_SYNTHESIS_PROVENANCE,
)
from .models import SynthesisResult

log = logging.getLogger(__name__)


@runtime_checkable
class _RelationalMemoryLike(Protocol):
    async def write_narrative(
        self,
        *,
        session_id: str,
        agent_id: str | None,
        title: str,
        body: str,
        tags: tuple[str, ...],
        embedding: tuple[float, ...] | None,
        confidence: float,
        provenance: str,
    ) -> str: ...


@runtime_checkable
class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class SynthesisEngine:
    """Kosmos Tektos synthesis engine (ADR-105 D1)."""

    def __init__(
        self,
        *,
        relational_memory: _RelationalMemoryLike | None = None,
        event_bus: _EventBusLike | None = None,
        max_records: int = 100,
    ) -> None:
        self._relational_memory = relational_memory
        self._event_bus = event_bus
        self._recent: deque[SynthesisResult] = deque(maxlen=max_records)

    @property
    def is_persistence_bound(self) -> bool:
        return self._relational_memory is not None

    def recent(self, limit: int = 10) -> tuple[SynthesisResult, ...]:
        if limit <= 0:
            return ()
        return tuple(list(self._recent)[-limit:])

    # --- rule-based analytic core --------------------------------------

    @staticmethod
    def _extract_lessons(
        spec: dict[str, Any], execution_feedback: dict[str, Any]
    ) -> tuple[str, ...]:
        lessons: list[str] = []
        what_happened = str(execution_feedback.get("what_happened", "")).lower()
        error = execution_feedback.get("error")
        stop_reason = str(execution_feedback.get("stop_reason", "")).lower()
        tool_outcomes = execution_feedback.get("tool_outcomes") or ()
        resource_exhausted = bool(execution_feedback.get("resource_exhausted", False))

        spec_desc = str(spec.get("description") or spec.get("goal") or "").strip()

        if error or stop_reason in {"llm_error", "sandbox_error"}:
            lessons.append(
                f"Execution failed against spec '{spec_desc[:80]}': "
                f"{str(error or stop_reason)[:200]}"
            )
        if "rejected" in what_happened or any(
            not (getattr(t, "accepted", None) if not isinstance(t, dict) else t.get("accepted", True))
            for t in tool_outcomes
        ):
            rejected = sum(
                1
                for t in tool_outcomes
                if not (getattr(t, "accepted", True) if not isinstance(t, dict) else t.get("accepted", True))
            )
            if rejected > 0:
                lessons.append(
                    f"Governance gates rejected {rejected} tool call(s); the spec's "
                    "tool set does not clear immune/loop-safety at this budget."
                )
        if resource_exhausted or "budget" in what_happened:
            lessons.append(
                "Spec ran the system to capacity edge (ResourcePort.can_allocate "
                "returned False after the turn)."
            )
        if (
            not lessons
            and stop_reason not in {"llm_error", "sandbox_error"}
            and len(tool_outcomes) > 0
        ):
            lessons.append(
                f"Spec '{spec_desc[:80]}' completed cleanly with "
                f"{len(tool_outcomes)} tool call(s); tactic is confirmed for "
                "this class of turn."
            )
        return tuple(lessons)

    @staticmethod
    def _generate_recommendations(lessons: tuple[str, ...]) -> tuple[str, ...]:
        recs: list[str] = []
        for lesson in lessons:
            lower = lesson.lower()
            if "failed" in lower or "error" in lower:
                recs.append(
                    f"Next time, add a pre-flight check that would have caught: "
                    f"{lesson[:160]}"
                )
            elif "rejected" in lower or "governance" in lower:
                recs.append(
                    "Next time, propose a smaller/read-only tool set for this "
                    "class of turn, or pre-approve the specific tools before "
                    "running the spec."
                )
            elif "capacity" in lower or "budget" in lower:
                recs.append(
                    "Next time, break the spec into smaller sub-specs so no single "
                    "turn drives ResourcePort to exhaustion."
                )
            elif "confirmed" in lower or "completed cleanly" in lower:
                recs.append(
                    "Reuse this tactic for structurally similar specs; record it as "
                    "a positive experience for planner recall."
                )
            else:
                recs.append(f"Next time, consider: {lesson[:160]}")
        return tuple(recs)

    # --- public entry point --------------------------------------------

    async def synthesize(
        self,
        *,
        session_id: str,
        spec: dict[str, Any],
        execution_feedback: dict[str, Any],
        confidence: float | None = None,
    ) -> tuple[SynthesisResult, str | None]:
        """Produce a synthesis from spec (thesis) + feedback (antithesis).

        Returns ``(result, narrative_id)`` — narrative_id ``None`` in
        memory-only mode. Never raises (fail-open).
        """
        spec_id = str(spec.get("id") or spec.get("spec_id") or "unknown-spec")
        spec_desc = str(spec.get("description") or spec.get("goal") or "")
        what_happened = str(
            execution_feedback.get("what_happened")
            or execution_feedback.get("summary")
            or ""
        )
        what_expected = str(
            spec.get("expected_outcome")
            or spec.get("expected")
            or spec_desc
        )

        lessons = self._extract_lessons(spec, execution_feedback)
        recommendations = self._generate_recommendations(lessons)

        priority = "high" if any(
            k in " ".join(lessons).lower() for k in ("failed", "error", "capacity")
        ) else "normal"

        insight_type = (
            "error_pattern"
            if any("failed" in l.lower() or "error" in l.lower() for l in lessons)
            else "positive_confirmation"
            if any("confirmed" in l.lower() for l in lessons)
            else "synthesis"
        )

        synthesis_text = (
            " ".join(recommendations)
            if recommendations
            else f"No corrective synthesis needed for spec '{spec_desc[:80]}'."
        )

        result = SynthesisResult(
            spec_id=spec_id,
            source="reflection_engine",
            insight_type=insight_type,
            what_happened=what_happened,
            what_was_expected=what_expected,
            synthesis=synthesis_text,
            lessons=lessons,
            recommendations=recommendations,
            is_actionable=bool(lessons),
            priority=priority,
            confidence=(
                float(confidence)
                if confidence is not None
                else TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE
            ),
            metadata={"spec_id": spec_id},
        )
        self._recent.append(result)

        narrative_id: str | None = None
        if self._relational_memory is not None:
            try:
                narrative_id = await self._relational_memory.write_narrative(
                    session_id=session_id,
                    agent_id=TEKTOS_SYNTHESIS_PROVENANCE,
                    title=f"{TEKTOS_SYNTHESIS_PREDICATE}:{result.id}",
                    body=json.dumps(
                        {
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
                        default=str,
                    ),
                    tags=(
                        TEKTOS_SYNTHESIS_PROVENANCE,
                        result.insight_type,
                        session_id,
                    ),
                    embedding=None,
                    confidence=result.confidence,
                    provenance=TEKTOS_SYNTHESIS_PROVENANCE,
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.synthesis: write_narrative failed; continuing in "
                    "memory-only mode (ADR-105 D9 fail-open)"
                )
                narrative_id = None

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    EventEnvelope(
                        event_type=TEKTOS_SYNTHESIS_PREDICATE,
                        producer_plugin=TEKTOS_SYNTHESIS_PROVENANCE,
                        payload={
                            "session_id": session_id,
                            "spec_id": result.spec_id,
                            "confidence": result.confidence,
                            "narrative_id": narrative_id,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.synthesis: EventBus publish failed; continuing "
                    "(fail-open)"
                )

        return result, narrative_id


__all__ = ["SynthesisEngine"]
