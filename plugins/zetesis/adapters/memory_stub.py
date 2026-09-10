"""ZetesisMemoryStub — Protocol-conformant MemoryPort stub (ADR-056 sub-slice 2/4).

Runtime-safe no-op stub. ``write_event`` returns a synthesized
:class:`MemoryEventId` (uuid4 id, ``datetime.utcnow`` timestamp) and
does not persist anything. Every other method raises so downstream
code never silently reads phantom data. Sub-slice 4 upgraded
``write_event`` from a raising stub to a no-op-returning-valid-handle
stub so the DoD trial could exercise the full ``ZetesisPlugin.research()``
port-call chain without a live MemoryPort backend (DozerDB was not up
at Stage 6.3.9). Real MemoryPort binds at kernel boot in Stage 6.4+.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ports.memory import MemoryEventId, MemoryHit


class ZetesisMemoryStub:
    """Minimal MemoryPort stub. Write returns a synthetic handle; reads raise."""

    _MSG = "ZetesisMemoryStub is a sub-slice-2 skeleton; wire a real MemoryPort."

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        source_citation: str | None = None,
        pii_tier: str = "Public",
        attributes: dict[str, Any] | None = None,
    ) -> MemoryEventId:
        # Runtime-safe no-op: return a synthetic handle so callers that
        # only need an event id (like ZetesisPlugin.research) can proceed.
        # Nothing is persisted; a second call for the same tuple yields
        # a fresh id.
        return MemoryEventId(
            id=f"stub-{uuid.uuid4().hex}",
            written_at=datetime.now(timezone.utc),
        )

    async def query_temporal(
        self,
        cypher_or_query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        raise NotImplementedError(self._MSG)

    async def link_entities(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError(self._MSG)

    async def quarantine_write(
        self,
        payload: dict[str, Any],
        *,
        reason: str,
        provenance: str,
        confidence: float,
    ) -> MemoryEventId:
        raise NotImplementedError(self._MSG)

    async def search_semantic(
        self,
        query: str,
        *,
        corpus: str | None = None,
        limit: int = 20,
        min_score: float = 0.0,
    ) -> list:
        # ADR-074 D1 added search_semantic to MemoryPort. Stub degrades
        # to an empty list (Zetesis's real semantic lane lives behind
        # the DozerDB adapter; this stub exists only for wiring tests).
        return []

    async def search_hybrid(
        self,
        query: str,
        *,
        corpus: str | None = None,
        limit: int = 20,
        lexical_weight: float = 0.5,
        semantic_weight: float = 0.5,
        min_score: float = 0.0,
    ) -> list:
        # ADR-085 / ADR-099 added search_hybrid to MemoryPort. Per the
        # ADR-085 rule, adapters without a lexical index MUST raise
        # NotImplementedError — no silent degrade to semantic-only.
        # Zetesis's real hybrid lane will land when a DozerDB LexicalIndex
        # is wired at kernel boot (Stage 7.4+1).
        raise NotImplementedError(self._MSG)

    def is_healthy(self) -> bool:
        return False

    async def close(self) -> None:
        return None
