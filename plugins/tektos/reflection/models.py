"""Frozen slotted dataclasses for the Tektos reflection engine.

Preserves the shape of the donor's ``ReflectionInsight`` and
``ReflectionState`` pydantic models (see
``tektos-ultima/src/tektos/memory/reflection_engine.py``) as Kosmos-owned
frozen slotted dataclasses. Fields dropped at Stage 8.3 (per ADR-105 D2):

- ``hemisphere`` — depended on donor's ``MemoryEntry.hemisphere``
  (Stage 13 concern).
- ``who/what/where/when/why/how`` W5H1M rubric — preserved as free-form
  ``metadata`` keys when callers want them; not enforced at the dataclass
  level to keep the surface minimal at 8.3.

ADR-007: no imports from other plugins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _new_insight_id() -> str:
    return f"refl-{uuid.uuid4().hex[:8]}"


def _new_session_id() -> str:
    return f"reflsession-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ReflectionInsight:
    """A single insight generated during active reflection.

    Preserves the donor's semantics: ``is_direct_experience`` +
    ``trust_score`` capture the yogic "direct experience > inference"
    principle. ``bias_detected`` + ``correction`` capture the corrective
    channel that feeds ``SynthesisEngine`` at Stage 8.3. ``is_novel`` +
    ``novelty_score`` capture McKenna's "generation of novelty" concept.
    """

    id: str = field(default_factory=_new_insight_id)
    source: str = ""
    content: str = ""
    is_direct_experience: bool = False
    trust_score: float = 0.5
    bias_detected: str | None = None
    correction: str | None = None
    is_novel: bool = False
    novelty_score: float = 0.0
    insight_type: str = "reflection"
    timestamp: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReflectionState:
    """State of a completed active-reflection session.

    Frozen — sessions are constructed once by
    ``ReflectionEngine.reflect_on_turn`` (or its session-level sibling)
    and never mutated. Counters are aggregates computed at construction.
    """

    id: str = field(default_factory=_new_session_id)
    started_at: str = field(default_factory=_now_iso)
    ended_at: str | None = None
    focus: str | None = None
    is_novelty_focused: bool = False
    memories_examined: int = 0
    insights_generated: int = 0
    biases_detected: int = 0
    direct_experience_entries: int = 0
    inference_entries: int = 0
    trust_ratio: float = 0.0
    insights: tuple[ReflectionInsight, ...] = ()


__all__ = ["ReflectionInsight", "ReflectionState"]
