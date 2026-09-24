# ADR-110 — Tektos-Ultima Native Dashboard (Stage 9.2)

**Status:** Ratified
**Date:** 2026-09-24
**Supersedes:** — (extends ADR-109's gateway; preserves ADR-091 surface)

## Context

ADR-109 (Stage 9.1) landed the kernel gateway: `/api/tektos-ultima/gateway/*` proxies the standalone Tektos API (`:8020`) with typed degrade envelopes. The user-confirmed integration scope is **native UI first**: replace the ADR-091 single-iframe page at `/tektos-ultima` with real Kosmos pages that drive the Tektos API through the kernel, then retire the iframe + CSP middleware only after parity is verified (Stage 9.5).

Stage 9.2 is the first native page: a subsystem status grid. The standalone Tektos frontend (`:5556`, `frontend/src/app/page.tsx`) is a single-page IDE with 37 panels; the grid is the kernel of the dashboard the user sees first and the foundation Stages 9.3 (sessions/chat) and 9.4 (ops pages) extend.

## Decision

### D1 — Route ownership
`/tektos-ultima` becomes the **native dashboard** (client component, `ui/app/tektos-ultima/page.tsx`). The former ADR-091 iframe page moves **unchanged in behaviour** to `/tektos-ultima/legacy` (`ui/app/tektos-ultima/legacy/page.tsx`), test-ids suffixed `-legacy-*`. The legacy page, the bridge router (`kernel/tektos_ultima_bridge.py`), and `KosmosIframeCSPMiddleware` all stay mounted until Stage 9.5.

### D2 — Data path
All data flows through the ADR-109 gateway (`/api/tektos-ultima/gateway/*`); the page never calls `:8020` directly. Consequences: same-origin (no CORS), the browser sees only the Kosmos origin, and upstream outage degrades to the gateway's 503 envelope — which the page renders as an offline banner plus per-card `degraded`, never a crash (ADR-101 spirit at the UI layer).

### D3 — Subsystem grid
14 cards, each bound to one Tektos status endpoint: immune, thermal, inference, memory, rag, skills, tools, models, plugins, neo4j, postgres, redis, hindsight, self_repair. Each card renders: icon + title + status pill (Healthy/Degraded/Down/pending), two headline lines, one muted detail line. Parse rules are pure functions of the documented upstream shapes (verified live against `:8020` in-session 2026-09-24); an unexpected shape yields a `down` card labelled `unexpected shape` — the grid is resilient to upstream schema drift by construction.

### D4 — Polling + degradation
`Promise.all` fan-out every 10 s (per-card `fetch` failures mark only that card `degraded: unreachable`); an in-flight guard prevents overlapping refreshes; header pill aggregates `healthy/total`. Reachability comes from `GET …/gateway/health` (ADR-109 probe), which also supplies upstream URL, active session count, and LLM model for the header.

### D5 — Styling
Inline styles on the repo's existing oklch design tokens (`--color-surface`, `--color-amoghasiddhi`/`--color-ratnasambhava`/`--color-amitabha` for healthy/degraded/down, `--color-border-soft`, etc.) — dark theme per user preference; no new CSS file, matching the convention of the other native pages.

### D6 — Test surface
`ui/tests/20-tektos-ultima-shell.spec.ts` rewritten: dashboard renders heading/pill/upstream/legacy-link; all 14 cards + status pills visible; gateway health probe returns the ADR-109 typed envelope (200 `{upstream, reachable, status_code}` **or** 503 `{error: tektos_ultima_unavailable}` — CI-safe either way); legacy iframe preserves ADR-089 sandbox + src contract; the four ADR-091 bridge/CSP tests are preserved verbatim (surface unchanged until 9.5). 8/8 green against the live kernel.

### D7 — Explicit deferrals
Sessions/chat (Stage 9.3), ops pages for DB/memory/skills/tools/logs/telemetry/self-repair detail (Stage 9.4), iframe + CSP retirement (Stage 9.5 after parity), engine porting (later phase). No new kernel routes, no new formal port, no PORTING_LEDGER row (UI stage).

## Consequences

- Positive: first-class Kosmos dashboard of the Tektos agent; upstream outage is visible and non-fatal; legacy UI remains available during migration; every claim on the page is parseable from documented upstream shapes.
- Negative: 14 parallel fetches per poll (bounded, read-only, local); legacy page briefly duplicated (retires in 9.5).
