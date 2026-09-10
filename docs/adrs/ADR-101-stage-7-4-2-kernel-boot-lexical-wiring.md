# ADR-101 — Kernel-boot wiring of `DozerDbLexicalIndex` into `_boot_memory`

**Status:** Ratified (2026-09-10)
**Lock-in phase:** Stage 7.4+2
**Supersedes:** —

## Context

ADR-100 landed the production `DozerDbLexicalIndex` at Stage 7.4+1 and
explicitly deferred kernel-boot wiring to Stage 7.4+2 with a dedicated
ADR (D6):

> Boot-time wiring for `ZetesisPlugin`'s DozerDB factory is **not** in
> this slice. That is Stage 7.4+2 — kernel boot needs to grow the
> ability to inject `DozerDbLexicalIndex` with the correct Bolt
> credentials, and that touches the plugin factory contract, which
> deserves its own ADR review.

The current-state analysis:

- **`kernel/app.py::_boot_memory`** already constructs
  `DozerDbMemoryAdapter` inside a `_try("memory")` best-effort wrapper.
  It env-gates the graph backend on `KOSMOS_MEMORY_BACKEND=dozerdb` and
  reads `KOSMOS_DOZERDB_URI` / `_USER` / `_PASSWORD` / `_DATABASE`
  (defaults `"neo4j"`) for the Bolt connection. Both branches
  (`dozerdb` and default `in_memory`) currently construct the adapter
  **without** the `lexical=` kwarg — so `MemoryPort.search_hybrid`
  raises `NotImplementedError` in production per ADR-085's honesty
  rule.
- **`plugins/zetesis/adapters/real/factory.py::build_stage_6_5_zetesis_plugin`**
  accepts a `memory: MemoryPort | None` parameter and, when the caller
  supplies one, uses it verbatim (`memory=registry.memory` at
  `kernel/app.py:537`). When called standalone with no memory
  parameter, it builds an in-memory-only `DozerDbMemoryAdapter` with
  no lexical (the code path used by `test_stage_6_5_zetesis_mount.py`
  and other test harnesses).
- **`DozerDbMemoryAdapter.__init__`** already exposes the
  `lexical: LexicalIndex | None = None` kwarg (ADR-099 D3 + ADR-100
  landed the callable surface); no adapter-layer signature change is
  needed.
- **Live-tier env-var conventions in the repo:** `KOSMOS_MEMORY_BACKEND`
  (mode switch), `KOSMOS_DOZERDB_URI` / `_USER` / `_PASSWORD` /
  `_DATABASE` (Bolt credentials), `KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL`
  (fast-vs-live test tier gate). The `KOSMOS_STAGE_XX_LIVE` names are
  test-tier switches; production wiring uses `KOSMOS_MEMORY_BACKEND` +
  `KOSMOS_DOZERDB_*`.

The wiring must land in one place, be opt-in, share the same Bolt
credentials as the graph backend, and preserve `search_hybrid`'s
`NotImplementedError` contract when lexical is unwired (do not silently
degrade to semantic-only — that would violate ADR-085).

## Decision

Five governing decisions.

### D1 — Wiring lives in `kernel/app.py::_boot_memory`, not in the factory

The `_boot_memory` function is the single canonical construction site
for `DozerDbMemoryAdapter` in production paths (`kernel/app.py:410–464`).
The Zetesis factory receives the fully-constructed adapter via
`memory=registry.memory`. Extending `_boot_memory` therefore:

1. Wires the lexical lane for every consumer of the kernel-owned
   `MemoryPort` in one place (Zetesis today, future plugins tomorrow),
   satisfying ADR-063's shared-MemoryPort principle.
2. Keeps the factory contract unchanged. The `build_stage_6_5_zetesis_plugin`
   signature does **not** grow a new parameter; callers that already
   pass `memory=registry.memory` inherit the wired lexical lane for
   free. Standalone factory calls (tests, ad-hoc scripts) keep their
   in-memory MemoryPort without a lexical lane — matching pre-ADR-101
   behaviour, so `search_hybrid` still raises `NotImplementedError` for
   those callers, which is what ADR-085 mandates.
3. Confines the new env-var reads to the same `_try("memory")`
   best-effort scope, so a lexical bootstrap failure cannot brick
   kernel boot — it degrades gracefully to `lexical=None` with the
   failure recorded in `registry.errors["memory_lexical"]`, and
   `search_hybrid` reverts to its `NotImplementedError` contract.

### D2 — Opt-in via `KOSMOS_MEMORY_LEXICAL=dozerdb`; default `off`

Introduce one new env var: `KOSMOS_MEMORY_LEXICAL`, values:

- `"off"` (default when unset): no lexical lane; `search_hybrid`
  continues to raise `NotImplementedError` per ADR-085.
- `"dozerdb"`: construct `DozerDbLexicalIndex` using the **same**
  `KOSMOS_DOZERDB_URI` / `_USER` / `_PASSWORD` / `_DATABASE` env vars
  as the graph backend (single Bolt endpoint per deployment; ADR-008
  §"single canonical store").

Reasons for opt-in (not automatic when `KOSMOS_MEMORY_BACKEND=dozerdb`):

- The lexical lane requires a Lucene fulltext index which some Neo4j
  configurations disable at the config level (e.g. `dbms.security.
  procedures.blocked=db.index.fulltext.*`). Auto-wiring would boot the
  memory subsystem into an unusable state whose failure mode
  (`ProcedureCallFailed` at first `search_hybrid` call) is more
  confusing than the current honest `NotImplementedError`. Requiring
  the operator to opt in makes the deployment intent explicit.
- The env var is namespaced under `KOSMOS_MEMORY_*` (not
  `KOSMOS_DOZERDB_*`) because it selects a **lane** of the
  `MemoryPort`, not a backend of the DozerDB connection. Future
  lexical backends (SQLite FTS5, Elasticsearch — both rejected in
  ADR-100 but not permanently ruled out) would extend the same
  `KOSMOS_MEMORY_LEXICAL` enum.

Reject-shape guard: `KOSMOS_MEMORY_LEXICAL=dozerdb` with
`KOSMOS_MEMORY_BACKEND=in_memory` (or unset) is a nonsensical
combination — the lexical adapter needs a Bolt endpoint and the
in-memory graph backend has none. `_boot_memory` raises a
`RuntimeError` in this shape, which the outer `_try("memory")` catches
and records into `registry.errors["memory"]`. The kernel continues to
boot without a memory subsystem, mirroring the failure mode when the
Bolt endpoint is unreachable.

### D3 — Health check at boot; unhealthy → `lexical=None` + log warning

After constructing `DozerDbLexicalIndex(...)`, immediately call
`lexical.is_healthy()`. On `False`:

- Log a warning through `kernel/app.py`'s standard logging path with
  the recorded `_init_error` (surfaced via `lexical._init_error`).
- Discard the unhealthy instance (call `close()` best-effort; swallow
  any close error into the same warning).
- Fall through to `lexical=None` for that boot cycle. `search_hybrid`
  will raise `NotImplementedError` — the same behaviour as an operator
  who never set `KOSMOS_MEMORY_LEXICAL`.

The kernel does **not** retry lexical bootstrap after boot. If the
DozerDB fulltext procedure is transiently unavailable, the operator
restarts the kernel or fixes the DozerDB config and restarts. This
matches the "no in-flight backend hot-swap" discipline established for
the graph backend (`kernel/app.py:_boot_memory` does not retry
`DozerDbGraphBackend` construction either).

### D4 — Kernel-boot lexical construction failure is caught by `_try("memory")`; no separate subsystem

The lexical lane is not its own kernel subsystem — it is a slot on the
memory adapter. Failure to construct it therefore surfaces through
`registry.errors["memory"]` (via the outer `_try("memory")` wrapper).
Do **not** introduce `registry.errors["memory_lexical"]`. Rationale:

- The `registry.errors` dict is enumerated over on the `/api/kernel/health`
  endpoint (spec §12 D3). Introducing a sub-subsystem key would grow
  the error surface without a corresponding capability toggle in the
  kernel status API.
- A lexical bootstrap failure means `search_hybrid` degrades to
  `NotImplementedError` — which is a **contract-preserving** degrade
  (ADR-085 mandates this exact behaviour when no lexical is wired).
  The kernel is not in an error state; only the hybrid retrieval
  capability is unavailable. Operators check by calling
  `search_hybrid` and observing the `NotImplementedError`, not by
  polling a health field.

If the operator sets `KOSMOS_MEMORY_LEXICAL=dozerdb` but the wiring
falls back to `None` (D3), a `log.warning` line is the operator's
signal. The warning message references ADR-101 D3 so an operator
grepping logs can find this ADR.

### D5 — Two-tier tests: fast (no live DozerDB) + env-gated live smoke

Fast tier — new tests in `tests/kernel/test_stage_7_4_2_lexical_wiring.py`:

1. `KOSMOS_MEMORY_LEXICAL` unset → `_boot_memory()` returns adapter
   with `_lexical is None`; `search_hybrid` raises `NotImplementedError`
   (contract preservation).
2. `KOSMOS_MEMORY_LEXICAL="off"` (explicit) → same as unset.
3. `KOSMOS_MEMORY_LEXICAL="dozerdb"` with `KOSMOS_MEMORY_BACKEND="in_memory"`
   or unset → `_boot_memory` fails; `registry.errors["memory"]`
   contains a clear message referencing ADR-101 D2; adapter is `None`.
4. `KOSMOS_MEMORY_LEXICAL="dozerdb"` + `KOSMOS_MEMORY_BACKEND="dozerdb"`
   + Bolt env vars set + fake `neo4j` driver installed with a
   healthy fake driver → `_boot_memory()` returns adapter with
   `_lexical` an instance of `DozerDbLexicalIndex`; the adapter's
   `is_healthy()` returns True.
5. Same as (4) but the fake driver raises on construction — captured
   into `_init_error`; wiring falls through to `lexical=None`; a
   warning is logged referencing ADR-101 D3; adapter is still
   constructed (graph backend still works).
6. Same as (4) but with an unknown `KOSMOS_MEMORY_LEXICAL="mystery"`
   value → `_boot_memory` fails; `registry.errors["memory"]` message
   enumerates the allowed values.

Live tier: no new live-only tests. The existing Stage 7.4+1 live-tier
test (`KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL=1`) already exercises the
end-to-end round trip; adding a second live-tier kernel-boot test
would duplicate coverage without adding assertion strength.

## Rationale

**Why not add `lexical=` to the factory signature.** Would create two
construction sites for `DozerDbLexicalIndex` (the factory when called
standalone + the kernel when it constructs `_boot_memory`). Two sites
means two env-var-parsing implementations that can drift. Keeping the
construction inside `_boot_memory` means one canonical env-var reader.

**Why the factory contract stays unchanged.** Existing tests that call
`build_stage_6_5_zetesis_plugin()` with no arguments (like
`test_factory_wires_all_ten_ports` and `test_stage_6_5_zetesis_mount`)
would break if the factory grew a required `lexical` parameter, and
would silently gain a lexical they didn't ask for if it grew an
optional one. Neither is desirable. The kernel is the injection point
for shared cross-plugin subsystems; the factory just accepts what the
kernel passes.

**Why opt-in and not auto-on when `KOSMOS_MEMORY_BACKEND=dozerdb`.**
See D2 for the operational reason (Lucene procedures may be blocked at
Neo4j config layer). A secondary reason: the two lanes have separate
failure modes worth exercising independently — Bolt reachability is
one failure surface, fulltext-index availability is another. Wiring
them behind separate env toggles lets operators enable them
independently while debugging.

**Why not use `KOSMOS_DOZERDB_LEXICAL_URI` (dedicated lexical
endpoint).** ADR-008 §"single canonical store" forbids splitting the
graph and lexical lanes across different Bolt endpoints — they share
the same node set (`MemoryEvent` nodes carry both graph edges and
`text`/`corpus_name` fulltext properties). One Bolt endpoint per
memory subsystem.

**Why not wire lexical for the in-memory branch too.** The `in_memory`
graph backend implies `in_memory` lexical. Kosmos already ships
`InMemoryLexicalIndex` for exactly this shape (ADR-099 D4), used by
the 11 Stage 7.4 contract tests. Auto-wiring it in `_boot_memory`
would let `search_hybrid` succeed in the default `KOSMOS_MEMORY_BACKEND=in_memory`
boot mode — but that would make it too easy to accidentally ship a
production deployment relying on the in-memory lexical lane, which
is a test backend (linear scan, no persistence). The failure mode
(`NotImplementedError` in the default boot mode) is louder than a
silent BM25-Okapi test backend serving production `search_hybrid`
queries.

**Why is_healthy at boot, not lazy.** `DozerDbLexicalIndex.__init__`
constructs the driver eagerly and captures failures into
`_init_error`. Checking `is_healthy()` synchronously right after
construction surfaces DNS-resolution or authentication failures at
boot instead of at first query, matching operator expectations from
the graph backend (which also errors at first query, not at
construction, so the health check is Kosmos's boot-time signal).

**Alternatives considered:**

1. **Add `lexical` parameter to `build_stage_6_5_zetesis_plugin`.**
   Rejected: creates two env-var-parsing sites; changes the factory
   contract; breaks or silently mutates existing test harnesses. See
   "Why the factory contract stays unchanged" above.
2. **Auto-wire lexical whenever `KOSMOS_MEMORY_BACKEND=dozerdb`.**
   Rejected: Lucene fulltext procedures may be disabled at Neo4j
   config layer; auto-wiring boots into an unusable state. See D2.
3. **Introduce `registry.errors["memory_lexical"]`.** Rejected:
   grows the health-endpoint surface without a corresponding
   capability toggle. See D4.
4. **Lazy lexical bootstrap on first `search_hybrid` call.**
   Rejected: hides DNS/auth failures until first query; breaks the
   "boot fails loudly, queries fail with contract-shape errors"
   discipline established by the graph backend.
5. **Wire lexical for `KOSMOS_MEMORY_BACKEND=in_memory` too (via
   `InMemoryLexicalIndex`).** Rejected: risks accidentally shipping
   the test backend into production. See "Why not wire lexical for
   the in-memory branch too" above.

## Consequences

**Files changed:**

- **New:** `docs/adrs/ADR-101-stage-7-4-2-kernel-boot-lexical-wiring.md` (this file).
- **New:** `tests/kernel/test_stage_7_4_2_lexical_wiring.py` (six fast-tier tests per D5).
- **Modified:** `kernel/app.py` — `_boot_memory` grows a lexical-lane wiring block per D1–D4 (env parse, construct, health-check, fall-through-on-failure, warning log).
- **Modified:** `docs/Kosmos-Build-Sequence-v26.md` — add Stage 7.4+2 stanza with LANDED marker.
- **Modified:** `docs/adrs/README.md` — ADR-101 row appended; "Remaining open decisions" paragraph updated.
- **Modified:** `BUILD_LOG.md` — one entry per completed step.
- **Modified:** `SESSION_HANDOFF.md` — overwritten at session end.

Not modified: `plugins/zetesis/adapters/real/factory.py`. The factory
already threads `memory=registry.memory` through; no signature change
is needed to inherit the wired lexical lane. (`PORTING_LEDGER.md` is
also unchanged — Stage 7.4+2 is a wiring-only slice, no new vendored
components.)

**Downstream effects:**

- Operators who set `KOSMOS_MEMORY_LEXICAL=dozerdb` + the standard
  DozerDB env vars get a working `MemoryPort.search_hybrid` in
  production. Operators who don't get the current `NotImplementedError`
  behaviour, unchanged.
- The `ZetesisPlugin` mount inherits the lexical lane transparently
  because it uses the kernel-owned memory adapter.
- The pattern is reusable: future plugins that consume `MemoryPort`
  (Tektos already does; Rigpa donor code will) inherit `search_hybrid`
  without needing plugin-side lexical wiring.
- ADR-100 D6's Stage 7.4+2 pointer is now discharged. The
  `LexicalIndex` implementation surface is fully closed: Protocol +
  in-memory backend (ADR-099) + production adapter (ADR-100) + kernel
  wiring (ADR-101).

## Lock-in phase

Stage 7.4+2.

## References

- `Kosmos-Build-Spec-v26.md` §17 (ADR summary), §25 (Tektos absorption + shared memory)
- `Kosmos-Build-Sequence-v26.md` — Stage 7.4+2 stanza (added by this ADR)
- ADR-085 (`MemoryPort.search_hybrid` surface + honesty rule)
- ADR-099 (Stage 7.4 re-scope; `LexicalIndex` Protocol locked; `InMemoryLexicalIndex` lands)
- ADR-100 (Stage 7.4+1; production `DozerDbLexicalIndex`; boot-wiring deferred to this ADR)
- ADR-063 (kernel-owned MemoryPort shared across plugins)
- ADR-008 (DozerDB memory port; single canonical store)
- `kernel/app.py` — `_boot_memory` (Bolt-env-var contract)
