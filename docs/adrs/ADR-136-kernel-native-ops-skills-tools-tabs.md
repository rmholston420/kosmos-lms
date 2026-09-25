# ADR-136: kernel-native ops Skills + Tools tabs

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.20 (endpoint split, tools/skills family)
- **Supersedes:** none

## Context

The ops SkillsTab and ToolsTab (`ui/app/tektos-ultima/ops/page.tsx`)
proxied five calls to the standalone `:8020` engine:

- Skills: `GET /api/skills` (24-skill registry list: id/name/category/
  version/description/enabled/usage counters), `GET
  /api/skills/stats`, `POST /api/skills/{id}/toggle`.
- Tools: `GET /api/tools` (executable tool descriptors with
  description + enabled flag), `POST /api/tools/{name}/enable|disable`.

Two of the five already had kernel-native referents from earlier
stages: `/api/skills/stats` (ADR-125 — Tektos Manager archetype
tracker, `KOSMOS_TEKTOS_MANAGER=on`) and `/api/tools` (ADR-126 —
ADR-107 static capability table + routing-only Tool Router,
`KOSMOS_TEKTOS_TOOL_ROUTER=on`). The UI never re-pointed to them and
still rendered the donor's flat `{name, description, enabled}` table
shapes.

The remaining three have **no kernel referent**, and both are
ratified deferrals, not oversights:

- **Skill registry list + toggle** — ADR-108 D9 explicitly defers the
  donor's 830-LOC skill manager; the kernel's skills surface is the
  Manager's *skill-candidate* archetype tracker (recurring task
  patterns at threshold), not an editable registry.
- **Tool enable/disable** — ADR-126 D9: execution (approval gateway +
  sandbox + live call counters) stays on the standalone
  `TektosToolRegistry`; the kernel router is routing-only.

**User precedent (ADR-135, memory, 2026-09-25):** where a donor
surface is policy of one plugin (Tektos) rather than neutral
substrate, the kernel read paths land now and the mutating controls
degrade honestly — no fake stores, no double systems in the kernel.

## Decision

Reframe both tabs to render what the kernel actually has (slice
T1+T2, `c076a76`, UI-only — the endpoints already exist and are
tested by ADR-125/126 suites):

- **T1 — SkillsTab:** single `GET /api/skills/stats` call
  (`base: ""`, kernel-native). Metrics row: `status/healthy/
  archetypes/at_threshold/threshold/events`. Candidate table from
  `skills.archetype_list` (Category/Count/Threshold/Candidate/Last
  seen). `wired: false` → inline degraded-state note
  ("KOSMOS_TEKTOS_MANAGER=off — the donor's 24-skill registry is
  deferred (ADR-108 D9) and not ported"). `errors[]` surfaced in the
  message line. **The toggle button is removed, not disabled:** a
  disabled toggle would imply a store exists that it merely cannot be
  changed; none does in the kernel.
- **T2 — ToolsTab:** single `GET /api/tools` call (`base: ""`).
  Metrics row: `status/healthy/known_tools/categories/
  routes_buffered/router`. Capability-table table (13 tools, ADR-107
  D1, static — renders even when the router is off). `wired: false`
  → degraded-state note ("KOSMOS_TEKTOS_TOOL_ROUTER=off — execution
  stays on the standalone Tektos registry, ADR-126 D9"). **The
  enable/disable buttons are removed, not disabled:** same rationale —
  there is no kernel registry to mutate.

## Honest limits

- Skills: the tab shows *candidates* (tracker state), not an
  executable skill library. The donor's usage counters, versioning,
  improve/prune/dedup/maintenance actions, and skill execution are all
  part of the deferred ADR-108 D9 registry — none is faked here.
- Tools: the capability table is a *known-tool → category* map (13
  tools, 5 categories); the donor's per-tool description, sandbox
  limits, and live call counters live in the standalone registry and
  are not ported. `routes_buffered`/`recent_routes` render only when
  the router is wired.
- Both tabs keep the 15 s poll interval (unchanged from the donor
  tabs).

## Verification

- UI-only slice (endpoints pre-exist): `tsc` + `next build` green
  (22/22 static pages).
- Full `tests/kernel` + `plugins/tektos` + `tests/adapters`
  regression green (exit 0; only the known Colossus-only interactive
  skips).
- Live on restarted kernel (:8000):
  - `/api/skills/stats` → `{"status":"initialized","healthy":true,
    "skills":{"registry":"deferred (ADR-108 D9)","wired":true,
    "archetypes":0,"at_threshold":0,"threshold":3,"total_events":0,
    "archetype_list":[]}}` (manager wired; zero events — honest).
  - `/api/tools` → `{"status":"initialized","healthy":true,
    "tools":{"wired":true,"known_tools":13,
    "categories":{"terminal":3,"file_operations":5,"search":1,
    "web":3,"delegation":1}, …}}` (capability table fully rendered).

## Consequences

- The ops page no longer proxies any skills/tools call to `:8020`;
  its remaining gateway refs are the DB tab (`/api/db/*`) + `/health`,
  a separate family.
- "Skill registry" and "tool execution/enable-disable" are now named
  future deliverables of the ADR-108 D9 / ADR-126 D9 deferrals,
  surfaced honestly in the UI instead of pretending they exist.
- Commit chain: T1+T2 `c076a76` (UI reframe, live-verified) → T3 docs
  (this ADR + README row + BUILD_LOG 11.20).
