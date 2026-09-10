"""Frozen slotted dataclasses for the Tektos synthesis engine.

Preserves the shape of the donor's ``SynthesisFeedback`` pydantic model
(see ``tektos-ultima/src/tektos/memory/synthesis_engine.py``) as a
Kosmos-owned frozen slotted dataclass. Renamed to ``SynthesisResult``
to match the runtime-tier donor's terminology (chosen for clarity; the
donor project uses both names interchangeably across tiers).

ADR-007: no imports from other plugins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _new_synth_id() -> str:
    return f"synth-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """The third state that emerges from thesis (spec) + antithesis (execution).

    Preserves the donor's Hegelian-dialectic semantics:

    - ``what_happened`` — the antithesis (execution reality).
    - ``what_was_expected`` — the thesis (what the spec predicted).
    - ``synthesis`` — the new state (what to do differently next time).
    - ``lessons`` / ``recommendations`` — structured extraction from the
      free-form synthesis text, used by
      ``ExperienceReplay.get_planner_guidance`` to build Stage 8.4
      planner spec metadata.
    """

    id: str = field(default_factory=_new_synth_id)
    spec_id: str = ""
    source: str = "reflection_engine"
    insight_type: str = "synthesis"
    what_happened: str = ""
    what_was_expected: str = ""
    synthesis: str = ""
    lessons: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    is_actionable: bool = True
    priority: str = "normal"
    confidence: float = 0.5
    timestamp: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["SynthesisResult"]
