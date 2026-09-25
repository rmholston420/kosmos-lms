# ADR-113: Tektos integration — Stage 9.5, native panels page + iframe retirement

- **Status:** Ratified (2026-09-24)
- **Stage:** Tektos integration 9.5 (of 9.1–9.5)
- **Supersedes:** the ADR-091 microfrontend surface (iframe + postMessage
  bridge + `/tektos-ultima/frontend` reverse proxy). Extends ADR-109
  (gateway), ADR-110 (dashboard), ADR-111 (sessions), ADR-112 (ops).

## Context

Stages 9.2–9.4 replaced the ADR-091 single-iframe page with native Kosmos
pages (dashboard, sessions + chat, ops) that drive the standalone Tektos
API (`:8020`) through the ADR-109 kernel gateway. The ADR-091 surface —
`kernel/tektos_ultima_bridge.py` (reverse proxy + postMessage relay),
`ui/components/TektosUltimaBridge.tsx`, the `/tektos-ultima/legacy` page,
and the `frame-ancestors` CSP middleware — was kept mounted as a fallback
until the standalone frontend (`:5556`) had **no unique capability** left.

A full GET-route parity sweep (OpenAPI spec at `:8020`/openapi.json, 82
GET routes) against the four native pages found one residual gap: a set of
deep-subsystem endpoints (hooks, repo map, routing decisions, session
state, tool schemas, skill search/detail, DB table drill-down, archive
sessions) and the root `/health` probe had no native surface.

## Decision

**D1 — Close the parity gap with a native panels page.** Add
`ui/app/tektos-ultima/panels/page.tsx`: a 14-tab read-only status page,
all fetches through `/api/tektos-ultima/gateway/*`.

| Tab | Primary reads |
|-----|---------------|
| Status | `/health` (core row, gateway envelope unwrapped) + subsystem grid |
| Planner | `/api/planner/*` |
| Context | `/api/context/*` |
| Immune | `/api/immune/*` |
| Dreamtime | `/api/dreamtime/*` |
| Metabolism | `/api/metabolism/*` |
| Agents | `/api/agents/*` |
| Self-Imp | `/api/self_improvement/*` |
| Schema | `/api/schema/*` |
| Hindsight | `/api/hindsight/*` |
| Axioms | `/api/axioms/*` |
| Knowledge | `/api/knowledge/*` |
| Config | `/api/config/*` |
| **Drill** | `/api/hooks`, `/api/repoMap/status`, `/api/routing/decide`, `/api/state/{id}`, `/api/tools/schema`, `/api/skills/search` + `/api/skills/{id}` (per-skill View), `/api/db/tables/{name}/sample`+`/analyze`, `/api/archive/sessions` |

The Drill tab is the parity-closing surface: it renders the endpoints that
no earlier page covered, including a skill-search box with per-skill detail
drill and a DB table drill. Every tab is read-only and null-guarded
(`isObj` / `Array.isArray`) per the Stage 9.2–9.4 convention — a shape
change degrades one tab, never the page.

**D2 — Retire the ADR-091 iframe surface.** Delete:
`kernel/tektos_ultima_bridge.py`, `ui/app/tektos-ultima/legacy/page.tsx`,
`ui/components/TektosUltimaBridge.tsx`. Remove their mount from
`kernel/app.py` and the "Legacy UI →" link from the dashboard. The
`/tektos-ultima/legacy` route now 404s.

**D3 — Preserve the CSP hardening.** The `frame-ancestors 'self'` ASGI
middleware survives the retirement and moves into
`kernel/tektos_ultima_gateway.py` as `KosmosCSPMiddleware`, mounted
kernel-wide. Rationale: even with no iframe, no Kosmos page should be
nestable inside a third-party origin. It is a raw-ASGI (send-wrapping)
middleware, so streaming (SSE) responses are not buffered.

**D4 — Retire the standalone frontend + gateway services.** The Tektos
standalone Next.js frontend (`tektos-frontend.service`, `:5556`) and
WebSocket gateway proxy (`tektos-gateway.service`, `:8765`) are no longer
consumed: the dashboard is native and the API is same-origin through the
ADR-109 gateway. Both units are disabled + removed from
`deploy/systemd/user/` (Tektos repo), `tektos.target` now Wants only
backend + hindsight, and `install.sh`/`README.md` are updated to the
three-service stack. The Tektos backend (`:8020`) and hindsight
(`:9000`/`:8095`) are unchanged.

## Consequences

- Parity is complete: after the Drill tab, `/health` probe, and per-skill
  detail, **all 82 GET routes** in the Tektos OpenAPI spec are reachable
  from a native Kosmos page (dashboard, sessions, ops, or panels).
- The dashboard header keeps Sessions →, Ops →, Panels →; the Legacy UI →
  link is gone.
- `ui/tests/20-tektos-ultima-shell.spec.ts` is rewritten: asserts the
  native dashboard (no legacy link), the ADR-109 gateway health envelope,
  that `/tektos-ultima/legacy/` now 404s, and that kernel HTML responses
  still carry `frame-ancestors 'self'`.
- New `ui/tests/23-tektos-ultima-panels.spec.ts` (7 tests, strictly
  read-only): status tab boots with real subsystem rows, planner/agents,
  immune/metabolism, axioms with category filter, hindsight/knowledge,
  the `/health` core row, and the Drill tab (hooks, repo map, routing,
  skill search + skill detail). All green against the live kernel + live
  Tektos backend.
- Kernel-side: the ADR-091 proxy + bridge are gone; the ADR-109 gateway is
  the sole kernel-side Tektos surface. The kernel no longer reads
  `KOSMOS_TEKTOS_ULTIMA_UPSTREAM` or `registry.event_bus` for Tektos.
- Ports `:5556` and `:8765` are freed on Collosus. The Tektos backend on
  `:8020` remains the single source of truth and is unchanged.
- The ADR-045 HTMX plan-approval dashboard at `/tektos`
  (`plugins/tektos/ui/`, `TEKTOS_UI_ROUTE_PATH="/tektos"`, port 8765 in its
  own `ui/policy.py`) is a **separate, still-active Kosmos-native surface**
  and is intentionally untouched by this retirement — its `8765` constant
  is its own reserved-port record (ADR-045 Q1c), not the retired
  `tektos-gateway.service` port.
