# ADR-119 — Kernel-native model catalog on `/api/llm/status` (Models card re-point)

- **Status:** Ratified
- **Date:** 2026-09-25
- **Stage:** 11.3 (Endpoint Split — models family)
- **Extends:** ADR-118 (`/api/llm/status`)

## Context

The dashboard **Models** card (`🎛️`) fetched `/api/models` through the
ADR-109 gateway — a pure proxy to the retired standalone Tektos API at
`:8020`. That catalog described a *different* machine's lanes (incl.
`granite4.1-8b-instruct` on `:8092`, a standalone-only CPU fallback) and
would go stale or dead the moment the standalone backend is turned off.

## Decision

**D1. `models` array on `/api/llm/status`.** Built from the *live*
`FailoverLLMAdapter` state (same source of truth as ADR-118's active
lane), one entry per lane:

```json
"models": [
  { "id": "qwen3.8-27b-code", "name": "qwen3.8-27b-code",
    "lane": "primary",  "backend": "llama.cpp",
    "endpoint": "http://127.0.0.1:8090",
    "active": true,  "recommended": true },
  { "id": "qwen3-vl:4b", "name": "qwen3-vl:4b",
    "lane": "fallback", "backend": "ollama",
    "endpoint": "http://127.0.0.1:11434",
    "active": false, "recommended": false }
]
```

`active` tracks the failover pin (so the card follows a real failover);
`recommended` marks the primary lane. No new route — the Models card
reuses the already-polled ADR-118 endpoint (zero extra round-trips).

**D2. Models card re-pointed.** `page.tsx` `SUBSYSTEMS`:
`models` → `/api/llm/status`; `parseCard` reads the nested `models`
array, preferring the `active` lane, then `recommended`. Card now shows
`N lanes` + the active model + its backend.

## Consequences

- The model list can no longer disagree with what the kernel routes
  through — it *is* the routing table.
- The `:8020` proxy becomes one dependency lighter for the dashboard.
- `recommended`/`active` semantics: primary is always recommended;
  `active` flips only on failover — the card will visibly show the
  fallback model riding during a llama.cpp outage.

## Verification (live, Colossus)

- `curl :8000/api/llm/status` → both lanes present, primary
  `active: true / recommended: true`, endpoints `:8090` / `:11434`.
- UI rebuilt (`next build` clean); `tsc` clean (pre-existing Playwright
  spec error only).
- Tests: `tests/kernel/test_stage_11_2_adr_118_llm_status.py` now 6/6
  (added: both-lane catalog shape; `active` follows failover pin).
