# ADR-087 — Hermes LLM topology adapter (CPU planner + GPU coder split)

**Status:** Ratified
**Lock-in phase:** Stage 4.7
**Amends:** ADR-009 (llama-swap primary + router-mode fallback), ADR-022 (LLMPort surface expansion) — extends without removing

## Context

The user's knowledge wiki (entity `hermes-agent`) captures a local agent orchestration pattern already in use on Colossus: a **lightweight CPU control plane** (planner / thinker) that can escalate to a **single large GPU model** (coder / executor) through a localhost GPU/CPU failover endpoint. Tektos-Ultima's planner runs at a different cadence and context budget than its coder; the same fixed-model routing that suits pure-coding workloads is wasteful for planner steps.

`LLMPort` (ADR-022, ADR-054 factory) does not yet expose a `role` dimension. `llama-swap` (ADR-009) can swap models between requests but does not inherently understand planner-vs-coder as roles.

## Decision

Add a **Hermes topology adapter** at `adapters/llm/hermes/adapter.py` implementing `LLMPort` with role-aware routing.

### Adapter contract

- Adapter accepts `role: Literal["planner","coder","reflection","default"]` in the generation-request kwargs (backward compatible: absent = `"default"`).
- Routing table (configuration, not code):
  - `role="planner"` → CPU-hosted small model (default Granite 4.1 or similar CPU-viable candidate per benchmark).
  - `role="coder"` → GPU-hosted large model (per current llama-swap primary; Qwen2.5-Coder-32B or successor).
  - `role="reflection"` → CPU (same as planner) unless a `reflection`-specific override is configured.
  - `role="default"` → falls back to the current llama-swap default.
- Failover: if the CPU model server is unavailable, `planner`/`reflection` requests failover to the GPU model with a `llm.role.failover` envelope on `EventBusPort`. If the GPU model is unavailable during thermal red state (`ThermalPort.pressure() == "red"`), all requests raise (matches ADR-081 rule).
- Adapter is a full `LLMPort` implementation; existing callers unaffected when they omit `role`.

### Backward compatibility

- Existing `OllamaAdapter` and `LlamaSwapAdapter` unchanged.
- Hermes adapter is opt-in via kernel `IDENTITY.toml` routing config: `llm.primary_adapter = "hermes"` selects it.
- ADR-057 Rule 1 (llama-swap-only routing) is respected: Hermes adapter uses llama-swap for the GPU side; the CPU side is a distinct model server (llama.cpp or Ollama on a fixed CPU model).

## Rationale

- **Role dimension over inference-time routing hints**: makes intent explicit and lets the routing table stay configuration.
- **Failover envelopes on `EventBusPort`** so operator dashboards see when the split is degrading.
- **Adapter selection via kernel config** rather than a new kernel switch: Hermes is one of several possible topologies (future: TP shard, model-parallel).
- **Rejected: extend `LLMPort` Protocol with a `role` parameter.** That would ripple into every adapter and every caller; keeping `role` as an optional kwarg (already the shape of `LLMPort.generate` kwargs per ADR-022) is source-compatible.
- **Rejected: separate `PlannerLLMPort` and `CoderLLMPort` ports.** Callers would need to know which port to inject; the current single-port abstraction with `role` hint is simpler.

## Consequences

- Files created (this ADR): none (surface change only; adapter lands Stage 4.7).
- Files planned (Stage 4.7): `adapters/llm/hermes/adapter.py`, `adapters/llm/hermes/routing.py`, `adapters/llm/hermes/test_contract.py`.
- Configuration schema (Stage 4.7): `IDENTITY.toml` gains `[llm.hermes]` section with routing table.
- No change to existing adapters.
- Benchmark decision (Colossus, per user's benchmarking discipline via `local-llm-bench` skill): CPU planner candidate (Granite 4.1 vs alternatives) locked in a Stage 4.7 pre-flight step; result recorded in `PORTING_LEDGER.md`.

## Lock-in phase

Locked at Stage 4.7.

## References

- ADR-009 (llama-swap primary + router-mode fallback)
- ADR-022 (LLMPort surface expansion)
- ADR-054 (LLMPort factory)
- ADR-057 Rule 1 (llama-swap-only routing)
- ADR-081 (ThermalPort — red-state inference refusal)
- Knowledge wiki entity `hermes-agent`
