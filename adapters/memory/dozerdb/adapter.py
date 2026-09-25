"""adapters.memory.dozerdb.adapter — DozerDB MemoryPort adapter (ADR-027).

Architecture (three injectable Protocol seams; matches ADR-025/026 pattern):

    DozerDbMemoryAdapter                          (implements MemoryPort)
      ├── GraphBackend         (Cypher I/O — DozerDB in prod, in-mem in tests)
      ├── AmgPolicy            (Agent Memory Guard v0.3.0 in prod, no-op in tests)
      └── TemporalIndex        (Graphiti in prod, in-mem in tests)

Plugins MUST depend on `ports.memory.MemoryPort` only — never on
`DozerDbMemoryAdapter`, `neo4j`, `graphiti_core`, or `agent_memory_guard`
directly (ADR-007).

Write path (enforced order):
    1. `ports.memory.validate_zero_trust_write` — non-bypassable floor.
    2. `AmgPolicy.evaluate(...)` — allow / redact / quarantine / block.
    3. `GraphBackend` transaction — CIDOC-CRM-shaped triple + provenance
       properties (Stage 1.8 accepts any string subject/predicate/object;
       full CRM class-hierarchy enforcement lands in Gnosis 3.1).
    4. `TemporalIndex.record_event(...)` — Graphiti episode registration.

Read path:
    1. `TemporalIndex.query_temporal(...)` — Graphiti in prod; delegates to
       `GraphBackend.query_cypher` for the in-memory test backend.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

from ports.embeddings import EmbeddingsPort
from ports.memory import (
    MemoryEventId,
    MemoryHit,
    MemoryPort,
    MemoryWriteBlocked,
    validate_hybrid_weights,
    validate_zero_trust_write,
)
from ports.vector import VectorPort

from .semantic_memory_path import SemanticMemoryPath

__all__ = [
    "AlwaysBlockAmgPolicy",
    "AlwaysQuarantineAmgPolicy",
    "AmgPolicy",
    "AmgVerdict",
    "DozerDbMemoryAdapter",
    "GraphBackend",
    "InMemoryGraphBackend",
    "InMemoryLexicalIndex",
    "InMemoryTemporalIndex",
    "LexicalIndex",
    "NoOpAmgPolicy",
    "TemporalIndex",
]

# ADR-085 Reciprocal Rank Fusion constant — port-level default, adapters MAY
# expose a tuned ``k`` via configuration but MUST NOT change the port default.
RRF_K: int = 60



log = logging.getLogger(__name__)


# ── AmgPolicy Protocol + verdict + test doubles ─────────────────────────────


@dataclass(frozen=True, slots=True)
class AmgVerdict:
    """Result of an Agent Memory Guard policy evaluation."""

    decision: Literal["allow", "redact", "quarantine", "block"]
    reason: str = ""
    redacted_payload: dict[str, Any] | None = None


@runtime_checkable
class AmgPolicy(Protocol):
    """Agent Memory Guard policy interface (write-time filter).

    Real implementation wraps `agent_memory_guard` v0.2.2 SHA-256 baseline +
    YAML policy engine. In-memory implementations are used for contract tests.
    """

    def evaluate(self, payload: dict[str, Any]) -> AmgVerdict: ...


class NoOpAmgPolicy:
    """AmgPolicy test double that always returns `allow`."""

    def evaluate(self, payload: dict[str, Any]) -> AmgVerdict:
        return AmgVerdict(decision="allow")


class AlwaysBlockAmgPolicy:
    """AmgPolicy test double that always returns `block`."""

    def __init__(self, reason: str = "test-block") -> None:
        self._reason = reason

    def evaluate(self, payload: dict[str, Any]) -> AmgVerdict:
        return AmgVerdict(decision="block", reason=self._reason)


class AlwaysQuarantineAmgPolicy:
    """AmgPolicy test double that always returns `quarantine`."""

    def __init__(self, reason: str = "test-quarantine") -> None:
        self._reason = reason

    def evaluate(self, payload: dict[str, Any]) -> AmgVerdict:
        return AmgVerdict(decision="quarantine", reason=self._reason)


# ── GraphBackend Protocol + in-memory test backend ──────────────────────────


@runtime_checkable
class GraphBackend(Protocol):
    """Cypher-shaped graph store abstraction.

    Real backend: `DozerDbGraphBackend` (Bolt to DozerDB via `neo4j` driver).
    Test backend: `InMemoryGraphBackend` (pure-Python dicts).

    All methods are async. `is_healthy` is sync + non-throwing (ADR-023
    rule 5). `close` is async + idempotent.
    """

    async def add_node(self, label: str, props: dict[str, Any]) -> str: ...
    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        props: dict[str, Any] | None,
    ) -> None: ...
    async def query_cypher(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...
    async def count_nodes(self, label: str) -> int: ...
    async def delete_node(self, node_id: str) -> None: ...
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...


class InMemoryGraphBackend:
    """Pure-Python `GraphBackend` for contract tests. Zero third-party deps.

    Supports the small subset of Cypher used by the adapter: substring match
    against node label or props via a simple parametric interpreter. Not a
    general-purpose Cypher engine.
    """

    def __init__(self, *, fail_healthy: bool = False) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: list[dict[str, Any]] = []
        self._closed = False
        self._fail_healthy = fail_healthy

    async def add_node(self, label: str, props: dict[str, Any]) -> str:
        node_id = props.get("id") or str(uuid.uuid4())
        self._nodes[node_id] = {"id": node_id, "label": label, **props}
        return node_id

    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        props: dict[str, Any] | None,
    ) -> None:
        self._edges.append(
            {
                "from": from_id,
                "to": to_id,
                "rel_type": rel_type,
                "props": dict(props or {}),
            }
        )

    async def query_cypher(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Minimal query: `label:<Label>` returns all nodes with that label;
        `contains:<substr>` returns nodes whose payload dumps to `substr`.
        Anything else returns all nodes. Test-only semantics.
        """
        needle = (cypher or "").strip()
        if needle.startswith("label:"):
            label = needle.split(":", 1)[1].strip()
            return [n for n in self._nodes.values() if n.get("label") == label]
        if needle.startswith("contains:"):
            frag = needle.split(":", 1)[1].strip().lower()
            return [n for n in self._nodes.values() if frag in str(n).lower()]
        return list(self._nodes.values())

    async def count_nodes(self, label: str) -> int:
        """Test-only: count nodes with this label (mirrors the backend)."""
        return sum(1 for n in self._nodes.values() if n.get("label") == label)

    async def delete_node(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)
        self._edges = [
            e for e in self._edges if e["from"] != node_id and e["to"] != node_id
        ]

    def is_healthy(self) -> bool:
        if self._fail_healthy:
            return False
        return not self._closed

    async def close(self) -> None:
        self._closed = True


# ── TemporalIndex Protocol + in-memory test backend ─────────────────────────


@runtime_checkable
class TemporalIndex(Protocol):
    """Temporal knowledge-graph indexer.

    Real backend: `GraphitiTemporalIndex` (wraps `graphiti_core`).
    Test backend: `InMemoryTemporalIndex`.
    """

    async def record_event(
        self,
        event_id: str,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> None: ...
    async def query_temporal(
        self,
        query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]: ...
    async def close(self) -> None: ...


@dataclass
class _Episode:
    id: str
    payload: dict[str, Any]
    as_of: datetime


class InMemoryTemporalIndex:
    """Pure-Python `TemporalIndex` for contract tests."""

    def __init__(self) -> None:
        self._episodes: list[_Episode] = []

    async def record_event(
        self,
        event_id: str,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> None:
        self._episodes.append(_Episode(id=event_id, payload=dict(payload), as_of=as_of))

    async def query_temporal(
        self,
        query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        needle = (query or "").lower()
        for ep in self._episodes:
            if as_of is not None and ep.as_of > as_of:
                continue
            payload_dump = str(ep.payload).lower()
            score = 1.0 if not needle or needle in payload_dump else 0.0
            if score == 0.0 and needle:
                continue
            hits.append(
                MemoryHit(id=ep.id, payload=dict(ep.payload), score=score, as_of=ep.as_of)
            )
            if len(hits) >= limit:
                break
        return hits

    async def close(self) -> None:
        return None


# ── LexicalIndex Protocol + in-memory BM25 test backend (ADR-085 / ADR-099) ──


_LEX_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _lex_text_from_payload(payload: dict[str, Any]) -> str:
    """Concatenate the tokenised surface of a MemoryPort write payload.

    Shared by ``InMemoryLexicalIndex`` and ``DozerDbLexicalIndex``
    (ADR-100 D3) so tokenisation parity holds across the in-memory
    test backend and the production Lucene-fulltext backend. The three
    fields (subject / predicate / object) are the same triple
    ``MemoryPort.write_event`` accepts; missing fields degrade to the
    empty string.
    """
    return " ".join(
        [
            str(payload.get("subject", "")),
            str(payload.get("predicate", "")),
            str(payload.get("object", "")),
        ]
    )


def _lex_tokenize(text: str) -> list[str]:
    """Tokenize free text for the in-memory BM25 index.

    Lowercased word tokens matching ``[A-Za-z0-9_]+``. Symmetric with the
    tokenizer a Neo4j Lucene analyser applies to English text at index time,
    so RRF rank-order agreement between this backend and the real
    ``DozerDbLexicalIndex`` (Stage 7.4+1) is preserved on ASCII-only corpora.
    """
    return [t.lower() for t in _LEX_TOKEN_RE.findall(text or "")]


@runtime_checkable
class LexicalIndex(Protocol):
    """BM25-shaped lexical retrieval index over the MemoryEvent corpus.

    Real backend: ``DozerDbLexicalIndex`` (wraps a Neo4j Lucene fulltext index
    over the ``:MemoryEvent`` label; Stage 7.4+1).
    Test backend: ``InMemoryLexicalIndex`` (pure-Python BM25-Okapi).

    Adapter-scoped Protocol (per ADR-099 D3): composed inside
    ``DozerDbMemoryAdapter`` and never exposed to plugins directly. Plugins
    use ``MemoryPort.search_hybrid``, not this Protocol, per ADR-007 +
    ADR-027.
    """

    async def index_event(
        self,
        event_id: str,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> None: ...

    async def search_lexical(
        self,
        query: str,
        *,
        corpus: str | None,
        limit: int,
    ) -> list[MemoryHit]: ...

    async def close(self) -> None: ...


@dataclass
class _LexDoc:
    id: str
    payload: dict[str, Any]
    as_of: datetime
    corpus: str | None
    tokens: list[str]
    length: int
    tf: Counter[str]


class InMemoryLexicalIndex:
    """Pure-Python BM25-Okapi ``LexicalIndex`` for contract tests (ADR-099 D4).

    Tokenises subject / predicate / object at index time. Scores at query
    time using BM25-Okapi with ``k1 = 1.5`` and ``b = 0.75``. Returns
    ``MemoryHit`` objects sorted by score descending, ``score`` populated
    with the raw BM25 value.

    Corpus filter: ``search_lexical(corpus=X)`` only considers events whose
    payload ``attributes.corpus_name`` equals ``X`` (or all events when
    ``corpus is None``).
    """

    K1: float = 1.5
    B: float = 0.75

    def __init__(self) -> None:
        self._docs: dict[str, _LexDoc] = {}
        self._closed = False

    async def index_event(
        self,
        event_id: str,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> None:
        if self._closed:
            raise RuntimeError("InMemoryLexicalIndex is closed")
        tokens = _lex_tokenize(_lex_text_from_payload(payload))
        corpus = (payload.get("attributes") or {}).get("corpus_name")
        self._docs[event_id] = _LexDoc(
            id=event_id,
            payload=dict(payload),
            as_of=as_of,
            corpus=corpus,
            tokens=tokens,
            length=len(tokens),
            tf=Counter(tokens),
        )

    async def search_lexical(
        self,
        query: str,
        *,
        corpus: str | None,
        limit: int,
    ) -> list[MemoryHit]:
        if not query:
            return []
        q_tokens = _lex_tokenize(query)
        if not q_tokens:
            return []
        pool = [
            d
            for d in self._docs.values()
            if corpus is None or d.corpus == corpus
        ]
        if not pool:
            return []
        n = len(pool)
        avgdl = sum(d.length for d in pool) / n if n else 0.0
        # BM25-Okapi IDF: log((N - df + 0.5) / (df + 0.5) + 1). +1 keeps IDF
        # non-negative for terms present in most docs.
        df: Counter[str] = Counter()
        for d in pool:
            for term in set(q_tokens):
                if d.tf.get(term, 0) > 0:
                    df[term] += 1
        idf = {
            term: math.log(((n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5)) + 1.0)
            for term in set(q_tokens)
        }
        scored: list[tuple[float, _LexDoc]] = []
        for d in pool:
            if d.length == 0:
                continue
            score = 0.0
            for term in q_tokens:
                tf = d.tf.get(term, 0)
                if tf == 0:
                    continue
                numer = tf * (self.K1 + 1.0)
                denom = tf + self.K1 * (1.0 - self.B + self.B * (d.length / avgdl))
                score += idf[term] * (numer / denom)
            if score > 0.0:
                scored.append((score, d))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            MemoryHit(id=d.id, payload=dict(d.payload), score=score, as_of=d.as_of)
            for score, d in scored[:limit]
        ]

    async def close(self) -> None:
        self._closed = True


# ── DozerDbMemoryAdapter ────────────────────────────────────────────────────


@dataclass
class _AdapterOptions:
    """Constructor options captured for is_healthy / close bookkeeping."""

    closed: bool = False
    close_errors_swallowed: list[str] = field(default_factory=list)


class DozerDbMemoryAdapter:
    """MemoryPort adapter backed by DozerDB + Graphiti + Agent Memory Guard.

    Wiring is via injected `GraphBackend`, `AmgPolicy`, `TemporalIndex`
    Protocol implementations. Contract tests use in-memory backends declared
    above; production wiring uses `DozerDbGraphBackend` (lazy `neo4j`
    import), `AmgGuardPolicy` (lazy `agent_memory_guard` v0.3.0 import; see
    ADR-048 for the v0.2.2→v0.3.0 bump), and `GraphitiTemporalIndex` (lazy
    `graphiti_core` import). The prior alias `AmgV02Policy` is retained for
    one release cycle.

    Zero-trust guarantee: every write path calls
    `ports.memory.validate_zero_trust_write` before any backend I/O. See
    ADR-027 §Enforcement layers.
    """

    def __init__(
        self,
        *,
        graph: GraphBackend,
        amg: AmgPolicy,
        temporal: TemporalIndex,
        embeddings: EmbeddingsPort | None = None,
        vector: VectorPort | None = None,
        lexical: LexicalIndex | None = None,
        default_corpus: str | None = None,
    ) -> None:
        self._graph = graph
        self._amg = amg
        self._temporal = temporal
        # ADR-074 D3: optional semantic memory lane. Constructed only
        # when BOTH ports are wired. When absent, ``search_semantic``
        # degrades to an empty list and ``write_event`` skips the
        # embed+upsert side effect.
        self._semantic: SemanticMemoryPath | None = None
        if embeddings is not None and vector is not None:
            self._semantic = SemanticMemoryPath(
                embeddings=embeddings,
                vector=vector,
            )
        # ADR-099 D3: optional lexical retrieval lane. When absent,
        # ``search_hybrid`` MUST raise ``NotImplementedError`` per
        # ADR-085 (no silent degrade to semantic-only). When present,
        # ``write_event`` mirrors every accepted write into the index.
        self._lexical: LexicalIndex | None = lexical
        self._default_corpus = default_corpus
        self._state = _AdapterOptions()

    # ── writes ──────────────────────────────────────────────────────────

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
        # 1. Non-bypassable port-level guard (spec §7).
        validate_zero_trust_write(provenance=provenance, confidence=confidence)

        payload: dict[str, Any] = {
            "subject": subject,
            "predicate": predicate,
            "object": object,
            "provenance": provenance,
            "confidence": float(confidence),
            "pii_tier": pii_tier,
            "source_citation": source_citation,
            "attributes": dict(attributes or {}),
        }

        # 2. Agent Memory Guard policy layer.
        verdict = self._amg.evaluate(payload)
        if verdict.decision == "block":
            raise MemoryWriteBlocked(verdict.reason or "AMG blocked write")
        if verdict.decision == "redact" and verdict.redacted_payload is not None:
            payload = dict(verdict.redacted_payload)
        if verdict.decision == "quarantine":
            # Route via quarantine lane with the same provenance/confidence.
            return await self.quarantine_write(
                payload,
                reason=verdict.reason or "AMG quarantine",
                provenance=provenance,
                confidence=float(confidence),
            )

        # 3. Graph write. CIDOC-CRM decomposition: three nodes + two edges
        #    (:Subject)-[:PREDICATE {props}]->(:Object). Stage 1.8 accepts any
        #    string subject/predicate/object; Gnosis 3.1 will enforce the CRM
        #    class hierarchy + EDGE_TYPES.md predicate whitelist.
        written_at = datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())

        subject_id = await self._graph.add_node(
            "Entity", {"value": subject, "role": "subject"}
        )
        object_id = await self._graph.add_node(
            "Entity", {"value": object, "role": "object"}
        )
        event_props = {
            "id": event_id,
            "predicate": predicate,
            "written_at": written_at.isoformat(),
            **payload,
        }
        await self._graph.add_node("MemoryEvent", event_props)
        await self._graph.add_edge(
            event_id, subject_id, "SUBJECT_OF", {"role": "subject"}
        )
        await self._graph.add_edge(
            event_id, object_id, "OBJECT_OF", {"role": "object"}
        )

        # 4. Temporal index registration.
        await self._temporal.record_event(event_id, payload, as_of=written_at)

        # 5. Semantic memory lane (ADR-074 D3). Optional side effect;
        #    failures are logged but do not affect the primary write.
        #    Corpus resolution: attributes["corpus_name"] > default_corpus.
        if self._semantic is not None:
            corpus = (
                (attributes or {}).get("corpus_name")
                or self._default_corpus
            )
            await self._semantic.embed_and_upsert(
                event_id,
                payload,
                corpus=corpus,
                as_of=written_at,
            )

        # 6. Lexical index lane (ADR-099 D3). Optional side effect; failures
        #    are logged but do not affect the primary write. Mirrors the
        #    semantic lane's ADR-074 D3 opt-in shape.
        if self._lexical is not None:
            try:
                await self._lexical.index_event(
                    event_id,
                    payload,
                    as_of=written_at,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "DozerDbMemoryAdapter.write_event: lexical index failed: %s",
                    exc,
                )

        return MemoryEventId(id=event_id, written_at=written_at)

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
        validate_zero_trust_write(provenance=provenance, confidence=confidence)
        payload = {
            "source_id": source_id,
            "target_id": target_id,
            "relationship": relationship,
            "provenance": provenance,
            "confidence": float(confidence),
            "attributes": dict(attributes or {}),
        }
        verdict = self._amg.evaluate(payload)
        if verdict.decision == "block":
            raise MemoryWriteBlocked(verdict.reason or "AMG blocked link")
        if verdict.decision == "quarantine":
            await self.quarantine_write(
                payload,
                reason=verdict.reason or "AMG quarantine",
                provenance=provenance,
                confidence=float(confidence),
            )
            return
        # allow / redact both proceed to the graph.
        edge_props = payload
        if verdict.decision == "redact" and verdict.redacted_payload is not None:
            edge_props = dict(verdict.redacted_payload)
        await self._graph.add_edge(source_id, target_id, relationship, edge_props)

    async def quarantine_write(
        self,
        payload: dict[str, Any],
        *,
        reason: str,
        provenance: str,
        confidence: float,
    ) -> MemoryEventId:
        validate_zero_trust_write(provenance=provenance, confidence=confidence)
        written_at = datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())
        node_props = {
            "id": event_id,
            "reason": reason,
            "provenance": provenance,
            "confidence": float(confidence),
            "written_at": written_at.isoformat(),
            "quarantined_payload": dict(payload),
        }
        await self._graph.add_node("Quarantined", node_props)
        # Quarantined writes are NOT indexed in Graphiti — they are not
        # semantic memory until reviewed and promoted (spec §115).
        return MemoryEventId(id=event_id, written_at=written_at)

    # ── reads ───────────────────────────────────────────────────────────

    async def query_temporal(
        self,
        cypher_or_query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        return await self._temporal.query_temporal(
            cypher_or_query, as_of=as_of, limit=limit
        )

    async def search_semantic(
        self,
        query: str,
        *,
        corpus: str | None = None,
        limit: int = 20,
        min_score: float = 0.0,
    ) -> list[MemoryHit]:
        """Semantic retrieval via EmbeddingsPort + VectorPort (ADR-074 D1).

        Degrades to an empty list when the semantic lane is unwired
        (either dependency ``None`` at construction time).
        """
        if self._semantic is None:
            return []
        resolved_corpus = corpus or self._default_corpus
        return await self._semantic.semantic_lookup(
            query,
            corpus=resolved_corpus,
            limit=limit,
            min_score=min_score,
        )

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
        """Hybrid lexical + semantic retrieval via RRF (ADR-085 / ADR-099 D2).

        Fuses ``LexicalIndex.search_lexical`` with ``search_semantic`` via
        Reciprocal Rank Fusion with constant ``k = RRF_K`` (60). Weights
        MUST sum to 1.0 (enforced by ``ports.memory.validate_hybrid_weights``
        — non-bypassable). ``min_score`` filters on the fused score.

        Raises:
            ValueError: port-level weight guard failed.
            NotImplementedError: this adapter has no wired ``LexicalIndex``
                (ADR-085 — no silent degrade to semantic-only).
        """
        # 1. Non-bypassable port-level guard.
        validate_hybrid_weights(lexical_weight, semantic_weight)

        # 2. Honesty rule (ADR-085): raise, do not silently degrade.
        if self._lexical is None:
            raise NotImplementedError(
                "DozerDbMemoryAdapter.search_hybrid requires a LexicalIndex "
                "(ADR-085; wire one via the `lexical=` kwarg)."
            )

        resolved_corpus = corpus or self._default_corpus

        # 3. Run both retrieval legs. The semantic leg tolerates being
        #    unwired — collapses to an empty list under ADR-074 D3.
        lex_hits = await self._lexical.search_lexical(
            query,
            corpus=resolved_corpus,
            limit=limit,
        )
        sem_hits = await self.search_semantic(
            query,
            corpus=resolved_corpus,
            limit=limit,
            min_score=0.0,  # filtering happens post-fusion on fused score.
        )

        # 4. Reciprocal Rank Fusion. rrf(r) = 1 / (RRF_K + r) with r 1-indexed.
        lex_rank = {h.id: i + 1 for i, h in enumerate(lex_hits)}
        sem_rank = {h.id: i + 1 for i, h in enumerate(sem_hits)}

        # 5. Payload preference: semantic > lexical (semantic-side payload
        #    carries the fuller shape that ``SemanticMemoryPath`` produces).
        payload_by_id: dict[str, dict[str, Any]] = {
            h.id: dict(h.payload) for h in lex_hits
        }
        for h in sem_hits:
            payload_by_id[h.id] = dict(h.payload)

        as_of_by_id: dict[str, datetime | None] = {
            h.id: h.as_of for h in lex_hits
        }
        for h in sem_hits:
            as_of_by_id[h.id] = h.as_of

        fused: list[tuple[float, str]] = []
        for event_id in payload_by_id:
            lex_score = (
                1.0 / (RRF_K + lex_rank[event_id])
                if event_id in lex_rank
                else 0.0
            )
            sem_score = (
                1.0 / (RRF_K + sem_rank[event_id])
                if event_id in sem_rank
                else 0.0
            )
            score = (
                float(lexical_weight) * lex_score
                + float(semantic_weight) * sem_score
            )
            if score >= min_score:
                fused.append((score, event_id))

        fused.sort(key=lambda pair: pair[0], reverse=True)

        return [
            MemoryHit(
                id=event_id,
                payload=payload_by_id[event_id],
                score=score,
                as_of=as_of_by_id.get(event_id),
            )
            for score, event_id in fused[:limit]
        ]

    # ── observability (ADR-123, Stage 11.7) ───────────────────────────────

    async def stats(self) -> dict[str, Any]:
        """Honest corpus counts for the dashboard (never raises).

        Counts the node labels this adapter writes (``MemoryEvent``,
        ``Entity``, ``Quarantined``) via ``GraphBackend.count_nodes`` —
        real Cypher on DozerDB, a label-filter on the in-memory backend.
        A failed count degrades to ``None`` — the endpoint reports the
        failure instead of a fabricated number.
        """
        out: dict[str, Any] = {
            "healthy": self.is_healthy(),
            "memory_events": None,
            "entities": None,
            "quarantined": None,
            "errors": [],
        }
        for prop, label in (
            ("memory_events", "MemoryEvent"),
            ("entities", "Entity"),
            ("quarantined", "Quarantined"),
        ):
            try:
                out[prop] = await self._graph.count_nodes(label)
            except Exception as exc:  # noqa: BLE001 — ADR-023 rule 5
                out["errors"].append(f"{label}: {type(exc).__name__}")
                log.warning("memory.stats count failed for %s: %s", label, exc)
        return out

    # ── lifecycle ───────────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Sync, non-throwing (ADR-023 rule 5)."""
        try:
            if self._state.closed:
                return False
            return bool(self._graph.is_healthy())
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("memory.is_healthy raised: %s", exc)
            return False

    async def close(self) -> None:
        """Idempotent — safe to call multiple times."""
        if self._state.closed:
            return
        self._state.closed = True
        for name, obj in (("graph", self._graph), ("temporal", self._temporal)):
            try:
                await obj.close()
            except Exception as exc:  # noqa: BLE001 - swallow per ADR-023 rule 5
                self._state.close_errors_swallowed.append(f"{name}: {exc}")
                log.warning("memory.close swallowed %s.close error: %s", name, exc)
