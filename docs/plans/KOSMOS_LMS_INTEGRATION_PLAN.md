# Kosmos-LMS Integration Plan

**Full fork + rewrite of `rmholston420/kosmos` merging `rmholston420/tektos-ultima` as the canonical `plugins/tektos/` implementation.**

- **Target repo:** `rmholston420/kosmos-lms` (public, MIT-licensed)
- **Source repos:** `rmholston420/kosmos` (MIT), `rmholston420/tektos-ultima` (no LICENSE, sole author = Lama Lawapa Naljor)
- **Frontend model:** Kosmos Next.js shell hosts the Tektos Next.js UI as an iframe/microfrontend mounted at `/tektos/*` behind the kernel
- **Scaffold policy:** preserve Kosmos `plugins/tektos/` (ratified by ADR-036/037/038/041/042/044/045/046/063/065); layer Tektos-Ultima into it as the runtime; harvest anything of value from the current Kosmos scaffold back into Tektos
- **License strategy:** kosmos-lms declares MIT at repo root; every Tektos-derived module gets a PORTING_LEDGER entry that cites the author (rmholston420) as sole copyright holder relicensing at port-in
- **Discipline:** Kosmos-Build-Spec-v25 rules apply verbatim — ports/adapters, ADR authoring, PORTING_LEDGER, BUILD_LOG/DEBUG_LOG/KNOWN_ISSUES/SESSION_HANDOFF quartet, ADR-007 events-only cross-plugin coupling, MemoryPort zero-trust writes

Prepared 2026-09-10. Standalone, step-by-step; every step lists inputs, outputs, ADR touchpoints, PORTING_LEDGER touchpoints, tests, and the DoD that must pass before advancing.

---

## 0. Executive summary

Tektos-Ultima was always meant to live inside Kosmos. This plan folds it in as **the** implementation of the Tektos plugin under Kosmos governance, without discarding the ratified scaffold that already occupies `plugins/tektos/`. The scaffold owns port-integration surfaces (ADR-036 TektosAgent shape, ADR-045 HTMX dashboard, ADR-063 kernel mount, ADR-065 UI mount, aider repomap, docling ingest, Pier eval, OpenSpec parser); Tektos-Ultima brings the multi-iteration runtime, immune system, loop safety, planner, self-improvement/self-repair, thermal control, 4-tier memory model, tool registry, gateway proxy, and 40 status panels.

Nine stages, each with an exit gate; the whole plan is ~60 numbered work steps. Stages 0–2 make kosmos-lms exist and align both trees to shared ports without any Tektos code moving. Stages 3–6 migrate Tektos capabilities behind ports, one subsystem at a time, each with an ADR + PORTING_LEDGER + BUILD_LOG triple. Stages 7–8 land the UI microfrontend and the systemd deployment surface. Stage 9 is the retirement + freeze.

Six new formal ports are proposed (ADR-authored): `ImmunePort`, `LoopSafetyPort`, `ThermalPort`, `SandboxPort`, `VoicePort`, `VisionPort`. One existing port (`MemoryPort`) is extended with a Hindsight-style hybrid retrieval query interface (documented as an ADR amendment, not a new port). `SelfModificationPort` is deliberately deferred until the immune-system and approval interlocks land — it is the highest-risk capability and gets its own late-stage ADR.

The frontend keeps the two Next.js apps distinct: `ui/` (Kosmos shell, Next 16.2.11) remains the outer chrome; `plugins/tektos/frontend/` (Tektos, Next 15.4) is served from the kernel under `/tektos/*` and iframed in. This defers a Next.js version reconciliation, gives each app its own dev port, and lets the Tektos UI keep its 40 panels and Monaco/xterm/D3 dependencies untouched.

CI adopts Tektos-Ultima's six-job pipeline (ruff, mypy, pytest, next build, eslint, Playwright chromium) as the baseline and extends it with Kosmos's port-contract tests, plugin-isolation AST check, and Playwright against the Kosmos UI.

## 1. Guiding principles (non-negotiable)

1. **Kosmos discipline is authoritative.** Every port/adapter/plugin/ADR/log rule in `Kosmos-Build-Spec-v25.md` applies to kosmos-lms unchanged. When Tektos-Ultima's practice conflicts with Kosmos's, Kosmos wins.
2. **ADR-007 events-only cross-plugin coupling.** No plugin imports another. Every Tektos capability that must reach outside its own plugin does so through EventBusPort or a formal port.
3. **MemoryPort zero-trust writes are non-bypassable.** Every persistence path adds `provenance` (from a Tektos taxonomy) and `confidence` before the port call. Anything that fails to supply both raises `MemoryWriteBlocked`.
4. **No ADR ID reuse.** Tektos-Ultima's two ADR sources (`ADR-LEDGER.md`, `adrs/README.md`) are discarded. All Tektos-derived decisions get new IDs in Kosmos's continuous sequence starting at ADR-077.
5. **PORTING_LEDGER before first commit** for every module carried over. Entry cites author (rmholston420) as sole copyright holder relicensing at port-in, SPDX `MIT`, source URL `https://github.com/rmholston420/tektos-ultima/blob/<sha>/<path>`, upstream commit SHA, port(s), modifications.
6. **One BUILD_LOG entry per step, one DEBUG_LOG entry per bug** — timestamps `YYYY-MM-DD HH:MM EDT`. Never edit past entries.
7. **Contract tests are the port lock.** Every port has a `test_contract.py` under `adapters/<port>/<component>/` that passes for the adapter and passes again when swapped to a different adapter for the same port.
8. **No plugin ships without its UI.** The FrontendContractPort parity check must return COMPLIANT before a Tektos capability can advance stage. Iframe mount counts as UI parity for kosmos-lms per the ADR-045 lineage.
9. **Colossus resource envelope is a stop condition.** 128 GB RAM, 32 GB VRAM. Any adapter that would breach at steady state is a stop.
10. **Deterministic before probabilistic.** Schema checks, routing, authorization, provenance stay deterministic. LLMs are called only for work that genuinely requires probabilistic reasoning.

## 2. Repo topology target

```
kosmos-lms/                                  # MIT, public
├── LICENSE                                  # MIT, author rmholston420
├── README.md
├── PORTING_LEDGER.md                        # seeded with every ported Tektos module
├── BUILD_LOG.md                             # started fresh at ADR-077 landing
├── DEBUG_LOG.md
├── KNOWN_ISSUES.md
├── SESSION_HANDOFF.md
├── Kosmos-Build-Spec-v26.md                 # v25 baseline + Tektos amendments (ADR-078)
├── Kosmos-Build-Sequence-v26.md
├── pyproject.toml
├── Makefile
├── .github/workflows/                       # 6-job baseline from tektos-ultima, extended
│   ├── ci.yml
│   └── contract-tests.yml
├── docs/
│   ├── adrs/                                # ADR-001..ADR-076 preserved; ADR-077+ new
│   ├── ports.md                             # canonical port allocation (MERGED registry)
│   └── knowledge/                           # docs from both repos, deduped
├── ports/                                   # 15 existing + 6 new (Immune/LoopSafety/Thermal/Sandbox/Voice/Vision)
├── adapters/                                # existing 15 + new Hermes LLM adapter, Postgres/Redis for MemoryPort ext.
├── plugins/
│   ├── phrouros/                            # unchanged from kosmos
│   ├── praxis/                              # unchanged
│   ├── zetesis/                             # unchanged
│   └── tektos/                              # ENLARGED
│       ├── agent.py                         # extended ADR-036 (multi-iteration)
│       ├── plugin.py                        # unchanged registration surface
│       ├── models.py, errors.py             # unchanged
│       ├── runtime/                         # NEW — carried from src/tektos/runtime/
│       ├── planner/                         # NEW — carried from src/tektos/agents/planner/
│       ├── agents/                          # NEW — coding/manager/self_improvement
│       ├── self_improvement/                # NEW
│       ├── self_modification/               # NEW (gated; ADR-090)
│       ├── self_repair/                     # NEW
│       ├── skills/                          # NEW
│       ├── memory/                          # kept; adapts hindsight_client to MemoryPort
│       ├── immune/                          # NEW — 12 detectors extracted, exposed as ImmunePort adapter
│       ├── loop_safety/                     # NEW — LoopSafetyPort adapter
│       ├── thermal/                         # NEW — ThermalPort adapter
│       ├── sandbox/                         # NEW — SandboxPort adapter over bwrap
│       ├── tools/                           # existing 7 built-ins served as in-process MCP server
│       ├── mcp/                             # existing tool_policy + fake_playwright + new tool servers
│       ├── openspec/, renderer/, repomap/, ingest/, eval/, ui/htmx/  # UNCHANGED (Kosmos-side scaffold)
│       ├── frontend/                        # NEW — carried from tektos-ultima/frontend/
│       ├── gateway_proxy/                   # NEW — carried as-is; retained for Hermes Desktop compat
│       └── tests/                           # extended: existing 13 + Tektos-Ultima's 336 py + 28 Playwright
├── kernel/
│   ├── app.py                               # extended: mounts /tektos/frontend (iframe host), /tektos/api/*
│   └── kernel_ui_glue/
├── ui/                                      # unchanged Kosmos Next 16 shell; adds <iframe src="/tektos/frontend"> panel
├── governance/                              # extended with axioms/ if Tektos axioms adopted
├── ops/                                     # extended with systemd/user/*.service unit set
│   └── systemd/user/
│       ├── kosmos-lms-kernel.service        # replaces tektos-backend
│       ├── kosmos-lms-gateway.service       # tektos gateway_proxy
│       ├── kosmos-lms-hindsight.service     # optional; only if Hindsight adapter path selected
│       ├── kosmos-lms-llm-hindsight.service # optional
│       ├── kosmos-lms-frontend.service      # Kosmos shell (ui/)
│       ├── kosmos-lms-tektos-frontend.service # Tektos plugin frontend
│       └── kosmos-lms.target
├── deploy/
│   ├── data-services/                       # Postgres/Neo4j/Redis one-shot installers (from tektos-ultima)
│   └── docker/                              # optional; not authoritative
├── scripts/
├── tests/                                   # kernel/tests remain; ports contract tests aggregate
└── vendor/                                  # unchanged from kosmos
```

Directory-level design decisions:

- **`plugins/tektos/frontend/`** houses the Tektos Next.js app inside the plugin, not at repo root, so `plugins/tektos/` remains a single deletable unit and ADR-007 boundaries hold.
- **`plugins/tektos/gateway_proxy/`** is a shim (not a plugin subsystem for cross-plugin coupling). It runs as its own process under systemd, purely translating Hermes Desktop JSON-RPC 2.0 ↔ kernel EventBusPort WS. Kept for Hermes compatibility; deprecatable in a later cut.
- **`plugins/tektos/immune/`, `loop_safety/`, `thermal/`, `sandbox/`** each contain both the port-adapter facade and the vendored logic. Each has its own contract test. Any plugin that wants immune coverage subscribes through EventBusPort or calls `ImmunePort` via the plugin's own port handle — no cross-plugin imports.

## 3. New ports proposal (six ADRs)

Each proposed port needs a full ADR under `docs/adrs/` following `kosmos-adr-authoring`. Draft outlines follow; full ADR bodies land in Stage 4.

### 3.1 ADR-079 — `ImmunePort` (scan/respond/health)

- **Contract:** `scan(ctx: ImmuneContext) -> list[Threat]`, `respond(threats: list[Threat]) -> list[ResponseRecord]`, `register_detector(name: str, detector: Detector) -> None`, `get_health() -> HealthScore`, `is_healthy() -> bool`.
- **Reference adapter:** `adapters/immune/tektos_defense/` — vendored from `src/tektos/runtime/immune_system.py` (1925 LOC, 12 detectors including SecretExposureDetector's 12 regex patterns).
- **Zero-trust boundary:** Immune events written through MemoryPort must carry `provenance="immune_system"` + `confidence` derived from `Threat.severity`.
- **Escalation ladder:** quarantine → throttle → isolate → halt is preserved. Isolation targets are addressed by VSM tag, not by plugin name (so `S3 Manager` isolation doesn't require the immune adapter to know which plugins are S3).
- **Alternatives considered:** fold into ObservabilityPort (rejected — response ladder is out-of-scope); make it a plugin (rejected — ambient coverage across plugins violates ADR-007 unless it's a port).
- **Consequences:** kernel boots ImmunePort before any other subsystem; every port that writes to MemoryPort emits an immune-observable event; SecretExposureDetector applies to log lines and outbound-tool arguments in-flight.

### 3.2 ADR-080 — `LoopSafetyPort` (hard limits + repetition + circuit breaker)

- **Contract:** `start_turn(session_id, config) -> TurnHandle`, `record(handle, snapshot: TurnSnapshot) -> LoopSafetyState`, `should_stop(handle) -> Optional[StopReason]`, `reset(session_id) -> None`.
- **Reference adapter:** `adapters/loop_safety/tektos_3tier/` — vendored from `src/tektos/runtime/loop_safety.py` (`max_turns=15`, `max_tokens_per_turn=8192`, `max_tokens_total=65536`, `max_wall_time_seconds=300.0`, `repetition_window=3`, `repetition_threshold=2`, `warning_threshold_pct=0.8`).
- **Interlock:** stop reasons emit envelopes on EventBusPort (`loop_safety.warning`, `loop_safety.stop`) that ImmunePort subscribes to.
- **Read-only tool budget** (`_readonly_tools_disabled`, `TEKTOS_READONLY_TOOL_ROUNDS`) is a LoopSafetyPort feature, not TektosAgent-internal — so any future coding agent behind LLMPort gets it for free.
- **Alternatives considered:** fold into ImmunePort (rejected — different lifecycle, sub-second turn-level state).

### 3.3 ADR-081 — `ThermalPort` (PID GPU/CPU regulation)

- **Contract:** `sample() -> ThermalSample`, `regulate() -> ThermalDecision`, `set_thresholds(yellow, cap, red) -> None`, `is_healthy() -> bool`.
- **Reference adapter:** `adapters/thermal/tektos_pid/` — vendored from `src/tektos/thermal/{regulator,monitor,metrics,power_optimizer}.py`. PID constants (`PID_KP`, `PID_KI`, `PID_KD`), thresholds (yellow 51 °C, cap 80 °C, red 88 °C), 400 W GPU limit, file-only mode ≥ 80 °C.
- **Kernel wiring:** thermal `>= cap` blocks new LLMPort calls at the port layer (returns `ThermalCap`), thermal `>= red` triggers ImmunePort `SelfDegradationDetector`.
- **Alternatives considered:** extend ObservabilityPort (rejected — needs closed-loop actuation, not just metrics).

### 3.4 ADR-082 — `SandboxPort` (isolated code execution)

- **Contract:** `execute(spec: ExecutionSpec) -> ExecutionResult`, `create_slot() -> WorktreeSlot`, `destroy_slot(slot) -> None`, `is_healthy() -> bool`. `ExecutionSpec` carries approval-tier hint; SandboxPort refuses to execute above tier without an ApprovalGatewayPort receipt.
- **Reference adapter:** `adapters/sandbox/bwrap/` — vendored from `providers/sandbox_provider.py` (bash + file + directory + regex search), running inside git-worktree + bubblewrap boundary already documented in the Kosmos wiki page.
- **Tool registry:** the seven built-in Tektos tools (`bash`, `file_read`, `file_write`, `file_delete`, `directory_list`, `directory_create`, `search`) are re-served as an in-process MCP server that consumes SandboxPort — so external MCP tools and built-in tools share one MCPPort surface.
- **Alternatives considered:** treat sandbox as a plain MCP server (rejected — sandbox lifecycle + approval-tier binding is stateful across a session; MCP's request/response shape is a poor fit).

### 3.5 ADR-083 — `VoicePort` (STT/TTS)

- **Contract:** `state() -> VoiceState`, `transcribe(audio) -> Transcript`, `synthesize(text, *, voice="default") -> AudioClip`.
- **Reference adapter:** `adapters/voice/whisper_edgetts/` — `faster-whisper >= 1` + `edge-tts >= 6.1.9` + `pydub` (Tektos `voice` extra).
- **Frontend gate:** optional plugin capability; not required for MVP.

### 3.6 ADR-084 — `VisionPort` (image analysis)

- **Contract:** `analyze(image: ImageRef, *, prompt: str) -> VisionResult`, `analyze_url(url, *, prompt) -> VisionResult`, `is_healthy() -> bool`.
- **Reference adapter:** `adapters/vision/qwen3_vl/` — Qwen3-VL-4B at `:8094` (Hermes topology) or via LLMPort with vision model.
- **Alternatives considered:** extend LLMPort (rejected — image-in payload shape is different enough to deserve its own port and its own adapter fake).

## 4. Existing-port amendments (ADRs on existing subjects)

### 4.1 ADR-085 — MemoryPort extension: hybrid retrieval (Hindsight-shaped)

- Amends ADR-027. Adds `search_hybrid(query: str, *, k=5, alpha=0.7, rerank=True) -> list[MemoryHit]` combining pgvector semantic + BM25 keyword + cross-encoder rerank (ms-marco-MiniLM-L-6-v2). Backing implementation lives in `adapters/memory/dozerdb/hybrid.py` OR in a new `adapters/memory/hindsight_bridge/` that proxies to a running Hindsight service (see §5.3).
- Zero-trust write contract unchanged; reads unaffected.

### 4.2 ADR-086 — EventBusPort extension: session envelope taxonomy

- Amends ADR-023/061. Adds an envelope subtype registry (`assistant.delta`, `assistant.reasoning`, `assistant.completed`, `tool.started`, `tool.completed`, `tool.permission.required`, `session.state_change`, `session.ready`, `session.failed`, `system.message`, `loop_safety.warning`, `loop_safety.stop`, `immune.threat`, `immune.response`, `thermal.warning`, `thermal.cap`) so any transport can reason about the shapes without loading the plugin.
- Gateway proxy translates JSON-RPC 2.0 method names to envelope subtypes at the wire.

### 4.3 ADR-087 — LLMPort adapter: Hermes proxy topology

- Adds `adapters/llm/hermes_proxy/` that speaks the Hermes-style OpenAI-compatible endpoint at `:8093` with the topology-A / topology-B configurations from `.env.example`. Tektos-Ultima's `TEKTOS_LLM_FAILOVER_COOLDOWN_SECONDS=30` becomes an adapter option, not an env global.
- Existing Ollama and llama-swap adapters stay. Selection is per-request via LLMPort's model routing.

### 4.4 ADR-088 — LoopSafetyPort read-only tool budget interlock

- Formalises the Tektos read-only tool budget behaviour: budget flip resets the loop-safety monitor to avoid tripping repetition detection on natural re-reads (Tektos wiki known edge case).

### 4.5 ADR-089 — FrontendContractPort: iframe-mount panel type

- Amends ADR-031/045. Adds `PanelKind.IFRAME` with `iframe_src: str`, `sandbox: str = "allow-scripts allow-same-origin"`, `origin_check: bool = True`. Tektos plugin registers a single iframe panel targeting `/tektos/frontend` mounted by the kernel.

### 4.6 ADR-090 — `SelfModificationPort` (deferred, high-risk)

- Contract: `propose(change) -> Proposal`, `validate(proposal) -> ValidationResult`, `apply(proposal, receipt: ApprovalReceipt) -> ApplyResult`.
- Interlocks: ImmunePort `SelfModificationDetector`, `SelfDegradationDetector`, `InferenceEngineProtectionDetector` all run pre-apply; ApprovalGatewayPort tier ≥ **CRITICAL**; SandboxPort dry-run before real apply.
- Deferred to Stage 6; not required for MVP.

## 5. Overlap resolution decisions (Kosmos-side vs Tektos-side)

Every duplicate identified in the audit gets a single owning implementation. `SUPERSEDES` markers land in PORTING_LEDGER; deprecated Tektos modules are deleted, not left in tree.

| Concern | Owner in kosmos-lms | Superseded / merged | Notes |
|---|---|---|---|
| Agent shape | `plugins/tektos/agent.py` (Kosmos-scaffold, extended per ADR-036 amendment) | Tektos `agents/coding_agent/executor.py`, `runtime/sdk.py` | Multi-iteration loop, tool-loop, reflection engine lift into `TektosAgent` methods |
| Coding executor | Kosmos ADR-036 pattern-vendored OpenHands shape, extended | Tektos `agents/coding_agent/` | Tektos's coding_agent details fold in as helper methods |
| Planner | New `plugins/tektos/planner/` (from Tektos `agents/planner/`) | — | New capability; no Kosmos equivalent |
| Repomap | Kosmos `plugins/tektos/repomap/` (aider pattern, 984 LOC, ADR-038) | Tektos `runtime/{repo_map,repo_map_generator,repo_memory}.py`, `repograph/core.py` | File-level diff needed to pull any Tektos-specific ranker logic |
| Eval | Kosmos `plugins/tektos/eval/` (Pier, ADR-042) | Tektos `runtime/{evaluation_framework,external_evaluator}.py` | Approval-tier weighting from Tektos merges into Pier task config |
| OpenSpec / task decomposer | Kosmos `plugins/tektos/openspec/` | Tektos `runtime/task_decomposer.py` | Merge as OpenSpec change-proposal parser input |
| MCP integration | Kosmos MCPPort + `adapters/mcp/{in_process,stdio}` | Tektos `runtime/mcp_integration.py`, `mcp_server.py` | Tektos in-process built-in tools become new in-process MCP server under SandboxPort |
| RAG | Kosmos Zetesis (`plugins/zetesis/`) | Tektos `runtime/{rag_engine,rag_retriever}.py` | Any Tektos-specific retrieval strategies fold into Zetesis extension |
| Approvals | Kosmos ApprovalGatewayPort + Praxis | Tektos `runtime/approval_registry.py` | Deleted; Tektos code consumes ApprovalGatewayPort |
| Event bus | Kosmos EventBusPort (envelope-first, Valkey) | Tektos `event_bus.py`, `gateway_adapter.py` | Tektos in-process pub/sub deleted; envelopes rewritten to Kosmos shape |
| WS surface | Kosmos `/api/events/ws` (ADR-061) | Tektos `runtime/ws_manager.py` | Deleted; gateway_proxy retained as external translator |
| Session FSM | Move Tektos `state_machine.py` into `plugins/tektos/runtime/state_machine.py` | — | FSM stays intra-plugin (ADR-007), emits `session.state_change` envelopes |
| Memory backend | Kosmos MemoryPort + `adapters/memory/dozerdb/` | Tektos `memory/neo4j_memory.py` (direct DozerDB client) | Deleted; Tektos code reads/writes through MemoryPort |
| Memory backends (Postgres/Redis/file) | Wrapped as adapters if kept | Tektos direct clients | Postgres kept behind MemoryPort hybrid adapter (§4.1); Redis kept only as EventBusPort transport backing; file-based memory deleted (redundant with DataPort) |
| Hindsight | See §5.3 decision below | | Two-path fork; parent must pick one at Stage 3 kickoff |
| Search | Kosmos SearchPort + SearXNG adapter | Tektos `providers/searxng_provider.py` | Tektos DuckDuckGo/Tavily/Farfalle plugins become new SearchPort adapters |
| Sandbox tools | New SandboxPort + `adapters/sandbox/bwrap/` | Tektos `providers/sandbox_provider.py`, `tools/registry.py` | Registry becomes an in-process MCP server surface |
| Immune / loop-safety / thermal | New ports (§3) | Tektos originals moved verbatim into the adapter directories | See §3 |
| Observability | Kosmos ObservabilityPort + otel_stack | Tektos `runtime/observability.py`, `telemetry/collector.py` | Deleted; Tektos telemetry endpoints become panels over ObservabilityPort |
| Frontend | Kosmos `ui/` (outer shell) + `plugins/tektos/frontend/` (Tektos, iframed) | Tektos `frontend-legacy/` | Legacy dropped; two apps coexist under one origin via kernel mount |
| HTMX dashboard | Kosmos `plugins/tektos/ui/` (ADR-045) retained | — | Present alongside iframe; user can pick per session |

### 5.1 Memory-model reconciliation

Tektos's 4-tier brain metaphor (sensory / working / long-term / procedural) becomes **query-time views**, not storage tiers:

- **Sensory (100 ms–4 s):** EventBusPort ring buffer bounded by `EVENT_BUS_RING_MAX_AGE_SECONDS`. Not persisted.
- **Working (seconds–minutes):** in-process `SessionContext` object inside `plugins/tektos/runtime/session.py`. Never touches MemoryPort.
- **Long-term (days–permanent):** MemoryPort writes with `provenance` from the Tektos taxonomy, `confidence` from source-derived heuristics (see §5.2).
- **Procedural (permanent):** MemoryPort writes with `provenance="tektos_procedural"` for skills + ADR-registry mirror.

This preserves the mental model while collapsing to one storage plane, which is the only shape the zero-trust write contract permits.

### 5.2 Provenance + confidence taxonomy (mandatory)

Every Tektos-derived write path gets a fixed `provenance` tag and a `confidence` derivation:

| Provenance | Written by | Confidence derivation |
|---|---|---|
| `tektos_agent` | TektosAgent per-iteration observation | 0.75 default, LLM self-report if available, capped by approval tier |
| `tektos_reflection` | reflection_engine | 0.60 (post-hoc synthesis) |
| `tektos_synthesis` | synthesis_engine | 0.55 |
| `tektos_planner` | planner emitted plans | 0.80 (deterministic template) or 0.65 (LLM-derived) |
| `tektos_skill` | skills registry | 0.90 (curated) / 0.70 (auto-generated + dedup-checked) |
| `tektos_dreamtime` | dreamtime off-hours reflection | 0.50 |
| `tektos_hindsight` | Hindsight retain | 0.65 default; overridable per call |
| `tektos_experience` | experience_replay | 0.60 |
| `tektos_schema_evolution` | schema evolution proposals | 0.40 (proposal) / 0.85 (post-approval-applied) |
| `tektos_self_repair` | self_repair engine | 0.70 |
| `immune_system` | ImmunePort threat + response records | severity-derived: LOW 0.60, MEDIUM 0.75, HIGH 0.90, CRITICAL 0.99 |
| `loop_safety` | LoopSafetyPort stop records | 0.95 (deterministic) |
| `thermal` | ThermalPort samples + regulator decisions | 0.98 (deterministic hardware read) |

Anything without a taxonomy entry is a stop condition until one is authored.

### 5.3 Hindsight decision (parent decides at Stage 3 kickoff)

Two options remain viable; both are ADR-worthy and both are compatible with the rest of the plan:

**Option H1 — Hindsight-as-service, adapted behind MemoryPort.** Keep the standalone `hindsight-api` service on `:9000` and its dedicated `llama-server` on `:8095` (IBM Granite 4.0 H Tiny Q4_K_M) under systemd. Add `adapters/memory/hindsight_bridge/` that translates MemoryPort `write_event`/`search_hybrid` calls into Hindsight's `POST /banks/{id}/{retain,recall}`. Injects `provenance` + `confidence` at the adapter, then reflects retrieved memories back with derived confidence scores. Retains BGE-small + BM25 + MS-MARCO-MiniLM rerank stack. Ships as its own systemd units under `kosmos-lms.target`.

**Option H2 — Hindsight retired, capability moves into DozerDB adapter.** Delete the Hindsight service. Land ADR-085's `search_hybrid` inside `adapters/memory/dozerdb/hybrid.py`, adding pgvector + BM25 + rerank against DozerDB. Removes two systemd units, one dependency on `hindsight-api` + `granite-4.0-h-tiny`, and eliminates the `:9177` vs `:9000` port confusion. Costs the specific behaviour of Granite 4.0 H Tiny for entity extraction on `retain` (which would fold into an LLMPort-based extraction step gated by cost).

Default recommendation: **H1 for Stage 3–5, migrate to H2 in Stage 8 with an ADR amendment.** H1 preserves the currently working shape; H2 is the long-term cleaner boundary. Both use ADR-085's `search_hybrid` contract, so downstream code doesn't change.

### 5.4 Port-collision resolution

The `docs/ports.md` in kosmos-lms is the **merged** port registry (Kosmos ports + Tektos ports). Non-negotiable rules:

- `HindsightConfig.base_url` default flipped to `http://127.0.0.1:9000` (Tektos systemd). `:9177` is documented explicitly as "Hermes sibling install — do not use in kosmos-lms".
- Tektos `main.py` port `:8020` is retired. The kernel binds `:8020` under `kosmos-lms-kernel.service` and serves both existing Kosmos routes and (under `/tektos/api/*`) the retained Tektos endpoints.
- Gateway proxy `:8765` unchanged; it now proxies to the kernel, not to Tektos main.
- Kosmos UI stays on `:3000` (default) or `:3001` per Kosmos dev conventions.
- Tektos frontend stays on `:5556` in dev; in prod it's served from the kernel under `/tektos/frontend` so no separate bind.
- Data services: Postgres 5432, Neo4j 7474/7687, Redis 6379, SearXNG 8888 — all shared, no conflict.
- Model endpoints: LLMPort adapters expose selection between Hermes topology (`:8090/8091/8093/8094`), Tektos direct topology (`:8090/8092`), and Ollama (`:11434`). Only one topology binds the GPU at a time; a `topology` env variable picks it at boot.

## 6. Stage-by-stage rollout

Nine stages. Each stage is one PR-worthy scope with a Definition of Done that must pass before advancing. Every step lists its ADR/PORTING_LEDGER/BUILD_LOG outputs. Stage timing assumes one working session per numbered step.

### Stage 0 — Repository genesis

**Purpose:** create the public repo and land the initial commit with legal + discipline scaffolding. No code moves.

**Step 0.1 — Fork Kosmos into kosmos-lms.**

- Action: use `gh repo create rmholston420/kosmos-lms --public` then clone kosmos as a bare mirror, push to new remote. This preserves Kosmos commit history (which contains the ratified ADRs), letting kosmos-lms diverge cleanly.
- Alternative considered: empty repo. Rejected because losing the 78 ADR history would force manual reconciliation.
- Output: `rmholston420/kosmos-lms` on GitHub, `main` = current `kosmos/main`.
- BUILD_LOG.

**Step 0.2 — Add LICENSE (MIT) + author line.**

- Action: write `LICENSE` (SPDX MIT, copyright 2026 rmholston420 / Lama Lawapa Naljor). Update `README.md` first paragraph to say MIT.
- Output: `LICENSE`, `README.md` edit.
- BUILD_LOG.

**Step 0.3 — Add ADR-077 (integration cut).**

- Content: this decision. States kosmos-lms = kosmos + tektos-ultima merge; supersedes ADR-041 (Tektos plugin bootstrap) `Stage 3.7` scope; states the new-port intent (ADR-079…ADR-084); flags the H1/H2 Hindsight decision as OPEN.
- Update `docs/adrs/README.md` to add ADR-077.
- Output: `docs/adrs/ADR-077-kosmos-lms-integration-cut.md`, index row.
- BUILD_LOG.

**Step 0.4 — Add ADR-078 (spec v26 cut).**

- Content: forks `Kosmos-Build-Spec-v25.md` to `Kosmos-Build-Spec-v26.md`; adds §22 "Tektos absorption" summarising this plan; §17 ADR summary table extended through ADR-076 preserved, ADR-077+ appended.
- Move v25 to `archive/Kosmos-Build-Spec-v25.md` (never referenced from live code).
- Output: new v26 spec, archive, ADR-078.
- BUILD_LOG.

**Step 0.5 — Import Tektos-Ultima CI baseline.**

- Copy `.github/workflows/ci.yml` from tektos-ultima (six jobs) into kosmos-lms. Extend with `contract-tests.yml` for port contract tests + AST plugin-isolation test.
- Adjust paths: `python-lint` runs on `src/` + `plugins/` + `kernel/` + `adapters/` + `ports/`. `frontend-build` and `frontend-lint` run in `ui/` first; a matrix job later adds `plugins/tektos/frontend/`.
- Output: `.github/workflows/*.yml`.
- BUILD_LOG.

**Step 0.6 — Log discipline bootstrap.**

- Write `BUILD_LOG.md` (append-only header + entries 0.1–0.5), `DEBUG_LOG.md` (empty header), `KNOWN_ISSUES.md` (empty header), `SESSION_HANDOFF.md` (Stage 0 complete).
- Output: four log files.
- No new BUILD_LOG entry (this step is what creates it).

**Step 0.7 — PORTING_LEDGER seed.**

- Copy Kosmos's `PORTING_LEDGER.md` verbatim (it already tracks the Kosmos-scaffold Tektos ports).
- Append new section header `## Tektos-Ultima absorption (started YYYY-MM-DD HH:MM EDT)` with a `PLANNED` entry for each module family to be ported in Stages 3–7 (immune, loop_safety, thermal, sandbox, runtime, planner, agents, self_improvement, self_repair, memory-hindsight_bridge, gateway_proxy, tools/registry, skills, schema_evolution). Each entry cites source URL `https://github.com/rmholston420/tektos-ultima/blob/<HEAD-sha>/<path>`, SPDX `MIT (relicensed at port-in by sole author)`, target port(s), and ADR reference (`ADR-###` once authored).
- Output: extended `PORTING_LEDGER.md`.
- BUILD_LOG.

**Stage 0 DoD:** repo public, MIT, ADR-077 and ADR-078 ratified, six-job CI passing on the untouched Kosmos code, four logs present, PORTING_LEDGER seeded with PLANNED entries for every upcoming port.

---

### Stage 1 — Port skeletons and ADR authoring

**Purpose:** land the six new port contracts and their fake adapters. No vendored logic yet. Contract tests pass against fakes only. This is the port-first substrate that Stage 3–6 code lands into.

**Step 1.1 — Author ADR-079 `ImmunePort`.** Full body per §3.1. Update `docs/adrs/README.md`. BUILD_LOG.

**Step 1.2 — Write `ports/immune.py`** (Protocol + value objects `Threat`, `ThreatSeverity`, `ThreatCategory`, `ResponseRecord`, `HealthScore`, `ImmuneContext`). Add `adapters/immune/fake/` implementing the port with no-op detectors + a contract test at `adapters/immune/fake/test_contract.py`. Fake registers as a Kosmos ObservabilityPort emitter for `immune.threat` envelopes.

**Step 1.3 — Wire ImmunePort into kernel boot** as the FIRST subsystem (before notification). Boot-order change is a spec §21 edit; requires ADR-079 to be Ratified. Update `Kosmos-Build-Sequence-v26.md` §21.

**Step 1.4 — Author ADR-080 `LoopSafetyPort`**, `ports/loop_safety.py`, `adapters/loop_safety/fake/`, contract test.

**Step 1.5 — Author ADR-081 `ThermalPort`**, `ports/thermal.py`, `adapters/thermal/fake/`, contract test. Fake returns a fixed 45 °C sample.

**Step 1.6 — Author ADR-082 `SandboxPort`**, `ports/sandbox.py`, `adapters/sandbox/fake/` (in-memory noop), contract test.

**Step 1.7 — Author ADR-083 `VoicePort`**, `ports/voice.py`, `adapters/voice/fake/`, contract test.

**Step 1.8 — Author ADR-084 `VisionPort`**, `ports/vision.py`, `adapters/vision/fake/`, contract test.

**Step 1.9 — Author ADR-085 (MemoryPort hybrid retrieval)** amending ADR-027. Add `MemoryPort.search_hybrid(...)` protocol method; keep write contract unchanged. `adapters/memory/dozerdb/` gets a placeholder `search_hybrid` returning `NotImplementedError`; `adapters/memory/fake/` implements a trivial in-memory hybrid.

**Step 1.10 — Author ADR-086 (envelope taxonomy)** amending ADR-023/061. Add `ports/event_envelope.py` `EnvelopeKind` enum with the taxonomy from §4.2. Update EventBusPort contract tests to accept the taxonomy.

**Step 1.11 — Author ADR-087 (Hermes LLM adapter)**, ADR-088 (loop-safety read-only budget interlock), ADR-089 (iframe panel kind).

**Stage 1 DoD:** six new ADRs ratified, six new port files present, six fake adapters passing their own contract tests, kernel boot order updated in spec v26 §21, all pre-existing Kosmos tests still passing (1264 py, 10 Playwright).

---

### Stage 2 — Tektos-Ultima quarantine + tree-import

**Purpose:** get Tektos-Ultima's source into kosmos-lms as a **quarantined** directory that isn't yet on the Python path or CI-linted. Every subsequent step ports one subsystem out of quarantine into its port-behind location.

**Step 2.1 — Quarantine import.** `git subtree add --prefix=vendor/tektos_ultima https://github.com/rmholston420/tektos-ultima.git main --squash`. This preserves upstream reference without polluting live code paths. `vendor/tektos_ultima/` is excluded from ruff/mypy/pytest via `pyproject.toml` overrides.

**Step 2.2 — README + inventory.** Write `vendor/tektos_ultima/PORTED.md` — a checklist of every module family, updated as each is ported out (Stages 3–7). PORTING_LEDGER entries reference this checklist row.

**Step 2.3 — CI extension.** Add `frontend-tektos-build` and `frontend-tektos-lint` matrix jobs that build `plugins/tektos/frontend/` once it exists (skipped until Stage 8).

**Stage 2 DoD:** vendor tree present, PORTED.md checklist authored, CI matrix extended, live code still clean.

---

### Stage 3 — Immune, loop-safety, thermal (defense subsystems first)

**Purpose:** land the three defense subsystems as real adapters before any coding-agent work. They are prerequisites for the sandboxed executor and for any self-modification work.

**Step 3.1 — Port ImmunePort real adapter.**

- Move `vendor/tektos_ultima/src/tektos/runtime/immune_system.py` → `plugins/tektos/immune/detectors.py` + `plugins/tektos/immune/adapter.py`.
- `adapters/immune/tektos_defense/` re-exports the plugin-side implementation as the port-registered adapter. (Adapter-in-plugin is an accepted Kosmos pattern where the port is plugin-native but exposed system-wide — see ADR-079 rationale.)
- Extract the 12 detector classes verbatim. Remove all `main.py`-import coupling; substitute EventBusPort subscriptions for the `respond_to_threats` fanout.
- Write MemoryPort provenance/confidence injection at the adapter boundary (Threat → MemoryPort event with `provenance="immune_system"` + severity-derived confidence).
- Contract test: `adapters/immune/tektos_defense/test_contract.py` — inject a prompt-injection sample, assert `PromptInjectionDetector` fires; inject a bash `rm -rf ~/.config` sample, assert `DangerousCommandDetector` fires; assert every fire emits an `immune.threat` envelope.
- PORTING_LEDGER: `Tektos ImmunePort adapter — VENDORED` with source URL, upstream SHA, SPDX MIT (author relicensed at port-in), path `plugins/tektos/immune/detectors.py`, port `ImmunePort`, modifications "removed main.py imports; substituted EventBusPort for fanout; added MemoryPort provenance/confidence at adapter boundary".
- BUILD_LOG.

**Step 3.2 — Port LoopSafetyPort real adapter.**

- Move `vendor/.../runtime/loop_safety.py` + `loop_guard.py` → `plugins/tektos/loop_safety/`.
- `adapters/loop_safety/tektos_3tier/` binds. Configuration constants become adapter-init parameters; env overrides (`TEKTOS_READONLY_TOOL_ROUNDS`) preserved.
- Contract test: 15-turn cap fires; `max_tokens_total=65536` fires; repetition on window=3 threshold=2 fires; wall-time 300 s fires; read-only budget reset flips monitor state per ADR-088.
- PORTING_LEDGER. BUILD_LOG.

**Step 3.3 — Port ThermalPort real adapter.**

- Move `vendor/.../thermal/{regulator,monitor,metrics,power_optimizer,config}.py` → `plugins/tektos/thermal/`.
- `adapters/thermal/tektos_pid/` binds. Preserve PID constants and thresholds; expose `set_thresholds` for overrides. Lazy NVML import stays.
- Kernel interlock: LLMPort adapters check `ThermalPort.regulate()` before each call; `ThermalDecision.blocked` → return `ThermalCap` error envelope. `red ≥ 88 °C` triggers ImmunePort `SelfDegradationDetector`.
- Contract test: mock NVML sample sequence (increasing temps) drives PID; assert `blocked` at cap, assert `SelfDegradationDetector` fire at red.
- PORTING_LEDGER. BUILD_LOG.

**Step 3.4 — Stage 3 exit gate.**

- Run full pytest + Playwright. Kernel starts. ImmunePort registers detectors. LoopSafetyPort available. ThermalPort binds NVML (or mock in CI). All contract tests pass. All Kosmos scaffolds still pass their tests (`test_stage_2_4_exit_gate.py`, `test_stage_3_12_exit_gate.py`).

**Stage 3 DoD:** three defense subsystems real, adapters wired, kernel boots them at defined order, contract + integration tests green, Kosmos Stage 3 exit-gate tests still green.

---

### Stage 4 — Sandbox + tool registry + MCP consolidation

**Step 4.1 — Port SandboxPort real adapter.**

- Move `vendor/.../providers/sandbox_provider.py` → `plugins/tektos/sandbox/bwrap_provider.py` + adapter facade.
- Approval-tier binding: `ExecutionSpec` carries tier hint; adapter refuses execution above `MODERATE` without an `ApprovalReceipt` obtained through ApprovalGatewayPort. Interlocks with ImmunePort's `DangerousCommandDetector`.
- Uses git-worktree + bubblewrap boundary already documented in the Kosmos wiki (writable overlay for `.git/worktrees/<slot>/` so `git apply --index` can create `index.lock`).
- PORTING_LEDGER, BUILD_LOG, contract test.

**Step 4.2 — Serve Tektos built-in tools as in-process MCP.**

- Move `vendor/.../tools/registry.py` → `plugins/tektos/mcp/builtin_server.py`. Convert the 7 built-in tools into MCP tool definitions; each handler calls SandboxPort under the hood.
- Register the built-in server through the existing `adapters/mcp/in_process/` factory. Consumers see one MCPPort catalogue for both built-in and external MCP tools.
- ADR-036 amendment (not new): the TektosAgent's tool-loop now discovers tools exclusively through MCPPort.
- PORTING_LEDGER, BUILD_LOG, contract test verifying `bash`, `file_read/write/delete`, `directory_list/create`, `search` all round-trip through MCP.

**Step 4.3 — Deprecate Tektos direct tool paths.**

- Delete `vendor/.../runtime/tool_router.py`-derived imports from any newly ported module; substitute MCPPort routing.
- Update `PORTING_LEDGER.md`: mark tool_router.py `SUPERSEDED by MCPPort`.

**Stage 4 DoD:** SandboxPort real, 7 built-ins live via MCP, external MCP still works (existing Kosmos MCP contract tests green), TektosAgent's tool loop consumes MCPPort exclusively.

---

### Stage 5 — Tektos runtime + agent + planner core

**Step 5.1 — Port `runtime/session.py`, `state_machine.py`, `session_state.py`.**

- Target: `plugins/tektos/runtime/{session,state_machine,session_state}.py`.
- Substitutions: `event_bus` → EventBusPort. `approval_registry` → ApprovalGatewayPort. `ws_manager` → deleted (use kernel `/api/events/ws`). SDK direct model calls → LLMPort.
- Envelopes rewritten to Kosmos envelope-first shape (ADR-023). Session FSM emits `session.state_change` per ADR-086.
- PORTING_LEDGER, BUILD_LOG, tests.

**Step 5.2 — Extend `plugins/tektos/agent.py` with multi-iteration + tool loop + read-only budget.**

- Amend ADR-036 with a `> STATUS AMENDMENT: multi-iteration + tool-loop + read-only budget` block. Existing one-iteration surface preserved for backwards-compatibility with `POST /api/tektos/turn` (ADR-063).
- New method `TektosAgent.run_until_complete(session_id, prompt, *, max_iterations=15)` uses LoopSafetyPort as its stopping oracle. Every observation writes to MemoryPort with `provenance="tektos_agent"` + confidence 0.75 (or LLM-self-report if available).
- Tests: existing Stage 3.1 tests still pass; new multi-iteration tests assert LoopSafetyPort cap fires; read-only budget test asserts budget exhaustion + monitor reset.

**Step 5.3 — Port `runtime/reflection_engine.py`, `synthesis_engine.py`, `experience_replay.py`, `dreamtime` handlers.**

- Target: `plugins/tektos/runtime/{reflection,synthesis,experience}.py`. Dreamtime scheduling handled by a plugin-internal scheduler; not a kernel service.
- All writes get provenance from the taxonomy (§5.2).
- PORTING_LEDGER, BUILD_LOG, tests.

**Step 5.4 — Port `agents/planner/*` and `runtime/planner_orchestrator.py`.**

- Target: `plugins/tektos/planner/`. Planner emits `plan.proposed` envelopes; kernel forwards to Praxis for tier-2 approval when required.
- Merge Kosmos `plugins/tektos/openspec/` and Tektos `runtime/task_decomposer.py`: OpenSpec parses the decomposed change proposal; planner emits it.
- PORTING_LEDGER, BUILD_LOG, tests.

**Step 5.5 — Port `agents/coding_agent/executor.py` details.**

- Target: helper methods on `TektosAgent`. Coding-specific tool sequences (patch/build/test/commit) become MCP tool orchestrations.
- Verify existing Kosmos coding-agent test suite still passes.

**Step 5.6 — Port `agents/manager/*` (guardrails, metrics, archetype).**

- Split: guardrail logic → ImmunePort detectors (extension). Metrics → ObservabilityPort. Archetype tracker → plugin-internal (`plugins/tektos/runtime/archetype.py`).

**Step 5.7 — Port `runtime/multi_agent_orchestrator.py`, `hierarchical_agent.py`, `long_running_agent.py`.**

- Target: `plugins/tektos/agents/` sub-package. All cross-agent coupling stays intra-plugin (ADR-007 compliant).

**Stage 5 DoD:** TektosAgent multi-iteration loop works end-to-end against LLMPort + MemoryPort + MCPPort + LoopSafetyPort + ImmunePort + ThermalPort; reflection/synthesis/experience replay writing back through MemoryPort with correct provenance; planner emits plans; contract + integration tests green.

---

### Stage 6 — Memory adapter, Hindsight decision, self-repair, self-improvement

**Step 6.1 — Land ADR for Hindsight decision (H1 default).**

- Author ADR-091 formalising the choice between H1 (Hindsight bridge adapter) and H2 (retire Hindsight). H1 recommended for MVP; ADR-091 records the migration path to H2 in a later cut.
- **Parent decision required at Stage 6 kickoff.** If parent selects H2, ADR-091 records that instead and Steps 6.2–6.3 change accordingly.

**Step 6.2 — Port Hindsight client + bridge (H1 path).**

- Move `vendor/.../memory/hindsight_client.py` → `plugins/tektos/memory/hindsight_client.py`. **Default `base_url = "http://127.0.0.1:9000"`** (Tektos systemd) — port-collision fix from audit finding.
- New adapter `adapters/memory/hindsight_bridge/` implements `MemoryPort.search_hybrid` and adds provenance/confidence injection on writes.
- Systemd units `kosmos-lms-hindsight.service` and `kosmos-lms-llm-hindsight.service` land in Stage 8.
- PORTING_LEDGER: Hindsight client (VENDORED), Hindsight bridge adapter (WIRED). BUILD_LOG.

**Step 6.3 — Port `memory/{neo4j,postgres,redis,file_based,persistence,backup_scheduler}.py`.**

- Deletion policy: `neo4j_memory.py`, `file_based_memory.py` deleted (superseded by DozerDB adapter and DataPort respectively). `postgres_memory.py` → adapter contribution to `hindsight_bridge` (persistence layer). `redis_memory.py` → adapter contribution to EventBusPort valkey backing if not already covered. `persistence.py`, `backup_scheduler.py` → into DozerDB adapter's backup path.
- PORTING_LEDGER `SUPERSEDED` entries where applicable.

**Step 6.4 — Port `self_repair/*` and `runtime/self_repair` handlers.**

- Target: `plugins/tektos/self_repair/`. Each repair strategy proposes through ApprovalGatewayPort; execution goes through SandboxPort. Writes provenance `"tektos_self_repair"`.
- PORTING_LEDGER, BUILD_LOG, tests.

**Step 6.5 — Port `self_improvement/*` and `runtime/self_improvement/*`.**

- Target: `plugins/tektos/self_improvement/`. Metrics/experiences/report/enqueue/status endpoints become part of the Tektos plugin surface (mounted under `/tektos/api/self_improvement/*` per ADR-063 extension).

**Step 6.6 — Port `skills/*`.**

- Target: `plugins/tektos/skills/`. Skills DB writes go through MemoryPort with `provenance="tektos_skill"`. Dedup + improve + execute + select endpoints re-mount under `/tektos/api/skills/*`.
- Pier eval integration: skill improvements can be Pier-scored.

**Step 6.7 — Author ADR-090 `SelfModificationPort` and defer implementation.**

- ADR-090 lands per §3.6 but marked `Status: Proposed, deferred to Stage 9+`. No adapter yet. Immune-system + approval interlocks documented as prerequisites.
- Import `self_modification/*` from Tektos remains in `vendor/` only; it does not enter live code until ADR-090 flips to Ratified.

**Stage 6 DoD:** MemoryPort supports hybrid retrieval; Hindsight bridge (or DozerDB hybrid, per H1/H2) works end-to-end; self-repair proposes through approvals + executes through sandbox; self-improvement subsystem functional; skills DB backed by MemoryPort; SelfModificationPort ADR authored but not implemented.

---

### Stage 7 — Endpoint split: retire `main.py`, mount `/tektos/api/*`

**Purpose:** dissolve Tektos's 5800-line 154-endpoint `main.py` monolith. Every endpoint lands under `/tektos/api/*` on the Kosmos kernel, owned by a specific plugin subsystem behind a port. Steps 7.1–7.5 are grouped by endpoint family; each is one BUILD_LOG entry.

**Step 7.1 — Runtime, health, logs, directory** endpoints (4) → kernel + plugin. Health under `/tektos/api/health`; logs via ObservabilityPort. `directory_list` served through SandboxPort read-only.

**Step 7.2 — Memory, hindsight, dreamtime, experience, replay** (13) → `/tektos/api/memory/*`, `/tektos/api/hindsight/*`, `/tektos/api/dreamtime/*`. All read paths go through MemoryPort (`search_hybrid` for hindsight recall), all write paths inject provenance/confidence.

**Step 7.3 — Tools, MCP, sandbox, skills** (~24) → `/tektos/api/tools/*`, `/tektos/api/mcp/*`, `/tektos/api/skills/*`. Tools discovered via MCPPort catalogue.

**Step 7.4 — Immune, self-repair, self-improvement, self-modification (probes only), thermal, telemetry, planner, schema-evolution, context (curator/compactor/monitor)** (~40) → `/tektos/api/{immune,self_repair,self_improvement,thermal,planner,schema,context}/*`. Each family fronts a specific port or plugin subsystem. Schema-evolution `/propose` and `/apply` require ApprovalGatewayPort tier CRITICAL until ADR-090 implementation lands.

**Step 7.5 — Sessions, models, LLM probe, routing, config, keys, DB manager** (~48) → `/tektos/api/{sessions,models,llm,routing,config,keys,db}/*`. `db_manager.py` (arbitrary CRUD) is high-risk; it lands with ApprovalGatewayPort tier CRITICAL required for any write, and gated behind ImmunePort's SecretExposureDetector on responses.

**Step 7.6 — Vision, voice, MCP-server, plugins, telegram, email** (~15) → `/tektos/api/{vision,voice,mcp_server,plugins}/*`. Requires VoicePort + VisionPort adapters (ADR-083/084). Telegram/email gateways ship as optional plugin sub-capabilities; disabled unless env vars set.

**Step 7.7 — WebSockets: `/ws/{session_id}`, `/ws/pty`.**

- `/ws/{session_id}` → replaced by kernel `/api/events/ws` (ADR-061) with a `session_filter=<id>` query param.
- `/ws/pty` → new adapter under SandboxPort that streams a PTY channel; behind approval tier MODERATE.

**Step 7.8 — Delete `vendor/tektos_ultima/src/tektos/main.py`** once every endpoint above lands. PORTING_LEDGER: `main.py SUPERSEDED by kernel /tektos/api/* mounts`.

**Stage 7 DoD:** every one of the ~154 endpoints re-served under the kernel; `main.py` deleted from vendor; contract tests for each `/tektos/api/*` family green; end-to-end smoke test drives an agent turn through the new WS bridge.

---

### Stage 8 — Frontend microfrontend + deployment surface

**Step 8.1 — Move Tektos frontend into plugin.**

- `git mv vendor/tektos_ultima/frontend → plugins/tektos/frontend`. Drop `vendor/tektos_ultima/frontend-legacy/`.
- Update `plugins/tektos/frontend/package.json` scripts to build into `plugins/tektos/frontend/.next` with `basePath: "/tektos/frontend"` set in `next.config.js`.

**Step 8.2 — Kernel mount for Tektos frontend.**

- New sub-app mount `/tektos/frontend` on kernel serving the built Next.js static output + serverless routes. Reverse-proxy shape follows ADR-045 HTMX sub-app pattern.
- Ensures same-origin so the iframe (Step 8.3) can share cookies for approvals without CSRF gymnastics.

**Step 8.3 — Kosmos UI iframe panel.**

- New page `ui/app/tektos/page.tsx` renders `<iframe src="/tektos/frontend" sandbox="allow-scripts allow-same-origin">` under the Kosmos shell.
- Register iframe panel through FrontendContractPort per ADR-089 (`PanelKind.IFRAME`, priority 80).
- `ui/app/tektos/page.tsx` also exposes a header row with "Open in new tab" and a "Legacy HTMX dashboard" link to `/tektos-ui` (Kosmos-scaffold, ADR-065) so the two Tektos UIs coexist.

**Step 8.4 — Systemd unit set.**

- Move `deploy/systemd/user/tektos-*.service` → `ops/systemd/user/kosmos-lms-*.service`. Rename units:
  - `kosmos-lms-kernel.service` (replaces `tektos-backend.service`, uvicorn on `:8020`, kernel app entry point).
  - `kosmos-lms-gateway.service` (was `tektos-gateway.service`; unchanged proxying to `:8020` from `:8765`).
  - `kosmos-lms-frontend.service` (Kosmos shell on `:3000` or `:3001` per Kosmos convention).
  - `kosmos-lms-tektos-frontend.service` (Tektos plugin frontend on `:5556` dev; retired in prod because the kernel serves it under `/tektos/frontend`).
  - `kosmos-lms-hindsight.service` + `kosmos-lms-llm-hindsight.service` (H1 path only).
  - `kosmos-lms.target` grouping all with `Wants=` semantics (not `Requires=`) so single-service failure does not cascade.
- Systemd `Linger=yes` guidance preserved from Tektos.
- PORTING_LEDGER + BUILD_LOG.

**Step 8.5 — Data-service bring-up.**

- Move `deploy/data-services/*` from Tektos. Idempotent one-shot host installers for Postgres 18 + pgvector 0.8.1, Neo4j 7474/7687, Redis 6379. Not part of `kosmos-lms.target`.

**Step 8.6 — Merged `docs/ports.md`.**

- Merge Tektos `docs/ports.md` into Kosmos `docs/ports.md`. Adds "no `0.0.0.0` without written reason" rule from Tektos. Flags `:9177` as forbidden.

**Step 8.7 — CI matrix enables `plugins/tektos/frontend`.**

- `frontend-tektos-build` and `frontend-tektos-lint` matrix jobs unskipped. Playwright chromium runs against both `ui/` and `plugins/tektos/frontend/`.

**Stage 8 DoD:** kosmos-lms deploys as a single `kosmos-lms.target`; kernel serves both Kosmos and Tektos UIs under one origin; iframe panel renders Tektos in Kosmos shell; both Playwright suites green; systemd unit set boots and survives reboot with `Linger=yes`.

---

### Stage 9 — Retirement, freeze, spec close-out

**Step 9.1 — Sunset markers on source repos.**

- Add `DEPRECATED.md` to both `rmholston420/tektos-ultima` and `rmholston420/kosmos` referencing `rmholston420/kosmos-lms` as the sole ongoing home.
- Optionally archive `tektos-ultima` on GitHub. Kosmos may remain active for the ratified ADRs' history reference until kosmos-lms's ADR history is publicly navigable.

**Step 9.2 — `vendor/tektos_ultima/` deletion.**

- Every module accounted for in `vendor/tektos_ultima/PORTED.md`; anything not ported gets an ADR explaining rejection. Then delete the vendor tree. Final PORTING_LEDGER entry closes the absorption section.

**Step 9.3 — Kosmos-Build-Sequence-v26 finalisation.**

- Update `Kosmos-Build-Sequence-v26.md` to reflect the completed Tektos absorption. Author ADR-092 as the Stage-9 exit gate.

**Step 9.4 — SelfModificationPort implementation (optional, gated).**

- Only if immune-system + approval interlocks fully proved out. Otherwise remains `Proposed, deferred`.

**Step 9.5 — SESSION_HANDOFF final.**

- Overwrite `SESSION_HANDOFF.md`: kosmos-lms is the sovereign local-first LMS; Tektos absorbed; next work sequence resumes from Kosmos Stage 1.7 or Stage 4 per user direction.

**Stage 9 DoD:** vendor tree deleted; both source repos deprecated; spec v26 sealed; kosmos-lms is the single ongoing home.

---

## 7. Contract tests to author (checklist)

Every port lock lands under `adapters/<port>/<component>/test_contract.py`. Minimum set:

- `adapters/immune/fake/test_contract.py`
- `adapters/immune/tektos_defense/test_contract.py` — 12 detector cases, MemoryPort provenance/confidence assertion, envelope emission
- `adapters/loop_safety/fake/test_contract.py`
- `adapters/loop_safety/tektos_3tier/test_contract.py` — five stop-reason cases, read-only budget interlock
- `adapters/thermal/fake/test_contract.py`
- `adapters/thermal/tektos_pid/test_contract.py` — PID sample sequence, LLMPort blocking at cap, immune trigger at red
- `adapters/sandbox/fake/test_contract.py`
- `adapters/sandbox/bwrap/test_contract.py` — seven tool cases + approval-tier refusal + git-worktree lifecycle
- `adapters/voice/fake/test_contract.py`
- `adapters/voice/whisper_edgetts/test_contract.py` (Stage 8; may skip in CI without models)
- `adapters/vision/fake/test_contract.py`
- `adapters/vision/qwen3_vl/test_contract.py` (Stage 8; may skip in CI)
- `adapters/memory/dozerdb/test_hybrid_contract.py` (ADR-085 extension) or `adapters/memory/hindsight_bridge/test_contract.py` (H1 path)
- `adapters/llm/hermes_proxy/test_contract.py` (ADR-087)
- `tests/isolation/test_ast_no_cross_plugin_imports.py` (ADR-007 enforcer) — extended to include `plugins/tektos/{immune,loop_safety,thermal,sandbox,runtime,planner,agents,self_improvement,self_repair,memory,skills}`

## 8. PORTING_LEDGER entries to seed (Stage 0.7)

Each `PLANNED` entry follows the template. Names below are stage-of-first-landing:

- Immune Port + Tektos-Defense adapter (Stage 3.1)
- Loop Safety Port + Tektos-3-Tier adapter (Stage 3.2)
- Thermal Port + Tektos-PID adapter (Stage 3.3)
- Sandbox Port + bwrap adapter (Stage 4.1)
- Tektos built-in tool MCP server (Stage 4.2)
- Tektos runtime session/state_machine/session_state (Stage 5.1)
- TektosAgent multi-iteration extension (Stage 5.2)
- Reflection/Synthesis/Experience replay (Stage 5.3)
- Planner subsystem (Stage 5.4)
- Coding-agent executor merge (Stage 5.5)
- Manager subsystem split (Stage 5.6)
- Multi-agent/hierarchical/long-running agents (Stage 5.7)
- MemoryPort hybrid retrieval (Stage 6.1)
- Hindsight client + bridge adapter (Stage 6.2)
- Memory legacy backend sweep (Stage 6.3)
- Self-repair (Stage 6.4)
- Self-improvement (Stage 6.5)
- Skills (Stage 6.6)
- SelfModificationPort (Stage 6.7 ADR only)
- Voice + Vision ports and adapters (Stages 7.6 + 8)
- Frontend microfrontend (Stage 8.1–8.3)
- Systemd unit set (Stage 8.4)
- Gateway proxy retention (Stage 5.1 or 7.7)
- `main.py` supersession (Stage 7.8)

## 9. Risks, open questions, kill-switches

### 9.1 Risks with mitigations

- **License scope creep.** If any Tektos-Ultima module was itself a derivative of a non-permissive upstream (e.g. GPL/AGPL), the "author relicenses at port-in" argument fails for that module. **Mitigation:** at Stage 2.1 quarantine, run a header scan on every `.py` file for `SPDX-License-Identifier:` and for headers referencing GPL/AGPL/BUSL/SSPL; every hit becomes a per-module ADR before port-in.
- **Kosmos scaffold drift during migration.** Kosmos active work (Stage 1.7+) could land while kosmos-lms is diverging. **Mitigation:** freeze `rmholston420/kosmos` on the Stage 0.1 fork commit; any new Kosmos work happens in kosmos-lms directly. Sunset ADR-093 on the source repo.
- **Provenance taxonomy gaps.** New Tektos subsystems may need new taxonomy entries mid-stage. **Mitigation:** taxonomy lives in `governance/provenance_taxonomy.yaml`; adding an entry requires an ADR amendment, not a new ADR.
- **Iframe origin/cookie issues.** If Tektos frontend needs its own auth surface, iframe-under-kernel may break approvals. **Mitigation:** Step 8.2 mounts under the same origin as the kernel API precisely so shared cookies work; if it fails, fall back to `PanelKind.IFRAME` with `sandbox="allow-scripts"` (no `allow-same-origin`) plus a postMessage bridge — ADR-089 covers both modes.
- **PID thermal actuation permission errors.** NVML power-limit writes typically need CAP_SYS_ADMIN or the `gpu-power-limit.service`. **Mitigation:** thermal adapter degrades gracefully to "monitor only" if `nvmlDeviceSetPowerManagementLimit` returns permission-denied; emits `thermal.actuation_denied` envelope; ImmunePort escalation ladder stays intact.
- **Test-suite mass.** 336 Tektos py tests + 1264 Kosmos py tests + 28+10 Playwright = ~1600 py tests + 38 E2E. **Mitigation:** Stage 5+ Tektos tests refactored to use port fakes as fixtures (already the Kosmos convention); GPU-dependent tests marked `pytest.mark.gpu` and gated in CI.

### 9.2 Open questions requiring parent decision at stage kickoff

- **Stage 3 kickoff:** H1 vs H2 Hindsight path (§5.3). Default recommendation: H1 for Stages 3–5, migrate to H2 in Stage 8.
- **Stage 5.6 kickoff:** does the Tektos manager's archetype-tracking become a Praxis-visible signal (cross-plugin coupling via EventBusPort) or stay Tektos-internal? Default recommendation: envelope-emit, no direct Praxis import.
- **Stage 6.7 kickoff:** does SelfModificationPort land in Stage 9 or does it defer beyond kosmos-lms MVP entirely? Default recommendation: defer beyond MVP; ADR-090 stays `Proposed`.
- **Stage 8.3 kickoff:** iframe `sandbox` attributes (`allow-same-origin` on or off). Default recommendation: on, because same-origin mount removes CSRF gymnastics and the Kosmos kernel is the trust boundary anyway.

### 9.3 Kill-switches (stop conditions per Kosmos discipline)

- Any adapter would import into plugin space without going through a port → **stop**.
- Any MemoryPort write path missing `provenance` or `confidence` → **stop**.
- Any plugin-to-plugin import → **stop** (AST test enforces).
- Colossus resource envelope (128 GB RAM / 32 GB VRAM) exceeded at steady state → **stop**.
- A DEBUG_LOG search hit exists for a symptom and the recorded fix has not been tried → **stop; try that fix first**.
- Any contract test fails → **stop**.

## 10. Sequence-of-execution appendix (BUILD_LOG order)

```
Stage 0: 0.1 → 0.2 → 0.3 → 0.4 → 0.5 → 0.6 → 0.7    (7 entries)
Stage 1: 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8 → 1.9 → 1.10 → 1.11   (11 entries)
Stage 2: 2.1 → 2.2 → 2.3    (3 entries)
Stage 3: 3.1 → 3.2 → 3.3 → 3.4    (4 entries)
Stage 4: 4.1 → 4.2 → 4.3    (3 entries)
Stage 5: 5.1 → 5.2 → 5.3 → 5.4 → 5.5 → 5.6 → 5.7    (7 entries)
Stage 6: 6.1 → 6.2 → 6.3 → 6.4 → 6.5 → 6.6 → 6.7    (7 entries)
Stage 7: 7.1 → 7.2 → 7.3 → 7.4 → 7.5 → 7.6 → 7.7 → 7.8    (8 entries)
Stage 8: 8.1 → 8.2 → 8.3 → 8.4 → 8.5 → 8.6 → 8.7    (7 entries)
Stage 9: 9.1 → 9.2 → 9.3 → 9.4 → 9.5    (5 entries)
```

Total ~62 BUILD_LOG steps, ~14 new ADRs (ADR-077 through ADR-092 minus a few merges), ~40 PORTING_LEDGER entries.

---

## Appendix A — Diff of contract from what's already ratified

Because Kosmos already ratified ADR-036/037/038/041/042/044/045/046/063/065 for the plugins/tektos/ scaffold, the amendments the new plan requires are limited and enumerable:

| Existing ADR | Amendment required | Where |
|---|---|---|
| ADR-023 (EventBusPort envelopes) | Envelope taxonomy enum | ADR-086 |
| ADR-027 (MemoryPort v0.2.2) | Add `search_hybrid` | ADR-085 |
| ADR-031 (FrontendContractPort schema) | Add `PanelKind.IFRAME` | ADR-089 |
| ADR-036 (Tektos agent shape) | Multi-iteration + tool loop | Amendment block on ADR-036 file |
| ADR-041 (Tektos plugin bootstrap) | Extend descriptor to include immune/loop_safety/thermal/sandbox ports as declared dependencies | Amendment block |
| ADR-045 (HTMX dashboard) | Kept as-is; iframe panel is additive | none |
| ADR-063 (Tektos kernel mount) | Extend to include the ~154 `/tektos/api/*` endpoints (grouped) | Amendment block |
| ADR-065 (Tektos UI kernel mount) | Kept as-is; kernel now mounts a second Tektos sub-app at `/tektos/frontend` | Amendment block |

Everything else is a fresh ADR (ADR-077 through ADR-092).

## Appendix B — Concrete kernel boot order after Stage 3

Kosmos current boot: notification, frontend_contract, resource, event_bus, approval, phrouros, zetesis.

Post-Stage-3 kosmos-lms boot: **immune, loop_safety, thermal, notification, frontend_contract, resource, event_bus, approval, sandbox, mcp, memory, llm, phrouros, praxis, zetesis, tektos**.

Rationale: defense ports first (fail-closed at kernel start); infrastructure ports next; plugins last. Any port that fails to bind at boot marks its kernel-facing status `SUSPENDED`, and dependent plugins register with degraded panels.

## Appendix C — File-count budget (rough)

- New port files: 6 (`ports/{immune,loop_safety,thermal,sandbox,voice,vision}.py`)
- New fake adapters: 6 dirs, ~2 files each = ~12 files
- New real adapters: 8 dirs (defense × 3, sandbox, hermes_proxy, hindsight_bridge, voice, vision), ~3–4 files each = ~30 files
- Tektos plugin new subsystems (immune/loop_safety/thermal/sandbox/runtime/planner/agents/self_improvement/self_repair/skills): ~100 files carried, ~40 new tests
- Tektos frontend: ~111 TS/TSX carried verbatim
- Systemd units: 7 new files
- ADRs: ~14 new files + ~6 amendment blocks
- PORTING_LEDGER entries: ~40
- BUILD_LOG entries: ~62

## Appendix D — What the audit found that must NOT be lost

1. SecretExposureDetector's 12 regex patterns (kept in `plugins/tektos/immune/detectors.py`)
2. Loop-safety exact constants (`max_turns=15`, `max_tokens_total=65536`, `max_wall_time_seconds=300.0`, `repetition_window=3`, `repetition_threshold=2`)
3. Thermal thresholds (yellow 51 °C, cap 80 °C, red 88 °C, 400 W GPU limit)
4. Read-only tool budget reset on budget-exhaustion (ADR-088 formalises)
5. Gateway proxy JSON-RPC 2.0 method → envelope translation (kept intact)
6. `HindsightConfig.base_url` **fixed** to `:9000` at port-in (audit-flagged bug)
7. `.env.example` topology A/B model routing (encoded as LLMPort adapter options)
8. Whisper + edge-tts model wiring (VoicePort adapter)
9. 40 Tektos status panels (all live behind the iframe)
10. VSM subscription defaults (S1/S2/S3/S4/S5 topic patterns) preserved as EventBusPort subscription seed
11. Aider repomap (Kosmos ADR-038 already covers) — ensure any Tektos-specific ranker logic is diffed and merged
12. Kosmos Stage 3 exit-gate tests (`test_stage_2_4_exit_gate.py`, `test_stage_3_12_exit_gate.py`) — must stay green through Stages 3–7

---

**End of plan.** Land Stage 0 first; every subsequent stage begins with a fresh SESSION_HANDOFF read and ends with a BUILD_LOG entry + SESSION_HANDOFF overwrite.
