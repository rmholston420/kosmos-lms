# ADR-118 — Kernel-native `/api/llm/status`: top bar shows the ACTIVE LLM lane

- **Status:** Ratified
- **Date:** 2026-09-25
- **Stage:** 11.2 (Endpoint Split — LLM family, first slice)
- **Supersedes:** the top-bar's dependency on ADR-068 D1's `/api/ollama/status`
  (that endpoint is retained unchanged for the Ollama-specific panel)

## Context

Since ADR-116, `registry.llm` is a `FailoverLLMAdapter`:
**llama.cpp `:8090` (`qwen3.8-27b-code`) primary → Ollama `:11434`
(`qwen3-vl:4b`) fallback**, sticky failback. The kernel UI's top-bar
`ModelSwapIndicator` (rendered by `PersistentShell` on every page) still
polled ADR-068 D1's `/api/ollama/status`, which is a raw passthrough to
Ollama `/api/ps` — i.e. it displays *whatever model Ollama happens to
have loaded*. In steady state that is the embedder
`nomic-embed-text:latest`, so the dashboard announced the wrong model at
the most prominent position while the kernel actually routed every
request to llama.cpp `:8090`.

Root cause: ADR-068 D1 predated the failover design and was never
re-pointed.

## Decision

**D1. New kernel-native endpoint `GET /api/llm/status`.**
Reads the *live* `FailoverLLMAdapter` state (`.active_backend`,
`._primary` / `._fallback`) and reports the lane the kernel is
**actually routing through** — no Ollama `/api/ps` passthrough, no
:8020 proxy:

```json
{
  "healthy": true,
  "backend": "llama.cpp",
  "lane": "primary",
  "model": "qwen3.8-27b-code",
  "base_url": "http://127.0.0.1:8090",
  "vram_used_bytes": 31194087424,
  "vram_capacity_bytes": 34190917632,
  "detail": "llama.cpp @ http://127.0.0.1:8090"
}
```

- `backend`: `"llama.cpp"` | `"ollama"` — the transport in use.
- `lane`: `"primary"` | `"fallback"` — the failover lane in use.
- `vram_used_bytes`: **real GPU reading** via `nvidia-smi --query-gpu`
  (async subprocess, 5 s in-process cache, 2 s timeout). `null` when
  unavailable — never fabricated. `vram_capacity_bytes` falls back to
  the known 32 GiB RTX 5090 constant only when the live reading fails.
- Always 200 with `healthy`; `healthy: false` when no LLM registry entry
  exists (detail carries `registry.errors["llm"]`).
- Credential-free by construction (base URL is a localhost port, model
  is a name).

**D2. Top bar repointed.** `ui/components/ModelSwapIndicator.tsx` now
polls `/api/llm/status` (new `LlmStatus` type + `getLlmStatus` in
`kernel-client.ts`). It shows the active lane's model, suffixes
`(fallback)` when the failover pin is engaged, and renders real GPU
VRAM used/total. Same 5 s poll cadence, same degraded-state
behaviour (keep last known value on transport error).

**D3. `/api/ollama/status` unchanged.** The Ollama-specific panel keeps
its ADR-068 D1 endpoint; only the top bar moved.

## Consequences

- The dashboard's most prominent claim (which model is answering) is
  now true by construction — it reflects routing state, not an
  unrelated process's memory contents.
- A real failover to Ollama is now *visible* in the top bar
  (`qwen3-vl:4b (fallback)`), turning a silent degradation into a
  glanceable signal.
- Precedent for the rest of Stage 11: status endpoints report the
  kernel's *own* live state, never a proxied sidecar's.

## Verification (live, Colossus)

- `curl :8000/api/llm/status` → `llama.cpp / primary / qwen3.8-27b-code /
  :8090 / 29.0 GiB used of 32.0 GiB`.
- UI rebuilt (`next build`); served bundle chunk references
  `api/llm/status`; no `nomic` string anywhere in `ui/out/`.
- `tests/kernel/test_stage_11_2_adr_118_llm_status.py` — 4/4 pass
  (primary lane, fallback lane, GPU-reading-unavailable, no-registry).
- Kernel healthy after restart, `boot_errors: {}`.
