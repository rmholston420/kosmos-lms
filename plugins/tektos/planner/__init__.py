"""plugins.tektos.planner — Tektos planners.

Two engines share this package:

- **Stage 4.7 seed** (ADR-093): ``TektosTurnPlanner``, ``Plan``, ``PlanNode``,
  ``PlanNodeKind`` — scripted turn planner, unchanged.
- **Stage 8.4 spec-planner** (ADR-106): ``TektosSpecPlanner`` — Kosmos-native
  rewrite of the donor ``Planner`` orchestrator that composes language-game
  detection, disambiguation, translation, template selection, and spec
  generation, persisting through ``RelationalMemoryPort.write_narrative``.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

# Locked constants (ADR-106 D4) — declared before submodule imports so
# spec_planner.py can import them from the package root.
TEKTOS_SPEC_PLANNER_PROVENANCE: str = "tektos.planner"
"""Locked provenance."""

TEKTOS_SPEC_PLANNER_PREDICATE: str = "tektos.planner.spec_generated"
"""Locked event kind + narrative title prefix."""

TEKTOS_SPEC_PLANNER_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036, mirrors ADR-105)."""

from plugins.tektos.planner.spec_models import (  # noqa: E402
    Ambiguity,
    AmbiguityResolution,
    ArchitectureChoice,
    ArchitectureTemplate,
    BuildSpec,
    ClarifyingQuestion,
    LanguageGame,
    PlannerOutput,
    SpecPhase,
    W5H1M,
)
from plugins.tektos.planner.spec_planner import TektosSpecPlanner  # noqa: E402
from plugins.tektos.planner.turn_planner import (  # noqa: E402
    Plan,
    PlanNode,
    PlanNodeKind,
    TektosTurnPlanner,
)

__all__ = [
    # Stage 8.4 (ADR-106)
    "TEKTOS_SPEC_PLANNER_DEFAULT_CONFIDENCE",
    "TEKTOS_SPEC_PLANNER_PREDICATE",
    "TEKTOS_SPEC_PLANNER_PROVENANCE",
    "TektosSpecPlanner",
    # Stage 8.4 models
    "Ambiguity",
    "AmbiguityResolution",
    "ArchitectureChoice",
    "ArchitectureTemplate",
    "BuildSpec",
    "ClarifyingQuestion",
    "LanguageGame",
    "PlannerOutput",
    "SpecPhase",
    "W5H1M",
    # Stage 4.7 seed (ADR-093)
    "Plan",
    "PlanNode",
    "PlanNodeKind",
    "TektosTurnPlanner",
]
