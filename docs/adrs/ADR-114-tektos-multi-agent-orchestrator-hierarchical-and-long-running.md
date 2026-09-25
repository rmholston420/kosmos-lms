# ADR-114 — Tektos multi-agent orchestrator + hierarchical + long-running agents (Stage 8.7)

**Status:** Ratified
**Date:** 2026-09-24
**Stage:** v2 Stage 8.7 (Plan §4 line 102)
**Discharges:** ADR-107 D9 point 1 (recovery-strategy execution loop), ADR-108 D9 (rhythm-hook scheduler deferred to 8.7+, recovery loop deferred to "a future Stage 8.7 multi-agent orchestrator"), Plan v2 line 102.

---

## Context

Stages 8.3–8.6 delivered the analytic + executive engine family (reflection / synthesis / experience-replay per ADR-105; spec-planner / task-decomposer per ADR-106; spec-executor / tool-router per ADR-107; S3 Manager per ADR-108). Three donor runtime subsystems remain unported, and two prior ADRs explicitly defer their behavior to this stage:

- ADR-107 D9 point 1: "the actual retry / alternative / skip loop stays in the Stage 8.7 multi-agent orchestrator" — the `classify_recovery(category)` classifier landed at 8.6 but nothing *executes* the strategy.
- ADR-108 D9: "Circadian/ultradian/heartbeat scheduling deferred to Stage 8.7+ (multi-agent orchestrator)" — the long-running engine's heartbeat path is the natural home.

Plan v2 line 102 scopes the slice:

> **8.7 — Multi-agent + hierarchical + long-running agents.** Vendor donor multi-agent orchestrator; hierarchical spawn via existing EventBusPort. Long-running via `RelationalMemoryPort.record_event` heartbeats. ~2 sessions.

Donor surface (Tektos `src/tektos/runtime/`, 1,380 LOC total):

| Donor file | Lines | Role |
|---|---|---|
| `multi_agent_orchestrator.py` | 541 | Task/agent lifecycle, keyword capability matching, real-tool dispatch, (pseudo-)parallel execution, result reconciliation |
| `hierarchical_agent.py` | 347 | Six-role hierarchical execution (architect/planner/coder/reviewer/tester/deployer), dependency gating, `asyncio.gather` batching |
| `long_running_agent.py` | 492 | Checkpoint/resume, progress tracking, heartbeat interval, `CheckpointManager` persistence |

### Donor defects audited (2026-09-24)

1. **`MultiAgentOrchestrator._dispatch_real_tool`** runs commands via `subprocess.run(cmd, shell=True)` and writes arbitrary paths from regex-extracted strings in task descriptions — a shell-injection and path-arbitration surface. Kosmos rejects this; execution routes through `SandboxPort` (ADR-107 precedent: quality gates via `SandboxPort`, fail-open when unwired).
2. **`MultiAgentOrchestrator.execute_parallel`** is misnamed — it executes tasks sequentially in a `for` loop. The rewrite makes it a true `asyncio.gather` under a `Semaphore(max_concurrent_agents)`.
3. **`HierarchicalAgent` role handlers are LLM stubs** — each returns a template string (`"Architecture design for: X"`). The rewrite routes them through `LLMPort.chat` when bound and keeps the donor template as the deterministic unwired fallback (preserves donor behavior as the floor, not the ceiling).
4. **Module-level singleton registries** (`_agents: dict` + `get_hierarchical_agent()` / `get_long_running_agent()` convenience functions) in both `hierarchical_agent.py` and `long_running_agent.py` — global mutable state invisible to the kernel lifecycle. Rejected; the kernel boot owns exactly one instance per engine and reflects it onto `TektosPlugin`.
5. **`LongRunningAgent` persists checkpoints as raw JSON files** under `./checkpoints/<session_id>/`. The plan pins long-running persistence to `RelationalMemoryPort.record_event` heartbeats; the rewrite uses `record_event` for checkpoints + heartbeats with an in-process ring buffer as the ADR-101 fallback (mirrors ADR-108 D3's narrative + ring-buffer split).

### Alternatives considered

1. **Vendor verbatim (byte-for-byte) under `adapters/tektos/vendor/`.** Rejected — the donor ships `shell=True` subprocess execution and module-global singletons; ADR-105/106/107/108 all chose the rewrite-over-vendor path for the same hygiene reasons.
2. **Three separate engine subpackages (`orchestrator/`, `hierarchical/`, `long_running/`).** Rejected — the plan scopes one slice; the three donors share one lifecycle (spawn → execute → checkpoint → reconcile), one env gate, and one router family. One subpackage with three sibling engines mirrors ADR-107 (spec-executor + tool-router in `executor/`).
3. **Wire subagents to `TektosTurnLoop` for real multi-turn LLM delegation.** Rejected at 8.7 — the turn loop is the S1 surface and integrating it in both directions would couple the orchestrator to loop internals. Hierarchical role handlers use a *single* `LLMPort.chat` call per role (bounded, no tool loop); full turn-loop delegation is an explicit deferral (D9).

---

## Decision

### D1 — Scope

One new engine subpackage `plugins/tektos/orchestrator/` (the sixth Tektos engine family after reflection, synthesis, experience, planner, executor, manager) landing **three sibling engines**:

- `TektosOrchestrator` — multi-agent task orchestration (donor `MultiAgentOrchestrator` rewritten per D2).
- `TektosHierarchicalAgent` — role-based hierarchical execution (donor `HierarchicalAgent` rewritten per D2).
- `TektosLongRunningAgent` — checkpoint/resume + heartbeat persistence (donor `LongRunningAgent` + `CheckpointManager` rewritten per D2; the standalone `CheckpointManager` class is folded into the engine — one persistence path, not two).

### D2 — Rewrite (semantics preserved, defects fixed)

- **Orchestrator:** task/agent lifecycle, the four default agents (file/terminal/browser/reviewer), keyword capability matching (`assign_task`), and `reconcile_results` preserved **verbatim** (they are pure and correct). `_dispatch_real_tool` rerouted: command execution → `SandboxPort.run(SandboxRequest(...))` (ADR-079/107 precedent); file read/search/patch branches collapse to sandbox or fail-open `sandbox_unavailable` status when the port is unbound (donor's raw `open()`/`subprocess` paths are REJECTED — see Context defect 1). `execute_parallel` becomes a true `asyncio.gather` under `asyncio.Semaphore(max_concurrent_agents)` (Context defect 2). Recovery: on a failed task the engine calls `plugins.tektos.manager.classify_recovery(category)` (ADR-108, landed 8.6) and records the chosen `RecoveryStrategy` on the result — the *execution* surface ADR-107 D9 deferred (a `retry` strategy re-dispatches once, up to `max_retries`; `alternative_tool` falls back to the terminal agent route; `skip` marks the task cancelled; `escalate` marks it failed with an `escalated=True` flag — no human-in-the-loop loop at 8.7).
- **Hierarchical:** the six `AgentRole` handlers preserve the donor's dependency gating, timing, `AgentResult.to_markdown`, and `execute_batch` gather semantics. Role handlers become `await llm.chat(messages=[...role prompt + task description...])` when `LLMPort` is bound; the donor template strings are preserved verbatim as the deterministic unwired fallback (tests assert the fallback text byte-for-byte). The donor module-level `_agents` registry is REJECTED (Context defect 4).
- **Long-running:** `AgentState`, `AgentCheckpoint`, `AgentProgress` semantics preserved (including `progress_percent` / `elapsed_minutes` / `to_markdown`). Persistence rerouted from JSON files to `RelationalMemoryPort.record_event` (kind `tektos.long_running.checkpoint` for checkpoints, `tektos.long_running.heartbeat` for interval heartbeats) per Plan line 102; `query_events` reads them back for `load_checkpoint` / `list_checkpoints`; the in-process ring buffer (`deque(maxlen=...)`) mirrors ADR-108 D3 and is the ADR-101 fallback when the port is unbound. `cleanup_old_checkpoints(keep_last)` keeps the donor's count semantics, applied to the ring buffer + a delete-on-rotate record. Module-level `_agents` registry REJECTED (Context defect 4).

### D3 — Write surface

- `TektosOrchestrator` + `TektosHierarchicalAgent` persist through `RelationalMemoryPort.write_narrative` (title prefix = locked predicate), body = `json.dumps(record)`, `confidence=TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE` (0.75, ADR-036).
- `TektosLongRunningAgent` persists through `RelationalMemoryPort.record_event` (checkpoints + heartbeats) — the only engine in the family on `record_event`, per Plan line 102.
- Ring-buffer fallback on every engine (ADR-101 degrade pattern).
- Provenance: `tektos.orchestrator` (both orchestrator and hierarchical — one family, one provenance, mirroring how ADR-107 kept two provenances only because the engines were separately addressable; here the router is one surface).
- Every port call wrapped `try/except Exception` + `log.exception` (fail-open, ADR-108 D9 pattern).

### D4 — Locked constants (single source of truth in `__init__.py`)

- `TEKTOS_ORCHESTRATOR_PROVENANCE = "tektos.orchestrator"`
- `TEKTOS_ORCHESTRATOR_PREDICATE = "tektos.orchestrator.task_completed"`
- `TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE = 0.75`
- `TEKTOS_ORCHESTRATOR_EVENT_BATCH = "tektos.orchestrator.batch_completed"`
- `TEKTOS_ORCHESTRATOR_EVENT_ROLE = "tektos.hierarchical.role_completed"`
- `TEKTOS_LONG_RUNNING_CHECKPOINT_KIND = "tektos.long_running.checkpoint"`
- `TEKTOS_LONG_RUNNING_HEARTBEAT_KIND = "tektos.long_running.heartbeat"`

### D5 — `TektosPlugin` field

One new field: `orchestrator: object | None` (holds the `TektosOrchestrator` bundle; the engine exposes `.hierarchical` and `.long_running` handles for the other two engines). `object | None` typing per the ADR-007 rationale on `turn_loop` / `manager`.

### D6 — Kernel wiring

One `@_try("tektos_orchestrator")` boot function (`_boot_tektos_orchestrator`) with the bespoke pattern (ADR-107 executor / ADR-108 manager — extra collaborators beyond the shared `_boot_stage_8_x_engine` helper):

- Env gate `KOSMOS_TEKTOS_ORCHESTRATOR={off,on}` (default `off`); unknown value → `registry.errors["tektos_orchestrator"]`.
- Hard requirement: `registry.relational_memory` non-None → else ADR-101 degrade (WARN + `None`).
- Optional collaborators: `registry.event_bus`, `registry.sandbox`, `registry.llm`, `registry.observability` — each fail-open when absent.
- Registry slots: `tektos_orchestrator`, `tektos_hierarchical`, `tektos_long_running` (three slots, one boot function, mirroring how the executor boot populates two slots).
- Wires AFTER `_boot_tektos_manager` (orchestrator consults `classify_recovery` from the manager subpackage at call time — import-time only, no boot-order dependency beyond availability of the module).

### D7 — Event types (three new)

- `tektos.orchestrator.task_completed` — per-task lifecycle end (success or failure, with recovery strategy).
- `tektos.orchestrator.batch_completed` — `OrchestrationResult` aggregate after `execute_parallel` / `reconcile`.
- `tektos.hierarchical.role_completed` — per-role `AgentResult` in the hierarchical engine.

Envelope-first per ADR-023; producer_plugin = `TEKTOS_ORCHESTRATOR_PROVENANCE`.

### D8 — FastAPI router surface

One factory `build_orchestrator_router(bundle)` in `plugins/tektos/orchestrator/api.py`, `APIRouter(tags=["tektos.orchestrator"])`, **no internal prefix**, mounted under `/tektos/api/orchestrator`. Missing bundle → `503 {"detail": "ADR-114 degrade: orchestrator not wired", "adr": "ADR-114"}` via `_guard()`.

- `POST /orchestrate` — body `{session_id, tasks: [{description, priority, dependencies?}]}` → `OrchestrationResult` (create → assign → parallel execute → reconcile).
- `GET /stats` → `get_orchestration_stats()`.
- `POST /hierarchical/batch` — body `{session_id, tasks: [{role, description, context?, dependencies?}]}` → `{results: [AgentResult dicts]}`.
- `POST /long-running/start` — body `{session_id, total_steps?}` → `{state}`.
- `POST /long-running/checkpoint` — body `{session_id, current_step?, completed?}` → `{checkpoint_id | null}`.
- `POST /long-running/resume` — body `{session_id}` → `{resumed: bool}`.
- `GET /long-running/progress?session_id=...` → `AgentProgress` dict.
- `POST /long-running/stop` — body `{session_id, reason?}` → `{state}`.

### D9 — Fail-open + explicit deferrals

- Fail-open around every `write_narrative`, `record_event`, `query_events`, `EventBusPort.publish`, `SandboxPort.run`, `LLMPort.chat`, `ObservabilityPort.score` call.
- Explicit deferrals from 8.7:
  - **Real multi-turn subagent delegation via `TektosTurnLoop`.** Role handlers are single-shot `LLMPort.chat` calls; a subagent that itself runs a tool loop is deferred (Alternative 3).
  - **Human-in-the-loop `escalate`.** `classify_recovery → "escalate"` marks the task failed + `escalated=True` and emits the event; no interactive approval loop at 8.7 (ApprovalPort integration is a future slice).
  - **Circadian/ultradian rhythm scheduler.** The long-running engine exposes `heartbeat()` (interval-gated per donor `checkpoint_if_needed`); a wall-clock rhythm scheduler remains deferred (ADR-108 D9) — the hook surface is present and tested, the scheduler is not.
  - **Browser agent real dispatch.** Donor's browser agent was already a stub error; stays fail-open `sandbox_unavailable` (no browser port in the kernel at 8.7).

### R1 — REJECTS donor `_dispatch_real_tool` raw `subprocess.run(shell=True)` + raw `open()` path writes

Shell injection + path arbitration surface (Context defect 1). Rerouted to `SandboxPort.run`; the donor's command-extraction regex is preserved *only* as the `SandboxRequest` argument builder.

### R2 — REJECTS donor module-level singleton registries

`hierarchical_agent._agents` / `long_running_agent._agents` + `get_*_agent()` / `list_*_agents()` (Context defect 4). Kernel boot owns the instances; per-session state is a dict on the engine keyed by `session_id`, exposed via `list_sessions()`.

### R3 — REJECTS donor `./checkpoints` JSON-file persistence

Raw disk state invisible to the memory subsystem (Context defect 5). Replaced by `RelationalMemoryPort.record_event` + ring buffer per D2/D3.

### R4 — Pydantic `BaseModel` on donor dataclasses

The three donors use plain `@dataclass` + `Enum`. Kosmos convention (ADR-105/106/107/108): `@dataclass(frozen=True, slots=True)` value objects + `Literal` unions for enum surfaces, `replace()` for mutation. `Subagent` / `Task` / `AgentTask` carry lifecycle state — they stay **mutable** dataclasses (state machines, not value objects) with the frozen/slots treatment applied to result records (`OrchestrationResult`, `AgentResult`, `AgentCheckpoint`, `AgentProgress`).

---

## Consequences

- The orchestrator is the sixth Tektos engine subpackage under `plugins/tektos/` and follows the ADR-105/106/107/108 shape exactly — the four-decision skeleton (D1 scope · D2 rewrite · D3 write surface · D4 constants) plus D5–D9. That parity keeps the boot-slot table and `TektosPlugin` dataclass predictable.
- ADR-107 D9 point 1 is fully discharged: `classify_recovery` (8.6) + the retry/alternative/skip/escalate execution loop (8.7) together form the recovery-strategy state machine.
- ADR-108 D9's two deferrals are discharged: heartbeat surface on the long-running engine (D9 note: scheduler still deferred) and the recovery loop (D2).
- Three new registry slots + one env gate; default `off` keeps the kernel boot surface unchanged for existing deployments.
- The `TektosPlugin.orchestrator` field gives UI/gateway code one handle to the whole family (mirrors `manager`).
- Test plan: `plugins/tektos/tests/test_stage_8_7_{orchestrator,hierarchical,long_running}_engine.py` (contract tests, no live ports — stubs per ADR-108 test shape, fallback texts asserted verbatim) + `test_stage_8_7_orchestrator_router.py` + `tests/kernel/test_stage_8_7_orchestrator_wiring.py` (env-gate scenarios per ADR-108 D6 shape).

## Donor reference

- Donor: `tektos-ultima/src/tektos/runtime/{multi_agent_orchestrator,hierarchical_agent,long_running_agent}.py` (1,380 LOC total; subprocess dispatch + module singletons + JSON-file checkpoints explicitly REJECTED per R1/R2/R3).
- Kosmos target: `plugins/tektos/orchestrator/{__init__,models,engine,hierarchical,long_running,api}.py`.

## Related ADRs

- **ADR-101** — ADR-023-style degrade pattern (503 router surface + boot-time WARN + ring-buffer fallbacks).
- **ADR-023** — EventEnvelope event kinds; three new predicates.
- **ADR-079** — `SandboxPort` as the only command-execution surface (R1).
- **ADR-107** — spec-executor + tool-router (two engines in one subpackage, the precedent for D1; D9 point 1 discharged here).
- **ADR-108** — S3 Manager (`classify_recovery` consumer, fail-open + ring-buffer pattern).
- **ADR-036** — 0.75 pre-Reflexion default confidence.
