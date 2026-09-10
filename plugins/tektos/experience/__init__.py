"""Tektos Experience Replay (Stage 8.3 · ADR-105).

Synthesis-to-Planner Wiring — the missing link in Tektos'
self-improvement loop. Kosmos-native rewrite of
``tektos-ultima/src/tektos/memory/experience_replay.py`` that persists
via ``RelationalMemoryPort.write_narrative`` and recalls via
``RelationalMemoryPort.search_narratives`` (ADR-102 §D3), replacing the
donor's in-memory ``_records`` list with the port-backed ledger.

Domain intent (preserved verbatim from the donor's module docstring):

    The missing link in Tektos' self-improvement loop:
    1. SynthesisEngine produces SynthesisFeedback from execution reality
    2. ExperienceReplay stores these as structured experience memories
    3. When the Planner generates a new spec, ExperienceReplay provides
       relevant past syntheses as guidance
    4. The spec carries synthesis_guidance in its metadata
    5. The Coding Agent sees "here's what went wrong last time — don't
       repeat it"

    This is where the Hegelian spiral becomes operational:
    - Thesis: Planner's spec
    - Antithesis: Execution reality
    - Synthesis: What we learned
    - New Thesis: Planner's spec, informed by what we learned

    The spiral staircase.

At Stage 8.3 ``context`` is a plain ``str`` — the ``LanguageGame`` enum
lands at Stage 8.4 with the planner (per ADR-105 D9).

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

TEKTOS_EXPERIENCE_PROVENANCE: str = "tektos.experience"
"""Locked provenance."""

TEKTOS_EXPERIENCE_PREDICATE: str = "tektos.experience.recorded"
"""Locked event kind + narrative title prefix."""

TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036)."""

from .models import ExperienceRecord  # noqa: E402
from .replay import ExperienceReplay  # noqa: E402

__all__ = [
    "ExperienceRecord",
    "ExperienceReplay",
    "TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE",
    "TEKTOS_EXPERIENCE_PREDICATE",
    "TEKTOS_EXPERIENCE_PROVENANCE",
]
