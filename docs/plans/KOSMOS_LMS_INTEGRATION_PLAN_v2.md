# Kosmos-LMS Integration Plan v2

**Version:** 2 (2026-09-10 rewrite)
**Supersedes:** `KOSMOS_LMS_INTEGRATION_PLAN.md` (v1, 2026-09-10 morning) — v1 preserved as historical reference; v2 is the authoritative plan going forward.
**Anchor commit:** `e932a02` (Stage 7.4+2 landed)
**Baseline test suite:** 1462 passed / 0 failed / 15 skipped
**Author:** Perplexity agent (informed optimal choices per user standing preference)
**User confirmations (2026-09-10 04:40 EDT):**
- Tektos-Ultima is the most important part of kosmos-lms → runtime port-in prioritized
- Fidelity port (copy donor verbatim, rewrite import boundaries only)
- Postgres kept in data-services layer; role decided by agent → slotted as 5th memory layer via ADR-102
- Endpoint-family order: agent recommendation (session → memory → tools → immune/thermal/self → planner/agents → voice/vision/gateways → websockets → delete main.py)
- WebSocket testing: in-process `httpx` + `websockets` clients in Cloud CI
- ADR-091 microfrontend reverse-proxy architecture accepted permanently

---

## 0. Executive summary

Kosmos-LMS integration is ~65% by scope at commit `e932a02`. Governance, ports, adapters, safety subsystems, memory hybrid search, voice/vision, and the microfrontend shell are all landed. Remaining work is centered on **Tektos-Ultima runtime port-in** (the largest gap, prioritized per user) and **endpoint-split** (154 endpoints across 7 families).

Plan v2 replaces v1's stale 60-step 9-stage structure with a **7-stage sequence** (Stages 8–14) anchored to actual v26 Build-Sequence numbering. Each stage lists concrete BUILD_LOG-order slices with rough session estimates.

**Total remaining sessions estimate:** 30–40 focused Cloud-side sessions + 2 Colossus-side verification passes.

---

## 1. Guiding principles (unchanged from v1)

- **Kosmos discipline authoritative**: BUILD_LOG (append-only), DEBUG_LOG (search first), KNOWN_ISSUES (running list), SESSION_HANDOFF (overwrite), PORTING_LEDGER (every port entry cited with source URL + commit SHA + SPDX), ADR-per-load-bearing-decision.
- **Ports-and-adapters is authoritative**: no plugin imports a vendor library directly; every donor snapshot lives at `adapters/<port>/tektos/vendor/` behind a formal port.
- **ADR-007 events-only cross-plugin coupling**: no plugin imports another plugin.
- **Zero-trust MemoryPort writes**: every write carries `provenance` + `confidence`.
- **License**: re-license to MIT only at port-in time; `rmholston420` sole copyright holder.
- **Fidelity port** (Plan-v2 addition): for Tektos-Ultima runtime port-in, copy donor verbatim under `adapters/<port>/tektos/vendor/`; rewrite import boundaries + adapter façades only. Donor idiosyncrasies preserved.

---

## 2. Repo topology (target vs actual as of `e932a02`)

**Target (unchanged from Kosmos-Build-Spec-v26):**
```
kosmos-lms/
  kernel/        (FastAPI, boot, registry, routes)
  ports/         (formal Protocol contracts; 22 today → 23 after ADR-102)
  adapters/      (implementations, one dir per port + vendor snapshots)
  plugins/       (phrouros, praxis, tektos, zetesis)
  ui/            (Kosmos Next 16.2.11 shell, static export)
  ops/           (systemd, compose)
  docs/          (Spec, Sequence, ADRs, Plans)
  BUILD_LOG.md / DEBUG_LOG.md / KNOWN_ISSUES.md / SESSION_HANDOFF.md
  PORTING_LEDGER.md
```

**Actual state gaps vs target (from 2026-09-10 audit):**
- `vendor/tektos_ultima/` — does NOT exist (Stage 2 quarantine skipped; direct-vendor pattern used instead)
- `plugins/tektos/` — has scaffolds (agent, planner, runtime, self_improve, self_repair, tools, ui) but the donor runtime subsystems (session FSM, `run_until_complete`, reflection, synthesis, dreamtime, coding-agent executor, manager, multi-agent) are NOT ported
- Microfrontend served via reverse-proxy per ADR-091 (permanent choice) — no `plugins/tektos/frontend/`
- `deploy/systemd/` and `deploy/data-services/` — do NOT exist yet (Stage 12 scope)
- 154 Tektos-Ultima endpoints — 0 re-hosted (Stage 11 scope)

---

## 3. What has landed (26 stages complete)

| v26 Stage | ADR anchor | Scope | Landed |
|---|---|---|---|
| 0 (setup) | ADR-077 / 078 | kosmos-lms genesis + v26 spec cut | ✅ 2026-09-10 |
| 1.1 – 1.3 | ADR-079..089 | Port skeletons (Immune, LoopSafety, Thermal, Sandbox, Voice, Vision, Search extensions, etc.) | ✅ 2026-09-10 |
| 2.4 exit gate | — | Kosmos-fork stabilization gate | ✅ (pre-fork) |
| 3.1 – 3.12 | (Kosmos ADRs) | Kosmos MemoryPort + baseline | ✅ (pre-fork) |
| 3.13 | ADR-092 | Immune + LoopSafety + Thermal absorption (3 detectors, state machine, PID) | ✅ 2026-09-10 |
| 4.7 | ADR-093 | Sandbox + Planner + ToolRegistry absorption | ✅ 2026-09-10 |
| 4.8 | ADR-094 | Tool-surface reconciliation + filesystem tools + `MCPToolBridge` | ✅ 2026-09-10 |
| 5.6 | ADR-095 | Self-improve + self-repair propose-only (HUMAN_REQUIRED tier) | ✅ 2026-09-10 |
| 6.5 | ADR-096 | Voice + Vision two-write pattern locked | ✅ 2026-09-10 |
| 6.5 adapter | ADR-097 | faster-whisper STT (TTS deferred) | ✅ 2026-09-10 |
| 6.5 adapter | ADR-098 | Qwen2.5-VL + Tesseract vision | ✅ 2026-09-10 |
| 6.5.8 | ADR-065 | Tektos-UI HTMX kernel mount at `/tektos-ui` | ✅ (pre-fork) |
| Microfrontend | ADR-091 | Tektos-Ultima iframe shell at `/tektos-ultima` + reverse proxy | ✅ 2026-09-10 |
| 7.4 | ADR-099 | `MemoryPort.search_hybrid` on DozerDbMemoryAdapter (H1 retired) | ✅ 2026-09-10 |
| 7.4+1 | ADR-100 | Real `DozerDbLexicalIndex` (Neo4j Lucene fulltext) | ✅ 2026-09-10 |
| 7.4+2 | ADR-101 | Kernel-boot lexical wiring | ✅ 2026-09-10 |

---

## 4. What remains — 7-stage sequence

### Stage 8 — Tektos-Ultima runtime completion (fidelity port)

**Goal:** end-to-end, an autonomous Tektos-Ultima coding session runs from inside kosmos-lms via `plugins/tektos/*`, satisfying the plan-v1 Appendix D "must not lose" checklist.

**Slices** (each = one BUILD_LOG entry + one PORTING_LEDGER flip + contract tests):

- **8.0 — RelationalMemoryPort + Postgres 5th-layer plumbing** (ADR-102). New port, 2 adapters (noop-sqlite + postgres+pgvector), Alembic migrations, kernel wiring, contract tests. ~1 session. **First slice — everything downstream can record audit + narrative here.**
- **8.1 — Session FSM + session_state port-in.** Vendor `src/tektos/state_machine.py` + `src/tektos/runtime/session.py` under `adapters/tektos/vendor/`. Wrap behind existing `plugins/tektos/runtime/turn_loop.py` (extend it). Endpoints: `POST /tektos/api/session/create`, `GET /tektos/api/session/{id}`, `POST /tektos/api/session/{id}/step`, `POST /tektos/api/session/{id}/end`. Contract tests via `httpx.AsyncClient`. ~1 session.
- **8.2 — Agent multi-iteration `run_until_complete` + read-only budget wiring.** Vendor `src/tektos/agents/coding_agent.py` (or nearest donor) under `adapters/tektos/vendor/`. Wire ADR-088 read-only budget through `LoopSafetyPort.record_tool_call`. Endpoints: `POST /tektos/api/agent/run_until_complete`, `GET /tektos/api/agent/{id}/status`. ~1 session.
- **8.3 — Reflection + synthesis + experience-replay engines.** Vendor donor engines. New `plugins/tektos/reflection/`, `plugins/tektos/synthesis/`, `plugins/tektos/experience/`. All writes route through `RelationalMemoryPort.write_narrative`. Endpoints: `POST /tektos/api/reflection/reflect`, `POST /tektos/api/synthesis/synthesize`, `GET /tektos/api/experience/recent`. ~2 sessions.
- **8.4 — Planner-orchestrator + task-decomposer.** Vendor `src/tektos/routing.py` + donor planner. Extend `plugins/tektos/planner/`. Endpoints: `POST /tektos/api/planner/plan`, `POST /tektos/api/planner/decompose`. ~1 session.
- **8.5 — Coding-agent executor helpers.** Vendor patch/build/test/commit helpers from `src/tektos/agents/coding_agent.py` + `src/tektos/gitops.py` + `src/tektos/git_integration.py`. Route through `SandboxPort.run` (patch/build/test) and `RelationalMemoryPort.record_event` (commit-audit). ~2 sessions.
- **8.6 — Manager (guardrails/metrics/archetype).** Vendor donor manager. Guardrails delegate to `ImmunePort`; metrics to `ObservabilityPort`; archetype-tracker lives plugin-internal. ~1 session.
- **8.7 — Multi-agent + hierarchical + long-running agents.** Vendor donor multi-agent orchestrator; hierarchical spawn via existing EventBusPort. Long-running via `RelationalMemoryPort.record_event` heartbeats. ~2 sessions.
- **Stage 8 exit gate.** End-to-end acceptance test: given a fixture repo + a coding task string, `POST /tektos/api/agent/run_until_complete` returns a completed session with real patch + test-run evidence in `RelationalMemoryPort`. **Discharges plan-v1 Appendix D items 10, 11 (VSM subs + Aider repomap already merged).**

**Stage 8 subtotal:** 11 sessions.

### Stage 9 — Detector + tool coverage completion

- **9.1 — Port 9 remaining immune detectors.** Vendor `src/tektos/runtime/immune_system.py` remainder including SecretExposureDetector's 12 regex patterns. Extend `adapters/immune/tektos/detectors.py`. **Discharges plan-v1 Appendix D items 1 + 5.**
- **9.2 — Port 3 remaining built-in tools** (`bash`, `directory_create`, `search`). Extend `plugins/tektos/tools/` per ADR-094 tier map.
- **9.3 — Contract tests** for full 12-detector + 7-tool DoD.
- **Stage 9 exit gate:** all 12 detectors green in contract tests; all 7 built-in tools invocable through registry.

**Stage 9 subtotal:** 2 sessions.

### Stage 10 — Skills DB port

- **10.1 — Author ADR-103 (skills DB port).** Provenance tier `tektos_skill`; endpoint surface `/tektos/api/skills/*`; storage split — skill metadata in `RelationalMemoryPort`, skill embeddings in `EmbeddingsPort`, skill artifacts in blob store.
- **10.2 — Port skills subsystem.** Vendor `src/tektos/skills/` behind the new port.
- **10.3 — Pier eval integration** for skill improvements (donor has `plugins/tektos/eval/test_pier_eval.py` scaffold today).
- **Stage 10 exit gate:** skills round-trip through the new port with Pier scoring.

**Stage 10 subtotal:** 2 sessions.

### Stage 11 — Endpoint split (154 endpoints under `/tektos/api/*`, delete `main.py`)

Family order **matches Stage 8 slice order** so runtime + endpoints land together where possible. Stage 8 slices already ship the "runtime + session + agent + reflection + planner + executor + manager + multi-agent" family (~40 endpoints). Stage 11 slices land the remaining families that don't have a corresponding runtime slice.

- **11.1 — Memory family** (13 endpoints): hindsight, dreamtime, experience, replay, memory-search. Backed by `MemoryPort` + `RelationalMemoryPort`. ~1 session.
- **11.2 — Tools + MCP + sandbox family** (~24 endpoints): tool.invoke, tool.list, MCP.list_tools, sandbox.run, sandbox.status. Backed by `MCPPort` + `SandboxPort` + tool_registry. ~1-2 sessions.
- **11.3 — Immune + thermal + self-\* + telemetry family** (~40 endpoints): immune.check, immune.log, thermal.status, thermal.metrics, self_improve.propose, self_repair.propose, telemetry.\*. ~2 sessions.
- **11.4 — Models + LLM + routing + config + keys + DB family** (~48 endpoints): models.list, llm.probe, routing.decide, config.get/set, keys.rotate, db.stats. Backed by `LLMPort` + `SecretsPort`. ~2 sessions.
- **11.5 — Voice + vision + MCP-server + plugins + gateways family** (~15 endpoints): voice.transcribe/synthesize, vision.describe/extract_text, plugin.list, plugin.status, telegram/email gateway health. ~1 session.
- **11.6 — WebSockets family** (2 endpoints): `/tektos/api/ws/{session_id}` (agent event stream) via `EventBusPort` subscription; `/tektos/api/ws/pty` (PTY stream) via new `SandboxPort.pty()` method. **Tested with in-process `httpx.AsyncClient` + `websockets` clients** (per user Q3 decision). ~1 session.
- **11.7 — Delete `main.py`.** Verify all 154 endpoints have replacements. Delete donor `main.py` if it were vendored (it isn't — this becomes a documentation-only step marking the endpoint migration complete). Update PORTING_LEDGER row for `main.py` from `PENDING` → `RETIRED-BY-ENDPOINT-SPLIT`. ~0.5 session.
- **Stage 11 exit gate:** `/tektos/api/*` mounts 154 endpoints; contract tests green; endpoint parity table checked against donor.

**Stage 11 subtotal:** 8-9 sessions.

### Stage 12 — Deployment surface

- **12.1 — Systemd unit set.** Port donor's 5 units + target from `deploy/systemd/user/`. Add `kosmos-lms.target` with `Wants=` for all downstream units. User-scope (systemd linger) per donor pattern. Land at `deploy/systemd/user/`.
- **12.2 — Data-service installers.** Port `install-neo4j.sh`, `install-redis.sh`, `install.sh` (orchestrator). Author new `install-postgres.sh` (Postgres 18 + pgvector 0.8.1 + pg_uuidv7 + Alembic migrations) per ADR-102.
- **12.3 — `docs/network-ports.md`.** Merge donor `docs/ports.md` (network-port assignments — distinct from `docs/PORT_CONTRACTS.md` which is port surface contracts). Enforce spec §25.7 no-`0.0.0.0` rule and `:9177` forbidden.
- **12.4 — CI matrix.** Add `frontend-tektos-build` + `frontend-tektos-lint` jobs to `.github/workflows/ci.yml`. Add Playwright leg targeting the microfrontend shell.
- **12.5 — Colossus verification pass** (user-side). User pulls, runs `systemctl --user daemon-reload`, executes each installer, runs `KOSMOS_STAGE_120_LIVE=1 pytest tests/deployment/` + headed Playwright suite. Cloud sandbox lands artifacts; Colossus proves them.
- **Stage 12 exit gate:** `kosmos-lms.target` boots on Colossus, survives reboot, all systemd units green, Postgres accepts connections, Alembic migrations applied, Playwright green in headed mode.

**Stage 12 subtotal:** 3 Cloud sessions + 1 Colossus verification session.

### Stage 13 — Remaining donor subsystems

- **13.1 — `schema_evolution.py`.** Approval-gated CRITICAL tier; wire through `ApprovalGatewayPort`.
- **13.2 — `db_manager.py`.** CRITICAL tier; ImmunePort SecretExposureDetector on responses.
- **13.3 — `gateway_proxy.py`.** JSON-RPC 2.0 method → envelope translation (Appendix D item 5 — preserve intact).
- **13.4 — `gitops.py` + `git_integration.py`.** Already partially landed as part of Stage 8.5; this slice picks up remaining helpers (branch management, PR helpers).
- **13.5 — `recovery.py` + `state_machine.py` helpers.** Recovery ties into ADR-090 (still deferred) — propose-only shape acceptable.
- **13.6 — `store/`, `search/`, `telemetry/`, `metabolism/`.** Utilities; some already landed as Stage 8 side-effects.
- **13.7 — `voice.py` reconciliation.** Donor's `src/tektos/voice.py` (310 lines) predates `VoicePort`. Reconcile: keep only whatever is orthogonal to the port; delete duplicates.
- **Stage 13 exit gate:** donor `src/tektos/` inventory ≤ 5 modules unported; each unported module has a `PORTED.md`-tracked rejection ADR.

**Stage 13 subtotal:** 4-5 sessions.

### Stage 14 — Retirement + freeze

- **14.1 — Sunset markers** on `rmholston420/tektos-ultima` (README banner + BUILD_LOG close) and `rmholston420/kosmos` (already frozen at c455165; add explicit sunset marker).
- **14.2 — `vendor/tektos_ultima/` cleanup.** No-op if quarantine never landed (current state); else `git rm -r`.
- **14.3 — ADRs 077–102+ → LOCKED.** Amend each header block.
- **14.4 — Spec close-out.** Kosmos-Build-Spec-v26 marked LOCKED; author ADR-104 for the close-out; if further work is anticipated, cut v27.
- **14.5 — Program sign-off** in BUILD_LOG.
- **Stage 14 exit gate:** PROGRAM COMPLETE.

**Stage 14 subtotal:** 1 session.

---

## 5. Grand total remaining

| Stage | Sessions |
|---|---|
| 8 Runtime | 11 |
| 9 Detectors + tools | 2 |
| 10 Skills DB | 2 |
| 11 Endpoint split | 8-9 |
| 12 Deployment | 3 Cloud + 1 Colossus |
| 13 Donor remainder | 4-5 |
| 14 Freeze | 1 |
| **Total** | **~32-34 Cloud + 1 Colossus** |

Each session is roughly 1-3 hours of focused agent work. At one session per work-day this is ~7 weeks; at two sessions per work-day, ~3.5 weeks.

---

## 6. Risks + kill switches (unchanged from v1, updated for v2)

- **Donor drift.** If `rmholston420/tektos-ultima` receives new commits after fork, either merge deltas into vendored snapshots (preferred) or freeze the port at the SHA in PORTING_LEDGER. Track via `PORTING_LEDGER.md` upstream-SHA column.
- **Postgres availability in Cloud CI.** Fast tests use noop sqlite adapter. Live Postgres tier gated by `KOSMOS_STAGE_80_REAL_POSTGRES=1` — Cloud runs against ephemeral compose Postgres in CI; Colossus runs against real installer.
- **Endpoint parity gap.** After Stage 11.7 (delete `main.py` marker), if any consumer discovers a missing endpoint, add it as a hotfix slice with ADR-105+. Do NOT keep `main.py` alive as a shim.
- **ADR-090 (SelfModificationPort) still deferred.** Stage 13.5 relies on the propose-only shape from ADR-095. If ADR-090 ratifies during v2 execution, revisit and upgrade Stages 8.6 (manager) and 13.5 (recovery) to apply-capable.
- **Kill switch: quality of runtime port.** If fidelity port at Stage 8.x reveals donor code that violates a Kosmos invariant (e.g. bypasses MemoryPort zero-trust), stop the slice, author a rejection ADR, and either rewrite that specific module against the contract (per user Q2 fallback) or reject with cause.

---

## 7. Sequence-of-execution appendix (BUILD_LOG order)

Immediate execution order:

1. **8.0** — RelationalMemoryPort + Postgres 5th-layer (ADR-102, this commit)
2. **8.1** — Session FSM + session endpoints
3. **8.2** — Agent multi-iteration + read-only budget wiring
4. **8.3** — Reflection + synthesis + experience-replay
5. **8.4** — Planner-orchestrator + task-decomposer
6. **8.5** — Coding-agent executor helpers
7. **8.6** — Manager
8. **8.7** — Multi-agent + hierarchical + long-running
9. **9.1–9.3** — Detectors + tools completion
10. **10.1–10.3** — Skills DB
11. **11.1–11.7** — Endpoint split families
12. **12.1–12.4** — Deployment artifacts (Cloud)
13. **12.5** — Colossus verification (user-side)
14. **13.1–13.7** — Donor subsystem remainder
15. **14.1–14.5** — Retirement + freeze

Every slice: SESSION_HANDOFF read at start; BUILD_LOG appended at end; SESSION_HANDOFF overwritten at end.

---

## Appendix A — Decision reconciliation (v1 → v2)

| Plan v1 element | Status in v2 |
|---|---|
| Stage 0 (genesis) | ✅ Landed; no v2 change |
| Stage 1 (port skeletons) | ✅ Landed; no v2 change |
| Stage 2 (quarantine + subtree) | ❌ SKIPPED; v2 retires as unnecessary (direct-vendor pattern succeeded) |
| Stage 3.1–3.4 (immune/loop_safety/thermal) | ✅ Landed as v26 Stage 3.13 (ADR-092); v2 renumbers |
| Stage 4.1–4.3 (sandbox/tools/MCP) | ✅ Landed as v26 Stages 4.7 + 4.8 (ADR-093, 094); v2 renumbers |
| Stage 5.1–5.7 (runtime/agent/reflection/etc.) | ⏸ REOPENED as **v2 Stage 8.1–8.7** |
| Stage 6.1 (ADR-091 Hindsight decision) | ❌ RETIRED; ADR-091 was reallocated to microfrontend shell; the Hindsight decision landed as ADR-099 |
| Stage 6.2 (Hindsight bridge H1) | ❌ RETIRED by ADR-099 |
| Stage 6.3 (memory subsystem port) | ⏸ REOPENED as **v2 Stage 8.0** (RelationalMemoryPort) + parts of Stage 13 |
| Stage 6.4/6.5 (self_repair/self_improve) | ✅ Landed propose-only as v26 Stage 5.6 (ADR-095); apply-side deferred with ADR-090 |
| Stage 6.6 (skills DB) | ⏸ REOPENED as **v2 Stage 10** |
| Stage 6.7 (ADR-090 deferred) | ✅ Ratified as PROPOSED / DEFERRED; unchanged |
| Stage 7.1–7.8 (endpoint split) | ⏸ REOPENED as **v2 Stage 11.1–11.7** |
| Stage 8.1 (git mv frontend) | ❌ RETIRED by ADR-091 (reverse-proxy architecture chosen permanently) |
| Stage 8.2 (kernel mount static) | ❌ RETIRED by ADR-091 |
| Stage 8.3 (iframe panel) | ✅ Landed as part of ADR-091 |
| Stage 8.4 (systemd) | ⏸ REOPENED as **v2 Stage 12.1** |
| Stage 8.5 (data-services) | ⏸ REOPENED as **v2 Stage 12.2**, now includes Postgres per ADR-102 |
| Stage 8.6 (docs/ports.md) | ⏸ REOPENED as **v2 Stage 12.3** (renamed to `docs/network-ports.md`) |
| Stage 8.7 (CI matrix) | ⏸ REOPENED as **v2 Stage 12.4** |
| Stage 9 (retirement + freeze) | ⏸ REOPENED as **v2 Stage 14** |

---

**End of Plan v2.** Land Stage 8.0 (RelationalMemoryPort + Postgres) first, per Sequence-of-Execution appendix.
