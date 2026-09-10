"""Kosmos-native ``ReflectionEngine`` (Stage 8.3 · ADR-105).

Consumes Stage 8.2 ``TurnOutcome`` records (or arbitrary
observation-dict inputs) and produces ``ReflectionInsight`` +
``ReflectionState`` records. Persists narratives via
``RelationalMemoryPort.write_narrative`` (ADR-102) when a port is bound;
publishes ``tektos.reflection.completed`` envelopes on the ``EventBus``
when one is bound. Both collaborators are optional (ADR-105 D1).

Rule-based analytic logic — preserved verbatim in intent from the donor
(``tektos-ultima/src/tektos/memory/reflection_engine.py``):

- ``examine_direct_experience`` — weight explicit execution observations
  (``"execute"`` keyword) and failure evidence (``"error"`` / ``"fail"``)
  as high-trust direct experience. Failures are the most trustworthy.
- ``check_for_biases`` — heuristic hemisphere-balance check when caller
  supplies hemisphere-labeled observations. Falls back to a
  count-based inference-vs-direct-experience check when no hemisphere
  labels are present.
- ``_generate_insight_for_turn`` — Stage 8.3 shape: derives an insight
  from a ``TurnOutcome`` by inspecting ``stop_reason`` / ``error`` /
  ``tool_outcomes`` / ``resource_exhausted``.

The engine is decoupled from ``TektosTurnLoop`` at 8.3 — callers invoke
``reflect_on_turn(outcome)`` explicitly (either directly, via the Stage
8.3 FastAPI router at ``POST /tektos/api/reflection/reflect``, or via a
Stage 8.4 auto-subscription that ADR-105 D9 defers).

ADR-007: this module imports only from ``ports.*`` and its own
``plugins.tektos.reflection`` subpackage.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

from ports.event_envelope import EventEnvelope

from . import (
    TEKTOS_REFLECTION_DEFAULT_CONFIDENCE,
    TEKTOS_REFLECTION_PREDICATE,
    TEKTOS_REFLECTION_PROVENANCE,
)
from .models import ReflectionInsight, ReflectionState

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


class ReflectionEngine:
    """Kosmos Tektos reflection engine (ADR-105 D1)."""

    def __init__(
        self,
        *,
        relational_memory: _RelationalMemoryLike | None = None,
        event_bus: _EventBusLike | None = None,
        max_records: int = 100,
    ) -> None:
        self._relational_memory = relational_memory
        self._event_bus = event_bus
        self._recent: deque[ReflectionInsight] = deque(maxlen=max_records)

    @property
    def is_persistence_bound(self) -> bool:
        return self._relational_memory is not None

    def recent(self, limit: int = 10) -> tuple[ReflectionInsight, ...]:
        """Return the most-recent insights (newest last).

        At Stage 8.3 the memory-only ring buffer is the source of
        ``recent`` even when the port is bound; the port-backed recall
        path lives on ``ExperienceReplay`` (which is the intended recall
        surface for planner-consumed guidance per ADR-105 §Rationale).
        """
        if limit <= 0:
            return ()
        items = list(self._recent)[-limit:]
        return tuple(items)

    # --- rule-based analytic core --------------------------------------

    @staticmethod
    def _generate_insight_for_turn(
        outcome: dict[str, Any],
        *,
        focus: str | None = None,
    ) -> ReflectionInsight:
        """Rule-based insight generation from a ``TurnOutcome`` dict.

        Preserves the donor's yogic weighting: direct-observation
        outcomes (successful execution) get moderate trust; failure
        outcomes (``error`` set, terminal ``stop_reason``) are the most
        trustworthy signal (95% trust score, matching donor 0.95).
        """
        stop_reason = str(outcome.get("stop_reason", "")).lower()
        error = outcome.get("error")
        tool_outcomes = outcome.get("tool_outcomes") or ()
        resource_exhausted = bool(outcome.get("resource_exhausted", False))

        if error or stop_reason in {"llm_error", "sandbox_error"}:
            return ReflectionInsight(
                source="turn_outcome",
                content=(
                    f"Failure pattern: stop_reason={stop_reason!r}; "
                    f"error={str(error)[:200]!r}"
                ),
                is_direct_experience=True,
                trust_score=0.95,
                bias_detected=None,
                correction=(
                    f"Learn from: {str(error)[:120] if error else stop_reason}"
                ),
                insight_type="failure_pattern",
                metadata={"focus": focus, "stop_reason": stop_reason},
            )

        if resource_exhausted:
            return ReflectionInsight(
                source="turn_outcome",
                content=(
                    "Direct observation: post-turn ResourcePort.can_allocate "
                    "returned False; system is at capacity edge."
                ),
                is_direct_experience=True,
                trust_score=0.85,
                bias_detected="capacity_underestimation",
                correction="Reduce concurrent workload or raise budget.",
                insight_type="resource_pressure",
                metadata={"focus": focus, "stop_reason": stop_reason},
            )

        accepted = sum(1 for t in tool_outcomes if getattr(t, "accepted", False) or (isinstance(t, dict) and t.get("accepted")))
        rejected = len(tool_outcomes) - accepted
        if rejected > 0 and accepted == 0 and len(tool_outcomes) > 0:
            return ReflectionInsight(
                source="turn_outcome",
                content=(
                    f"Direct observation: all {len(tool_outcomes)} tool call(s) "
                    "were rejected by immune or loop-safety gates."
                ),
                is_direct_experience=True,
                trust_score=0.9,
                bias_detected="tool_selection_mismatch",
                correction=(
                    "Tool set proposed does not clear governance gates; "
                    "re-plan with a smaller/read-only tool set."
                ),
                insight_type="tool_gating_pattern",
                metadata={"focus": focus, "stop_reason": stop_reason},
            )

        return ReflectionInsight(
            source="turn_outcome",
            content=(
                f"Direct observation: turn stopped cleanly (stop_reason="
                f"{stop_reason!r}); {accepted}/{len(tool_outcomes)} tools accepted."
            ),
            is_direct_experience=True,
            trust_score=0.75,
            insight_type="clean_completion",
            metadata={"focus": focus, "stop_reason": stop_reason},
        )

    @staticmethod
    def examine_direct_experience(
        observations: tuple[dict[str, Any], ...],
    ) -> tuple[ReflectionInsight, ...]:
        """Weight execution observations by the yogic direct-experience principle.

        Each observation is a free-form dict; expected keys (all
        optional): ``content: str``, ``hemisphere: {"left","right"}``
        (Stage 13 concern; when absent the check falls back to keyword
        heuristics), ``why: str``.
        """
        insights: list[ReflectionInsight] = []
        for m in observations:
            content = str(m.get("content", ""))
            content_lc = content.lower()
            hemisphere = str(m.get("hemisphere", "")).lower()
            if hemisphere == "left" and "execute" in content_lc:
                insights.append(
                    ReflectionInsight(
                        source=str(m.get("source", "observation")),
                        content=f"Direct observation: {content[:200]}",
                        is_direct_experience=True,
                        trust_score=0.9,
                        insight_type="direct_experience",
                        metadata={"why": m.get("why")},
                    )
                )
            if "error" in content_lc or "fail" in content_lc:
                insights.append(
                    ReflectionInsight(
                        source=str(m.get("source", "observation")),
                        content=f"Failure pattern: {content[:200]}",
                        is_direct_experience=True,
                        trust_score=0.95,
                        bias_detected=None,
                        correction=f"Learn from: {content[:120]}",
                        insight_type="failure_pattern",
                    )
                )
        return tuple(insights)

    @staticmethod
    def check_for_biases(
        observations: tuple[dict[str, Any], ...],
    ) -> tuple[ReflectionInsight, ...]:
        """Detect speculation-bias / recency-bias / confirmation-bias patterns.

        When ``hemisphere`` labels are absent (Stage 8.3 default), falls
        back to a simple direct-vs-inference ratio check based on the
        ``is_direct_experience`` field of any pre-built insights the
        caller supplies via ``observations[i]["insight"]``.
        """
        insights: list[ReflectionInsight] = []
        left = sum(1 for m in observations if str(m.get("hemisphere", "")).lower() == "left")
        right = sum(1 for m in observations if str(m.get("hemisphere", "")).lower() == "right")
        total = left + right
        if total > 0 and right / total > 0.8 and left > 0:
            insights.append(
                ReflectionInsight(
                    source="hemisphere_balance",
                    content=(
                        f"Speculation bias detected: {right} speculative vs "
                        f"{left} operative entries. System is over-planning, "
                        "under-executing."
                    ),
                    is_direct_experience=False,
                    trust_score=0.7,
                    bias_detected="speculation_bias",
                    correction=(
                        "Increase execution cadence; reduce speculative "
                        "planning cycles."
                    ),
                    insight_type="bias_detected",
                )
            )
        return tuple(insights)

    # --- public entry point --------------------------------------------

    async def reflect_on_turn(
        self,
        *,
        session_id: str,
        turn_outcome: dict[str, Any],
        focus: str | None = None,
        confidence: float | None = None,
    ) -> tuple[ReflectionInsight, str | None]:
        """Reflect on a completed turn.

        Returns ``(insight, narrative_id)`` — ``narrative_id`` is
        ``None`` when persistence is unbound (memory-only mode).

        Never raises: persistence and event-bus failures are logged and
        swallowed (fail-open, mirrors ADR-104 D2 pattern).
        """
        insight = self._generate_insight_for_turn(turn_outcome, focus=focus)
        self._recent.append(insight)

        eff_conf = (
            float(confidence)
            if confidence is not None
            else TEKTOS_REFLECTION_DEFAULT_CONFIDENCE
        )

        narrative_id: str | None = None
        if self._relational_memory is not None:
            try:
                narrative_id = await self._relational_memory.write_narrative(
                    session_id=session_id,
                    agent_id=TEKTOS_REFLECTION_PROVENANCE,
                    title=f"{TEKTOS_REFLECTION_PREDICATE}:{insight.id}",
                    body=json.dumps(
                        {
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
                        default=str,
                    ),
                    tags=(
                        TEKTOS_REFLECTION_PROVENANCE,
                        insight.insight_type,
                        session_id,
                    ),
                    embedding=None,
                    confidence=eff_conf,
                    provenance=TEKTOS_REFLECTION_PROVENANCE,
                )
            except Exception:  # noqa: BLE001 — fail-open (ADR-104 D2 pattern)
                log.exception(
                    "tektos.reflection: write_narrative failed; continuing "
                    "in memory-only mode (ADR-105 D9 fail-open)"
                )
                narrative_id = None

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    EventEnvelope(
                        event_type=TEKTOS_REFLECTION_PREDICATE,
                        producer_plugin=TEKTOS_REFLECTION_PROVENANCE,
                        payload={
                            "session_id": session_id,
                            "insight_type": insight.insight_type,
                            "confidence": eff_conf,
                            "narrative_id": narrative_id,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.reflection: EventBus publish failed; continuing "
                    "(fail-open)"
                )

        return insight, narrative_id


__all__ = ["ReflectionEngine"]
