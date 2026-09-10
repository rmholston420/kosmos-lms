# Kosmos Porting Ledger

Every vendored, evaluated, or rejected OSS component. Required by
`Kosmos-Build-Spec-v25.md` §§48 & 252.

**Backfilled 2026-08-01 01:12 EDT** — this file was previously missing
from the repo root despite spec references. Entries below cover the
kernel bootstrap (new) plus placeholders for historical vendor
decisions already ratified in ADRs (see `docs/adrs/README.md` for
authoritative history through ADR-056).

Format per entry:

```
#### <Component> — <STATUS>
- **Source:** <upstream URL>
- **Commit / Version:** <SHA or tag>
- **License:** <SPDX>
- **Kosmos location:** `<path>`
- **Port(s):** <formal port name(s)>
- **Modifications:** <bullet list; "none" if unmodified>
- **ADR:** <ADR-###>
- **Logged:** <YYYY-MM-DD HH:MM EDT>
```

Statuses: `VENDORED` · `PATTERN-VENDORED` · `PLANNED` ·
`EVALUATED-REJECTED` · `SUPERSEDED`

---

## Kernel

#### FastAPI kernel bootstrap — HAND-BUILT (no vendor)
- **Source:** none — purpose-written for Kosmos
- **Commit / Version:** —
- **License:** MIT (Kosmos)
- **Kosmos location:** `kernel/app.py`, `kernel_ui_glue/`
- **Port(s):** none directly; composes `FrontendContractPort`,
  `ApprovalResolverPort`, `ResourcePort`, `NotificationPort`,
  `EventBusPort`
- **Modifications:** N/A
- **ADR:** ADR-057 (Stage 6.3 route surface) · ADR-052 (Stage 6.1
  skeleton)
- **Logged:** 2026-08-01 01:12 EDT
- **Notes:** Vendor-before-build check ratified 2026-08-01:
  Rigpa-LMS `plugin_kernel/` is plugin-side only (does not expose a
  kernel bootstrap surface); no permissively-licensed OSS candidate
  matches Kosmos's composed-port bootstrap requirement — closest
  Python scaffolds (`fastapi-mvc`, NestJS-style DI frameworks) all
  inject their own DI which conflicts with our formal-port Protocol
  seams. Hand-build ratified.


## Stage 6.5 · Zetesis Kernel Mount (ADR-058)

The following adapters go from `PLANNED` / `VENDORED` to `WIRED` at
Stage 6.5 — the kernel lifespan constructs each one via
`build_stage_6_5_zetesis_plugin()` and holds the resulting plugin
under `registry.zetesis`. Real backends (DozerDB compose, real Qdrant
client, OTEL collector) attach at Stage 6.5.1+.

#### DozerDbMemoryAdapter — WIRED
- **Source:** `adapters/memory/dozerdb/adapter.py`
- **Backend at 6.5:** `InMemoryGraphBackend` + `InMemoryTemporalIndex`
  + `NoOpAmgPolicy` (real DozerDB/Graphiti/AMG backends attach at
  6.5.1 once neo4j-compose is up on Colossus)
- **License:** MIT (Kosmos code) + GPLv3 (embedded DozerDB backend)
- **Kosmos location:** `plugins/zetesis/adapters/real/factory.py`
- **Port(s):** `MemoryPort`
- **Modifications:** none — factory wires seams via DI
- **ADR:** ADR-058 · ADR-027 (adapter shape) · ADR-047 (backend)
- **Logged:** 2026-08-01 01:36 EDT

#### QdrantVectorAdapter — WIRED
- **Source:** `adapters/vector/qdrant/adapter.py`
- **Backend at 6.5:** `InMemoryQdrantBackend` (spec-endorsed until
  Compose lands per adapter docstring §7)
- **License:** MIT
- **Kosmos location:** `plugins/zetesis/adapters/real/factory.py`
- **Port(s):** `VectorPort`
- **Modifications:** none
- **ADR:** ADR-058 · ADR-026 (adapter shape)
- **Logged:** 2026-08-01 01:36 EDT

#### FilesystemDataAdapter — WIRED
- **Source:** `adapters/data/filesystem/adapter.py`
- **Backend at 6.5:** on-disk storage rooted at
  `~/.local/state/kosmos/data` (created lazily on first write)
- **License:** MIT
- **Kosmos location:** `plugins/zetesis/adapters/real/factory.py`
- **Port(s):** `DataPort`
- **Modifications:** none
- **ADR:** ADR-058 · ADR-028 (adapter shape)
- **Logged:** 2026-08-01 01:36 EDT

#### OllamaAdapter — WIRED (via Zetesis plugin)
- **Source:** `adapters/llm/ollama/adapter.py`
- **Backend at 6.5:** local Ollama at `http://127.0.0.1:11434/v1`,
  default model `qwen2.5:32b-instruct-q4_K_M`
- **License:** MIT
- **Kosmos location:** `plugins/zetesis/adapters/real/factory.py`
- **Port(s):** `LLMPort`
- **Modifications:** none
- **ADR:** ADR-058 · ADR-022 (LLMPort surface)
- **Logged:** 2026-08-01 01:36 EDT

#### SearxngAdapter — WIRED (via Zetesis plugin)
- **Source:** `adapters/search/searxng/adapter.py`
- **Backend at 6.5:** local SearXNG at `http://127.0.0.1:8888`
- **License:** MIT
- **Kosmos location:** `plugins/zetesis/adapters/real/factory.py`
- **Port(s):** `SearchPort`
- **Modifications:** none
- **ADR:** ADR-058 · ADR-021 (SearchPort surface)
- **Logged:** 2026-08-01 01:36 EDT

#### OtelStackObservabilityAdapter — WIRED (via Zetesis plugin)
- **Source:** `adapters/observability/otel_stack/adapter.py`
- **Backend at 6.5:** `StubOtelBackend` (real OTEL collector attaches
  at 6.5.1+ once the observability compose service lands)
- **License:** MIT
- **Kosmos location:** `plugins/zetesis/adapters/real/factory.py`
- **Port(s):** `ObservabilityPort`
- **Modifications:** none
- **ADR:** ADR-058
- **Logged:** 2026-08-01 01:36 EDT


## Stage 1.5 · Kosmos UI Persistent Shell (ADR-068)

The Next.js UI at `ui/` composes these permissively-licensed OSS
components behind the `FrontendContractPort` React client
(`ui/lib/kernel-client.ts`). All are node_modules dependencies, not
vendored source trees; SPDX license verified on every version listed.

#### next 16 + react 19 + react-dom 19 — DEPENDED-ON
- **Source:** https://github.com/vercel/next.js · https://github.com/facebook/react
- **Commit / Version:** next `16.0.0`, react/react-dom `19.0.0`
- **License:** MIT
- **Kosmos location:** `ui/` (Next.js `app/` router, static export `output: "export"`)
- **Port(s):** none directly; consumes `FrontendContractPort` schema
- **Modifications:** none
- **ADR:** ADR-067 (Stage 1 shell) · ADR-068 (Stage 1.5 realization)
- **Logged:** 2026-08-01 06:12 EDT

#### tailwindcss v4 (with Five-Wisdom OKLCH `@theme`) — DEPENDED-ON
- **Source:** https://github.com/tailwindlabs/tailwindcss
- **Commit / Version:** `^4.0.0`
- **License:** MIT
- **Kosmos location:** `ui/app/globals.css` (`@theme` block)
- **Port(s):** none
- **Modifications:** none — pure config; Tibetan Five Buddha Family palette
  authored in-tree as OKLCH tokens, hydratable at runtime from
  `/api/kernel/design-tokens` via `DesignTokenHydrator`.
- **ADR:** ADR-068
- **Logged:** 2026-08-01 06:12 EDT

#### @radix-ui/react-dialog — DEPENDED-ON
- **Source:** https://github.com/radix-ui/primitives
- **Commit / Version:** `^1.1.0`
- **License:** MIT
- **Kosmos location:** `ui/components/PersistentShell.tsx`,
  `ui/components/CommandPalette.tsx`, `ui/components/KillSwitch.tsx`
- **Port(s):** none — provides Radix `Sheet`-equivalent (contextual
  drawer), Cmd+K modal, and kill-switch confirmation dialog
- **Modifications:** none
- **ADR:** ADR-068
- **Logged:** 2026-08-01 06:12 EDT

#### cmdk — DEPENDED-ON
- **Source:** https://github.com/pacocoursey/cmdk
- **Commit / Version:** `^1.0.0`
- **License:** MIT
- **Kosmos location:** `ui/components/CommandPalette.tsx`
- **Port(s):** none — a11y-correct combobox for the Cmd+K palette per
  UX Design Spec §"Persistent Shell"
- **Modifications:** none — wraps a static navigation list in Wave A;
  Wave B swaps in kernel-schema-driven commands
- **ADR:** ADR-068
- **Logged:** 2026-08-01 06:12 EDT

#### @tanstack/react-query — DEPENDED-ON (Wave B onward)
- **Source:** https://github.com/TanStack/query
- **Commit / Version:** `^5.60.0`
- **License:** MIT
- **Kosmos location:** `ui/` (installed; not yet consumed — Wave A uses
  plain `useEffect` + `fetch` via `kernelClient`; Wave B introduces the
  QueryClient provider and per-port hooks)
- **Port(s):** none
- **Modifications:** none
- **ADR:** ADR-068
- **Logged:** 2026-08-01 06:12 EDT

#### zustand — DEPENDED-ON (Wave B onward)
- **Source:** https://github.com/pmndrs/zustand
- **Commit / Version:** `^5.0.0`
- **License:** MIT
- **Kosmos location:** `ui/` (installed; not yet consumed — Wave B
  introduces per-`state_namespace` store per UX Design Spec §"Stack
  Validation")
- **Port(s):** none
- **Modifications:** none
- **ADR:** ADR-068
- **Logged:** 2026-08-01 06:12 EDT


### Stage 1.5 Wave D · UI dependencies (MEMORY_INTEGRITY graph)

#### cytoscape — VENDORED
- **Source:** https://github.com/cytoscape/cytoscape.js
- **Commit / Version:** `^3.30.0`
- **License:** MIT
- **Kosmos location:** `ui/` (npm dep; consumed inside
  `ui/components/panels/MemoryIntegrityPanel.tsx` only — never
  imported by other components)
- **Port(s):** none — client-side graph rendering surface for the
  MEMORY_INTEGRITY panel per UX Design Spec §"Data-Type Taxonomy" #1
- **Modifications:** none
- **ADR:** ADR-070
- **Logged:** 2026-08-01 07:19 EDT

#### react-cytoscapejs — VENDORED
- **Source:** https://github.com/plotly/react-cytoscapejs
- **Commit / Version:** `^2.0.0`
- **License:** MIT
- **Kosmos location:** `ui/` (npm dep; thin React binding for cytoscape,
  consumed inside `ui/components/panels/MemoryIntegrityPanel.tsx` only)
- **Port(s):** none
- **Modifications:** none
- **ADR:** ADR-070
- **Logged:** 2026-08-01 07:19 EDT

#### DDC Uchen font (Christopher John Fynn, 2010) — VENDORED (font asset)
- **Source:** upstream distribution
  `https://deb.debian.org/debian/pool/main/f/fonts-ddc-uchen/fonts-ddc-uchen_1.0.orig.tar.gz`
  (identical binary to Chris Fynn's original release for the Dzongkha
  Development Commission of Bhutan)
- **Commit / Version:** `1.0` (Debian `orig.tar.gz`, single-file tarball
  containing `DDC_Uchen.ttf`; sha256 verifiable at build time)
- **License:** SIL Open Font License 1.1 (embedded name records IDs
  13 + 14; `OFL.txt` bundled beside the font per OFL clause 2 as an
  accompanying text file)
- **Kosmos location:** `ui/public/fonts/ddc-uchen/DDC_Uchen.woff2` plus
  `ui/public/fonts/ddc-uchen/OFL.txt` (converted TTF→woff2 via fonttools
  4.x; only compression format changed, not the underlying font tables)
- **Port(s):** none (static asset consumed by `@font-face` in
  `ui/app/globals.css` — the Kosmos wordmark and job-page display
  headings; wired via `--font-display: "DDC Uchen", ...`)
- **Modifications:** container format only (TTF→woff2, brotli-compressed
  Font Table Directory per WOFF2 spec). No glyph, kerning, name-record,
  or license-metadata modification. Reserved Font Name "DDC Uchen"
  preserved unmodified per OFL clause 3.
- **ADR:** ADR-072
- **Logged:** 2026-08-01 09:04 EDT

## Stage 1.6 Phase 0 · EmbeddingsPort (ADR-073)

#### httpx — EmbeddingsPort transport (continued satisfaction)
- **Source:** https://github.com/encode/httpx
- **Commit / Version:** already vendored per Stage 6.5.6 (ADR-063); no new version bump.
- **License:** BSD-3-Clause (SPDX)
- **Kosmos location:** `adapters/embeddings/ollama/adapter.py` (imports only)
- **Port(s):** `EmbeddingsPort` (transport layer; not a vendored implementation of the port itself)
- **Modifications:** none
- **ADR:** ADR-073
- **Logged:** 2026-08-01 10:35 EDT

No other new vendored components: ``OllamaEmbeddingsAdapter`` calls
Ollama's native ``/api/embed`` endpoint directly via ``httpx``. The
``EmbeddingsPort`` protocol itself is Kosmos-original code (no OSS port
vendored). Graphiti's ``EmbedderClient`` shape is duck-typed via
``KosmosGraphitiEmbedder`` — no `graphiti_core` API surface is vendored
into Kosmos beyond the existing memory adapter usage.


## Stage 1.6 Phase 1 · Semantic memory + graph visualization (ADR-074)

#### qdrant-client — VectorPort real backend (continued satisfaction)
- **Source:** https://github.com/qdrant/qdrant-client
- **Commit / Version:** already declared as `qdrant-client>=1.11` in
  `pyproject.toml`; no new version bump. Live-tier binding lands in
  Phase 1 with `adapters/vector/qdrant/real_backend.py`.
- **License:** Apache-2.0 (SPDX)
- **Kosmos location:** `adapters/vector/qdrant/real_backend.py`
  (lazy `AsyncQdrantClient` import inside `__init__`)
- **Port(s):** `VectorPort` via `QdrantBackend` seam (ADR-026)
- **Modifications:** none — Kosmos adds a wrapper backend around
  `AsyncQdrantClient` implementing the `QdrantBackend` Protocol.
- **ADR:** ADR-074
- **Logged:** 2026-08-01 11:05 EDT

#### react-force-graph-2d — DimensionalForceGraph 2D renderer
- **Source:** https://github.com/vasturiano/react-force-graph
- **Commit / Version:** ^1.29.1 (npm)
- **License:** MIT (SPDX)
- **Kosmos location:** `ui/components/graph/DimensionalForceGraph.tsx`
  (SSR-off dynamic import from `ui/app/gnosis/graph/page.tsx`)
- **Port(s):** none — DOM-only rendering component; consumed via
  `next/dynamic({ ssr: false })`
- **Modifications:** none (unmodified npm dep)
- **ADR:** ADR-074
- **Logged:** 2026-08-01 11:05 EDT

#### react-force-graph-3d — DimensionalForceGraph 3D renderer
- **Source:** https://github.com/vasturiano/react-force-graph
- **Commit / Version:** ^1.29.1 (npm)
- **License:** MIT (SPDX)
- **Kosmos location:** `ui/components/graph/DimensionalForceGraph.tsx`
- **Port(s):** none — DOM-only
- **Modifications:** none
- **ADR:** ADR-074
- **Logged:** 2026-08-01 11:05 EDT

#### three — WebGL runtime for react-force-graph-3d
- **Source:** https://github.com/mrdoob/three.js
- **Commit / Version:** ^0.185.1 (runtime), ^0.185.0 (types)
- **License:** MIT (SPDX)
- **Kosmos location:** transitive dep of `react-force-graph-3d`
- **Port(s):** none — pure WebGL runtime
- **Modifications:** none
- **ADR:** ADR-074
- **Logged:** 2026-08-01 11:05 EDT

#### DimensionalForceGraph.tsx — Rigpa-LMS donor
- **Source:** https://github.com/rmholston420/Rigpa-LMS
- **Commit / Version:** 2026-08-01 clone (Apache-2.0)
- **License:** Apache-2.0 (SPDX)
- **Kosmos location:** `ui/components/graph/DimensionalForceGraph.tsx`
- **Port(s):** none — presentational React component
- **Modifications:** dropped Vite-specific `import.meta.env.DEV` demo
  affordance (Next.js does not expose that global); tightened prop
  types to the shared 2D/3D intersection surface; renamed export to
  match Kosmos file naming.
- **ADR:** ADR-074
- **Logged:** 2026-08-01 11:05 EDT

#### graphDimensionStore.ts — Rigpa-LMS donor
- **Source:** https://github.com/rmholston420/Rigpa-LMS
- **Commit / Version:** 2026-08-01 clone (Apache-2.0)
- **License:** Apache-2.0 (SPDX)
- **Kosmos location:** `ui/lib/graph/graphDimensionStore.ts`
- **Port(s):** none — Zustand store
- **Modifications:** renamed persistence key
  `rigpa-graph-dimension` → `kosmos-graph-dimension`; removed
  demo-data flag branch (single-user local-first).
- **ADR:** ADR-074
- **Logged:** 2026-08-01 11:05 EDT

#### GraphDimensionToggle.tsx — Rigpa-LMS donor
- **Source:** https://github.com/rmholston420/Rigpa-LMS
- **Commit / Version:** 2026-08-01 clone (Apache-2.0)
- **License:** Apache-2.0 (SPDX)
- **Kosmos location:** `ui/components/graph/GraphDimensionToggle.tsx`
- **Port(s):** none
- **Modifications:** dropped the Vite dev-only “Demo data” checkbox;
  restyled with Kosmos design-token CSS variables
  (`--space-1/2`, `--color-*`).
- **ADR:** ADR-074
- **Logged:** 2026-08-01 11:05 EDT

## Historical entries

Full history through ADR-056 lives in `docs/adrs/README.md`. Notable
vendored components (see linked ADRs for details):

- **docling 2.116.0** — MIT · PATTERN-VENDORED · ADR-044 · Stage 3.10
- **datacurve-pier 0.3.0** — Apache-2.0 · VENDORED (dev-only) ·
  ADR-042 · Stage 3.8
- **HTMX 2.0.4** — 0BSD · VENDORED · ADR-045 · Stage 3.11
- **OpenHands SDK** — MIT · PATTERN-VENDORED · ADR-036 · Stage 3.1
- **Open Deep Research** (`langchain-ai/open_deep_research@d337ae3`)
  — MIT · VENDORED · ADR-010 · Stage 6.2 (WINNER)
- **AREX-Turbo** (`BAAI/AREX-Turbo`) — Apache-2.0 ·
  EVALUATED-REJECTED (Stage 6.2) · ADR-010 · retained on-shelf with
  four-clause revisit gate
- **agent-memory-guard 0.3.0** — Apache-2.0 · VENDORED · ADR-048 ·
  Stage 4.3
- **DozerDB 5.26.27** — GPLv3 (embedded backend only) · VENDORED ·
  ADR-047 · Stage 4.2
- **Graphiti** — Apache-2.0 · VENDORED · ADR-027 · Stage 4.2
- **SuttaCentral Bilara** — CC0 · VENDORED (data corpus) · ADR-050 ·
  Stage 4.5
- **Superpowers KB** — MIT · VENDORED (data corpus) · ADR-049 ·
  Stage 4.4

New adopts, evaluations, and rejections must be appended to
this file **at the same time** as the ADR that ratifies them, per
`kosmos-spec-diff` skill fan-out rules.

---

## Tektos-Ultima absorption (seeded 2026-09-10 by ADR-077)

Source repo: `rmholston420/tektos-ultima` (public, no LICENSE file at source; sole copyright holder rmholston420 relicenses at port-in). Every entry below is `PLANNED` until landed in a numbered Stage step of `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN.md`.

#### Tektos runtime seed (TurnLoop) — VENDORED (Stage 3.13)
- **Source:** https://github.com/rmholston420/tektos-ultima (author's `orchestrator/*` + `runtime/agent_loop.py` patterns — seed only; no verbatim copy)
- **Commit / Version:** 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
- **License:** MIT (re-license at port-in per scaffold policy; rmholston420 sole copyright)
- **Kosmos location:** `plugins/tektos/runtime/turn_loop.py`
- **Port(s):** `ImmunePort` (ADR-079), `LoopSafetyPort` (ADR-080, ADR-088), `ThermalPort` (ADR-081), `EventBusPort` (ADR-086 `tektos.agent.turn.*` envelopes)
- **Modifications:** minimal Stage 3.13 vertical slice per ADR-092 §3 — no LLM inference, no planner, no sandbox, no MCP, no RAG, no memory search, no self-modification. Composes the three Stage 3.13 adapters through their formal ports. Wholesale-import of Tektos-Ultima's `orchestrator/` monolith rejected under ADR-007 (would import 25+ runtime siblings without adapters).
- **ADR:** ADR-077, ADR-079, ADR-080, ADR-088, ADR-092
- **Logged:** 2026-09-10 01:00 EDT

#### Tektos immune system (3 seed detectors) — VENDORED (Stage 3.13)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/runtime/immune_system.py (lines 1-236 shared types + 238-311 PromptInjection + 558-637 SecretExposure + 639-860 DangerousCommand)
- **Commit / Version:** 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
- **License:** MIT (re-license at port-in per scaffold policy)
- **Kosmos location:** `adapters/immune/tektos/vendor/immune_donor.py` (donor snapshot) + `adapters/immune/tektos/adapter.py` (`TektosImmuneAdapter`)
- **Port(s):** `ImmunePort` (ADR-079)
- **Modifications:** trimmed donor from 1925 lines → 638 (kept 3 seed detectors + shared types + helpers; dropped 9 other detectors, `ResponseRecord`/`HealthScore` orchestrator types). Donor `Detector.detect(ImmuneContext) -> list[Threat]` wrapped by `_DetectorAdapter` to port's `Detector.evaluate(ImmuneScanRequest) -> tuple[DetectorHit, ...]`. Severity mapping LOW→info, MEDIUM→warn, HIGH/CRITICAL→block. Aggregation policy block>warn>allow. Verdict envelopes on `EventBusPort` (`immune.verdict.<decision>`); block verdicts additionally `write_event(provenance="immune_verdict", confidence=1.0)` on `MemoryPort` per ADR-079 rule 2.
- **ADR:** ADR-079, ADR-092
- **Logged:** 2026-09-10 01:00 EDT

#### Tektos immune system (9 remaining detectors) — PLANNED (Stage 4+)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/runtime/immune_system.py (SelfModificationDetector, ExfiltrationDetector, PathTraversalDetector, ResourceExhaustionDetector, and 5 others deferred per ADR-092 §4)
- **License:** MIT (re-license at port-in)
- **Kosmos location:** future add to `adapters/immune/tektos/vendor/immune_donor.py` + additional `_DetectorAdapter` wrappers.
- **Port(s):** `ImmunePort` (ADR-079)
- **Modifications:** land after SandboxPort (ADR-082, Stage 4.7) and self-modification port (ADR-090) so their gating loops exist.
- **ADR:** ADR-079, ADR-092

#### Tektos loop safety — VENDORED (Stage 3.13)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/runtime/loop_safety.py (`LoopSafetyMonitor`, 403 lines)
- **Commit / Version:** 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
- **License:** MIT (re-license at port-in per scaffold policy)
- **Kosmos location:** `adapters/loop_safety/tektos/vendor/loop_safety_donor.py` (verbatim snapshot) + `adapters/loop_safety/tektos/adapter.py` (`TektosLoopSafetyAdapter`)
- **Port(s):** `LoopSafetyPort` (ADR-080, ADR-088)
- **Modifications:** verbatim import (no source edits). Wrapping adapter owns per-turn `LoopSafetyMonitor` instances keyed by `turn_id`; adds the ADR-088 read-only budget interlock (`LoopCaps.read_only_budget`) donor lacked; publishes state-transition envelopes (`loop_safety.<status>`) on `EventBusPort` per ADR-080 rule 1; terminal states additionally `write_event(provenance="loop_safety", confidence=1.0)` on `MemoryPort` per ADR-080 rule 2. `StopReason→LoopSafetyStatus` mapping: `MAX_TURNS`/`MAX_TOKENS`/`MAX_WALL_TIME`/`CIRCUIT_BREAKER`→`exhausted`; `REPETITION`→`repetition`.
- **ADR:** ADR-080, ADR-088, ADR-092
- **Logged:** 2026-09-10 01:00 EDT

#### Tektos thermal metrics — VENDORED (Stage 3.13)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/thermal/metrics.py (`MetricsCollector` + NVML wrapper, 271 lines)
- **Commit / Version:** 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
- **License:** MIT (re-license at port-in per scaffold policy)
- **Kosmos location:** `adapters/thermal/tektos/vendor/thermal_donor.py` (verbatim snapshot) + `adapters/thermal/tektos/adapter.py` (`TektosThermalAdapter` + `ColossusThermalThresholds`)
- **Port(s):** `ThermalPort` (ADR-081)
- **Modifications:** verbatim donor import (raw NVML telemetry only). Adapter adds ADR-081 level classification (`_level_from_temp` maps to `green` <51 / `yellow` 51-80 / `cap` 80-88 / `red` ≥88); `sample()` runs `MetricsCollector.collect()` in `asyncio.to_thread`; `pressure()` is sync + non-throwing (returns cached, defaults green/0/None) per ADR-081 rule 3; level-crossing transitions publish `thermal.<level>` on `EventBusPort` per rule 1; red transitions additionally `write_event(provenance="thermal", confidence=1.0)` on `MemoryPort` per rule 2. `apply_power_cap`/`release_power_cap` implemented as event-only stubs (publish envelope + update cached pressure) — nvidia-smi shell-out lands with `ThermalRegulator` PID loop in a later stage. `_NoOpCollector` fallback used when NVML raises so CI can construct the adapter without a GPU.
- **ADR:** ADR-081, ADR-092
- **Logged:** 2026-09-10 01:00 EDT

#### Tektos thermal PID regulator — PLANNED (Stage 4+)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/src/tektos/thermal (`ThermalRegulator` PID controller + `nvidia-smi -pl` power-cap actuator; explicitly excluded from Stage 3.13 per ADR-092 §4)
- **License:** MIT (re-license at port-in)
- **Kosmos location:** future extension to `adapters/thermal/tektos/adapter.py` (or sibling `regulator.py`).
- **Port(s):** `ThermalPort` (ADR-081), `ResourcePort` (throttle back-pressure)
- **Modifications:** implement real `apply_power_cap(watts)` via `nvidia-smi -pl` subprocess + PID loop; wire throttle events into `ResourcePort`.
- **ADR:** ADR-081, ADR-092

#### Tektos sandbox — VENDORED (Stage 4.7)
- **Source:** https://github.com/rmholston420/tektos-ultima
- **Commit / Version:** `2b45cac1f9ac214c85ff53571b949445b5415209` (2026-09-10)
- **License:** MIT (re-licensed at port-in; rmholston420 sole copyright)
- **Kosmos location:** `adapters/sandbox/tektos/vendor/sandbox_exec_donor.py` (donor snapshot), `adapters/sandbox/tektos/adapter.py` (`TektosSandboxAdapter`)
- **Port(s):** `SandboxPort` (ADR-082)
- **Modifications:** donor `subprocess.run(..., shell=True, timeout=..., cwd=fs_root)` primitive trimmed to ~180 lines (kept `exec_argv`, output-cap, `_docker_exec` helper for future Terminal-Bench); dropped sudo auto-retry (leaks host state), PEP-668 hint injection, file / directory / search tools, MCP integration. Adapter layer adds: `argv`-first exec (never `shell=True`, closes upstream injection surface), `resource.setrlimit` via `preexec_fn` (RLIMIT_AS + RLIMIT_CPU + 128 MB RLIMIT_FSIZE), `SandboxLimits.network` enforcement (`"none"` / `"loopback"` wrap in `unshare --user --map-root-user --net`; fail-closed with `sandbox.isolation_unavailable` envelope + `exit_code=126` when `unshare` missing / kernel refuses), opportunistic cgroups v2 write at `/sys/fs/cgroup/kosmos-sandbox/<run_id>/memory.max` when mount is writable, wall-time via donor `subprocess.run(timeout=...)` in `asyncio.to_thread` with `killed_by="limit"` on TimeoutExpired, `kill()` records cancel intent (subprocess.run blocks a worker thread so mid-flight SIGTERM isn't injectable) and reclassifies terminal envelope as `killed_by="user"`, lifecycle envelopes on every run per ADR-082 rule 1, `MemoryPort.write_event(provenance="sandbox", confidence=1.0)` per rule 2.
- **ADR:** ADR-082, ADR-093
- **Logged:** 2026-09-10 01:15 EDT

#### NoOp sandbox — VENDORED (Stage 4.7)
- **Source:** none (Kosmos-native)
- **License:** MIT
- **Kosmos location:** `adapters/sandbox/noop/adapter.py`
- **Port(s):** `SandboxPort` (ADR-082)
- **Modifications:** synthesizes `SandboxResult(exit_code=0, stdout="", killed_by="exit", wall_seconds=0.0, peak_memory_mb=0)` without executing anything. Wired in CI on non-Linux hosts and used by contract tests that need Protocol conformance without side effects. Same lifecycle-envelope + `MemoryPort` write discipline as `TektosSandboxAdapter` (attributes include `"noop": true` so downstream consumers can filter). Required by ADR-082 §Enforcement rule 4.
- **ADR:** ADR-082, ADR-093
- **Logged:** 2026-09-10 01:15 EDT

#### Tektos hindsight memory (bridge adapter) — EVALUATED-REJECTED (Stage 3-5, H1 skipped)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/tektos/hindsight
- **License:** MIT (relicensed at port-in — never triggered)
- **Kosmos location:** `adapters/memory/hindsight_bridge/` — **never created**
- **Port(s):** `MemoryPort` (bridge — never implemented)
- **Modifications:** N/A — no code ever landed. The H1 (bridge Tektos to legacy hindsight service) → H2 (Tektos on DozerDB) plan was collapsed to H2-only through Stages 3–5: `plugins/tektos/` consumes `MemoryPort` directly via the DozerDB adapter with no bridge in between. Directory never existed; no imports in the codebase; no `pyproject.toml` entry. Stage 7.4 was originally chartered to retire this bridge; ADR-099 records the contingency firing (H1 detour skipped, direct H2 kept) and re-scopes Stage 7.4 to landing `search_hybrid` on `DozerDbMemoryAdapter` instead. Retire on paper only — no repo state to change.
- **ADR:** ADR-085, ADR-099
- **Logged:** 2026-09-10 03:20 EDT

#### DozerDB hybrid retrieval (`search_hybrid` + `InMemoryLexicalIndex`) — VENDORED (Stage 7.4)
- **Source:** none (Kosmos-native; RRF fusion formula per ADR-085 verbatim; BM25-Okapi lexical scoring is a hand-authored test backend)
- **License:** MIT
- **Kosmos location:** `adapters/memory/dozerdb/adapter.py` (adds `LexicalIndex` Protocol, `InMemoryLexicalIndex` test backend, `RRF_K = 60`, `DozerDbMemoryAdapter.search_hybrid` method, and lexical-mirror side effect in `write_event`); `adapters/memory/dozerdb/test_search_hybrid_contract.py` (RRF math + weight-guard + honesty-rule + corpus + `min_score` + `limit` contract)
- **Port(s):** `MemoryPort` (ADR-085 method); `LexicalIndex` is adapter-scoped, NOT a formal port under `ports/` (symmetric with `GraphBackend` and `TemporalIndex` — ADR-007 + ADR-027 forbid plugin bypass of `MemoryPort`)
- **Modifications:** `search_hybrid` calls `validate_hybrid_weights` first (non-bypassable weight guard), raises `NotImplementedError` when no `LexicalIndex` is wired (ADR-085 honesty rule — no silent degrade to semantic-only), runs lexical + semantic legs in parallel semantically (both `await`ed sequentially per the port contract), fuses with `score = lw · 1/(RRF_K+rank_lex) + sw · 1/(RRF_K+rank_sem)`, merges by hit id (semantic payload wins on collision — semantic side carries the richer shape produced by `SemanticMemoryPath`), filters by `min_score` post-fusion, and truncates to `limit`. `write_event` mirrors accepted payloads into the wired lexical index; failures are logged, not raised, to preserve write durability. `InMemoryLexicalIndex` uses BM25-Okapi (k1=1.5, b=0.75) with tokenization matching the ports contract; corpus filtering reads `attributes.corpus_name`.
- **ADR:** ADR-085, ADR-099
- **Logged:** 2026-09-10 03:20 EDT

#### DozerDB Lucene fulltext lexical adapter (`DozerDbLexicalIndex`) — VENDORED (Stage 7.4+1)
- **Source:** https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/ (Neo4j Lucene fulltext index; Cypher `CALL db.index.fulltext.queryNodes(...)`)
- **License:** GPL-3.0 (Neo4j Community) / DozerDB fork (permissive) — real integration point uses DozerDB's permissive fork already vendored in Stage 1.8; adapter code is MIT under kosmos-lms.
- **Kosmos location:** `adapters/memory/dozerdb/dozerdb_lexical_index.py`
- **Port(s):** `LexicalIndex` Protocol (adapter-scoped; defined in `adapters/memory/dozerdb/adapter.py`)
- **Modifications:** production `LexicalIndex` implementation backed by DozerDB's Lucene fulltext index (per ADR-100). Mirrors `DozerDbGraphBackend`'s async-driver + `_init_error` + sync-non-throwing `is_healthy` + idempotent `close` pattern. `index_event` writes `MERGE (n:MemoryEvent {id: $id}) SET n.text = $text, n.as_of = datetime($as_of_iso), n.corpus_name = $corpus`, where `text` is the shared subject-predicate-object concatenation from `_lex_text_from_payload` (parity with `InMemoryLexicalIndex`). `search_lexical` calls `CALL db.index.fulltext.queryNodes($index_name, $query) YIELD node, score` with a post-YIELD `WHERE $corpus IS NULL OR node.corpus_name = $corpus` filter, ordering + limit, and returns `MemoryHit`s carrying a minimal payload (`{"text": ..., "attributes": {"corpus_name": ...}}` — full-triple rehydration is `MemoryPort.query_temporal`'s job). Bootstraps the fulltext index lazily on first `index_event`/`search_lexical` via `CREATE FULLTEXT INDEX $index_name IF NOT EXISTS FOR (n:MemoryEvent) ON EACH [n.text]`. Both `label` and `index_name` are constructor-tunable and go through the `DozerDbGraphBackend` identifier guard (`^[A-Za-z_][A-Za-z0-9_]*$`) before literal Cypher interpolation (ADR-100 D2 — `CREATE FULLTEXT INDEX` does not accept `$name` substitution). Lucene procedure failures degrade to `[]` with a warning log, matching the log-only side-effect discipline of `DozerDbMemoryAdapter.write_event`'s lexical mirror. Fast tier: mocked `neo4j.AsyncGraphDatabase` (25 tests). Live tier: env-gated `KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL=1` against `ops/compose/memory.yml`. Boot-time wiring into `ZetesisPlugin`'s DozerDB factory deferred to Stage 7.4+2.
- **ADR:** ADR-099, ADR-100
- **Logged:** 2026-09-10 03:45 EDT

#### Tektos planner (Kosmos-native seed) — VENDORED (Stage 4.7)
- **Source:** none (Kosmos-native seed; full donor absorption deferred)
- **License:** MIT
- **Kosmos location:** `plugins/tektos/planner/turn_planner.py`
- **Port(s):** `EventBusPort` (ADR-086)
- **Modifications:** hand-authored `TektosTurnPlanner.plan(prompt: str) -> Plan` returning a scripted 3-node chain `(read → analyze → summarize)` with linear `depends_on`. Emits `tektos.plan.started` + one `tektos.plan.node` per node + `tektos.plan.completed` on `EventBusPort` per ADR-086 (payload carries `plan_id`, `node_id`, `correlation_id=plan_id`, `source="tektos_planner"`). No LLM call at Stage 4.7 — satisfies the Stage 4.7 DoD verb ("a scripted plan node round-trips through EventBusPort") without landing `LLMPort` role-routing on the critical path.
- **ADR:** ADR-093
- **Logged:** 2026-09-10 01:15 EDT

#### Tektos planner (full donor absorption) — PLANNED (Stage 4.7+1)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/src/tektos/agents/planner (8 modules: `orchestrator.py`, `translator.py`, `disambiguator.py`, `spec_generator.py`, `template_selector.py`, `repo_map.py`, `language_game.py`, `models.py`)
- **License:** MIT (re-license at port-in)
- **Kosmos location:** `plugins/tektos/planner/vendor/` + extend `TektosTurnPlanner` to invoke translator → disambiguator → spec_generator via `LLMPort`.
- **Port(s):** `LLMPort` (Hermes topology ADR-087), `EventBusPort`, `RepoMapPort` (future)
- **Modifications:** planner LLM calls routed through `LLMPort`; role-routing (CPU-planner / GPU-coder split per ADR-087) required before absorption; explicitly deferred at ADR-093 to keep Stage 4.7 critical path independent of ADR-087 benchmark.
- **ADR:** ADR-087, ADR-093

#### Tektos self-repair donor data model — VENDORED (Stage 5.6)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/self_repair/models.py (`RepairStatus`, `RepairStrategy`, `DegradationLevel` enums + `RepairRecord` dataclass only)
- **Commit / Version:** upstream commit `2b45cac1f9ac214c85ff53571b949445b5415209` (2026-09-10)
- **License:** MIT (re-licensed at port-in — upstream repo has no LICENSE; sole copyright holder rmholston420)
- **Kosmos location:** `adapters/tektos/vendor/self_repair_models_donor.py`
- **Port(s):** none directly — consumed by `plugins/tektos/self_repair/proposer.py` which drives `ApprovalGatewayPort` + `MemoryPort` + `EventBusPort`
- **Modifications:** vendored ONLY the pure-data primitives (ADR-095 D1). Dropped `RepairResult`, `HealthSnapshot`, `DegradationPlan` from `models.py` — all coupled to the `SelfRepairEngine` orchestrator which is intentionally NOT ported. Enum vocabulary retained unchanged so future post-ADR-090 engine port lands without naming discontinuity. Retained `to_dict`/`from_dict` serializers unchanged.
- **ADR:** ADR-095 (Stage 5.6 propose-only scope)
- **Logged:** 2026-09-10 02:20 EDT

#### Tektos self-improvement donor data model — VENDORED (Stage 5.6)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/self_improvement/engine.py (`ExperienceRecord` dataclass only)
- **Commit / Version:** upstream commit `2b45cac1f9ac214c85ff53571b949445b5415209` (2026-09-10)
- **License:** MIT (re-licensed at port-in — upstream repo has no LICENSE; sole copyright holder rmholston420)
- **Kosmos location:** `adapters/tektos/vendor/self_improve_models_donor.py`
- **Port(s):** none directly — consumed by `plugins/tektos/self_improve/proposer.py`
- **Modifications:** vendored ONLY `ExperienceRecord` (ADR-095 D1). `SelfImprovementAdapter` (openhands-ext feedback loop wiring) and `LoopOrchestrator` (session-lifecycle hook path) are intentionally NOT ported — both auto-trigger self-modification on session completion and persist experience against live meta-learning databases (violates ADR-090 interim rule 4). Retained `to_dict`/`to_json`/`from_dict` serializers unchanged (feeds future Stage 7.4 Hindsight bridge without a separate vendoring step).
- **ADR:** ADR-095 (Stage 5.6 propose-only scope)
- **Logged:** 2026-09-10 02:20 EDT

#### Tektos self-improve + self-repair proposers — HAND-BUILT (Stage 5.6)
- **Source:** Kosmos-native (built on top of the vendored donor data model above); replaces the wholesale port of the donor engine/strategies/workflows/health_monitor/effectiveness modules that would ship apply paths during the ADR-090 DEFERRED window.
- **Commit / Version:** N/A (Kosmos-native)
- **License:** MIT (kosmos-lms LICENSE)
- **Kosmos location:** `plugins/tektos/self_improve/proposer.py` (`SelfImprovementProposer`, `SelfImprovementProposal`), `plugins/tektos/self_repair/proposer.py` (`SelfRepairProposer`, `SelfRepairProposal`)
- **Port(s):** `ApprovalGatewayPort` (ADR-033), `MemoryPort` (ADR-027, spec §25.4), `EventBusPort` (ADR-023, ADR-086)
- **Modifications:** propose-only proposers per ADR-095 D2. Each `propose()` routes through `ApprovalGatewayPort.propose(tier=HUMAN_REQUIRED, proposing_domain="tektos")` (ADR-095 D3), writes `MemoryPort` with `provenance="tektos_self_modification"` + `confidence=0.85` (satisfies ADR-090 interim rule 3 + spec §25.4 ≤ 0.9 ceiling), publishes `tektos.self_modification.proposed` (namespace reserved by ADR-086). Each `apply()` raises `NotImplementedError` referencing ADR-090 — physically cannot mutate the filesystem (belt-and-suspenders on top of the approval-gate deny path). `record_denial()` writes the second `MemoryPort` triple with `predicate="tektos.self_modification.denied"` (ADR-095 D4) so denials are as observable as proposals. `provenance` is a class-level constant (not a ctor arg) — cannot be overridden per instance. Confidence ceiling of 0.9 enforced at ctor.
- **ADR:** ADR-095 (Stage 5.6 propose-only scope)
- **Logged:** 2026-09-10 02:20 EDT

#### Tektos self-improvement + self-repair engines — DEFERRED (post-ADR-090)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/src/tektos/self_repair (engine.py, strategies.py, workflows.py, health_monitor.py, effectiveness.py — 2465 lines) + .../self_improvement/engine.py (`SelfImprovementAdapter` 672 lines) + .../agents/self_improvement/loop_orchestrator.py (275 lines) + .../self_modification/{self_gui_expander.py, self_test_expander.py} (792 lines)
- **License:** MIT (relicensed at port-in when landed)
- **Kosmos location (planned):** `plugins/tektos/self_repair/engine.py`, `strategies.py`, `workflows.py`, `health_monitor.py`, `effectiveness.py`; `plugins/tektos/self_improve/engine.py`; `adapters/self_modification/tektos/` (adapter under future `SelfModificationPort`).
- **Port(s):** `SelfModificationPort` (ADR-090 — PROPOSED / DEFERRED)
- **Modifications:** intentionally NOT ported in Stage 5.6 per ADR-095 §Consequences. Donor engines carry real apply paths (`APPLY_PATCH`, `RESTART_SERVICE`, `CLEAR_CACHE`, `FREE_VRAM`, filesystem-mutating expanders, session-lifecycle auto-triggers, meta-learning persistence loops) that would ship apply code during the ADR-090 DEFERRED window (violates ADR-090 interim rule 4). Unlocked at ADR-090 ratification.
- **ADR:** ADR-090 (deferred), ADR-095 (exclusion locked)

#### Tektos gateway proxy — PLANNED (Stage 2)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/tektos/gateway
- **License:** MIT (relicensed at port-in)
- **Kosmos location:** `adapters/event_bus/tektos_gateway/`
- **Port(s):** `EventBusPort` (ADR-086 formalises envelope taxonomy)
- **Modifications:** WebSocket proxy at `:8765` becomes an `EventBusPort` transport adapter; envelopes tagged per ADR-086 taxonomy (`tektos.*`, `immune.*`, `thermal.*`, `loop_safety.*`, `sandbox.*`, `hindsight.*`).
- **ADR:** ADR-086

#### Tektos frontend (Next.js 15.4, 40 panels) — SCAFFOLDED (Stage 2, 2026-09-10)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/frontend
- **License:** MIT (relicensed at port-in)
- **Kosmos location:** `plugins/tektos/frontend/` (upstream code drop deferred to Stage 3.13+); Stage 2 shell integration lives at `ui/app/tektos-ultima/`, `ui/components/TektosUltimaBridge.tsx`, and `kernel/tektos_ultima_bridge.py`.
- **Port(s):** `FrontendContractPort` (ADR-089 adds `PanelKind.IFRAME`); microfrontend shell integration per ADR-091.
- **Modifications:** Tektos Next 15.4 app runs on upstream port `:5556` (spec §25.7); Kosmos kernel exposes it same-origin at `/tektos-ultima/frontend/*` via Starlette streaming proxy (env `KOSMOS_TEKTOS_ULTIMA_UPSTREAM`, default `http://127.0.0.1:5556`); Kosmos Next 16.2.11 shell mounts it as `PanelKind.IFRAME` under **`/tektos-ultima`** (not `/tektos`, which stays the ADR-065 approval list); postMessage bridge routes envelopes to `POST /api/tektos-ultima/bridge` which validates `tektos.*` namespace + publishes to `EventBusPort`. Stage 3.13+ ports upstream panels + wires them through `FrontendContractPort` descriptors.
- **ADR:** ADR-089, ADR-091

#### Tektos tool registry — VENDORED (Stage 4.7)
- **Source:** https://github.com/rmholston420/tektos-ultima
- **Commit / Version:** `2b45cac1f9ac214c85ff53571b949445b5415209` (2026-09-10)
- **License:** MIT (re-licensed at port-in; rmholston420 sole copyright)
- **Kosmos location:** `adapters/sandbox/tektos/vendor/tool_registry_donor.py` (donor snapshot — trimmed `ToolDefinition` + JSON-schema validation), `plugins/tektos/tools/registry.py` (`TektosToolRegistry`, `ToolDescriptor`)
- **Port(s):** `ApprovalGatewayPort` + `ApprovalResolverPort` (ADR-033, ADR-045), `SandboxPort` (ADR-082), `EventBusPort` (ADR-086)
- **Modifications:** donor `ToolRegistry` trimmed from 553 lines to ~140 in vendor snapshot; kept `ToolDefinition` shape (`name`, `description`, `parameters` JSON schema, `handler`, `enabled`, `timeout`) + `jsonschema` validation with permissive fallback; dropped MCP client integration (Stage 4.8+), REST API surface, direct event emission (routed through `EventBusPort` instead), pre-baked bash/file/search handlers (Kosmos plugin layer registers explicitly with approval-tier metadata upstream lacked). `TektosToolRegistry` adds: `ToolDescriptor` extends the upstream shape with `approval_tier: ChangeApprovalTier` + `network: SandboxNetworkPolicy`; `invoke()` validates arguments then routes through `ApprovalGatewayPort.propose` (AUTONOMOUS returns synchronously; HUMAN_REVIEW / HUMAN_REQUIRED polls `ApprovalResolverPort.get_by_id` every 100 ms with jittered backoff and hard timeout, raises `ToolApprovalDenied` on REJECTED / REVIEW_MISSED); execution flows through `SandboxPort.run` (never direct handler invocation — no bypass of the isolation boundary); every `tektos.tool.{invoked,approved,denied,completed}` envelope carries `provenance="tektos_tool"` + `confidence=1.0` in payload per Stage 4.7 DoD.
- **ADR:** ADR-093
- **Logged:** 2026-09-10 01:15 EDT

#### Tektos MCP integration — VENDORED (Stage 4.8)
- **Source:** https://github.com/rmholston420/tektos-ultima MCP client + upstream `ToolRegistry` MCP branch (pattern-vendored: `MCPPort` + adapters already landed at Stage 3.2; Stage 4.8 adds bridge onto the Stage-4.7 registry)
- **Commit / Version:** upstream commit `2b45cac1f9ac214c85ff53571b949445b5415209` (2026-09-10)
- **License:** MIT (re-licensed at port-in — upstream repo has no LICENSE; sole copyright holder rmholston420)
- **Kosmos location:** `plugins/tektos/mcp/tool_bridge.py` (Stage 4.8), `plugins/tektos/mcp/tool_policy.py` (Stage 3.2 — locked `TEKTOS_TOOL_TIER_MAP`)
- **Port(s):** `MCPPort` (read), `ApprovalGatewayPort`, `SandboxPort` — no new port surface (composition-only bridge)
- **Modifications:** `MCPToolBridge.discover_and_register` translates `MCPPort.list_tools()` → `ToolDescriptor` registrations on the Stage-4.7 `TektosToolRegistry`; tier resolution honors the locked `TEKTOS_TOOL_TIER_MAP` (ADR-037) with `DEFAULT_TIER=HUMAN_REQUIRED` fail-closed; per-tier default `SandboxNetworkPolicy` (AUTONOMOUS/HUMAN_REVIEW=`loopback`, HUMAN_REQUIRED=`none`); `network_override` kwarg lets tests pin `network="none"` globally; every registered MCP tool flows through the registry — no direct `mcp.call_tool` path bypasses the approval gate or the pre-approval detector chain.
- **ADR:** ADR-094 (Stage 4.8 tool-surface reconciliation)
- **Logged:** 2026-09-10 02:05 EDT

#### Tektos filesystem tools (read/list/write/delete) — VENDORED (Stage 4.8)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/providers/sandbox_provider.py (`_file_read`, `_file_write`, `_file_delete` handlers + `_safe_path` traversal guard)
- **Commit / Version:** upstream commit `2b45cac1f9ac214c85ff53571b949445b5415209` (2026-09-10)
- **License:** MIT (re-licensed at port-in — upstream repo has no LICENSE; sole copyright holder rmholston420)
- **Kosmos location:** `plugins/tektos/tools/filesystem.py` (descriptors + invocation helpers), `adapters/sandbox/tektos/vendor/fs_ops_donor.py` (vendored `resolve_within_root` + `format_file_read_page` primitives)
- **Port(s):** `SandboxPort` (execution), `ApprovalGatewayPort` (tier gating), `MemoryPort` (write-through), `EventBusPort` (envelopes)
- **Modifications:** four `ToolDescriptor` registrations — `file_read`/`file_list`=AUTONOMOUS, `file_write`=HUMAN_REVIEW, `file_delete`=HUMAN_REQUIRED, all `network="none"` (per ADR-094 §Rationale). Execution model differs from donor: argv-first through `SandboxPort.run` using coreutils (`cat`/`ls`/`tee`/`rm`) instead of in-process handlers; write content passed via stdin, never on command line (closes shell-injection surface). Path-traversal detector runs pre-approval (see below); malicious paths never reach `ApprovalPort.propose`. `format_file_read_page` primitive preserved verbatim from donor.
- **ADR:** ADR-094 (Stage 4.8 tool-surface reconciliation)
- **Logged:** 2026-09-10 02:05 EDT

#### Tektos path-traversal detector — VENDORED (Stage 4.8)
- **Source:** derived from `_safe_path` in https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/providers/sandbox_provider.py — restructured as `Detector` protocol implementation, not a direct port of the upstream call
- **Commit / Version:** upstream commit `2b45cac1f9ac214c85ff53571b949445b5415209` (2026-09-10)
- **License:** MIT (re-licensed at port-in — upstream repo has no LICENSE; sole copyright holder rmholston420)
- **Kosmos location:** `plugins/tektos/tools/detectors/path_traversal.py` (detector), `adapters/sandbox/tektos/vendor/fs_ops_donor.py::resolve_within_root` (traversal primitive)
- **Port(s):** `ImmunePort` (implements `Detector` Protocol from `ports/immune.py`)
- **Modifications:** upstream `_safe_path` returned `Path|None` with side-effect logging — vendored `resolve_within_root` returns `ResolveOutcome(resolved, reason)` so the detector emits a structured `DetectorHit.evidence` (`reason=<tag> path=... namespace_root=... tool=...`) with tag one of `empty_path` / `dotdot_component` / `absolute_escape` / `symlink_escape` / `resolve_error:*`; symlink check strengthened via `Path.is_relative_to` on the resolved real path. Detector self-filters on `kind=="tektos.tool.filesystem"` and `tool_name in FILESYSTEM_TOOL_NAMES` so it can be registered without polluting non-filesystem tool invocations. `severity_ceiling="block"`, `name="path_traversal"`.
- **ADR:** ADR-094 (Stage 4.8 tool-surface reconciliation)
- **Logged:** 2026-09-10 02:05 EDT

#### Tektos CI (`.github/workflows/ci.yml`) — PLANNED (Stage 0.5)
- **Source:** https://github.com/rmholston420/tektos-ultima/blob/main/.github/workflows/ci.yml
- **License:** MIT (relicensed at port-in)
- **Kosmos location:** `.github/workflows/ci.yml`
- **Port(s):** N/A (build infrastructure)
- **Modifications:** six-job base (ruff, mypy, pytest, next build, eslint, Playwright chromium) plus two new jobs — Kosmos port-contract tests (`pytest tests/ports/`) and AST plugin-isolation guard (`scripts/check_plugin_isolation.py` enforcing ADR-007).
- **ADR:** ADR-077

---

## Stage 6.5 — Voice + Vision port-in (2026-09-10)

#### faster-whisper (SYSTRAN) — HAND-BUILT (donor-informed) (Stage 6.5)
- **Source:** https://github.com/SYSTRAN/faster-whisper (pip: `faster-whisper`); design lineage from donor `https://github.com/rmholston420/tektos-ultima/blob/main/src/tektos/voice.py` (`STTEngine` class, lines 102–149)
- **Commit / Version:** faster-whisper as installed at Stage 6.5 (pinned via optional `voice` extra); donor upstream commit `2b45cac1f9ac214c85ff53571b949445b5415209`
- **License:** MIT (faster-whisper) — dependency `CTranslate2` also MIT; donor re-licensed MIT at port-in
- **Kosmos location:** `adapters/voice/faster_whisper/adapter.py`
- **Port(s):** `VoicePort` (transcribe only; synthesize raises `TTSNotConfigured` per ADR-097 D3)
- **Modifications:** rewrite behind port — async wrapper around `WhisperModel.transcribe`; env-tunable model/device/compute-type (`KOSMOS_WHISPER_MODEL`/`_DEVICE`/`_COMPUTE_TYPE`); per-segment confidence derived from `avg_logprob` via `exp()` with `[0.0, 1.0]` clamp; aggregate confidence = mean of segment confidences; segments streamed through a bounded list; MIME → suffix table for temp-file spool; graceful `is_healthy()` false when `faster_whisper` import unavailable
- **ADR:** ADR-097 (VoicePort adapter selection)
- **Logged:** 2026-09-10 02:48 EDT

#### NoOp VoicePort adapter — HAND-BUILT (Stage 6.5)
- **Source:** Kosmos-native (no upstream)
- **License:** MIT (kosmos-lms scaffold policy)
- **Kosmos location:** `adapters/voice/noop/adapter.py`
- **Port(s):** `VoicePort`
- **Modifications:** N/A; ships a 44-byte-header silent WAV (100 ms @ 8 kHz mono 8-bit PCM) for `synthesize`; empty `Transcript` for `transcribe`; single `noop`/`No-op`/`und`/`neutral` VoiceProfile
- **ADR:** ADR-097 D4
- **Logged:** 2026-09-10 02:48 EDT

#### rhasspy/piper + OHF-Voice/piper1-gpl — EVALUATED-REJECTED (Stage 6.5)
- **Source:** https://github.com/rhasspy/piper (archived 2025-10-06); active fork https://github.com/OHF-Voice/piper1-gpl
- **License:** rhasspy/piper was MIT; active fork `piper1-gpl` is **GPL-3.0**; runtime dep `espeak-ng` also GPL
- **Reason for rejection:** fails `kosmos-port-workflow` §3 permissive-license filter (GPL viralizes the kosmos-lms monorepo). No user override sought — TTS is not on the Stage 6.5 DoD critical path; deferred to Stage 6.5+1 ADR (ADR-097 D3) after Coqui-fork benchmark.
- **ADR:** ADR-097 D3

#### edge-tts — EVALUATED-REJECTED (Stage 6.5)
- **Source:** https://github.com/rany2/edge-tts (donor `src/tektos/voice.py` TTSVoice used this)
- **License:** LGPL-3.0 (library) — the runtime engine is Microsoft Edge's **cloud** TTS service
- **Reason for rejection:** violates persistent user preference "free, self-hosted, open-source tooling that runs on Linux" (relies on Microsoft cloud endpoint). TTS engine selection deferred per ADR-097 D3.
- **ADR:** ADR-097 D3

#### TTS engine selection — PLANNED (post-Stage 6.5)
- **Candidates for post-Stage 6.5 benchmark:** `idiap/coqui-ai-TTS` (MPL-2.0 — most active Coqui fork), StyleTTS2 (MIT), Kokoro-82M (Apache-2.0), OpenVoice-derived forks
- **Trigger:** Stage 6.5+1 ADR when a downstream feature requires synthesis
- **Interim:** `FasterWhisperVoiceAdapter.synthesize` raises `TTSNotConfigured`; `NoOpVoiceAdapter` returns silent WAV for CI
- **ADR:** ADR-097 D3

#### Qwen2.5-VL 7B via Ollama — HAND-BUILT (Stage 6.5)
- **Source:** https://ollama.com/library/qwen2.5-vl (upstream model: https://github.com/QwenLM/Qwen2.5-VL); no donor code (Kosmos-native adapter)
- **Commit / Version:** `qwen2.5-vl:7b` at Ollama registry; adapter default overridable via env `KOSMOS_VISION_MODEL`
- **License:** Apache-2.0 (Qwen2.5-VL model + Ollama runtime)
- **Kosmos location:** `adapters/vision/ollama_qwen_vl/adapter.py`
- **Port(s):** `VisionPort` (describe + detect; extract_text raises `VisionCapabilityUnsupported` per ADR-098 D3)
- **Modifications:** N/A (no upstream code); async `httpx.AsyncClient` wrapper for `POST /api/generate` with base64-encoded `images` array; JSON-mode prompt for `detect` with robust parser tolerating top-level list, `{"detections": [...]}`  dict, or lone dict; malformed entries silently skipped; loopback-only base URL by default (`KOSMOS_OLLAMA_BASE_URL`); confidence for `describe` = 0.5 placeholder (model emits none); confidence for `detect` = per-entry JSON field with default 0.5; `is_healthy()` probes `GET /api/tags` with 2 s timeout
- **ADR:** ADR-098 (VisionPort adapter selection)
- **Logged:** 2026-09-10 02:48 EDT

#### Tesseract + pytesseract — HAND-BUILT (Stage 6.5)
- **Source:** https://github.com/tesseract-ocr/tesseract + https://github.com/madmaze/pytesseract; no donor code
- **License:** Apache-2.0 (both)
- **Kosmos location:** `adapters/vision/tesseract/adapter.py`
- **Port(s):** `VisionPort` (extract_text; describe + detect raise `VisionCapabilityUnsupported` per ADR-098 D2)
- **Modifications:** async wrapper around `pytesseract.image_to_data(output_type=DICT)`; per-block confidence normalised to `[0.0, 1.0]` via `conf/100`; blocks with `conf == -1` (Tesseract's "no OCR" sentinel) excluded from both text join and aggregate; aggregate confidence = mean of surviving block confidences; graceful `is_healthy()` false when binary missing; system `tesseract-ocr` binary path overridable via env `KOSMOS_TESSERACT_CMD`
- **ADR:** ADR-098
- **Logged:** 2026-09-10 02:48 EDT

#### NoOp VisionPort adapter — HAND-BUILT (Stage 6.5)
- **Source:** Kosmos-native
- **License:** MIT
- **Kosmos location:** `adapters/vision/noop/adapter.py`
- **Port(s):** `VisionPort`
- **Modifications:** N/A; empty `VisionDescription` (`model="noop"`); empty `OCRResult`; empty detections tuple; all confidences `0.0`
- **ADR:** ADR-098 D1
- **Logged:** 2026-09-10 02:48 EDT

#### Kosmos BlobStore (content-addressed) — HAND-BUILT (Stage 6.5)
- **Source:** Kosmos-native
- **License:** MIT
- **Kosmos location:** `adapters/data/blobs/blob_store.py`
- **Port(s):** N/A — helper, not a formal Kosmos port (per ADR-096 D3 rationale)
- **Modifications:** N/A; two-method sync API (`put_bytes(data) -> sha256_hex`, `open_path(sha256_hex) -> Path`); sha256 sharded 2-char prefix layout; atomic write via tempfile + `os.replace`; env `KOSMOS_BLOB_ROOT` override; idempotent — repeated writes of identical bytes are a no-op
- **ADR:** ADR-096 D3
- **Logged:** 2026-09-10 02:48 EDT

#### Kosmos TektosFrontendMemoryWriter (two-write pattern) — HAND-BUILT (Stage 6.5)
- **Source:** Kosmos-native
- **License:** MIT
- **Kosmos location:** `adapters/tektos_frontend/frontend_memory_writer.py`
- **Port(s):** consumes `MemoryPort` + `BlobStore`; shared by all Stage 6.5 voice + vision adapters
- **Modifications:** N/A; four record methods (voice, vision-description, vision-OCR, vision-detections); every call fans out to exactly two `MemoryPort.write_event` calls per ADR-096 D1 (ingest triple `confidence=1.0` + result triple with passthrough confidence per ADR-083/084); detection aggregate confidence = mean of per-detection confidences (empty → 0.0); result summary strings capped at 4 KiB / 256-char detection summary; raw bytes NEVER enter MemoryPort (bytes → BlobStore, URI + hash → MemoryPort)
- **ADR:** ADR-096 D1
- **Logged:** 2026-09-10 02:48 EDT

## Stage 8.0 — RelationalMemoryPort · Postgres 5th memory layer (ADR-102)

The 5th memory layer combines the R1 audit ledger (sessions, approvals,
tool-invocation, ADR-088 budget history, ADR-092 immune events) and the R2
episodic-narrative store (tsvector + hnsw pgvector hybrid search). Ships two
adapters: NoOp (aiosqlite in-memory, required for CI) and Postgres
(asyncpg + pgvector, production). Kernel wiring gated by
`KOSMOS_RELATIONAL_MEMORY={off,noop,postgres}` — see
`kernel/app.py::_boot_relational_memory`. All entries below logged
2026-09-10 05:00 EDT.

#### aiosqlite 0.22.1 — VENDORED
- **Source:** https://github.com/omnilib/aiosqlite
- **Commit / Version:** 0.22.1
- **License:** MIT
- **Kosmos location:** transitively via `pip install aiosqlite`; imported at
  `adapters/relational_memory/noop/adapter.py`
- **Port(s):** RelationalMemoryPort (noop adapter only)
- **Modifications:** none; async wrapper over stdlib sqlite3
- **ADR:** ADR-102 D2
- **Logged:** 2026-09-10 05:00 EDT

#### asyncpg 0.31.0 — VENDORED
- **Source:** https://github.com/MagicStack/asyncpg
- **Commit / Version:** 0.31.0
- **License:** Apache-2.0
- **Kosmos location:** transitively via `pip install asyncpg`; imported at
  `adapters/relational_memory/postgres/adapter.py`
- **Port(s):** RelationalMemoryPort (postgres adapter only)
- **Modifications:** none; connection pool `min_size=2 max_size=10`;
  per-connection `init` callback registers pgvector types
- **ADR:** ADR-102 D2
- **Logged:** 2026-09-10 05:00 EDT

#### pgvector-python 0.5.0 — VENDORED
- **Source:** https://github.com/pgvector/pgvector-python
- **Commit / Version:** 0.5.0
- **License:** MIT
- **Kosmos location:** transitively via `pip install pgvector`; imported at
  `adapters/relational_memory/postgres/adapter.py` (register_vector for
  asyncpg codec) and `migrations/versions/001_initial.py` (server-side
  extension via `CREATE EXTENSION vector`)
- **Port(s):** RelationalMemoryPort (postgres adapter only)
- **Modifications:** none; embedding column typed `vector(1536)` matching
  the current EmbeddingsPort default (OpenAI text-embedding-3 shape)
- **ADR:** ADR-102 D3, D5
- **Logged:** 2026-09-10 05:00 EDT

#### pg_uuidv7 — VENDORED (server-side Postgres extension, optional)
- **Source:** https://github.com/fboulnois/pg_uuidv7
- **Commit / Version:** tracked at operator install time; migration is
  tolerant of absence (falls back to `gen_random_uuid()`)
- **License:** MPL-2.0
- **Kosmos location:** `adapters/relational_memory/postgres/migrations/
  versions/001_initial.py` — `CREATE EXTENSION IF NOT EXISTS pg_uuidv7`
  guarded by a DO block that swallows errors and warns
- **Port(s):** RelationalMemoryPort (postgres adapter only)
- **Modifications:** none; the migration authors a `kosmos_uuid7()` PL/pgSQL
  wrapper that dispatches to `uuid_generate_v7()` when available, else
  `gen_random_uuid()` — preserves temporal ordering when the extension is
  installed and stays functional when it is not
- **ADR:** ADR-102 D3
- **Logged:** 2026-09-10 05:00 EDT

#### Alembic 1.19.2 — VENDORED (migrations-only)
- **Source:** https://github.com/sqlalchemy/alembic
- **Commit / Version:** 1.19.2
- **License:** MIT
- **Kosmos location:** `adapters/relational_memory/postgres/migrations/`
  (env.py + alembic.ini + script.py.mako + versions/001_initial.py)
- **Port(s):** operator-only tool for RelationalMemoryPort postgres schema
  management; NOT imported at runtime by the kernel or by any plugin
- **Modifications:** env.py reads DSN from `KOSMOS_POSTGRES_URI` at runtime
  (normalises `postgres://` → `postgresql+asyncpg://`); migration is
  offline-and-online-safe; no ORM models declared (schema is raw SQL to
  keep Postgres-specific features — tsvector generated column, pgvector,
  pg_uuidv7 — first-class rather than approximated through the ORM)
- **ADR:** ADR-102 D3, D7 (no auto-migrate on boot)
- **Logged:** 2026-09-10 05:00 EDT

## Stage 8.1 — SessionPort (ADR-103)

#### Tektos-Ultima `state_machine.py` — VENDORED
- **Source:** https://github.com/rmholston420/tektos-ultima
- **Commit / Version:** as of `/home/user/workspace/audit/tektos-ultima` snapshot, 2026-09-10
- **License:** MIT — re-licensed only at port-in-point; kosmos-lms declares
  MIT; rmholston420 is sole copyright holder on both projects
- **Kosmos location:** `adapters/session/tektos/vendor/state_machine.py` (235 lines)
- **Port(s):** SessionPort (adapters/session/tektos/adapter.py)
- **Modifications:** single import rewrite (ADR-103 D2):
  - `from tektos.event_bus import get_event_bus` →
    `from adapters.session.tektos.vendor_bindings import get_event_bus`
    (shim wraps 3-arg positional `publish(event_type, session_id, payload)`
    into an envelope-first `EventBusPort.publish(EventEnvelope)` — the
    only concession needed to bridge donor's pre-ADR-023 publish surface)
- **ADR:** ADR-103
- **Logged:** 2026-09-10 05:24 EDT

#### Tektos-Ultima `runtime/session.py` — VENDORED
- **Source:** https://github.com/rmholston420/tektos-ultima
- **Commit / Version:** as of `/home/user/workspace/audit/tektos-ultima` snapshot, 2026-09-10
- **License:** MIT — re-licensed only at port-in-point
- **Kosmos location:** `adapters/session/tektos/vendor/session.py` (494 lines)
- **Port(s):** SessionPort (adapters/session/tektos/adapter.py)
- **Modifications:** three import rewrites (ADR-103 D2):
  - `from tektos.state_machine import State, get_state_machine` →
    `from adapters.session.tektos.vendor.state_machine import State, get_state_machine`
    (retargets to the vendored sibling so the two donor files stay a
    self-consistent unit under `vendor/`)
  - `from tektos.store.event_store import append_event` →
    `from adapters.session.tektos.vendor_bindings import append_event`
    (shim routes lifecycle events through the same EventBusPort used
    by state transitions; the SQLite event store is deferred to Stage
    13 per ADR-103 D3)
  - Function-local `from tektos.store.event_store import delete_session
    as store_delete` → `from adapters.session.tektos.vendor_bindings
    import store_delete` (shim returns 0 with an INFO log at Stage 8.1)
- **ADR:** ADR-103 (D2 fidelity port, D3 store deferral, D7 SessionState
  naming precedence)
- **Logged:** 2026-09-10 05:24 EDT
