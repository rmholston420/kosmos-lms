# ADR-123: kernel-native `/api/memory/stats` (Memory card re-point)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.7 (endpoint split, memory family)
- **Supersedes:** none (removes the ADR-109 gateway proxy for the Memory card)

## Context

The Memory card on the Tektos dashboard fetched `/api/memory/stats` through
the ADR-109 gateway proxy to the retired `:8020` standalone engine, whose
envelope (`working_count`, `long_term_count`, `procedural_count`,
`balance`) described a tier model the kernel's memory port does not
implement. With `KOSMOS_MEMORY_BACKEND=dozerdb` the kernel's live
`registry.memory` is `DozerDbMemoryAdapter` over Neo4j (`bolt://127.0.0.1:7687`),
which writes `MemoryEvent`, `Entity`, and `Quarantined` nodes. The card
therefore showed fabricated tiers while the real graph sat idle a proxy away.

## Decision

### D1 — dedicated `GraphBackend.count_nodes(label)`, not a shared query string

`InMemoryGraphBackend.query_cypher` understands the test-only convention
`label:<Label>`; the DozerDB backend forwards its argument to Neo4j as
**real Cypher**, where `label:MemoryEvent` is a syntax error (verified live:
the first `stats()` draft returned all-`None` with Cypher errors). So the
two backends cannot share a query string — a protocol method is required:

- `GraphBackend.count_nodes(label: str) -> int` (protocol).
- `DozerDbGraphBackend.count_nodes` — `MATCH (n:<label>) RETURN count(n) AS c`,
  with `<label>` passed through the same `_validate_identifier` guard as
  every other Cypher interpolation in the backend (injection-safe).
- `InMemoryGraphBackend.count_nodes` — label filter over the in-memory node
  map (mirrors the existing `label:` convention).

### D2 — `DozerDbMemoryAdapter.stats()`

Returns `{healthy, memory_events, entities, quarantined, errors}`. Each
count is independent: a failing count degrades to `None` + an entry in
`errors` (ADR-023 rule 5 — never a fabricated number, never a 500). The
adapter reports what it actually writes: `MemoryEvent` (events), `Entity`
(entities materialised from payloads), `Quarantined` (quarantined writes).

### D3 — kernel endpoint `GET /api/memory/stats`

Always-200 envelope mirroring the old card's shape where possible:

```json
{"healthy": true, "backend": "dozerdb", "memory_events": 0, "entities": 0,
 "quarantined": 0, "errors": [], "timestamp": "..."}
```

- `registry.memory` is `None` (memory off) → `healthy: false`,
  `backend: "none"`, counts `None` — the card renders "offline" instead of
  proxying to a dead engine.
- `stats()` itself raising → `healthy: false`, `errors: ["<ExcType>"]`.
- `backend` is the adapter's declared backend name (defensive passthrough).

### D4 — card re-point + honest parse

`base: ""` (kernel root) replaces the gateway proxy. The `memory` parseCard
case was **rewritten** (not extended): the old tier keys no longer exist, so
the card now shows `memory_events` / `entities` / `quarantined` counts with a
health dot, and an "offline" line when `backend: "none"`. A `null` count
renders `?` — a visible degradation, not a silent zero.

## Consequences

- The Memory card reflects the **real** graph: live-verified against an
  independently-run Neo4j query (sync driver) — both report the same counts.
  On Collosus the graph is currently **empty** (0/0/0): the kernel has not
  written memories since the split, which the card now shows honestly.
  (Neo4j's `label does not exist` warnings on an empty label are benign —
  the count is 0, not an error.)
- `count_nodes` is a narrow, injection-guarded protocol addition; the two
  existing contract-test suites (71 tests incl. the live-docker tier) still
  pass unchanged.
- Remaining Stage 11 families after this: rag, skills, tools, plugins,
  self_repair, logs, directory, sessions.

## Tests

`tests/kernel/test_stage_11_7_adr_123_memory_stats.py` — 6 tests:
happy path (counts pass-through + label order), `None` adapter → backend
`"none"`, per-count failure → `None` + `errors` entry (never 500),
`stats()` raising → healthy false, and the **real** `DozerDbMemoryAdapter`
against `InMemoryGraphBackend` + `InMemoryTemporalIndex` (2 events → 2
MemoryEvent + 4 Entity, then graph-raising → all `None`).
