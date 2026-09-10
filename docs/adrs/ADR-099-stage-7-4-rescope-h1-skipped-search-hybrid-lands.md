# ADR-099 — Stage 7.4 re-scope: H1 skipped, `search_hybrid` lands on `DozerDbMemoryAdapter`

**Status:** Ratified
**Lock-in phase:** Stage 7.4
**Amends:** ADR-085 (`MemoryPort.search_hybrid`) — lock-in phase clarified: the *adapter method* lands at Stage 7.4 (surface locked at Stage 1.3 is unchanged). Also amends `Kosmos-Build-Spec-v26.md` §25.3 (H1 → H2 migration) and `Kosmos-Build-Sequence-v26.md` Stage 7.4 charter to reflect that H1 (`adapters/memory/hindsight_bridge/`) was never landed.

## Context

The Stage 7.4 charter written into `Kosmos-Build-Sequence-v26.md` reads: *"hindsight data migrated into DozerDB via a one-shot migration script … `adapters/memory/hindsight_bridge/` retired … hindsight port `:9000` released."* The charter assumes **H1** (hindsight-bridge adapter) landed in Stages 3–5 per `Kosmos-Build-Spec-v26.md` §25.3.

**Verification against the repo at commit `532b309` shows H1 never landed:**

- `adapters/memory/hindsight_bridge/` **does not exist** (`ls` returns "No such file or directory").
- `PORTING_LEDGER.md` line 471 still reads `#### Tektos hindsight memory (bridge adapter) — PLANNED (Stage 3-5)`; the row never flipped to `VENDORED`.
- No Python module in the repo imports `hindsight` — only doc strings and ADR rationale mention it (`ports/memory.py` docstring; `ports/event_envelope.py` docstring; several ADR files).
- `pyproject.toml` has no `hindsight_bridge` entry.
- `BUILD_LOG.md` records no hindsight-bridge port-in step across Stages 3.13, 4.7, 4.8, 5.6, 6.5, or 6.6.
- `plugins/tektos/agent.py` writes and reads exclusively via `MemoryPort` (i.e. the DozerDB adapter) — see `self.memory.write_event` (line 161), `self.memory.query_temporal` (line 218).

**Why H1 was skipped (post-hoc reconstruction from BUILD_LOG + ADR trail):** Stage 3.13 (ADR-092) absorbed the Tektos runtime with explicit exclusions of every hindsight-adjacent runtime module. Stage 4.7 (ADR-093) absorbed sandbox + planner + tools with hindsight not on the DoD. Stage 5.6 (ADR-095) shipped propose-only self-improve/self-repair without invoking hindsight. Tektos's Kosmos-ported agent path went directly to `MemoryPort.write_event` / `query_temporal` from Stage 3.2 onward, which turned out to be sufficient for every subsequent Tektos slice. The H1 detour was never blocking, so it was not built. This is consistent with the user preference "informed optimal choices and forward progress" — the team correctly walked past H1 when the substitute (direct DozerDB via `MemoryPort`) proved sufficient, but the spec was not amended to record the walk-past.

**Independent evidence — the 6 pre-existing test failures:** `adapters/memory/dozerdb/test_contract.py::test_adapter_isinstance_memoryport` and its five siblings across `plugins/tektos/tests/` and `plugins/zetesis/tests/` all assert `isinstance(<adapter>, MemoryPort)` on a `runtime_checkable` Protocol. They fail with `assert False` because `DozerDbMemoryAdapter` implements every `MemoryPort` method **except** `search_hybrid`. These are not "protocol-drift" failures — they are one failure repeated across 6 test files, all pointing at the same missing adapter method. Landing `search_hybrid` resolves all 6.

**What Stage 7.4 substantively lands, then, is exactly ADR-085's promise:** the `search_hybrid` adapter method on `DozerDbMemoryAdapter`, so `MemoryPort`'s Protocol conformance is complete. There is no migration to run and no bridge to retire.

## Decision

### D1 — Retire the H1 detour on paper

- `PORTING_LEDGER.md`'s `#### Tektos hindsight memory (bridge adapter) — PLANNED (Stage 3-5)` row is flipped to `EVALUATED-REJECTED (Stage 3-5, skipped as contingency)` with rationale citing ADR-099 §Context.
- `Kosmos-Build-Spec-v26.md` §25.3 gets a `> **STATUS AMENDMENT (2026-09-10, ADR-099):**` block at the top of the H1/H2 subsection recording that H1 was never built and H2 collapses into "land `search_hybrid`".
- No repo state changes for retirement — nothing to delete, nothing to release.

### D2 — Stage 7.4 substantively lands `search_hybrid` on `DozerDbMemoryAdapter`

Add a new `MemoryPort` adapter method `search_hybrid` on `adapters/memory/dozerdb/adapter.py::DozerDbMemoryAdapter` implementing the ADR-085 contract verbatim:

- Fuses `search_semantic` (semantic leg, ADR-074) with a new lexical leg via Reciprocal Rank Fusion, `k=60` (constant per ADR-085).
- Fused score: `score(h) = lexical_weight * rrf(rank_lex(h)) + semantic_weight * rrf(rank_sem(h))`, `rrf(r) = 1/(k+r)`, missing legs contribute `0`.
- Calls `ports.memory.validate_hybrid_weights(lexical_weight, semantic_weight)` first — non-bypassable.
- Filters by `min_score` (fused, post-fusion).
- Merges hits by `MemoryHit.id`; when the same id appears in both legs, the payload is taken from the semantic leg (preserves the richer payload structure `SemanticMemoryPath` returns).

### D3 — Lexical leg wired as an optional `LexicalIndex` dependency (ADR-074 wiring style)

- Introduce a new `LexicalIndex` Protocol on `adapters/memory/dozerdb/adapter.py` (adapter-scoped, **not** a formal Kosmos port — it is composed inside the DozerDB adapter, symmetric with the existing adapter-scoped `TemporalIndex` and `GraphBackend` Protocols).
- Wire it via a new `lexical: LexicalIndex | None = None` kwarg on `DozerDbMemoryAdapter.__init__` (mirrors the `embeddings: EmbeddingsPort | None` + `vector: VectorPort | None` wiring pattern established by ADR-074 D3).
- When `_lexical is None`, `search_hybrid` **raises `NotImplementedError`** per ADR-085's rule — no silent degrade to semantic-only.
- When `_lexical is not None` **but** `self._semantic is None`, `search_hybrid` still runs — the semantic leg contributes an empty ranked list and RRF collapses to `lexical_weight * rrf(lex_rank)`.

Rationale for adapter-scoped Protocol (not a formal port under `ports/`):
- Symmetric with `GraphBackend` and `TemporalIndex`, which are already declared inside `adapters/memory/dozerdb/adapter.py` (lines 128 and 217) and never lifted to `ports/`.
- `MemoryPort` is the single plugin-visible surface (ADR-027 rule). Composition inside the adapter is an implementation detail; introducing `ports/lexical.py` would let plugins bypass `MemoryPort`, which ADR-007 and ADR-027 forbid.

### D4 — In-memory lexical index ships now; real DozerDB backend deferred to Stage 7.4+1

- `InMemoryLexicalIndex` ships inside `adapters/memory/dozerdb/adapter.py` alongside `_InMemoryGraphBackend` and `InMemoryTemporalIndex`. Tokenizes over subject/predicate/object using a lowercased-whitespace-plus-punctuation regex; scores using **BM25-Okapi** (`k1=1.5`, `b=0.75`) computed in pure Python. Returns `list[MemoryHit]` ranked descending, with `score` = BM25 score.
- Contract tests use it end-to-end (no external service, no network).
- The **real** `DozerDbLexicalIndex` — wrapping a Neo4j Lucene fulltext index over the `MemoryEvent` label — lands in a follow-up slice (Stage 7.4+1) after a benchmark against the in-memory implementation on a representative Tektos corpus. This mirrors the Stage 6.5 pattern where `NoOpVoiceAdapter` shipped before `FasterWhisperVoiceAdapter`, and the real vision-Ollama adapter shipped without a formal fulltext-index dependency.
- The real production wiring must supply a `DozerDbLexicalIndex` (or accept `NotImplementedError` on `search_hybrid`); Tektos slices that need hybrid retrieval will not deploy until the real lexical index lands. This is enforced by ADR-085's `NotImplementedError` rule — Tektos code that calls `search_hybrid` without a wired lexical index gets an immediate failure, not silent degrade.

### D5 — No changes to `MemoryPort` Protocol surface

ADR-085 already added the `search_hybrid` method on `MemoryPort` (Stage 1.3 surface lock). This ADR does not touch the port. It lands the adapter implementation. Zero changes to `ports/memory.py`.

### D6 — Contract-test coverage locked

New tests land alongside the adapter change:

- `adapters/memory/dozerdb/test_search_hybrid_contract.py` — unit tests for the fusion math (RRF constants, weight boundary conditions, missing-leg handling, min_score filter, `NotImplementedError` when lexical unwired) using `InMemoryLexicalIndex` + a stub semantic path.
- The 6 pre-existing `test_*_isinstance_memoryport` / `test_*_conforms_to_memoryport_protocol` failures across the repo flip from **FAIL** to **PASS** as a side effect. Baseline (1420 pass / 6 fail / 14 skip) advances to (**1420 + N_new_tests + 6 fixed** pass / **0 fail** / 14 skip). This is the first Stage-N session in the entire Kosmos history that walks away with **zero pre-existing failures**.

## Rationale

**Why re-scope rather than execute the charter verbatim.** Executing the charter would flip a `PLANNED` PORTING_LEDGER row directly to `RETIRED` without an intervening `VENDORED` state, would run a "migration script" that migrates zero rows, and would "release" a port that was never opened. Per `kosmos-port-workflow` §Stop conditions, this is a stop-and-escalate situation: the vendor step never happened, so retirement is not the shape of the work. The correct move under `kosmos-adr-authoring` §"Amending an ADR when contingency triggered" is a new ADR that records the reality and re-plans.

**Why not build `hindsight_bridge` first and then migrate.** Stages 3–5 are done and shipped. Building H1 now would be pure retrofit: Tektos already reads and writes via DozerDB `MemoryPort` in production paths. Injecting a bridge adapter, migrating data through it, then immediately migrating it back would be work for its own sake. The user preference "informed optimal choices and forward progress" and the `kosmos-port-workflow` §Stop condition on "would this add complexity we do not need?" both point at "no."

**Why the RRF constant `k=60`.** ADR-085 mandates it. This ADR does not re-open the choice.

**Why BM25-Okapi for the in-memory lexical index.** Standard, well-understood, reproducible in pure Python without an external index dependency. Matches what a Neo4j Lucene fulltext index computes on the wire, so `search_hybrid` results should be *shape-compatible* between the in-memory index and the future real backend (fused rankings agree on identity of top-k; absolute BM25 scores differ, but RRF depends only on rank order).

**Why no ADR-085 status change.** ADR-085 is Ratified with lock-in "Stage 7.4 (surface locked at Stage 1.3; adapter lands at Stage 7.4)." This ADR fulfills that lock-in exactly. A status amendment block on ADR-085 is not needed; ADR-099 supersedes only the H1/H2 migration mechanism, not the `search_hybrid` surface.

**Alternatives considered:**

1. **Execute charter verbatim.** Rejected: no data to migrate, no adapter to retire, no port to release. Result would be a fake step in BUILD_LOG.
2. **Land `hindsight_bridge` first (retroactive H1) then migrate (H2).** Rejected: pure retrofit; Tektos already talks DozerDB; violates "forward progress" preference; violates `kosmos-port-workflow` "would this add complexity we do not need?"
3. **Land `search_hybrid` without an ADR** (treat as a bug fix). Rejected: this reshapes Stage 7.4 scope from "migrate + retire" to "extend adapter surface," which is structural per `kosmos-spec-diff` §2 — requires an ADR.
4. **Ship real `DozerDbLexicalIndex` (Neo4j fulltext) in this stage.** Rejected: requires a running Neo4j-community DozerDB, a fulltext-index creation migration, and a benchmark harness — all out of scope for a single slice. Landing the in-memory index first + deferring the real one to Stage 7.4+1 matches the pattern used for `FasterWhisperVoiceAdapter` (ships behind an env-tunable model, benchmark comes later) and for `OllamaQwenVLVisionAdapter` (ships with a placeholder confidence, calibration deferred).

## Consequences

**Files changed:**

- **New:** `docs/adrs/ADR-099-stage-7-4-rescope-h1-skipped-search-hybrid-lands.md` (this file).
- **New:** `adapters/memory/dozerdb/test_search_hybrid_contract.py`.
- **Modified:** `adapters/memory/dozerdb/adapter.py` — adds `LexicalIndex` Protocol, `InMemoryLexicalIndex` test backend, `lexical` kwarg on `DozerDbMemoryAdapter.__init__`, `search_hybrid` method.
- **Modified:** `PORTING_LEDGER.md` — flips `hindsight_bridge` row to EVALUATED-REJECTED (H1 skipped) with ADR-099 reference; flips `search_hybrid` PLANNED row (currently implicit in ADR-085 body) into an explicit VENDORED row.
- **Modified:** `docs/Kosmos-Build-Sequence-v26.md` — Stage 7.4 stanza rewritten with LANDED marker (2026-09-10 · ADR-099) recording the re-scoped substantive work.
- **Modified:** `docs/Kosmos-Build-Spec-v26.md` — `> **STATUS AMENDMENT (2026-09-10, ADR-099):**` block on §25.3 recording that H1 was never built.
- **Modified:** `docs/adrs/README.md` — ADR-099 row appended; "Remaining open decisions" sentence unchanged (still ADR-090 + TTS engine selection).
- **Modified:** `BUILD_LOG.md` — one entry per completed step per `kosmos-log-maintenance`.
- **Modified:** `SESSION_HANDOFF.md` — overwritten at session end.

**Downstream effects:**

- The 6 pre-existing "MemoryPort protocol-drift" failures resolve. All future stages inherit a clean baseline.
- `DozerDbMemoryAdapter` is now fully `MemoryPort`-Protocol-conformant under `runtime_checkable`.
- Any plugin that wants hybrid retrieval must ensure the real DozerDB wiring supplies a `LexicalIndex`; ADR-085's `NotImplementedError` rule surfaces this loudly rather than silently.
- Stage 7.4+1 slice: land `DozerDbLexicalIndex` wrapping a Neo4j Lucene fulltext index. Its PORTING_LEDGER row is added as `PLANNED (Stage 7.4+1)` at the same time this ADR ratifies.

**ADR-085 lock-in phase:** unchanged. This ADR fulfills ADR-085's promise; it does not amend the surface.

## Lock-in phase

Stage 7.4 (this session, 2026-09-10).

## References

- ADR-085 (`MemoryPort.search_hybrid` surface — Stage 1.3 lock)
- ADR-074 (semantic memory lane wiring — dependency-injection style that D3 mirrors)
- ADR-027 (MemoryPort full surface — plugin-visible interface)
- ADR-008 (DozerDB as canonical memory store)
- ADR-007 (events-only cross-plugin coupling — reason `LexicalIndex` stays adapter-scoped)
- `Kosmos-Build-Sequence-v26.md` Stage 7.4 stanza (lines 527-531 pre-amendment)
- `Kosmos-Build-Spec-v26.md` §25.3 H1/H2 migration plan (pre-amendment)
- `PORTING_LEDGER.md` `#### Tektos hindsight memory (bridge adapter) — PLANNED (Stage 3-5)` row (pre-amendment)
- Verification commit: `532b309` (Stage 6.5 landing — clean baseline for Stage 7.4 work)
