# ADR-104 — Tektos Turn Loop: Session + LLM + Sandbox + Resource integration

**Status:** Ratified v25
**Lock-in phase:** Stage 8.2
**Supersedes:** — (extends ADR-092 §3 which landed the Stage 3.13 pre-LLM skeleton)

## Context

Stage 3.13 (ADR-092 §3) landed `plugins/tektos/runtime/turn_loop.py::TektosTurnLoop` as an **event-driven pre-LLM slice** wired to three ports: `ImmunePort` (prompt + tool-call gating), `LoopSafetyPort` (turn budget + ADR-088 read-only interlock), and `ThermalPort` (hot-path pressure). The Stage 3.13 loop deliberately excluded LLM inference, sandbox execution, session lifecycle mutation, and resource arbitration — those were called out as "Stage 4.7 and later" in the module docstring.

The Stage 8.2 donor audit (`docs/stage-8-2-donor-audit.md`) confirmed that the donor `RuntimeSDK._stream_llm` (`tektos-ultima/src/tektos/runtime/sdk.py`, 1471 lines) touches **11 collaborators**, **9 of which are Kosmos ports already**. The donor loop's 7 raw `session.status = …` writes and its `HookRegistry.run("session.start"/"complete"/"fail")` fire sites map 1:1 onto:

- `SessionPort.start_turn` / `complete_turn` / `fail_turn` / `interrupt_turn` (Stage 8.1, ADR-103)
- `EventBusPort.publish(EventEnvelope(event_type="session.<lifecycle>", …))` (ADR-023)

The audit's kill-switch review (clause carried forward from ADR-103) established that `_stream_llm` **cannot** be a fidelity port — vendoring it violates ADR-007 (cross-plugin imports), ADR-023 (raw `append_event`), and ADR-029 (raw `MetabolismEngine` bypasses ResourcePort). The correct action is to **grow the Stage 3.13 loop** with the four missing port integrations (SessionPort, LLMPort, SandboxPort, ResourcePort) while preserving the donor's behaviour invariants (audit §7). This ADR locks that decision.

## Decision

**D1 — Scope.** Stage 8.2 grows `plugins/tektos/runtime/turn_loop.py::TektosTurnLoop` — the same class landed at Stage 3.13 — with four new **optional** port collaborators: `SessionPort`, `LLMPort`, `SandboxPort`, `ResourcePort`. Every new collaborator is optional (defaults to `None`); the Stage 3.13 pre-LLM slice remains callable with zero new deps bound. Stage 8.2 does not introduce a new class or a new plugin file. It does not add a new formal port. It does not modify the four already-wired ports (Immune, LoopSafety, Thermal, EventBus).

**D2 — SessionPort integration.** When `session_port` and `session_id` are both provided to `run_turn`, the loop:

- calls `await session_port.start_turn(session_id, reason="tektos.turn")` **before** the immune prompt scan (so a blocked-by-immune outcome fails the turn properly);
- calls `await session_port.complete_turn(session_id, reason=stop_reason)` on the normal-completion path (`stop_reason == "completed"`);
- calls `await session_port.fail_turn(session_id, reason=stop_reason)` on every non-completion stop reason (`immune_blocked_prompt`, `immune_blocked_tool_call`, `thermal_red`, `loop_exhausted`, `loop_repetition`, `budget_exhausted`, plus new `llm_error`, `sandbox_error`, `resource_exhausted`);
- exposes a new `TektosTurnLoop.interrupt(session_id)` method that calls `await session_port.interrupt_turn(session_id, reason="external")` — the external interrupt surface (mirrors donor `RuntimeSDK.interrupt`).

When either `session_port` or `session_id` is missing, all four calls are skipped (Stage 3.13 semantics preserved).

**D3 — LLMPort integration.** When `llm` is provided, the loop calls `await llm.generate(prompt=prompt, system=system_prompt, **options)` **once** per `run_turn` invocation — a single non-streaming inference. The result is stored on `TurnOutcome.llm_response: dict[str, Any] | None`. On any `Exception` raised by `llm.generate`, the loop stops with `stop_reason="llm_error"` and the exception message is captured in `TurnOutcome.error`. Streaming, tool-call routing, and the multi-round agent loop (donor `while True:`) are **explicitly deferred** — see D9.

**D4 — SandboxPort integration.** When `sandbox` is provided, each `ToolCallSpec` with a non-`None` `.sandbox_request: SandboxRequest` gets executed via `await sandbox.run(request)`. The `SandboxResult` (exit_code, stdout, stderr, wall_seconds, peak_memory_mb, killed_by) is attached to the corresponding `ToolCallOutcome.sandbox_result` field. When `sandbox` is `None` or `spec.sandbox_request` is `None`, no execution happens (the tool is still budget-accounted via `LoopSafetyPort.record_tool_call`). Sandbox exceptions stop the turn with `stop_reason="sandbox_error"`.

**D5 — ResourcePort integration.** When `resource` is provided, the loop performs a **post-turn** best-effort check: `await resource.can_allocate(ResourceKind.COMPUTE, Decimal("1"))`. If the check returns `False`, the turn's `TurnOutcome.resource_exhausted` field is set to `True` (informational — the turn itself has already completed; the flag advises callers). The loop does **not** perform pre-turn `allocate` at 8.2 — priority-queue arbitration on the *submission side* is a Stage-8.7 concern once the multi-agent orchestrator lands. Resource exceptions are logged and swallowed (fail-open on informational check).

**D6 — Event fan-out changes.** Two new `tektos.agent.turn.*` event types land at 8.2:

- `tektos.agent.turn.llm_completed` — published after `llm.generate` returns, with payload `{agent_id, session_id?, model, latency_ms, response_length}`.
- `tektos.agent.turn.sandbox_completed` — published per successful sandbox run, with payload `{agent_id, session_id?, tool, exit_code, wall_seconds, killed_by?}`.

All existing Stage 3.13 events (`tektos.agent.turn.started`, `.tool_call`, `.blocked`, `.completed`) are unchanged in shape. When a `session_id` is bound, every published payload also carries `"session_id"` for correlation.

**D7 — HookRegistry disposition (audit §9 Q1).** The donor `runtime/hooks.py` (325-line `HookRegistry`) is **rejected**. Its `session.start` / `session.complete` / `session.fail` fire sites are subsumed by the SessionPort transitions in D2 and by the EventBus publishes in D6. No `HookPort` is introduced; user extensibility rides the existing `EventBusPort` subscription mechanism.

**D8 — Read-only tool budget disposition (audit §9 Q2).** The ADR-088 read-only budget already lives inside `TektosLoopSafetyAdapter` (per its own docstring). No new state on `TektosTurnLoop`. The donor's `_readonly_tool_rounds` / `_readonly_tools_disabled` / `_readonly_nudge_sent` triple is superseded by the loop-safety adapter's per-turn budget and terminal-status enum (`budget_exhausted` already handled at 3.13).

**D9 — Explicit exclusions (deferred to later stages).** The following donor `_stream_llm` capabilities are **out of scope** at 8.2:

- Streaming LLM output (`generate_stream`) and its multi-round agent `while True:` — Stage 8.3+ (reflection loop consumes streaming).
- Tool-call routing from LLM responses to sandbox execution — Stage 8.3+ (needs the multi-round loop).
- RAG retrieval, planner orchestrator, hierarchical agent, multi-agent orchestrator, repo-map generator, tool router, task decomposer, context curator, context compactor, LLM failover — Stages 8.3–8.7 as scheduled in Plan v2.
- `SessionPort.LiveSession` mutation of `attached_clients` / `resume_session_id` / `fork_session_id` — Stage 8.3+ (session-aware conversations).
- Per-session `asyncio.Lock` (donor `_session_locks` dict) — deferred to Stage 8.3 when multi-turn same-session flows land; at 8.2 each `run_turn` call is independent and the caller owns concurrency.

**D10 — Kernel wiring.** Add `_boot_tektos_turn_loop` to `kernel/app.py` immediately after `_boot_session` and before `_boot_gnosis_seeder`. Env-gate: `KOSMOS_TEKTOS_TURN_LOOP={off,on}` (default `off`). When `on`, the boot function constructs `TektosTurnLoop(immune=..., loop_safety=..., thermal=..., event_bus=registry.event_bus, session_port=registry.session, llm=..., sandbox=..., resource=...)`, pulling every collaborator from the registry with `None` when the source slot is unset. The loop is stored at `registry.tektos_turn_loop`. When any *required* Stage 3.13 collaborator (immune / loop_safety / thermal) is missing, boot logs a WARNING and leaves `registry.tektos_turn_loop=None` — ADR-101 degrade pattern.

**D11 — TektosPlugin dataclass.** `plugins/tektos/plugin.py::TektosPlugin` grows one optional field: `turn_loop: TektosTurnLoop | None = None`. The field is populated at kernel-boot time (D10). No public API of the plugin changes at 8.2; the field exists so Stage 8.3+ code paths can reach the loop through the plugin object. The Stage 3.7 descriptor registration behavior is unchanged.

## Rationale

The Stage 3.13 loop and the LoopSafety adapter already carry the load-bearing invariants (turn accounting, budget, repetition, thermal, immune) — extending the same class through optional-collaborator injection is the smallest possible change that satisfies the Stage 8.2 DoD without disturbing 3.13 tests. Every alternative considered was strictly worse:

- **Rewriting from scratch under a new `TurnController` class** would duplicate ~200 lines of already-tested immune/thermal/loop-safety wiring and force a follow-on ADR to delete `TektosTurnLoop`. Rejected.
- **Vendoring `_stream_llm` as a fidelity port** violates ADR-007 + ADR-023 + ADR-029 by construction (audit §5 + §6). Rejected.
- **Making the four new ports required (non-optional)** would break the Stage 3.13 test surface (11 tests currently pass without any of them). Rejected.
- **Pre-turn `ResourcePort.allocate` with priority-queue enqueue** would move Stage 8.7 orchestrator concerns into 8.2. Rejected.
- **Streaming LLM at 8.2** requires the multi-round tool-call loop from donor `_stream_llm`, which requires a tool router, which requires task decomposition — the whole 8.3–8.5 stack. Rejected; the single non-streaming `generate` call is the smallest LLM slice that proves the LLMPort integration without pre-empting downstream stages.

## Consequences

**Files changed:**

- `plugins/tektos/runtime/turn_loop.py` — `TektosTurnLoop.__init__` grows four keyword-only optional args (`session_port`, `llm`, `sandbox`, `resource`); `run_turn` grows an optional `session_id` kwarg + an optional `system_prompt` kwarg + optional `llm_options: dict` kwarg; the internal flow gains SessionPort transitions (D2), a single LLM call (D3), per-tool sandbox execution (D4), and post-turn resource check (D5); two new event types (D6); `interrupt(session_id)` method added.
- `plugins/tektos/runtime/turn_loop.py` — `TurnOutcome` dataclass grows three new frozen slots: `llm_response`, `resource_exhausted`, `error`. `ToolCallSpec` grows one new frozen slot: `sandbox_request`. `ToolCallOutcome` grows one new frozen slot: `sandbox_result`. New `TurnStopReason` literals: `llm_error`, `sandbox_error`.
- `plugins/tektos/runtime/test_turn_loop.py` — additive tests for every new integration path (D2, D3, D4, D5, D6, D11 dataclass slot) plus a golden-path integration test that binds all four new ports at once.
- `plugins/tektos/plugin.py` — `TektosPlugin` grows optional `turn_loop` field per D11.
- `kernel/app.py` — new `_boot_tektos_turn_loop` per D10; new `_BootRegistry.tektos_turn_loop: Any = None` slot.
- `tests/kernel/test_stage_8_2_tektos_turn_loop_wiring.py` — new; ~7 fast tests covering unset / off / on-with-full-registry / on-with-missing-immune / on-with-only-session / boot-order.
- `docs/adrs/ADR-104-tektos-turn-loop-session-and-llm-integration.md` — this file.
- `docs/adrs/README.md` — ADR-104 row appended.
- `docs/Kosmos-Build-Spec-v26.md` — §17 ADR-104 row appended after ADR-103.
- `docs/Kosmos-Build-Sequence-v26.md` — Stage 8.2 stanza appended after Stage 8.1.
- `PORTING_LEDGER.md` — no vendor entry required (this is a port-consuming extension of a Kosmos-owned file, not a vendor port).
- `BUILD_LOG.md`, `KNOWN_ISSUES.md`, `SESSION_HANDOFF.md` — updated per `kosmos-log-maintenance` skill.

**Preserved invariants:**

- ADR-007: `TektosTurnLoop` imports only `ports.*` and `plugins.tektos.*`; no cross-plugin imports.
- ADR-008: any future MemoryPort write from the loop must carry `provenance` + `confidence`; no such writes at 8.2.
- ADR-023: envelope-first `EventBusPort.publish` upheld (all new events use `EventEnvelope`).
- ADR-029: ResourcePort is consulted, not bypassed (D5). No raw `MetabolismEngine`.
- ADR-088: read-only budget enforcement stays inside `TektosLoopSafetyAdapter`.
- ADR-092: Stage 3.13 event-shape backward compatibility — every existing `tektos.agent.turn.*` event type is unchanged.
- ADR-101: `_boot_tektos_turn_loop` follows the degrade pattern.
- ADR-103: SessionPort transitions are consumed via the formal port; no direct `session.status = …` writes.

## Lock-in phase

Stage 8.2. This ADR is amendable at Stage 8.3 to unlock streaming + multi-round agent loop; any such amendment must ship as ADR-104-amendment (`> **STATUS AMENDMENT**` block) or as a superseding ADR.

## References

- `docs/stage-8-2-donor-audit.md` — full audit + kill-switch review
- ADR-092 (Stage 3.13 turn-loop skeleton — this ADR extends it)
- ADR-103 (SessionPort — consumed here)
- ADR-023 (EventBusPort envelope contract)
- ADR-029 (ResourcePort priority arbitration)
- ADR-088 (read-only tool budget)
- ADR-101 (degrade-pattern for optional kernel-boot collaborators)
- Donor `tektos-ultima/src/tektos/runtime/sdk.py::RuntimeSDK` (referenced, not vendored)
