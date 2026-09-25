# ADR-126: kernel-native `/api/tools` — Tektos Tool Router + capability table

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.10 (endpoint split, tools family)
- **Supersedes:** none

## Context

The Tools card in the Tektos-Ultima dashboard proxied `:8020/api/tools` — the
standalone engine's executable `TektosToolRegistry`: 11 tool descriptors with
JSON schemas, sandbox limits (`timeout`, `max_memory_mb`, `max_cpu_percent`,
`network` policy) and **live usage counters** (`call_count`, `last_call`).
The kernel never boots that registry, so none of it had a kernel referent.

The kernel's real tools surface is the **Tektos Tool Router** (Stage 8.5,
ADR-107):

- A **static capability table** (`_CAPABILITY_TABLE`) mapping 13 known tool
  names → 5 categories (terminal / file_operations / search / web /
  delegation). It is pure data — always available, no gate.
- A **routing-only engine** (`TektosToolRouter`) that maps a natural-language
  task description or a `SubTask.tools_needed` tuple onto a `ToolRoute`
  (primary tool + fallbacks + matched vs. unrouted tools). It is gated by
  `KOSMOS_TEKTOS_TOOL_ROUTER` (default off) and requires `relational_memory`
  to persist route narratives (ADR-107 D1/D9). Routing only — **no execution,
  no approval gateway, no sandbox** (ADR-107 D9 defers the execution/recovery
  state machine). MCP dynamic discovery also deferred.

ADR-107 D9 is explicit: execution (approval + sandbox) is not landed in the
kernel. The executable registry with call counters remains a
**standalone-engine component** — the card must say so honestly rather than
fabricate counters.

## Decisions

### D1 — Enable the router lane

`KOSMOS_TEKTOS_TOOL_ROUTER=on` in `kosmos-kernel.local.env` (gitignored,
local-only). The router boots through the shared `_boot_stage_8_x_engine`
helper (relational_memory + event_bus constructor args only). Its
relational_memory prerequisite is the **same ADR-102 gate already enabled for
Stage 11.9** (`KOSMOS_RELATIONAL_MEMORY=postgres`) — no new dependency.

### D2 — Kernel-native `GET /api/tools` (always-200)

Reads the live `registry.tektos_tool_router` + the static capability table:

```
{
  status: "initialized" | "degraded",
  healthy: bool,
  tools: {
    router: "routing-only (ADR-107 D9 — execution deferred)",
    wired: bool,                 # router booted?
    known_tools: int,            # capability table size (static)
    categories: {cat: count},    # capability table histogram (static)
    known_tool_names: [str],     # sorted
    routes_buffered: int | None, # len(router._buffer) when wired
    recent_routes: [             # router.list_recent(10), serialized
      {id, primary_tool, category, reason,
       matched_tools, unrouted_tools, created_at}
    ],
    execution: "not wired in kernel (standalone Tektos registry)"
  },
  errors: [str],
  timestamp: iso8601
}
```

- `wired: false` (the ADR-107 default) = **valid degraded state**, not an
  error: `healthy: false`, `routes_buffered: None`, empty `recent_routes`.
- The capability table is reported **even when the router is off** (it is a
  static import, not a booted component) — so the card is never empty.
- Route serialization is duck-typed on plugin internals (ADR-007 rule).
- Tracker/router raising → error entry + partial data; **never 500**.
- `routes_buffered` reads the router's private `_buffer` (documented
  read-only introspection, same pattern as the Stage 11.9 tracker `events`).

### D3 — Card re-pointed

`page.tsx`: Tools card `base: ""` (kernel-native, same as the other Stage 11
cards); `parseCard` rewritten for the ADR-126 envelope:

- Line 1: `13 known tools · routing-only`
- Line 2: category histogram (`terminal 3 · file_operations 5 · …`) when
  wired, else `router offline (KOSMOS_TEKTOS_TOOL_ROUTER=off)`
- Detail: `router live · N routes buffered · execution on standalone
  registry (ADR-107 D9)` — honest about the execution gap.

## Verification

- 5/5 tests (`test_stage_11_10_adr_126_tools_stats.py`): degraded (off) with
  real capability-table counts; sorted name list; wired-empty; wired-with-two
  real `ToolRoute`s driven through the actual `TektosToolRouter` (bash
  keyword route + file_read/unknown_tool split); raising-router partial
  degradation. GPU-free, no Postgres, no network.
- Full `tests/kernel/` regression green.
- **Live:** `GET :8000/api/tools` → `healthy: true, wired: true,
  known_tools: 13` with the real histogram, `routes_buffered: 0` (no tasks
  routed yet — honest zero, not fabricated).
- `tsc --noEmit` clean (one pre-existing Playwright-spec error in an
  untouched file); `next build` succeeds.

## Consequences

- The Tools card no longer fabricates `call_count`/`last_call` counters that
  the kernel cannot see.
- The capability table is surfaced as kernel data for the first time.
- When ADR-107 D9 execution lands (approval gateway + sandbox in the
  kernel), the `execution` field flips and `call_count` can be added
  honestly — this ADR leaves that seam explicit.
