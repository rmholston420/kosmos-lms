# Audit Report — `rmholston420/kosmos` and `rmholston420/tektos-ultima`

Prepared as an integration input for a **full fork + rewrite into `rmholston420/kosmos-lms`**. This report is descriptive only — it does not propose the integration plan.

- Kosmos clone: `/home/user/workspace/audit/kosmos` (default branch, HEAD as of clone time)
- Tektos-Ultima clone: `/home/user/workspace/audit/tektos-ultima`
- Sizes: Kosmos ≈ 9 MB, Tektos-Ultima ≈ 5 MB
- Both repos are public and were treated read-only.

Evidence citations use the form `path:line` and are collected in §5.

---

## 1. Kosmos — current state

### 1.1 Repository layout

Top-level directories: `adapters/`, `docs/`, `governance/`, `kernel/`, `ops/`, `plugins/`, `ports/`, `scripts/`, `templates/`, `tests/`, `ui/`, `vendor/`.

Root operational files:
- `BUILD_LOG.md` (3194 lines, ~186 append-only entries)
- `DEBUG_LOG.md` (~97 KB, append-only diagnosis log)
- `KNOWN_ISSUES.md` (94 lines)
- `PORTING_LEDGER.md` (388 lines)
- `SESSION_HANDOFF.md` (overwritten each session; last write `2026-08-01 12:07 EDT`, Stage 1.6 Phase 2 COMPLETE)
- `Makefile`, `pyproject.toml`, `README.md`, `research_6_3_7b.md`

### 1.2 Spec, ADRs, and governance discipline

`docs/adrs/README.md` is the authoritative ADR index. **78 ADR files (ADR-001 through ADR-076 plus a few supplements)** live under `docs/adrs/`. The build spec is `Kosmos-Build-Spec-v25.md`, the rollout is `Kosmos-Build-Sequence-v25.md`. Newer-wins conflict rule is spec-baseline (see `kosmos-spec-diff` skill).

Governance is not aspirational — the four logs are actively maintained:
- BUILD_LOG entries are timestamped `YYYY-MM-DD HH:MM EDT`, one per completed step; the most recent entries are from `2026-08-01 13:45 EDT`.
- SESSION_HANDOFF cleanly reflects "Stage 1.6 Phase 2 — COMPLETE. Next: Stage 1.6 Phase 3 (ADR-076, not yet authored) or Stage 1.7." (`SESSION_HANDOFF.md:1-8`).
- `PORTING_LEDGER.md` uses the mandated `VENDORED · PATTERN-VENDORED · PLANNED · EVALUATED-REJECTED · SUPERSEDED` statuses.

### 1.3 Formal ports (15) — `ports/`

| # | Port | File | Notes |
|---|------|------|-------|
| 1 | ApprovalGatewayPort / ChangeApprovalTier | `ports/approval.py` | Tiered change approvals (used by Tektos plugin agent) |
| 2 | DataPort | `ports/data.py` | Filesystem-backed data adapter |
| 3 | EmbeddingsPort | `ports/embeddings.py` | Ollama adapter |
| 4 | EventBusPort | `ports/event_bus.py` | Envelope-first (ADR-023); publish takes `EventEnvelope`; `producer_plugin` non-empty; `subscribe → asyncio.Queue`; xrange-shaped `read_recent` |
| 5 | EventEnvelope | `ports/event_envelope.py` | Shared value object |
| 6 | FrontendContractPort | `ports/frontend_contract.py` | Declarative UI schema (ADR-031). Surface: `register_plugin`, `list_plugins`, `get_route_manifest`, `get_design_tokens`, `get_state_namespaces`, `get_panel_manifest`, `check_ui_parity`, `render_kernel_schema`. Zero-trust `validate_plugin_descriptor` |
| 7 | LLMPort | `ports/llm.py` | Keyword-only kwargs; includes model management (`list_models`, `pull_model`, `delete_model`); `generate_stream: AsyncIterator[str]`; `is_healthy` non-throwing (ADR-022) |
| 8 | MCPPort | `ports/mcp.py` | Locked at Stage 3.2 (ADR-037). Pattern-vendored from `modelcontextprotocol/python-sdk` (MIT, commit `a4f4ccd091138771535e17191123f20b30fda68e`). Verbs: `initialize`, `list_tools`, `call_tool`, `close`, `is_healthy`. `MCP_PROTOCOL_VERSION = "2024-11-05"` |
| 9 | MemoryPort | `ports/memory.py` | Locked Stage 1.8. DozerDB + Graphiti + Agent-Memory-Guard v0.2.2 (ADR-027 extends ADR-008). `MEMORY_REQUIRED_FIELDS = frozenset({"provenance", "confidence"})` — zero-trust enforced at port layer, non-bypassable |
| 10 | NotificationPort | `ports/notification.py` | Kernel notifications |
| 11 | ObservabilityPort | `ports/observability.py` | OTEL stack adapter |
| 12 | ResourcePort | `ports/resource.py` | Balances + queue (SQLite adapter) |
| 13 | SearchPort | `ports/search.py` | SearXNG adapter |
| 14 | SecretsPort | `ports/secrets.py` | `age`-encrypted file adapter |
| 15 | TraceFeedPort | `ports/trace_feed.py` | Phrouros trace ingest |
| 16 | VectorPort | `ports/vector.py` | Qdrant adapter |

(16 files exist; `event_envelope.py` is the shared value object, so 15 formal ports + 1 envelope module.)

### 1.4 Adapters — `adapters/`

Present adapters (subdirs): `approval_resolver/praxis`, `data/filesystem`, `embeddings/ollama`, `event_bus/valkey`, `frontend_contract/kernel`, `llm/{llama_swap, ollama}`, `mcp/{in_process, stdio}`, `memory/dozerdb` (extensive: `gate`, `corpora`, `amg_policy` subtrees), `notification/kernel`, `observability/otel_stack`, `resource/sqlite`, `search/searxng`, `secrets/age_file`, `vector/qdrant`.

### 1.5 Plugins — `plugins/`

Four plugins in tree: `phrouros/` (real Stage 6.5, ADR-059), `praxis/` (approval resolver), **`tektos/`** (already substantial — see §1.11), `zetesis/` (Stage 6.5, ADR-058: composes MemoryPort + VectorPort + DataPort + LLMPort).

### 1.6 Kernel — `kernel/app.py`

Single 2746-line FastAPI app, kernel version `6.12.0` (bumped 2026-08-01 per BUILD_LOG D5 for ADR-075). Boots seven subsystems behind per-subsystem try/except in this order: `notification`, `frontend_contract`, `resource`, `event_bus`, `approval`, `phrouros`, `zetesis`. Route surface (partial, illustrative):

- `GET /health`
- Kernel introspection: `/api/kernel/{schema, routes, panels, plugins, design-tokens, kill, resume, suspension}`
- Resources: `/api/resources/{balances, queue}`
- Approvals (ADR-062): `POST /api/approvals/{id}/{approve, reject}`
- **Tektos (ADR-063 mount): `POST /api/tektos/turn`** — drives one `TektosAgent` iteration over the kernel-owned `LLMPort` + `MemoryPort` adapters; returns `TektosStep`
- Gnosis retrieval surrogate (ADR-064): `/api/gnosis/{query, corpora, stats}` (five landed corpora: `synthetic-lifeline`, `humanities-cidoc-sample`, `rigpa-export`, `superpowers`, `humanities-bilara`)
- `POST /api/memory/search-semantic` (ADR-075 D2, added 2026-08-01)
- Praxis, Phrouros anomalies, Zetesis research (SSE, ADR-060)
- WebSockets: `/api/events/ws` (ADR-061 event-bus bridge, `ready` frame + JSON `event` frames), `/api/algedonic/ws`
- Sub-app mounts: `/tektos-ui` (ADR-065), `/gnosis-gate`

### 1.7 Frontend — `ui/`

Next.js 16.2.11 + React 19.2.4 + TypeScript + Tailwind 4. Deps of note: `@radix-ui/react-dialog`, `cmdk`, `cytoscape`, `react-cytoscapejs`, `react-force-graph-2d`, `react-force-graph-3d`, `three`, `zustand`, `@tanstack/react-query`. Route pages under `ui/app/{command, gnosis, govern, kernel, memory, observe, operate, tektos, zetesis}/`. Playwright E2E tests under `ui/tests/`.

### 1.8 PORTING_LEDGER highlights

Selected vendored / pattern-vendored components (see `PORTING_LEDGER.md` full ~388 lines):

| Component | Status | License | Kosmos location | Port(s) |
|-----------|--------|---------|-----------------|---------|
| FastAPI kernel bootstrap | HAND-BUILT | MIT (Kosmos) | `kernel/app.py`, `kernel_ui_glue/` | Composes multiple |
| DozerDB Memory Adapter | WIRED (Stage 6.5) | MIT + embedded GPLv3 (DozerDB) | `plugins/zetesis/adapters/real/factory.py` | MemoryPort |
| Qdrant Vector Adapter | WIRED | MIT | same | VectorPort |
| Filesystem Data Adapter | WIRED | MIT | same | DataPort |
| Ollama LLM Adapter | WIRED (Zetesis) | MIT | `adapters/llm/ollama/` | LLMPort |
| Graphiti | temporal index (planned; hard-delete in ADR-075) | Apache-2.0 | inside MemoryPort backend | MemoryPort |
| Agent Memory Guard v0.2.2 | write-time policy | Apache-2.0 | MemoryPort layer | MemoryPort |
| OpenHands SDK (Agent/Conversation shape) | PATTERN-VENDORED (ADR-036) | MIT | `plugins/tektos/agent.py` | consumes MemoryPort+LLMPort+MCPPort+ApprovalGatewayPort |
| `modelcontextprotocol/python-sdk` (client surface) | PATTERN-VENDORED (ADR-037) | MIT | `ports/mcp.py`, `adapters/mcp/{in_process,stdio}` | MCPPort |
| aider repomap (ADR-038) | PATTERN-VENDORED | Apache-2.0 | `plugins/tektos/repomap/` | consumes DataPort |
| docling 2.116.0 (ADR-044) | VENDORED | MIT | `plugins/tektos/ingest/` | DataPort |
| datacurve-pier 0.3.0 (ADR-042) | VENDORED | Apache-2.0 | `plugins/tektos/eval/` | — |
| HTMX 2.0.4 (ADR-045) | VENDORED | 0BSD | `plugins/tektos/ui/htmx.min.js` | FrontendContractPort |

### 1.9 ADRs directly relevant to Tektos integration

Locked-in ADRs the audit found by inspection:
- ADR-007: **events-only cross-plugin coupling** (hard rule; no plugin imports another plugin)
- ADR-008 / ADR-027: MemoryPort zero-trust write contract (`provenance` + `confidence` required)
- ADR-022: LLMPort surface + rules
- ADR-023: EventBusPort envelope-first MVP
- ADR-031: FrontendContractPort declarative UI schema
- ADR-032/033/034: Praxis / Phrouros / other plugin panel priorities
- ADR-036: Tektos coding agent shape (OpenHands pattern-vendor, deferred at Stage 3.1)
- ADR-037: MCPPort + Playwright + APEX tool gating (Stage 3.2)
- ADR-038: aider repomap (Stage 3.3)
- ADR-041: Tektos plugin bootstrap at Stage 3.7 (spec-kit trigger; first plugin descriptor registration)
- ADR-042: Pier eval harness (Stage 3.8)
- ADR-044: docling ingest (Stage 3.9)
- ADR-045: HTMX dashboard for Tektos (Stage 3.11) — flips `UiParityStatus` COMPLIANT
- ADR-046: Stage-3 exit gate
- ADR-058: Zetesis kernel mount (Stage 6.5)
- ADR-059: Phrouros real backend (Stage 6.5)
- ADR-060/061/062: Zetesis SSE / event-bus WS / approval REST endpoints
- ADR-063: Tektos kernel mount (`POST /api/tektos/turn`)
- ADR-064: Gnosis retrieval surrogate
- ADR-065: Tektos UI kernel mount (`/tektos-ui` HTMX sub-app)
- ADR-074/075: latest Stage 1.6 Phase 2 landing (semantic memory search, Graphiti hard-delete, kernel 6.12.0)

### 1.10 Known issues (open)

`KNOWN_ISSUES.md` is 94 lines. From SESSION_HANDOFF the only currently flagged noise is `WebSocketDisconnect(1001)` in `events_ws._drain_client` during Playwright page-nav — expected behavior, not a bug (`SESSION_HANDOFF.md:23-24`).

### 1.11 Kosmos already contains a substantial `plugins/tektos/` scaffold

**This is a critical finding for the parent's integration plan.** `plugins/tektos/` is not a stub — it has ~3,051 non-test LOC and ~5,565 test LOC across:

| Kosmos-side path | Purpose | LOC |
|------------------|---------|-----|
| `plugins/tektos/agent.py` | `TektosAgent` (Stage 3.1, ADR-036). Pattern-vendored OpenHands `Agent`/`Conversation` shape; consumes `ApprovalGatewayPort`, `LLMPort`, `MCPPort`, `MemoryPort`, `TraceFeedPort` | 355 |
| `plugins/tektos/plugin.py` | Stage 3.7 plugin bootstrap (ADR-041); registers `PluginDescriptor` with `FrontendContractPort`; one `Panel` on `PanelSlot.APPROVALS_QUEUE` at priority 90 | 184 |
| `plugins/tektos/models.py`, `errors.py` | Value objects + typed errors (`TektosAgentAlreadyRunError`, `TektosAgentNotStartedError`, `TektosInvalidConfidenceError`) | 149 |
| `plugins/tektos/mcp/` | `fake_playwright_server.py`, `tool_policy.py` — APEX gating | 186 |
| `plugins/tektos/renderer/` | Plan renderer (ADR-041): `project.py`, `models.py`, `policy.py` | 402 |
| `plugins/tektos/repomap/` | aider-pattern repomap (ADR-038): `indexer`, `policy`, `rank`, `render`, `tags` | 984 |
| `plugins/tektos/ingest/` | docling ingest (ADR-044): `harness`, `models`, `policy` | 595 |
| `plugins/tektos/eval/` | Pier eval (ADR-042); one landed task `tektos-plan-execution-smoke`; DeepSWE corpus (ADR-...) | — |
| `plugins/tektos/openspec/` | OpenSpec change proposals (`parser`, `plan`, `policy`, `models`) | — |
| `plugins/tektos/ui/` | HTMX dashboard (ADR-045): `server` (256), `executor` (127), `templates` (235), `policy` (158), `models` (62), plus `htmx.min.js` | 924 |
| `plugins/tektos/tests/` | 13 test files, ~5,565 LOC, including `test_stage_2_4_exit_gate.py` (683) and `test_stage_3_12_exit_gate.py` (528) | 5565 |

The current confidence contract in the plugin agent is: fixed provenance `"tektos_agent"`, caller-supplied confidence (default 0.75, ADR-036). One iteration per `send_message` + `run` at Stage 3.1; multi-iteration loops, tool calls, task decomposition, and FrontendContractPort registration are all deferred to later 3.x steps.

### 1.12 CI

**No `.github/workflows/` at kosmos root.** CI configuration is absent from the repository itself. Tests run locally via `make` / `pytest` (spec-mandated); the last SESSION_HANDOFF reports "Colossus: pytest 1264 passed / 14 skipped; Playwright 10/10 passed after kernel restart".

---

## 2. Tektos-Ultima — current state

### 2.1 Repository layout

Top-level: `src/`, `frontend/`, `frontend-legacy/`, `plugins/`, `adrs/`, `docs/`, `deploy/{data-services,systemd/user/}`, `tests/`, `scripts/`, `tektos_build_system/`, `.github/`.

Root files: `ADR-LEDGER.md`, `PORTING_LEDGER.md`, `SESSION_HANDOFF.md` (last-generated `2026-08-14`), `README.md` (very short — 30 lines), `Dockerfile`, `docker-compose.yml`, `pyproject.toml` (4691 B), `uv.lock` (310 KB), `.env.example` (5923 B), `.pre-commit-config.yaml`, `.dockerignore`, `.gitignore`. **No LICENSE file at root.**

Python file count: **148**. Frontend TS/TSX file count: **111**.

### 2.2 Python source layout — `src/tektos/`

Submodule directories: `agents/{coding_agent, manager, planner, self_improvement}`, `axioms/{c, directive, milestone, test}`, `gitops/`, `gui/`, `memory/`, `migrations/`, `ports/`, `protocol/`, `providers/`, `recovery/`, `repograph/`, `runtime/`, `search/`, `self_improvement/`, `self_modification/`, `self_repair/`, `skills/`, `store/`, `telemetry/`, `thermal/`, `tools/`, `utils/`.

Loose modules directly under `src/tektos/`: `__init__.py`, `auth.py`, `axioms.py`, `config.py`, `db_manager.py`, `email_gateway.py`, **`event_bus.py`**, **`gateway_adapter.py`**, **`gateway_proxy.py`**, `git_integration.py`, `gitops.py`, `main.py`, `mcp_server.py`, `metabolism.py`, `plugin.py`, `plugin_loader.py`, `rate_limiter.py`, `recovery.py`, `repograph.py`, `requests.py`, `routing.py`, `schema_evolution.py`, `state_machine.py`, `telegram_gateway.py`, `voice.py`.

`src/tektos/runtime/` (39 modules — cognition and safety core):

```
approval_registry.py            backup_scheduler.py         context_compactor.py
context_curator.py              context_engineering.py      context_monitor.py
conversation_compressor.py      dynamic_settings.py         embedder.py
evaluation_framework.py         experience_replay.py        external_evaluator.py
hierarchical_agent.py           hooks.py                    immune_system.py
inference_engine.py             llm_client.py               long_running_agent.py
loop_guard.py                   loop_safety.py              mcp_integration.py
multi_agent_orchestrator.py     observability.py            planner_orchestrator.py
rag_engine.py                   rag_retriever.py            reflection_engine.py
repo_map.py                     repo_map_generator.py       repo_memory.py
sdk.py                          self_modification.py        session.py
session_state.py                state_manager.py            synthesis_engine.py
task_decomposer.py              tool_router.py              ws_manager.py
```

`src/tektos/memory/`:

```
backup_scheduler.py   experience_replay.py   file_based_memory.py   hindsight_client.py
memory_system.py      neo4j_memory.py        persistence.py         postgres_memory.py
redis_memory.py       reflection_engine.py   synthesis_engine.py
```

`src/tektos/thermal/`: `config.py`, `metrics.py`, `monitor.py`, `power_optimizer.py`, `regulator.py` (PID controller with `PID_KP/KI/KD`, `TARGET_TEMP`, integral/derivative limits).

`src/tektos/tools/`: `__init__.py`, `registry.py` (dynamic tool registry, 553 LOC).

`src/tektos/axioms/`: subdirs `c`, `directive`, `milestone`, `test` — axiom families used by S5 identity.

### 2.3 `main.py` — one large FastAPI monolith

`src/tektos/main.py` mounts **~154 endpoints** (154 `@app.` decorators, of which 2 are WebSocket routes). Header comment states "Adapted from PlexClaw with all critical bug fixes … Bug #9 JSON parsing in WS, Bug #10 approve/reject errors, Bug #12 FS_ROOT configurable". Endpoint families (line numbers approximate):

| Family | Path prefix | Endpoints |
|--------|-------------|-----------|
| Runtime | `/api/prompt/sse`, `/health`, `/api/logs`, `/api/directory_list` | 4 |
| Axioms | `/api/axioms`, `/api/axioms/{id}/verify` | 2 |
| Voice | `/api/voice/{state,stt,tts}` | 3 |
| Memory (4-tier) | `/api/memory`, `/api/memory/stats`, `/api/memory/decay`, `/api/memory/{tier}/{id}` | 4 |
| Dreamtime | `/api/dreamtime/{summary,history,run,trigger-skill-generation}` | 4 |
| Skills | `/api/skills[...]` — 16 endpoints incl. `/execute`, `/dedup`, `/{id}/improve`, `/{id}/improve/from-execution`, `/maintenance`, `/select` | 16 |
| Tools | `/api/tools[...]` — list, schema, register, `/{name}/{enable,disable,execute}` | 6 |
| MCP | `/api/mcp/{status,connect}` | 2 |
| Metabolism | `/api/metabolism[...]` | 3 |
| **Immune** | `/api/immune/{health,threats,memory,responses,detectors,memory/entries}` | 6 |
| Self-repair | `/api/self_repair/{status,history,repair,health}` | 4 |
| Thermal | `/api/thermal/{status,health,reset}` | 3 |
| Self-improvement | `/api/self_improvement/{metrics,experiences,report,enqueue,status}` | 5 |
| Planner | `/api/planner/{templates,language-games,plan,status}` | 4 |
| Schema evolution | `/api/schema/{patterns,propose,apply}` | 3 |
| DB manager | `/api/db[...]` — 20+ endpoints for arbitrary CRUD + backup + optimize | ~24 |
| Models & Sessions | `/api/models`, `/api/sessions[...]` — CRUD + archive + fork + interrupt + model switch + delegate + events + replay | ~17 |
| Search | `/api/search` | 1 |
| Vision | `/api/vision/{analyze,analyze-url,status}` | 3 |
| Plugins | `/api/plugins`, `/api/plugins/{name}/toggle` | 2 |
| Context / Embedder / Evaluation / Inference / RAG / RepoMap / ToolRouter / ContextCurator / RAGRetriever / Observability / Multi-agent / Nervous-system | `/api/{...}/status[...]` — status panels for every runtime subsystem | ~15 |
| LLM probe | `/api/llm/probe` | 1 |
| Schema | `/api/schema` | 1 |
| State manager | `/api/state/{id}[...]` | 3 |
| Telemetry / Hooks / Config / Schedule / Routing / Keys | `/api/{telemetry,hooks[...],config,schedule,routing/decide,keys}` | ~7 |
| **Neo4j / Postgres / Redis** health | `/api/{neo4j,postgres,redis}/status` | 3 |
| **Hindsight** | `/api/hindsight/{status,retain,recall,reflect,experiences}` | 5 |
| WebSockets | `/ws/{session_id}` (main WS), `/ws/pty` | 2 |

Header confirms this is a `PlexClaw`-adapted, single-file monolith (`src/tektos/main.py:1-16`).

### 2.4 Tool registry — `src/tektos/tools/registry.py`

`ToolDefinition` dataclass with `name`, `description`, JSON-schema `parameters`, `handler`, `enabled`, `timeout`, `call_count`, `last_call`. `ToolRegistry.load_built_in(sandbox)` registers **7 built-in tools**: `bash`, `file_read`, `file_write`, `file_delete`, `directory_list`, `directory_create`, `search` (regex). Every handler delegates to `sandbox.execute(name, params)` — the tool layer is a schema+dispatch shell over `SandboxProvider`. External tools are pluggable via MCP through `mcp_server.py` and `runtime/mcp_integration.py`. `to_tools_schema()` renders the OpenAI tool-schema shape. Design comment cites VSM3 "requisite variety" (`src/tektos/tools/registry.py:1-30`).

### 2.5 Immune system — `src/tektos/runtime/immune_system.py`

1925 LOC. Biologically-modeled active-defense subsystem. Class layout:

- `Threat`, `ThreatSeverity`, `ThreatCategory` (categories include `PROMPT_INJECTION`, more)
- `ResponseRecord`, `HealthScore`, `ImmuneContext`
- `Detector` (Protocol) plus **12 concrete detectors**, all registered by `_register_default_detectors`:
  - `PromptInjectionDetector`
  - `ContextCollapseDetector(max_context_pct=0.9)`
  - `ResourceExhaustionDetector`
  - `LoopDetectionDetector`
  - `PerformanceDegradationDetector`
  - `SelfDegradationDetector`
  - **`SecretExposureDetector`** — 12 compiled regex patterns for API keys, passwords, `mysql -pXXX`, secret keys, tokens, `aws_secret`, `ghp_...` GitHub PATs, `sk-...` OpenAI-style, private-key headers, DB connection strings (`mysql|postgres|mongodb|redis://user:pass@`), Slack webhook/bot tokens (`src/tektos/runtime/immune_system.py:570-599`)
  - `DangerousCommandDetector` (bash write-target inspection helpers `_bash_command_writes`, `_bash_write_targets`)
  - `SelfModificationDetector`
  - `InferenceEngineProtectionDetector`
  - `ModelFailoverDetector`
  - `BodyProtectionDetector`
- Orchestration: `ImmuneMemory`, `ResponseEngine` (quarantine → throttle → isolate → halt escalation ladder), `HealthDashboard`, and `ImmuneSystem` singleton with `register_detector(name, detector)`, `respond_to_threats()`, `get_health()`.

Docstring maps biology to VSM: S1 body, S2 white blood cells, S3 orchestrator, S4 adaptive immunity, S5 self/non-self axioms.

### 2.6 Loop safety — `src/tektos/runtime/loop_safety.py`

403 LOC. Three tiers documented in header:
- Tier 1 hard limits: `max_turns=15`, `max_tokens_per_turn=8192`, `max_tokens_total=65536`, `max_wall_time_seconds=300.0`
- Tier 2 behavioral: `TurnSnapshot(turn_num, tool_calls, input_ids, text_length, tokens_used)` fed into a rolling `deque(repetition_window=3)`; `repetition_threshold=2`
- Tier 3 circuit breaker: `warning_threshold_pct=0.8`, `circuit_breaker_enabled=True`
- States: `NORMAL | WARNING | CRITICAL | STOPPED`; stop reasons: `MAX_TURNS | MAX_TOKENS | MAX_WALL_TIME | REPETITION | CIRCUIT_BREAKER`

Companion module `loop_guard.py` sits alongside.

### 2.7 Hindsight cross-session memory

`src/tektos/memory/hindsight_client.py` (148 LOC) is a synchronous `httpx` wrapper around a Hindsight HTTP server. `HindsightConfig(base_url="http://127.0.0.1:9177", bank_id="default", timeout=30.0)`. Methods: `health`, `retain(content, *, context, tags)`, `retain_batch(items)`, `recall(query, *, limit=5)`, `reflect(question, *, max_tokens=1000)`, `get_experiences(context, *, limit=10)` (tag-preferring filter). Endpoints: `GET /health`, `POST /banks/{bank_id}/{retain,recall,reflect}`. Module-level `get_hindsight_client(config)` singleton.

Note port mismatch: the client default is **`:9177`** (Hermes install), while the `deploy/systemd/user/tektos-hindsight.service` runs Tektos's own hindsight on **`:9000`** — see `docs/ports.md` "Sibling installs on this workstation (not tektos, do not use)".

### 2.8 4-tier memory system — `src/tektos/memory/memory_system.py`

Docstring models the human brain's four memory systems (`src/tektos/memory/memory_system.py:1-38`):
1. Sensory (100 ms – 4 s): raw event-stream buffer
2. Working / short-term (seconds – minutes): 7±2 items (Miller's Law) — session context, current spec, active plan
3. Long-term (days – permanent): declarative + episodic → Hindsight, session DB, Trail
4. Procedural / semantic (permanent): skills DB, ADRs, PORTING_LEDGER, git history

Also invokes bicameral architecture (S1 left-hemisphere / S4 right-hemisphere / S3 corpus callosum). Backing stores:
- `neo4j_memory.py` — DozerDB (community fork extending Neo4j; free) via `bolt://localhost:7687`
- `postgres_memory.py`, `redis_memory.py`, `file_based_memory.py`
- `persistence.py`, `backup_scheduler.py`
- `experience_replay.py`, `reflection_engine.py`, `synthesis_engine.py` (self-improvement wiring)

### 2.9 Gateway / event bus / state machine

- `src/tektos/gateway_proxy.py` (757 LOC) — WebSocket JSON-RPC 2.0 proxy bridging **Hermes Desktop frontend** on `ws://:8765/` to Tektos REST + WS on `http://127.0.0.1:8020`. Handles JSON-RPC methods: `session.{create,list,resume,close,interrupt,status,most_recent}`, `prompt.submit`, `model.options`, `config.{get_value,set}`, `ping`. Normalizes Tektos event types to gateway-notification shape: `assistant.{delta,reasoning,completed}`, `tool.{started,completed,permission.required}`, `session.{ready,created,updated,interrupted,failed}`, `system.message`. Reconnects automatically after `assistant.completed` closes the Tektos WS. Synthesizes per-session `_assistant_msg_ids` so the frontend has a stable id per turn.
- `src/tektos/gateway_adapter.py` — in-process adapter counterpart.
- `src/tektos/event_bus.py` (203 LOC) — in-process pub/sub with type-filter routing (`exact`, prefix `tool.*`, wildcard `*`), synchronous delivery. Documents VSM-layer default subscriptions (S1 `tool.*`/`assistant.*`, S2 all, S3 `resource.*`/`loop_safety.*`/`session.failed`/`tool.permission.required`, S4 `self_improvement.*`/`resource.warning`, S5 `session.failed`). Adapted from PlexClaw event routing (simplified) + Hermes Agent pub/sub pattern.
- `src/tektos/state_machine.py` — explicit FSM: `created → ready → running → ready|interrupted|failed`, `interrupted → ready`. Invalid transitions raise `InvalidTransitionError`. Emits `session.state_change` on every transition. ADR-005 in `ADR-LEDGER.md`.
- `src/tektos/runtime/ws_manager.py` — WS fanout.
- `src/tektos/store/event_store.py` — append-only SQLite event store + FTS5.

### 2.10 Thermal control

`thermal/regulator.py` implements a PID controller (constants `PID_KP`, `PID_KI`, `PID_KD`, `PID_INTEGRAL_LIMIT`, `PID_DERIVATIVE_LIMIT`, `TARGET_TEMP`) for GPU power/clock; lazy-imports `pynvml`; fan control skipped as unavailable. `thermal/monitor.py` runs an async loop: collect telemetry → PID → adjust → report → log. Policy from `SESSION_HANDOFF.md`: **Yellow 51 °C, Cap 80 °C, Red 88 °C; file-only mode ≥ 80 °C (no inference); 400 W GPU power limit enforced via `gpu-power-limit.service`**.

### 2.11 Deployment surface

`deploy/systemd/user/` ships six units under a common `tektos.target`:

| Unit | Port | Bind | Purpose |
|------|------|------|---------|
| `tektos-backend.service` | 8020 | 127.0.0.1 | uvicorn on `main:app`, `KillMode=mixed`, `TimeoutStartSec=120` (whisper + migrations) |
| `tektos-gateway.service` | 8765 | 127.0.0.1 | `python -m tektos.gateway_proxy --port 8765 --tektos-url http://127.0.0.1:8020`. `Requires=tektos-backend.service` |
| `tektos-hindsight.service` | 9000 | 0.0.0.0 | `hindsight-api --port 9000 --log-level info`. `Requires=tektos-llm-hindsight.service`. `Wants` (not Requires) at target level so failure does not cascade. `StartLimitBurst=3` / `StartLimitIntervalSec=120` |
| `tektos-llm-hindsight.service` | 8095 | 127.0.0.1 | `llama-server` with **IBM Granite 4.0 H Tiny 7B-A1B Q4_K_M** (`~/dev/tektos-ultima-v1/models/granite-4.0-h-tiny-Q4_K_M.gguf`), `--ctx-size 16384`, `--n-gpu-layers -1`, `--parallel 2`, `--cont-batching`, `--log-disable`. `StartLimitBurst=5` |
| `tektos-frontend.service` | 5556 | 0.0.0.0 | `bash -lc 'exec npm run start'` in `frontend/` |
| `tektos.target` | — | — | Groups all four services with `Wants=` (not `Requires=`) so single-service failure does not stop the whole stack |

`docker-compose.yml` and `Dockerfile` also present (not yet inspected in depth) — the systemd path is the canonical local topology.

### 2.12 Ports allocation (from `docs/ports.md`)

Loopback-only Tektos services: 8020 backend, 8765 gateway, 8095 llama-server for hindsight; 9000 hindsight (`0.0.0.0` by upstream default); 5556 frontend (`0.0.0.0`). Hermes-managed model endpoints Tektos assumes: 8090 default LLM, 8091 embedder Qwen3-Embedding-0.6B, 8092/8093 reserved, 8094 vision Qwen3-VL-4B. Host data services: 5432 PostgreSQL 18 + pgvector 0.8.1 (hindsight `hindsight` db), 7474/7687 Neo4j HTTP/Bolt, 6379 Redis. **Sibling install:** 9177 Hermes Hindsight (separate hindsight install under Hermes venv). The doc is explicit that "no Tektos component should ever bind to 0.0.0.0 on a workstation without a matching entry that explains why".

### 2.13 Frontend

`frontend/package.json`: Next 15.4, React 19.1, Tailwind 4, Playwright 1.52, Jest 30, Radix Dialog/Popover/ScrollArea/Tooltip, `@tanstack/react-virtual`, `@monaco-editor/react`, Monaco 0.52, xterm 6 + addons (fit, serialize, unicode11, web-links, webgl), `d3`, `d3-force-3d`, `cmdk`, `date-fns`, `dompurify`, `highlight.js`, `marked`. Dev port `3004` (`next dev --turbopack -p 3004`); prod port `5556` (`next start -p 5556`).

Component directories: `assistant-ui/tool-visualizers`, `chat/`, `graphs/`, `palette/`, `panels/`, `panes/`, `shell/{AppShell.tsx, LeftRail.tsx}`. **40 panels** under `frontend/src/components/panels/`, matching every backend `/api/{...}/status` endpoint:

```
AxiomsPanel  ConfigPanel  ContextCuratorPanel  ContextPanel  DatabasePanel
DreamtimePanel  EmbedderPanel  EvaluationPanel  HindsightPanel  HooksPanel
ImmuneSystemPanel  InferencePanel  KeysPanel  LogsPanel  McpPanel
MemoryPanel  MemorySystemPanel  MetabolismPanel  ModelRouterPanel
MultiAgentOrchestratorPanel  Neo4jPanel  NervousSystemPanel  ObservabilityPanel
OpsPanel  PlannerPanel  PostgresPanel  RagPanel  RagRetrieverPanel
RedisPanel  RepoMapPanel  SchedulingPanel  SchemaEvolutionPanel
SelfImprovementPanel  SelfRepairPanel  SettingsPanel  SkillsPanel
SystemDashboard  TelemetryPanel  ThermalPanel  ToolRouterPanel
```

App-router pages: `frontend/src/app/{artifacts, dashboard, runs, s, settings}`. `frontend-legacy/` still ships in the tree (older Next.js version retained).

### 2.14 Plugins (Tektos-side)

`plugins/`: `duckduckgo_plugin`, `farfalle_plugin`, `searxng_plugin`, `tavily_plugin` — four search-provider plugins over the `Plugin` ABC in `src/tektos/plugin.py`. Ranking classification per `plugin.py:1-30`:
- **Built-in** (existential): `protocol/`, `store/`, `runtime/`, `self_modification/`, `self_improvement/`, `agents/`, `ports/`
- **Plugin** (swappable): `providers/`, `memory/` backends, `telegram_gateway.py`
- **Skill** (procedural, not code): `~/.hermes/skills/`

### 2.15 ADR / porting discipline

Tektos has **two conflicting ADR sources**:
- `ADR-LEDGER.md` at root — narrative form, only 91 lines, entries ADR-005 (Nervous System) and ADR-004 (Metabolism), both dated 2026-08-16.
- `adrs/README.md` — six shorter ADRs (ADR-001 SQLite, ADR-002 FastAPI, ADR-003 Next.js, ADR-004 Heroicons, ADR-005 Port Allocation, ADR-006 GPU Thermal).

**Both sources use "ADR-004" and "ADR-005" for different decisions.** There is no ADR-index reconciler.

`PORTING_LEDGER.md` covers only **new** additions (telemetry endpoint, event bus, state machine, and three frontend panels/types), not the historical vendoring of PlexClaw / Hermes / OpenHands patterns that permeates the codebase.

### 2.16 CI, license, and packaging

`.github/workflows/ci.yml` runs six jobs: `python-lint` (ruff check + format), `python-typecheck` (mypy), `python-tests` (pytest, gated on lint+typecheck), `frontend-build` (Next build), `frontend-lint` (eslint; warnings tolerated), `frontend-e2e` (Playwright chromium only). Summary job is informational only. `python-tests` runs full pytest — no live GPU/model gating.

`pyproject.toml`: `hatchling` build; deps FastAPI ≥0.104, uvicorn[standard] ≥0.24, websockets ≥12, aiosqlite ≥0.19, pydantic ≥2.5, httpx ≥0.25, python-multipart, aiofiles. Optional extras: `gpu` (`nvidia-ml-py ≥12`), `voice` (`faster-whisper ≥1`, `edge-tts ≥6.1.9`, `pydub`), `mcp` (`mcp ≥1.0`), `dev` (pytest, ruff, mypy, aiogram, requests + mirrored voice/mcp deps). `[project.scripts] tektos = "tektos.main:main"`. Ruff line-length 100, tests excluded. **Mypy `strict = false`** with a large `[[tool.mypy.overrides]]` `ignore_errors=true` block covering `main.py`, `runtime.sdk`, `runtime.immune_system`, `runtime.multi_agent_orchestrator`, `runtime.hooks`, `runtime.conversation_compressor`, `runtime.rag_retriever`, `runtime.inference_engine`, `schema_evolution`, `db_manager`, `gateway_adapter`, `gateway_proxy`, `mcp_server`, `metabolism`, `routing`, `repograph.core`, `self_repair.strategies`, `self_repair.engine`, `agents.planner.spec_generator`, `agents.planner.repo_map`, `telegram_gateway`, plus `skills.manager`, `self_modification.*`, `self_improvement.engine`.

**No LICENSE / COPYING file at repo root.** README does not state a license either. Under GitHub default, public code with no license is **all-rights-reserved** to the author — this is a blocker for any full fork/rewrite under a Kosmos permissive-license regime.

### 2.17 `.env.example` topology

The env doc pins two LLM topologies:
- **Topology A (recommended):** Tektos → Hermes proxy at `http://127.0.0.1:8093/v1`, model `qwen3.8-27b-code`; Tektos-side failover disabled because Hermes owns GPU→CPU failover to 8090 and 8092.
- **Topology B (fallback):** Tektos → direct llama-server at `:8090` (primary `qwen3.8-27b-code`) + fallback `:8092` (`granite4.1-8b-instruct`) + Tektos-managed failover with `TEKTOS_LLM_FAILOVER_COOLDOWN_SECONDS=30`.

`TEKTOS_PROMPT_TIMEOUT_SECONDS=120` (introduced in PR #9). Embedder `:8091` (`qwen3-embedding-0.6b`). Vision `:8094` (`qwen3-vl-4b`). SearXNG `:8888/search`. Hindsight LLM `:8095` (`granite-4.0-h-tiny` @ Q4_K_M, ctx 16384). Hindsight service points at `HINDSIGHT_API_LLM_BASE_URL=http://127.0.0.1:8095/v1` with `HINDSIGHT_API_LLM_API_KEY=local` (llama-server does not authenticate). Hindsight embeddings stay local: `HINDSIGHT_API_EMBEDDINGS_PROVIDER=local`, `BAAI/bge-small-en-v1.5`.

### 2.18 Test surface

`SESSION_HANDOFF.md`: **336 Python tests + 28 Playwright E2E** (chromium only) all passing. `tests/` on disk not enumerated per-file here; pytest config `asyncio_mode = "auto"`, `testpaths = ["tests"]`.

---

## 3. Overlap / gap matrix

For every Tektos capability, this table records:
- **Kosmos equivalent** (port, adapter, plugin, kernel route, or "none")
- **Nature of overlap** (duplicate, partial, adapter-shaped, none)
- **Migration axis** — what has to happen for the capability to live inside `kosmos-lms` under Kosmos discipline (ADR-007 events-only, zero-trust MemoryPort writes with `provenance` + `confidence`, port/adapter separation, ADR + PORTING_LEDGER + BUILD_LOG update)

### 3.1 Cognition, agent surface

| Tektos capability | Tektos location | Kosmos equivalent | Overlap | Migration axis |
|-------------------|-----------------|-------------------|---------|----------------|
| Coding agent (single-turn loop) | `agents/coding_agent/executor.py`, `runtime/session.py` | `plugins/tektos/agent.py` (`TektosAgent`, Stage 3.1 ADR-036, one-turn) | Duplicate at conceptual level; Kosmos version is a strict port-consumer subset | Fold Tektos's multi-iteration + tool-loop + reflection logic into an extended `TektosAgent` behind LLMPort/MCPPort/MemoryPort/ApprovalGatewayPort/TraceFeedPort. Confidence per event, provenance `"tektos_agent"` (or a finer taxonomy) |
| Planner (spec generation, template selection, disambiguation, language games) | `agents/planner/{orchestrator,spec_generator,template_selector,disambiguator,language_game,translator,repo_map}.py` | Not present (Kosmos has plan renderer + OpenSpec parser in `plugins/tektos/{renderer,openspec}` but no planner engine) | Partial — Kosmos has downstream plan-rendering; Tektos has upstream plan-generation | Port the planner as a Tektos sub-capability. Emits plans through EventBusPort; approval tier lifts through ApprovalGatewayPort |
| Manager (guardrails, archetype tracking, metrics) | `agents/manager/{orchestrator,guardrails,metrics,telemetry,archetype_tracker}.py` | Praxis (`plugins/praxis`) is Kosmos's approval-resolver, and Phrouros is the anomaly detector — closest analogues but not the same role | Partial | Reclassify manager → hybrid of Praxis (approval) + Phrouros (anomaly) + new "orchestrator" subsystem inside Tektos plugin |
| Multi-agent orchestrator | `runtime/multi_agent_orchestrator.py` | None | Gap | New capability inside Tektos plugin; must obey ADR-007 (agents-as-plugins pattern would violate it — keep in-plugin) |
| Hierarchical / long-running agent | `runtime/hierarchical_agent.py`, `runtime/long_running_agent.py` | None | Gap | Same as above; may need Kosmos-level session-state persistence via MemoryPort |
| Task decomposer | `runtime/task_decomposer.py` | Kosmos `plugins/tektos/openspec` (change proposals) | Partial | Merge into OpenSpec parser + planner path |
| Reflection engine | `runtime/reflection_engine.py`, `memory/reflection_engine.py` | None | Gap | Add as Tektos-plugin subsystem writing back through MemoryPort with `provenance="tektos_reflection"` |
| Synthesis engine | `runtime/synthesis_engine.py`, `memory/synthesis_engine.py` | None | Gap | Same |
| Self-improvement (SynthesisEngine → Planner feedback loop) | `runtime/*`, `self_improvement/*`, ADR-005 in `ADR-LEDGER.md` (Phase 6 done) | None | Gap | Requires ADR authoring in Kosmos; touches MemoryPort + EventBusPort + LLMPort. Contains a self-improvement mandate (Tektos's raison d'être) that has no analogue in current Kosmos |
| Self-modification (`self_gui_expander`, `self_test_expander`) | `self_modification/*` | None | Gap | Bounded by Kosmos immune-system-style protections; needs new ADR + likely new port (`SelfModificationPort` with approval gating) |
| Self-repair | `self_repair/{engine,workflows,strategies,effectiveness,health_monitor}.py` | None | Gap | Wraps under ApprovalGatewayPort + notification |

### 3.2 Memory

| Tektos capability | Tektos location | Kosmos equivalent | Overlap | Migration axis |
|-------------------|-----------------|-------------------|---------|----------------|
| 4-tier memory system (sensory / working / long-term / procedural) | `memory/memory_system.py` | MemoryPort + Zetesis (single unified graph+temporal+policy layer) | **Conceptual conflict** — Tektos models 4 tiers with distinct backends; Kosmos models one MemoryPort with `write_event` + `query_temporal` + `search_semantic` | Reclassify Tektos "tiers" as query-time views over Kosmos MemoryPort. Working memory → session context in the Tektos-plugin; long-term/procedural → MemoryPort corpora; sensory → EventBusPort ring buffer |
| Hindsight cross-session memory | `memory/hindsight_client.py` (HTTP `POST /banks/{id}/{retain,recall,reflect}`); dedicated `hindsight-api` + `llama-server :8095` (Granite 4.0 H Tiny) via systemd | None. Kosmos has DozerDB + Graphiti + AMG under MemoryPort, plus Gnosis retrieval surrogate | Partial — different mental model | Two options: (a) run Hindsight as an adjacent service and adapter it behind MemoryPort; (b) replace Hindsight with DozerDB-backed retention through MemoryPort. The zero-trust write requirement means Hindsight `retain` calls MUST be wrapped so they inject `provenance` + `confidence` before hitting the port. **Port collision:** `HindsightConfig.base_url` defaults to `:9177` (Hermes install) while Tektos systemd runs on `:9000` — client callers presumably override at runtime |
| Neo4j / DozerDB backend | `memory/neo4j_memory.py` (`bolt://localhost:7687`, DozerDB plugin) | `adapters/memory/dozerdb/` (DozerDB + Graphiti + AMG) | Duplicate — Kosmos version is more sophisticated (graph + temporal + write-time policy filter) | Deprecate Tektos direct Neo4j client; route through MemoryPort |
| Postgres memory | `memory/postgres_memory.py` | None (Postgres 18 + pgvector 0.8.1 present on host for Hindsight only) | Gap | If retained, must live behind an adapter for MemoryPort |
| Redis memory | `memory/redis_memory.py` | None (Redis 6379 host-managed for cache) | Gap | Same |
| File-based memory | `memory/file_based_memory.py` | `adapters/data/filesystem/` (DataPort) | Overlap | Fold under DataPort or drop |
| Experience replay | `memory/experience_replay.py`, `runtime/experience_replay.py` | None | Gap | Add through MemoryPort + EventBusPort |
| Reflection / synthesis engines (memory-side) | `memory/{reflection,synthesis}_engine.py` | None | Gap | Same |
| Persistence + backup scheduler | `memory/persistence.py`, `memory/backup_scheduler.py`, `runtime/backup_scheduler.py` | DozerDB backup (spec §7 zero-trust) via adapter | Partial | Consolidate into DozerDB adapter path |

### 3.3 Runtime, orchestration, safety

| Tektos capability | Tektos location | Kosmos equivalent | Overlap | Migration axis |
|-------------------|-----------------|-------------------|---------|----------------|
| **Immune system** (12 detectors, 1925 LOC) | `runtime/immune_system.py` | None | Gap | High-value Tektos IP. Needs a new Kosmos formal port (proposal: `ImmunePort` with `scan(ctx) -> list[Threat]`, `respond(threats) -> ResponseRecord`, `get_health() -> HealthScore`). SecretExposureDetector's 12 patterns are directly reusable in Kosmos guarded write paths |
| Loop safety (3-tier: hard-limits, repetition, circuit-breaker) | `runtime/loop_safety.py`, `runtime/loop_guard.py` | None | Gap | Same as above — a `LoopSafetyPort` (or fold into `ImmunePort` as an ambient detector) |
| Approval registry | `runtime/approval_registry.py` | ApprovalGatewayPort + Praxis adapter | Overlap | Deprecate Tektos registry; consume ApprovalGatewayPort |
| Nervous system (event bus + state machine) | `event_bus.py`, `state_machine.py` (ADR-005 in `ADR-LEDGER.md`) | EventBusPort (envelope-first, ADR-023) + Kosmos does not have an explicit session FSM | Overlap on event bus; gap on FSM | Retire Tektos in-process bus in favor of EventBusPort. Move Tektos FSM into the Tektos plugin as its own state-management layer (envelopes emit `session.state_change`) |
| Context engineering (compactor, curator, monitor, engineering, compression) | `runtime/context_{compactor,curator,monitor,engineering}.py`, `runtime/conversation_compressor.py` | None | Gap | Add as Tektos-plugin subsystems consuming MemoryPort |
| Dynamic settings | `runtime/dynamic_settings.py` | Governance dir in Kosmos (`governance/`) | Partial | Fold into Kosmos governance surface |
| Hooks registry | `runtime/hooks.py` | EventBusPort subscription | Partial | Subscribers register through EventBusPort |
| Inference engine, LLM client | `runtime/inference_engine.py`, `runtime/llm_client.py` | LLMPort + Ollama/llama-swap adapters | Overlap | Deprecate Tektos inference layer; consume LLMPort. Tektos's Hermes-topology proxy at `:8093` can become a new LLMPort adapter |
| MCP integration | `runtime/mcp_integration.py`, `mcp_server.py` | MCPPort + in_process/stdio adapters (ADR-037, protocol `2024-11-05`) | Overlap | Consume MCPPort |
| Observability | `runtime/observability.py` | ObservabilityPort + otel_stack adapter | Overlap | Consume ObservabilityPort |
| Planner orchestrator | `runtime/planner_orchestrator.py` | None (see §3.1) | Gap | Add as planner subsystem in plugin |
| RAG engine + retriever | `runtime/{rag_engine,rag_retriever}.py` | Zetesis composes MemoryPort + VectorPort + LLMPort + DataPort | Overlap — Zetesis is Kosmos's canonical RAG | Deprecate Tektos RAG; use Zetesis or extend it with any missing Tektos-specific retrievers |
| Repo map + generator + repo memory | `runtime/{repo_map,repo_map_generator,repo_memory}.py`, `repograph/core.py` | `plugins/tektos/repomap/` (ADR-038, aider pattern, 984 LOC) | Duplicate | Consolidate on Kosmos repomap; migrate any Tektos-specific ranker logic |
| Session + session state + state manager | `runtime/{session,session_state,state_manager}.py` | Kernel `/api/tektos/turn` (single-turn, ADR-063); no session persistence layer | Gap | Session state must persist through MemoryPort (episodic) + DataPort (large blobs) |
| Tool router | `runtime/tool_router.py` | MCPPort routing (in-plugin) | Partial | Fold into MCPPort consumer within Tektos plugin |
| WS manager | `runtime/ws_manager.py` | `/api/events/ws` (ADR-061 event-bus WS bridge) | Overlap | Deprecate Tektos WS manager; use kernel event-bus WS |
| SDK | `runtime/sdk.py` | LLMPort + kernel routes | Overlap | Deprecate |

### 3.4 Tools & sandbox

| Tektos capability | Tektos location | Kosmos equivalent | Overlap | Migration axis |
|-------------------|-----------------|-------------------|---------|----------------|
| Tool registry (dynamic, JSON-schema, event-emitting) | `tools/registry.py` (553 LOC), 7 built-ins (`bash`, `file_read`, `file_write`, `file_delete`, `directory_list`, `directory_create`, `search`) | MCPPort + APEX tool gating (ADR-037) via `plugins/tektos/mcp/tool_policy.py` | Partial — different shape (registry vs. MCP catalog) | Model built-in tools as MCP tools served by an in-process adapter, so external MCP + built-in tools share one surface |
| Sandbox provider | `providers/sandbox_provider.py` | None (Kosmos has no execution sandbox port) | Gap | Add a `SandboxPort` proposal or wrap sandbox behind MCPPort as a special server. Approval tier for destructive commands lifts through ApprovalGatewayPort + DangerousCommandDetector |
| Search providers (SearXNG, Google, DDG, Farfalle, Tavily) | `providers/searxng_provider.py`, `plugins/{duckduckgo,farfalle,searxng,tavily}_plugin/` | SearchPort + SearXNG adapter | Overlap on SearXNG; DuckDuckGo / Tavily / Farfalle are Tektos-only | Extend SearchPort adapters or make Tektos search plugins consume SearchPort |
| Unified search facade | `search/unified_search.py`, `providers/unified_search.py` | SearchPort direct call | Overlap | Consume SearchPort |
| Vision | `providers/vision_client.py`, `/api/vision/*`, Qwen3-VL-4B :8094 | None | Gap | Needs LLMPort extension or a new `VisionPort` (out of scope of current ADRs) |

### 3.5 Governance & self-improvement

| Tektos capability | Tektos location | Kosmos equivalent | Overlap | Migration axis |
|-------------------|-----------------|-------------------|---------|----------------|
| Axioms (S5 identity) | `axioms.py`, `axioms/{c,directive,milestone,test}/`, `/api/axioms` | Kosmos has no S5 axiom surface — ADRs and specs play that role | Gap | Axioms port or fold into `governance/` config; each verify triggers Praxis approval |
| Metabolism | `metabolism.py`, `/api/metabolism*` | None | Gap | New subsystem; probably tied to resource budgeting through ResourcePort |
| Dreamtime | `/api/dreamtime/*`, `runtime/dreamtime` (in main.py handlers) | None | Gap | Off-hours reflection loop — schedule + MemoryPort |
| Skills | `skills/{executor,manager,registry}.py`, `/api/skills/*` (~16 endpoints incl. dedup, improve, execute) | None | Gap | Move skills DB behind MemoryPort (`provenance="tektos_skill"`) |
| Schema evolution | `schema_evolution.py`, `/api/schema/{patterns,propose,apply}` | None | Gap | High-risk; needs Kosmos ADR + approval gating |
| Self-improvement metrics / experiences / report / enqueue | `runtime/self_improvement/*`, `self_improvement/`, `/api/self_improvement/*` | None | Gap | Same |
| Evaluation framework + external evaluator | `runtime/{evaluation_framework,external_evaluator}.py` | Pier eval (ADR-042) in `plugins/tektos/eval/` | Overlap | Consolidate into Pier eval |
| Recovery, git integration, gitops | `recovery.py`, `git_integration.py`, `gitops.py`, `gitops/engine.py` | None | Gap | New subsystems; likely wrap under ApprovalGatewayPort |

### 3.6 I/O gateways

| Tektos capability | Tektos location | Kosmos equivalent | Overlap | Migration axis |
|-------------------|-----------------|-------------------|---------|----------------|
| Gateway WebSocket proxy (JSON-RPC 2.0 bridge for Hermes Desktop) | `gateway_proxy.py` (757 LOC, :8765) | None | Gap | Retain as-is if kosmos-lms still wants Hermes Desktop compatibility; otherwise deprecate. Not a plugin — it's a shim |
| Gateway adapter (in-process) | `gateway_adapter.py` | Kernel `/api/events/ws` (ADR-061) | Overlap | Deprecate in-process adapter; consume kernel WS |
| Telegram gateway | `telegram_gateway.py`, `email_gateway.py`, `voice.py`, `/api/voice/*` | None (Kosmos NotificationPort is different — kernel-level notifications) | Gap | Convert to Tektos plugin sub-capabilities; may bring in `aiogram` + `edge-tts` deps into kosmos-lms |
| MCP server (Tektos exposes itself over MCP) | `mcp_server.py` | None (Kosmos consumes MCP but does not export itself) | Gap | If kept, becomes a "Kosmos-as-MCP-server" surface |
| Rate limiter | `rate_limiter.py` | None | Gap | New subsystem or via ResourcePort |
| Routing | `routing.py`, `/api/routing/decide` | None | Gap | Move into LLMPort adapter selection logic |

### 3.7 Thermal, telemetry, GPU

| Tektos capability | Tektos location | Kosmos equivalent | Overlap | Migration axis |
|-------------------|-----------------|-------------------|---------|----------------|
| PID thermal regulator | `thermal/regulator.py` (`PID_KP/KI/KD`, `TARGET_TEMP`) | None | Gap | New `ThermalPort` proposal or fold into ObservabilityPort/ResourcePort. Yellow/Cap/Red thresholds and GPU-power-limit constant must move over |
| Thermal monitor (async loop) | `thermal/monitor.py` | None | Gap | Same |
| Power optimizer | `thermal/power_optimizer.py` | None | Gap | Same |
| Metrics collector | `thermal/metrics.py`, `telemetry/collector.py`, `/api/telemetry` | ObservabilityPort + otel_stack adapter | Partial | Merge telemetry surfaces; ObservabilityPort likely needs GPU-metric extension |

### 3.8 Frontend

| Tektos surface | Kosmos surface | Overlap | Migration axis |
|----------------|----------------|---------|----------------|
| Next.js 15.4 + React 19.1 frontend (`frontend/`), 40 panels, `AppShell` + `LeftRail`, Monaco editor, xterm terminal, D3 3D force graphs | Next.js 16.2.11 + React 19.2.4 frontend (`ui/`), pages `command/gnosis/govern/kernel/memory/observe/operate/tektos/zetesis`, cytoscape + react-force-graph, plus HTMX dashboard sub-app at `/tektos-ui` (ADR-045) | Overlap in stack, but the actual UIs are distinct products | Per parent's decision, **Kosmos shell hosts the Tektos UI as an iframe/microfrontend**. Requires the Tektos frontend to be reachable under kosmos-lms's origin (or served from the same origin via kernel sub-app mount). Panels overlap with existing Kosmos HTMX/`/tektos-ui` sub-app; policy decision needed on iframe-only vs. hybrid |
| `frontend-legacy/` older Next.js version | None | Overlap-with-self | Drop from kosmos-lms |
| Assistant-ui tool visualizers | None | Gap | Move over as-is inside the iframe payload |

### 3.9 Data services & deployment

| Tektos deployment element | Kosmos equivalent | Notes |
|---------------------------|-------------------|-------|
| systemd `tektos.target` with 5 unit files (backend :8020, gateway :8765, hindsight :9000, llm-hindsight :8095, frontend :5556) | Not shipped as systemd; Kosmos assumes local dev + kernel process | kosmos-lms will need a matching systemd unit set or an equivalent supervisor |
| `docker-compose.yml` + `Dockerfile` | Not present in Kosmos | Optional — decide which topology is authoritative |
| PostgreSQL 18 + pgvector 0.8.1 (Hindsight only) | Not required by Kosmos | Only pulled in if Hindsight is retained |
| Neo4j 7474/7687 | DozerDB adapter → 7687 (assumed) | Shared |
| Redis 6379 | Not required by Kosmos | Only if Tektos Redis-backed features move over |
| SearXNG :8888 | SearXNG adapter (uses same) | Shared |
| Hermes stack (LLM :8090/8092, embedder :8091, vision :8094, proxy :8093) | Kosmos LLMPort adapters (ollama, llama_swap) | Alternate provisioning path |
| Hindsight :9177 (Hermes sibling install) | None (documented as "do not use" in `docs/ports.md`) | Port-collision hazard with hindsight client default |

### 3.10 CI / license / discipline

| Concern | Tektos | Kosmos | Migration axis |
|---------|--------|--------|----------------|
| CI | `.github/workflows/ci.yml` — ruff + mypy + pytest + Next build + eslint + Playwright chromium | **Absent from repo** | Adopt Tektos CI as the kosmos-lms baseline; extend to Kosmos-side pytest + ports contract tests + Playwright against `ui/` |
| License | **No LICENSE file, no README license line** — public repo defaults to all-rights-reserved | MIT (per `PORTING_LEDGER.md` kernel entry) | **Blocker.** kosmos-lms cannot fork Tektos permissively until the author (rmholston420) adds a LICENSE. Trivial for the same author, but must happen before code moves |
| ADR discipline | Two conflicting ADR sources (`ADR-LEDGER.md` root vs. `adrs/README.md`), same IDs used for different decisions | 78 ADRs, single index, newer-wins rule | Discard Tektos ADR files; re-author Tektos-derived decisions as new Kosmos ADRs |
| PORTING_LEDGER discipline | Only tracks new additions; PlexClaw/Hermes/OpenHands lineage undocumented | Mandated statuses (`VENDORED · PATTERN-VENDORED · PLANNED · EVALUATED-REJECTED · SUPERSEDED`) | Every Tektos module ported into kosmos-lms needs a fresh PORTING_LEDGER entry with source URL, SHA/version, license, port(s), modifications, ADR |
| Log discipline | No BUILD_LOG / DEBUG_LOG / KNOWN_ISSUES / SESSION_HANDOFF quartet | Enforced quartet with append-only + search-first rules | kosmos-lms inherits Kosmos's log discipline; migration itself gets BUILD_LOG entries |
| Mypy strict | `strict=false` with 20+ `ignore_errors=true` overrides | Not verified (no CI file to compare) | Migration should target `strict=true` per Tektos module; align with Kosmos ruleset |
| Test count | 336 py + 28 Playwright | 1264 py + 10 Playwright (per last SESSION_HANDOFF) | Tektos test surface must move over and adapt to port-based fakes |

---

## 4. Integration risks and open questions

The parent will design the plan; this section flags risks the plan must address.

### 4.1 Hard blockers

1. **Tektos-Ultima has no LICENSE.** Public repo with no LICENSE file defaults to all-rights-reserved under US copyright + GitHub ToS. Even a self-fork by the same author is fine, but kosmos-lms cannot ship the code under Kosmos's implied MIT unless (a) the same GitHub user (rmholston420) adds a LICENSE to tektos-ultima before or during the fork, or (b) kosmos-lms explicitly re-licenses at the port-in point. Either way, the PORTING_LEDGER entries for every Tektos-derived module need an SPDX line — currently there is nothing to cite.

2. **ADR-007 (events-only cross-plugin coupling) forbids the pattern Tektos uses internally.** Tektos's `runtime/*` is deeply cross-coupled (planner_orchestrator imports agents, agents import runtime, immune imports everything). Inside a single `plugins/tektos` package this is legal (intra-plugin), but any Tektos capability that needs to reach across into Praxis / Phrouros / Zetesis / Gnosis must go through EventBusPort. The immune system in particular is written as an ambient in-process singleton — reintroducing it as a plugin subsystem while preserving its global visibility over other plugins is the sharpest ADR-007 conflict.

3. **Zero-trust MemoryPort writes require `provenance` + `confidence` on every write.** Every Tektos code path that persists — Hindsight `retain`, Skills insert, Experience replay, Reflection engine output, Session events, Schema evolution proposals, Dreamtime summaries — currently has no confidence field. Migration must inject sensible confidence values everywhere and choose a provenance taxonomy (`tektos_agent`, `tektos_reflection`, `tektos_skill`, `tektos_dreamtime`, `tektos_hindsight`, `tektos_planner`, etc.). Anything that fails to supply both fields will raise `MemoryWriteBlocked` at the port layer — non-bypassable.

### 4.2 Structural conflicts

4. **`plugins/tektos/` already exists in Kosmos with substantial code and 13 test files** including `test_stage_2_4_exit_gate.py` (683 LOC) and `test_stage_3_12_exit_gate.py` (528 LOC). This is not a green field. Any full rewrite must decide whether to (a) preserve the existing Kosmos plugin as the shell and layer Tektos-Ultima capabilities on top, (b) replace it wholesale and re-author every referenced ADR (ADR-036, ADR-037, ADR-038, ADR-041, ADR-042, ADR-044, ADR-045, ADR-046, ADR-063, ADR-065), or (c) fork Kosmos into kosmos-lms and start Tektos plugin from scratch. Each path has different disruption to the Stage 3 exit gate.

5. **Two conflicting ADR sources inside Tektos-Ultima** (`ADR-LEDGER.md` at root and `adrs/README.md`) use `ADR-004` and `ADR-005` for different decisions each. Neither survives migration untouched. All Tektos decisions must be re-numbered under Kosmos's continuous sequence (currently ADR-076 is the tail; the next open ID is ADR-077).

6. **Kosmos MemoryPort ↔ Tektos 4-tier memory system are mutually exclusive mental models.** Tektos partitions memory into sensory / working / long-term / procedural with different backends per tier (Redis, Postgres, Neo4j, files). Kosmos MemoryPort assumes one graph+temporal+policy plane. Reconciling the two is not a code migration; it is a design decision the parent must make (three feasible paths — see §3.2).

7. **Duplicate event bus.** Tektos ships `event_bus.py` (in-process, VSM-tagged). Kosmos ships `EventBusPort` envelope-first with `producer_plugin` and Valkey backing. Tektos code that publishes without an envelope must be rewritten; anything relying on the Tektos type-filter syntax (`prefix.*`) needs a compat layer.

8. **Duplicate repomap.** Kosmos `plugins/tektos/repomap/` (984 LOC, aider pattern) and Tektos `runtime/{repo_map,repo_map_generator,repo_memory}.py` + `repograph/core.py` implement the same idea twice. Diff scope unclear without file-level comparison.

9. **Duplicate eval / approvals / MCP / RAG.** Pier eval (Kosmos) vs. `runtime/evaluation_framework.py` + `external_evaluator.py` (Tektos). ApprovalGatewayPort/Praxis vs. `runtime/approval_registry.py`. MCPPort vs. `runtime/mcp_integration.py`+`mcp_server.py`. Zetesis vs. `runtime/{rag_engine,rag_retriever}.py`. Each duplicate is a keep/drop decision.

### 4.3 New Kosmos ports likely required

The following Tektos capabilities have no natural home under Kosmos's current 15-port surface and are strong candidates for new formal ports (each requires an ADR under `kosmos-adr-authoring`):

- **ImmunePort** — scan / respond / health, with the 12 detector classes as the reference detector set
- **LoopSafetyPort** (or fold into ImmunePort) — hard limits + repetition + circuit breaker
- **ThermalPort** — GPU/CPU thermal telemetry + PID actuation (may extend ObservabilityPort instead)
- **SandboxPort** — executable-code sandbox (bash + file + search), currently `providers/sandbox_provider.py`; could alternatively be a special MCP server
- **VoicePort / VisionPort** — voice STT/TTS and vision analysis; currently `/api/voice/*` and `/api/vision/*`
- **SelfModificationPort** — gated GUI/test/code expansion; must interlock with ApprovalGatewayPort and ImmunePort

### 4.4 Port-collision and topology risks

10. **Hindsight port default is wrong.** `HindsightConfig.base_url = "http://127.0.0.1:9177"` is the *Hermes sibling install* per `docs/ports.md`. Tektos systemd runs its own hindsight on `:9000`. If the singleton is constructed without a config override, all Tektos → Hindsight traffic hits the Hermes install (or fails). kosmos-lms must decide which port is canonical and fix the default.

11. **Tektos-Ultima assumes a Hermes ecosystem (`:8090` LLM, `:8091` embedder, `:8092` reserved, `:8093` proxy, `:8094` vision, `:8095` hindsight-LLM).** Kosmos LLMPort adapters expect Ollama (`:11434`) or llama-swap. Both cannot bind the same GPU simultaneously. Deployment topology decision required: (a) kosmos-lms adopts Hermes topology, (b) kosmos-lms adopts Kosmos-style Ollama, (c) both are supported through LLMPort adapters.

12. **`main.py` is a single-file 5800-line FastAPI monolith with ~154 endpoints.** Splitting it into port-consuming subsystems is a mechanical but non-trivial migration; every endpoint needs an owning subsystem, an authorization/tier decision, and either a kernel-route mount or a plugin-side sub-app under `/tektos-ui`. Roughly 25 endpoint families to categorize.

13. **`frontend-legacy/` ships alongside `frontend/`.** Historical divergence — kosmos-lms should not carry it forward.

### 4.5 Discipline and process risks

14. **Tektos PORTING_LEDGER covers only new deltas.** The provenance of PlexClaw, Hermes Agent, and OpenHands SDK patterns inside Tektos-Ultima is documented only informally in file headers ("Adapted from PlexClaw…", "Pattern-vendored from OpenHands…"). Backfilling PORTING_LEDGER entries for every ported Tektos module will require reading each header and mapping to source URL + SHA — several dozen entries.

15. **Tektos test suite depends on live services (whisper model, `edge-tts`, `mcp`, `aiogram`).** `pyproject.toml` mirrors `voice` and `mcp` deps into `dev` so `pip install -e .[dev]` exercises the full test suite — kosmos-lms CI must either match this posture or refactor tests to use port-based fakes (Kosmos style).

16. **Kosmos `SESSION_HANDOFF` reports Stage 1.6 Phase 2 COMPLETE and open question is "Stage 1.6 Phase 3 or Stage 1.7 next".** A concurrent full-fork migration would interrupt that in-flight sequencing; the parent's plan must decide whether kosmos-lms forks from a stable point (e.g. current `main`) and diverges, or Kosmos itself pauses.

### 4.6 Open questions for the parent

- **Iframe boundary policy:** does the Tektos frontend load at kosmos-lms's own origin (via kernel sub-app mount, ADR-045-style HTMX or full Next.js) or at a separate origin behind a proxy? Determines auth model, CSP, and cookie sharing.
- **Session identity:** does a Tektos session correspond 1:1 to a Kosmos session, or does Kosmos hold multiple concurrent Tektos sessions under one kernel? Affects state_machine merge design.
- **Approval model:** does every Tektos tool-call gate through ApprovalGatewayPort/Praxis, or only destructive ones? Affects DangerousCommandDetector wiring.
- **Immune system scope:** does the immune system defend only Tektos, or does it become a Kosmos-wide subsystem visible to Praxis/Phrouros/Zetesis/Gnosis? Determines whether ImmunePort is Kosmos-formal or Tektos-internal.
- **Self-modification mandate:** Tektos's raison d'être is self-improvement (`self_modification/`, schema evolution, skill improvement). Kosmos has no such mandate. Does kosmos-lms adopt it, and if so under what approval + ADR gating?
- **Hermes coupling:** does kosmos-lms retain the Hermes gateway JSON-RPC bridge (`gateway_proxy.py`), or drop it and expose the Kosmos event-bus WS only?
- **License:** will the author (rmholston420) add MIT (or another OSI-permissive) LICENSE to tektos-ultima before or during the port-in?

---

## 5. Files / paths quoted (evidence)

Line numbers are approximate and reflect the state of both clones at audit time.

### Kosmos evidence

- `Kosmos-Build-Spec-v25.md` — spec baseline, newer-wins rule
- `Kosmos-Build-Sequence-v25.md` — Stage 0–10 rollout
- `docs/adrs/README.md` — ADR-001…ADR-076 index (78 entries)
- `PORTING_LEDGER.md:1-100` — header + kernel + Stage 6.5 Zetesis wiring block (DozerDbMemoryAdapter WIRED, QdrantVectorAdapter WIRED, FilesystemDataAdapter WIRED, OllamaAdapter WIRED)
- `SESSION_HANDOFF.md:1-30` — Stage 1.6 Phase 2 complete, kernel 6.11.0 → 6.12.0
- `BUILD_LOG.md` — 186 append-only entries
- `KNOWN_ISSUES.md` — 94 lines
- `kernel/app.py:1-40` — Stage 6.5.9 boot sequence + `/api/phrouros/anomalies`, `/api/zetesis/research` (SSE ADR-060), `/api/events/ws` (ADR-061), `/api/approvals/{id}/{approve,reject}` (ADR-062), `POST /api/tektos/turn` (ADR-063), `/api/gnosis/{query,corpora,stats}` (ADR-064)
- `ports/memory.py:1-40` — DozerDB + Graphiti + AMG; `MEMORY_REQUIRED_FIELDS = frozenset({"provenance", "confidence"})`
- `ports/frontend_contract.py:1-60` — FrontendContractPort surface + `validate_plugin_descriptor`
- `ports/mcp.py:1-40` — Pattern-vendored MCP client, protocol `2024-11-05`
- `ports/event_bus.py:1-40` — Envelope-first + xrange-shaped read
- `ports/llm.py:1-30` — Keyword-only kwargs, model management, `is_healthy` non-throwing
- `plugins/tektos/plugin.py:1-60` — Stage 3.7 ADR-041 plugin bootstrap; APPROVALS_QUEUE panel at priority 90
- `plugins/tektos/agent.py:1-40` — `TektosAgent` ADR-036 pattern-vendored OpenHands; one iteration per turn; provenance `"tektos_agent"`
- `plugins/tektos/repomap/` — aider pattern, 984 LOC across `indexer/policy/rank/render/tags`
- `plugins/tektos/ingest/harness.py` — docling ingest ADR-044
- `plugins/tektos/eval/tasks/tektos-plan-execution-smoke/` — Pier eval seed task
- `plugins/tektos/ui/htmx.min.js` + `plugins/tektos/ui/{server,executor,templates,policy}.py` — ADR-045 HTMX dashboard
- `ui/package.json` — Next 16.2.11 + React 19.2.4

### Tektos-Ultima evidence

- `README.md:1-30` — Phases 1–5 overview, port list (8020, 5555, but systemd uses 5556)
- `SESSION_HANDOFF.md:1-80` — Phases 1–6 complete, Phase 7 (Kosmos plugin) deferred; 336 py + 28 Playwright tests
- `ADR-LEDGER.md:3` — ADR-005 Nervous System (2026-08-16)
- `ADR-LEDGER.md:58` — ADR-004 Metabolism Layer (2026-08-16)
- `adrs/README.md:1-49` — ADR-001…ADR-006 (SQLite, FastAPI, Next.js, Heroicons, Port Allocation, GPU Thermal) — **collision with root ADR-LEDGER on IDs 004 and 005**
- `PORTING_LEDGER.md` — Only tracks 2026-08-16 VS1/VS2 additions (telemetry, event bus, state machine, three panels)
- `pyproject.toml:1-140` — hatchling; extras `gpu/voice/mcp/dev`; mypy `strict=false` with ~20 module `ignore_errors`
- `src/tektos/main.py:1-16` — Header "Adapted from PlexClaw with all critical bug fixes"
- `src/tektos/main.py` — 154 `@app.` decorators enumerated across §2.3
- `src/tektos/tools/registry.py:1-30, 178-290, 553` — 7 built-in tools (`bash`, `file_read`, `file_write`, `file_delete`, `directory_list`, `directory_create`, `search`)
- `src/tektos/runtime/immune_system.py:1-40` — biology-to-VSM mapping; 12 detectors registered
- `src/tektos/runtime/immune_system.py:570-599` — SecretExposureDetector's 12 regex patterns
- `src/tektos/runtime/loop_safety.py:1-80` — 3-tier limits, `max_turns=15`, `max_tokens_total=65536`, `max_wall_time_seconds=300.0`, `repetition_window=3`, `repetition_threshold=2`
- `src/tektos/memory/hindsight_client.py:1-148` — Full client; `HindsightConfig` default port `9177` (Hermes sibling), Tektos systemd runs on `9000`
- `src/tektos/memory/memory_system.py:1-38` — 4-tier brain model + bicameral architecture
- `src/tektos/memory/neo4j_memory.py:1-40` — DozerDB via `bolt://localhost:7687`
- `src/tektos/gateway_proxy.py:1-80` — JSON-RPC 2.0 bridge for Hermes Desktop, `TEKTOS_BASE_URL=http://127.0.0.1:8020`, `TEKTOS_WS_URL=ws://127.0.0.1:8020`; assistant/tool/session event normalization
- `src/tektos/event_bus.py:1-50` — pub/sub with type filters (`exact | prefix.* | *`), synchronous delivery, VSM subscription defaults
- `src/tektos/state_machine.py` + `ADR-LEDGER.md:3-55` — FSM: `created → ready → running → ready|interrupted|failed`, `interrupted → ready`
- `src/tektos/thermal/regulator.py:1-50` — PID constants + NVML lazy import
- `src/tektos/thermal/monitor.py:1-50` — async regulation loop
- `src/tektos/plugin.py:1-30` — Built-in vs. Plugin vs. Skill taxonomy
- `docs/ports.md` — Complete port allocation table; explicit "no `0.0.0.0` without written reason" rule; sibling-install warning for `:9177`
- `deploy/systemd/user/tektos-backend.service` — `python -m tektos.main serve`, `KillMode=mixed`, `TimeoutStartSec=120`
- `deploy/systemd/user/tektos-gateway.service` — `python -m tektos.gateway_proxy --port 8765 --tektos-url http://127.0.0.1:8020`
- `deploy/systemd/user/tektos-hindsight.service` — `hindsight-api --port 9000`, `Requires=tektos-llm-hindsight.service`, `StartLimitBurst=3`
- `deploy/systemd/user/tektos-llm-hindsight.service` — `llama-server` with IBM Granite 4.0 H Tiny 7B-A1B Q4_K_M @ `:8095`, ctx 16384, `--parallel 2`
- `deploy/systemd/user/tektos-frontend.service` — `npm run start` on `:5556`
- `deploy/systemd/user/tektos.target` — `Wants=` all five, no cascade on single-service failure
- `.env.example:36-100` — Topology A (Hermes proxy `:8093`) vs. Topology B (direct llama-server `:8090`+`:8092`); `TEKTOS_PROMPT_TIMEOUT_SECONDS=120`; Hindsight LLM config
- `.github/workflows/ci.yml` — 6-job pipeline (ruff, mypy, pytest, next build, eslint, playwright chromium) + informational summary
- `frontend/package.json:1-80` — Next 15.4, React 19.1, Tailwind 4, Playwright 1.52, Monaco 0.52, xterm 6
- `frontend/src/components/panels/` — 40 panel components enumerated in §2.13

---

**End of report.**
