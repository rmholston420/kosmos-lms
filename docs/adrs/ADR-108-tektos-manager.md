# ADR-108 — Tektos Manager Engine (Stage 8.6)

**Status:** Ratified v25
**Lock-in phase:** Plan v2 Stage 8.6
**Supersedes:** —

## Context

Stages 8.3–8.5 delivered analytic + executive engines (reflection / synthesis / experience-replay per ADR-105; spec-planner / task-decomposer per ADR-106; spec-executor / tool-router per ADR-107). ADR-107 D9 explicitly deferred the recovery-strategy state machine, mutable `ToolPerformance` running stats, and integration with `TektosTurnLoop` to Stage 8.6 (manager) or later. Plan v2 §4 line 101 pins Stage 8.6 as:

> **8.6 — Manager (guardrails/metrics/archetype).** Vendor donor manager. Guardrails delegate to `ImmunePort`; metrics to `ObservabilityPort`; archetype-tracker lives plugin-internal. ~1 session.

The primary donor is `tektos-ultima/src/tektos/agents/manager/` (1646 LOC across 6 modules). The relevant Kosmos state:

- `ImmunePort` (ADR-079) is ratified at `ports/immune.py` (170 LOC). A Kosmos-native Tektos immune adapter already lives at `adapters/immune/tektos/` with 12 detectors, including `SecretExposureDetector` (12 regex patterns). Guardrail delegation therefore consumes the existing port.
- `ObservabilityPort` (ADR-025) is ratified at `ports/observability.py` (172 LOC). A `OtelStackObservabilityAdapter` lives at `adapters/observability/otel_stack/`. Metric recording therefore consumes the existing port.
- `ThermalPort` (ADR-081) is ratified at `ports/thermal.py` (107 LOC) with the identical RTX 5090 threshold table used by the donor's `telemetry.py` (Yellow=51°C, Cap=80°C+400W, Red=88°C). Thermal responsibility therefore belongs to `ThermalPort`, not the manager.
- ADR-023 forbids positional `EventBusPort.publish`.
- ADR-007 forbids cross-plugin imports.
- ADR-008 requires locked `provenance` + `confidence ∈ (0, 1]` on every memory write.
- ADR-092 forbids event-shape breaks.
- ADR-101 requires optional-dependency degrade at kernel boot.
- ADR-104 (Stage 8.2) already grew `TektosTurnLoop` with `SandboxPort` + `LLMPort` + `SessionPort` + `ResourcePort`; the manager becomes an eventual peer, not a modifier of the turn loop.
- ADR-105 D5 + ADR-106 D5 + ADR-107 D5 established the `TektosPlugin.<engine>: object | None = None` field pattern.
- ADR-107 D6 established the pattern: engines using two collaborators (`relational_memory` + `event_bus`) reuse the shared `_boot_stage_8_x_engine` helper; engines with additional collaborators (as the executor did with `sandbox`) use a bespoke boot function reusing the same env-gate + degrade + plugin-reflection semantics.

Options considered:

1. **Full fidelity port of donor `agents/manager/`** (~1646 LOC including `telemetry.py`). Rejected — drags pydantic in, duplicates `ImmunePort` / `ObservabilityPort` / `ThermalPort`, and adds Colossus-only pynvml + Unix-socket fan-controller plumbing.
2. **Wait to build the manager until Stage 8.7.** Rejected — ADR-107 D9 already pinned recovery-strategy classification helpers + `ToolPerformance` mutable stats to a manager-owned surface; Stage 8.4 outputs remain observability-thin without it, and the manager is the S3 pillar of the VSM architecture.
3. **Add formal `ManagerPort`.** Rejected — same reasoning as ADR-105/106/107 D11: single Tektos-internal consumer at 8.6, `TektosPlugin.manager: object | None` field IS the coupling surface; premature port surface.
4. **Duplicate donor's `PrimeMoverMetrics.record()` in-process sample store alongside `ObservabilityPort`.** Rejected — violates the single-source-of-truth invariant; `ObservabilityPort.score()` (ADR-025) already writes to OTel counters + histograms with p50/p95/p99 percentile derivation.
5. **Duplicate donor's `_check_guardrails()` regex alongside `ImmunePort`.** Rejected — `ImmunePort` (ADR-079) is the ratified scanning surface; the Tektos adapter already ships 12 detectors including secret exposure. The manager's guardrail branch becomes an `ImmunePort.scan()` client. Donor's inline regex is preserved only as a fallback keyword scan when `ImmunePort` is unbound (D9 fail-open).
6. **CHOSEN — single Kosmos-native `TektosManager` engine under `plugins/tektos/manager/`** with the archetype-tracker + guardrails enum-and-rule-dict preserved verbatim as plugin-internal helpers, delegating guardrail scans to `ImmunePort` and metric recording to `ObservabilityPort`. Mirrors ADR-105/106/107 shape exactly.

## Decision

### D1 — Single engine under `plugins/tektos/manager/`

New package `plugins/tektos/manager/` with:

- `TektosManager` (engine) — orchestrates lifecycle hooks (`on_task_start` / `on_task_complete` / `on_error` / `on_spiral_update` / `on_rhythm_event`) + health reporting. Consumes `RelationalMemoryPort`, `EventBusPort`, `ImmunePort`, `ObservabilityPort` — all optional per D9 fail-open.

Package layout mirrors ADR-105/106/107:

```
plugins/tektos/manager/
  __init__.py                # locked constants + models re-export
  models.py                  # frozen slotted dataclasses (ManagerFeedback, ManagerHealthReport, enums as Literal unions)
  guardrails.py              # Guardrail enum + GUARDRAIL_RULES metadata (verbatim from donor)
  archetype_tracker.py       # plugin-internal ArchetypeTracker + ArchetypeEvent + Archetype (rewrite of donor)
  engine.py                  # TektosManager engine
  api.py                     # build_manager_router(engine) factory
```

### D2 — Rewrite pattern

- Rewrite donor `agents/manager/models.py` — pydantic `BaseModel` → frozen slotted dataclasses; enums as `Literal` unions matching ADR-105/106/107 shape (`FeedbackType`, `FeedbackSeverity`, `ManagerState`, `SpiralDirection`). W5H1M metadata (`who` / `what` / `where` / `when` / `why` / `how`) preserved verbatim on `ManagerFeedback`, including the `_M` extension (`what_happened` / `what_should_happen` / `try_this`).
- Rewrite donor `agents/manager/archetype_tracker.py` — pydantic → frozen slotted dataclasses; all donor methods preserved verbatim (`record_event`, `get_archetype`, `get_active_archetypes`, `get_archetypes_at_threshold`, `get_archetype_counts`, `should_create_structure`, `mark_structure_created`, `clear_events`). Threshold default `3` preserved.
- Rewrite donor `agents/manager/orchestrator.py::Manager` → `TektosManager`. Renamed for Kosmos naming discipline (matches `TektosSpecPlanner` / `TektosSpecExecutor` / `TektosToolRouter`). Donor `_generate_archetype_feedback` and `_check_guardrails` re-shaped: archetype-hit path preserved verbatim; guardrail path REROUTED to `ImmunePort.scan()` with the donor's inline regex retained as a fallback keyword scan.
- Rewrite donor `agents/manager/metrics.py` — donor `PrimeMoverMetrics` class REPLACED with (a) a module-level frozen threshold table `_THRESHOLDS: Mapping[str, MetricThreshold]` preserving the donor's 8 metric names + warning/critical/direction verbatim, (b) a pure function `_check_threshold(name, value) -> "warning" | "critical" | None` preserving donor's `check_threshold` branching verbatim, (c) `record()` REROUTED to `ObservabilityPort.score()` (ADR-025).
- Preserve donor `agents/manager/guardrails.py` VERBATIM (enum + `GUARDRAIL_RULES` dict) as `plugins/tektos/manager/guardrails.py`. This is policy vocabulary, not detection code — `ImmunePort` is the scanner.
- REJECT donor `agents/manager/telemetry.py` (see D12).

### D3 — Persistence sink

`RelationalMemoryPort.write_narrative` (ADR-102) with the same shape as Stage 8.3/8.4/8.5 engines:

- `title` prefixed with the engine's ADR-108 predicate.
- `tags` include locked provenance + domain context (`session_id`, `category`, `severity`).
- `body` is JSON-serialised `ManagerFeedback` dataclass.
- `provenance` + `confidence` locked to the engine's constants (D4).
- Every port call wrapped in `try/except Exception` with `log.exception(...)` per D9.
- Ring-buffer fallback (`max_records=100`) always populated so recall works even when the port is unwired.

### D4 — Three locked constants (all `∈ (0, 1]` per ADR-008)

```python
TEKTOS_MANAGER_PROVENANCE = "tektos.manager"
TEKTOS_MANAGER_PREDICATE = "tektos.manager.feedback_generated"
TEKTOS_MANAGER_DEFAULT_CONFIDENCE = 0.75
```

Confidence `0.75` mirrors ADR-105/106/107 default (pre-Reflexion, per ADR-036); manager feedback is heuristic (archetype thresholds, spiral warnings, guardrail routing), not high-certainty policy.

### D5 — `TektosPlugin` dataclass amendment

`TektosPlugin` grows one new optional field, mirroring ADR-105 D5 + ADR-106 D5 + ADR-107 D5:

```python
manager: object | None = field(default=None)
```

Field typed as `object | None` (not the concrete engine class) to preserve ADR-007 no-cross-plugin-imports: the `TektosPlugin` dataclass lives in `plugins/tektos/plugin.py` and cannot import from sibling `plugins/tektos/manager/`. Wiring happens best-effort at kernel boot via `setattr`.

### D6 — Kernel wiring (one new boot slot, bespoke boot function per ADR-107 executor pattern)

- One new `_BootRegistry` slot (`tektos_manager: Any = None`) inserted after the Stage 8.5 slots (`tektos_executor`, `tektos_tool_router`) and before the Gnosis seeder assignments.
- One `@_try("tektos_manager")` boot function (`_boot_tektos_manager`) using the bespoke pattern established by ADR-107 D6 for the executor — the shared `_boot_stage_8_x_engine` helper takes only `relational_memory` + `event_bus`, whereas the manager engine additionally accepts `immune` + `observability` collaborators.
- Env-gate `KOSMOS_TEKTOS_MANAGER={off,on}`, default `off` silent; unknown value → `RuntimeError` captured in `registry.errors`.
- `on` requires `registry.relational_memory` non-None (ADR-101 degrade to `None` with WARN log when missing).
- `immune` + `observability` + `event_bus` collaborators are OPTIONAL — engine falls open when any is `None` (the fallback keyword scan handles the immune case; ring buffer + skipped observability calls handle the others).
- Wired engine reflected onto `TektosPlugin.manager` via `setattr` (fail-safe on frozen dataclass).

### D7 — Three new event types

Envelope-first `EventBusPort.publish` per ADR-023:

- `tektos.manager.feedback_generated` — payload: `session_id`, `feedback_id`, `feedback_type`, `severity`, `narrative_id | None`.
- `tektos.manager.archetype_recognized` — payload: `session_id`, `category`, `occurrence_count`, `threshold`, `feedback_id`, `narrative_id | None`.
- `tektos.manager.guardrail_triggered` — payload: `session_id`, `guardrail_source` (`"immune"` when routed through ImmunePort, `"fallback_keyword"` when the plugin-internal branch handled it), `detector_hits` (tuple; may be empty), `feedback_id`, `narrative_id | None`.

Both event names respect ADR-092 backward compatibility (no existing event types renamed). Metric samples flow through `ObservabilityPort.score()` (ADR-025) — no new event type for those.

### D8 — FastAPI router surface

One router factory in `plugins/tektos/manager/api.py`:

- `build_manager_router(engine)`:
  - `POST /tektos/api/manager/task-start` — body `{session_id, task_id, spec_id}`.
  - `POST /tektos/api/manager/task-complete` — body `{session_id, task_id, success, tokens_used, tools_used, elapsed_seconds}`.
  - `POST /tektos/api/manager/error` — body `{session_id, category, description, severity}`; response `{feedback | null, narrative_id | null}`.
  - `POST /tektos/api/manager/spiral-update` — body `{session_id, new_radius, description}`.
  - `GET /tektos/api/manager/health` — response `ManagerHealthReport`.
  - `GET /tektos/api/manager/recent` — query `?limit=N` (default 10); response `{count, items}`.

Router uses `APIRouter(tags=["tektos.manager"])` with **no internal prefix** (mount-time prefix per Stage 8.3/8.4/8.5 pattern). Missing engine → `503 {"detail": "ADR-108 degrade: manager not wired", "adr": "ADR-108"}` via a `_guard()` closure inside the factory.

### D9 — Fail-open + explicit deferrals

- Fail-open pattern (`try/except Exception` with `log.exception`) around every `RelationalMemoryPort.write_narrative`, `EventBusPort.publish`, `ImmunePort.scan`, and `ObservabilityPort.score` call — engine functionality never blocked by port failures; the ring buffer + fallback keyword scan + skipped observability calls are always available as fallback.
- Explicit deferrals from 8.6:
  - **Skill / tool creation when an archetype hits threshold.** Donor's `_generate_archetype_feedback` comment reads "Create permanent skill or tool `<category>` to handle this pattern." Skill creation itself is the donor's `src/tektos/skills/manager.py` (830 LOC) — its own subsystem, deferred to a future skill-registry stage. At 8.6 the manager only *emits the feedback* — `Archetype.permanent_structure_id` stays `None` until the skill-registry stage lands. **Discharged (Stage 14.6, 2026-09-26):** the full donor skills substrate (registry + manager + executor, ~2,100 LOC) is now kernel-native at `kernel/skills/` (byte-verbatim port, same class as `db_manager` / `metabolism` / `rag_retriever`), booted as `registry.tektos_skills` with the three donor seams fail-open (tool registry → `registry.tektos_tools`, memory → injected `DictMemoryStore` adapter, db → `data/tektos_skills.db`). 16 skill routes + the T8c-8c `POST /api/dreamtime/trigger-skill-generation` route are live on the kernel surface. Note: `permanent_structure_id` auto-creation at archetype threshold remains un-wired (the manager still only *emits the feedback*); the discharge is the skill-store substrate + REST surface, not the archetype→skill auto-creation loop.
  - **Rhythm-hook scheduler.** Donor's `Manager.on_rhythm_event()` is a passive feedback generator; no scheduler wires into it at 8.6. Circadian/ultradian/heartbeat scheduling deferred to Stage 8.7+ (multi-agent orchestrator).
  - **Recovery-strategy state-machine execution.** ADR-107 D9 deferred the retry / alternative-tool / skip execution loop to the manager. Kosmos discharges this at 8.6 by exposing a `classify_recovery(category)` helper on `TektosManager` that returns a `RecoveryStrategy` Literal (`"retry"` / `"alternative_tool"` / `"skip"`) — the actual retry loop stays in a future Stage 8.7 multi-agent orchestrator, but the classification surface is present. (Discharges ADR-107 D9 point 1.)
  - **`ToolPerformance` mutable running stats.** ADR-107 D9 deferred these to the manager. Kosmos rejects duplicating them: `ObservabilityPort.score()` already collects tool-success ratio + latency samples via OTel; querying per-tool percentiles is an ObservabilityPort concern. (Discharges ADR-107 D9 point 2 by delegation.)
  - **Integration with `TektosTurnLoop`.** ADR-107 D9 deferred this to the manager. Kosmos defers again: at 8.6 the turn loop stays untouched; the manager becomes a peer that turn-loop callers may consult but that requires no turn-loop modification.
  - **`ManagerPort`** — Stage 8.7+ (D11); at 8.6 the `TektosPlugin.manager` object-slot field IS the coupling surface.

### D10 — Engine stays optional

Mirrors ADR-104 D11 + ADR-105 D5 + ADR-106 D10 + ADR-107 D10: manager engine is optional. Existing tests do not depend on wiring; env-gate defaults `off`.

### D11 — REJECTS `ManagerPort` at 8.6

- No cross-plugin consumer of a formal `ManagerPort` exists at 8.6 (`TektosTurnLoop` is inside the same plugin; the Stage 8.7 multi-agent orchestrator also lives inside `plugins/tektos/*`).
- `TektosPlugin.manager: object | None` field IS the coupling surface.
- Port surface would grow substantially when the Stage 8.7 multi-agent orchestrator + skill-registry stage add second and third consumers; locking a Protocol now would over-fit the routing-plus-lifecycle shape.

### R1 — REJECTS donor `agents/manager/telemetry.py` at 8.6 (Colossus-only hardware surface)

Donor `telemetry.py` (601 LOC) is RTX 5090 + pynvml + `/tmp/tektos/fan_controller.sock` Unix-socket daemon + `subprocess.run("nvidia-smi", …)` + `nvmlDeviceSetPowerLimit`. Kosmos already ships `ThermalPort` (ADR-081) at `ports/thermal.py` with the identical RTX 5090 threshold table (Yellow=51°C, Cap=80°C+400W, Red=88°C) and a Tektos adapter at `adapters/thermal/tektos/`. The manager consumes `ThermalPort` (existing) if a downstream call site needs thermal-aware decisions, but the manager is not the thermal orchestrator. No PORTING_LEDGER entry lands for telemetry.py at 8.6.

### R2 — REJECTS in-process `PrimeMoverMetrics.samples: list[MetricSample]` accumulator at 8.6

Duplicates `ObservabilityPort` (ADR-025). Kosmos delegates metric recording to `ObservabilityPort.score()` / `log_cost()` (which already writes to OTel counters + histograms and derives p50/p95/p99 at query time). Threshold table + `check_threshold()` semantics preserved as a **pure function** on `TektosManager` module-scope (`_check_threshold(name, value) -> "warning" | "critical" | None`); the manager consults the threshold table when routing feedback but never stores samples in-process.

### R3 — REJECTS donor's inline `_check_guardrails()` regex as the sole detection surface

Duplicates `ImmunePort` (ADR-079). Kosmos routes guardrail checks through `ImmunePort.scan()` with `kind="tektos.manager.guardrail"`. Donor's regex is preserved as a **fallback keyword scan** used only when `ImmunePort` is unbound (D9 fail-open).

### R4 — Pydantic on donor `ManagerFeedback` / `ArchetypeEvent` / `Archetype` / `MetricSample` / `MetricThreshold`

Rejected. Kosmos convention (ADR-105/106/107): frozen slotted dataclasses everywhere in engine code paths.

## Rationale

The manager is the fifth Tektos engine subpackage under `plugins/tektos/` and follows the ADR-105/106/107 shape exactly — the four-decision skeleton (D1 scope · D2 rewrite · D3 write surface · D4 constants) plus the same D5–D10 wiring / event / router / fail-open blocks. That parity keeps the boot-slot table and `TektosPlugin` dataclass predictable and lets the shared `_boot_stage_8_x_engine` helper stay untouched (the manager's bespoke boot mirrors the executor's bespoke boot from ADR-107 D6 for the same reason: extra collaborators).

Delegating guardrails to `ImmunePort` and metrics to `ObservabilityPort` — instead of duplicating both in-process — is the exact pattern Plan v2 §4 line 101 specified. Kosmos already ratified those ports for Stage 3.13 (ADR-079) and Stage 1.6 (ADR-025) respectively; the Tektos immune adapter with 12 detectors is already vendored. Building a parallel scanner or sample store inside the manager would violate the single-source-of-truth invariant that ADR-023 / ADR-025 / ADR-079 collectively enforce.

The donor's thermal telemetry module is a legitimate Tektos-Ultima surface for the standalone RTX 5090 workstation runtime, but Kosmos ratified `ThermalPort` (ADR-081) precisely to abstract that hardware plumbing. Landing a second thermal orchestrator inside the manager would create ambiguity about which subsystem owns power capping. Delegating to `ThermalPort` (already vendored at `adapters/thermal/tektos/`) keeps the manager focused on the S3 responsibilities Plan v2 pinned it to.

Rejecting `ManagerPort` at 8.6 is consistent with ADR-105/106/107 D11: single-consumer surfaces do not warrant a formal port until a second consumer exists. Stage 8.7 (multi-agent + hierarchical + long-running orchestrators) may be the point where `ManagerPort` becomes worth authoring; if so, an amendment ADR will supersede this decision at that time.

## Consequences

Files added:

- `docs/adrs/ADR-108-tektos-manager.md` (this ADR)
- `plugins/tektos/manager/__init__.py`
- `plugins/tektos/manager/models.py`
- `plugins/tektos/manager/guardrails.py`
- `plugins/tektos/manager/archetype_tracker.py`
- `plugins/tektos/manager/engine.py`
- `plugins/tektos/manager/api.py`
- `plugins/tektos/tests/test_stage_8_6_manager_engine.py`
- `plugins/tektos/tests/test_stage_8_6_manager_archetype_tracker.py`
- `plugins/tektos/tests/test_stage_8_6_manager_guardrails.py`
- `plugins/tektos/tests/test_stage_8_6_manager_router.py`
- `tests/kernel/test_stage_8_6_manager_wiring.py`

Files modified:

- `docs/adrs/README.md` — ADR-108 row inserted between ADR-107 and ADR-106.
- `docs/Kosmos-Build-Spec-v26.md` §17 — ADR-108 row inserted above ADR-107.
- `docs/Kosmos-Build-Sequence-v26.md` — Stage 8.6 stanza appended after Stage 8.5.
- `docs/PORTING_LEDGER.md` — two new entries appended to Tektos section (manager engine VENDORED · ADR-108; archetype-tracker VENDORED · ADR-108).
- `plugins/tektos/plugin.py` — `TektosPlugin` grows `manager: object | None = None` field with ADR-108 D5 comment.
- `kernel/app.py` — one new `_BootRegistry` slot + one `_boot_tektos_manager` bespoke boot function; one new `registry.tektos_manager = _boot_tektos_manager` binding inserted after the Stage 8.5 slot assignments.
- `BUILD_LOG.md` — one appended entry per `kosmos-log-maintenance`.
- `SESSION_HANDOFF.md` — overwritten to reflect Stage 8.6 complete state.

Ports preserved / reinforced:

- **ADR-007** — new subpackage imports only from `ports.*` + own subpackage; enforced at test time via existing AST scan.
- **ADR-008** — every `write_narrative` supplies locked `provenance="tektos.manager"` + `confidence=0.75 ∈ (0, 1]`.
- **ADR-023** — envelope-first `EventBusPort.publish` upheld; never positional args.
- **ADR-025** — `ObservabilityPort.score()` is the metric-recording surface; no duplicate in-process sample store.
- **ADR-079** — `ImmunePort.scan()` is the guardrail-scanning surface; donor's regex kept only as fallback keyword scan for D9.
- **ADR-081** — donor `telemetry.py` REJECTED; `ThermalPort` retains ownership of the RTX 5090 threshold table.
- **ADR-092** — no existing event types renamed.
- **ADR-101** — degrade pattern for optional kernel-boot collaborators + request-time degrade in FastAPI router (503 + `adr` marker).
- **ADR-102** — `RelationalMemoryPort.write_narrative` is the persistence substrate.
- **ADR-104** — `TektosTurnLoop` untouched at 8.6.
- **ADR-105 / ADR-106 / ADR-107** — sibling engines share the same shape; the shared boot helper serves ADR-105 + ADR-106 + ADR-107 for the two-collaborator engines; the manager uses a bespoke boot function per the ADR-107 executor pattern.

Test count target: ~55 new tests (~24 engine + ~10 archetype + ~4 guardrails + ~9 router + ~8 kernel-wiring). Full regression target: **≥ 1763 passed / 21 skipped / 1 deselected** on the plugin/kernel testpaths (Stage 8.5 baseline 1708 + delta of ~47 in `testpaths` + 8 kernel-wiring tests outside `testpaths` invoked explicitly).

## Lock-in phase

Plan v2 Stage 8.6.

## References

- `Kosmos-Build-Spec-v26.md` §17 (ADR-108 row).
- `Kosmos-Build-Sequence-v26.md` (Stage 8.6 stanza).
- `docs/adrs/ADR-023-event-envelope.md`.
- `docs/adrs/ADR-025-observability-port.md`.
- `docs/adrs/ADR-079-immune-port.md`.
- `docs/adrs/ADR-081-thermal-port.md`.
- `docs/adrs/ADR-102-relational-memory-port-postgres-5th-layer.md`.
- `docs/adrs/ADR-104-tektos-turn-loop-session-and-llm-integration.md`.
- `docs/adrs/ADR-105-tektos-reflection-synthesis-experience-engines.md`.
- `docs/adrs/ADR-106-tektos-spec-planner-and-task-decomposer-engines.md`.
- `docs/adrs/ADR-107-tektos-executor-and-tool-router.md`.
- Donor: `tektos-ultima/src/tektos/agents/manager/{models,orchestrator,archetype_tracker,guardrails,metrics}.py` (1045 LOC total; telemetry.py explicitly REJECTED per R1).
- `PORTING_LEDGER.md` Tektos section.
