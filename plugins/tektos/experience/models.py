"""Frozen slotted dataclass for the Tektos experience-replay engine.

Preserves the shape of the donor's ``ExperienceRecord`` pydantic model
(see ``tektos-ultima/src/tektos/memory/experience_replay.py``). The
donor's ``LanguageGame`` enum on ``context`` lands at Stage 8.4 (per
ADR-105 D9); at 8.3 ``context`` is a plain ``str``.

ADR-007: no imports from other plugins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _new_exp_id() -> str:
    return f"exp-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    """A single piece of experience: what happened + what to do differently.

    ``cycle_id`` links back to the ``SynthesisResult.spec_id`` that
    produced this experience — the planner uses this to trace guidance
    back to the originating synthesis cycle.
    """

    id: str = field(default_factory=_new_exp_id)
    cycle_id: str = ""
    insight_type: str = "synthesis"
    what_happened: str = ""
    what_was_expected: str = ""
    guidance: str = ""
    context: str = ""
    confidence: float = 0.5
    priority: str = "normal"
    timestamp: str = field(default_factory=_now_iso)
    tags: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        """One-line summary for planner context (donor parity)."""
        return f"[{self.insight_type}] {self.guidance[:120]}"


__all__ = ["ExperienceRecord"]
