# ADR-085 — MemoryPort surface extension: `search_hybrid`

**Status:** Ratified
**Lock-in phase:** Stage 7.4 (surface locked at Stage 1.3; adapter lands at Stage 7.4)
**Amends:** ADR-027 (MemoryPort full surface — extends without removing existing methods)

## Context

ADR-027 locked `MemoryPort` with `write_event`, `query_temporal`, `link_entities`, `quarantine_write`, `list_quarantined`, `approve_quarantined`, `reject_quarantined`, `search_semantic` (ADR-074), and adjacent surfaces. Tektos-Ultima's hindsight system relies on hybrid (BM25 lexical + vector semantic) retrieval, tuned to code and coding-agent traces. When hindsight retires at Stage 7.4 (per §25.3 H1 → H2), Tektos must have an equivalent retrieval surface on `MemoryPort`.

`search_semantic` (ADR-074) covers pure vector retrieval. `query_temporal` covers timeline scans. Neither covers hybrid rank fusion (RRF or weighted).

## Decision

Extend `MemoryPort` with **`search_hybrid`**:

```python
async def search_hybrid(
    self,
    query: str,
    *,
    corpus: str,
    limit: int = 20,
    lexical_weight: float = 0.5,
    semantic_weight: float = 0.5,
    min_score: float | None = None,
) -> tuple[MemoryHit, ...]: ...
```

### Contract

1. Returns `MemoryHit` tuples (existing value object from ADR-027) with `score` set to the fused rank.
2. `lexical_weight + semantic_weight` MUST sum to 1.0. Port-level guard raises `ValueError` otherwise.
3. Both weights ≥ 0.0; a weight of 0.0 makes the call equivalent to the opposite pure-search.
4. Uses Reciprocal Rank Fusion (RRF, k=60) by default; adapter MAY substitute a different fusion but MUST document it.
5. Adapters lacking a lexical index MUST raise `NotImplementedError` (rather than silently degrading to pure semantic).

## Rationale

- **Hybrid over pure semantic**: Tektos-Ultima's hindsight tuning shows lexical scoring is essential for code retrieval (variable names, error message strings) where pure vector search under-performs.
- **RRF over score-fusion**: score fusion requires per-corpus calibration; RRF is calibration-free.
- **Weights as caller parameters** rather than adapter-fixed: same adapter serves different plugins (Tektos favors lexical; Zetesis favors semantic).
- **NotImplementedError over silent degradation**: matches the fail-loud convention used elsewhere in the port surface; callers that want pure semantic should call `search_semantic` explicitly.

## Consequences

- Files edited (this ADR): `ports/memory.py` (extend Protocol + add value-object docs; port-level guard for weight sum). Existing `search_semantic` unchanged.
- Files edited (Stage 7.4): `adapters/memory/dozerdb/` adapter implements `search_hybrid` composing DozerDB full-text index + Qdrant vector search via `SemanticMemoryPath`.
- `PORT_CONTRACTS.md` `MemoryPort` row extended with `search_hybrid` in the surface list.
- No existing method is removed; existing callers unaffected.

## Lock-in phase

Locked at Stage 1.3 (surface); adapter locked at Stage 7.4.

## References

- ADR-027 (MemoryPort full surface — this amends)
- ADR-074 (semantic memory + graph visualization — `search_semantic` parent)
- ADR-026 (VectorPort backend)
- ADR-077, ADR-078 (v26 §25.3 hindsight H1 → H2)
