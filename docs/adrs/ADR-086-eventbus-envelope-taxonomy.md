# ADR-086 — EventBusPort envelope taxonomy for Tektos absorption

**Status:** Ratified
**Lock-in phase:** Stage 3.13
**Amends:** ADR-023 (EventBusPort envelope-first MVP — this ADR locks the envelope-kind namespace)

## Context

ADR-023 locked `EventBusPort` with envelope-first publishing but left the `event_type` namespace open (envelopes have `producer_plugin`; the string `event_type` is a free-text convention). Tektos-Ultima absorption introduces envelopes from immune, loop-safety, thermal, sandbox, hindsight, gateway, planner, tool-registry, and frontend subsystems. Without a locked namespace, adapters will invent overlapping strings (`immune.blocked` vs `immune.block` vs `immune_verdict`) and downstream subscribers will miss events.

## Decision

Lock the following envelope-kind taxonomy for Tektos-side publications. Format: `<subsystem>.<action>[.<qualifier>]`.

### Immune

- `immune.scan.started` — every `ImmunePort.scan()` invocation.
- `immune.verdict.allow` — verdict allowed.
- `immune.verdict.warn` — verdict warned.
- `immune.verdict.block` — verdict blocked.
- `immune.detector.registered` — `ImmunePort.register_detector()` success.

### Loop safety

- `loop_safety.turn.started` / `loop_safety.turn.ended`.
- `loop_safety.state.ok` / `.warn` / `.exhausted` / `.repetition` / `.budget_exhausted`.
- `loop_safety.read_only_budget_exhausted` (spec §25.6) — text-only completion forced.

### Thermal

- `thermal.sample` — periodic sample envelope (default 5 s cadence; configurable).
- `thermal.green` / `.yellow` / `.cap` / `.red` — threshold-crossing envelopes.
- `thermal.power_cap.applied` / `.released`.

### Sandbox

- `sandbox.started` / `sandbox.completed` / `sandbox.killed`.

### Hindsight (Stages 3–5 only; retired at Stage 7.4)

- `hindsight.write` / `hindsight.read`.

### Tektos runtime

- `tektos.turn.started` / `tektos.turn.completed`.
- `tektos.plan.node.created` / `.completed` / `.aborted`.
- `tektos.tool.invoked` / `tektos.tool.result`.
- `tektos.self_modification.proposed` (gated behind ADR-090; never `.applied` until ratified).
- `tektos.gateway.envelope.replayed`.
- `tektos.frontend.action` — user-initiated frontend actions.

### Cross-subsystem rule

Every envelope MUST populate `producer_plugin` per ADR-023 rule 2 with the emitting plugin's canonical name (`tektos`, `phrouros`, `praxis`, etc.). Envelope-kind strings alone do NOT identify the producer.

### Reserved prefixes

No other subsystem may publish under `immune.*`, `loop_safety.*`, `thermal.*`, `sandbox.*`, `hindsight.*`, `tektos.*`. Adapters emitting envelopes in these namespaces MUST be Tektos-side.

## Rationale

- **Locked taxonomy over free-text**: prevents the "immune.blocked vs immune.block" divergence Tektos-Ultima's parallel history already contains.
- **Dot-namespace format** matches Kosmos's existing conventions (`zetesis.research.started`, `phrouros.anomaly.detected` from prior ADRs).
- **Reserved prefixes** enforce clean subsystem ownership.
- **Rejected: use `producer_plugin` alone to identify subsystem.** Same plugin (`tektos`) emits envelopes from multiple subsystems; a subsystem prefix is needed for subscribers that only care about one.

## Consequences

- Files edited (this ADR): `ports/event_envelope.py` gets a docstring update enumerating the reserved namespaces (no code change to the value object).
- Files created (this ADR): none.
- Files edited (Stage 3.13+): every Tektos-side adapter and plugin publishes with these envelope kinds.
- CI check (Stage 0.7 CI baseline): a lint check flags publications using unlisted namespaces from Tektos-side code.

## Lock-in phase

Locked at Stage 3.13. New namespaces (e.g. a future `nomisma.*`) added by future ADRs.

## References

- ADR-023 (EventBusPort envelope-first MVP — this locks the namespace)
- ADR-077, ADR-078 (v26 §25.4)
