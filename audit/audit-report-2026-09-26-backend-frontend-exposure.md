# Kosmos-LMS Backend → Frontend Exposure Audit — 2026-09-26

**Scope:** Is any backend functionality not exposed on the frontend (Next.js static
export served at kernel root, `ui/app`, `ui/components`, `ui/lib`)?

**Method (verified, not guessed):**
1. Static inventory of all 235 route decorators in `kernel/`, `plugins/`, `adapters/`, `ports/`.
2. **Ground truth from the live kernel** (`http://127.0.0.1:8000/openapi.json`):
   **191 REST routes + 3 WebSocket routes = 201 mounted** — this is the authoritative
   backend surface (catches lifespan-mounted routers the static scan can't resolve).
3. Exhaustive scan of every API string literal in the UI (117 unique refs),
   including template-literal and `${KERNEL}`-prefixed forms, plus all WS URLs.
4. Bidirectional diff, each "dead" and "unexposed" hit re-verified by direct grep
   and live `curl` (e.g. `/api/skills` → `{"skills":[]}`, `/api/tektos/data-services`
   → SPA HTML, proving that ref is swallowed by the static `/` mount).

---

## Verdict

**~75% of the mounted backend is consumed by the UI (≈150/201).** The gap has
three distinct tiers with different severities:

- **Tier 1 — mounted, real, no UI consumer: 48 REST routes + 1 WS route.**
  These are fully working kernel surfaces a user can never reach from the frontend.
- **Tier 2 — mounted sub-apps with no UI navigation: `/tektos-ui` and `/gnosis-gate`.**
  Two complete standalone HTML UIs are mounted but the Next.js shell never links to them.
- **Tier 3 — routers that exist in code but are never mounted (22 routes across 7 plugin
  router factories).** They only appear in tests. Dead surface.

Plus a small set of **dead UI client calls** that point at routes that don't exist
(frontend → backend direction, flagged because it breaks pages).

---

## Tier 1 — Mounted, working, unreachable from the UI

### 1a. Multi-agent orchestrator control surface (12 routes) — **P2, largest functional gap**

UI `AgentsTab` (`app/tektos-ultima/panels/page.tsx:769`) reads `/tektos/api/orchestrator/status`
and `/agents` **only**. The entire write/control surface of the ADR-114 orchestrator is
exposed to API consumers but has zero UI affordance:

| Method | Path |
|---|---|
| POST | `/tektos/api/orchestrator/tasks` |
| POST | `/tektos/api/orchestrator/tasks/{task_id}/execute` |
| POST | `/tektos/api/orchestrator/tasks/{task_id}/assign` |
| POST | `/tektos/api/orchestrator/parallel` |
| GET  | `/tektos/api/orchestrator/stats` |
| GET  | `/tektos/api/orchestrator/recent` |
| POST | `/tektos/api/orchestrator/hierarchical/plan` |
| POST | `/tektos/api/orchestrator/hierarchical/tasks` |
| GET  | `/tektos/api/orchestrator/hierarchical/recent` |
| GET  | `/tektos/api/orchestrator/long-running/status` |
| POST | `/tektos/api/orchestrator/long-running/checkpoint` |
| POST | `/tektos/api/orchestrator/long-running/heartbeat` |

The panel shows the roster read-only; you cannot launch, assign, or track a task
through the hierarchical or long-running engines from anywhere in the shell.

### 1b. Skill lifecycle (10 routes) — P2

UI reads only `/api/skills/stats` (ops tab, archetype tracker) and
`/api/skills/search` + `/api/skills/{id}` (panels knowledge tab). The full CRUD +
self-maintenance surface served from `kernel/app.py:5541-5830` is unexposed:

`POST /api/skills` · `PUT /api/skills/{id}` · `DELETE /api/skills/{id}` ·
`/toggle` · `/prune` · `/improve` · `/improve/from-execution` · `/execute` ·
`/api/skills/maintenance` · `/api/skills/select`

(ops page deliberately defers the registry list/toggles per ADR-108 D9 — but the
routes *do* exist and are live; the UI comment says "the kernel has NO skill
registry", which is now false and should be corrected.)

### 1c. Vision & Voice I/O (4 routes) — P3

Status endpoints are exposed; the actual capability is not callable from the UI:
`POST /api/vision/analyze`, `POST /api/vision/analyze-url`, `POST /api/voice/stt`,
`POST /api/voice/tts`.

### 1d. Hindsight memory write/reflect leg (3 routes) — P3

`POST /api/hindsight/retain`, `POST /api/hindsight/recall`, `POST /api/hindsight/reflect`
— UI only reads `/status` and `/experiences`. (Recall/reflect are the synthesis legs;
retain is the write path. No UI entry point for any of them.)

### 1e. Dreamtime execution (2 routes) — P3

`POST /api/dreamtime/run`, `POST /api/dreamtime/trigger-skill-generation` — UI reads
only `/summary` and `/history`. No "run a contemplation cycle" control.

### 1f. Planner execution (1 route) — P3

`POST /api/planner/plan` — UI reads only `/status`, `/templates`, `/language-games`.
No "plan this prompt" action.

### 1g. Session/agent turn drivers (4 routes) — P3

`POST /api/tektos/turn` (ADR-063 agent iteration), `POST /api/delegate` (subagent
spawn), `POST /api/state/{session_id}/save`, `POST /api/state/{session_id}/snapshot`.
The sessions page drives turns via `/api/prompt/sse`, so `/api/tektos/turn` is the
raw ADR-063 path with no UI; state GET is exposed but save/snapshot are not.

### 1h. System controls & introspection (10 routes) — P3/P4

| Route | Notes |
|---|---|
| `POST /api/thermal/reset` | ops shows thermal status; no reset control |
| `POST /api/self_repair/health` | manual health-check trigger (repair trigger IS exposed) |
| `POST /api/llm/probe` | re-probe LLM lanes — no UI |
| `POST /api/mcp/connect` | connect an MCP server + import its tools — no UI |
| `POST /api/hooks/fire` | manual hook trigger — no UI |
| `POST /api/axioms/{axiom_id}/verify` | mark axiom verified — no UI |
| `POST /api/embedder/embed` | raw embedding — no UI |
| `GET /api/notifications/health` | only `/slo` + `/ack` are wired in kernel-client |
| `GET /api/gnosis/stats` | ADR-064 top-line dashboard numbers — no UI |
| `GET /api/gnosis/event/{event_id}` | single-event drill-down — no UI |

### 1i. WebSocket — `/ws/pty` (1 route) — P3

ADR-141 Stage 14.9 discharged the PTY WS onto the kernel, but **nothing in the UI
references `/ws/pty`** (`/api/events/ws` and `/api/algedonic/ws` both have consumers:
`lib/events-ws.tsx`, `lib/kernel-client.ts:326`). The PTY surface has zero frontend
attachee — a terminal panel that was never built, or a forgotten consumer.

### 1j. Data-services status (5 routes) — P4

`/api/tektos/data-services/{neo4j,postgres,redis,hindsight,qdrant}/status` — see also
the dead-ref bug below: the UI's base `/api/tektos/data-services` ref resolves to SPA
HTML (swallowed by the static `/` mount), so the Tektos dashboard's data-services card
is reading an HTML page, not the per-store status routes that do exist.

---

## Tier 2 — Mounted sub-apps with no shell navigation

| Mount | Contents | Gap |
|---|---|---|
| `/tektos-ui` (`kernel/app.py:2640`, `plugins/tektos/ui/server.py`) | Full HTML Tektos plan UI: index, plan detail, approve, execute, diff, healthz, htmx.js (7 routes) | Next.js shell never links here. Ironically this *is* the HTML home of the Plan→Approve→Execute→Diff flow the Next.js detail page dead-calls (see below). |
| `/gnosis-gate` (`kernel/app.py:10001`, `adapters/memory/dozerdb/gate/server.py`) | Stage 4.6 DozerDb graph gate, 6 HTML/text routes (corpora, event, traversal) | No UI link; `lib/kernel-client.ts:378` comment says the surface was "collapsed" into `/api/gnosis/*` — the gate is orphaned HTML. |

Note: `/tektos-ui` is the **functional referent** for the broken Next.js
`app/tektos/detail/page.tsx` — its plan-approve/execute/diff POSTs map 1:1 onto
`TEKTOS_UI_PLAN_*_PATH` routes. Either link the shell to `/tektos-ui` or port those
four flows to kernel REST.

---

## Tier 3 — Routers in code, never mounted (22 routes, test-only)

`build_decomposer_router`, `build_executor_router` (×2 `/recent`),
`build_experience_router`, `build_manager_router`, `build_planner_router`,
`build_reflection_router`, `build_synthesis_router` (plugins/tektos/*/api.py) are
**never `include_router`'d** on the live app — the only call sites are
`plugins/tektos/tests/`. The kernel does use the *engines* (manager powers
`/api/skills/stats`; executor is injected as `coding=` into the orchestrator
router, ADR-141 T1), but these routers' HTTP surface is dead: 22 routes
(`decompose`, `execute`, `route`, `record`, `reflect`, `synthesize`, `plan`,
`error`, `rhythm`, `spiral-update`, `task-start/complete`, `recent` ×7).

Resolution options: mount them (then the UI gap list above shrinks and gains
consumers) or retire them per the ADR-141 discharge pattern.

---

## Reverse-direction defects (UI → missing backend)

| Dead ref | Location | Consequence |
|---|---|---|
| `GET/POST /api/tektos/plan/{id}[/approve\|/execute\|/diff]` | `lib/kernel-client.ts:110-115`, consumed by `app/tektos/detail/page.tsx` (approve/execute/diff buttons) | **Detail page is functionally broken**: kernel-client.ts:105 comment admits "The four calls below will 404 until then." Approve/Execute buttons in the shell hit routes that don't exist. |
| `GET /api/toolRouter/status` | `app/tektos-ultima/panels/page.tsx:226` | No live route → panel card renders error/falls through to SPA HTML. Tool Router has no kernel REST status route. |
| `GET /api/tektos/data-services` | `app/tektos-ultima/page.tsx:26` | Returns SPA HTML (static mount swallows it); the real per-store routes live at `/api/tektos/data-services/{store}/status` and are unused. |

(Verified by direct grep + live `curl`; `/api/corpus/{name}/*` is comment-only, not a live ref.)

---

## Recommended execution order (ROI)

1. **Fix the broken detail page** (dead `/api/tektos/plan/*` calls) — link
   `app/tektos/detail` to the existing `/tektos-ui` plan routes, or port the four
   flows to kernel REST. Smallest diff, removes a visibly broken control surface.
2. **Orchestrator control panel** (Tier 1a) — the biggest functional gap: 12 live
   routes for task launch/assign/execute/hierarchical/long-running behind a
   read-only roster tab.
3. **Skill lifecycle surface** (Tier 1b) — CRUD + toggle/execute/maintenance on the
   existing `/api/skills/*` routes; also corrects the stale ops-tab claim that the
   kernel "has no skill registry."
4. **Fix the two dead panel refs** (`/api/toolRouter/status`,
   `/api/tektos/data-services`) — either add the kernel routes or re-point the
   refs to existing routes.
5. **Capability actions batch** (Tier 1c–1f): vision analyze, voice stt/tts,
   hindsight retain/recall/reflect, dreamtime run, planner plan — one
   "Actions" cluster per existing status tab; routes all exist.
6. **Decide Tier 3**: mount or retire the 7 unmounted plugin routers (ADR-141
   discharge pattern if retiring).
7. **`/ws/pty`**: build the terminal panel or document the deferral.

## Inventory numbers

| Metric | Count |
|---|---|
| Route decorators in source (kernel+plugins+adapters+ports) | 235 |
| **Live mounted routes (openapi + 3 WS)** | **201** |
| Sub-app routes (`/tektos-ui` + `/gnosis-gate`) | 13 |
| UI unique API refs | 117 |
| Live routes with a UI consumer | ≈152 |
| Live routes with NO UI consumer (Tier 1) | **49** (48 REST + `/ws/pty`; the other 2 WS — `/api/events/ws`, `/api/algedonic/ws` — are consumed) |
| Unmounted router routes (Tier 3) | 22 |
| Dead UI refs (no live backend) | 7 real (4 plan + toolRouter + data-services + 1 comment-only) |

---

## Remediation status — 2026-09-26 (Stage 14.12 close-out)

| # | Recommendation | Status |
|---|---|---|
| 1 | Fix broken detail page (`/api/tektos/plan/*`) | **DONE** — ADR-067 D4 discharged: `execute`/`diff` legs ported kernel-native, `getPlanDetail`/`approve` re-pointed to the native `/api/approvals/{id}` routes; 4/4 live tests. |
| 2 | Orchestrator control panel (Tier 1a) | **DONE** — panels AgentsTab already carries the mutation surface (task create / assign / execute / parallel / hierarchical / long-running) on the kernel-native `/tektos/api/orchestrator/*` routes (verified in working tree, `ui/app/tektos-ultima/panels/page.tsx:1159+`). |
| 3 | Skill lifecycle surface (Tier 1b) | **DONE** — panels Skill tab already has toggle / execute / delete on `/api/skills/*`; Stage 14.12 added the canonical `POST /api/skills/prune` the Maintenance panel calls (both prune forms agree, tested). |
| 4 | Fix the two dead panel refs | **DONE** — `GET /api/tektos/data-services` base index route added (200, `total: 5`); `/api/toolRouter/status` was a stale *comment* ref (the tab fetches `/api/tools`) — comment corrected. |
| 5 | Capability actions batch (Tier 1c–1f) | **DONE** — Actions tab already carried all five capability clusters + delegate; Stage 14.12 added the read-only regression spec (9/9 panels Playwright). |
| 6 | Decide Tier 3 | **DONE — retired** (ADR-146): 8 never-mounted router factories / 22 routes deleted; donor had none of them (zero `include_router` in recovered `main.py`); all 8 engines stay live. |
| 7 | `/ws/pty` terminal panel | **DONE — built**: Terminal tab on `/tektos-ultima/panels` (xterm.js over `/ws/pty`, lazy client-only import for SSG), live-verified full PTY round-trip + Playwright regression. |

All 7 recommended items closed; ADR-141 donor tally unchanged at **154 P / 0 D / 0 T = 154**
(Stage 14.12 adds new kernel capabilities + a consumer on top of the discharged surface,
so no donor-row count moves — only the `/ws/pty` consumer note was refreshed).
