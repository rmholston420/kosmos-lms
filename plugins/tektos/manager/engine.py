"""Kosmos-native Tektos S3 Manager engine (Stage 8.6 · ADR-108).

:class:`TektosManager` rewrites
``tektos-ultima/src/tektos/agents/manager/orchestrator.py::Manager`` per
ADR-108 D2. Semantics preserved verbatim:

* Lifecycle hooks: ``on_task_start`` / ``on_task_complete`` / ``on_error``
  / ``on_spiral_update`` / ``on_rhythm_event``.
* Archetype-hit path (``_generate_archetype_feedback``) verbatim.
* Guardrail scanning REROUTED from donor's inline regex to
  :meth:`ports.immune.ImmunePort.scan` (ADR-079); donor regex kept as a
  fallback keyword scan when the port is unbound (ADR-108 D9).
* Metric recording REROUTED to :meth:`ports.observability.ObservabilityPort.score`
  (ADR-025); donor's ``PrimeMoverMetrics.samples`` in-process accumulator
  REJECTED (ADR-108 R2). Threshold table + branching preserved as pure
  ``_check_threshold`` function.
* Donor ``telemetry.py`` REJECTED (ADR-108 R1) — ``ThermalPort`` (ADR-081)
  owns RTX 5090 threshold enforcement.

Every port call is wrapped in a try/except with ``log.exception``; the
engine's ring buffer of last ``max_records`` feedbacks is always populated
so downstream callers have observable state even when every port fails.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

from ports.event_envelope import EventEnvelope

from . import (
    TEKTOS_MANAGER_DEFAULT_CONFIDENCE,
    TEKTOS_MANAGER_EVENT_ARCHETYPE,
    TEKTOS_MANAGER_EVENT_GUARDRAIL,
    TEKTOS_MANAGER_PREDICATE,
    TEKTOS_MANAGER_PROVENANCE,
)
from .archetype_tracker import ArchetypeTracker
from .guardrails import GUARDRAIL_RULES, Guardrail
from .models import (
    ManagerFeedback,
    ManagerHealthReport,
    ManagerState,
    MetricThreshold,
    RecoveryStrategy,
)

log = logging.getLogger(__name__)


# ── Structural Protocols (avoid concrete port imports for ADR-007 hygiene) ──


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


@runtime_checkable
class _ImmuneLike(Protocol):
    async def scan(self, request: Any) -> Any: ...

    def is_healthy(self) -> bool: ...


@runtime_checkable
class _ObservabilityLike(Protocol):
    def score(
        self,
        name: str,
        value: float,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> None: ...


# ── Metric threshold table (donor ``PrimeMoverMetrics.thresholds`` verbatim) ─
# Direction "below" — larger values are bad (error_rate, latency, ...)
# Direction "above" — smaller values are bad (token_efficiency, tool_success_ratio, ...)
# Kosmos "above/below" == donor "lower_is_better/higher_is_better" respectively.
_THRESHOLDS: dict[str, MetricThreshold] = {
    "error_rate": MetricThreshold(warning=0.05, critical=0.10, direction="below"),
    "token_efficiency": MetricThreshold(warning=1.5, critical=2.0, direction="above"),
    "tool_success_ratio": MetricThreshold(warning=0.80, critical=0.60, direction="above"),
    "context_compression_ratio": MetricThreshold(warning=1.5, critical=2.0, direction="above"),
    "skill_creation_rate": MetricThreshold(warning=0.5, critical=0.1, direction="above"),
    "archetype_frequency": MetricThreshold(warning=5.0, critical=10.0, direction="below"),
    "spiral_radius": MetricThreshold(warning=0.5, critical=0.8, direction="below"),
    "latency": MetricThreshold(warning=10.0, critical=30.0, direction="below"),
}


def _check_threshold(name: str, value: float) -> Literal["warning", "critical"] | None:
    """Pure port of donor ``PrimeMoverMetrics.check_threshold`` semantics.

    Returns ``"critical"`` / ``"warning"`` / ``None``. Never raises.
    """

    threshold = _THRESHOLDS.get(name)
    if threshold is None:
        return None

    if threshold.direction == "below":
        # donor "lower_is_better" — bigger is worse
        if value >= threshold.critical:
            return "critical"
        if value >= threshold.warning:
            return "warning"
    else:  # "above" — donor "higher_is_better", smaller is worse
        if value <= threshold.critical:
            return "critical"
        if value <= threshold.warning:
            return "warning"
    return None


# ── Guardrail fallback keyword scan (ADR-108 D9 · R3) ─────────────────────


_SECRET_KEYWORDS: tuple[str, ...] = (
    "secret",
    "credential",
    "api_key",
    "apikey",
    "token",
    "password",
    "connection_string",
)
_COMPUTE_KEYWORDS: tuple[str, ...] = ("comput", "calculation", "arithmetic")


def _fallback_guardrail_scan(
    category: str, description: str
) -> tuple[Guardrail, str] | None:
    """Fallback keyword scan used only when :class:`ImmunePort` is unbound.

    Preserved verbatim from donor ``Manager._check_guardrails``. Returns
    ``(guardrail, reason)`` on hit, ``None`` on clean.
    """

    haystack = f"{category} {description}".lower()

    if any(kw in haystack for kw in _SECRET_KEYWORDS):
        return (
            Guardrail.NO_HARD_CODED_SECRETS,
            "keyword_scan matched secret-related token",
        )
    if any(kw in haystack for kw in _COMPUTE_KEYWORDS):
        return (
            Guardrail.LLM_MUST_NOT_COMPUTE,
            "keyword_scan matched computation-related token",
        )
    return None


# ── Recovery strategy classification (ADR-108 D9 · discharges ADR-107 D9.1) ─


_RETRY_KEYWORDS: tuple[str, ...] = ("timeout", "network", "rate_limit", "throttle")
_ALTERNATIVE_KEYWORDS: tuple[str, ...] = (
    "not_found",
    "not_installed",
    "unavailable",
    "unsupported",
)
_ESCALATE_KEYWORDS: tuple[str, ...] = (
    "auth",
    "permission",
    "forbidden",
    "credential",
)


def classify_recovery(category: str) -> RecoveryStrategy:
    """Classify a failure category to a recovery strategy (pure function).

    Discharges ADR-107 D9 point 1 — the classification surface lives here at
    8.6; the actual retry / alternative / skip loop stays in the Stage 8.7
    multi-agent orchestrator. Deterministic and side-effect-free.
    """

    haystack = category.lower()
    if any(kw in haystack for kw in _ESCALATE_KEYWORDS):
        return "escalate"
    if any(kw in haystack for kw in _RETRY_KEYWORDS):
        return "retry"
    if any(kw in haystack for kw in _ALTERNATIVE_KEYWORDS):
        return "alternative_tool"
    return "skip"


# ── Feedback body serialisation ────────────────────────────────────────────


def _feedback_to_body(feedback: ManagerFeedback) -> dict[str, Any]:
    """Serialise a :class:`ManagerFeedback` for the narrative body."""

    return {
        "id": feedback.id,
        "type": feedback.type,
        "severity": feedback.severity,
        "who": feedback.who,
        "what": feedback.what,
        "where": feedback.where,
        "when": feedback.when,
        "why": feedback.why,
        "how": feedback.how,
        "what_happened": feedback.what_happened,
        "what_should_happen": feedback.what_should_happen,
        "try_this": feedback.try_this,
        "session_id": feedback.session_id,
        "category": feedback.category,
    }


# ── Engine ─────────────────────────────────────────────────────────────────


class TektosManager:
    """Kosmos Tektos S3 Manager (ADR-108 D1).

    Guardrails, not command. Regulates variety between S1 (agent) and S4
    (planner), tracks archetypes, delegates guardrail scanning to
    :class:`ports.immune.ImmunePort`, and records metrics through
    :class:`ports.observability.ObservabilityPort`.

    Every hook returns ``(feedback, narrative_id)`` where ``feedback`` may
    be ``None`` (no re-direction needed) and ``narrative_id`` is ``None``
    when persistence is unbound or the write call failed.
    """

    def __init__(
        self,
        *,
        relational_memory: _RelationalMemoryLike | None = None,
        event_bus: _EventBusLike | None = None,
        immune: _ImmuneLike | None = None,
        observability: _ObservabilityLike | None = None,
        max_records: int = 100,
        archetype_threshold: int = 3,
        max_feedback_length: int = 500,
    ) -> None:
        self._relational_memory = relational_memory
        self._event_bus = event_bus
        self._immune = immune
        self._observability = observability
        self._buffer: deque[ManagerFeedback] = deque(maxlen=max_records)
        self._state: ManagerState = "idle"
        self._spiral_radius: float = 1.0
        self._max_feedback_length = max_feedback_length
        self.archetypes = ArchetypeTracker(threshold=archetype_threshold)

    # ── Property surfaces ──────────────────────────────────────────────────

    @property
    def is_persistence_bound(self) -> bool:
        return self._relational_memory is not None

    @property
    def is_immune_bound(self) -> bool:
        try:
            return self._immune is not None and self._immune.is_healthy()
        except Exception:  # noqa: BLE001
            log.exception("tektos.manager: immune is_healthy() raised; treating as unbound")
            return False

    @property
    def state(self) -> ManagerState:
        return self._state

    @property
    def spiral_radius(self) -> float:
        return self._spiral_radius

    # ── Lifecycle hooks ────────────────────────────────────────────────────

    async def on_task_start(
        self,
        *,
        session_id: str,
        task_id: str,
        spec_id: str = "",
    ) -> None:
        """Task start — state → active + latency=0 metric.

        Donor parity: no feedback returned; observability-only.
        """

        self._state = "active"
        self._score(
            "latency",
            0.0,
            attributes={"session_id": session_id, "task_id": task_id, "spec_id": spec_id},
        )

    async def on_task_complete(
        self,
        *,
        session_id: str,
        task_id: str,
        success: bool,
        tokens_used: int = 0,
        tools_used: int = 0,
        elapsed_seconds: float = 0.0,
    ) -> None:
        """Task complete — state → idle + metric fanout.

        Donor parity: records latency, error_rate, and (on success) both
        token_efficiency and tool_success_ratio through
        :meth:`ObservabilityPort.score`.
        """

        base_attrs = {"session_id": session_id, "task_id": task_id}
        self._score("latency", elapsed_seconds, attributes=base_attrs)
        if success:
            self._score("error_rate", 0.0, attributes=base_attrs)
            self._score(
                "token_efficiency",
                tokens_used / max(1, tools_used),
                attributes=base_attrs,
            )
            self._score("tool_success_ratio", 1.0, attributes=base_attrs)
        else:
            self._score("error_rate", 1.0, attributes=base_attrs)
            self._score("tool_success_ratio", 0.0, attributes=base_attrs)
        self._state = "idle"

    async def on_error(
        self,
        *,
        session_id: str,
        category: str,
        description: str,
        severity: str = "warning",
        confidence: float | None = None,
    ) -> tuple[ManagerFeedback | None, str | None]:
        """Error hook — archetype update + guardrail scan + optional feedback.

        Returns ``(feedback, narrative_id)``. Order preserves donor semantics:
        the archetype-hit path takes precedence; if the archetype has not yet
        hit threshold, the guardrail path fires.
        """

        # 1. Record the event; archetype counter increments.
        try:
            self.archetypes.record_event(category, description, severity)
        except Exception:  # noqa: BLE001
            log.exception("tektos.manager: archetype record_event failed")

        # 2. Metric: archetype_frequency (per-category running count).
        arche = self.archetypes.get_archetype(category)
        if arche is not None:
            self._score(
                "archetype_frequency",
                float(arche.occurrence_count),
                attributes={"session_id": session_id, "category": category},
            )

        # 3. Archetype-hit path.
        if self.archetypes.should_create_structure(category):
            feedback = self._generate_archetype_feedback(session_id, category)
            if feedback is not None:
                narrative_id = await self._persist(feedback, confidence=confidence)
                await self._publish_archetype(feedback, narrative_id)
                return feedback, narrative_id

        # 4. Guardrail path (routed through ImmunePort when bound).
        guardrail_hit = await self._scan_guardrails(session_id, category, description)
        if guardrail_hit is not None:
            feedback, source, detector_hits = guardrail_hit
            narrative_id = await self._persist(feedback, confidence=confidence)
            await self._publish_guardrail(feedback, source, detector_hits, narrative_id)
            return feedback, narrative_id

        return None, None

    async def on_spiral_update(
        self,
        *,
        session_id: str,
        new_radius: float,
        description: str,
        confidence: float | None = None,
    ) -> tuple[ManagerFeedback | None, str | None]:
        """Spiral update — warn on expansion (donor semantics verbatim)."""

        old_radius = self._spiral_radius
        self._spiral_radius = new_radius
        self._score(
            "spiral_radius",
            new_radius,
            attributes={"session_id": session_id},
        )
        if new_radius > old_radius:
            feedback = ManagerFeedback(
                type="spiral_warning",
                severity="warning",
                what="Spiraling out detected",
                where="manager spiral tracker",
                why=(
                    f"Spiral radius increased from {old_radius:.2f} to {new_radius:.2f}"
                ),
                how=(
                    "Reduce scope, converge toward S5 identity, validate before expanding"
                ),
                what_happened=(
                    f"Spiral radius increased from {old_radius:.2f} to {new_radius:.2f}"
                ),
                what_should_happen=(
                    "Spiral radius should decrease toward center (S5 identity)"
                ),
                try_this=description or "Reduce scope, validate convergence, then expand again",
                session_id=session_id,
                category="spiral_expansion",
            )
            narrative_id = await self._persist(feedback, confidence=confidence)
            await self._publish_feedback(feedback, narrative_id)
            return feedback, narrative_id
        return None, None

    def on_rhythm_event(
        self,
        *,
        session_id: str,
        rhythm_name: str,
        description: str,
    ) -> ManagerFeedback:
        """Rhythm event — synchronous per donor parity.

        Rhythm scheduler itself is deferred to Stage 8.7+ per ADR-108 D9; at
        8.6 this method is a passive feedback generator only.
        """

        return ManagerFeedback(
            type="rhythm_triggered",
            severity="info",
            what=f"Rhythm '{rhythm_name}' triggered",
            where="manager scheduler",
            why=description,
            how=f"Execute {rhythm_name} cycle tasks",
            what_happened=(
                f"Rhythm '{rhythm_name}' triggered per biological schedule"
            ),
            what_should_happen=f"Execute {rhythm_name} cycle tasks",
            try_this=description,
            session_id=session_id,
            category=f"rhythm.{rhythm_name}",
        )

    # ── Query surfaces ─────────────────────────────────────────────────────

    def get_health_report(self) -> ManagerHealthReport:
        """Snapshot manager health (mirrors donor ``get_health_report``)."""

        active = self.archetypes.get_active_archetypes()
        return ManagerHealthReport(
            state=self._state,
            spiral_radius=self._spiral_radius,
            active_archetypes=tuple(
                (a.category, a.occurrence_count, a.threshold) for a in active
            ),
            feedback_total=len(self._buffer),
        )

    def list_recent(self, limit: int = 10) -> tuple[ManagerFeedback, ...]:
        if limit <= 0:
            return ()
        return tuple(list(self._buffer)[-limit:])

    def classify_recovery(self, category: str) -> RecoveryStrategy:
        """Pass-through to the module-level pure classifier (D9)."""

        return classify_recovery(category)

    def check_metric_threshold(
        self, name: str, value: float
    ) -> Literal["warning", "critical"] | None:
        """Pass-through to the module-level pure threshold checker."""

        return _check_threshold(name, value)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _generate_archetype_feedback(
        self, session_id: str, category: str
    ) -> ManagerFeedback | None:
        archetype = self.archetypes.get_archetype(category)
        if archetype is None:
            return None
        count = archetype.occurrence_count
        return ManagerFeedback(
            type="archetype_recognized",
            severity="warning",
            what=(
                f"Archetype '{category}' hit threshold ({count} occurrences)"
            ),
            where="event store",
            why=(
                f"Repeated pattern '{category}' detected — time to encode as "
                "permanent skill or tool"
            ),
            how=(
                f"Create permanent skill or tool '{category}' to handle this pattern"
            ),
            what_happened=(
                f"Error pattern '{category}' has occurred {count} times"
            ),
            what_should_happen=(
                "A permanent skill or tool should handle this pattern"
            ),
            try_this=(
                f"Create a permanent skill for '{category}' to prevent future occurrences"
            ),
            session_id=session_id,
            category=category,
        )

    async def _scan_guardrails(
        self, session_id: str, category: str, description: str
    ) -> tuple[ManagerFeedback, Literal["immune", "fallback_keyword"], tuple[Any, ...]] | None:
        """Scan through :class:`ImmunePort` when bound; fall back otherwise."""

        # ImmunePort path.
        if self.is_immune_bound:
            try:
                # Import structural shapes lazily to keep ADR-007 imports clean:
                # ports.immune is a formal port so a direct import is allowed.
                from ports.immune import ImmuneScanRequest  # local import — port-only

                verdict = await self._immune.scan(  # type: ignore[union-attr]
                    ImmuneScanRequest(
                        payload={
                            "category": category,
                            "description": description,
                            "session_id": session_id,
                        },
                        kind="tektos.manager.guardrail",
                        source_plugin="tektos.manager",
                    )
                )
                if getattr(verdict, "decision", "allow") in ("warn", "block"):
                    hits = tuple(getattr(verdict, "detector_hits", ()) or ())
                    guardrail = self._infer_guardrail_from_hits(
                        hits, category=category, description=description
                    )
                    feedback = self._build_guardrail_feedback(
                        session_id=session_id,
                        category=category,
                        guardrail=guardrail,
                        reason=getattr(verdict, "reason", "immune verdict") or "immune verdict",
                    )
                    return feedback, "immune", hits
                return None
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.manager: ImmunePort.scan failed; "
                    "falling back to keyword scan (ADR-108 D9)"
                )
                # fall through to keyword scan

        # Fallback keyword scan (donor semantics preserved).
        hit = _fallback_guardrail_scan(category, description)
        if hit is None:
            return None
        guardrail, reason = hit
        feedback = self._build_guardrail_feedback(
            session_id=session_id,
            category=category,
            guardrail=guardrail,
            reason=reason,
        )
        return feedback, "fallback_keyword", ()

    def _infer_guardrail_from_hits(
        self,
        hits: tuple[Any, ...],
        *,
        category: str,
        description: str,
    ) -> Guardrail:
        """Map ImmunePort detector hits to a :class:`Guardrail` enum value.

        Best-effort: uses the first hit's ``detector_name`` as a keyword
        against the same donor secret/compute keyword sets before falling
        back to :class:`Guardrail.RE_DIRECTION_OVER_PUNISHMENT`.
        """

        for hit in hits:
            name = str(getattr(hit, "detector_name", "")).lower()
            if any(kw in name for kw in _SECRET_KEYWORDS):
                return Guardrail.NO_HARD_CODED_SECRETS
            if any(kw in name for kw in _COMPUTE_KEYWORDS):
                return Guardrail.LLM_MUST_NOT_COMPUTE
            if "sandbox" in name:
                return Guardrail.SANDBOX_ISOLATION
            if "redact" in name or "leak" in name:
                return Guardrail.REDACTION_POLICY
        # Same fallback keyword scan against the raw category+description.
        fallback = _fallback_guardrail_scan(category, description)
        if fallback is not None:
            return fallback[0]
        return Guardrail.RE_DIRECTION_OVER_PUNISHMENT

    def _build_guardrail_feedback(
        self,
        *,
        session_id: str,
        category: str,
        guardrail: Guardrail,
        reason: str,
    ) -> ManagerFeedback:
        meta = GUARDRAIL_RULES.get(guardrail, {})
        description = str(meta.get("description", guardrail.value))
        enforcement = str(meta.get("enforcement", "Manager enforcement"))
        return ManagerFeedback(
            type="guardrail_triggered",
            severity="critical",
            what=f"Guardrail '{guardrail.value}' triggered",
            where="tektos.manager",
            why=reason,
            how=enforcement,
            what_happened=f"Guardrail '{guardrail.value}' triggered on category '{category}'",
            what_should_happen=description,
            try_this=enforcement,
            session_id=session_id,
            category=category,
        )

    async def _persist(
        self,
        feedback: ManagerFeedback,
        *,
        confidence: float | None,
    ) -> str | None:
        """Ring-buffer + optional ``RelationalMemoryPort.write_narrative``."""

        # Enforce the max feedback body length by clipping the derived body
        # AFTER truncating oversized string fields (donor parity).
        if len(feedback.what) > self._max_feedback_length:
            feedback = replace(feedback, what=feedback.what[: self._max_feedback_length])
        self._buffer.append(feedback)

        if self._relational_memory is None:
            return None

        eff_conf = (
            float(confidence) if confidence is not None else TEKTOS_MANAGER_DEFAULT_CONFIDENCE
        )
        try:
            return await self._relational_memory.write_narrative(
                session_id=feedback.session_id,
                agent_id=TEKTOS_MANAGER_PROVENANCE,
                title=f"{TEKTOS_MANAGER_PREDICATE}:{feedback.id}",
                body=json.dumps(_feedback_to_body(feedback), default=str),
                tags=(
                    TEKTOS_MANAGER_PROVENANCE,
                    feedback.category or "unknown",
                    feedback.severity,
                ),
                embedding=None,
                confidence=eff_conf,
                provenance=TEKTOS_MANAGER_PROVENANCE,
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.manager: write_narrative failed; ring-buffer only "
                "(ADR-108 D9 fail-open)"
            )
            return None

    async def _publish_feedback(
        self, feedback: ManagerFeedback, narrative_id: str | None
    ) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(
                EventEnvelope(
                    event_type=TEKTOS_MANAGER_PREDICATE,
                    producer_plugin=TEKTOS_MANAGER_PROVENANCE,
                    payload={
                        "session_id": feedback.session_id,
                        "feedback_id": feedback.id,
                        "feedback_type": feedback.type,
                        "severity": feedback.severity,
                        "narrative_id": narrative_id,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.manager: EventBus publish feedback_generated failed (fail-open)"
            )

    async def _publish_archetype(
        self, feedback: ManagerFeedback, narrative_id: str | None
    ) -> None:
        # feedback_generated fires for every persisted feedback…
        await self._publish_feedback(feedback, narrative_id)
        if self._event_bus is None:
            return
        arche = self.archetypes.get_archetype(feedback.category)
        try:
            await self._event_bus.publish(
                EventEnvelope(
                    event_type=TEKTOS_MANAGER_EVENT_ARCHETYPE,
                    producer_plugin=TEKTOS_MANAGER_PROVENANCE,
                    payload={
                        "session_id": feedback.session_id,
                        "category": feedback.category,
                        "occurrence_count": (
                            arche.occurrence_count if arche is not None else 0
                        ),
                        "threshold": arche.threshold if arche is not None else 0,
                        "feedback_id": feedback.id,
                        "narrative_id": narrative_id,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.manager: EventBus publish archetype_recognized failed (fail-open)"
            )

    async def _publish_guardrail(
        self,
        feedback: ManagerFeedback,
        source: Literal["immune", "fallback_keyword"],
        detector_hits: tuple[Any, ...],
        narrative_id: str | None,
    ) -> None:
        await self._publish_feedback(feedback, narrative_id)
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(
                EventEnvelope(
                    event_type=TEKTOS_MANAGER_EVENT_GUARDRAIL,
                    producer_plugin=TEKTOS_MANAGER_PROVENANCE,
                    payload={
                        "session_id": feedback.session_id,
                        "guardrail_source": source,
                        "detector_hits": tuple(
                            str(getattr(h, "detector_name", "")) for h in detector_hits
                        ),
                        "feedback_id": feedback.id,
                        "narrative_id": narrative_id,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.manager: EventBus publish guardrail_triggered failed (fail-open)"
            )

    def _score(
        self, name: str, value: float, *, attributes: dict[str, Any] | None = None
    ) -> None:
        """Best-effort observability metric emit."""

        if self._observability is None:
            return
        try:
            self._observability.score(
                f"plugin.tektos.manager.{name}", float(value), attributes=attributes
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.manager: ObservabilityPort.score failed for %s (fail-open)", name
            )


__all__ = [
    "TektosManager",
    "classify_recovery",
]
