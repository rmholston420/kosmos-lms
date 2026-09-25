# ADR-116 — LLM primary/failover: llama.cpp :8090 primary, Ollama :11434 fallback

**Status:** Ratified
**Date:** 2026-09-25
**Stage:** v2 Stage 9.4 (post-Stage-9 GPU-share follow-up; discharges the ops note at the tail of the 2026-09-25 GPU-share BUILD_LOG entry)

---

## Context

Since the 2026-09-25 GPU-share hardening, the single llama.cpp `llama-server` on `:8090` (Qwen3.8-27B, `--parallel 2`) is the machine's shared inference server — both the Hermes Agent and Kosmos consume it. The BUILD_LOG entry for that work closed with an open ops note:

> kernel `registry.llm` (OllamaAdapter) still defaults to `:11434` (`KOSMOS_OLLAMA_BASE_URL` unset) — separate from the :8090 shared server; left unchanged here, flagged for a follow-up decision.

The follow-up decision is now made by the operator: **both Hermes Agent and Kosmos-LMS should use the LLM on `:8090` (Qwen3.8-27B) as primary; Ollama is fallback only, engaged when llama.cpp fails.**

Why the kernel could not be repointed via env var alone:

1. `kernel/app.py::_boot_llm` hardwires `OllamaAdapter()` (ADR-063); the kernel has no `LlamaSwapAdapter` boot path.
2. `OllamaAdapter` speaks Ollama's **native** protocol (`/api/generate`, `/api/chat`, `/api/embed`). llama-server exposes only the **OpenAI-compatible** API (`/v1/*`) — `KOSMOS_OLLAMA_BASE_URL=http://127.0.0.1:8090` would produce 404s, not a working lane.
3. `LlamaSwapAdapter` (Stage 1.3, ADR-022 conformance proven) already speaks `/v1/*` and already accepts `base_url` + `KOSMOS_LLAMA_SWAP_BASE_URL` / `KOSMOS_LLAMA_SWAP_DEFAULT_MODEL` overrides — but its defaults are the llama-swap sidecar (`:8080`, `qwen3:14b-q8_0`), neither of which is running on this host.
4. llama-server advertises its model as **`qwen3.8-27b-code`** (verified via `/v1/models`), not the adapter default `qwen3:14b-q8_0` — so a plain repoint would 400 on model-not-found even with the right base URL.

Alternatives considered:

1. **Stop using Ollama entirely; raise the `:8090` concurrency cap and run llama.cpp as the sole lane.** Rejected — Ollama (`qwen3-vl:4b` resident on `:11434`, verified live) is the operator-designated fallback and also serves the vision adapter; a llama.cpp outage would take the Tektos agent down with it.
2. **Env-var repoint only (`KOSMOS_OLLAMA_BASE_URL=:8090`).** Rejected — protocol mismatch (see 2 above).
3. **`KOSMOS_LLM_BACKEND=llama_server` env-gated boot branch selecting one adapter or the other.** Rejected — an either/or selector with no automatic fallback is strictly weaker than the operator's stated requirement ("Ollama is only for fallback *if llama.cpp fails*"), and it would require the operator to notice the failure and flip an env var + restart.

## Decision

### D1 — `FailoverLLMAdapter` (new composite adapter)

`adapters/llm/failover/adapter.py` defines `FailoverLLMAdapter(primary: LLMPort, fallback: LLMPort, *, failback: bool = True)`. It is the **only** code that implements failover policy; the individual adapters remain dumb transports.

- Implements the full `LLMPort` Protocol at runtime (contract test asserts `isinstance(..., LLMPort)`) so every existing consumer (`TektosAgent`, orchestrator, `/api/tektos/turn`, `/api/ollama/status`) holds it unchanged.
- **Failover**: on any `httpx.HTTPError` / `httpx.HTTPStatusError` / `ConnectionError` / `TimeoutError` / `OSError` from the primary → transparently retry the same call on the fallback. Non-HTTP exceptions (e.g. `NotImplementedError` from `pull_model`) propagate — they are not backend failures.
- **Streaming**: `generate_stream` is an async generator, so failover can only engage **before the first delta is yielded** (mid-stream failover would duplicate tokens — rejected by design). After the first yield, errors propagate.
- **Failback**: when `failback=True` (default), the primary is *sticky* until one attempt against it succeeds; each failing call retries the primary first before falling back. This is self-healing: when llama-server restarts, the next call recovers it with zero operator action.
- **Telemetry**: `self.active_backend` ("primary" | "fallback") reflects the backend serving the most recent completed call; `self.failover_count` counts failover events. Non-throwing `is_healthy()` = `primary.is_healthy() or fallback.is_healthy()`.
- `pull_model` / `delete_model`: try primary, `NotImplementedError` → fallback (both backends on this host raise, so the composite raises too — capability parity preserved).
- `close()` closes both sub-adapters; idempotent.

### D2 — `:8090` becomes the kernel's primary LLM by default

`kernel/app.py::_boot_llm` is rewritten:

```
primary  = LlamaSwapAdapter()          # KOSMOS_LLAMA_SWAP_* env or defaults
fallback = OllamaAdapter()             # KOSMOS_OLLAMA_* env or defaults
return FailoverLLMAdapter(primary, fallback)
```

`ops/systemd/kosmos-kernel.local.env` gains the three new vars (values verified live against the server):

```
KOSMOS_LLAMA_SWAP_BASE_URL=http://127.0.0.1:8090
KOSMOS_LLAMA_SWAP_DEFAULT_MODEL=qwen3.8-27b-code
KOSMOS_OLLAMA_DEFAULT_MODEL=qwen3-vl:4b
```

- The third line pins the **fallback model explicitly** (Ollama's default model is `qwen3:14b`, not resident here). This is the one unavoidable consequence of a cross-backend fallback: the fallback lane serves a *smaller, different* model (`qwen3-vl:4b`). It is a degraded but functional lane — exactly the operator's stated intent ("fallback only").
- `KOSMOS_OLLAMA_BASE_URL` stays unset (`:11434` is already `OllamaAdapter`'s default and the live server).
- `adapters/llm/failover/__init__.py` exports the adapter; `adapters/llm/__init__.py` stays empty (consistent with current package style).

### D3 — Env-var override matrix (documented, no new code)

| Var | Default | Effect |
|---|---|---|
| `KOSMOS_LLAMA_SWAP_BASE_URL` | `http://127.0.0.1:8080` | primary base URL (llama-swap sidecar; `:8090` on this host) |
| `KOSMOS_LLAMA_SWAP_DEFAULT_MODEL` | `qwen3:14b-q8_0` | primary default model (`qwen3.8-27b-code` on this host) |
| `KOSMOS_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | fallback base URL |
| `KOSMOS_OLLAMA_DEFAULT_MODEL` | `qwen3:14b` | fallback default model (`qwen3-vl:4b` on this host) |

To disable failover entirely, an operator sets the primary env vars to a dead endpoint — the adapter then serves every call from Ollama, which is the pre-ADR-116 behavior modulo the (now documented) default-model pin.

### D4 — DoD tests (new, contract-style, no live GPU required)

`adapters/llm/failover/test_contract.py` — 12 tests using stub adapters (no network, no GPU):

1. `isinstance(FailoverLLMAdapter(...), LLMPort)` (the load-bearing conformance assertion).
2. Happy path: `generate`/`chat`/`generate_text` served by primary; fallback never touched.
3. Failover on `httpx.ConnectError` from primary → fallback result returned, `active_backend == "fallback"`, `failover_count == 1`.
4. Failback: after a failed primary attempt, the next call **retries primary first** (call-order assertion) and recovers when it succeeds → `active_backend` back to "primary".
5. Both-down: primary and fallback both raise → exception propagates (no silent success).
6. `generate_stream` failover **before first yield** works; post-first-yield error propagates (no duplication).
7. `is_healthy()`: primary down + fallback up → `True`; both down → `False`; never raises.
8. `pull_model`/`delete_model`: `NotImplementedError` from primary → fallback consulted.
9. `close()` closes both sub-adapters exactly once each.
10. Keyword-only signature discipline on the composite's public methods (ADR-022 rule 1 parity).
11. `active_backend` starts `"primary"` and `failover_count` starts `0`.
12. Failover on **4xx model-not-found** (the `qwen3:14b-q8_0` default-model misconfig class of error) → fallback engaged (the exact failure mode D2's env vars prevent on this host).

Plus one kernel-level test in `tests/kernel/`: `_boot_llm` returns an adapter whose `active_backend == "primary"` and whose primary/fallback base URLs are read from the env (monkeypatched, no live servers).

### D5 — Live verification plan (operator-visible evidence)

1. **Primary lane**: `POST /api/tektos/turn` with a trivial prompt → agent response generated through `:8090` (verify via `/v1/chat/completions` request visible in llama-server log / token usage shape), `FailoverLLMAdapter.active_backend == "primary"`.
2. **Failover lane**: temporarily `systemctl --user stop llama-server-8090` → same call succeeds via Ollama `:11434` (`qwen3-vl:4b`), `active_backend == "fallback"`, `failover_count` incremented; `restart llama-server-8090` → next call transparently returns to primary (failback) with no restart of the kernel.
3. **/health**: `registry.llm is not None` stays true throughout (the composite is never `None`; ADR-063 degrade path untouched).

---

## Consequences

- The Tektos agent's main inference lane moves from `:11434` (`qwen3:14b`, 14B) to `:8090` (`qwen3.8-27b-code`, 27B) — a model-quality upgrade on the primary path, which is the operator's stated goal for both Hermes and Kosmos.
- The Ollama lane's role changes from "default primary" to "cold fallback". Its `max_concurrent=1` semaphore (6b952f6) is now a *fallback-shaping* concern, not a primary one; left as-is.
- Fallback generations are materially weaker (4B VL model). Any work that must run on the primary model should treat a fallback-served response as degraded — surfaced via `active_backend`, not hidden.
- `LlamaSwapAdapter` is now load-bearing for llama.cpp (not just llama-swap). Its name is retained for ADR-022/Stage-1.3 continuity; the ADR-009 "llama-swap primary sidecar" framing is superseded on this host by this ADR (llama-swap itself is not running here; the adapter is the OpenAI-`/v1` transport to llama.cpp).
- No new formal port, no new pip dependency (httpx already vendored), no change to `ports/llm.py`.

## Open questions

- Whether to later add **mid-stream** failover with a truncation marker (`[fallback engaged — partial output discarded]`). Rejected for now (token-duplication risk + complexity); would be a follow-up ADR if llama.cpp becomes flaky under load.
- Whether the fallback model should be pinned per-deployment in a config file rather than env var. Out of scope — env var is the established Kosmos config channel (ADR-063, ADR-073 precedent).
