"""Dreamtime / contemplation engine — Tektos cognitive family (ADR-141 T8c-8a).

Donor provenance: tektos-ultima-v1 ``src/tektos/memory/memory_system.py`` —
``MemoryTier`` (77), ``Hemisphere`` (86), ``MemoryEntry`` (96), ``DreamState``
(692), ``DreamResult`` (702), ``DreamtimeEngine`` (735-993) ported VERBATIM
(engine + models byte-for-byte; only the ``self.memory.*`` call surface
changed — see the adapter below).

Layering decision (user's governing rule, ADR-142/143 precedent): dreamtime
is the Tektos coding agent's own idle contemplation — its cognitive family —
so it lands beside T6's ``plugins/tektos/memory/persistence.py``, NOT in
``kernel/``. ADR-007: the engine is booted by the composition root via DI
(T8c-8b) and never imports the persistence module itself.

Adapter (documented divergence): the donor engine consumed the donor
``MemorySystem`` object API (``get_recent_long_term`` /
``get_procedural_memories`` / ``add_long_term_memory`` /
``add_procedural_memory``, ``MemoryEntry`` objects). The kernel's T6 store
(``MemoryPersistence``, ``registry.tektos_memory_persistence``) is
dict-based. ``DictMemoryStore`` below implements EXACTLY those four donor
methods on top of the T6 store — the engine body stays verbatim, and the
engine's ``self.memory`` is injected. Engine logic, state machine, insight
strategies, and novelty scoring are untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── Donor-verbatim models (memory_system.py) ──────────────────────────────


class MemoryTier(str, Enum):
    """The four memory tiers, ordered by persistence."""

    SENSORY = "sensory"  # 100ms - 4s
    WORKING = "working"  # seconds - minutes
    LONG_TERM = "long_term"  # days - permanent
    PROCEDURAL = "procedural"  # permanent (skills, wisdom)


class Hemisphere(str, Enum):
    """Bicameral hemisphere — left vs right brain."""

    LEFT = "left"  # Operative, logical, sequential, language
    RIGHT = "right"  # Speculative, holistic, contextual, spatial


class MemoryEntry(BaseModel):
    """A single memory entry carrying W5H1M metadata."""

    id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:8]}")
    content: str = Field(..., description="The memory content")
    tier: MemoryTier = Field(..., description="Which memory tier this belongs to")
    hemisphere: Hemisphere = Field(
        default=Hemisphere.LEFT,
        description="Which hemisphere generated this memory (left=operative, right=speculative)",
    )
    is_novel: bool = Field(
        default=False,
        description="Is this a genuine novelty (not recombination of existing patterns)?",
    )
    novelty_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="How novel is this entry? 0 = purely recombined, 1 = pure novelty",
    )
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str | None = Field(
        default=None,
        description="When this memory expires/decays (sensory & working only)",
    )
    source_tier: MemoryTier | None = Field(
        default=None,
        description="Which tier this was transferred from (None if created at this tier)",
    )
    destination_tier: MemoryTier | None = Field(
        default=None,
        description="Which tier this was transferred to (None if stays at this tier)",
    )
    # W5H1M metadata
    who: str = Field(default="", description="Who created this memory")
    what: str = Field(default="", description="What event/pattern was encoded")
    where: str = Field(default="", description="Where was this generated")
    when: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="When created"
    )
    why: str = Field(default="", description="Why was this encoded")
    how: str = Field(default="", description="How was this encoded")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DreamState(str, Enum):
    """Dreamtime/contemplation states for right-hemisphere processing."""

    IDLE = "idle"  # Not currently dreaming
    GATHERING = "gathering"  # Collecting memories for processing
    PROCESSING = "processing"  # Right hemisphere cross-pollinating ideas
    INSIGHT_GENERATED = "insight_generated"  # Novel connections discovered
    SAVING = "saving"  # Persisting insights to long-term memory



class DreamResult(BaseModel):
    """A result of dreamtime/contemplation processing."""

    id: str = Field(default_factory=lambda: f"dream-{uuid.uuid4().hex[:8]}")
    source_count: int = Field(..., description="How many memories were processed")
    insight_count: int = Field(..., description="How many novel insights were generated")
    is_novel: bool = Field(default=False, description="Was this genuine novelty?")
    novelty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    insights: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    who: str = Field(
        default="S4 Planner/Thinker (Right Hemisphere)",
        description="W5H1M: Who generated these insights",
    )
    what: str = Field(default="", description="W5H1M: What insights were generated")
    where: str = Field(
        default="right hemisphere (speculative processing)", description="W5H1M: Where generated"
    )
    when: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="W5H1M: When generated",
    )
    why: str = Field(
        default="Cross-pollinate ideas and generate novelty during contemplation",
        description="W5H1M: Why processing",
    )
    how: str = Field(
        default="Right-hemisphere associative processing of long-term memories",
        description="W5H1M: How processed",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Adapter: donor MemorySystem call surface over the T6 dict store ───────


def _dict_to_entry(d: dict[str, Any], tier: MemoryTier) -> MemoryEntry:
    """Map a T6 store row-dict to the donor ``MemoryEntry`` shape."""
    return MemoryEntry(
        id=d.get("id", f"mem-{uuid.uuid4().hex[:8]}"),
        content=d.get("content", ""),
        tier=tier,
        hemisphere=Hemisphere(d.get("hemisphere") or "left"),
        is_novel=bool(d.get("is_novel")),
        novelty_score=float(d.get("novelty_score") or 0.0),
        timestamp=d.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        expires_at=d.get("expires_at"),
        source_tier=MemoryTier(d["source_tier"]) if d.get("source_tier") else None,
        destination_tier=(
            MemoryTier(d["destination_tier"]) if d.get("destination_tier") else None
        ),
        who=d.get("who", ""),
        what=d.get("what", ""),
        where=d.get("where", ""),
        when=d.get("when", ""),
        why=d.get("why", ""),
        how=d.get("how", ""),
        metadata=d.get("metadata") or {},
    )


class DictMemoryStore:
    """Donor ``MemorySystem`` call surface over T6 ``MemoryPersistence``.

    Implements exactly the four methods ``DreamtimeEngine`` touches —
    ``get_recent_long_term``, ``get_procedural_memories``,
    ``add_long_term_memory``, ``add_procedural_memory`` — with donor
    signatures, so the engine ports verbatim.
    """

    def __init__(self, memory_persistence: Any) -> None:
        self._mem = memory_persistence

    def get_recent_long_term(self, limit: int = 20) -> list[MemoryEntry]:
        rows = self._mem.load_long_term(limit=limit)
        return [_dict_to_entry(r, MemoryTier.LONG_TERM) for r in rows]

    def get_procedural_memories(self) -> list[MemoryEntry]:
        rows = self._mem.load_procedural(limit=1000)
        return [_dict_to_entry(r, MemoryTier.PROCEDURAL) for r in rows]

    def add_long_term_memory(
        self,
        content: str,
        hemisphere: Hemisphere = Hemisphere.RIGHT,
        **kwargs: Any,
    ) -> MemoryEntry:
        entry = self._entry_dict(content, hemisphere, **kwargs)
        self._mem.save_long_term(entry)
        return _dict_to_entry(entry, MemoryTier.LONG_TERM)

    def add_procedural_memory(
        self,
        content: str,
        skill_id: str | None = None,
        **kwargs: Any,
    ) -> MemoryEntry:
        # Donor signature has no `hemisphere` param — the engine passes it
        # as a kwarg, so pop it here (donor default: right).
        hemisphere = kwargs.pop("hemisphere", Hemisphere.RIGHT)
        if isinstance(hemisphere, str):
            hemisphere = Hemisphere(hemisphere)
        entry = self._entry_dict(content, hemisphere, **kwargs)
        self._mem.save_procedural(entry)
        return _dict_to_entry(entry, MemoryTier.PROCEDURAL)

    @staticmethod
    def _entry_dict(
        content: str, hemisphere: Hemisphere, **kwargs: Any
    ) -> dict[str, Any]:
        """Build a T6 store entry-dict from donor add_* kwargs."""
        return {
            "id": f"mem-{uuid.uuid4().hex[:8]}",
            "content": content,
            "hemisphere": hemisphere.value,
            "is_novel": bool(kwargs.get("is_novel")),
            "novelty_score": float(kwargs.get("novelty_score") or 0.0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "who": kwargs.get("who", ""),
            "what": kwargs.get("what", ""),
            "where": kwargs.get("where", ""),
            "when": kwargs.get("when", ""),
            "why": kwargs.get("why", ""),
            "how": kwargs.get("how", ""),
            "metadata": dict(kwargs.get("metadata") or {}),
        }


# ── Donor-verbatim engine (memory_system.py:735-993) ──────────────────────


class DreamtimeEngine:
    """Dreamtime/contemplation engine — right-hemisphere processing during idle.

    ClaudeBots have a dream function: during idle periods, they review
    conversation history, cross-pollinate ideas, and surface insights
    that were not available during active conversation.

    This is NOT idle time — it's speculative processing time.

    The dreamtime engine:
    1. Gathers memories from long-term and procedural tiers
    2. Performs associative cross-pollination (right-hemisphere style)
    3. Identifies novel connections between previously unrelated concepts
    4. Generates insights and saves them to long-term memory
    5. Reports results for Manager review

    Dreamtime states:
    - IDLE: Not currently dreaming
    - GATHERING: Collecting memories for processing
    - PROCESSING: Right-hemisphere associative cross-talk
    - INSIGHT_GENERATED: Novel connections discovered
    - SAVING: Persisting insights to long-term memory

    Creativity = Generation of Novelty (McKenna)
    Dreamtime is the system's capacity for genuine creative emergence.
    """

    def __init__(self, memory_system: MemorySystem) -> None:
        self.memory = memory_system
        self.state = DreamState.IDLE
        self.dream_history: list[DreamResult] = []
        self.insight_count: int = 0

    def begin_contemplation(
        self,
        max_memories: int = 50,
        focus_area: str | None = None,
    ) -> list[MemoryEntry]:
        """Begin a dreamtime session.

        Gathers memories from long-term and procedural tiers for
        right-hemisphere associative processing.

        Args:
            max_memories: Maximum memories to gather for processing.
            focus_area: Optional focus area for targeted processing.

        Returns:
            List of gathered memories for processing.
        """
        self.state = DreamState.GATHERING
        gathered: list[MemoryEntry] = []

        # Gather long-term memories (right-hemisphere: holistic, contextual)
        long_term = self.memory.get_recent_long_term(limit=max_memories)
        gathered.extend(long_term)

        # Gather procedural memories (skills, principles, wisdom)
        procedural = self.memory.get_procedural_memories()
        gathered.extend(
            procedural[: max(1, max_memories // len(procedural) + 1) if procedural else 1]
        )

        # Filter by focus area if specified
        if focus_area:
            gathered = [
                m
                for m in gathered
                if focus_area.lower() in m.content.lower() or focus_area.lower() in m.what.lower()
            ]

        self.state = DreamState.PROCESSING
        return gathered

    def process_associations(
        self,
        memories: list[MemoryEntry],
    ) -> DreamResult:
        """Process gathered memories through right-hemisphere associative cross-talk.

        This is where creativity happens — the system finds novel connections
        between previously unrelated concepts. The Manager evaluates whether
        the generated novelty is worth encoding.

        Args:
            memories: Memories gathered by begin_contemplation.

        Returns:
            DreamResult with generated insights.
        """
        if not memories:
            return DreamResult(
                source_count=0,
                insight_count=0,
                is_novel=False,
                novelty_score=0.0,
                insights=[],
            )

        # Right-hemisphere associative processing:
        # Find connections between memories that share concepts but have different domains
        insights: list[str] = []

        # Strategy 1: Cross-domain connections (left + right hemisphere)
        left_memories = [m for m in memories if m.hemisphere == Hemisphere.LEFT]
        right_memories = [m for m in memories if m.hemisphere == Hemisphere.RIGHT]

        for left in left_memories[:5]:
            for right in right_memories[:5]:
                if left.what and right.what:
                    # Check for conceptual overlap
                    left_words = set(left.what.lower().split())
                    right_words = set(right.what.lower().split())
                    common = left_words & right_words
                    if common:
                        insight = f"Connection: '{left.content[:80]}' ↔ '{right.content[:80]}' (shared concept: {', '.join(common)})"
                        insights.append(insight)

        # Strategy 2: Novel pattern synthesis
        # Combine multiple memories to generate emergent insights
        if len(memories) >= 3:
            # Take up to 3 memories and synthesize
            sample = memories[: min(3, len(memories))]
            if len(sample) == 3:
                insight = f"Synthesis: '{sample[0].content[:60]}' + '{sample[1].content[:60]}' + '{sample[2].content[:60]}' → emergent pattern"
                insights.append(insight)
            elif len(sample) == 2:
                insight = f"Synthesis: '{sample[0].content[:60]}' + '{sample[1].content[:60]}' → new relationship"
                insights.append(insight)

        # Strategy 3: Gap detection
        # Find what's missing — what questions remain unanswered
        for memory in memories:
            if "unknown" in memory.content.lower() or "?" in memory.content:
                insights.append(f"Gap: Unanswered question — '{memory.content[:80]}'")

        # Evaluate novelty
        is_novel = len(insights) > 0 and any(
            "emergent" in i.lower() or "connection" in i.lower() for i in insights
        )
        novelty_score = min(1.0, len(insights) * 0.15) if is_novel else 0.0

        self.state = DreamState.INSIGHT_GENERATED

        result = DreamResult(
            source_count=len(memories),
            insight_count=len(insights),
            is_novel=is_novel,
            novelty_score=novelty_score,
            insights=insights,
        )

        return result

    def save_insights(self, result: DreamResult) -> int:
        """Save dreamtime insights to long-term memory.

        The Manager evaluates whether insights should be encoded.
        High-novelty insights are promoted to procedural memory.

        Args:
            result: DreamResult from process_associations.

        Returns:
            Number of insights saved.
        """
        if not result.insights:
            return 0

        saved = 0
        for insight in result.insights:
            # High novelty → procedural memory (permanent)
            # Moderate novelty → long-term memory (persistent)
            if result.novelty_score > 0.5:
                self.memory.add_procedural_memory(
                    content=insight,
                    hemisphere=Hemisphere.RIGHT,
                    is_novel=result.is_novel,
                    novelty_score=result.novelty_score,
                    what="dreamtime_insight",
                    where="right hemisphere",
                    why="Creative emergence from associative processing",
                    how="Dreamtime engine",
                )
            else:
                self.memory.add_long_term_memory(
                    content=insight,
                    hemisphere=Hemisphere.RIGHT,
                    is_novel=result.is_novel,
                    novelty_score=result.novelty_score,
                    what="dreamtime_insight",
                    where="right hemisphere",
                    why="Creative emergence from associative processing",
                    how="Dreamtime engine",
                )
            saved += 1
            self.insight_count += 1

        self.state = DreamState.SAVING
        return saved

    def run_contemplation(
        self,
        max_memories: int = 50,
        focus_area: str | None = None,
    ) -> DreamResult:
        """Run a complete dreamtime/contemplation cycle.

        Full pipeline:
        1. Gather memories (right-hemisphere: holistic, contextual)
        2. Process associations (cross-pollinate ideas)
        3. Save insights (promote to long-term or procedural)

        Args:
            max_memories: Maximum memories to gather for processing.
            focus_area: Optional focus area for targeted processing.

        Returns:
            DreamResult with generated insights.
        """
        # Step 1: Gather
        memories = self.begin_contemplation(max_memories=max_memories, focus_area=focus_area)

        # Step 2: Process
        result = self.process_associations(memories)

        # Step 3: Save
        self.save_insights(result)

        # Record in dream history
        self.dream_history.append(result)

        # Reset state
        self.state = DreamState.IDLE

        return result

    def get_dream_history(self, limit: int = 10) -> list[DreamResult]:
        """Get recent dreamtime results."""
        return self.dream_history[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """Get dreamtime system summary."""
        return {
            "state": self.state.value,
            "total_dreams": len(self.dream_history),
            "total_insights": self.insight_count,
            "recent_dreams": [
                {
                    "id": d.id,
                    "source_count": d.source_count,
                    "insight_count": d.insight_count,
                    "is_novel": d.is_novel,
                    "novelty_score": d.novelty_score,
                    "timestamp": d.timestamp,
                }
                for d in self.get_dream_history()
            ],
        }
