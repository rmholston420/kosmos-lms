# ADR-112: Tektos integration — Stage 9.4, native ops page

- **Status:** Ratified (2026-09-24)
- **Stage:** Tektos integration 9.4 (of 9.1–9.5)
- **Supersedes:** — (extends ADR-109, ADR-110, ADR-111)

## Context

ADR-110 (dashboard) and ADR-111 (sessions + chat) cover Tektos's primary
user-facing surfaces. The remaining standalone UI (`:5556`) also exposes
subsystem operations — database maintenance, memory, skills, tools, logs,
GPU telemetry, and the self-repair engine. To retire the iframe bridge in
Stage 9.5 (ADR-105), every capability of the standalone UI must have a
native counterpart.

## Decision

Add `ui/app/tektos-ultima/ops/page.tsx` — a single tabbed operations page
with seven tabs, all driving the standalone Tektos API (`:8020`) through
the ADR-109 kernel gateway (same-origin, no direct `:8020` fetches):

| Tab | Reads | Actions |
|-----|-------|---------|
| Database | `/api/db`, `/api/db/backups`, `/api/db/schema`, `/api/db/analyze` | backup (gzip), optimize, restore (confirm-gated) |
| Memory | `/api/memory`, `/api/memory/stats` | decay (confirm-gated) |
| Skills | `/api/skills`, `/api/skills/stats` | per-skill toggle |
| Tools | `/api/tools` | per-tool enable/disable |
| Logs | `/api/logs` (10 s poll) | level filter + substring filter (read-only) |
| Telemetry | `/api/telemetry` (5 s poll) | client-side rolling history (120 samples) with sparklines |
| Self-Repair | `/api/self_repair/status`, `/api/self_repair/history` | run repair (confirm-gated) |

D1. **Delegation, not reimplementation.** The page is a thin viewer over
   the existing Tektos REST endpoints; no ops logic lives in Kosmos. This
   keeps Stage 9.5 retirement mechanical: if the endpoints exist and the
   tabs render, the standalone UI has no unique capability.

D2. **Null-guarded rendering.** Every upstream body is validated
   (`isObj` / `Array.isArray`) before render, matching the Stage 9.2/9.3
   convention: a shape change degrades one tab to an empty state, never
   the page or the rest of the app.

D3. **Destructive actions are confirm-gated.** Restore, memory decay, and
   repair trigger `window.confirm` first. The Playwright spec (22) is
   strictly read-only — it never clicks an action button — so CI runs
   cannot mutate Tektos state.

D4. **Polling cadence mirrors the standalone UI.** Logs 10 s, telemetry
   5 s, everything else 15 s. Telemetry has no upstream history endpoint,
   so the page keeps a client-side rolling buffer (last 120 samples) for
   sparklines; the buffer resets on navigation, which is acceptable for an
   ops page (no alerting depends on it).

## Consequences

- Upstream bug found and fixed during this stage: `GET /api/db/backups`
  returned 500 because `main.py` called `list_backups()` on the
  `DbManager.backup` **method** instead of the `backup_mgr` attribute
  (Tektos commit `b24f4d6`).
- The dashboard header gains an "Ops →" link (testid
  `tektos-ultima-ops-link`), next to Sessions → and Legacy UI →.
- New spec `ui/tests/22-tektos-ultima-ops.spec.ts` (5 tests, read-only):
  boots on the DB tab with the live `events` schema, lists ≥10 registered
  tools and ≥1 skill, renders live log lines with working level filter,
  shows a live GPU sample (°C + thermal zone), and renders the memory and
  repair tabs. All green against the live kernel + live Tektos backend.
- Remaining standalone-UI parity gap after this stage: none identified
  beyond pages already covered by ADR-110/111/112. Stage 9.5 (iframe
  retirement) can proceed after a final parity sweep.
