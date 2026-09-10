"""adapters.memory.dozerdb.test_search_hybrid_contract — Stage 7.4 / ADR-099 D2.

Contract tests for ``DozerDbMemoryAdapter.search_hybrid``. Verifies the
RRF fusion formula from ADR-085 verbatim:

    score(h) = lexical_weight * rrf(rank_lexical(h))
             + semantic_weight * rrf(rank_semantic(h))
    rrf(r) = 1 / (RRF_K + r), RRF_K = 60

- Non-bypassable weight guard (``validate_hybrid_weights``).
- ``NotImplementedError`` when the lexical lane is unwired (ADR-085
  honesty rule — no silent degrade to semantic-only).
- ``LexicalIndex`` Protocol conformance for the in-memory backend.
- Missing-semantic-leg fusion (lexical-only path).
- Fused score ordering + payload preference (semantic > lexical).
- ``min_score`` filters on fused score, not per-leg score.
- ``corpus`` propagates to both legs.
- ``limit`` truncates the fused list.

The semantic leg is stubbed via a lightweight ``FakeSemanticMemoryPath``
attached at ``adapter._semantic`` so we can assert fusion math without
booting an EmbeddingsPort + VectorPort pair.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from adapters.memory.dozerdb import (
    DozerDbMemoryAdapter,
    InMemoryGraphBackend,
    InMemoryLexicalIndex,
    InMemoryTemporalIndex,
    LexicalIndex,
    NoOpAmgPolicy,
    RRF_K,
)
from ports.memory import MemoryHit, MemoryPort


# ── Helpers ─────────────────────────────────────────────────────────────────


def _adapter_with_lexical(
    lexical: LexicalIndex | None = None,
) -> DozerDbMemoryAdapter:
    return DozerDbMemoryAdapter(
        graph=InMemoryGraphBackend(),
        amg=NoOpAmgPolicy(),
        temporal=InMemoryTemporalIndex(),
        lexical=lexical if lexical is not None else InMemoryLexicalIndex(),
    )


def _rrf(rank: int) -> float:
    return 1.0 / (RRF_K + rank)


class _StubSemanticPath:
    """Stubs :class:`SemanticMemoryPath` for fusion-math assertions."""

    def __init__(self, hits: list[MemoryHit]) -> None:
        self._hits = hits

    async def embed_and_upsert(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def semantic_lookup(
        self,
        query: str,
        *,
        corpus: str | None,
        limit: int,
        min_score: float,
    ) -> list[MemoryHit]:
        return list(self._hits[:limit])


# ── LexicalIndex Protocol conformance ───────────────────────────────────────


def test_inmemory_lexical_index_isinstance_lexicalindex() -> None:
    assert isinstance(InMemoryLexicalIndex(), LexicalIndex)


# ── Weight guard (ADR-085, non-bypassable) ──────────────────────────────────


@pytest.mark.asyncio
async def test_search_hybrid_rejects_weights_not_summing_to_one() -> None:
    adapter = _adapter_with_lexical()
    with pytest.raises(ValueError):
        await adapter.search_hybrid(
            "query",
            lexical_weight=0.7,
            semantic_weight=0.7,
        )


@pytest.mark.asyncio
async def test_search_hybrid_accepts_boundary_weights() -> None:
    adapter = _adapter_with_lexical()
    # Both boundary combinations are legal (guard accepts sum == 1.0).
    assert await adapter.search_hybrid(
        "q", lexical_weight=1.0, semantic_weight=0.0
    ) == []
    assert await adapter.search_hybrid(
        "q", lexical_weight=0.0, semantic_weight=1.0
    ) == []


# ── Honesty rule: NotImplementedError when lexical unwired ──────────────────


@pytest.mark.asyncio
async def test_search_hybrid_raises_when_lexical_missing() -> None:
    adapter = DozerDbMemoryAdapter(
        graph=InMemoryGraphBackend(),
        amg=NoOpAmgPolicy(),
        temporal=InMemoryTemporalIndex(),
        # lexical intentionally omitted
    )
    with pytest.raises(NotImplementedError):
        await adapter.search_hybrid("query")


# ── Lexical index side-effect wired through write_event ─────────────────────


@pytest.mark.asyncio
async def test_write_event_mirrors_into_lexical_index() -> None:
    lexical = InMemoryLexicalIndex()
    adapter = _adapter_with_lexical(lexical=lexical)

    await adapter.write_event(
        subject="agent:tektos",
        predicate="observed",
        object="repository indexing complete",
        provenance="stage-7-4-test",
        confidence=1.0,
    )

    hits = await lexical.search_lexical("repository", corpus=None, limit=5)
    assert hits, "write_event must mirror payload into the lexical index"
    assert hits[0].id  # BM25 ranking populates a hit


# ── Fusion math: lexical-only path (no semantic wired) ──────────────────────


@pytest.mark.asyncio
async def test_search_hybrid_lexical_only_returns_lexical_hits_in_order() -> None:
    lexical = InMemoryLexicalIndex()
    adapter = _adapter_with_lexical(lexical=lexical)
    # No semantic path attached; the adapter's semantic leg returns [].

    await adapter.write_event(
        subject="s1",
        predicate="p",
        object="alpha alpha alpha beta",
        provenance="t",
        confidence=1.0,
    )
    await adapter.write_event(
        subject="s2",
        predicate="p",
        object="alpha only",
        provenance="t",
        confidence=1.0,
    )

    hits = await adapter.search_hybrid(
        "alpha",
        lexical_weight=1.0,
        semantic_weight=0.0,
        limit=5,
    )

    assert len(hits) == 2
    # Fused score with lexical_weight=1.0 == rrf(rank_lex).
    assert hits[0].score == pytest.approx(_rrf(1))
    assert hits[1].score == pytest.approx(_rrf(2))
    assert hits[0].score > hits[1].score


# ── Fusion math: both legs contribute ───────────────────────────────────────


@pytest.mark.asyncio
async def test_search_hybrid_fuses_lexical_and_semantic_by_rrf() -> None:
    lexical = InMemoryLexicalIndex()
    adapter = _adapter_with_lexical(lexical=lexical)

    # Prime the lexical index directly (bypasses write_event ordering
    # ambiguity so we control the exact lexical ranking).
    now = datetime.now(timezone.utc)
    await lexical.index_event(
        "id-A",
        {"subject": "sA", "predicate": "p", "object": "keyword match A"},
        as_of=now,
    )
    await lexical.index_event(
        "id-B",
        {"subject": "sB", "predicate": "p", "object": "keyword match B"},
        as_of=now,
    )
    await lexical.index_event(
        "id-C",
        {"subject": "sC", "predicate": "p", "object": "keyword match C"},
        as_of=now,
    )

    # Attach a stub semantic path that returns a DIFFERENT ranking so we
    # can observe fusion combining both signals.
    adapter._semantic = _StubSemanticPath(
        [
            MemoryHit(
                id="id-C",  # semantically 1st, lexically last (rank 3)
                payload={"note": "semantic-payload-C"},
                score=0.9,
                as_of=now,
            ),
            MemoryHit(
                id="id-B",  # semantically 2nd, lexically 2nd
                payload={"note": "semantic-payload-B"},
                score=0.8,
                as_of=now,
            ),
        ]
    )

    hits = await adapter.search_hybrid(
        "keyword",
        lexical_weight=0.5,
        semantic_weight=0.5,
        limit=10,
    )

    scores = {h.id: h.score for h in hits}
    # ADR-085 formula, verbatim:
    #   score = lw * rrf(rank_lex) + sw * rrf(rank_sem)
    # A: lex rank 1, sem missing (0).  score = 0.5 * rrf(1)                 = 0.5 * 1/61
    # B: lex rank 2, sem rank 2.       score = 0.5 * rrf(2) + 0.5 * rrf(2)  = rrf(2)         = 1/62
    # C: lex rank 3, sem rank 1.       score = 0.5 * rrf(3) + 0.5 * rrf(1)  = 0.5*(1/63+1/61)
    expected_A = 0.5 * _rrf(1)
    expected_B = 0.5 * _rrf(2) + 0.5 * _rrf(2)
    expected_C = 0.5 * _rrf(3) + 0.5 * _rrf(1)

    assert scores["id-A"] == pytest.approx(expected_A)
    assert scores["id-B"] == pytest.approx(expected_B)
    assert scores["id-C"] == pytest.approx(expected_C)

    # Order: expected_C ≈ 0.01311... > expected_B ≈ 0.01613 > expected_A ≈ 0.0082
    # Actually compute: rrf(1)=1/61≈0.01639, rrf(2)=1/62≈0.01613, rrf(3)=1/63≈0.01587
    # expected_A = 0.5 * 0.01639 = 0.00820
    # expected_B = 0.01613
    # expected_C = 0.5 * (0.01587 + 0.01639) = 0.01613
    # Ordering: B == C > A. Both B and C are valid at rank 0/1.
    assert hits[-1].id == "id-A"
    assert {hits[0].id, hits[1].id} == {"id-B", "id-C"}


# ── Payload preference: semantic wins on id collision ───────────────────────


@pytest.mark.asyncio
async def test_search_hybrid_semantic_payload_wins_on_collision() -> None:
    lexical = InMemoryLexicalIndex()
    adapter = _adapter_with_lexical(lexical=lexical)

    now = datetime.now(timezone.utc)
    await lexical.index_event(
        "collide",
        {"subject": "s", "predicate": "p", "object": "keyword"},
        as_of=now,
    )
    adapter._semantic = _StubSemanticPath(
        [
            MemoryHit(
                id="collide",
                payload={"origin": "semantic"},
                score=0.9,
                as_of=now,
            )
        ]
    )

    hits = await adapter.search_hybrid("keyword", limit=5)
    assert len(hits) == 1
    assert hits[0].payload == {"origin": "semantic"}


# ── min_score filters on fused score ────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_hybrid_min_score_filters_on_fused_score() -> None:
    lexical = InMemoryLexicalIndex()
    adapter = _adapter_with_lexical(lexical=lexical)

    now = datetime.now(timezone.utc)
    for i in range(5):
        await lexical.index_event(
            f"id-{i}",
            {"subject": f"s{i}", "predicate": "p", "object": f"needle {i}"},
            as_of=now,
        )

    # With lexical_weight=1.0 and 5 hits, rank-r fused score = rrf(r).
    # Filter above rrf(2) leaves only the rank-1 hit.
    hits = await adapter.search_hybrid(
        "needle",
        lexical_weight=1.0,
        semantic_weight=0.0,
        min_score=_rrf(2) + 1e-9,
        limit=10,
    )
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(_rrf(1))


# ── corpus filter propagates to lexical leg ─────────────────────────────────


@pytest.mark.asyncio
async def test_search_hybrid_corpus_filters_lexical_leg() -> None:
    lexical = InMemoryLexicalIndex()
    adapter = _adapter_with_lexical(lexical=lexical)

    now = datetime.now(timezone.utc)
    await lexical.index_event(
        "in-corpus",
        {
            "subject": "s",
            "predicate": "p",
            "object": "shared token",
            "attributes": {"corpus_name": "alpha"},
        },
        as_of=now,
    )
    await lexical.index_event(
        "out-corpus",
        {
            "subject": "s",
            "predicate": "p",
            "object": "shared token",
            "attributes": {"corpus_name": "beta"},
        },
        as_of=now,
    )

    hits = await adapter.search_hybrid(
        "shared",
        corpus="alpha",
        lexical_weight=1.0,
        semantic_weight=0.0,
        limit=10,
    )
    assert [h.id for h in hits] == ["in-corpus"]


# ── limit truncates the fused list ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_hybrid_limit_truncates_fused_output() -> None:
    lexical = InMemoryLexicalIndex()
    adapter = _adapter_with_lexical(lexical=lexical)

    now = datetime.now(timezone.utc)
    for i in range(10):
        await lexical.index_event(
            f"id-{i}",
            {"subject": f"s{i}", "predicate": "p", "object": f"target {i}"},
            as_of=now,
        )

    hits = await adapter.search_hybrid(
        "target",
        lexical_weight=1.0,
        semantic_weight=0.0,
        limit=3,
    )
    assert len(hits) == 3
