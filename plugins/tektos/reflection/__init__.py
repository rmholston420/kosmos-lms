"""Tektos Reflection Engine (Stage 8.3 · ADR-105).

Active Contemplation / Meditative Reflection Engine — a Kosmos-native
rewrite of the ``tektos-ultima/src/tektos/memory/reflection_engine.py``
semantics that preserves the rule-based analytic logic and the yogic
domain-language of the donor without dragging in ``MemorySystem``,
``DreamtimeEngine``, ``Hemisphere``, or ``MemoryEntry`` (which land at
Stage 13 per ADR-105 D9).

Domain intent (preserved verbatim from the donor's module docstring):

    Contemplation/meditation is the active, deliberate version of
    dreamtime. The system consciously turns attention inward to examine
    patterns, biases, and failure modes. It is triggered intentionally —
    after complex tasks, before major decisions, when execution has
    produced direct experience.

    As the Yogi knows: direct experience is more trustworthy than any
    other means of knowledge. The operative hemisphere (S1) that actually
    executes generates truth. The speculative hemisphere (S4) that plans
    generates hypotheses. The Manager (S3) weighs both.

At Stage 8.3 the "hemisphere" of a memory entry is not modelled; the
engine reasons over Stage 8.2 ``TurnOutcome`` shapes directly. When
Stage 13 lands ``MemorySystem`` + ``Hemisphere``, this engine grows an
optional richer input path (per ADR-105 D9).

ADR-007: this module imports only from ``ports.*`` and its own
``plugins.tektos.reflection`` subpackage. It MUST NOT import any other
plugin.
"""

from __future__ import annotations

TEKTOS_REFLECTION_PROVENANCE: str = "tektos.reflection"
"""Locked provenance for every ``RelationalMemoryPort`` write from this
engine. Mirrors ADR-036 §Tektos and ADR-052 §Zetesis patterns.
"""

TEKTOS_REFLECTION_PREDICATE: str = "tektos.reflection.completed"
"""Locked ``EventBusPort`` event kind + narrative title prefix."""

TEKTOS_REFLECTION_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036). Replaced by
actor-evaluator-derived confidence when Reflexion lands at Stage 5.X
per ADR-039.
"""

from .engine import ReflectionEngine  # noqa: E402 — defined after constants to break cycle
from .models import ReflectionInsight, ReflectionState  # noqa: E402

__all__ = [
    "ReflectionEngine",
    "ReflectionInsight",
    "ReflectionState",
    "TEKTOS_REFLECTION_DEFAULT_CONFIDENCE",
    "TEKTOS_REFLECTION_PREDICATE",
    "TEKTOS_REFLECTION_PROVENANCE",
]
