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
| **P — Preserved** | 76 (35 + T6 2 + T7 2 + T8a 24 + T8b-1 2 + T8b-2 1 + T8b-3 1 + T8b-4 1 + T8c-1 2 + T8c-2 1 + T8c-3 1 + T8c-4 2 + T8c-5 1 + T8c-6 1, 2026-09-26) | kernel/plugin referent exists and is live |
| **D — Deferred** | 70 + 2 WS | recorded path; functionality lost until the named port lands |
| **T — To-port** | 10 | no referent yet; each becomes a work item before deletion (T8 scope; orchestrator ×2 folded into T8c) |

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
| `GET /api/axioms` | **P (Stage 13.3, 2026-09-26)** — kernel (registry.tektos_axioms; bare 10-field list; ?category= filter; any failure → [] at 200 donor degrade). Substrate: donor `tektos/axioms.py` (262 LOC) verbatim → `kernel/axioms.py` (generic knowledge store → kernel-level per layering rule); Tektos axiom DATA (19 .axiom files) → `plugins/tektos/axioms/` passed as a directory, never imported (ADR-007). registry slot replaces donor `load_axioms()` singleton; KOSMOS_TEKTOS_AXIOMS_DIR override. Live-verified: 29 active axioms, wire fields locked, category filter 5 constraint / unknown → [] |
| `POST /api/axioms/{axiom_id}/verify` | **P (Stage 13.3, 2026-09-26)** — kernel (registry.tektos_axioms.verify, persisted to the .axiom data dir via _save); `{"ok": true, "id", "status": "verified"}` / unknown id → 404 `{"detail": "Axiom '<id>' not found"}` / subsystem absent → 404 same shape (donor had no uninitialized state — its singleton always existed, possibly empty). Live-verified: verify 200 + unknown 404 (live-verify flip restored to pristine donor data after the probe) |
| `GET /api/context/status` | **P (Stage 13.7, 2026-09-26)** — donor route over `registry.tektos_metabolism` (donor `tektos/metabolism.py` 572-LOC byte-verbatim → `kernel/metabolism.py`; generic resource-monitoring substrate → kernel per layering rule, no Tektos-specific data); donor wire: `status:"active"` + `context_budget`/`gpu`/`system`/`overall_health`, `not_initialized` when gate-off. Live-verified: active, overall critical (VRAM 90.9% with the 27B model resident). |
| `GET /api/contextCurator/status` | **P (Stage 13.8, 2026-09-26)** — donor `tektos/runtime/context_curator.py` (110 LOC, 100% stdlib) → `kernel/context_curator.py` byte-verbatim (generic context-window lifecycle substrate → kernel per layering rule); `registry.tektos_context_curator` booted at the composition root with donor values (main.py:1434: 256k, 0.75); donor's log-only `await start()` scheduled on the running loop (no state change); donor route wire verbatim (`initialized` + `get_compaction_stats()`, `not_initialized` gate-off at 200). Live-verified: initialized, should_compact false, full stats envelope; 3 tests. |
| — 13.2 substrate — | **P (Stage 13.2a, 2026-09-26).** Donor `db_manager.py` (1575 LOC, 100% stdlib) → `kernel/db_manager.py`; donor FULL schema-evolution engine `tektos/schema_evolution.py` (1644 LOC) → `kernel/schema_evolution_full.py` (distinct from the T8c-9 migrations engine). `registry.tektos_db` booted under `KOSMOS_TEKTOS_DB=on`, kernel-owned db at donor's canonical `data/tektos.db` (fresh file, no donor data carried). Donor self-import `from .schema_evolution import RelationshipDetector` fixed to absolute (documented divergence). The 19 routes below ride on this substrate. |
| `GET /api/db/analyze` | **P (Stage 13.2b, 2026-09-26)** — kernel /api/db/analyze (registry.tektos_db.analyze_all, donor wire verbatim) |
| `POST /api/db/backup` | **P (Stage 13.2e, 2026-09-26)** — kernel (registry.tektos_db.backup; {backup, path, size_bytes, tables, rows, checksum}; donor cartesian-join `rows` quirk preserved 1:1, reproduced standalone + live) |
| `GET /api/db/backups` | **P (Stage 13.2e, 2026-09-26)** — kernel (registry.tektos_db.list_backups; {"backups": [...]} shape locked) |
| `POST /api/db/dml` | **P (Stage 13.2d, 2026-09-26)** — kernel (registry.tektos_db.execute_dml; `{"rows_affected": n}`; UPDATE/DELETE without WHERE + require_confirmation=True → 400) |
| `POST /api/db/explain` | **P (Stage 13.2d, 2026-09-26)** — kernel (registry.tektos_db.explain_query; SELECT → `{plan, estimated_rows, uses_index}`; non-SELECT → 400) |
| `POST /api/db/export` | **P (Stage 13.2e, 2026-09-26)** — kernel (registry.tektos_db.export_table; json/csv; {"exported": true, path, format}; missing table → donor-500 preserved 1:1, live-confirmed) |
| `POST /api/db/import` | **P (Stage 13.2e, 2026-09-26)** — kernel (registry.tektos_db.import_table; json/csv; {"imported": true, rows}; unsupported format → 400; missing file → donor-500 (unhandled FileNotFoundError), live-confirmed) |
| `POST /api/db/indexes` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.create_index; existing index → `{"created": false}` 200 donor if-exists; bad table identifier → 400) |
| `DELETE /api/db/indexes/{index_name}` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.drop_index; missing index → `{"dropped": false}` 200) |
| `POST /api/db/optimize` | **P (Stage 13.2e, 2026-09-26)** — kernel (registry.tektos_db.optimize; {vacuum, analyze, tables_analyzed, total_rows, suggestions, normalization_issues, relationships_detected, ...}) |
| `POST /api/db/query` | **P (Stage 13.2d, 2026-09-26)** — kernel (registry.tektos_db.execute_query; non-SELECT → 400 donor ValueError; malformed/missing table → 500 donor unhandled sqlite3) |
| `POST /api/db/restore` | **P (Stage 13.2e, 2026-09-26)** — kernel (registry.tektos_db.restore; missing backup → 400 {"detail": "Backup not found: ..."}; donor-verbatim) |
| `GET /api/db/schema` | **P (Stage 13.2b, 2026-09-26)** — kernel /api/db/schema (registry.tektos_db.introspect, donor wire verbatim) |
| `POST /api/db/tables` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.create_table; bad name → 400; existing → `{"created": false}` 200 donor if-not-exists) |
| `DELETE /api/db/tables/{table_name}` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.drop_table; missing/malformed name → `{"dropped": false}` 200 — existence check precedes _safe_identifier, 400 path unreachable, live-confirmed) |
| `GET /api/db/tables/{table_name}/analyze` | **P (Stage 13.2b, 2026-09-26)** — kernel (registry.tektos_db.analyze_table; missing table → 404 donor ValueError) |
| `POST /api/db/tables/{table_name}/columns` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.add_column; existing column → `{"added": false}` 200) |
| `DELETE /api/db/tables/{table_name}/columns/{column_name}` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.drop_column; missing column → `{"dropped": false}` 200) |
| `PATCH /api/db/tables/{table_name}/columns/{old_name}/rename` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.rename_column; missing source table → 400) |
| `PATCH /api/db/tables/{table_name}/rename` | **P (Stage 13.2c, 2026-09-26)** — kernel (registry.tektos_db.rename_table; missing source → 400; bad new name → 400) |
| `GET /api/db/tables/{table_name}/sample` | **P (Stage 13.2b, 2026-09-26)** — kernel (registry.tektos_db.get_table_sample; bad identifier → 404 donor ValueError; missing well-formed table → 500 donor unhandled OperationalError, test-locked + live-confirmed) |
| `POST /api/db/transaction` | **P (Stage 13.2d, 2026-09-26)** — kernel (registry.tektos_db.execute_transaction). **DONOR LATENT BUG preserved 1:1**: donor takes a bare `BaseModel` body; pydantic 2.13 refuses to instantiate it → EVERY request 500s ("BaseModel cannot be instantiated directly"). Proven against live donor :8020 (same detail, fastapi 0.141.1 / pydantic 2.13.4) — route broken in both environments, same class as 13.1c placeholder-SQL bug. Test-locked (3 payload shapes) |
| `POST /api/hindsight/recall` | ADR-134 honest limit (kernel /api/memory/search-semantic is the read-side referent) |
| `POST /api/hindsight/reflect` | ADR-134 honest limit |
| `POST /api/hindsight/retain` | ADR-134 honest limit: kernel hindsight is read-side; retain/recall/reflect actions deferred |
| `GET /api/inference/metrics` | kernel /api/inference/status (partial); metrics surface deferred |
| `POST /api/mcp/connect` | Stage 13 (MCP) |
| `GET /api/mcp/status` | Stage 13 (MCP) |
| `GET /api/metabolism` | **P (Stage 13.7, 2026-09-26)** — donor route over `registry.tektos_metabolism` (booted at the composition root with a 3-arg→envelope publish adapter — ADR-007: substrate stays verbatim, event translation in app.py; `KOSMOS_TEKTOS_METABOLISM=on` default, no bus → None → gate-off degrade); donor wire: `assess_health().to_dict()` (timestamp/overall_health/gpu/system/context_budget/inference/latency counters). Gate-off → donor-verbatim `{"error": "Metabolism engine not initialized"}` at 200 (13.2e convention). Live-verified: overall critical (VRAM 90.9% — the 27B model resident), gpu temp 68.0, real nvidia-smi + /proc reads. |
| `GET /api/metabolism/context` | **P (Stage 13.7, 2026-09-26)** — donor route (`get_stats()`: max_tokens/current_tokens/token_pct/tool_calls/sessions/metrics_history_count). Live-verified: max_tokens 262144 (donor main.py:897 boot value), history count tracking. |
| `GET /api/metabolism/history` | **P (Stage 13.7, 2026-09-26)** — donor route (`get_metrics_history(limit=100)`; bounded deque of assess_health snapshots, maxlen 1000 donor-verbatim). Live-verified: ≥1 entry after an assess_health call, `?limit=` honored. |
| `GET /api/nervous-system/status` | **P (Stage 13.4, 2026-09-26)** — kernel route over two EXISTING kernel referents, no new substrate: donor's "nervous system" = event bus + session state machine; the kernel already owns `registry.event_bus` (boot slot, app.py:589) and the vendored FSM (`adapters/session/tektos/vendor/state_machine.py`, donor `state_machine.py` byte-verbatim — same `_states`/`_transitions_completed` surface; `State` is a `str, Enum` so `dict(sm._states)` serializes to state names, donor-identical wire). Donor path + 200-always wire verbatim (`{status:"active", event_bus, state_machine, total_sessions, states}`); unconditional `"active"` matches donor (a status surface, not a wiring report — NOT the T1 orchestrator deviation) |
| `GET /api/observability/status` | **P (Stage 13.5, 2026-09-26)** — kernel route; donor just reports two booleans (`_telemetry_collector` / `_auto_recovery` objects exist). Kernel referents: `telemetry` = ADR-138 ON-DEMAND sampler (`kernel.tektos_telemetry` / `GET /api/telemetry`) — no running collector daemon in the kernel, boolean reports sampler-module wired (true); `auto_recovery` = `registry.self_repair` (ADR-142 full donor self-repair engine — the auto-recovery supersession, boots unconditionally per ADR-141 R6). Donor field set preserved verbatim + one additive `note` making the daemon→kernel-mechanism mapping explicit (T1-orchestrator honest-degrade pattern; prevents a silently renamed boolean from misrepresenting). 200 always. Live-verified: `{status:"active", telemetry:true, auto_recovery:true, note:...}` |
| `GET /api/rag/status` | Stage 13 (RAG) |
| `GET /api/ragRetriever/status` | Stage 13 (RAG) |
| `GET /api/repoMap/status` | **P (Stage 13.9, 2026-09-26)** — donor `tektos/runtime/repo_map_generator.py` (135 LOC, 100% stdlib) → `kernel/repo_map_generator.py` byte-verbatim (generic repo-structure substrate → kernel per layering rule); `registry.tektos_repo_map` booted with the Kosmos repo root as `project_root` (donor main.py:1493 mapped the donor's own repo root — kernel-honest equivalent: map the repo the substrate lives in); the real `os.walk` scan scheduled on the running loop fire-and-forget as in the donor boot; donor route wire verbatim (`initialized` + get_stats(), `not_initialized` gate-off at 200). Live-verified: 962 entries (712 files, 250 dirs) over the Kosmos repo; 4 tests. |
| `POST /api/schema/apply` | **P (2026-09-26, Stage 13.1c)** — kernel-native (app.py, after propose), donor wire verbatim (main.py:3297): body → SchemaProposal → validate → only-if-valid `apply_proposal` (DDL + version bump + `_schema_evolution_log` row) → `{success, version}` / `{success:false, errors}`. Engine referent `registry.tektos_schema_evolution`; 503 when env-gated off. **Divergences:** (1) body table default "working" (donor "sessions"); (2) **donor latent bug preserved verbatim** — default body (no proposed_sql) executes literal "ALTER TABLE placeholder" → 500 (donor fallback is dead code; reproduced against donor's own engine+tektos.db); (3) donor behavior: route-built proposals store no rollback_sql, so `rollback_last()` returns False for them. Live-verified: explicit DDL applied + PRAGMA-confirmed, invalid table rejected, default body → 500.
| `GET /api/schema/patterns` | **P (2026-09-26, Stage 13.1a)** — kernel-native (app.py, after GET /api/schema). Engine referent `registry.tektos_schema_evolution` (T8c-9 verbatim port). Donor wire verbatim (main.py:3229): bare list of {field, table, percentage, confidence, suggested_type, pattern_type, example_values}; top_k param; {error, table} honest-degrade. Divergences: table default "working" (donor "sessions"); metadata_field default "metadata" (donor "payload" — T6 store's JSON col). Live-verified: seeded 3 rows → 4 patterns (repeated_metadata, retry_count→REAL).
| `POST /api/schema/propose` | **P (2026-09-26, Stage 13.1b)** — kernel-native (app.py, after patterns). Dry-run: FieldPattern → SchemaProposal → validate → {reason, proposed_sql, valid, errors} (main.py:3265), NO DDL executed. Engine referent `registry.tektos_schema_evolution`. Divergence: body table default "working" (donor "sessions"). Live-verified: propose on long_term → valid ALTER TABLE, column NOT added.
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
| `GET /api/thermal/health` | **P (Stage 13.6, 2026-09-26)** — kernel route over the ADR-121 ThermalWatchdog (the kernel's thermal referent; same class as the donor's ThermalMonitor). Donor `get_health_score()` bands (monitor.py:174) verbatim as `watchdog.get_health_score()` — pure temp→score map (None/0 → 1.0, <60→1.0 … ≥85→0.1). Gate-off → donor-verbatim `{"error": "Thermal monitor not initialized"}` at 200 (13.2e convention). Live-verified: 73°C → 0.7. |
| `POST /api/thermal/reset` | **P (Stage 13.6, 2026-09-26)** — kernel route; donor `reset()` (monitor.py:218, `regulator.reset()` → optimal) kernel-side equivalent: clear the SustainedCooldownRule at/above window + restore NOMINAL_POWER_CAP_W via `apply_cap` when cooldown is active. `watchdog.reset()` then returns the `:8020`-shaped `snapshot()`. Gate-off → same donor-verbatim error. Live-verified: `{"status":"reset", snapshot with real gpu temp}`. |
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
| `GET /api/config` | **P (2026-09-26, T8b-1)** — kernel-native: `tektos_config_get` (app.py) surfaces live lane (ADR-132 topology) + boot env rows; donor wire `protocol_version`/`llm`/`config`/`llm_available`; tests `tests/kernel/test_adr141_t8b1_config_surface.py` |
| `PATCH /api/config` | **P (2026-09-26, T8b-1)** — kernel-native: `tektos_config_patch`; donor wire `ok`/`key`/`value`/`note` preserved + honest `applied` flag (configured lanes not live-mutated — documented divergence) |
| `POST /api/delegate` | **P (2026-09-26, T8c-3)** — kernel-native: donor main.py:4065. Fresh sub-session via `registry.session.create_session` + `await registry.tektos_turn_loop.run_turn` (ADR-104 turn loop = kernel referent for the donor's `runtime_sdk.submit_prompt`); donor's verbatim GOAL/CONTEXT/WORKFLOW subagent prompt + donor system prompt; donor wire `{subagent_id, status: started, goal}`. Donor quirk preserved: request's session_id/timeout accepted but unused (fresh sub-session, turn awaited before reply). 5 tests; live :8000 → sub-session `ec041f3e` ran a real LLM turn, retrievable via /api/sessions |
| `GET /api/directory_list` | **P (2026-09-26, T8a)** — kernel-native (Stage 11.14 ADR-130, app.py:5293; test_stage_11_14_adr_130_directory_list.py) |
| `GET /api/dreamtime/history` | **P (2026-09-26, T8c-8b)** — kernel-native (app.py dreamtime block, after T6 memory actions). Donor main.py:2392, wire `{"dreams": [DreamResult]}` verbatim. Rides `registry.tektos_dreamtime` (donor DreamtimeEngine verbatim, T8c-8a → plugins/tektos/memory/dreamtime.py) booted over the T6 3-tier store (same KOSMOS_TEKTOS_MEMORY gate, same db). Degraded shape `{"error": "Dreamtime engine not initialized"}` @200 (donor's own fail shape) |
| `POST /api/dreamtime/run` | **P (2026-09-26, T8c-8b)** — kernel-native (donor main.py:2418). Full contemplation cycle: donor body `{max_memories=50, focus_area=None}`, donor wire `{id, source_count, insight_count, is_novel, novelty_score, insights, timestamp}` verbatim; insights persist back into the shared T6 store by novelty score. Live :8000: 3 seeded memories → 4 insights (2 connection, 1 synthesis, 1 gap), novelty 0.6, 4 rows persisted |
| `GET /api/dreamtime/summary` | **P (2026-09-26, T8c-8b)** — kernel-native (donor main.py:2365), `engine.get_summary()` verbatim (`{state, total_dreams, total_insights, recent_dreams[]}`) |
| `POST /api/dreamtime/trigger-skill-generation` | **Deferred (T8c-8c)** — donor main.py:2430 needs the donor SkillManager (skills/manager.py 830 LOC + skills/registry.py 777 LOC — a SQLite skill store). The kernel has no skill-store referent (only ADR-125 `/api/skills/stats` read surface); the kernel learning engine's `skill_creator` DI seam exists but is unpopulated. A follow-up skills ADR (skill-store port + `skill_creator` wiring) is the honest path; degraded shape would otherwise be fabricated |
| `POST /api/embedder/embed` | **P (2026-09-26, T7)** — kernel-native, donor shape (wired to registry.embeddings) |
| `GET /api/embedder/status` | **P (2026-09-26, T7)** — kernel-native, donor shape (wired to registry.embeddings) |
| `GET /api/evaluation/status` | **P (2026-09-26, T8c-6)** — kernel-native: donor main.py:4484. Substrate = donor `runtime/evaluation_framework.py` (417 LOC, self-contained, stdlib-only) verbatim port → `kernel/evaluation_framework.py` (generic benchmark/quality-measurement infra → kernel-level per layering rule). Route consumes `get_evaluation_harness()` exactly as the donor did (fresh call, module singleton). Donor wire `{status, total_evaluations, completed_evaluations, average_score}`; `{status: error, error}` at 200 (donor shape). 3 tests; live :8000 → `initialized`, 0 evals |
| `GET /api/hooks` | **P (2026-09-26, T8c-4)** — kernel-native: donor main.py:5101. Substrate = donor `runtime/hooks.py` (325 LOC, self-contained, stdlib-only) verbatim port → `kernel/hooks.py`; booted as `registry.hook_manager` (app.py, resource monitor = kernel thermal watchdog — lacks `check_thermal_limit`, so the donor's own hasattr guard skips the thermal builtins: 4 not 6). Donor wire `{hooks: [{event_type, handlers[]}]}`; `{error}` at 200 when off (donor shape). 8 tests; live :8000 → 4 builtin events listed |
| `POST /api/hooks/fire` | **P (2026-09-26, T8c-4)** — kernel-native: donor main.py:5117. Donor wire `{event_type, results: [{outcome, message, blocking, data}]}` verbatim; 422 missing event_type (donor pydantic), 503 system off, 500 fire failure; `stop_on_abort=False` (donor). Live :8000 → `tool.before` fire → `continue` |
| `GET /api/keys` | **P (2026-09-26, T8b-2)** — kernel-native: `tektos_list_api_keys` (app.py); donor wire `{keys: [{name,key,value,configured}]}` — KOSMOS_* secret set + DATABASE_URL/OPENAI_API_KEY, values masked (`••••••••`/`not configured`); test `tests/kernel/test_adr141_t8b2_keys_surface.py` |
| `POST /api/llm/probe` | **P (2026-09-26, T8b-3)** — kernel-native: `tektos_llm_probe` (app.py); donor wire `{llm_available, base_url, model}` over `registry.llm.is_healthy()` (ADR-132 FailoverLLMAdapter — real per-backend probe, engages fallback); test `tests/kernel/test_adr141_t8b3_llm_probe.py` |
| `POST /api/memory/decay` | **P (2026-09-26, T6)** — kernel-native, donor shape |
| `DELETE /api/memory/{tier}/{entry_id}` | **P (2026-09-26, T6)** — kernel-native, donor shape |
| `GET /api/multi-agent-orchestrator/agents` | **P (2026-09-26, T8c-1)** — kernel-native: `/tektos/api/orchestrator/agents` (plugins/tektos/orchestrator/api.py, ADR-141 T1 donor-fidelity port — `[{id, name, role, status, active_tasks}]` verbatim); UI re-pointed (panels/page.tsx AgentsTab); 7 tests (`test_adr141_t1_orchestrator_status_agents.py`); live :8000 → 200 |
| `GET /api/multi-agent-orchestrator/status` | **P (2026-09-26, T8c-1)** — kernel-native: `/tektos/api/orchestrator/status` (ADR-141 T1 donor-fidelity port — `{status, hierarchical_agent, long_running_agent, coding_executor}` booleans, honest degrade); live :8000 → 200 |
| `GET /api/planner/language-games` | **P (2026-09-26, T8a)** — kernel-native (ADR-141 T4, app.py:5821; test_adr141_t4_planner_surface.py) |
| `POST /api/planner/plan` | **P (2026-09-26, T8a)** — kernel-native (T4, app.py:5840) |
| `GET /api/planner/status` | **P (2026-09-26, T8a)** — kernel-native (T4, app.py:5877) |
| `GET /api/planner/templates` | **P (2026-09-26, T8a)** — kernel-native (T4, app.py:5806) |
| `POST /api/plugins/{name}/toggle` | **Deferred (2026-09-26, T8c-7)** — no honest kernel referent *today*. The donor toggled 4 swappable search-provider plugins (`tektos-ultima/plugins/{searxng,duckduckgo,farfalle,tavily}_plugin/`). The kernel has no runtime loadable-plugin loader — its `plugins/` packages are fixed composition-root subsystems (ADR-127) and its only wired search adapter is `adapters/search/searxng`. ADR-127's `GET /api/plugins` already reports the functional-plugin registry as "pending (follow-up ADR)". T8c-7 considered (a) a `registry.plugin_enabled` toggle flag and (b) a 4-subsystem manifest — both rejected: (a) is read by nothing (no-op = fabricated functionality); (b) duplicates ADR-127's committed `GET` and would report fixed subsystems as togglable. No functionality lost: kernel search works via the searxng adapter; only runtime-toggle-across-N-providers is deferred until the functional-registry follow-up ADR lands (out of ADR-141 gate scope — re-opening ADR-127's decision here would be scope creep). |
| `GET /api/routing/decide` | **P (2026-09-26, T8c-2)** — kernel-native: donor `src/tektos/routing.py` (396 LOC, generic multi-model routing) verbatim → `kernel/routing.py` substrate + `registry.model_router` boot slot (kernel primary-lane env, donor BALANCED/general profile) + `_decide_routing` thin surface (donor wire `{task, category, recommended_model, confidence, fallback_models, estimated_cost}` + honest `reason`). Documented divergence: donor route ALWAYS failed (wrong route() kwargs + .get() on dataclass → stuck 0.5-confidence fallback); kernel calls route() correctly (length→complexity 1-5, unknown category→MISC). 7 tests; live :8000 → `Selected qwen3.8-27b-code for refactoring (tier=fast)` |
| `GET /api/schedule` | **P (2026-09-26, T8c-5)** — kernel-native: donor main.py:5266. Donor defect fixed (T8c-2 class): donor built a FRESH `BackupScheduler()` per request (in-memory `backup_records` starts `[]`) → route ALWAYS returned `[]`. Kernel referent scans the REAL on-disk backup dir (`KOSMOS_BACKUP_DIR`, default `~/.tektos/backups`) for donor's own `{postgresql,redis,sqlite,neo4j}_{ts}.{ext}` artifacts → donor wire `[{id,name,type,status,last_run,next_run,interval,enabled}]`, newest first; `[]` degrade on failure (donor shape). 4 tests; live :8000 → 106 real backups |
| `GET /api/schema` | **P (2026-09-26, T8c-9)** — kernel-native (app.py, after dreamtime block). Composite referent, donor wire verbatim (main.py:4747): schema half → `registry.tektos_schema_evolution` (donor `SchemaEvolutionEngine` verbatim port → `kernel/schema_evolution.py`, 758 LOC; `escape_sql_identifier` helper inlined from donor `db_utils.py`); self_improvement half → `registry.tektos_learning` (ADR-143 T3, same method names). **DB divergence (documented):** donor introspected its event-store SQLite `data/tektos.db` (retired with main.py, ADR-137); the kernel runs the engine over the T6 memory store (`data/memory.db`, same `KOSMOS_TEKTOS_MEMORY` gate) — the kernel's only in-process SQLite file. Env-gated: returns the donor's own fail shape `{"error": "Schema evolution engine not initialized"}` (200) when the gate is off. The 3 action routes (patterns/propose/apply) stay D (Stage 13.1) — this engine is their substrate. Live-verified: 5 tables introspected, learning metrics populated. |
| `GET /api/search` | **P (2026-09-26, T8b-4)** — kernel-native: `tektos_search_sessions` (app.py) + `search_events_global` (kernel/tektos_replay.py): donor wire `{sessions: [{id, title, tag}], events: [{session_id, seq, type, payload, created_at}]}` — sessions via the T2c session port, events via cross-session substring search over the replay substrate (donor FTS5-fallback semantics); 4 tests; live :8000 (empty + `turn` probe → 200) |
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
     **T8b-1 (2026-09-26)** — config GET/PATCH kernel-native (donor
     main.py:5160/5232). GET surfaces the live lane (ADR-132 topology via
     registry.llm — model/base_url/lane, mirrors /api/llm/status) + boot env
     rows + masked sensitive keys, at the donor wire
     (`protocol_version`/`llm`/`config`/`llm_available`). PATCH preserves the
     donor wire (`ok`/`key`/`value`/`note`) with one documented divergence:
     an honest `applied` flag — configured lanes are read at boot and are NOT
     live-mutated (restart required), unconfigured env keys are written back
     for the next boot. 6 tests, all live against :8000. Full `tests/kernel/`
     586 passed.
     **T8b-2 (2026-09-26)** — `GET /api/keys` kernel-native (donor
     main.py:5328): donor wire `{keys:[{name,key,value,configured}]}` over the
     kernel's actual KOSMOS_* secret env set + DATABASE_URL/OPENAI_API_KEY;
     values masked, never plaintext. 1 test; live :8000 (DOZERDB configured →
     masked, rest `not configured`).
     **T8b-3 (2026-09-26)** — `POST /api/llm/probe` kernel-native (donor
     main.py:4590): donor wire `{llm_available, base_url, model}` over the
     existing `registry.llm.is_healthy()` — the ADR-132 FailoverLLMAdapter
     already runs the real per-backend probe and engages the fallback, so no
     new probe logic (layering rule). 3 tests; live :8000 (available=true,
     lane `qwen3.8-27b-code @ :8090` = /api/llm/status).
     **T8b-4 (2026-09-26)** — `GET /api/search` kernel-native (donor
     main.py:4203): donor wire `{sessions: [{id, title, tag}], events: [...]}`
     — sessions via the T2c session port (`registry.session.search_sessions`),
     events via new `kernel/tektos_replay.search_events_global` (cross-session
     substring search over the replay bus, donor FTS5-fallback semantics,
     donor row shape). 4 tests; live :8000 (empty + `turn` probe → 200).
     **T8b complete** — next: T8c (hooks, schedule, routing/decide, delegate,
     evaluation, plugins toggle, dreamtime).
     **T8c-1 (2026-09-26)** — orchestrator `/status` + `/agents` reconciled
     (T8a-style): both already kernel-native from ADR-141 T1 at
     `/tektos/api/orchestrator/{status,agents}` (donor-fidelity port,
     `test_adr141_t1_orchestrator_status_agents.py` 7 tests, live :8000 → 200,
     UI re-pointed). Counts P 68→70 / T 14→12. Remaining T8c: routing/decide,
     delegate, hooks ×2, schedule, evaluation, plugins toggle, dreamtime ×4,
     schema (10 rows).
     **T8c-2 (2026-09-26)** — `GET /api/routing/decide` kernel-native (donor
     main.py:5297): donor `routing.py` → `kernel/routing.py` substrate
     (verbatim, layering rule), router booted from primary-lane env, thin
     surface with donor wire + honest `reason`. Divergence (donor defect
     fixed): the donor route always hit its except-path (wrong kwargs +
     .get() on a dataclass) → 0.5-confidence fallback every time; kernel
     calls `route(task_category, complexity)` correctly. 7 tests; live :8000
     (`Selected qwen3.8-27b-code for refactoring (tier=fast)`). Remaining
     T8c: delegate, hooks ×2, schedule, evaluation, plugins toggle,
     dreamtime ×4, schema (11 rows).
     **T8c-3 (2026-09-26)** — `POST /api/delegate` kernel-native (donor
     main.py:4065): fresh sub-session + `await tektos_turn_loop.run_turn`
     (donor awaited `runtime_sdk.submit_prompt` — same semantics), donor
     verbatim subagent prompt, donor wire `{subagent_id, status, goal}`.
     Donor quirk preserved: request session_id/timeout unused. 5 tests;
     live :8000 (sub-session `ec041f3e` ran a real LLM turn). Remaining
     T8c: hooks ×2, schedule, evaluation, plugins toggle, dreamtime ×4,
     schema (10 rows).
     **T8c-4 (2026-09-26)** — hooks ×2 kernel-native (donor main.py:5101,
     :5117). Donor `runtime/hooks.py` (325 LOC, self-contained) verbatim
     port → `kernel/hooks.py`; `registry.hook_manager` booted in app.py
     after `model_router` with the kernel thermal watchdog as resource
     monitor (it lacks `check_thermal_limit`, so the donor's own hasattr
     guard registers 4 builtin events, not 6 — honest degrade, no fork).
     Wire verbatim: list `{hooks: [{event_type, handlers[]}]}` (+ `{error}`
     at 200 when off), fire `{event_type, results: [{outcome, message,
     blocking, data}]}` (422/503/500, `stop_on_abort=False`). 8 tests
     (`test_adr141_t8c4_hooks.py`, incl. thermal-guard activation with a
     monitor that DOES expose the method); live :8000 → 4 events listed,
     `tool.before` fire → `continue`. Remaining T8c: schedule, evaluation,
     plugins toggle, dreamtime ×4, schema (8 rows).
     **T8c-5 (2026-09-26)** — `GET /api/schedule` kernel-native (donor
     main.py:5266). Donor defect (T8c-2 class): fresh `BackupScheduler()`
     per request → always `[]`. Kernel scans the real backup dir
     (`KOSMOS_BACKUP_DIR`, default `~/.tektos/backups`) for donor's own
     `{postgresql,redis,sqlite,neo4j}_{ts}.{ext}` artifacts; donor wire
     `[{id,name,type,status,last_run,next_run,interval,enabled}]`, newest
     first; `[]` degrade (donor shape). 4 tests
     (`test_adr141_t8c5_schedule.py`); live :8000 → 106 real backups.
     Remaining T8c: evaluation, plugins toggle, dreamtime ×4, schema
     (7 rows).
     **T8c-6 (2026-09-26)** — `GET /api/evaluation/status` kernel-native
     (donor main.py:4484). Donor `runtime/evaluation_framework.py`
     (417 LOC, self-contained) verbatim port → `kernel/evaluation_framework.py`
     (kernel-level: generic benchmark/quality infra, layering rule). Route
     consumes `get_evaluation_harness()` as the donor did; donor wire
     verbatim + `{status: error}` at 200 degrade. `./evaluations/`
     (harness output dir, donor behavior) gitignored. 3 tests
     (`test_adr141_t8c6_evaluation_status.py`, incl. harness-state
     reflection + error degrade); live :8000 → `initialized`. Remaining
     T8c: plugins toggle, dreamtime ×4, schema (6 rows).
     **T8c-7 (2026-09-26)** — plugins toggle: **deferred, not ported**
     (no code committed — see the row at line 194). The donor's
     `GET /api/plugins` was already resolved (audit line 66) to the
     ADR-127 Stage 11.11 kernel endpoint (`app.py:5210` — 4 `plugins/`
     subsystems + frontend_contract descriptors, functional-registry gap
     marked "pending (follow-up ADR)"). The toggle's only honest referent
     is that future functional registry: the kernel's `plugins/` packages
     are fixed composition-root subsystems (no enable gate) and the only
     wired search adapter is searxng. A toggle flag read by nothing would
     be fabricated functionality; a 4-subsystem manifest would duplicate
     ADR-127's committed endpoint. Reverted the first-attempt code
     (duplicate shadowed GET + no-op toggle) before commit. Remaining
     T8c: dreamtime ×4, schema (5 rows).
     **T8c-8 (2026-09-26)** — dreamtime: **3 of 4 P (T8c-8a + T8c-8b),
     1 deferred (T8c-8c)**. T8c-8a: donor `DreamtimeEngine`
     (memory_system.py:735-993) + its models (MemoryTier/Hemisphere/
     MemoryEntry/DreamState/DreamResult) ported VERBATIM to
     `plugins/tektos/memory/dreamtime.py` (Tektos cognitive family, beside
     T6's persistence.py). Documented divergence: `DictMemoryStore`
     adapter implements exactly the 4 donor MemorySystem methods the
     engine touches over the T6 dict store (add_procedural_memory pops
     the `hemisphere` kwarg the verbatim engine passes — donor signature
     has no such param). 7 unit tests (FakeStore). T8c-8b: `registry.
     tektos_dreamtime` booted over the T6 3-tier store (same
     KOSMOS_TEKTOS_MEMORY gate, same db — one store, two consumers);
     3 routes at donor paths with donor wire verbatim (summary/history/
     run) + donor degraded shape `{"error": "Dreamtime engine not
     initialized"}` @200. Boot-ordering fix: T6 persistence slot now
     assigned immediately after its def (not batched) because `_try`
     executes boot fns at decoration time and the dreamtime boot reads
     the slot at ITS decoration time. 6 route tests. Live :8000: 3
     seeded memories → 4 insights (2 connection, 1 synthesis, 1 gap),
     novelty 0.6, insights persisted back into the shared SQLite store.
     T8c-8c (trigger-skill-generation) deferred — needs a skill-store
     referent (donor SkillManager 830 LOC + registry 777 LOC; kernel has
     none). Remaining T8c: schema, T8c-8c (1 row).
     **T8c-9 (2026-09-26)** — schema: **P**. Donor `SchemaEvolutionEngine`
     (migrations/schema_evolution.py, 758 LOC) ported VERBATIM to
     `kernel/schema_evolution.py` — layering rule: it's generic SQLite
     schema-introspection infra (not Tektos-policy-specific), so kernel-level;
     `escape_sql_identifier` helper inlined from donor `db_utils.py` (its only
     external dep). `registry.tektos_schema_evolution` booted over the T6
     memory store (same KOSMOS_TEKTOS_MEMORY gate, same db). Documented DB
     divergence: donor introspected its event-store SQLite `data/tektos.db`
     (retired with main.py, ADR-137) — the kernel's only in-process SQLite
     file is the T6 store. `GET /api/schema` at donor path, donor wire
     verbatim (main.py:4747): composite referent — schema half → the engine
     (get_schema/get_evolution_history/introspect/get_current_version),
     self_improvement half → `registry.tektos_learning` (ADR-143 T3, same
     method names; zero-shape when env-gated off). Donor degraded shape
     `{"error": "Schema evolution engine not initialized"}` @200 when the gate
     is off. The 3 action routes (patterns/propose/apply) stay D (Stage 13.1) —
     this engine is their substrate. 5 route tests. Live :8000: 5 tables
     introspected (working/long_term/procedural/transfer_log +
     _schema_evolution_log), learning metrics populated (10 experiences,
     velocity 0.778). Remaining T8c: T8c-8c (1 row).

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
