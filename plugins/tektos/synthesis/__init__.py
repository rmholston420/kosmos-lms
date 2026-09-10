"""Tektos Synthesis Engine (Stage 8.3 · ADR-105).

Reflection-to-Planner Feedback — the Synthesis Channel. Kosmos-native
rewrite of ``tektos-ultima/src/tektos/memory/synthesis_engine.py`` that
preserves the Hegelian-dialectic domain intent without dragging in the
donor's ``MemorySystem`` coupling (deferred to Stage 13 per ADR-105 D9).

Domain intent (preserved verbatim from the donor's module docstring):

    The Hegelian dialectic in action:
    - Thesis (S4 Planner): Generates a spec/plan/hypothesis
    - Antithesis (S1 Coding Agent): Executes the spec, produces reality
    - Synthesis (ReflectionEngine → Planner): The insight that changes
      future planning

    The synthesis is NOT a compromise between plan and execution. It is
    something genuinely new — a third state that neither the spec nor
    the execution alone could produce. This is where the system actually
    learns.

    As McKenna said: creativity is the generation of novelty. The
    synthesis is the novelty that emerges from the tension between
    thesis and antithesis.

ADR-007: this module imports only from ``ports.*`` and its own
``plugins.tektos.synthesis`` subpackage. It MUST NOT import any other
plugin — including the sibling ``plugins.tektos.reflection`` subpackage
(which lives under the same plugin namespace but is treated as an
independent capability for cross-plugin discipline).
"""

from __future__ import annotations

TEKTOS_SYNTHESIS_PROVENANCE: str = "tektos.synthesis"
"""Locked provenance for every ``RelationalMemoryPort`` write."""

TEKTOS_SYNTHESIS_PREDICATE: str = "tektos.synthesis.completed"
"""Locked ``EventBusPort`` event kind + narrative title prefix."""

TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036)."""

from .engine import SynthesisEngine  # noqa: E402
from .models import SynthesisResult  # noqa: E402

__all__ = [
    "SynthesisEngine",
    "SynthesisResult",
    "TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE",
    "TEKTOS_SYNTHESIS_PREDICATE",
    "TEKTOS_SYNTHESIS_PROVENANCE",
]
