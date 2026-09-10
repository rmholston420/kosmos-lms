"""ports.memory — MemoryPort Protocol (ADR-027, extends ADR-008; hybrid search added by ADR-085).

Locked in Stage 1.8. Backed by DozerDB (community Neo4j fork with enterprise
features backported permissively, per ADR-008) + Graphiti temporal index +
Agent Memory Guard v0.2.2 write-time policy filter.

ADR-085 extended this surface with ``search_hybrid`` (lexical + semantic
fusion via Reciprocal Rank Fusion, k=60 by default) to serve the Tektos
hindsight-migration path at Stage 7.4. Weights sum to 1.0 (port-level
guard); adapters without a lexical index MUST raise ``NotImplementedError``
rather than silently degrade.

Zero-trust guarantee (spec §7): every write MUST supply `provenance` and
`confidence`. Enforcement is at the port layer (this module) — non-bypassable
by any adapter or plugin. AMG runs as an additional defense-in-depth policy
layer atop the port guard, never as a replacement for it.

Canonical pattern (matches ADR-022/023/024/025/026):
- Backend-touching methods are async.
- `is_healthy()` is sync + non-throwing (ADR-023 rule 5).
- `close()` is async + idempotent.
- Typed value objects returned from reads (no raw dicts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from numbers import Real
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "MemoryEventId",
    "MemoryHit",
    "MemoryPort",
    "MemoryWriteBlocked",
    "MEMORY_REQUIRED_FIELDS",
    "validate_hybrid_weights",
    "validate_zero_trust_write",
]


MEMORY_REQUIRED_FIELDS = frozenset({"provenance", "confidence"})
"""Fields that every MemoryPort write MUST carry (spec §7 zero-trust)."""


@dataclass(frozen=True, slots=True)
class MemoryEventId:
    """Handle returned from every write. Immutable."""

    id: str
    written_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryHit:
    """One row of a query_temporal / search_semantic / query result. Immutable.

    ``score`` is optional: temporal queries populate it with a naive
    substring-match indicator (``1.0`` on match), semantic queries populate
    it with the vector-similarity score returned by the underlying
    ``VectorPort`` adapter, and callers that don't care about score set it
    to ``None``.
    """

    id: str
    payload: dict[str, Any]
    score: float | None = None
    as_of: datetime | None = None


class MemoryWriteBlocked(RuntimeError):
    """Raised by an adapter when Agent Memory Guard returns `block`.

    Port-level guard failures raise `ValueError` (constructor-time invariant).
    AMG `block` failures raise this (runtime policy invariant) so callers can
    distinguish "you passed bad args" from "policy says no".
    """


def validate_hybrid_weights(
    lexical_weight: float,
    semantic_weight: float,
) -> None:
    """Enforce ADR-085 weight-sum invariant at the port layer.

    Raises ValueError if either weight is outside [0.0, 1.0] or the two do
    not sum to 1.0 (within a small floating-point epsilon). Non-bypassable.
    """
    for name, value in (("lexical_weight", lexical_weight), ("semantic_weight", semantic_weight)):
        if not isinstance(value, Real) or isinstance(value, bool):
            raise ValueError(
                f"MemoryPort.search_hybrid {name!r} must be a real number in [0.0, 1.0] (ADR-085)."
            )
        if float(value) < 0.0 or float(value) > 1.0:
            raise ValueError(
                f"MemoryPort.search_hybrid {name!r} must be in [0.0, 1.0], got {float(value)} (ADR-085)."
            )
    total = float(lexical_weight) + float(semantic_weight)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(
            f"MemoryPort.search_hybrid weights must sum to 1.0, got {total} (ADR-085)."
        )


def validate_zero_trust_write(
    *,
    provenance: Any,
    confidence: Any,
) -> None:
    """Enforce spec §7 zero-trust guarantee at the port layer.

    Raises ValueError on:
    - falsy / empty / non-string provenance
    - missing confidence
    - confidence that is not a real number
    - confidence outside [0.0, 1.0]
    - confidence that is a bool (mirrors ADR-026 rule; bool is a subclass of
      int in Python and would otherwise pass a numeric check silently)

    This is a pure function. Adapters MUST call it before any backend I/O.
    Non-bypassable.
    """
    if not isinstance(provenance, str) or not provenance:
        raise ValueError(
            "MemoryPort write requires non-empty string 'provenance' "
            "(spec §7 zero-trust; ADR-027)."
        )
    if isinstance(confidence, bool):
        raise ValueError(
            "MemoryPort 'confidence' must be a real number in [0.0, 1.0], "
            "not bool (spec §7 zero-trust; ADR-027)."
        )
    if not isinstance(confidence, Real):
        raise ValueError(
            "MemoryPort 'confidence' must be a real number in [0.0, 1.0] "
            "(spec §7 zero-trust; ADR-027)."
        )
    conf = float(confidence)
    if conf < 0.0 or conf > 1.0:
        raise ValueError(
            f"MemoryPort 'confidence' must be in [0.0, 1.0], got {conf} "
            "(spec §7 zero-trust; ADR-027)."
        )


@runtime_checkable
class MemoryPort(Protocol):
    """Kosmos MemoryPort — the sole plugin-visible memory interface.

    Backed by a graph store (DozerDB, ADR-008), a temporal index (Graphiti),
    and a write-time policy filter (Agent Memory Guard v0.2.2). Plugins MUST
    NOT import any of those directly; all coupling flows through this port.
    """

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
        """Persist a typed claim-triple (subject, predicate, object).

        Raises:
            ValueError: port-level zero-trust guard failed (missing/invalid
                provenance or confidence).
            MemoryWriteBlocked: Agent Memory Guard returned `block`.
        """
        ...

    async def query_temporal(
        self,
        cypher_or_query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        """Query the temporal graph.

        If `as_of` is provided, results reflect graph state at that moment.
        `cypher_or_query` may be a Cypher fragment (adapter-interpreted) or
        a natural-language query if the temporal index supports it (Graphiti
        does; other backends may not).
        """
        ...

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
        """Create a directed typed edge between two existing memory nodes.

        Raises:
            ValueError: port-level zero-trust guard failed.
            MemoryWriteBlocked: AMG returned `block`.
        """
        ...

    async def quarantine_write(
        self,
        payload: dict[str, Any],
        *,
        reason: str,
        provenance: str,
        confidence: float,
    ) -> MemoryEventId:
        """Route an untrusted write to the quarantine lane (spec §115).

        Payloads land in a Gnosis sub-table (semantically a graph subgraph
        tagged `:Quarantined`), pending Tier-1/Tier-2 review before promotion
        to durable semantic memory.

        Raises:
            ValueError: port-level zero-trust guard failed.
        """
        ...

    async def search_semantic(
        self,
        query: str,
        *,
        corpus: str | None = None,
        limit: int = 20,
        min_score: float = 0.0,
    ) -> list[MemoryHit]:
        """Semantic nearest-neighbour retrieval (ADR-074).

        Embeds ``query`` via ``EmbeddingsPort`` and searches the DozerDB
        memory-vector namespace via ``VectorPort``, then re-hydrates each
        vector hit into a ``MemoryHit`` carrying the full stored payload
        (including provenance + confidence) and the raw similarity score.

        ``corpus`` selects the logical vector collection
        (``kosmos-memory-{corpus or "default"}``). ``min_score`` filters
        out hits below the given cosine similarity; ``0.0`` keeps every
        hit the vector store returns.

        Adapters MAY degrade to an empty list when the composed
        ``EmbeddingsPort`` or ``VectorPort`` is not booted; they MUST
        NOT swallow port-level guard failures (``ValueError`` is
        re-raised so callers see the bug immediately).
        """
        ...

    async def search_hybrid(
        self,
        query: str,
        *,
        corpus: str | None = None,
        limit: int = 20,
        lexical_weight: float = 0.5,
        semantic_weight: float = 0.5,
        min_score: float = 0.0,
    ) -> list[MemoryHit]:
        """Hybrid lexical + semantic retrieval via Reciprocal Rank Fusion (ADR-085).

        Runs a lexical query and ``search_semantic`` in parallel over the same
        ``corpus``, then fuses the two ranked result lists via RRF with
        constant ``k=60`` (default; adapters MAY expose a tuned ``k`` via
        configuration but MUST NOT change the port default). The final score
        of a hit ``h`` is

            score(h) = lexical_weight * rrf(rank_lexical(h))
                     + semantic_weight * rrf(rank_semantic(h))

        where ``rrf(r) = 1 / (k + r)`` and hits absent from a list contribute
        zero for that list.

        ``lexical_weight`` + ``semantic_weight`` MUST sum to 1.0
        (port-level guard: ``validate_hybrid_weights``). ``min_score``
        filters out hits below the given fused score.

        Adapters without a native lexical index MUST raise
        ``NotImplementedError`` — no silent degrade to semantic-only
        (ADR-085 rule: callers relying on hybrid deserve to know when
        they aren't getting it).

        Raises:
            ValueError: port-level weight guard failed.
            NotImplementedError: adapter has no lexical index.
        """
        ...

    def is_healthy(self) -> bool:
        """Sync, non-throwing readiness probe (ADR-023 rule 5).

        MUST NOT raise. On error, return False and log.
        """
        ...

    async def close(self) -> None:
        """Idempotent teardown. Safe to call multiple times."""
        ...
