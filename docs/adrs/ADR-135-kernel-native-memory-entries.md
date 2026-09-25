# ADR-135: kernel-native memory entries endpoint (`GET /api/memory`)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.19 (endpoint split, memory family)
- **Supersedes:** none

## Context

The ops MemoryTab (`ui/app/tektos-ultima/ops/page.tsx`) proxied three
calls to the *standalone* Tektos engine (`:8020`): `GET /api/memory`
(tiered entries list), `GET /api/memory/stats`, and `POST
/api/memory/decay`. The standalone referent is a **4-tier cognitive
store** — working/long_term/procedural + FTS5 search + `decay_all()`
value-function demotion (`tektos-ultima-v1/src/tektos/main.py`
L2294–2346).

The kernel does **not** implement that store. Its `registry.memory`
(`DozerDbMemoryAdapter`, `KOSMOS_MEMORY_BACKEND=dozerdb`) is a graph of
`MemoryEvent` nodes (subject/predicate/object triples, zero-trust
writes, AMG guard, semantic/hybrid/lexical lanes) — no tiers, no decay
value function, no FTS. ADR-123 already made `/api/memory/stats`
kernel-native on this basis and documented the divergence verbatim in
`kernel/app.py`: "a 4-tier cognitive store … the kernel does not
implement."

**User decision (2026-09-25):** the 4-tier store is *Tektos cognitive
policy*, not neutral substrate — it stays plugin-level. The shared
memory substrate (graph + retrieval lanes) already exists at kernel
level and is strictly more general; tiers are expressible as a
`tier` attribute on MemoryEvent. Tier-assignment rules + the decay
value function + dreamtime reflection will operate *against*
`registry.memory` via the port as Tektos plugin policy in a later
stage. This avoids the disease the endpoint split is curing: two memory
systems in the kernel (SQLite tiers + DozerDB graph) with divergent
writes and no referent.

## Decision

Honest split of the three ops calls:

- **M1 (slice M1, `bd6a269`)** — graph read surface.
  `GraphBackend.list_nodes(label, *, limit)` added to the Protocol and
  both backends: Bolt — real Cypher `MATCH (n:<Label>) WHERE
  n.written_at IS NOT NULL RETURN n ORDER BY n.written_at DESC LIMIT
  $lim` (ISO-8601 UTC strings sort temporally lexicographically; neo4j
  `Node` objects normalized to plain props dicts, 4.x
  `IntegerIdentity` handled); in-memory — label filter + limit.
  Adapter-level `recent_memory_events(limit)` mirrors `stats()`:
  raises on failure (the endpoint layer owns the degrade), never
  fabricates rows.
- **M2+M3 (slice M2+M3, `5750a81`)** — `GET /api/memory` in
  `kernel/app.py`: newest-first `MemoryEvent` rows mapped to the ops
  table's four columns exactly (`id/kind/content/score` =
  `id/predicate/object/confidence`) + `written_at/provenance/subject/
  pii_tier`. Client-side `written_at DESC` sort so Bolt (Cypher-ordered)
  and in-memory (insertion-order) backends render identically.
  Envelope `{entries, count, limit, backend, timestamp}`; `limit`
  clamped 1–100; `registry.memory is None` → 503 with boot-hint; read
  failure → 500 with detail. `/api/memory/stats` (ADR-123) untouched —
  coexistence covered by a test.
- **M4 (slice M4, `b01d601`)** — ops MemoryTab re-point: both GETs pass
  `base: ""` (kernel-native, the ADR-129/130/133/134 pattern).
  **Decay degrades honestly:** the button is disabled with a tooltip +
  click message — "kernel memory is a MemoryEvent graph — no tier decay
  (Tektos plugin policy, coming)". No fake endpoint, no silent drop:
  the absence of a referent is surfaced in the UI itself.

## Honest limits

- `decay` (and the donor's `DELETE /api/memory/{tier}/{entry_id}`) have
  no kernel referent and are NOT landed as endpoints — they arrive
  with the Tektos tier/decay plugin policy (later stage), which will
  also need to decide the decay value function against
  `provenance/confidence`.
- Entry depth = `limit` (≤100) recent `MemoryEvent` nodes; the donor
  returned tier-filtered + FTS5-searched views. Search over the kernel
  graph already exists elsewhere (`/api/memory/search-semantic`,
  ADR-075) and is not duplicated here.
- `kind` = the triple's predicate (not a tier name) — the ops table
  column renders it identically; the tab's header text was left
  generic ("Entries").

## Verification

- 4/4 M1 tests (`test_stage_11_19_adr_135_memory_graph_read.py` —
  in-memory backend: label filter + limit + empty label; real
  `write_event` → full row props; limit passthrough; empty corpus).
- 6/6 M3 endpoint tests (`test_stage_11_19_adr_135_memory_entries_
  endpoint.py` — ASGI + fakes: envelope + newest-first sort, limit
  clamp 0→1 / 500→100, empty corpus, 503 lane-offline, 500-with-detail,
  ADR-123 stats unchanged).
- Full `tests/kernel` + `plugins/tektos` + `tests/adapters` regression
  green (exit 0; only the known Colossus-only interactive skips).
- `next build` green; live on restarted kernel (:8000, real DozerDB):
  `/api/memory` → `{entries: [], count: 0, backend: "dozerdb"}` (empty
  graph — honest), `/api/memory/stats` → healthy dozerdb counts.

## Consequences

- MemoryTab no longer touches the `:8020` gateway.
- The tier/decay policy is now a *named* future deliverable: Tektos
  plugin policy against `registry.memory` (tiers as MemoryEvent
  attribute + decay value function + dreamtime reflection).
- Commit chain: M1 `bd6a269` → M2+M3 `5750a81` → M4 `b01d601` → docs
  (this ADR + README row + BUILD_LOG 11.19).
