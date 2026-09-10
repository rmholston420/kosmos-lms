# ADR-095 — Stage 5.6 Self-Improvement + Self-Repair Propose-Only Scope

**Status:** Ratified v26
**Lock-in phase:** Stage 5.6
**Supersedes:** —

## Context

Stage 5.6 in `Kosmos-Build-Sequence-v26.md` lands the Tektos self-improvement
and self-repair sub-packages behind `ApprovalPort` with all filesystem mutation
disallowed until ADR-090 (`SelfModificationPort`) ratifies. ADR-090 explicitly
DEFERS ratification and enumerates five interim rules that Stage 5.6 must
satisfy verbatim.

The donor Tektos-Ultima sub-packages total **4246 lines** across three donor
directories (`src/tektos/self_repair/` — 2465 lines; `src/tektos/self_improvement/`
+ `src/tektos/agents/self_improvement/` — 970 lines; `src/tektos/self_modification/`
— 811 lines). The donor engines carry **real apply paths**: `RepairStrategy`
enum values like `APPLY_PATCH`, `RESTART_SERVICE`, `CLEAR_CACHE`, `FREE_VRAM`;
`self_gui_expander.py` and `self_test_expander.py` write to disk; the
`SelfRepairEngine` orchestrator ties `HealthMonitor → StrategyRegistry →
HealingWorkflows → EffectivenessTracker` into a full detect→diagnose→repair→
verify→learn loop that executes strategies against live infrastructure.

Wholesale-porting these engines would ship apply code paths inside the same
commit that carries "no apply until ADR-090 ratifies" as its Definition of Done
— even guarded behind a feature flag, the presence of executing apply code in
the Kosmos tree during the DEFERRED window is a load-bearing safety violation.

This ADR locks the scope decision for Stage 5.6: **land a minimum-viable
proposal surface that satisfies ADR-090's five interim rules and physically
cannot execute an apply path**, and defer the donor engines' `apply()`
machinery to a post-ratification stage.

## Decision

### D1 — Vendor donor data-model primitives only; hand-build proposal flow

Vendor **only** the pure-data primitives from the donor engines into
`adapters/tektos/vendor/`:

- `adapters/tektos/vendor/self_repair_models_donor.py` — `RepairStatus` +
  `RepairStrategy` enums and the `RepairRecord` dataclass shape (fields only;
  no orchestration methods).
- `adapters/tektos/vendor/self_improve_models_donor.py` — `ExperienceRecord`
  dataclass shape (fields only; `to_dict()` / `to_json()` / `from_dict()`
  serializers retained since they are pure data).

Do **not** vendor:

- `self_repair/engine.py` — carries the orchestrator that executes strategies.
- `self_repair/strategies.py` — carries `APPLY_PATCH`, `RESTART_SERVICE`,
  `CLEAR_CACHE`, `FREE_VRAM` implementations.
- `self_repair/workflows.py` — carries healing workflows that mutate state.
- `self_repair/health_monitor.py` — carries threat-detection subscribers.
- `self_repair/effectiveness.py` — carries learning-loop state that would
  imply an apply→observe cycle.
- `self_improvement/engine.py` — carries the `SelfImprovementAdapter`
  cybernetic feedback loop that persists experience records and triggers
  meta-learning against live infrastructure.
- `agents/self_improvement/loop_orchestrator.py` — carries the session-lifecycle
  hook path that would auto-trigger self-modification on session completion.
- `self_modification/self_gui_expander.py`, `self_modification/self_test_expander.py`
  — carry filesystem-mutating expansion paths.

### D2 — Two Kosmos-native plugins under `plugins/tektos/self_improve/` + `plugins/tektos/self_repair/`

Each plugin exports one `Proposer` class with exactly two public methods:

- `async def propose(...) -> str` — builds a proposal dataclass, calls
  `ApprovalGatewayPort.propose(intention_id, delta, tier=HUMAN_REQUIRED,
  proposing_domain="tektos", diff_preview=...)`, writes to `MemoryPort` with
  `provenance="tektos_self_modification"` + `confidence=0.85` (satisfies
  ADR-090 interim rule 3 + spec §25.4 `≤ 0.9` invariant), publishes
  `tektos.self_modification.proposed` on the event bus (already reserved by
  ADR-086), and returns the `approval_id`.
- `async def apply(approval_id: str) -> Never` — **raises
  `NotImplementedError` with a fixed message referencing ADR-090**. Physically
  cannot mutate the filesystem — belt-and-suspenders on top of the
  approval-gate deny path.

There is **no** `_run_strategy()`, no `_execute_repair()`, no
`_expand_gui()`, no `_expand_tests()`, no `_persist_experience()` code path.
The plugins are pure propose-and-record.

### D3 — Approval tier locked to `HUMAN_REQUIRED`

Every self-modification proposal uses `ChangeApprovalTier.HUMAN_REQUIRED`.
Never `HUMAN_REVIEW` (which would allow provisional execution during the
4-hour escalation window) and never `AUTONOMOUS` (which would auto-approve).
This satisfies ADR-090 interim rule 5 ("no ApprovalPort verdict → no apply")
and ADR-019 (Approval UX) for the highest-risk change class.

### D4 — Deny-path memory write

When a proposal is denied (via `ApprovalResolverPort.resolve(approved=False)`),
the proposer writes a second `MemoryPort` triple with
`predicate="tektos.self_modification.denied"`,
`provenance="tektos_self_modification"`, `confidence=0.85`, and the resolution
`reason` in `attributes`. This closes the audit loop so denials are as
observable as proposals.

### D5 — No `SelfModificationPort` file lands in Stage 5.6

Per ADR-090 §Consequences bullet 1, `ports/self_modification.py` does **not**
land in Stage 5.6. The Stage-5.6 plugins consume `ApprovalGatewayPort` +
`MemoryPort` + `EventBusPort` directly. When ADR-090 flips PROPOSED → RATIFIED
in a later stage, the plugins refactor to use `SelfModificationPort` as their
proposal surface and gain their `apply()` implementations at that time.

## Rationale

### Why not port the donor engines wholesale?

- Ships apply code paths into the tree during the ADR-090 DEFERRED window.
- Would require deleting hundreds of lines of engine code to satisfy the
  Stage 5.6 DoD (no filesystem mutation), leaving vendored code that no
  longer resembles the donor.
- Effectiveness-tracker and meta-learning-loop code paths implicitly assume
  an apply→observe cycle; landing them without apply produces dead code.

### Why not skip vendoring entirely and hand-build everything?

- The `RepairStatus`/`RepairStrategy` enum vocabulary is stable donor-side and
  worth preserving for a future engine port — reinventing enum names would
  create a naming discontinuity when the donor engines eventually land.
- `ExperienceRecord` field shape is likewise stable and matches the
  serializer contract that will feed the future Hindsight bridge (Stage 7.4).

### Why `confidence=0.85`?

- ADR-090 interim rule 3 requires `confidence ≤ 0.9` for the
  `tektos_self_modification` provenance.
- Spec §25.4 (`Kosmos-Build-Spec-v26.md` line 721) locks the same `≤ 0.9`
  invariant.
- `0.85` gives 0.05 headroom below the ceiling, matching how the immune
  system writes `1.0` and Tektos tool invocations write `1.0` — a
  clearly-lower confidence marks self-modification as a distinct trust tier
  in the graph.

### Why publish `tektos.self_modification.proposed` on the bus?

- Already reserved by ADR-086 (event_type namespace lock).
- Downstream consumers (Tektos UI dashboard, future ImmunePort
  SelfModificationDetector) can subscribe without touching this plugin.

## Consequences

### Files that land in Stage 5.6

- `adapters/tektos/vendor/self_repair_models_donor.py` (new; ~120 lines).
- `adapters/tektos/vendor/self_improve_models_donor.py` (new; ~60 lines).
- `plugins/tektos/self_improve/__init__.py` (new).
- `plugins/tektos/self_improve/proposer.py` (new; SelfImprovementProposer +
  SelfImprovementProposal + tests-hook).
- `plugins/tektos/self_improve/test_proposer.py` (new; contract tests).
- `plugins/tektos/self_repair/__init__.py` (new).
- `plugins/tektos/self_repair/proposer.py` (new; SelfRepairProposer +
  SelfRepairProposal + tests-hook).
- `plugins/tektos/self_repair/test_proposer.py` (new; contract tests).

### Files touched (spec fan-out)

- `docs/Kosmos-Build-Sequence-v26.md` — Stage 5.6 stanza gains
  "(ADR-095)" reference in the What-lands sentence.
- `docs/adrs/README.md` — new row for ADR-095; open-decisions sentence
  updated to cite ADR-095 as Stage 5.6 landing.
- `PORTING_LEDGER.md` — 3 new VENDORED rows (2 donor primitives + the
  intentional non-port of the donor engines documented as a rejection with
  ADR-095 rationale).
- `BUILD_LOG.md` — 7 append-only entries.
- `SESSION_HANDOFF.md` — overwrite for end-of-session state.

### Testing DoD

- Happy-path propose (× 2, one per plugin): asserts the returned
  `approval_id` is a string, the `MemoryPort.write_event` call carried the
  correct provenance + confidence, and the `EventBusPort.publish` call
  carried a `tektos.self_modification.proposed` envelope with
  `producer_plugin="tektos"`.
- `apply()` raises `NotImplementedError` (× 2, one per plugin): asserts the
  exception message contains `"ADR-090"`.
- Deny path (× 1): stubbed `ApprovalResolverPort` returns `REJECTED`;
  proposer's post-denial hook writes the denial triple to `MemoryPort` with
  `predicate="tektos.self_modification.denied"`.
- Confidence-invariant (× 2, one per plugin): construction with
  `confidence > 0.9` raises `ValueError` at proposer init.
- Provenance-lock (× 2, one per plugin): proposer cannot be constructed
  with an override for provenance — it is a class-level constant, not a
  ctor arg.

### Downstream impact

- Stage 7.4 (Hindsight migration H1→H2) may consume `ExperienceRecord`
  from `adapters/tektos/vendor/self_improve_models_donor.py` without
  additional vendoring.
- When ADR-090 ratifies, the proposers land a real `apply()` implementation
  that delegates to `SelfModificationPort.apply()`, and the donor engines'
  strategy code becomes eligible for port-in behind that ratified port. No
  code from Stage 5.6 needs to be deleted at ratification — only extended.

## Lock-in phase

Stage 5.6 (this ADR ratifies at the same time the plugin code lands).

## References

- ADR-007 — events-only cross-plugin coupling (both plugins consume ports,
  not other plugins).
- ADR-019 — Approval UX (HUMAN_REQUIRED tier).
- ADR-023 — EventBusPort envelope-first MVP.
- ADR-027 — MemoryPort zero-trust write invariants (provenance + confidence
  required, `confidence ∈ [0.0, 1.0]`).
- ADR-033 — ChangeApprovalTier three-tier ladder.
- ADR-078 — Kosmos-Build-Spec-v26 cut (§25.4 provenance taxonomy).
- ADR-086 — Tektos event_type namespace lock (`tektos.self_modification.proposed`
  reserved).
- ADR-090 — `SelfModificationPort` (PROPOSED; DEFERRED) — interim rules 1–5.
- `docs/Kosmos-Build-Sequence-v26.md` Stage 5.6 stanza.
- `docs/Kosmos-Build-Spec-v26.md` §7 zero-trust, §25.4 provenance taxonomy.
