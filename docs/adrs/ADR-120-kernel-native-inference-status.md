# ADR-120 — Kernel-native `/api/inference/status` (Inference card re-point)

- **Status:** Ratified
- **Date:** 2026-09-25
- **Stage:** 11.4 (Endpoint Split — inference family)
- **Related:** ADR-118 (`/api/llm/status`), ADR-116 (failover lanes)

## Context

The dashboard **Inference** card (`🧠`) fetched `/api/inference/status`
through the ADR-109 gateway — a pure proxy to the retired standalone
Tektos API at `:8020`. That probe described the *standalone* engine's
view (`base_url: ...:8090/v1`, hardcoded there) and dies with the
standalone backend.

## Decision

**D1. Kernel-native `GET /api/inference/status`.** Probes the **active
lane** of the live `FailoverLLMAdapter` (same source of truth as
ADR-118): llama.cpp lane → `GET /v1/models`, Ollama lane →
`GET /api/version`, ≤3 s bound. The envelope deliberately mirrors the
old standalone shape so `parseCard("inference")` parses it unchanged:

```json
{"status": "active", "model": "qwen3.8-27b-code",
 "base_url": "http://127.0.0.1:8090", "health": "ok",
 "llm_available": true}
```

- `status: active` only when the probe actually succeeds — a down lane
  reports `degraded / health: error / llm_available: false` **while
  still naming the lane** (model + base_url), so the card shows *which*
  engine is down.
- Always 200 (a degraded reading is data, not a transport failure).
- No `/v1` suffix on `base_url` (the adapter stores it bare) — the
  probe appends the path; cosmetic only, no card impact.

**D2. Inference card re-pointed.** `page.tsx` SUBSYSTEMS:
`inference` → `base: ""` (kernel-native root), same endpoint string.
`fetchJson` uses `sub.base ?? GATEWAY`, so `""` is authoritative, not
falsy-coerced. No `parseCard` change.

## Consequences

- The Inference card now reports the kernel's *own* routing reality —
  including a live Ollama-failover state the standalone probe could
  never see.
- One more `:8020` proxy dependency removed from the dashboard.
- `Inference` and the top bar (ADR-118) now share a single source of
  truth: the `FailoverLLMAdapter`.

## Verification (live, Colossus)

- `curl :8000/api/inference/status` →
  `{"status":"active","model":"qwen3.8-27b-code","base_url":"http://127.0.0.1:8090","health":"ok","llm_available":true}`
- Kernel healthy after restart, `boot_errors: {}`.
- `next build` clean; served chunk references the kernel-native route.
- Tests: `tests/kernel/test_stage_11_4_adr_120_inference_status.py` —
  4/4 (primary probe path `/v1/models`, fallback probe path
  `/api/version`, lane-down degraded-with-identity, no-registry).
