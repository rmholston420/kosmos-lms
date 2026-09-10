# ADR-092 — Tektos-Ultima runtime absorption scope for Stage 3.13

**Status:** Ratified
**Lock-in phase:** Stage 3.13
**Supersedes:** —

## Context

Stage 3.13 (per `Kosmos-Build-Sequence-v26.md`) mandates that
`adapters/immune/tektos/`, `adapters/loop_safety/tektos/`, and
`adapters/thermal/tektos/` land as the first concrete adapters implementing
the six port Protocols ratified in Stage 1 (ADR-079/080/081). The
`PORTING_LEDGER.md` PLANNED rows for those adapters, and for the Tektos
runtime core, all cite paths like `tektos/orchestrator`, `tektos/immune`,
`tektos/safety`, and `tektos/thermal` in the upstream repo.

Inspection of `rmholston420/tektos-ultima` HEAD reveals the real layout is
different:

- All runtime concerns live under a **single flat module tree**
  `src/tektos/runtime/` — `immune_system.py` (1925 lines, 12 detectors +
  `ImmuneMemory` + `ResponseEngine` + `HealthDashboard` + `ImmuneSystem`
  orchestrator), `loop_safety.py` (403 lines, `LoopSafetyMonitor` +
  `LoopSafetyConfig` + `LoopSafetyReport` + `TurnSnapshot`), `loop_guard.py`
  (113 lines, thinner counterpart), plus `hierarchical_agent.py`,
  `inference_engine.py`, `session.py`, `hooks.py`, `observability.py`,
  `self_modification.py`, and 25+ other runtime siblings.
- Thermal is one of the few packages that IS a proper sub-package —
  `src/tektos/thermal/` with `metrics.py` (`MetricsCollector` +
  `NVMLCollector` + `CPUCollector` + `ThermalSnapshot`), `regulator.py`
  (`ThermalRegulator` PID + `RegulationDecision`), `monitor.py` (async
  background loop), `power_optimizer.py`, `config.py`.
- The upstream `ImmuneSystem` singleton also ships a **background asyncio
  task** (`start()` / `_check_interval=30`), an `ImmuneMemory` SQLite-style
  store, and a `HealthDashboard` aggregator — all of which are far larger
  than the Stage 3.13 DoD requires.
- The Stage 1 port Protocols (`LoopSafetyPort`, `ImmunePort`, `ThermalPort`)
  are much narrower than the donor APIs:
  - `LoopSafetyPort.record_tool_call(read_only=True)` requires the ADR-088
    read-only budget interlock, which is **not** present in the donor's
    `LoopSafetyMonitor` (donor tracks tokens + turns + wall-time +
    repetition but not read-only tool-call count).
  - `ImmunePort.Detector.evaluate()` takes an `ImmuneScanRequest` +
    returns `tuple[DetectorHit, ...]` — the donor's `Detector.detect()`
    takes an `ImmuneContext` + returns `list[Threat]` (different dataclass
    families, different severity encoding).
  - `ThermalPort.pressure()` returns a `ThermalPressure` snapshot with a
    computed `ThermalLevel` (`green` / `yellow` / `cap` / `red`) — the
    donor `MetricsCollector` returns raw temperatures with no level
    computation (that's `ThermalRegulator`'s job, which is coupled to the
    PID controller).

This mismatch could be resolved three ways:

1. Port the donor code wholesale into `plugins/tektos/runtime/` and expose
   it directly. **Rejected** — violates ADR-007 (plugins may not import
   another plugin's internals) and skips the port-boundary rewrap.
2. Rewrite the three subsystems from scratch inside `adapters/*/tektos/`.
   **Rejected** — loses the operational learnings baked into the donor
   (12 detector regex families, PID tuning constants for RTX 5090
   liquid-cooled at Colossus, repetition-detection tuning). Violates
   `kosmos-port-workflow` (vendor-before-hand-build).
3. **Chosen: vendor thin donor snapshots + write adapters that wrap them
   behind the port Protocols.** Preserves donor operational value; enforces
   port boundary; keeps the surface small enough for Stage 3.13 DoD.

## Decision

Stage 3.13 lands the following **and only the following** absorption
scope:

### 1. Vendor snapshots

Three vendored donor snapshots under
`adapters/<port>/tektos/vendor/`:

| Vendored file | Source | Reason |
|---|---|---|
| `adapters/loop_safety/tektos/vendor/loop_safety_donor.py` | `src/tektos/runtime/loop_safety.py` @ HEAD | `LoopSafetyMonitor` + config/report/snapshot dataclasses |
| `adapters/immune/tektos/vendor/immune_donor.py` | `src/tektos/runtime/immune_system.py` @ HEAD, TRIMMED to 3 seed detectors + shared dataclasses | Full 1925-line module is out of scope for Stage 3.13; seed with `PromptInjectionDetector`, `SecretExposureDetector`, `DangerousCommandDetector` |
| `adapters/thermal/tektos/vendor/thermal_donor.py` | `src/tektos/thermal/metrics.py` @ HEAD | `MetricsCollector` + `ThermalSnapshot` + telemetry dataclasses. `ThermalRegulator` PID loop, `monitor.py` async background loop, and `power_optimizer.py` are DEFERRED to a later stage (Stage 3.13+1 or Stage 4.7). |

Each vendored file carries a header comment recording upstream path,
commit SHA, SPDX license (`MIT`, per kosmos-lms re-license at port-in point
per the locked scaffold policy — donor has no `LICENSE` file, sole
copyright holder `rmholston420` per Stage 0 audit), and modifications
made.

### 2. Adapters (thin ports wrappers)

Three adapters under `adapters/<port>/tektos/`, each implementing the
Stage 1 Protocol in full:

- `adapters/loop_safety/tektos/adapter.py::TektosLoopSafetyAdapter` —
  Wraps `LoopSafetyMonitor` per-turn (one monitor instance per
  `TurnHandle`). Adds the ADR-088 read-only budget interlock (donor
  lacks it). Adapter owns per-turn state maps keyed by `turn_id`. Emits
  `loop_safety.<status>` on the injected `EventBusPort` on every state
  transition. Writes `MemoryPort` events with
  `provenance="loop_safety"`, `confidence=1.0` on terminal states.
- `adapters/immune/tektos/adapter.py::TektosImmuneAdapter` — Registers
  three seed detectors (`prompt_injection`, `secret_exposure`,
  `dangerous_command`) each wrapped as a `ports.immune.Detector`. The
  wrapper adapts the donor's `Detector.detect(ImmuneContext) → list[Threat]`
  to the port's `Detector.evaluate(ImmuneScanRequest) →
  tuple[DetectorHit, ...]`. Aggregation policy per ADR-079 (`block` if
  any hit is `block`, `warn` if any is `warn` and none `block`, else
  `allow`). Publishes `immune.verdict.<decision>` on `EventBusPort` after
  every scan. Writes `MemoryPort` on `block`.
- `adapters/thermal/tektos/adapter.py::TektosThermalAdapter` — Wraps
  `MetricsCollector.collect()` (runs in a thread via `asyncio.to_thread`
  because donor uses blocking NVML). Computes `ThermalLevel` from the
  Colossus RTX 5090 thresholds in ADR-081 (yellow 51 °C / cap 80 °C /
  red 88 °C). Publishes `thermal.<level>` on threshold crossings. Writes
  `MemoryPort` on red transitions. Caches last pressure snapshot for
  the sync `pressure()` hot-path caller (LLMPort adapters,
  ResourcePort). `apply_power_cap()` and `release_power_cap()` are
  **stubbed** — they publish the transition envelope and update the
  cached pressure but do not actually shell out to `nvidia-smi` in
  Stage 3.13 (that lands with the full `ThermalRegulator` port-in later).
  This is safe because ADR-081 spec § "adapter-configured, not
  port-hardcoded" already treats the cap as an advisory value that the
  regulator enforces.

### 3. Minimal runtime plugin

One plugin under `plugins/tektos/runtime/` — the smallest possible slice
that proves the three adapters compose:

- `plugins/tektos/runtime/__init__.py` — package marker only.
- `plugins/tektos/runtime/turn_loop.py::TektosTurnLoop` — a coroutine
  `run_turn(agent_id, prompt, tool_calls)` that:
  1. Calls `ImmunePort.scan()` on the prompt (kind
     `tektos.agent.prompt`, source `tektos_runtime`). Aborts if
     `decision == "block"`.
  2. Opens `LoopSafetyPort.begin_turn(agent_id)`.
  3. Consults `ThermalPort.pressure()`; if `level == "red"` aborts the
     turn before any tool call (matches ADR-081 § "Simulated-red-state
     test causes `LLMPort` to refuse inference" DoD, at the runtime
     layer).
  4. For each tool call: `ImmunePort.scan()` on the call, then
     `LoopSafetyPort.record_tool_call(read_only=...)`. If the immune
     verdict is `block` or the loop-safety state is any of
     `exhausted` / `repetition` / `budget_exhausted`, stop.
  5. `LoopSafetyPort.end_turn(handle)` and return the
     `TurnSummary` + a list of tool-call outcomes.
- The runtime plugin publishes `tektos.agent.turn.started`,
  `tektos.agent.turn.tool_call`, and `tektos.agent.turn.completed` on
  `EventBusPort` (payload includes `source="tektos_runtime"`).

Everything else — planner, hierarchical agent, session, hooks,
observability, self-modification, self-improvement, self-repair,
inference engine, MCP integration, RAG, repo map, backup scheduler,
context compactor, context curator, context monitor, embedder — is
**explicitly deferred** to Stage 4.7 (planner + sandbox + tool
registry), Stage 5.6 (self-*), Stage 6.5 (voice + vision), Stage 7.4
(hindsight migration), or later.

### 4. What is NOT ported in Stage 3.13

Locked exclusions:

- `ImmuneSystem` orchestrator singleton, `ImmuneMemory`,
  `HealthDashboard`, `ResponseEngine` — these are the donor's
  application-layer glue; Kosmos already has `MemoryPort` +
  `EventBusPort` doing the equivalent job. Individual `Detector`
  classes are ported one-at-a-time as `ports.immune.Detector`
  implementations.
- 9 of the 12 donor detectors (`context_collapse`, `resource_exhaustion`,
  `loop_detection`, `performance_degradation`, `self_degradation`,
  `self_modification`, `inference_engine_protection`, `model_failover`,
  `body_protection`) — deferred to a follow-up Stage 3.13+n batch. Seed
  set is `prompt_injection`, `secret_exposure`, `dangerous_command`
  because those three cover the highest-value detection surface for the
  first end-to-end vertical slice and are self-contained (no coupling
  to other donor subsystems).
- `ThermalRegulator` PID loop, `monitor.py` async background loop,
  `power_optimizer.py`. Adapter surfaces sample + pressure only; power
  cap is a stub that publishes the envelope but does not touch NVML.
- `loop_guard.py` — donor has both `loop_safety.py` and `loop_guard.py`;
  Stage 3.13 uses `loop_safety.py` (the fuller implementation) and
  drops `loop_guard.py` as a duplicate.

## Rationale

Chosen over the two rejected alternatives because:

- **vs. wholesale plugin import:** ADR-007 (events-only cross-plugin
  coupling) is non-negotiable. The donor's `ImmuneSystem` orchestrator
  would pull the runtime plugin into a hard dependency on
  `ImmuneMemory` + `ResponseEngine` + `HealthDashboard` — none of which
  match any Kosmos port and all of which duplicate `MemoryPort` +
  `EventBusPort` functionality. Wrap-behind-adapter cleanly severs the
  coupling.
- **vs. hand-rewrite:** the donor's 12 detector regex families and the
  PID tuning for Colossus's RTX 5090 encode operational learnings that
  would be expensive to reconstruct. `kosmos-port-workflow` requires
  vendor-before-hand-build.

Choosing three seed detectors keeps Stage 3.13 within the
Definition-of-Done envelope. The runtime `TurnLoop` is deliberately
minimal — it proves the three adapters compose correctly through the
port Protocols and emits the expected event stream, without pulling in
the LLMPort/planner/sandbox surface (those land Stage 4.7).

The thermal power cap is stubbed rather than implemented because the
donor's real power cap runs a PID loop against `nvidia-smi` on Collosus
hardware; the Cloud sandbox where CI runs has no NVML. Stubbing keeps
the port surface honest (transition envelopes fire, cache updates,
idempotency works) while avoiding a CI-only NVML branch. Real power
capping lands with the full `ThermalRegulator` port-in.

## Consequences

- New files:
  - `docs/adrs/ADR-092-tektos-runtime-absorption-scope.md` (this)
  - `adapters/loop_safety/__init__.py`, `adapters/loop_safety/tektos/{__init__,adapter,vendor/__init__,vendor/loop_safety_donor}.py`
  - `adapters/immune/__init__.py`, `adapters/immune/tektos/{__init__,adapter,vendor/__init__,vendor/immune_donor}.py`
  - `adapters/thermal/__init__.py`, `adapters/thermal/tektos/{__init__,adapter,vendor/__init__,vendor/thermal_donor}.py`
  - `plugins/tektos/__init__.py`, `plugins/tektos/runtime/{__init__,turn_loop}.py`
  - Adapter-specific behavioural tests under each adapter's `test_contract.py`
  - `plugins/tektos/runtime/test_turn_loop.py`
- Modified files:
  - `docs/adrs/README.md` — index row for ADR-092
  - `PORTING_LEDGER.md` — five rows flipped `PLANNED → VENDORED`
    (Tektos immune, Tektos loop-safety, Tektos thermal metrics,
    Tektos runtime seed, kosmos-plugin `tektos-runtime`)
  - `BUILD_LOG.md` — one entry per Stage 3.1–3.8 subtask
  - `SESSION_HANDOFF.md` — overwritten at session end
- Procedures affected:
  - `kosmos-port-workflow` vendor-before-hand-build satisfied for
    loop-safety, immune, thermal.
  - `kosmos-adr-authoring` fan-out satisfied (ADR + index + ledger + BUILD_LOG).
- Downstream ADRs:
  - **ADR-079** (ImmunePort) — `PromptInjectionDetector`,
    `SecretExposureDetector`, `DangerousCommandDetector` become
    reference implementations of `ports.immune.Detector`. 9 additional
    detectors deferred but tracked in a new `PORTING_LEDGER` "Tektos
    additional immune detectors" PLANNED row.
  - **ADR-080** (LoopSafetyPort) — `TektosLoopSafetyAdapter` becomes
    the reference implementation. Per-turn `LoopSafetyMonitor` instance
    is an implementation detail hidden from the port.
  - **ADR-081** (ThermalPort) — `TektosThermalAdapter` is the
    reference implementation for telemetry + level computation. Real
    power capping deferred; adapter emits `thermal.power_cap.applied` /
    `thermal.power_cap.released` transition envelopes but does not
    shell out to NVML.
  - **ADR-088** (LoopSafety read-only budget) — the interlock is
    implemented in `TektosLoopSafetyAdapter` because the donor
    `LoopSafetyMonitor` lacks it. Adapter owns the budget map keyed by
    `turn_id`.

## Lock-in phase

Stage 3.13. This ADR is amended only if a follow-up stage promotes any
of the deferred items (`ImmuneSystem` orchestrator, remaining 9
detectors, PID `ThermalRegulator`, `loop_guard.py`) into an adapter or
plugin surface.

## References

- `Kosmos-Build-Spec-v26.md` §25.4 (immune provenance),
  §25.5 (kernel boot registry), §25.6 (loop safety), §25.7
  (thermal thresholds, tektos-ultima upstream port)
- `Kosmos-Build-Sequence-v26.md` Stage 3.13 (this stage's DoD)
- ADR-007 (events-only cross-plugin coupling)
- ADR-023 (port canonical shape, rules 2 + 5)
- ADR-079 (ImmunePort), ADR-080 (LoopSafetyPort), ADR-081 (ThermalPort),
  ADR-086 (envelope taxonomy), ADR-088 (read-only budget interlock)
- `kosmos-port-workflow` skill (vendor-before-hand-build)
- `PORTING_LEDGER.md` (updated in this stage)
- Upstream donor: `github.com/rmholston420/tektos-ultima` @ HEAD as of
  2026-09-10; `src/tektos/runtime/loop_safety.py`,
  `src/tektos/runtime/immune_system.py`, `src/tektos/thermal/metrics.py`
