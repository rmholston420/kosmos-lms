# ADR-141: Tektos-Ultima functionality-preservation audit (route-by-route disposition)

- **Status:** Ratified (2026-09-25)
- **Scope:** Stage 11 exit gate (main.py deletion) — governing constraint enforcement
- **Supersedes:** ADR-139 "Run-repair trigger is retired" (reversed by user decision, see Decision 1)
- **Governing constraint (user, 2026-09-25, verbatim):** "Kosmos-LMS Tektos must not lose any of the functionality of Tektos-Ultima."

## Context

The Stage 11 exit gate requires deleting the standalone `main.py` and its :8020
service. The governing constraint converts that gate from "delete and accept the
residual" into a **functionality-preservation proof**: every donor route must map
to either (P) an existing kernel/plugin referent, (D) a recorded deferral with a
named port path, or (T) a to-port item with a committed work item. "Removed with
main.py" is an acceptable resolution only where the functionality is superseded by
an equivalent kernel mechanism.

### Audit method

- Donor inventory: regex over `tektos-ultima-v1/src/tektos/main.py` — **152 HTTP
  routes + 2 WebSocket routes** (`/ws/{session_id}`, `/ws/pty`).
- Referent inventory: all `@app.*` / `@router.*` routes across
  `kernel/*.py`, `plugins/**/*.py`, `adapters/**/*.py`, then **live-verified
  against the running kernel on :8000** (route exists in code AND is reachable —
  e.g. `GET /api/plugins` → 200; `/tektos/api/orchestrator/*` mounted but 503 when
  the bundle is not booted; other `build_*_router` plugins are defined but
  **not mounted** in `kernel/app.py` and are NOT counted as referents).
- Capability cross-check: for every "no referent" path, a function-level grep for
  the underlying capability in kernel/plugins/adapters, to distinguish "path
  renamed" from "functionality absent".

### Disposition counts (152 HTTP + 2 WS)

| Disposition | Count | Meaning |
|---|---|---|
| **P — Preserved** | 63 (35 + T6 2 + T7 2 + T8a 24, 2026-09-26) | kernel/plugin referent exists and is live |
| **D — Deferred** | 70 + 2 WS | recorded path; functionality lost until the named port lands |
| **T — To-port** | 19 | no referent yet; each becomes a work item before deletion (T8 scope; orchestrator ×2 folded into T8c) |

The deferral buckets are **honest temporary losses**, not permanent omissions:
every D route names the stage or ADR that carries its functionality. The Stage 11
exit gate cannot pass until every T route is P, and the plan's Stage 13 (subsystem
ports) + Stage 14 (deletion) sequence is the recorded path for the D routes.

## Route-by-route disposition

### Preserved — kernel/plugin referent exists (35 routes)

| Donor route (on :8020) | Disposition / referent |
|---|---|
| `GET /api/db` | kernel /api/db (ADR-137) — status only |
| `GET /api/hindsight/experiences` | kernel /api/hindsight/experiences (ADR-134) |
| `GET /api/hindsight/status` | kernel /api/hindsight/status (ADR-134) + data-services |
| `GET /api/immune/detectors` | kernel /api/immune/detectors (ADR-133) |
| `GET /api/immune/health` | kernel /api/immune/health (ADR-133) |
| `GET /api/immune/memory` | kernel /api/immune/memory (ADR-133) |
| `GET /api/immune/memory/entries` | kernel /api/immune/memory/entries (ADR-133) |
| `GET /api/immune/responses` | kernel /api/immune/responses (ADR-133) |
| `GET /api/immune/threats` | kernel /api/immune/threats (ADR-133) |
| `GET /api/inference/status` | kernel /api/inference/status |
| `GET /api/logs` | kernel /api/logs (ADR-129) |
| `GET /api/memory` | kernel /api/memory (ADR-135) |
| `GET /api/memory/stats` | kernel /api/memory/stats (ADR-135) |
| `GET /api/models` | kernel /api/models (ADR-132) |
| `GET /api/neo4j/status` | data-services /api/tektos/data-services/neo4j/status |
| `GET /api/plugins` | kernel /api/plugins (primary) |
| `GET /api/postgres/status` | data-services /api/tektos/data-services/postgres/status |
| `POST /api/prompt/sse` | kernel POST /api/prompt/sse (ADR-066 prompt SSE, kernel-native) |
| `GET /api/redis/status` | data-services /api/tektos/data-services/redis/status |
| `GET /api/self_repair/status` | kernel /api/self_repair/status (ADR-128) |
| `GET /api/sessions` | kernel /api/sessions |
| `POST /api/sessions` | kernel session create (primary) |
| `DELETE /api/sessions/{session_id}` | kernel session delete |
| `GET /api/sessions/{session_id}` | kernel /api/sessions/{session_id} |
| `PATCH /api/sessions/{session_id}` | kernel session patch |
| `POST /api/sessions/{session_id}/archive` | kernel archive (referent) |
| `POST /api/sessions/{session_id}/fork` | kernel session fork |
| `POST /api/sessions/{session_id}/interrupt` | kernel session interrupt |
| `POST /api/sessions/{session_id}/model` | kernel session model switch |
| `GET /api/sessions/{session_id}/replay` | kernel session replay (ADR-133) |
| `GET /api/skills/stats` | kernel /api/skills/stats (ADR-136) |
| `GET /api/telemetry` | kernel /api/telemetry (ADR-138) |
| `GET /api/thermal/status` | kernel /api/thermal/status (ADR-121) |
| `GET /api/tools` | kernel /api/tools (ADR-136) |
| `GET /health` | kernel /health (kernel-native) |

### Deferred — recorded path (70 routes)

| Donor route (on :8020) | Disposition / referent |
|---|---|
| `GET /api/axioms` | Stage 13 subsystem (axioms) |
| `POST /api/axioms/{axiom_id}/verify` | Stage 13 subsystem (axioms) |
| `GET /api/context/status` | Stage 13 (context subsystem) |
| `GET /api/contextCurator/status` | Stage 13 (context curator) |
| `GET /api/db/analyze` | Stage 13.2 db_manager |
| `POST /api/db/backup` | Stage 13.2 db_manager |
| `GET /api/db/backups` | Stage 13.2 db_manager |
| `POST /api/db/dml` | Stage 13.2 db_manager |
| `POST /api/db/explain` | Stage 13.2 db_manager |
| `POST /api/db/export` | Stage 13.2 db_manager |
| `POST /api/db/import` | Stage 13.2 db_manager |
| `POST /api/db/indexes` | Stage 13.2 db_manager |
| `DELETE /api/db/indexes/{index_name}` | Stage 13.2 db_manager |
| `POST /api/db/optimize` | Stage 13.2 db_manager |
| `POST /api/db/query` | Stage 13.2 db_manager |
| `POST /api/db/restore` | Stage 13.2 db_manager |
| `GET /api/db/schema` | Stage 13.2 db_manager |
| `POST /api/db/tables` | Stage 13.2 db_manager |
| `DELETE /api/db/tables/{table_name}` | Stage 13.2 db_manager |
| `GET /api/db/tables/{table_name}/analyze` | Stage 13.2 db_manager |
| `POST /api/db/tables/{table_name}/columns` | Stage 13.2 db_manager |
| `DELETE /api/db/tables/{table_name}/columns/{column_name}` | Stage 13.2 db_manager |
| `PATCH /api/db/tables/{table_name}/columns/{old_name}/rename` | Stage 13.2 db_manager |
| `PATCH /api/db/tables/{table_name}/rename` | Stage 13.2 db_manager |
| `GET /api/db/tables/{table_name}/sample` | Stage 13.2 db_manager |
| `POST /api/db/transaction` | Stage 13.2 db_manager |
| `POST /api/hindsight/recall` | ADR-134 honest limit (kernel /api/memory/search-semantic is the read-side referent) |
| `POST /api/hindsight/reflect` | ADR-134 honest limit |
| `POST /api/hindsight/retain` | ADR-134 honest limit: kernel hindsight is read-side; retain/recall/reflect actions deferred |
| `GET /api/inference/metrics` | kernel /api/inference/status (partial); metrics surface deferred |
| `POST /api/mcp/connect` | Stage 13 (MCP) |
| `GET /api/mcp/status` | Stage 13 (MCP) |
| `GET /api/metabolism` | Stage 13 (metabolism) |
| `GET /api/metabolism/context` | Stage 13 (metabolism) |
| `GET /api/metabolism/history` | Stage 13 (metabolism) |
| `GET /api/nervous-system/status` | Stage 13 (nervous-system) |
| `GET /api/observability/status` | Stage 13 (observability) |
| `GET /api/rag/status` | Stage 13 (RAG) |
| `GET /api/ragRetriever/status` | Stage 13 (RAG) |
| `GET /api/repoMap/status` | Stage 13 (repo map) |
| `POST /api/schema/apply` | Stage 13.1 schema_evolution |
| `GET /api/schema/patterns` | Stage 13.1 schema_evolution |
| `POST /api/schema/propose` | Stage 13.1 schema_evolution |
| `POST /api/self_repair/health` | part of full self-repair daemon port |
| `GET /api/self_repair/history` | ADR-139 split; user 2026-09-25: port full daemon (see ADR-141 decision) |
| `POST /api/self_repair/repair` | ADR-139: trigger; user 2026-09-25 decision = FULL port (supersedes 'retired') |
| `GET /api/skills` | ADR-108 D9: donor skills manager (830 LOC) ratified deferral |
| `POST /api/skills` | ADR-108 D9 |
| `POST /api/skills/dedup` | ADR-108 D9 |
| `GET /api/skills/dedup/groups` | ADR-108 D9 |
| `POST /api/skills/maintenance` | ADR-108 D9 |
| `GET /api/skills/search` | ADR-108 D9 |
| `POST /api/skills/select` | ADR-108 D9 |
| `DELETE /api/skills/{skill_id}` | ADR-108 D9 |
| `GET /api/skills/{skill_id}` | ADR-108 D9 |
| `PUT /api/skills/{skill_id}` | ADR-108 D9 |
| `POST /api/skills/{skill_id}/execute` | ADR-108 D9 |
| `POST /api/skills/{skill_id}/improve` | ADR-108 D9 |
| `POST /api/skills/{skill_id}/improve/from-execution` | ADR-108 D9 |
| `POST /api/skills/{skill_id}/prune` | ADR-108 D9 |
| `POST /api/skills/{skill_id}/toggle` | ADR-108 D9 |
| `GET /api/thermal/health` | Stage 13 thermal subsystem; kernel has /api/thermal/status (ADR-121) — health/reset action surface rides with it |
| `POST /api/thermal/reset` | Stage 13 thermal subsystem |
| `GET /api/toolRouter/status` | kernel tool_router router (executor/api.py) — status surface unverified |
| `POST /api/vision/analyze` | Stage 13.7 (vision :8094) |
| `POST /api/vision/analyze-url` | Stage 13.7 (vision :8094) |
| `GET /api/vision/status` | Stage 13.7 (vision :8094) |
| `GET /api/voice/state` | Stage 13.7 (voice) |
| `POST /api/voice/stt` | Stage 13.7 (voice) |
| `POST /api/voice/tts` | Stage 13.7 (voice) |

### To-port — no referent yet (47 routes at audit time; 23 remain — 24 reconciled to P in T8a, 2026-09-26)

| Donor route (on :8020) | Disposition / referent |
|---|---|
| `GET /api/archive/sessions` | **P (2026-09-26, T8a)** — kernel-native (ADR-141 T2c — registry.session ADR-103 port, app.py:5625; test_adr141_t2_session_surfaces.py) |
| `GET /api/archive/sessions/{session_id}` | **P (2026-09-26, T8a)** — kernel-native (T2c, app.py:5644) |
| `GET /api/archive/sessions/{session_id}/messages` | **P (2026-09-26, T8a)** — kernel-native (T2c, app.py:5670) |
| `POST /api/archive/sessions/{session_id}/rename` | **P (2026-09-26, T8a)** — kernel-native (T2c, app.py:5682) |
| `POST /api/archive/sessions/{session_id}/tag` | **P (2026-09-26, T8a)** — kernel-native (T2c, app.py:5697) |
| `GET /api/config` | no referent — config read |
| `PATCH /api/config` | no referent — config write |
| `POST /api/delegate` | no referent — delegate action (kernel has delegation via subagents, no HTTP surface) |
| `GET /api/directory_list` | **P (2026-09-26, T8a)** — kernel-native (Stage 11.14 ADR-130, app.py:5293; test_stage_11_14_adr_130_directory_list.py) |
| `GET /api/dreamtime/history` | no referent |
| `POST /api/dreamtime/run` | no referent |
| `GET /api/dreamtime/summary` | no referent — dreamtime read |
| `POST /api/dreamtime/trigger-skill-generation` | no referent |
| `POST /api/embedder/embed` | **P (2026-09-26, T7)** — kernel-native, donor shape (wired to registry.embeddings) |
| `GET /api/embedder/status` | **P (2026-09-26, T7)** — kernel-native, donor shape (wired to registry.embeddings) |
| `GET /api/evaluation/status` | no referent — evaluation harness status |
| `GET /api/hooks` | no referent — hooks list |
| `POST /api/hooks/fire` | no referent — hooks fire |
| `GET /api/keys` | no referent — keys list |
| `POST /api/llm/probe` | no referent — LLM probe action |
| `POST /api/memory/decay` | **P (2026-09-26, T6)** — kernel-native, donor shape |
| `DELETE /api/memory/{tier}/{entry_id}` | **P (2026-09-26, T6)** — kernel-native, donor shape |
| `GET /api/multi-agent-orchestrator/agents` | TO-PORT (T8c): engine.agents roster dict exists (ADR-114), /agents route missing |
| `GET /api/multi-agent-orchestrator/status` | TO-PORT (T8c): engine + bundle exist (ADR-114), /stats present, /status route missing |
| `GET /api/planner/language-games` | **P (2026-09-26, T8a)** — kernel-native (ADR-141 T4, app.py:5821; test_adr141_t4_planner_surface.py) |
| `POST /api/planner/plan` | **P (2026-09-26, T8a)** — kernel-native (T4, app.py:5840) |
| `GET /api/planner/status` | **P (2026-09-26, T8a)** — kernel-native (T4, app.py:5877) |
| `GET /api/planner/templates` | **P (2026-09-26, T8a)** — kernel-native (T4, app.py:5806) |
| `POST /api/plugins/{name}/toggle` | no referent — plugin toggle |
| `GET /api/routing/decide` | no referent — routing decision |
| `GET /api/schedule` | no referent — schedule read |
| `GET /api/schema` | no referent — schema read (kernel has /api/kernel/schema, different surface) |
| `GET /api/search` | no referent — search (kernel has /api/memory/search-semantic + zetesis) |
| `POST /api/self_improvement/enqueue` | **P (2026-09-26, T8a)** — kernel-native (ADR-143 S5, app.py:5033; test_adr143_s5_self_improve_routes.py) |
| `GET /api/self_improvement/experiences` | **P (2026-09-26, T8a)** — kernel-native (ADR-143 S5, app.py:5007) |
| `GET /api/self_improvement/metrics` | **P (2026-09-26, T8a)** — kernel-native (ADR-143 S5, app.py:4994) |
| `GET /api/self_improvement/report` | **P (2026-09-26, T8a)** — kernel-native (ADR-143 S5, app.py:5021) |
| `GET /api/self_improvement/status` | **P (2026-09-26, T8a)** — kernel-native (ADR-143 S5, app.py:5062) |
| `GET /api/sessions/{session_id}/events` | **P (2026-09-26, T8a)** — kernel-native (ADR-141 T2b — tektos_replay.get_events, app.py:5735; WS parity is ADR-140) |
| `GET /api/state/{session_id}` | **P (2026-09-26, T8a)** — kernel-native (ADR-141 T2a — kernel/session_state.py, app.py:5141) |
| `POST /api/state/{session_id}/save` | **P (2026-09-26, T8a)** — kernel-native (T2a, app.py:5169) |
| `POST /api/state/{session_id}/snapshot` | **P (2026-09-26, T8a)** — kernel-native (T2a, app.py:5222) |
| `POST /api/tools/register` | **P (2026-09-26, T8a)** — kernel-native (ADR-141 T5, app.py:4597; honest 501 — in-process registration only; test_adr141_t5_tools_surface.py) |
| `GET /api/tools/schema` | **P (2026-09-26, T8a)** — kernel-native (T5, app.py:4581) |
| `POST /api/tools/{tool_name}/disable` | **P (2026-09-26, T8a)** — kernel-native (T5, app.py:4633) |
| `POST /api/tools/{tool_name}/enable` | **P (2026-09-26, T8a)** — kernel-native (T5, app.py:4621) |
| `POST /api/tools/{tool_name}/execute` | **P (2026-09-26, T8a)** — kernel-native (T5, app.py:4651) |

## WebSocket disposition (2 routes)

| Donor route | Disposition |
|---|---|
| `WS /ws/{session_id}` | **D** — ADR-140: deferred to the deletion gate; parity-via-bus (`/api/events/ws` ADR-061 + prompt event publishing) or documented SSE-sufficient |
| `WS /ws/pty` | **D** — Stage 13 sandbox work (PTY is a sandbox-surface concern) |

## Decisions

1. **Self-repair: FULL donor port (supersedes ADR-139's "trigger is retired").**
   The donor self-repair subsystem is a 2,465-LOC package
   (`tektos-ultima-v1/src/tektos/self_repair/`: engine 466 LOC, strategies 723,
   health_monitor 261, workflows 470, models 245, effectiveness 233) with 8 builtin
   strategy classes (ResourceExhaustion, ContextOverflow, LoopDetection,
   PromptInjection, InfrastructureFailure, PerformanceDegradation, SelfDegradation,
   GuardrailViolation) plus `RepairStrategyRegistry`. The user directed (2026-09-25):
   port it with **FULL donor execution semantics** (no ADR-090 human-approval gate),
   accepting the architectural tension with the kernel's propose-only ADR-128.
   Resolution: land it as `plugins/tektos/self_repair/` — a plugin subsystem,
   env-gated (`KOSMOS_TEKTOS_SELF_REPAIR=on`), with the daemon loop (start/stop,
   `_monitoring_loop`, `repair_threat`, `manual_health_check`, history) executing
   in-process. The ADR-128 kernel `/api/self_repair/status` endpoint becomes a
   **bridge** to the ported engine's `get_status()` rather than the static
   propose-only envelope, so the ops tab and the daemon share one source of truth.
   This is the single largest preservation item in the audit.

2. **T-bucket ordering for pre-deletion work** (highest functional value first,
   smallest first within a tier):
   - **T1 — orchestrator `/status` + `/agents`** (2 routes): engine + `agents`
     roster dict already exist (ADR-114); two small routes on the mounted
     `build_orchestrator_router`. Smallest possible first port. **P (2026-09-25, `7395319`)** — donor-fidelity routes on `/tektos/api/orchestrator/{status,agents}`, AgentsTab re-pointed, 7 tests green + live-verified on :8000.
   - **T2 — session-adjacent surfaces**: `state/{session_id}` read/save/snapshot
     (3), `sessions/{session_id}/events` (1, pairs with ADR-140 WS parity),
     `archive/*` (5). **P (2026-09-25, `2fc7973` + `80ff592`)** — all 9
     routes kernel-native: T2a `kernel/session_state.py` (donor `SessionState`
     + `SessionStateManager` port with the per-session file fix — donor keyed
     every session at one shared path) + 3 state routes; T2b
     `tektos_replay.get_events` (filtered view over the same bus read as
     `/replay`) + `/api/sessions/{sid}/events` (since_seq/limit/event_type,
     donor `event_store.get_events` semantics); T2c `/api/archive/*`
     (list/detail/messages/rename/tag) on `registry.session`. 15 wire-shape
     tests green; full `tests/kernel/` 533 passed.
   - **T3 — self-improvement read surface** (5 routes: status/metrics/report/
     experiences/enqueue) — pairs with the ADR-134 hindsight read-side. **P (2026-09-25, ADR-143)** — all 5 routes kernel-native on `registry.tektos_self_improve`/`registry.tektos_learning`; donor + UI wire-compatible.
   - **T4 — planner surface** (4: templates/status/plan/language-games) — the
     `build_spec_planner_router` exists unmounted; mounting + missing routes.
     **P (2026-09-25, `9fcc1df`)** — all 4 routes kernel-native at the donor paths: T4a
     `POST /api/planner/plan` + `GET /api/planner/templates` + `GET
     /api/planner/language-games` over the donor `Planner` pipeline ported to
     `plugins/tektos/planner/pipeline.py` (the five leaf stages already
     existed from Stage 8.4); T4b `GET /api/planner/status` over the
     `PlannerOrchestrator` elevated to `kernel/plan_tracker.py`. Donor
     `model_dump()` wire verified field-for-field equal to the kernel
     serializer; 13 wire tests green; full `tests/kernel/` 546 passed. The
     SDK task-start plan hook (donor `sdk.py:889`, `plan.*` WS broadcast)
     rides with ADR-140.
   - **T5 — tool management surface** (5: register/schema/enable/disable/execute)
     — pairs with the ADR-136 tools read-side. **P (2026-09-25)** — all 5
     routes kernel-native at the donor paths (main.py:2843-2935): the
     registry SUBSTRATE (donor `ToolRegistry` + `ToolDefinition`,
     register/get/list/execute/schema + `tool.*` events) elevated to
     `kernel/tool_registry.py` (T5a — generic infrastructure); the
     coding-agent toolset (donor `SandboxProvider` 7 built-in tool handlers)
     ported to `plugins/tektos/tools/sandbox_provider.py` (T5b) + the 7
     `ToolDefinition`s in `plugins/tektos/tools/builtin_defs.py` (T5c),
     injected at boot in `kernel/app.py` (T5d, composition root, ADR-007).
     Donor parity: `POST /register` is the donor's 501 stub (HTTP tool
     registration refused); execute/enable/disable wires byte-identical to
     donor; 13/13 live donor-vs-kernel registry diffs (separate tmp
     sandboxes, roots normalized) + live :8000 smoke (all 5 routes, bash
     disable/enable round-trip, file_write→search round-trip). 20 tests;
     full `tests/kernel/` 566 passed. Donor Terminal-Bench Docker proxying
     + web/rag/delegate handlers are separate subsystems (out of T5 scope).
   - **T6 — memory actions** (2: decay, entry delete) — pairs with ADR-135.
     **P (2026-09-26)** — donor `MemoryPersistence` (3-tier cognitive store:
     working/long_term/procedural + transfer log + decay scheduler) ported
     donor-verbatim to `plugins/tektos/memory/persistence.py` (T6a,
     `e579fa2`; 14 tests + donor-vs-kernel behavioral parity CLEAN across
     all tiers/search/transfer/log/stats/import-export — only diff is the
     `created_at` wall-clock, a known false positive). T6b: the 2 donor
     routes (main.py:2324-2349) at the donor paths in `kernel/app.py` —
     `POST /api/memory/decay` (per-tier counts, long/proc always 0) and
     `DELETE /api/memory/{tier}/{entry_id}` (`{"deleted": bool}`, 400
     unknown tier, `{"error": ...}` degraded at 200 — all donor shapes);
     boot gate `KOSMOS_TEKTOS_MEMORY=on` (donor booted unconditionally at
     120 s decay; env default `off` so the gate stays honest) + registry
     slot + shutdown stop/close. 7 route tests (full-lifespan boot proves
     the real gate path). The ops-tab decay button is now live (was the
     ADR-135 honest degrade). Full `tests/kernel/` 573 passed.
   - **T7 — embedder surface** (2: status :8091, embed) — pairs with the ADR-132
     LLM lanes. **P (2026-09-26)** — NOT a second `EmbedderClient` port:
     per the governing layering rule the embedder is generic shared
     infrastructure the kernel already owns as `registry.embeddings`
     (`LlamaEmbeddingsAdapter`, ADR-124 D1 — same :8091, same
     qwen3-embedding-0.6b, same OpenAI-compat `/v1/embeddings`). The two
     donor routes (`main.py:4448/4464`) are a thin Tektos surface over that
     substrate at the donor paths with donor response shapes. One real gap
     closed cleanly: the donor's `usage` field, which the ADR-073 batch
     contract (`embed`) deliberately discards, now surfaces via a new
     non-breaking `embed_meta()` on the adapter (shared HTTP round-trip
     path, `EmbeddingMeta` pydantic model). 7 route tests, all live against
     the real :8091 llama-server embedder (no mocks). Full `tests/kernel/`
     580 passed.
   - **T8 — misc singletons**: config GET/PATCH, keys, hooks list/fire, schedule,
     search, routing/decide, delegate, llm/probe, evaluation/status,
     plugins/{name}/toggle, schema GET, dreamtime (4).
     **T8a (2026-09-26)** — table reconciliation, no code: re-verifying the
     audit-time to-port list against the live kernel (2026-09-26, :8000) found
     24 of the 47 rows **already kernel-native** — the "no referent" marks
     predate the T2/T4/T5, ADR-130 and ADR-143 S5 slices that landed since the
     audit. Each was live-probed (GETs + safe error-path POSTs) and carries an
     existing test file: archive/sessions ×5 (T2c), state ×3 (T2a,
     kernel/session_state.py), sessions/{id}/events (T2b,
     tektos_replay.get_events), planner ×4 (T4), self_improvement ×5 (ADR-143
     S5), tools ×5 (T5), directory_list (ADR-130). Rows → **P (T8a)**; counts
     P 39→63, T 43→19 (orchestrator ×2 folded into T8c). The 19 genuinely
     missing routes split into sub-slices by referent substrate: **T8b** —
     thin surfaces over existing kernel substrate (config GET/PATCH, keys,
     llm/probe over registry.llm, search over the T2c session search);
     **T8c** — missing routes over existing engines (routing/decide, delegate,
     orchestrator status/agents, plugins/{name}/toggle); **T8d** — substrate
     ports where none exists (hooks list/fire, schedule over the donor
     BackupScheduler, evaluation/status, schema GET, dreamtime ×4).

3. **D-bucket ports ride the plan's Stage 13** in its own order
   (13.1 schema_evolution → 13.2 db_manager → … → 13.7 voice), each with its own
   ADR + tests + live verify, consistent with the per-stage convention.

4. **Gate definition.** `main.py` may be deleted when: (a) every T route is P
   (referent live-verified on :8000); (b) the self-repair daemon (Decision 1) is
   ported and running; (c) the ADR-139 split resolves — history reads the ported
   engine's `get_repair_history()`, the repair trigger reads its
   `repair_threat()`; (d) the ADR-140 WS decision executes; (e) the page-level
   `/health` upstream probe and "upstream down" banner are removed; (f) the
   ADR-109 gateway module is deleted and :8020 is retired. D routes may remain at
   deletion only if their named Stage 13 port has already landed; otherwise they
   gate the deletion too.

## Consequences

- The Stage 11 "exit gate" is now a **152-route checklist**, not a single file
  deletion. This ADR is that checklist; each T item flips to P with a commit.
- ADR-139's "trigger retired" and "history → honest empty state" are superseded by
  Decision 1 (full port). ADR-139 gains a STATUS AMENDMENT block.
- The `tektos-ultima-v1` donor tree stays read-only reference material until the
  gate passes; it is NOT deleted at Stage 14 until every D route's port is green.

## Verification (live, 2026-09-25)

- `GET /api/plugins` on :8000 → **200** (kernel-native, P-confirmed).
- `GET /tektos/api/orchestrator/stats` on :8000 → **503** (router mounted; bundle
  not booted in this instance — confirms the mount exists, route absent = T1).
- All other `build_*_router` plugin surfaces (manager/planner/experience/
  reflection/synthesis/decomposer/executor/tool-router) → **404**: defined in
  `plugins/tektos/*/api.py` but **not mounted** in `kernel/app.py`. Not counted as
  referents.
- Data-services router (ADR-118) live: neo4j/postgres/redis/hindsight/qdrant
  status all → 200.
