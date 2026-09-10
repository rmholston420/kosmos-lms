# Stage 8.2 Donor Audit — Tektos-Ultima Turn Loop

**Audit date:** 2026-09-10 05:41 EDT
**Auditor:** Kosmos-LMS integration
**Donor workspace:** `/home/user/workspace/audit/tektos-ultima/src/tektos/`
**Workspace identity:** `f9fcf03a11a2e6286c164c610e3d461fc0df86dff61d9966c84ac21c120fb1fa` (Cloud)
**Target port:** SessionPort (Stage 8.1, ADR-103) — this stage adds the **turn loop** that drives it.

---

## 1. Naming reality check

The Plan v2 phrase "port `src/tektos/runtime/turn_loop.py`" **does not describe donor reality**. No file named `turn_loop.py` exists in the donor. The turn loop is a **method** on `RuntimeSDK` (`runtime/sdk.py`), not a standalone module:

```
runtime/sdk.py  — 2607 lines
  class RuntimeSDK
    submit_prompt(...)     # line 684  — 1-turn entry point
    _stream_llm(...)       # line 804  — 1471 lines  ← the actual turn loop
    _handle_tool_completion(...)  # line 2274 — 256 lines
    _execute_tool(...)     # line 2529
    _check_resources(...)  # line 2557
    interrupt(...)         # line 2597
```

`submit_prompt` = one turn. `_stream_llm` = the `while True:` LLM ↔ tools ↔ LLM inner loop **inside** that turn, including RAG retrieval, planner call, hierarchical-agent split, tool-router preflight, immune-system prompt-injection check, context curation, task decomposition, loop-safety enforcement (turns/tokens/wall-time/repetition), tool-call loop guard (SHA-256 pattern), streaming SSE parse, tool-approval callback, and event fan-out.

**Consequence:** Stage 8.2 is **not** a straight-line file port. It is a **decomposition slice** — the 1471-line `_stream_llm` must be broken apart into a small kernel-owned turn controller plus a handful of ports the sub-features already exist on (or need to exist on) in Kosmos.

---

## 2. Surface inventory — what the donor turn loop touches

Grepping `session.status = …` and `append_event(…)` inside `sdk.py` yields the full mutation surface:

| Line | Mutation | Meaning under SessionPort (Stage 8.1) |
|---|---|---|
| 714 | `session.status = "running"` | `SessionPort.start_turn(session_id)` |
| 754 | `session.status = "failed"` (timeout branch) | `SessionPort.fail_turn(session_id, reason="…timeout…")` |
| 770 | `session.status = "failed"` (exception branch) | `SessionPort.fail_turn(session_id, reason=str(exc))` |
| 784 | `session.status = "ready"` (success branch) | `SessionPort.complete_turn(session_id)` |
| 855 | `session.status = "failed"` (prompt-injection detected) | `SessionPort.fail_turn(session_id, reason="prompt injection …")` |
| 1420 | `session.status = "failed"` (mid-stream failure) | `SessionPort.fail_turn(session_id, reason=…)` |
| 2600 | `session.status = "interrupted"` | `SessionPort.interrupt_turn(session_id, reason=…)` |
| 714 | `session.updated_at = _time.monotonic()` | Handled by `SessionPort` on each transition. |

**All 7 status-mutation call sites map 1:1 onto the four SessionPort turn verbs** that landed at Stage 8.1 (`start_turn` / `complete_turn` / `fail_turn` / `interrupt_turn`). Zero raw `session.status = …` writes remain after the port-consuming rewrite.

The 12 `append_event(…)` call sites inside the turn loop are **event-stream writes**, not lifecycle transitions — they publish `assistant.delta`, `tool.started`, `tool.completed`, etc. into the SQLite event store. These map to `EventBusPort.publish(EventEnvelope(…))` (ADR-023 envelope-first shape), same shim pattern the Stage 8.1 vendor uses. The durable SQLite event store itself remains deferred to Stage 13 per ADR-103 D3.

---

## 3. Dependency graph — what Stage 8.2 must consume

`RuntimeSDK.__init__` takes **11 collaborators**. Mapping each to Kosmos port status:

| Donor collaborator | Kosmos port status | Stage 8.2 disposition |
|---|---|---|
| `llm_base_url` + `llm_model` (httpx client) | `LLMPort` (existing, Stage 1.7 llama-swap adapter) | **CONSUME** via port; drop `httpx.AsyncClient` from the loop |
| `session` (`LiveSession` mutation) | `SessionPort` (Stage 8.1, ADR-103) | **CONSUME** — the point of this stage |
| `append_event(…)` (SQLite event_store) | `EventBusPort` (Stage 1.4, ADR-023) + Stage 13 durable store | **CONSUME** bus; store still deferred |
| `LoopSafetyMonitor` (turns/tokens/wall/repetition) | **`LoopSafetyPort` — already listed as port #24 in v25** | **CONSUME** — port exists in surface; adapter must land this stage or ride donor `loop_safety.py` as a fidelity port |
| `ToolCallLoopGuard` (SHA-256 pattern) | **NOT a formal port** — internal component of loop-safety substrate | **PORT-IN as internal collaborator** of the LoopSafety adapter (donor `loop_guard.py`, 113 lines, verbatim) — or absorb into the same adapter as a helper |
| `SandboxProvider` (bash tool execution) | `SandboxPort` (Stage 1.5) | **CONSUME** — drop donor `SandboxProvider` in favor of the port |
| `ImmuneSystem` (prompt-injection, threat detection) | `ImmunePort` (Stage 9 target) | **DEFER call site** — leave the immune check as an optional `immune: ImmunePort \| None = None` collaborator; call only when bound. Landing the immune adapter proper is Stage 9. |
| `MetabolismEngine` (resource monitoring) | `ResourcePort` (Stage 1.9, ADR-029) | **CONSUME** via ResourcePort's `check_resources()` |
| `_context_compactor` / `_context_curator` / `_planner_orchestrator` / `_hierarchical_agent` / `_multi_agent_orchestrator` / `_repo_map_generator` / `_tool_router` / `_task_decomposer` | No ports yet — spec §18 lists these as later-Tektos capabilities | **DEFER** — Stage 8.2 lands the loop with **zero** of the "high-ROI" collaborators wired (all constructor slots default to `None`). Each lights up in its own stage (8.3 reflection, 8.4 planner, 8.5 executor, 8.6 manager, 8.7 multi-agent) per Plan v2. |
| `HookRegistry` (`_fire_hook("session.start" / "session.fail" / "session.complete")`) | No formal port — this **is** the EventBusPort in Kosmos terms | **REPLACE** — hook fires become `EventBusPort.publish(EventEnvelope(producer_plugin="tektos.turn", event_type="session.start"/"session.fail"/"session.complete", …))`. Delete the donor `HookRegistry` from the ported path; its function is subsumed. |

**Bottom line:** Stage 8.2 needs `LLMPort` + `SessionPort` + `EventBusPort` + `SandboxPort` + `ResourcePort` + `LoopSafetyPort`. Six ports, all of which already exist as formal contracts in v25. Plus one optional slot (`ImmunePort`) that stays `None` until Stage 9.

---

## 4. LoopSafetyPort adapter — the hidden Stage 8.2 sub-slice

`ports/loop_safety.py` exists in the port surface (spec §4 lists it), but the **only** landed adapter is the Stage 1 stub. The donor `runtime/loop_safety.py` (403 lines) is production-tested and enforces four independent controls:

- **Tier 1 — Hard limits:** `max_turns`, `max_tokens` (per turn + per session), `max_wall_time`.
- **Tier 2 — Repetition detection:** tool-call sequence hashing, identical-text detection, two-state oscillation detection.
- **Tier 3 — Circuit breaker:** stop + report on any Tier-1/Tier-2 threshold breach.

Plus `runtime/loop_guard.py` (113 lines) — SHA-256 tool-call arg hashing with sliding window, warning at 5, block at 8.

**Recommendation:** the same fidelity-port pattern used at Stage 8.1 applies. Both files go verbatim under `adapters/loop_safety/tektos/vendor/`, wrapped by a `TektosLoopSafetyAdapter` implementing `LoopSafetyPort`. A one-shot `NoOpLoopSafetyAdapter` (permits everything) is required for CI so the turn-loop tier can run without instantiating the full safety monitor.

This means Stage 8.2 lands **two** adapter families, not one:
1. **LoopSafetyPort** — noop + tektos (fidelity port of `loop_safety.py` + `loop_guard.py`) → prerequisite of the turn loop.
2. **Tektos turn-loop plugin surface** — Kosmos-owned `TurnController` that consumes all six ports listed in §3.

---

## 5. Fidelity-vs-rewrite ruling for the turn loop itself

Recall the Stage 8.1 answer to the fidelity question was **"A — fidelity port"**. That ruling was **file-scoped** and reasonable there because `state_machine.py` + `runtime/session.py` were self-contained and their contract shape matched a SessionPort 1:1 with three import rewrites.

`_stream_llm` **cannot** be a fidelity port:

1. **1471 lines with 8 wired collaborators** that don't correspond to any port shape. Vendoring it verbatim would immediately violate ADR-007 (a plugin importing eight unrelated modules across `tektos.runtime.*`), ADR-023 (raw `append_event` and `HookRegistry.run` calls bypass the EventBus envelope shape), and ADR-029 (raw `MetabolismEngine` bypasses ResourcePort's priority-queue arbitration).
2. **9 of the 11 constructor collaborators are Kosmos ports already** — vendoring would keep 9 in-plugin implementations that then have to be swapped out one at a time later, doubling the churn.
3. **The turn loop is the load-bearing seam** between SessionPort, LLMPort, EventBusPort, SandboxPort, ResourcePort, LoopSafetyPort, and (Stage 9+) ImmunePort. If it stays a black-box vendor blob, every downstream slice has to reach inside it, and the ports become nominal.

**Recommendation:** Stage 8.2 **rewrites `_stream_llm` against the ports** while preserving the donor's **behaviour skeleton** — the exact ordering of steps, the exact loop-safety check placement, the exact double-emit guards, the exact per-session-lock pattern. The 12 `append_event` sites and the tool-approval callback become a port-consuming inner loop. The `while True:` shape stays. The tier-1 loop-safety early-exit stays. What changes is *how* each side effect is issued.

The `_stream_llm` docstring already enumerates the invariants that must survive:

> - assistant.completed emitted ONLY at end_turn (not from partial deltas)
> - tool.completed emitted exactly once per tool_id
> - seq assigned by event store, not passed through
> - Full agent loop: LLM → tools → LLM → ... until no tool_calls
> - Immune system checks before each tool execution

Each of these becomes a **contract-test invariant** on `plugins/tektos/turn_loop.py`. Zero-drift assertion, not vendored code.

---

## 6. Kill-switch review (ADR-103 clause)

ADR-103's kill switch: *"if a vendor file violates a Kosmos invariant unresolvable with a small rewrite, stop the slice, author a rejection ADR, and rewrite that specific module against the port contract."*

For `_stream_llm`, the kill switch **triggers by construction** — the file cannot be vendored without violating ADR-007 and ADR-023. The correct action per that clause is exactly what §5 recommends: author a rejection sub-decision (part of the Stage 8.2 ADR) and rewrite against ports.

For `runtime/loop_safety.py` + `runtime/loop_guard.py`, the kill switch **does not trigger** — both are self-contained, have no plugin imports, and no bypass-the-EventBus writes. They are correctly handled as fidelity ports under `adapters/loop_safety/tektos/vendor/`.

For `runtime/hooks.py` (325 lines, `HookRegistry`), the kill switch **triggers** — its function is subsumed by `EventBusPort`. Do **not** port; delete from the consumed path.

---

## 7. Behavioural invariants that must survive the rewrite (contract-test candidates)

Extracted from the donor `_stream_llm` docstring, the surrounding comments, and the actual code paths. Each becomes a Stage 8.2 contract test:

1. **Single-turn lock** — one and only one `submit_prompt` runs per session at a time; other sessions are not blocked by a slow session (donor achieves this via `_session_locks` dict + `_session_locks_guard`).
2. **Prompt timeout** — `TEKTOS_PROMPT_TIMEOUT_SECONDS` (default 600s) is a hard ceiling on the entire turn; on breach → `session_failed` event + `SessionPort.fail_turn(reason="prompt timeout")`.
3. **assistant.completed exactly once per turn**, only at end-of-turn (never from a partial delta).
4. **tool.completed exactly once per `tool_id`** (guarded by `_completed_tools` set).
5. **`seq` is assigned by the event store**, never passed through by the loop.
6. **Immune-system prompt-injection check runs before the first LLM call**; on positive detection → `session_failed` event + `SessionPort.fail_turn` + no LLM inference occurs.
7. **Loop-safety check runs at the top of every turn iteration** with the previous turn's real tool names + input hashes; on breach → `loop_safety_warning` event + `assistant_completed(stop_reason)` + break.
8. **Read-only tool budget** — `_readonly_tool_rounds` and `_readonly_tools_disabled` gate: after N consecutive read-only turns, the read-only tool set is disabled and a nudge is sent (donor default preserved).
9. **Per-turn resource check** — `_check_resources(session)` runs in the `finally` block; must consume `ResourcePort`.
10. **Session state on branch exit:**
    - normal completion → `SessionPort.complete_turn` (state → READY)
    - prompt timeout → `SessionPort.fail_turn`
    - stream exception → `SessionPort.fail_turn`
    - prompt-injection detected → `SessionPort.fail_turn`
    - external `interrupt(session)` → `SessionPort.interrupt_turn`
11. **Loop-safety monitor is reset per prompt** via `self._loop_monitor.reset()` at the top of `_stream_llm`.
12. **No `import json` in the hot loop** (donor bug #1 fix) — enforce via `test_no_hot_path_json_import` on the ported file.
13. **Failed sessions removed from `_sessions` mapping**, not left in place (donor bug #8 fix) — enforce via a state-machine test.

---

## 8. Recommended stage sequencing

Stage 8.2 is large enough to justify explicit sub-stages under one ADR (Stage 8.2.0 / 8.2.1 / 8.2.2). Recommendation:

- **Stage 8.2.0 — LoopSafetyPort fidelity port** (prerequisite):
  - `adapters/loop_safety/noop/` (permit-all, CI-required)
  - `adapters/loop_safety/tektos/vendor/{loop_safety.py, loop_guard.py}` verbatim + `adapters/loop_safety/tektos/adapter.py` wrapping both
  - Kernel `_boot_loop_safety` in canonical order (immediately after `_boot_session`)
  - Contract tests: tier-1 hard limits, tier-2 repetition, tier-3 circuit breaker, loop-guard SHA-256 pattern, integration between the two

- **Stage 8.2.1 — TurnController plugin surface**:
  - `plugins/tektos/turn_loop.py` with `TurnController` class taking six ports as constructor deps (SessionPort, LLMPort, EventBusPort, SandboxPort, ResourcePort, LoopSafetyPort) + optional `ImmunePort`
  - `submit_prompt(session_id, prompt, system_prompt=None, on_tool_approval=None) -> None` — port-consuming rewrite of donor `_stream_llm`, invariants #1–#13 preserved
  - `interrupt(session_id) -> None` — thin wrapper over `SessionPort.interrupt_turn`
  - Contract tests: one per invariant (13 minimum), plus a golden-path test (create → submit → complete) and a golden-fail test (create → submit → fail_turn on timeout)
  - `TektosPlugin` dataclass grows to carry `turn_controller: TurnController` and stops being descriptor-only

- **Stage 8.2.2 — Wiring + docs fanout**:
  - Kernel `_boot_tektos_turn_controller` slot after `_boot_loop_safety`
  - Spec §4 LoopSafetyPort row promoted from "planned" to "landed"; §17 ADR-104 row appended
  - Build-Sequence Stage 8.2 stanza
  - PORTING_LEDGER entries: donor `loop_safety.py` (MIT, 403 lines verbatim), donor `loop_guard.py` (MIT, 113 lines verbatim)
  - BUILD_LOG entry, SESSION_HANDOFF overwrite, KNOWN_ISSUES check
  - Commit + tag `stage-8-2-complete` + push

**Test-count estimate:** 30–40 loop-safety contract tests + 20–25 TurnController contract tests + 6–8 kernel wiring tests = **~60 new tests**, all fast tier. Roughly matches the Stage 8.1 shape (71 new tests, all fast).

---

## 9. Open questions to resolve in the Stage 8.2 ADR

Load-bearing choices the ADR must lock:

- **Q1 — HookRegistry disposition:** confirm the recommendation to **delete** `HookRegistry` from the ported path in favor of `EventBusPort` fan-out (the "session.start" / "session.complete" / "session.fail" fire sites become `EventEnvelope`s with `producer_plugin="tektos.turn"`, `event_type="session.<lifecycle>"`). Alternative: keep a thin `HookPort` for user extensibility.
- **Q2 — Read-only tool budget shape:** the donor's `_readonly_tool_rounds` / `_readonly_tools_disabled` / `_readonly_nudge_sent` triple is state on the loop. Should it live inside `TurnController`, on `SessionPort.LiveSession`, or on a new small state object? The project wiki entry `concepts/read-only-tool-budget` already documents this as a first-class mechanism — recommend a small `TurnBudgetState` dataclass on `TurnController` with per-session persistence deferred until Stage 8.3.
- **Q3 — Where does `_completed_tools: set[str]` live?** Per-turn on the loop (donor pattern, resets each turn) or per-session on `SessionPort.LiveSession` (survives across turns of the same session)? Donor uses per-turn. Recommend keeping donor semantics — the guard is against double-emit *within* a turn.
- **Q4 — LLM failover:** donor exposes `LLM_FALLBACK_URL` + `LLM_FALLBACK_MODEL` + `LLM_FAILOVER_ENABLED` env vars and a `_probe_llm_loop` background task. Land at Stage 8.2 (part of the LLMPort surface) or defer to a Stage 8.2.x follow-up? Recommend defer — the port already has adapter-side model routing; failover as a first-class LLMPort concern needs its own ADR.
- **Q5 — Tool-approval callback signature:** donor accepts `on_tool_approval: Callable[[str, str], Awaitable[bool]]`. Kosmos has `ApprovalPort` (Stage 2 governance). Recommend the TurnController takes an optional `approval: ApprovalPort | None = None` and, when bound, routes tool-approval requests through the port instead of the callback. When unbound, accept `on_tool_approval` for parity with the donor test surface.
- **Q6 — `_stream_llm` size ceiling in the plugin:** cap `TurnController.submit_prompt` at ~400 lines (donor's is 1471, but ~1000 of those are RAG / planner / hierarchical-agent / multi-agent / repo-map / tool-router / task-decomposer wiring — all deferred to Stages 8.3–8.7). Recommend enforce via a static test on the plugin file.
- **Q7 — SSE parse helper location:** donor inlines OpenAI-compatible SSE parsing inside `_stream_llm`. Extract to `adapters/llm/tektos/sse.py` as a private helper reused by the LLM adapter, or keep inside `TurnController`? Recommend extract — the SSE format is an LLM-adapter concern, not a turn-loop concern.

**Preferred defaults for autonomous execution:** Q1 = delete HookRegistry; Q2 = `TurnBudgetState` on TurnController; Q3 = per-turn `_completed_tools`; Q4 = defer failover; Q5 = optional ApprovalPort with donor callback fallback; Q6 = 400-line cap enforced by test; Q7 = extract SSE to adapter. Proceed with these unless the user overrides.

---

## 10. What Stage 8.2 explicitly does NOT touch

- **RAG retrieval** (`_rag_retriever.retrieve`) — Stage 8.3+ (reflection loop + memory tier).
- **Planner orchestrator** (`_planner_orchestrator.create_plan`) — Stage 8.4.
- **Hierarchical agent** (`_hierarchical_agent.execute_task`) — Stage 8.5.
- **Multi-agent orchestrator** (`_multi_agent_orchestrator`) — Stage 8.7.
- **Repo-map generator** (`_repo_map_generator`) — later Tektos slice.
- **Tool router preflight** (`_tool_router`) — later Tektos slice.
- **Task decomposer** (`_task_decomposer`) — later Tektos slice.
- **Context curator** (`_context_curator`) — later Tektos slice.
- **Context compactor** (4-tier) — later Tektos slice.
- **Immune system** — Stage 9 (constructor slot present as `None`).
- **Durable SQLite event store** — Stage 13 per ADR-103 D3 (bus fan-out only at 8.2).
- **LLM failover** — Stage 8.2.x follow-up under its own ADR (per Q4 above).

Each stays as a `None`-defaulting constructor slot on `TurnController`, matching the Stage 6.1 Zetesis pattern — the port surface is broad, the wired collaborators start narrow, and each downstream stage lights up exactly one slot.

---

## 11. Stage 8.2 Definition of Done

- `LoopSafetyPort` has two adapters landed (`noop` + `tektos`), both green in Cloud.
- `plugins/tektos/turn_loop.py::TurnController` consumes six ports; zero `session.status = …` raw writes; zero `append_event(…)` raw calls; zero `_fire_hook(…)` calls; zero direct `httpx` calls.
- All 13 behavioural invariants (§7) have a passing contract test.
- Kernel boot order: `relational_memory → session → loop_safety → tektos_turn_controller → gnosis_seeder`.
- Full regression preserves the Stage 8.1 baseline (`1557 passed / 1 failed / 21 skipped` in Cloud, with the same pre-existing Stage 3.12 failure documented in KNOWN_ISSUES.md — no new failures).
- ADR-104 authored + ratified.
- PORTING_LEDGER, spec §4 + §17, Build-Sequence, BUILD_LOG, SESSION_HANDOFF all updated.
- Tag `stage-8-2-complete` pushed to `origin main`.

---

## 12. Immediate next actions

1. **Confirm the seven Stage-8.2 ADR defaults in §9** (Q1–Q7) — or override any of them. Once confirmed, no further approval prompts until Stage 8.2.2 doc fanout.
2. Author `docs/adrs/ADR-104-tektos-turn-controller-port-consuming-rewrite.md`.
3. Land Stage 8.2.0 (LoopSafetyPort fidelity port).
4. Land Stage 8.2.1 (TurnController).
5. Land Stage 8.2.2 (docs + commit + tag + push).
