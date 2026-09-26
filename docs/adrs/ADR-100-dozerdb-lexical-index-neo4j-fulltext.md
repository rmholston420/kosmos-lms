# ADR-100 — `DozerDbLexicalIndex` (Neo4j Lucene fulltext-backed `LexicalIndex`)

**Status:** Ratified (2026-09-10)
**Locked:** ADR-145 (2026-09-26) — Stage 14 program freeze; this ADR is locked (see ADR-145).
**Lock-in phase:** Stage 7.4+1
**Supersedes:** —

## Context

ADR-099 D4 deferred the production `LexicalIndex` implementation to a
follow-on slice so that Stage 7.4 could land the port contract + RRF
fusion math against a deterministic in-memory backend
(`InMemoryLexicalIndex`, BM25-Okapi, k1=1.5, b=0.75) first. That work
shipped as commit `48e14ed` (Stage 7.4 LANDED). Stage 7.4+1 is chartered
to land the production adapter.

The production lexical lane must:

1. Persist across process restarts (BM25 statistics survive restart).
2. Answer `search_lexical(query, corpus, limit)` in **O(log N)** on the
   corpus size, not O(N) — the in-memory backend's linear scan is
   acceptable at test scale but not at 10⁵+ events.
3. Reuse the DozerDB Bolt driver already vendored in Stage 1.8
   (`neo4j>=5.26` in `pyproject.toml`), so no new backend dependency
   lands in Stage 7.4+1.
4. Return `MemoryHit`s that RRF-fuse with the `SemanticMemoryPath`
   results on hit identity (i.e., the same `event_id` used across
   both lanes). Absolute scores may differ (Lucene scoring ≠ BM25-Okapi
   pure-Python), but rank *ordering* is what matters for RRF (per
   ADR-099 rationale on shape-compatibility).
5. Preserve the ADR-099 D3 boundary: `LexicalIndex` is
   **adapter-scoped**, not a formal port under `ports/`. Plugins never
   import it. It stays inside `adapters/memory/dozerdb/` symmetric with
   `GraphBackend` and `TemporalIndex`. ADR-007 + ADR-027 forbid any
   plugin bypass of `MemoryPort`.

Neo4j-community (and DozerDB's permissive fork of it) ships a Lucene
fulltext index primitive:

- **Creation:** `CREATE FULLTEXT INDEX <name> IF NOT EXISTS FOR (n:Label) ON EACH [n.prop1, n.prop2]`
- **Query:** `CALL db.index.fulltext.queryNodes($name, $query) YIELD node, score`
- **Corpus filtering:** downstream `WHERE` on `node.corpus_name` after
  the `YIELD`, since fulltext indexes do not natively support
  attribute-scoped subsets.

DozerDB 5.26.x is Bolt-compatible with Neo4j 5.26 and supports the same
`db.index.fulltext.*` procedures (verified against DozerDB docs; if the
Cypher call fails on the live tier, it's a DozerDB compatibility bug,
not a Kosmos contract violation — the port-level guard would surface it
via the `is_healthy() == False` path).

## Decision

Six governing decisions.

### D1 — Adapter shape mirrors `DozerDbGraphBackend`

Land `adapters/memory/dozerdb/dozerdb_lexical_index.py` as a class named
`DozerDbLexicalIndex` implementing the `LexicalIndex` Protocol from
`adapters.memory.dozerdb.adapter`. It follows the same construction
pattern as `DozerDbGraphBackend` — eager driver build via lazy
`neo4j.AsyncGraphDatabase` import, `_init_error` string surface,
sync + non-throwing `is_healthy`, idempotent async `close` that
swallows driver errors into a warning log.

Signature:

```python
class DozerDbLexicalIndex:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        database: str = "neo4j",
        label: str = "MemoryEvent",
        index_name: str = "memory_event_fulltext",
    ) -> None: ...

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
    def is_healthy(self) -> bool: ...
```

`label` and `index_name` are constructor-tunable so a multi-tenant
DozerDB instance can host multiple Kosmos deployments without stomping
on one another's indexes. Both are validated with the same
`_validate_identifier` regex `DozerDbGraphBackend` uses; injection guard
is non-optional.

### D2 — Idempotent bootstrap on first write, not at construction

`__init__` builds the driver but does **not** create the fulltext index.
The first `index_event` call executes:

```cypher
CREATE FULLTEXT INDEX $index_name IF NOT EXISTS
FOR (n:MemoryEvent) ON EACH [n.text]
```

behind a `self._index_ready` flag, then proceeds with the `MERGE`. This
avoids a construction-time network call (matches `DozerDbGraphBackend`
which is lazy about connecting) and makes the adapter safe to
instantiate in unit tests that never hit `index_event`. `IF NOT EXISTS`
is the standard Neo4j idempotency guard — repeated bootstraps are cheap
no-ops.

Note the parameter substitution restriction: `CREATE FULLTEXT INDEX`
does **not** accept `$name` for the index name — the name must appear
literally in the Cypher string. This is why D1 mandates the
`_validate_identifier` guard on `index_name`; the guard is what makes
literal interpolation safe. `db.index.fulltext.queryNodes` accepts the
index name as a string parameter — no interpolation needed there.

### D3 — `index_event` writes a single flat text property + optional corpus

```cypher
MERGE (n:MemoryEvent {id: $id})
SET n.text = $text,
    n.as_of = datetime($as_of_iso),
    n.corpus_name = $corpus
```

Where:
- `$id = event_id` (idempotent write; re-indexing an event overwrites).
- `$text = "{subject} {predicate} {object}"` — the same concatenation
  `InMemoryLexicalIndex` tokenises. Extraction lives in a shared
  helper (moved from `adapter.py` into a module-level function so both
  backends use identical text) to guarantee tokenisation parity.
- `$as_of_iso = as_of.isoformat()` — Neo4j `datetime()` constructor
  accepts ISO-8601.
- `$corpus = payload["attributes"]["corpus_name"]` or `None`.
  `SET n.corpus_name = null` removes the property (matching the
  in-memory backend's "no corpus" semantics).

The fulltext index is defined on `[n.text]` only — corpus filtering
happens post-YIELD in `search_lexical`. This keeps the index single-purpose
(Lucene tokenisation over one field) and avoids the multi-field-fulltext
ranking-normalisation quirk where a term-hit in one field can outweigh a
term-hit in another.

### D4 — `search_lexical` uses `db.index.fulltext.queryNodes` with post-YIELD corpus filter + payload rehydration

```cypher
CALL db.index.fulltext.queryNodes($index_name, $query) YIELD node, score
WHERE $corpus IS NULL OR node.corpus_name = $corpus
RETURN node.id AS id,
       node.text AS text,
       node.corpus_name AS corpus_name,
       node.as_of AS as_of,
       score
ORDER BY score DESC
LIMIT $limit
```

The `MemoryHit.payload` is reconstructed as a **minimal** dict:

```python
{
    "text": row["text"],
    "attributes": {"corpus_name": row["corpus_name"]} if row["corpus_name"] else {},
}
```

This is intentional. The in-memory backend stores the full original
payload because it's a test backend; the real backend only persists what
the fulltext index needs. Full payload rehydration is `MemoryPort`'s
job via a separate `query_temporal` — the `search_hybrid` fusion path in
`DozerDbMemoryAdapter` already handles this: when a hit appears in both
legs, the semantic-side payload wins on id collision (ADR-085 rule +
ADR-099 D2 restated). Lexical-only hits get the minimal shape;
downstream callers that need the full triple must re-read via
`query_temporal`. This is the same contract `DozerDbGraphBackend` offers
for graph queries — nodes carry their properties, and callers rehydrate
richer views separately.

Query pre-processing: Lucene syntax passes through unchanged — callers
may pass a raw query like `"agent AND (planner OR router)"` and Lucene
will honour it. If a caller passes a raw user string containing Lucene
reserved characters (`+ - && || ! ( ) { } [ ] ^ " ~ * ? : \ /`), Lucene
may raise. Kosmos does **not** escape at this layer; sanitisation is a
plugin concern (the plugin knows whether its query is Lucene-syntax or
user-typed). If a `neo.ClientError.Procedure.ProcedureCallFailed`
surfaces, `search_lexical` catches it, logs a `warning`, and returns
`[]` — this matches the "log-only" side-effect discipline established
for lexical writes in `DozerDbMemoryAdapter.write_event` (ADR-099
implementation).

### D5 — Two test tiers: fast (mocked driver) + live (env-gated real DozerDB)

Mirrors `DozerDbGraphBackend`'s test discipline exactly:

- **Fast tier:** `adapters/memory/dozerdb/test_dozerdb_lexical_index_contract.py`
  uses the same `_FakeDriver`/`_FakeSession`/`_install_fake_neo4j`
  pattern from `test_dozerdb_graph_backend_contract.py`. Verifies:
  Protocol conformance, identifier guard, bootstrap-then-index Cypher
  shape, `search_lexical` Cypher shape, corpus filter propagation,
  `MemoryHit` payload rehydration, close idempotency, `is_healthy`
  after close, `ProcedureCallFailed` degrades to `[]`.
- **Live tier:** env-gated `KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL=1`
  (new; sibling of `KOSMOS_STAGE_42_LIVE`). Skipped by default so the
  fast suite stays hermetic. Uses `MEMORY_BOLT_URI`/`MEMORY_BOLT_USER`/
  `MEMORY_BOLT_PASSWORD` env vars (same as the graph backend live tier)
  and asserts an end-to-end round trip: bootstrap → `index_event(three docs)`
  → `search_lexical("token", corpus=None)` returns ordered hits →
  `search_lexical("token", corpus="alpha")` filters correctly →
  cleanup.

### D6 — Ledger flip + spec fan-out; no `LexicalIndex` Protocol changes

The `LexicalIndex` Protocol shape locked in ADR-099 D3 is **not**
changed by this ADR. `DozerDbLexicalIndex` conforms to it as-is. The
Protocol is deliberately narrow (three methods + close/health) so that
`DozerDbLexicalIndex` is a drop-in replacement for `InMemoryLexicalIndex`
in `DozerDbMemoryAdapter.__init__(lexical=…)`.

Boot-time wiring for `ZetesisPlugin`'s DozerDB factory is **not** in
this slice. That is Stage 7.4+2 — kernel boot needs to grow the ability
to inject `DozerDbLexicalIndex` with the correct Bolt credentials, and
that touches the plugin factory contract, which deserves its own ADR
review. This slice ships the adapter + tests only; the factory keeps
its current opt-in `lexical=` kwarg (defaults to `None`).

## Rationale

**Why not skip Stage 7.4+1 and jump to boot-wiring.** The adapter and
the wiring are separable concerns. Landing the adapter first lets us
prove Cypher-shape correctness against a fast + live tier without
touching the factory contract. Wiring at boot without a proven adapter
would tangle two failure modes (adapter Cypher wrong vs. factory
signature wrong) and slow diagnosis.

**Why post-YIELD corpus filter, not two indexes per corpus.** Multi-index
approaches scale poorly with corpus count (each corpus adds a fulltext
index; index rebuild cost is O(corpus_events)). Post-YIELD filter costs
a single `WHERE` clause and Lucene's `queryNodes` returns hits with
associated node properties in one round-trip. If Tektos ever grows to
100+ corpora, the post-YIELD filter degrades to a bloom-filter shape
lookup — but that concern is >3 stages out and would require its own ADR.

**Why not pre-compute BM25 in the adapter to match `InMemoryLexicalIndex`
scores.** RRF depends only on rank ordering, not absolute scores.
Lucene's default BM25 similarity (Neo4j 5.x default) with parameters
k1=1.2, b=0.75 gives *different absolute scores* than the in-memory
backend's BM25-Okapi (k1=1.5, b=0.75), but the relative rank ordering on
the same corpus with the same query converges once documents outnumber
query terms by a wide margin (which is the normal operating regime).
`RRF_K = 60` from ADR-085 further damps rank-position sensitivity. This
is why ADR-099 D4 called out "shape-compatibility" as sufficient.

**Why raise for `ProcedureCallFailed` → return `[]`, not propagate.**
Lexical retrieval is a best-effort input to fusion. When Lucene can't
parse the query, the semantic leg alone still delivers value. This is
symmetric with the "log-only" discipline on `write_event`'s lexical
mirror side-effect (ADR-099 implementation) and with
`search_semantic` returning `[]` when the semantic lane is unwired
(ADR-074 D3). What we do **not** do: silently degrade the fused result
without any signal. The `log.warning` at the failure site is the
signal.

**Why validate `label` + `index_name` via the graph backend's identifier
regex.** `CREATE FULLTEXT INDEX` requires literal interpolation of the
index name (no parameter substitution). Any user-controlled string
reaching that Cypher literal is a Cypher-injection vector. The regex
`^[A-Za-z_][A-Za-z0-9_]*$` matches Neo4j's identifier grammar exactly
and shrinks the injection surface to zero. This is the same guard
`DozerDbGraphBackend` uses for node labels + relationship types (per
ADR-047 rationale).

**Alternatives considered:**

1. **SQLite FTS5 backend instead of DozerDB fulltext.** Rejected: adds
   a new backend dependency (SQLite + FTS5 tokeniser), requires a
   separate persistence lifecycle, and does not benefit from the
   already-vendored DozerDB driver. Would score worse under the
   `kosmos-port-workflow` "would this add complexity we do not need?"
   test.
2. **Elasticsearch backend.** Rejected: adds a JVM service to the
   Kosmos infrastructure footprint, violates the "self-hosted +
   Colossus-runnable" preference on the marginal complexity axis (a
   Docker container per lexical retrieval request), and duplicates
   DozerDB's fulltext capability.
3. **Wire boot-time injection in this slice.** Rejected: touches the
   `ZetesisPlugin` factory contract which is co-owned by other Stage 6
   consumers; deserves a dedicated ADR after this adapter proves out.
4. **Multi-corpus multi-index design.** Rejected: does not scale in
   the number of corpora; post-YIELD filter is O(hits) at query time
   and O(1) at write time; single-index design is the standard Neo4j
   pattern.
5. **Store the original triple as `subject`, `predicate`, `object`
   properties on the node and use a multi-field fulltext index.**
   Rejected: multi-field fulltext scoring has field-boost quirks
   (Lucene normalises TF by field length) and would produce results
   that diverge from `InMemoryLexicalIndex` on the same corpus.
   Single-`text` field keeps parity.

## Consequences

**Files changed:**

- **New:** `docs/adrs/ADR-100-dozerdb-lexical-index-neo4j-fulltext.md` (this file).
- **New:** `adapters/memory/dozerdb/dozerdb_lexical_index.py` (the adapter).
- **New:** `adapters/memory/dozerdb/test_dozerdb_lexical_index_contract.py` (fast + live tier).
- **Modified:** `adapters/memory/dozerdb/adapter.py` — extract shared text-concatenation helper (`_lex_text_from_payload`) so both backends tokenise identical text.
- **Modified:** `adapters/memory/dozerdb/__init__.py` — export `DozerDbLexicalIndex`.
- **Modified:** `PORTING_LEDGER.md` — flip `DozerDbLexicalIndex` row from `PLANNED (Stage 7.4+1)` to `VENDORED (Stage 7.4+1)` with ADR-100 reference.
- **Modified:** `docs/Kosmos-Build-Sequence-v26.md` — add Stage 7.4+1 stanza with LANDED marker.
- **Modified:** `docs/adrs/README.md` — ADR-100 row appended; "Remaining open decisions" paragraph updated.
- **Modified:** `BUILD_LOG.md` — one entry per completed step.
- **Modified:** `SESSION_HANDOFF.md` — overwritten at session end.

**Downstream effects:**

- `DozerDbLexicalIndex` is drop-in wireable via `DozerDbMemoryAdapter(lexical=DozerDbLexicalIndex(...))`. Zero changes needed to `search_hybrid` — the Protocol contract is unchanged.
- Boot-time wiring for the `ZetesisPlugin` factory becomes the natural Stage 7.4+2 slice; a fresh ADR will land alongside that work.
- The live-tier env var `KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL=1` joins the existing `KOSMOS_STAGE_42_LIVE=1` in the opt-in-tier catalog.

## Lock-in phase

Stage 7.4+1.

## References

- `Kosmos-Build-Spec-v26.md` §17 (ADR summary), §25 (Tektos absorption), §25.3 (H1/H2 status amendment)
- `Kosmos-Build-Sequence-v26.md` — Stage 7.4+1 stanza (added by this ADR)
- ADR-085 (`MemoryPort.search_hybrid` surface + RRF formula)
- ADR-099 (Stage 7.4 re-scope; ships `LexicalIndex` Protocol + `InMemoryLexicalIndex`)
- ADR-027 (MemoryPort as the singular plugin-facing memory contract)
- ADR-007 (events-only cross-plugin coupling; forbids plugin bypass of MemoryPort)
- ADR-047 (Cypher-injection guard for graph backend identifiers)
- `PORTING_LEDGER.md` — DozerDB adapter row (Stage 1.8), `search_hybrid` VENDORED row (Stage 7.4), `DozerDbLexicalIndex` VENDORED row (Stage 7.4+1)
- Neo4j Cypher fulltext-index docs: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/
