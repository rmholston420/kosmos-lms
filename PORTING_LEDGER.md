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

#### Tektos hindsight memory (bridge adapter) — PLANNED (Stage 3-5)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/tektos/hindsight
- **License:** MIT (relicensed at port-in)
- **Kosmos location:** `adapters/memory/hindsight_bridge/`
- **Port(s):** `MemoryPort` (bridge; ADR-085 extends `MemoryPort.search_hybrid`)
- **Modifications:** default hindsight port fixed from `:9177` → `:9000` (Tektos-Ultima source bug); adapter fronts hindsight for Tektos read/write path in Stages 3–5 while DozerDB remains the canonical Kosmos store; retired in Stage 8 per plan Decision H1 → H2 migration.
- **ADR:** ADR-085

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

#### Tektos self-improvement + self-repair — PLANNED (Stage 5, gated)
- **Source:** https://github.com/rmholston420/tektos-ultima/tree/main/tektos/self_improve, .../self_repair
- **License:** MIT (relicensed at port-in)
- **Kosmos location:** `plugins/tektos/self_improve/`, `plugins/tektos/self_repair/`
- **Port(s):** `SelfModificationPort` (ADR-090 — PROPOSED / DEFERRED); until then, self-modification paths are gated behind an approval loop via `ApprovalPort`.
- **Modifications:** all self-modifying paths write `provenance="tektos_self_modification"` + `confidence<1.0` on `MemoryPort` (zero-trust); no direct filesystem mutation until ADR-090 ratified.
- **ADR:** ADR-090 (deferred)

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
