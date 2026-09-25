# ADR-128: kernel-native `/api/self_repair/status` — propose-only proposer + strategy catalog

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.12 (endpoint split, self_repair family)
- **Supersedes:** none

## Context

The Tektos dashboard **Self-Repair** card proxied `:8020/api/self_repair/status` —
the standalone engine's *executing* repair daemon: `running`, `uptime_seconds`,
`completed_repairs`, `failed_repairs`, effectiveness rates, 8 registered strategies.

The kernel has **no executing repair daemon**. Its self-repair surface is the
propose-only `SelfRepairProposer` (Stage 5.6, ADR-095 D2 + ADR-090 interim):

1. Builds a `SelfRepairProposal` from a donor `RepairRecord` + strategy label.
2. Routes it through `ApprovalGatewayPort.propose` at tier **HUMAN_REQUIRED**
   (ADR-095 D3) — never auto-applied.
3. Writes a MemoryPort triple: `provenance="tektos_self_modification"`,
   `confidence=0.85` (spec §25.4 ceiling 0.9).
4. Publishes `tektos.self_modification.proposed` on the event bus (ADR-086).
5. `apply()` physically raises `NotImplementedError` (ADR-090) — cannot execute.

Before this ADR the proposer was never booted in the kernel (no registry slot).
Layering (per user directive): policy is plugin-level (Tektos proposer);
substrate (ApprovalPort / MemoryPort / EventBusPort) is kernel-level.

## Decision

### D1 — `KOSMOS_TEKTOS_SELF_REPAIR={off,on}` boot gate (default `off`)
`_boot_tektos_self_repair()` (shared `@_try` pattern, ADR-101 degrade): requires
`registry.approval` + `registry.memory` + `registry.event_bus` non-None; missing
→ WARN + `None`. No new dependency — all three are core kernel subsystems.
Wired slot: `registry.tektos_self_repair`.

### D2 — kernel-native `GET /api/self_repair/status` (always 200)
```json
{
  "status": "initialized | degraded",
  "healthy": true,
  "note": "propose-only (ADR-095 D2): HUMAN_REQUIRED approval, no execution in kernel",
  "proposer": { "wired": true, "tier": "HUMAN_REQUIRED",
                "confidence": 0.85, "provenance": "tektos_self_modification" },
  "strategies": { "strategies_registered": 19,
                  "categories": { "code": 4, "context": 4, "escalation": 1,
                                   "infrastructure": 5, "recovery": 2, "workload": 3 },
                  "strategy_names": ["apply_patch", "change_approach", ...] },
  "execution": "not wired in kernel (standalone Tektos repair engine, :8020/api/self_repair/status)",
  "errors": [], "timestamp": "..."
}
```

**Strategy catalog is static data** — the vendored donor `RepairStrategy` enum
(19 labels) grouped into the donor's own category comments — reported **even when
the proposer is off**, so the card is never empty (same rule as the ADR-126
capability table). The catalog is **self-checked against the enum**: any
member missing from (or extra in) the category map surfaces as an `errors[]`
entry — the count reflects the intersection, never a fabricated number.

`wired: false` (the default) = valid degraded state. `proposer.confidence` /
`provenance` read the **live** proposer (`_confidence`, class-level
`provenance`) — the ADR-095 D2 locked values.

### D3 — execution honesty
The `execution` field explicitly says the repair loop stays on the standalone
engine. No fabricated `completed_repairs` / effectiveness / uptime — none of
those counters have a kernel referent.

### D4 — card re-point
`page.tsx`: Self-Repair card `base: ""` (kernel-native); parseCard rewritten for
the ADR-128 object envelope: line 1 `proposer live · HUMAN_REQUIRED` /
`proposer offline`; line 2 `19 strategies · code 4 · context 4 · …`; detail:
`propose-only (ADR-095 D2) · execution on standalone repair engine (:8020)`.

## Consequences

- The dashboard Self-Repair card now reports kernel truth (propose-only
  proposer + static strategy catalog) instead of the standalone daemon's counters.
- The ADR-090 seam is visible: proposals flow through ApprovalPort in-kernel;
  execution is a named, honest deferral.
- The 19-label catalog (not :8020's 8) reflects the donor vocabulary a future
  post-ADR-090 `SelfRepairEngine` will consume.
