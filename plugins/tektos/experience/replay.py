"""Kosmos-native ``ExperienceReplay`` (Stage 8.3 · ADR-105).

Persists ``ExperienceRecord``s via ``RelationalMemoryPort.write_narrative``
and recalls via ``RelationalMemoryPort.search_narratives`` — the port is
the source of truth. When the port is unbound (memory-only mode) records
fall into a fixed-size ring buffer and recall serves from that buffer;
this preserves engine functionality in unit tests and boot-degrade
states without silently dropping data.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

from ports.event_envelope import EventEnvelope

from . import (
    TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE,
    TEKTOS_EXPERIENCE_PREDICATE,
    TEKTOS_EXPERIENCE_PROVENANCE,
)
from .models import ExperienceRecord

log = logging.getLogger(__name__)


@runtime_checkable
class _NarrativeHitLike(Protocol):
    narrative_id: str
    session_id: str
    body: str
    tags: tuple[str, ...]
    confidence: float


@runtime_checkable
class _RelationalMemoryLike(Protocol):
    async def write_narrative(
        self,
        *,
        session_id: str,
        agent_id: str | None,
        title: str,
        body: str,
        tags: tuple[str, ...],
        embedding: tuple[float, ...] | None,
        confidence: float,
        provenance: str,
    ) -> str: ...

    async def search_narratives(
        self,
        *,
        query: str,
        embedding: tuple[float, ...] | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        tags: tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[Any, ...]: ...


@runtime_checkable
class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class ExperienceReplay:
    """Kosmos Tektos experience-replay engine (ADR-105 D1)."""

    def __init__(
        self,
        *,
        relational_memory: _RelationalMemoryLike | None = None,
        event_bus: _EventBusLike | None = None,
        max_records: int = 100,
    ) -> None:
        self._relational_memory = relational_memory
        self._event_bus = event_bus
        self._buffer: deque[ExperienceRecord] = deque(maxlen=max_records)

    @property
    def is_persistence_bound(self) -> bool:
        return self._relational_memory is not None

    # --- write path ----------------------------------------------------

    async def record(
        self,
        *,
        session_id: str,
        synthesis: dict[str, Any],
        context: str | None = None,
        confidence: float | None = None,
    ) -> tuple[ExperienceRecord, str | None]:
        """Record one experience derived from a ``SynthesisResult`` dict.

        Never raises (fail-open). Returns ``(record, narrative_id)`` —
        ``narrative_id`` is ``None`` in memory-only mode.
        """
        eff_context = str(context or synthesis.get("context") or "software_engineering")
        eff_conf = (
            float(confidence)
            if confidence is not None
            else float(
                synthesis.get("confidence", TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE)
            )
        )
        record = ExperienceRecord(
            cycle_id=str(
                synthesis.get("spec_id")
                or synthesis.get("id")
                or synthesis.get("cycle_id")
                or "unknown-cycle"
            ),
            insight_type=str(synthesis.get("insight_type", "synthesis")),
            what_happened=str(synthesis.get("what_happened", "")),
            what_was_expected=str(synthesis.get("what_was_expected", "")),
            guidance=str(
                synthesis.get("synthesis")
                or synthesis.get("guidance")
                or ""
            ),
            context=eff_context,
            confidence=eff_conf,
            priority=str(synthesis.get("priority", "normal")),
            tags=tuple(synthesis.get("tags") or ()),
        )
        self._buffer.append(record)

        narrative_id: str | None = None
        if self._relational_memory is not None:
            try:
                narrative_id = await self._relational_memory.write_narrative(
                    session_id=session_id,
                    agent_id=TEKTOS_EXPERIENCE_PROVENANCE,
                    title=f"{TEKTOS_EXPERIENCE_PREDICATE}:{record.id}",
                    body=json.dumps(
                        {
                            "id": record.id,
                            "cycle_id": record.cycle_id,
                            "insight_type": record.insight_type,
                            "what_happened": record.what_happened,
                            "what_was_expected": record.what_was_expected,
                            "guidance": record.guidance,
                            "context": record.context,
                            "confidence": record.confidence,
                            "priority": record.priority,
                            "timestamp": record.timestamp,
                            "tags": list(record.tags),
                        },
                        default=str,
                    ),
                    tags=(
                        TEKTOS_EXPERIENCE_PROVENANCE,
                        record.context,
                        session_id,
                    ),
                    embedding=None,
                    confidence=record.confidence,
                    provenance=TEKTOS_EXPERIENCE_PROVENANCE,
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.experience: write_narrative failed; kept in memory-only "
                    "buffer (ADR-105 D9 fail-open)"
                )
                narrative_id = None

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    EventEnvelope(
                        event_type=TEKTOS_EXPERIENCE_PREDICATE,
                        producer_plugin=TEKTOS_EXPERIENCE_PROVENANCE,
                        payload={
                            "session_id": session_id,
                            "cycle_id": record.cycle_id,
                            "context": record.context,
                            "narrative_id": narrative_id,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.experience: EventBus publish failed; continuing "
                    "(fail-open)"
                )

        return record, narrative_id

    # --- recall path ---------------------------------------------------

    async def recall(
        self, *, context: str, limit: int = 10
    ) -> tuple[ExperienceRecord, ...]:
        """Recall past experiences for a given ``context``.

        Prefers the port-backed ``search_narratives`` when bound; falls
        back to the in-memory ring buffer (context-tag filtered) when
        unbound. Never raises: on port exception, degrades to the
        in-memory buffer (fail-open).
        """
        if limit <= 0:
            return ()

        if self._relational_memory is not None:
            try:
                hits = await self._relational_memory.search_narratives(
                    query=context,
                    embedding=None,
                    tags=(TEKTOS_EXPERIENCE_PROVENANCE,),
                    limit=limit,
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.experience: search_narratives failed; falling back "
                    "to in-memory ring buffer (fail-open)"
                )
                hits = None
            if hits is not None:
                records: list[ExperienceRecord] = []
                for hit in hits:
                    body_str = getattr(hit, "body", None)
                    if not body_str:
                        continue
                    try:
                        obj = json.loads(body_str)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    records.append(
                        ExperienceRecord(
                            id=str(obj.get("id", "")),
                            cycle_id=str(obj.get("cycle_id", "")),
                            insight_type=str(obj.get("insight_type", "synthesis")),
                            what_happened=str(obj.get("what_happened", "")),
                            what_was_expected=str(obj.get("what_was_expected", "")),
                            guidance=str(obj.get("guidance", "")),
                            context=str(obj.get("context", "")),
                            confidence=float(obj.get("confidence", 0.75)),
                            priority=str(obj.get("priority", "normal")),
                            timestamp=str(obj.get("timestamp", "")),
                            tags=tuple(obj.get("tags") or ()),
                        )
                    )
                return tuple(records[:limit])

        # In-memory fallback — filter by context tag, newest last.
        filtered = [r for r in self._buffer if r.context == context]
        return tuple(filtered[-limit:])

    def recent(self, limit: int = 10) -> tuple[ExperienceRecord, ...]:
        """Return the most-recent buffered records regardless of context."""
        if limit <= 0:
            return ()
        return tuple(list(self._buffer)[-limit:])


__all__ = ["ExperienceReplay"]
