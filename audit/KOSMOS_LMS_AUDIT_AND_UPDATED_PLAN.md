# Kosmos-LMS Full Audit & Updated Integration Plan

**Audit date:** 2026-09-10 04:30 EDT
**Auditor:** Perplexity agent, Cloud sandbox `f9fcf03a11a2e6286c164c610e3d461fc0df86dff61d9966c84ac21c120fb1fa`
**Scope:** three repos — `rmholston420/kosmos-lms` (HEAD `e932a02`), `rmholston420/tektos-ultima` (HEAD `2b45cac`), `rmholston420/kosmos` (HEAD `c455165`)
**Purpose:** honest snapshot of what has been built, what remains, and what the original 60-step Integration Plan got wrong or needs to change.

---

## 0. Executive summary

The Kosmos-LMS integration is **~65% complete** by scope, but the Integration Plan has drifted badly from reality on three axes:

1. **Numbering divergence.** The plan uses Stages 0–9 with ~60 steps. What actually landed uses a **v26-addendum numbering** grafted onto the primary Kosmos v26 sequence (Stages 3.13, 4.7, 4.8, 5.6, 6.5, 7.4/+1/+2). None of these numbers appear in the Integration Plan. Anyone reading the plan today cannot locate progress against it.
2. **Architecture divergence — frontend/microfrontend.** Plan Stage 8 charters a *port-in-and-static-mount* architecture (`git mv vendor/tektos_ultima/frontend → plugins/tektos/frontend`, kernel serves built Next.js output). What landed via **ADR-091 (2026-09-10)** is a *reverse-proxy-to-upstream-`:5556`* architecture — the Tektos-Ultima frontend stays in its own repo and dev-server, and the kernel proxies to it. This is a **materially different** integration shape that discharges most of the plan's Stage 8 intent under a different label, but leaves the plan wording stale.
3. **Massive scope skipped — endpoint split.** Plan Stage 7 (Steps 7.1–7.8) charters the retirement of Tektos-Ultima's 5998-line `main.py` monolith by re-serving all **154 endpoints** under `/tektos/api/*` on the kernel. Zero of these endpoints have been re-hosted. The kernel currently mounts **two** Tektos-Ultima routes (a reverse proxy + a postMessage bridge) totalling ~10% of the surface area. The entire endpoint-family retirement work in Stage 7 remains, and it is the single largest outstanding item.

Beyond those three, there are smaller gaps: the whole Tektos-Ultima runtime subsystems (`immune`, `loop_safety`, `thermal`, `sandbox`, `agents`, `memory`, `skills`) live **behind adapters at the port boundary** but **have never been ported into `plugins/tektos/*`** as the Integration Plan Stage 5 requires. They exist as `adapters/{immune,loop_safety,thermal,sandbox}/tektos/` façades — but the plugin-internal implementations live only in the external Tektos-Ultima repo. This means the multi-iteration agent loop, session state machine, reflection/synthesis engines, dreamtime, and skills DB are not actually usable from kosmos-lms.

Deployment surface — systemd units, data-service installers, docs/ports.md — is **not landed**. Stage 8 Steps 8.4–8.6 remain fully open.

**What has landed well:** the 25 ADRs (077–101), the six new formal ports (Immune, LoopSafety, Thermal, Sandbox, Voice, Vision), MemoryPort hybrid retrieval with real Neo4j Lucene lexical adapter, kernel-boot lexical wiring, five specialized adapters per port, 1462 passing tests with zero failures across the whole baseline, the microfrontend shell integration (ADR-091), and the Kosmos governance discipline (BUILD_LOG, DEBUG_LOG, PORTING_LEDGER, SESSION_HANDOFF, ADR authoring) enforced across every step.

---

## 1. Repository snapshot

### 1.1 kosmos-lms (target repo) — HEAD `e932a02`

| Category | Count / detail |
|---|---|
| ADRs authored | 103 total (Kosmos 001–076 preserved from fork, plus 077–101 authored in kosmos-lms) |
| Formal ports | 23 (`.py` files under `ports/`, up from Kosmos's 16) |
| Adapters (top-level port dirs) | 21 (up from Kosmos's 14) |
| Plugins | 4 (`phrouros`, `praxis`, `tektos`, `zetesis`) — same as Kosmos |
| Test baseline | **1462 passed / 0 failed / 15 skipped** (skips are opt-in Colossus-only integrations) |
| Kernel HTTP routes | 38 (`kernel/app.py`) + 1 tektos-ultima bridge router (`kernel/tektos_ultima_bridge.py`) + 1 Tektos-UI sub-app mount (`/tektos-ui`, HTMX) + 1 Kosmos Next static-export mount (`/`) + 1 Gnosis-gate sub-app (`/gnosis-gate`) |
| BUILD_LOG entries | ~120 across 4 dates (2026-07-29, 2026-07-30, 2026-08-01, 2026-09-10) |
| SESSION_HANDOFF state | Stage 7.4+2 LANDED; commit `e932a02` pushed to `origin/main` |

**New ports** (all authored since ADR-077 fork):
`immune.py` (ADR-079) · `loop_safety.py` (ADR-080) · `thermal.py` (ADR-081) · `sandbox.py` (ADR-082) · `voice.py` (ADR-083) · `vision.py` (ADR-084) · `event_envelope.py` extension (ADR-086) · `mcp.py` (Stage 3.2) · `embeddings.py` (ADR-073)

**New adapters** (top-level dirs):
`immune/tektos/` · `loop_safety/tektos/` · `thermal/tektos/` · `sandbox/{noop,tektos}/` · `voice/{noop,faster_whisper}/` · `vision/{noop,ollama_qwen_vl,tesseract}/` · `tektos/vendor/` · `tektos_frontend/`

### 1.2 tektos-ultima (donor) — HEAD `2b45cac`

| Category | Count / detail |
|---|---|
| `src/tektos/` top-level modules | 45 (agents, axioms, config, db_manager, email_gateway, event_bus, gateway_adapter, gateway_proxy, git_integration, gitops, gui, main, mcp_server, memory, metabolism, migrations, plugin, plugin_loader, ports, protocol, providers, rate_limiter, recovery, repograph, requests, routing, runtime, schema_evolution, search, self_improvement, self_modification, self_repair, skills, state_machine, store, telegram_gateway, telemetry, thermal, tools, utils, voice) |
| `main.py` size | 5998 lines, 154 HTTP endpoints |
| Frontend | Next.js 15.4 at `frontend/` — `src/{app,components,lib,styles,types}` + `tests/{unit,e2e}` (9 test specs) + Playwright config + Jest config |
| Frontend-legacy | Present at `frontend-legacy/` (obsolete Next.js scaffold; drop-target per plan Step 8.1) |
| Deploy | `deploy/systemd/user/*.service` (5 units + install.sh + tektos.target) · `deploy/data-services/*.sh` (Neo4j + Redis + orchestrator install) |
| docs/ports.md | Present (network-port assignment table) |
| Test suite | 171 Python test files under `tests/` |
| Plugins subdirectory | 4 search plugins (duckduckgo, farfalle, searxng, tavily) — unrelated to Kosmos-plugin architecture |

### 1.3 kosmos (donor, frozen) — HEAD `c455165` (2026-08-01)

| Category | Count / detail |
|---|---|
| ADRs | 78 (through ADR-076) |
| Formal ports | 16 (all also present in kosmos-lms) |
| Adapters | 14 (subset of kosmos-lms's 21) |
| Plugins | 4 (`phrouros`, `praxis`, `tektos`, `zetesis`) — Tektos plugin is Kosmos-scaffold only, no runtime |
| Missing from kosmos-lms | 25 ADRs (077–101) · 7 new ports · 7 new adapter families · Tektos-Ultima bridge · voice/vision · immune/loop_safety/thermal/sandbox adapters · MemoryPort search_hybrid + lexical index |
| Divergence date | 2026-08-01 last commit; kosmos-lms diverged 2026-09-10 with ADR-077 |
| Last BUILD_LOG entry | `2026-08-01 13:45 EDT — DozerDB end-to-end persistence proven` |

**Ruling:** the Kosmos donor is a **frozen historical reference**, safe to leave alone. All ongoing work is in kosmos-lms. Plan Stage 9 Step 9.1 (sunset marker on `rmholston420/kosmos`) is still open but non-blocking.

---

## 2. Integration Plan vs reality — stage-by-stage

Marker key:
- **✅ LANDED** — full DoD met, matches plan intent
- **🔀 LANDED-DIFFERENT** — DoD met via a different architecture than the plan chartered
- **⚠️ PARTIAL** — some steps landed, some open
- **⏸ NOT STARTED** — no work has begun
- **📎 OFF-PLAN** — landed under an addendum-numbering scheme not present in the plan

### Stage 0 — Repository genesis — **✅ LANDED**

| Step | Status | Note |
|---|---|---|
| 0.1 Fork Kosmos → kosmos-lms | ✅ | HEAD `a3d506c..e932a02` on `rmholston420/kosmos-lms` |
| 0.2 LICENSE (MIT) + author | ✅ | Present at `LICENSE` |
| 0.3 ADR-077 integration cut | ✅ | `docs/adrs/ADR-077-kosmos-lms-integration-cut.md` |
| 0.4 ADR-078 spec v26 cut | ✅ | `docs/adrs/ADR-078-kosmos-build-spec-v26-cut.md` + `docs/Kosmos-Build-Spec-v26.md` + `docs/Kosmos-Build-Sequence-v26.md` |
| 0.5 CI import | ⚠️ PARTIAL | `.github/workflows/ci.yml` present (8 jobs) but not the full Tektos-Ultima 6-job baseline; no `frontend-tektos-*` matrix legs |
| 0.6 Log discipline bootstrap | ✅ | BUILD_LOG (3902 lines) + DEBUG_LOG + KNOWN_ISSUES + SESSION_HANDOFF all present, discipline enforced |
| 0.7 PORTING_LEDGER seed | ✅ | `PORTING_LEDGER.md` extended per plan |

### Stage 1 — Port skeletons + ADR authoring — **✅ LANDED**

All 6 new port ADRs (079–084) + 5 amendment ADRs (085–089) + ADR-090 (SelfModificationPort deferred). All 6 port files present, all 6 adapter fakes present or superseded by real adapters. Kernel boot order updated. **Fully discharged.**

### Stage 2 — Tektos-Ultima quarantine + tree-import — **❌ SKIPPED**

| Step | Status | Note |
|---|---|---|
| 2.1 `git subtree add --prefix=vendor/tektos_ultima` | ❌ | `vendor/` contains only `adr_010/`. The quarantine subtree was never imported. |
| 2.2 `vendor/tektos_ultima/PORTED.md` checklist | ❌ | Not authored |
| 2.3 CI matrix `frontend-tektos-{build,lint}` | ❌ | Neither job present |

**Impact:** Stages 3–7 landed by **direct authoring / copy-paste from external Tektos-Ultima repo** instead of via `git mv` out of quarantine. The net code outcome is the same (adapters + plugins exist), but provenance recording in PORTING_LEDGER became less mechanical (each entry cites `github.com/rmholston420/tektos-ultima/blob/2b45cac/…` explicitly rather than being derived from the subtree). No known bugs from the divergence.

### Stage 3 — Immune, loop-safety, thermal — **📎 LANDED-OFF-PLAN as v26 Stage 3.13** (ADR-092)

| Plan step | v26 stage | Status | Note |
|---|---|---|---|
| 3.1 ImmunePort real adapter | Stage 3.13 | ✅ | `adapters/immune/tektos/` with 3 seed detectors; contract test green |
| 3.2 LoopSafetyPort real adapter | Stage 3.13 | ✅ | `adapters/loop_safety/tektos/` with 3-tier state machine |
| 3.3 ThermalPort real adapter | Stage 3.13 | ✅ | `adapters/thermal/tektos/` with PID controller, yellow 51 °C / cap 80 °C / red 88 °C |
| 3.4 Stage 3 exit gate | — | ✅ | Full suite green; ADR-092 ratified |

**Divergence:** the plan says the 12 SecretExposureDetector patterns and the 12 immune detectors should all port (Appendix D item 1). What landed is 3 seed detectors, not the full 12. The remaining 9 are still in the donor at `src/tektos/runtime/immune_system.py` and have **not** been ported.

### Stage 4 — Sandbox + tool registry + MCP consolidation — **📎 LANDED-OFF-PLAN as v26 Stages 4.7 + 4.8** (ADR-093 + ADR-094)

| Plan step | v26 stage | Status | Note |
|---|---|---|---|
| 4.1 SandboxPort real adapter | Stage 4.7 | ✅ | `adapters/sandbox/tektos/` (Linux namespaces + cgroups) + `adapters/sandbox/noop/` |
| 4.2 Tektos built-in tools via in-process MCP | Stage 4.7 + 4.8 | ⚠️ PARTIAL | Filesystem tools landed (`file_read`, `file_list`, `file_write`, `file_delete`) with tier-gated approval. The other 3 donor tools (`bash`, `directory_create`, `search`) are **not** ported. |
| 4.3 Deprecate direct tool paths | — | ✅ | `TektosAgent.call_tool` delegates to `tool_registry.invoke`; MCPToolBridge wires external MCP tools with `TEKTOS_TOOL_TIER_MAP` |

**Divergence:** the plan's 7 built-in tools are only partially ported (4 of 7). The remaining 3 (`bash`, `directory_create`, `search`) are still donor-only.

### Stage 5 — Tektos runtime + agent + planner core — **⚠️ PARTIAL** (huge gap)

| Plan step | Status | Note |
|---|---|---|
| 5.1 Port `runtime/{session,state_machine,session_state}.py` | ❌ | Only `plugins/tektos/runtime/{turn_loop.py, test_turn_loop.py}` landed (a 3-turn scripted loop, not the full FSM). Session state machine + session model not ported. |
| 5.2 Extend agent with multi-iteration + tool loop + read-only budget | ⚠️ | `plugins/tektos/agent.py` exists but is the pre-existing Kosmos-scaffold ADR-036 shape (single-iteration). Multi-iteration `run_until_complete` not added. Read-only budget mechanism logged in ADR-088 but not wired into the agent. |
| 5.3 Reflection engine, synthesis engine, experience replay, dreamtime | ❌ | None ported |
| 5.4 Planner + orchestrator | ⚠️ | `plugins/tektos/planner/{turn_planner.py, test_turn_planner.py}` landed as a 3-node linear planner (Stage 4.7.4 seed). Full `planner_orchestrator.py` + `task_decomposer.py` not ported. |
| 5.5 Coding-agent executor helpers (patch/build/test/commit) | ❌ | Not ported |
| 5.6 Manager (guardrails, metrics, archetype) | ❌ | Not ported |
| 5.7 Multi-agent + hierarchical + long-running agents | ❌ | Not ported |

**Impact:** **the core Tektos-Ultima autonomous coding-agent runtime is not usable from kosmos-lms.** The agent surface today is Stage 3.6's seed turn-loop and Stage 4.7.4's seed planner — enough to prove the port contracts but not enough to run an actual coding session.

### Stage 6 — Memory adapter, Hindsight, self-repair, self-improvement — **⚠️ PARTIAL** (major gaps + one plan retirement)

| Plan step | Status | Note |
|---|---|---|
| 6.1 ADR-091 Hindsight decision (H1 default) | 🔀 REVERSED | ADR-091 was authored as **microfrontend shell integration**, not Hindsight. The Hindsight decision was resolved by **ADR-099 (Stage 7.4 re-scope)**: H1 skipped entirely, `MemoryPort.search_hybrid` lands directly on `DozerDbMemoryAdapter`. |
| 6.2 Hindsight bridge port-in (H1) | ❌ RETIRED | Superseded by ADR-099. The `hindsight_bridge` PORTING_LEDGER row is now `EVALUATED-REJECTED`. |
| 6.3 Port memory{neo4j,postgres,redis,file_based,persistence,backup_scheduler} | ❌ | None ported |
| 6.4 Port self_repair/* | 📎 ⚠️ | Landed as v26 Stage 5.6 (ADR-095) as **propose-only** (`plugins/tektos/self_repair/proposer.py`, 274 lines, HUMAN_REQUIRED tier). Donor engines intentionally NOT ported (4046+ lines of donor code deferred). |
| 6.5 Port self_improvement/* | 📎 ⚠️ | Same as 6.4 — Stage 5.6 propose-only |
| 6.6 Port skills/* | ❌ | Not ported |
| 6.7 ADR-090 SelfModificationPort (deferred) | ✅ | ADR-090 present as PROPOSED / DEFERRED |

**Divergence:** ADR-091 in the plan (Hindsight decision) collides with ADR-091 as actually authored (microfrontend shell). **This is a real numbering conflict** — the plan reserved ADR-091 for Hindsight and it got used for the frontend. The Hindsight decision landed later as ADR-099. **Plan text needs to be updated** so future readers don't hunt for a Hindsight ADR that never was.

### Stage 7 — Endpoint split: retire `main.py`, mount `/tektos/api/*` — **⏸ NOT STARTED**

This is **the largest single outstanding gap.** Zero of the 154 endpoints have been re-hosted. The plan enumerates 8 steps grouped by endpoint family:

| Plan step | Endpoint families | Endpoints | Status |
|---|---|---|---|
| 7.1 Runtime, health, logs, directory | 4 | ⏸ |
| 7.2 Memory, hindsight, dreamtime, experience, replay | 13 | ⏸ |
| 7.3 Tools, MCP, sandbox, skills | ~24 | ⏸ |
| 7.4 Immune, self-repair, self-improvement, self-modification (probes), thermal, telemetry, planner, schema-evolution, context | ~40 | ⏸ |
| 7.5 Sessions, models, LLM probe, routing, config, keys, DB manager | ~48 | ⏸ |
| 7.6 Vision, voice, MCP-server, plugins, telegram, email | ~15 | ⏸ |
| 7.7 WebSockets (`/ws/{session_id}`, `/ws/pty`) | 2 | ⏸ |
| 7.8 Delete `vendor/tektos_ultima/src/tektos/main.py` | — | ⏸ |

**Note on plan numbering vs v26 Stages 7.4/+1/+2:** the confusion is real. The plan's "Stage 7" is **endpoint split**, wholly unrelated to v26 Stages 7.4/+1/+2 which cover `MemoryPort.search_hybrid` + lexical index + kernel-boot wiring. Both are legitimately labeled "Stage 7.X" and coexist without conflict, but this is exactly why the numbering is unreadable.

**Precedent:** the existing `kernel/tektos_ultima_bridge.py` (`POST /api/tektos-ultima/bridge` — 2 routes) is the shape that Stage 7 endpoints should extend. Each family becomes an `APIRouter` under `plugins/<family>/router.py` and is `include_router`-ed by `kernel/app.py`.

### Stage 8 — Frontend microfrontend + deployment surface — **🔀 LANDED-DIFFERENT (partial) + ⏸ NOT STARTED (partial)**

| Plan step | Chartered architecture | Actual state | Note |
|---|---|---|---|
| 8.1 `git mv vendor/.../frontend → plugins/tektos/frontend` | Port frontend source in-tree | ❌ NOT DONE (reverse-proxy chosen instead) | ADR-091 chose to proxy to upstream `:5556` rather than port source. **This decision should be documented as a Stage 8 amendment** so future readers understand why plugins/tektos/frontend/ doesn't exist. |
| 8.2 Kernel mount `/tektos/frontend` for static Next.js output | Static-mount | 🔀 REPLACED | Kernel mounts `/tektos-ultima/frontend/*` as a Starlette streaming reverse proxy per ADR-091. Both achieve the same-origin goal; the reverse proxy defers the static-build step. |
| 8.3 Kosmos UI iframe panel | New `ui/app/tektos/page.tsx` | 🔀 LANDED at `/tektos-ultima` | `ui/app/tektos-ultima/page.tsx` + `ui/components/TektosUltimaBridge.tsx` + Playwright `tests/20-tektos-ultima-shell.spec.ts`. The existing `/tektos` route (ADR-065 Kosmos-native approval list) is preserved. |
| 8.4 Systemd unit set | Move + rename donor units | ⏸ | Donor `deploy/systemd/user/*.service` (5 units + target) not yet ported. Only `ops/systemd/kosmos-kernel.service` (single system-scope unit) exists. |
| 8.5 Data-service installers | Move `deploy/data-services/*` | ⏸ | Donor's 3 installers (Neo4j, Redis, orchestrator) not yet ported. Kosmos-lms has `ops/compose/memory.yml` (DozerDB compose) but no Postgres/Redis. |
| 8.6 Merged `docs/ports.md` | Merge donor network-port table | ⏸ | Kosmos-lms has `docs/PORT_CONTRACTS.md` (port surface contracts — different concept from network-port assignment). Need new `docs/network-ports.md` merged from donor. |
| 8.7 CI matrix `frontend-tektos-{build,lint}` + Playwright | Add matrix jobs | ⏸ | Neither job present. Existing `frontend-e2e` job runs Playwright against `ui/` only. |

**Key insight:** ADR-091 already achieves the plan's *user-visible* Stage 8 DoD (kernel serves both UIs same-origin, iframe renders, Playwright green) via reverse-proxy topology. What remains are the *operational* pieces: systemd, data-services, docs, CI matrix.

### Stage 9 — Retirement, freeze, spec close-out — **⏸ NOT STARTED**

Not attempted. Every module needs the PORTED.md checklist (which itself was never authored, plan Step 2.2). Sunset markers on donor repos not authored.

---

## 3. Off-plan work that landed (v26 addendum stages)

These landed successfully but are **not in the Integration Plan text**. The plan needs to absorb them.

| v26 stage | ADR | Scope | Status |
|---|---|---|---|
| Stage 3.13 | ADR-092 | Immune + LoopSafety + Thermal port-in (3 detectors, 3-tier state machine, PID) | ✅ LANDED |
| Stage 4.7 | ADR-093 | Sandbox + Planner + ToolRegistry absorption | ✅ LANDED |
| Stage 4.8 | ADR-094 | Tool-surface reconciliation + filesystem tools + MCPToolBridge | ✅ LANDED |
| Stage 5.6 | ADR-095 | Self-improve + self-repair propose-only (gated behind HUMAN_REQUIRED) | ✅ LANDED |
| Stage 6.5 | ADR-096 / 097 / 098 | Voice + Vision adapters (faster-whisper STT, Qwen2.5-VL, Tesseract) | ✅ LANDED |
| Stage 6.5.8 | ADR-065 | Tektos UI kernel mount (HTMX at `/tektos-ui`) | ✅ LANDED (pre-existing) |
| Microfrontend shell | ADR-091 | Tektos-Ultima iframe at `/tektos-ultima` via reverse proxy to `:5556` | ✅ LANDED |
| Stage 7.4 | ADR-099 | `MemoryPort.search_hybrid` on DozerDbMemoryAdapter (H1 skipped) | ✅ LANDED |
| Stage 7.4+1 | ADR-100 | Real `DozerDbLexicalIndex` (Neo4j Lucene fulltext) | ✅ LANDED |
| Stage 7.4+2 | ADR-101 | Kernel-boot lexical wiring | ✅ LANDED |

---

## 4. What genuinely remains

### 4.1 Critical path (blocks a usable coding-agent from kosmos-lms)

1. **Full runtime port-in (Plan Stage 5).** Session FSM, `run_until_complete` multi-iteration agent loop, reflection/synthesis/experience-replay, planner-orchestrator, task-decomposer, coding-agent executor helpers (patch/build/test/commit), manager (guardrails/metrics/archetype), multi-agent orchestrator. **This is the largest single work item.** Without it, `plugins/tektos/` has a scaffold but no autonomous behavior.
2. **The 12 immune detectors (Appendix D item 1).** Only 3 landed at Stage 3.13. Need the remaining 9 including SecretExposureDetector's 12 regex patterns.
3. **The other 3 built-in tools** (`bash`, `directory_create`, `search`) to complete the 7-tool built-in registry.

### 4.2 Endpoint split (Plan Stage 7)

The largest single-integer scope: **154 endpoints across 7 families** (Steps 7.1–7.7), plus deletion of `main.py` (7.8). Each family is one BUILD_LOG entry + one PORTING_LEDGER flip + one contract-test file. This maps to roughly **15–25 sessions of focused work**, likely spanning multiple weeks.

### 4.3 Deployment surface (Plan Stage 8, remaining)

Systemd units (Step 8.4), data-service installers (Step 8.5), merged docs/ports.md (Step 8.6), CI matrix `frontend-tektos-{build,lint}` (Step 8.7). All are shell-script and YAML work, low code but requires user-side Colossus verification (Cloud sandbox cannot exercise systemd or headed Playwright).

### 4.4 Skills DB port (Plan Step 6.6)

Not started. Needs its own ADR (skills DB tier, MemoryPort provenance, `/tektos/api/skills/*` endpoints).

### 4.5 Additional runtime subsystems

`memory/` (Hindsight-adjacent — most already retired by ADR-099; a few utilities remain), `schema_evolution.py`, `db_manager.py` (tier CRITICAL), `gateway_proxy.py` (JSON-RPC 2.0 → envelope translation), `gitops.py`, `metabolism.py`, `recovery.py`, `state_machine.py`, `telemetry/`, `store/`, `search/`, `voice.py` (donor has a `voice.py` module distinct from `adapters/voice/*`; needs reconciliation).

### 4.6 Stage 9 close-out

PORTED.md checklist, sunset markers on donor repos, final PORTING_LEDGER close-out, all ADRs → LOCKED, spec close-out.

---

## 5. Updated Integration Plan v2 — proposed structure

The plan needs a rewrite that: (a) uses the actual v26 numbering already in Build-Sequence-v26; (b) marks landed stages; (c) restructures the remaining work into stages that map to concrete BUILD_LOG entries; (d) accounts for architecture decisions already made (ADR-091 reverse proxy, ADR-099 H1 retirement).

Proposed structure (I will author this as a new document at `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md` once you approve scope):

```
# Kosmos-LMS Integration Plan v2 (2026-09-10 rewrite)

0. Executive summary (with current-state anchor: HEAD e932a02, 1462/0/15 tests, 25 ADRs 077-101)
1. Guiding principles (unchanged — Kosmos discipline authoritative)
2. Repo topology TARGET vs ACTUAL (with the ADR-091 microfrontend shift documented)
3. What's landed (26 completed stages: v26 Stage 0-2.4, 3.1-3.12, 3.13, 4.7, 4.8, 5.6, 6.5, 6.5.8, 7.4/+1/+2, microfrontend)
4. What remains — organized as a NEW SEQUENCE:

   4.A — Runtime completion (Stages 8.1 - 8.7 in v26 numbering)
     8.1  Session FSM + session_state port-in                                 (~1 session)
     8.2  Agent multi-iteration `run_until_complete` + read-only budget wiring  (~1 session)
     8.3  Reflection + synthesis + experience-replay engines                    (~2 sessions)
     8.4  Planner-orchestrator + task-decomposer                                (~1 session)
     8.5  Coding-agent executor helpers (patch/build/test/commit)               (~2 sessions)
     8.6  Manager: guardrails-to-ImmunePort, metrics-to-ObservabilityPort,
          archetype-tracker plugin-internal                                     (~1 session)
     8.7  Multi-agent orchestrator + hierarchical-agent + long-running-agent    (~2 sessions)
     Stage-8 exit gate: agent runs a full autonomous coding session end-to-end

   4.B — Detector + tool coverage (Stage 9)
     9.1  Port 9 remaining immune detectors (incl SecretExposureDetector 12 patterns)
     9.2  Port 3 remaining built-in tools (bash, directory_create, search)
     9.3  Contract tests for full 12-detector + 7-tool DoD
     Stage-9 exit gate: Appendix D items 1, 2, 3 satisfied

   4.C — Skills DB (Stage 10)
     10.1 Author ADR-102 (skills DB provenance tier, /tektos/api/skills/* surface)
     10.2 Port skills subsystem behind MemoryPort provenance='tektos_skill'
     10.3 Pier eval integration for skill improvements
     Stage-10 exit gate: skills round-trip through MemoryPort with Pier scoring

   4.D — Endpoint split (Stages 11.1 - 11.7)
     11.1 Runtime + health + logs + directory (4 endpoints)
     11.2 Memory + hindsight + dreamtime + experience + replay (13 endpoints)
     11.3 Tools + MCP + sandbox + skills (~24 endpoints)
     11.4 Immune + self-repair + self-improvement + probes + thermal +
          telemetry + planner + schema + context (~40 endpoints)
     11.5 Sessions + models + LLM + routing + config + keys + db (~48 endpoints)
     11.6 Vision + voice + MCP-server + plugins + gateways (~15 endpoints)
     11.7 WebSockets (/ws/{session_id} → kernel /api/events/ws;
          /ws/pty → new SandboxPort adapter)
     Stage-11 exit gate: main.py deleted; all 154 endpoints under /tektos/api/*

   4.E — Deployment surface (Stage 12)
     12.1 Systemd unit set (5 units + kosmos-lms.target with Wants=)
     12.2 Data-service installers (Neo4j, Redis; skip Postgres unless user requests)
     12.3 docs/network-ports.md merged (no-0.0.0.0 rule, :9177 forbidden)
     12.4 CI matrix (frontend-tektos-build + -lint; add Playwright leg)
     12.5 Colossus verification pass (user-side, out-of-scope for Cloud sandbox)
     Stage-12 exit gate: kosmos-lms.target boots on Colossus, survives reboot

   4.F — Additional donor subsystems (Stage 13)
     13.1 schema_evolution.py (approval-gated CRITICAL)
     13.2 db_manager.py (CRITICAL tier, ImmunePort SecretExposureDetector on responses)
     13.3 gateway_proxy JSON-RPC 2.0 translation (preserve intact per Appendix D)
     13.4 gitops + git_integration
     13.5 recovery + state_machine helpers
     13.6 store + search + telemetry + metabolism
     13.7 Reconciliation of voice.py donor module with adapters/voice/*
     Stage-13 exit gate: donor src/tektos/ inventory ≤ 5 modules unported;
     each unported module has a PORTED.md-tracked rejection ADR

   4.G — Retirement + freeze (Stage 14)
     14.1 Sunset markers on rmholston420/{tektos-ultima, kosmos}
     14.2 vendor/tektos_ultima/ deletion (if quarantine ever landed — else no-op)
     14.3 All ADRs 077-101+ → LOCKED
     14.4 Spec close-out: Kosmos-Build-Spec-v26 → v27 or freeze
     14.5 Program sign-off entry in BUILD_LOG
     Stage-14 exit gate: PROGRAM COMPLETE

5. Risks + kill switches (unchanged from plan v1)
6. Sequence-of-execution appendix (BUILD_LOG order for the ~30 remaining work items)
7. Appendix A - decision reconciliation (which plan-v1 ADRs got renumbered, which got retired)
```

**Total remaining sessions estimate:** roughly **25-35 focused sessions** (each ~1-3 hours) plus 1-2 Colossus-side verification passes for Stage 12.

---

## 6. Open questions for the user

Before I do any code work, five decisions materially affect the plan:

1. **ADR-091 acceptance.** ADR-091 (2026-09-10) chose reverse-proxy over static-mount for the Tektos-Ultima frontend. This is a permanent architectural fork from plan Step 8.1. **Do you accept ADR-091 as-is** (I document plan Step 8.1 as retired by ADR-091), or **do you want to revisit** (reopen the static-mount option, which would require an ADR-091 amendment or supersedure)?

2. **Sequencing preference: runtime first vs endpoint split first.** The two largest outstanding scopes are runtime completion (Plan-v2 Stage 8, ~10 sessions) and endpoint split (Plan-v2 Stage 11, ~15+ sessions). They are independent. **Which do you want first?**
   - **Runtime first:** gets you a functionally usable coding agent inside kosmos-lms sooner. Endpoint split remains, but the user surface is via the microfrontend proxy (working today), not native `/tektos/api/*`.
   - **Endpoint split first:** gets you the clean architecture and the ability to delete `main.py` sooner. The agent still can't run autonomous coding sessions until Plan-v2 Stage 8 lands.
   - **Interleave:** each runtime subsystem lands with its endpoint family in one slice (e.g., session FSM + session endpoints together). Slower per stage but tighter integration.

3. **Postgres in data-services.** Plan Step 8.5 lists "Postgres 18 + pgvector 0.8.1" but the donor doesn't ship a Postgres installer (only Neo4j + Redis), and Kosmos memory is DozerDB not Postgres. **Drop Postgres from Stage 12.2** (recommended, matches actual dependencies), or **author a stub installer** to match the plan literally?

4. **Colossus verification split.** Stages 12 (systemd/data-services) and parts of 8 (headed Playwright per your preference) cannot be exercised in the Cloud sandbox. **Confirm the split:** I land the artifacts (unit files, installers, CI YAML) on Cloud + push to GitHub; you pull on Colossus and run `systemctl --user daemon-reload` + `install.sh` + headed Playwright to close the DoD. Or do you want a different verification arrangement?

5. **Where to put the updated plan.** Options:
   - **New file** `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md` (preserves v1 as historical, easy diff)
   - **Amend v1 in place** with `> STATUS AMENDMENT (2026-09-10):` blocks at each stage (per Kosmos ADR-amendment convention)
   - **Replace v1** and archive v1 to `docs/plans/archive/`

---

**End of audit.** Zero code or config has been changed in the repo. Workspace is at HEAD `e932a02`, tree clean.
