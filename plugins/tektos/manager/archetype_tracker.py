"""plugins.tektos.manager.archetype_tracker — plugin-internal archetype tracking.

Rewrite of donor ``tektos-ultima/src/tektos/agents/manager/archetype_tracker.py``
per ADR-108 D2. Donor pydantic ``BaseModel`` → frozen slotted dataclasses in
:mod:`.models`; tracker itself remains mutable-index-of-frozen-records
because the archetype counters must increment. Semantics preserved verbatim:

* Default threshold ``3``.
* ``record_event`` appends to a per-category ``events`` tuple and increments
  ``occurrence_count`` by rebuilding the frozen :class:`Archetype` via
  :func:`dataclasses.replace`.
* ``should_create_structure(category)`` returns ``True`` iff the archetype's
  ``occurrence_count`` has hit ``threshold`` AND ``permanent_structure_id``
  is still ``None`` (donor invariant — one skill per archetype).
* ``clear_events(keep_last)`` bounds the global event log; donor default
  ``keep_last=100`` preserved.

The animal that got eaten teaches more than the ones that got away.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .models import Archetype, ArchetypeEvent


class ArchetypeTracker:
    """Tracks events and recognizes archetypes (repeated patterns).

    When an archetype hits its frequency threshold, the manager emits a
    feedback recommending the caller encode this pattern as a permanent
    skill or tool. The tracker itself does not create skills — that is
    deferred to a future skill-registry stage per ADR-108 D9.

    Attributes:
        archetypes: mapping of category name to :class:`Archetype`.
        events: global list of every recorded :class:`ArchetypeEvent`.
        threshold: default threshold for new archetypes.
    """

    def __init__(self, threshold: int = 3) -> None:
        self.archetypes: dict[str, Archetype] = {}
        self.events: list[ArchetypeEvent] = []
        self.threshold = threshold

    # ── Event / archetype mutation ─────────────────────────────────────────

    def record_event(
        self,
        category: str,
        description: str,
        severity: str = "warning",
        **kwargs: Any,  # noqa: ARG002 — kept for donor parity; W5H1M lives on ManagerFeedback in Kosmos
    ) -> ArchetypeEvent:
        """Record an event and update archetype counts.

        Returns the recorded :class:`ArchetypeEvent`. Semantics preserved
        verbatim from donor.
        """

        event = ArchetypeEvent(
            category=category,
            description=description,
            severity=severity,
        )
        self.events.append(event)

        existing = self.archetypes.get(category)
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing is None:
            self.archetypes[category] = Archetype(
                category=category,
                occurrence_count=1,
                threshold=self.threshold,
                events=(event,),
                first_seen=now_iso,
                last_seen=now_iso,
            )
        else:
            self.archetypes[category] = replace(
                existing,
                occurrence_count=existing.occurrence_count + 1,
                events=existing.events + (event,),
                last_seen=now_iso,
            )

        return event

    # ── Queries ────────────────────────────────────────────────────────────

    def get_archetype(self, category: str) -> Archetype | None:
        """Return the archetype for ``category`` or ``None``."""

        return self.archetypes.get(category)

    def get_active_archetypes(self) -> list[Archetype]:
        """Return every archetype sorted by ``occurrence_count`` descending.

        Kosmos discharges donor's ``is_active`` flag — every tracked archetype
        is treated as active at 8.6; retirement is a future stage concern.
        """

        return sorted(
            self.archetypes.values(),
            key=lambda a: a.occurrence_count,
            reverse=True,
        )

    def get_archetypes_at_threshold(self) -> list[Archetype]:
        """Return archetypes that hit or exceeded threshold without a permanent structure."""

        return [
            a
            for a in self.archetypes.values()
            if a.occurrence_count >= a.threshold
            and a.permanent_structure_id is None
        ]

    def get_archetype_counts(self) -> dict[str, int]:
        """Return category → occurrence count mapping (donor parity)."""

        return {cat: a.occurrence_count for cat, a in self.archetypes.items()}

    def should_create_structure(self, category: str) -> bool:
        """True iff archetype hit threshold and has no permanent structure yet.

        Donor invariant verbatim.
        """

        archetype = self.archetypes.get(category)
        if archetype is None:
            return False
        if archetype.permanent_structure_id is not None:
            return False
        return archetype.occurrence_count >= archetype.threshold

    def mark_structure_created(self, category: str, structure_id: str) -> None:
        """Bind a permanent structure id to an archetype (donor parity).

        Called by a future skill-registry stage; at 8.6 the manager never
        calls this itself — ``permanent_structure_id`` stays ``None`` per
        ADR-108 D9.
        """

        existing = self.archetypes.get(category)
        if existing is None:
            return
        self.archetypes[category] = replace(
            existing, permanent_structure_id=structure_id
        )

    def clear_events(self, keep_last: int = 100) -> None:
        """Bound the global event log. Donor semantics verbatim."""

        if len(self.events) > keep_last:
            self.events = self.events[-keep_last:]


__all__ = ["ArchetypeTracker"]
