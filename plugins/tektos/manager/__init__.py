"""plugins.tektos.manager — Tektos S3 Manager (Stage 8.6 · ADR-108).

Single-engine package landing the Tektos S3 Manager (VSM System 3 — variety
regulator + guardrail enforcer). One engine (``TektosManager``) orchestrates
lifecycle hooks (task-start / task-complete / error / spiral-update / rhythm)
and health reporting, consuming four optional port collaborators:

* ``RelationalMemoryPort.write_narrative`` (ADR-102) — persistence sink.
* ``EventBusPort.publish`` (ADR-023 envelope-first) — three new event types.
* ``ImmunePort.scan`` (ADR-079) — guardrail scanning (donor regex kept
  ONLY as a fallback keyword scan when the port is unbound, per ADR-108 D9).
* ``ObservabilityPort.score`` (ADR-025) — metric recording (replaces donor
  in-process ``PrimeMoverMetrics.samples`` accumulator per ADR-108 R2).

Donor ``agents/manager/telemetry.py`` (601 LOC RTX 5090 pynvml + Unix-socket
fan controller) REJECTED at 8.6 per ADR-108 R1; ``ThermalPort`` (ADR-081)
owns the RTX 5090 threshold table verbatim.

ADR-007: this module imports only from ``ports.*`` and its own subpackage.
"""

from __future__ import annotations

# Locked constants (ADR-108 D4) ────────────────────────────────────────────
# Single source of truth. Every write / publish call reads from HERE.

TEKTOS_MANAGER_PROVENANCE: str = "tektos.manager"
"""Locked ``MemoryPort``/``RelationalMemoryPort`` provenance (ADR-008)."""

TEKTOS_MANAGER_PREDICATE: str = "tektos.manager.feedback_generated"
"""Locked event kind + narrative title prefix (ADR-023)."""

TEKTOS_MANAGER_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036 · mirrors ADR-105/106/107)."""

# Locked ancillary event kinds (ADR-108 D7) — envelope-first per ADR-023.
TEKTOS_MANAGER_EVENT_ARCHETYPE: str = "tektos.manager.archetype_recognized"
TEKTOS_MANAGER_EVENT_GUARDRAIL: str = "tektos.manager.guardrail_triggered"


from .models import (  # noqa: E402
    Archetype,
    ArchetypeEvent,
    FeedbackSeverity,
    FeedbackType,
    ManagerFeedback,
    ManagerHealthReport,
    ManagerState,
    MetricThreshold,
    RecoveryStrategy,
    SpiralDirection,
)
from .guardrails import GUARDRAIL_RULES, Guardrail, GuardrailLevel  # noqa: E402
from .archetype_tracker import ArchetypeTracker  # noqa: E402
from .engine import TektosManager  # noqa: E402

__all__ = [
    "GUARDRAIL_RULES",
    "TEKTOS_MANAGER_DEFAULT_CONFIDENCE",
    "TEKTOS_MANAGER_EVENT_ARCHETYPE",
    "TEKTOS_MANAGER_EVENT_GUARDRAIL",
    "TEKTOS_MANAGER_PREDICATE",
    "TEKTOS_MANAGER_PROVENANCE",
    "Archetype",
    "ArchetypeEvent",
    "ArchetypeTracker",
    "FeedbackSeverity",
    "FeedbackType",
    "Guardrail",
    "GuardrailLevel",
    "ManagerFeedback",
    "ManagerHealthReport",
    "ManagerState",
    "MetricThreshold",
    "RecoveryStrategy",
    "SpiralDirection",
    "TektosManager",
]
