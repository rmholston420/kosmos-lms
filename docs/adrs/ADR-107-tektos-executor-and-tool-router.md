# ADR-107 — Tektos Executor + Tool Router Helpers (Stage 8.5)

**Status:** Ratified v25
**Lock-in phase:** Plan v2 Stage 8.5
**Supersedes:** —

## Context

Stages 8.3–8.4 delivered the analytic engines: reflection / synthesis / experience-replay (ADR-105) and spec-planner / task-decomposer (ADR-106). A `BuildSpec` (from `TektosSpecPlanner.generate_spec`) or a `DecompositionPlan` (from `TaskDecomposer.decompose`) is now producible but has **no execution surface** in Kosmos.

Two donor modules cover this surface in `tektos-ultima`:

- `src/tektos/agents/coding_agent/executor.py` (501 lines) — `Executor.execute_spec(BuildSpec) -> ExecutionRecord`. Iterates spec phases, generates deterministic scaffold artifacts per deliverable, runs pytest on `*test*.py`, runs `ruff check`. Uses raw `subprocess.run` for exec (violates ADR-082 SandboxPort discipline) and pydantic `BaseModel` throughout.
- `src/tektos/runtime/tool_router.py` (536 lines) — `ToolRouter.route_tool(task_description) -> ToolRoute` + `execute_with_recovery`. Keyword-matches task descriptions against a capability table; internal per-tool `ToolPerformance` running stats; error classification enum + recovery strategies (retry / alternative tool / skip).

Constraints derived from prior ADRs and prior Kosmos state:

- ADR-082 requires isolated command execution through `SandboxPort` (already lands with `TektosSandboxAdapter` at Stage 4.7).
- ADR-023 forbids positional `EventBusPort.publish`.
- ADR-007 forbids cross-plugin imports.
- ADR-008 requires locked `provenance` + `confidence` on every memory write.
- ADR-092 forbids event-shape breaks.
- ADR-101 requires optional-dependency degrade at kernel boot.
- ADR-093 preserves the Stage 4.7 `TektosTurnPlanner` seed unchanged.
- ADR-104 (Stage 8.2) already grew `TektosTurnLoop` with `SandboxPort` + `LLMPort` + `SessionPort` + `ResourcePort`; the turn loop is the eventual consumer but stays untouched at 8.5.
- ADR-105 D5 + ADR-106 D5 established the `TektosPlugin.<engine>: object | None = None` field pattern.
- ADR-106 D9 explicitly deferred to Stage 8.5: "`RepoMapPort` (Stage 8.5 executor helpers), filesystem-reading tools (Stage 8.5), real `BuildSpec` execution against `TektosTurnLoop` (Stage 8.5), MCP-based tool discovery in decomposer `tools_needed` (Stage 8.5)."
- Kosmos already has `plugins/tektos/tools/{filesystem,registry}.py` (Stage 4.7) covering `file_read`/`file_write`/`file_list`/`file_stat` behind a policy-aware tool registry; `plugins/tektos/repomap/` is vendored (Stage 4.7 · ADR-038).

Options considered:

1. **Full fidelity port of donor Executor + ToolRouter** (~1000 lines). Rejected — drags pydantic in, raw `subprocess.run` violates ADR-082, `ToolPerformance` mutable state duplicates Stage 8.3 experience-replay, recovery strategy state machine belongs to Stage 8.6 (manager) or 8.7 (multi-agent).
2. **Wait to build until Stage 8.7 orchestrator lands.** Rejected — leaves Stage 8.4 outputs consumer-less for two stages; ADR-106 D9 already pinned the executor concerns to 8.5.
3. **Add a formal `ExecutorPort` + `ToolRouterPort`.** Rejected — same reasoning as ADR-106 D11 (single Tektos-internal consumer today; premature port surface).
4. **Route through the existing `TektosTurnLoop` directly (no new engine).** Rejected — turn-loop's job is per-turn tool-call routing driven by an LLM response; the 8.5 executor's job is deterministic spec-driven artifact generation without an LLM. Different concerns; forcing them together violates the D1 shape ADR-104 established.
5. **CHOSEN — two sibling helper engines under `plugins/tektos/executor/`.** Mirror the ADR-105 + ADR-106 shape exactly. `TektosSpecExecutor` consumes a `BuildSpec` and produces an `ExecutionRecord`; `TektosToolRouter` maps a `tools_needed` tuple to concrete port calls. Both persist through `RelationalMemoryPort.write_narrative` (ADR-102). Kernel env-gates + `TektosPlugin` object-slot fields per D5. `ExecutorPort` + `ToolRouterPort` deferred to 8.6+ (D11 / D12).

## Decision

### D1 — Two sibling engines under `plugins/tektos/executor/`

New package `plugins/tektos/executor/` with two engines and their models/router:

- `TektosSpecExecutor` — consumes a Stage 8.4 `BuildSpec`, produces an `ExecutionRecord` (frozen slotted dataclass) enumerating steps + artifacts + test/lint reports.
- `TektosToolRouter` — maps a `SubTask.tools_needed` tuple (from Stage 8.4 `DecompositionPlan`) to a `ToolRoute` (frozen slotted dataclass) naming the chosen port + argument shape; no execution at 8.5, routing only.

Package layout mirrors `plugins/tektos/decomposer/` exactly:

```
plugins/tektos/executor/
  __init__.py         # locked constants + models re-export
  models.py           # frozen slotted dataclasses: ExecutionRecord/Step/Artifact/TestReport, ToolRoute
  engine.py           # TektosSpecExecutor + TektosToolRouter
  api.py              # build_spec_executor_router(engine) + build_tool_router_router(engine)
```

### D2 — Rewrite pattern

- Rewrite `agents/coding_agent/executor.py` — pydantic → frozen slotted dataclasses; `subprocess.run` → optional `SandboxPort.run` port call (fail-open to a synthetic `ExecutionRecord.status = "sandbox_unavailable"` when unwired); donor scaffold heuristics (`_infer_extension`, `_sanitize_filename`, `_generate_scaffold`, `_generate_python_module`, `_generate_test_scaffold`, `_generate_config_scaffold`) preserved verbatim as module-level pure functions.
- Rewrite `runtime/tool_router.py` — capability table + keyword-match routing preserved verbatim; recovery strategy state machine (retry / alternative / skip) + mutable `ToolPerformance` running stats REJECTED at 8.5 (Stage 8.6 manager scope); execution REJECTED at 8.5 (routing only; caller executes).

### D3 — Persistence sink

Both engines persist through `RelationalMemoryPort.write_narrative` (ADR-102) with the same shape as Stage 8.3 + 8.4 engines: `title` prefixed with the engine's ADR-107 predicate; `tags` include locked provenance + domain context (`session_id`, `spec_id` / `plan_id`); `body` is JSON-serialised dataclass; `provenance` + `confidence` locked to the engine's constants (D4); every port call wrapped in `try/except Exception` with `log.exception(...)` per D9; ring-buffer fallback (`maxlen=100`) always populated.

### D4 — Six locked constants (all `∈ (0, 1]` per ADR-008)

```python
TEKTOS_EXECUTOR_PROVENANCE = "tektos.executor"
TEKTOS_EXECUTOR_PREDICATE = "tektos.executor.spec_executed"
TEKTOS_EXECUTOR_DEFAULT_CONFIDENCE = 0.75

TEKTOS_TOOL_ROUTER_PROVENANCE = "tektos.tool_router"
TEKTOS_TOOL_ROUTER_PREDICATE = "tektos.tool_router.routed"
TEKTOS_TOOL_ROUTER_DEFAULT_CONFIDENCE = 0.75
```

Confidence 0.75 matches ADR-036 pre-Reflexion default and Stage 8.3 + 8.4 engine defaults.

### D5 — `TektosPlugin` dataclass amendment

`TektosPlugin` grows two new optional fields, mirroring ADR-105 D5 + ADR-106 D5:

```python
executor: object | None = field(default=None)
tool_router: object | None = field(default=None)
```

Fields typed as `object | None` (not the concrete engine class) to preserve ADR-007 no-cross-plugin-imports: the `TektosPlugin` dataclass lives in `plugins/tektos/plugin.py` and cannot import from sibling `plugins/tektos/executor/`. Wiring happens best-effort at kernel boot via `setattr`.

### D6 — Kernel wiring (two new boot slots + shared helper reuse)

- Two new `_BootRegistry` slots (`tektos_executor: Any = None`, `tektos_tool_router: Any = None`) inserted after the Stage 8.4 slots (`tektos_spec_planner`, `tektos_decomposer`) and before the Gnosis seeder.
- Two `@_try("tektos_<slot>")` boot functions (`_boot_tektos_executor`, `_boot_tektos_tool_router`), both delegating to the existing shared `_boot_stage_8_x_engine(*, env_var, adr_note, engine_factory, plugin_field)` helper (which now serves ADR-105 + ADR-106 + ADR-107 — no rename, no new helper).
- Env-gates `KOSMOS_TEKTOS_{EXECUTOR,TOOL_ROUTER}={off,on}`, default `off` silent; unknown value → `RuntimeError` captured in `registry.errors`.
- `on` requires `registry.relational_memory` non-None (ADR-101 degrade to `None` with WARN log when missing); `TektosSpecExecutor` additionally accepts optional `registry.sandbox` — if wired the executor uses it, otherwise falls open to `sandbox_unavailable` records.
- Wired engines reflected onto `TektosPlugin.<field>` via `setattr` (fail-safe on frozen dataclass).

### D7 — Two new event types

Envelope-first `EventBusPort.publish` per ADR-023:

- `tektos.executor.spec_executed` — payload: `session_id`, `spec_id`, `execution_id`, `status` (`completed`/`failed`/`sandbox_unavailable`), `artifact_count`, `test_pass_count`, `test_fail_count`, `narrative_id | None`.
- `tektos.tool_router.routed` — payload: `session_id`, `tools_requested` (tuple), `tools_matched` (tuple), `unrouted` (tuple), `narrative_id | None`.

Both event names respect ADR-092 backward compatibility (no existing event types renamed).

### D8 — FastAPI router surface

Two router factories under `plugins/tektos/executor/api.py`:

- `build_spec_executor_router(engine)`:
  - `POST /tektos/api/executor/execute` — body = JSON-serialised `BuildSpec`; response = JSON-serialised `ExecutionRecord`.
  - `GET /tektos/api/executor/recent` — query `?limit=N` (default 10); response = last N records from ring buffer.
- `build_tool_router_router(engine)`:
  - `POST /tektos/api/tool-router/route` — body `{tools_needed: list[str], task_description: str}`; response = JSON-serialised `ToolRoute`.
  - `GET /tektos/api/tool-router/recent` — query `?limit=N`; response = last N routes.

Both factories:
- Use `APIRouter(tags=["tektos.executor"])` / `APIRouter(tags=["tektos.tool_router"])` with **no internal prefix** (mount-time prefix per Stage 8.3 pattern).
- Missing engine → `503 {"detail": "ADR-107 degrade: <engine> not wired", "adr": "ADR-107"}` via a `_guard()` closure inside each factory.

### D9 — Fail-open + explicit deferrals

- Fail-open pattern (`try/except Exception` with `log.exception`) around every `RelationalMemoryPort.write_narrative`, `EventBusPort.publish`, and `SandboxPort.run` call — engine functionality never blocked by port failures; the ring buffer + a synthetic `sandbox_unavailable` status are always available as fallback.
- Explicit deferrals from 8.5:
  - **Recovery strategy state machine** (retry / alternative-tool / skip) — Stage 8.6 (manager) or Stage 8.7 (multi-agent orchestrator).
  - **`ToolPerformance` mutable running stats** — Stage 8.3 experience-replay already covers per-tool learning; a duplicate mutable-state layer is out of scope.
  - **Actual tool execution inside `TektosToolRouter`** — Stage 8.6+; at 8.5 the router is routing-only. `TektosSpecExecutor` may execute through `SandboxPort` directly during `execute_spec` but does not delegate to `TektosToolRouter`.
  - **`ExecutorPort` + `ToolRouterPort`** — Stage 8.6+ (D11 / D12); at 8.5 the `TektosPlugin` object-slot fields ARE the coupling surface.
  - **LLM-driven artifact synthesis** — deferred; at 8.5 artifacts are the donor's deterministic scaffolds.
  - **MCP-based tool discovery in `TektosToolRouter.route`** — deferred to Stage 8.5+ or later.
  - **Integration with `TektosTurnLoop`** — deferred; TurnLoop stays untouched at 8.5.
  - **`RepoMapPort`** — ADR-106 D9 forward-referenced this to 8.5, but Kosmos already lands `plugins/tektos/repomap/` (Stage 4.7 · ADR-038) in-tree; the executor may READ from it via existing `MemoryPort.query_temporal` for context enrichment, but no new port surface is added at 8.5.

### D10 — Engines stay optional

Mirrors ADR-104 D11 + ADR-105 D5 + ADR-106 D10: both engines are optional. Existing tests do not depend on wiring; env-gates default `off`.

### D11 — REJECTS `ExecutorPort` at 8.5

- No cross-plugin consumer of a formal `ExecutorPort` exists at 8.5 (`TektosTurnLoop` is inside the same plugin; the Stage 8.6 manager and Stage 8.7 multi-agent orchestrator both live inside `plugins/tektos/*`).
- `TektosPlugin.executor: object | None` field IS the coupling surface.
- Port surface would be near-empty (single `execute_spec(spec) -> record` method).
- PORTING_LEDGER PLANNED row remains anchored to `LLMPort` / `EventBusPort` / `RelationalMemoryPort` for this stage — no `ExecutorPort` row is added.

### D12 — REJECTS `ToolRouterPort` at 8.5

- Identical reasoning to D11: no cross-plugin consumer today.
- The router is routing-only at 8.5 (D9 deferral); its shape may change substantially when execution + recovery land at 8.6, so locking a Protocol now would over-fit an interim design.

## Rationale

Two sibling engines match the exact shape established by ADR-105 + ADR-106 — the fifth and sixth engine subpackages under `plugins/tektos/` follow the same construction / persistence / wiring / router / test pattern the previous three set. That parity lets the shared `_boot_stage_8_x_engine` helper serve one more decision without a rename, keeps the `TektosPlugin.<engine>: object | None` field pattern regular, and lets the router factories reuse the mount-time prefix idiom the Stage 8.3 debugging cycle established.

The donor executor's raw `subprocess.run` is a direct ADR-082 violation, so a rewrite is not optional — the isolated command execution surface is `SandboxPort.run`. Because `SandboxPort` may not be wired at 8.5 (env-gated), the executor fails open to a `sandbox_unavailable` execution status instead of raising — this preserves the analytic pipeline (spec-planner → executor → reflection/synthesis feedback) even in a CI environment without a sandbox adapter.

The donor tool_router's execution + recovery paths are Stage 8.6+ concerns: `execute_with_recovery` maintains mutable `ToolPerformance` stats + error-classified retry loops, both of which duplicate Stage 8.3 experience-replay and Stage 8.6 manager responsibilities. Landing just the routing surface at 8.5 lets Stage 8.4 outputs flow into a downstream consumer without committing to design decisions the manager stage owns.

Rejecting `ExecutorPort` + `ToolRouterPort` at 8.5 is consistent with ADR-106 D11 / D12: single-consumer surfaces do not warrant a formal port until a second consumer exists. When Stage 8.7 lands the multi-agent orchestrator, an `ExecutorPort` may be worth authoring.

## Consequences

Files added:

- `docs/adrs/ADR-107-tektos-executor-and-tool-router.md` (this ADR)
- `plugins/tektos/executor/__init__.py`
- `plugins/tektos/executor/models.py`
- `plugins/tektos/executor/engine.py`
- `plugins/tektos/executor/api.py`
- `plugins/tektos/tests/test_stage_8_5_spec_executor_engine.py`
- `plugins/tektos/tests/test_stage_8_5_tool_router_engine.py`
- `plugins/tektos/tests/test_stage_8_5_engine_routers.py`
- `tests/kernel/test_stage_8_5_engine_wiring.py`

Files modified:

- `docs/adrs/README.md` — ADR-107 row inserted between ADR-106 and ADR-090.
- `docs/Kosmos-Build-Spec-v26.md` §17 — ADR-107 row inserted above ADR-106.
- `docs/Kosmos-Build-Sequence-v26.md` — Stage 8.5 stanza appended after Stage 8.4.
- `docs/PORTING_LEDGER.md` — two new entries appended to Tektos section (executor VENDORED · ADR-107; tool_router VENDORED · ADR-107).
- `plugins/tektos/plugin.py` — `TektosPlugin` grows `executor` + `tool_router: object | None = None` fields with ADR-107 D5 comment.
- `kernel/app.py` — two new `_BootRegistry` slots + two `_boot_tektos_{executor,tool_router}` functions delegating to the existing `_boot_stage_8_x_engine` helper; two new `registry.<slot> = _boot_tektos_<slot>` bindings inserted after the Stage 8.4 slot assignments.
- `BUILD_LOG.md` — one appended entry per `kosmos-log-maintenance`.
- `SESSION_HANDOFF.md` — overwritten to reflect Stage 8.5 complete state.

Ports preserved / reinforced:

- **ADR-007** — two new subpackages import only from `ports.*` + their own subpackage; no cross-plugin imports; enforced at test time via existing AST scan.
- **ADR-008** — every `write_narrative` supplies locked provenance + confidence ∈ (0, 1].
- **ADR-023** — envelope-first `EventBusPort.publish` upheld; never positional args.
- **ADR-082** — `SandboxPort.run` is the isolated-execution surface; the executor never touches raw `subprocess.run`.
- **ADR-092** — no existing event types renamed.
- **ADR-093** — Stage 4.7 `TektosTurnPlanner` seed untouched.
- **ADR-101** — degrade pattern for optional kernel-boot collaborators + request-time degrade in FastAPI routers.
- **ADR-102** — `RelationalMemoryPort` is the persistence substrate.
- **ADR-104** — `TektosTurnLoop` untouched at 8.5.
- **ADR-105 / ADR-106** — sibling engines follow the same shape; the shared boot helper now serves three ADRs.

Test count target: ~26 new tests (mirrors 8.4's 29-count shape scaled to two engines instead of three), full regression **≥ 1676 passed / 21 skipped / 1 deselected** (Stage 8.4 baseline 1650 + ≥ 26 delta).

## Lock-in phase

Plan v2 Stage 8.5.

## References

- `Kosmos-Build-Spec-v26.md` §17 (ADR-107 row).
- `Kosmos-Build-Sequence-v26.md` (Stage 8.5 stanza).
- `docs/adrs/ADR-082-sandbox-port.md`.
- `docs/adrs/ADR-102-relational-memory-port-postgres-5th-layer.md`.
- `docs/adrs/ADR-104-tektos-turn-loop-session-and-llm-integration.md`.
- `docs/adrs/ADR-105-tektos-reflection-synthesis-experience-engines.md`.
- `docs/adrs/ADR-106-tektos-spec-planner-and-task-decomposer-engines.md`.
- Donor: `tektos-ultima/src/tektos/agents/coding_agent/executor.py` (501 lines).
- Donor: `tektos-ultima/src/tektos/runtime/tool_router.py` (536 lines, routing surface only).
- `PORTING_LEDGER.md` Tektos section.
