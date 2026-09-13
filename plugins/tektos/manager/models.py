"""plugins.tektos.manager.models — frozen slotted dataclasses.

Rewrite of donor ``tektos-ultima/src/tektos/agents/manager/models.py`` per
ADR-108 D2. Pydantic ``BaseModel`` → ``@dataclass(frozen=True, slots=True)``;
enums as ``Literal`` unions matching ADR-105/106/107 shape. The donor's
W5H1M metadata (who / what / where / when / why / how) is preserved verbatim
on ``ManagerFeedback`` alongside the ``_M`` extension
(``what_happened`` / ``what_should_happen`` / ``try_this``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# ── Enums (Literal unions per ADR-105/106/107 pattern) ─────────────────────

FeedbackType = Literal[
    "redirection",
    "archetype_recognized",
    "guardrail_triggered",
    "rhythm_triggered",
    "spiral_warning",
    "skill_creation",
    "coordination",
]
"""Kind of manager feedback (donor ``FeedbackType`` enum, ADR-108 D2)."""

FeedbackSeverity = Literal["info", "warning", "critical"]
"""Feedback severity (donor ``FeedbackSeverity`` enum)."""

ManagerState = Literal["idle", "active", "responding", "escalating"]
"""Manager state (donor ``ManagerState`` enum). Kept lowercase-string for
JSON stability; donor's enum ``.value`` was already lowercase."""

SpiralDirection = Literal["converging", "expanding", "stable"]
"""Spiral direction (donor ``SpiralDirection`` enum)."""

RecoveryStrategy = Literal["retry", "alternative_tool", "skip", "escalate"]
"""Recovery-strategy classification (ADR-108 D9 → discharges ADR-107 D9
point 1). The classifier surface lives on the engine at 8.6; the actual
retry / alternative / skip execution loop stays in Stage 8.7's
multi-agent orchestrator."""


# ── Frozen slotted dataclasses ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ManagerFeedback:
    """S3 Manager feedback message with W5H1M metadata (donor ``ManagerFeedback``).

    The re-direction pattern (donor doc verbatim):

        "Here's what happened. Here's what should happen. Here's why.
         Try this."

    Kosmos convention: frozen + slotted; every downstream mutation produces
    a new record (see engine helpers).
    """

    type: FeedbackType
    severity: FeedbackSeverity
    # W5H1M metadata (donor W5 + How + Manager-extension _M):
    what: str
    where: str
    why: str
    how: str
    what_happened: str
    what_should_happen: str
    try_this: str
    who: str = "S3 Manager"
    # Optional context payloads. Kept as ``str`` to preserve JSON-stability
    # of the ``body`` field written through ``RelationalMemoryPort``.
    session_id: str = ""
    category: str = ""
    id: str = field(default_factory=lambda: f"mgr-fb-{uuid.uuid4().hex[:8]}")
    when: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class ArchetypeEvent:
    """A single event occurrence in an archetype (donor ``ArchetypeEvent``).

    An event is any lifecycle occurrence the Manager wants to track: an
    error, a delegation, a decision, a synthesis. Events accumulate into
    Archetypes, and Archetypes hitting threshold trigger feedback.
    """

    category: str
    description: str
    severity: str = "info"
    id: str = field(default_factory=lambda: f"arch-evt-{uuid.uuid4().hex[:8]}")
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class Archetype:
    """A recurring pattern tracked by the Manager (donor ``Archetype``).

    When an archetype's ``occurrence_count`` reaches its ``threshold``, the
    Manager emits an ``archetype_recognized`` feedback recommending the
    caller encode this pattern as a permanent skill or tool. Actual skill
    creation is deferred to a future skill-registry stage per ADR-108 D9;
    ``permanent_structure_id`` stays ``None`` until then.
    """

    category: str
    occurrence_count: int
    threshold: int
    events: tuple[ArchetypeEvent, ...] = ()
    permanent_structure_id: str | None = None
    id: str = field(default_factory=lambda: f"arch-{uuid.uuid4().hex[:8]}")
    first_seen: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_seen: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class MetricThreshold:
    """Warning/critical thresholds for a manager metric (donor ``MetricThreshold``).

    ``direction`` is either ``"above"`` (donor ``higher_is_better`` — values
    at or **below** the threshold are bad, e.g. tool-success ratio) or
    ``"below"`` (donor ``lower_is_better`` — values at or **above** the
    threshold are bad, e.g. error_rate, latency). Donor branch semantics
    preserved verbatim in :func:`plugins.tektos.manager.engine._check_threshold`.
    """

    warning: float
    critical: float
    direction: Literal["above", "below"] = "above"


@dataclass(frozen=True, slots=True)
class ManagerHealthReport:
    """Health snapshot returned by ``TektosManager.get_health_report``.

    Includes the manager state, current spiral radius, active archetype
    counts, and a rolling feedback total. The donor emitted a plain dict;
    Kosmos wraps it in a typed value object per port hygiene.
    """

    state: ManagerState
    spiral_radius: float
    active_archetypes: tuple[tuple[str, int, int], ...]  # (category, count, threshold)
    feedback_total: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


__all__ = [
    "Archetype",
    "ArchetypeEvent",
    "FeedbackSeverity",
    "FeedbackType",
    "ManagerFeedback",
    "ManagerHealthReport",
    "ManagerState",
    "MetricThreshold",
    "RecoveryStrategy",
    "SpiralDirection",
]
