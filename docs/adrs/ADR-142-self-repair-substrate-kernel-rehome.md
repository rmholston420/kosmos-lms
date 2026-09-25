# ADR-142: self-repair substrate re-homed to kernel shared infrastructure (DI policy injection)

- **Status:** Ratified (2026-09-25)
- **Scope:** ADR-141 R1–R6 execution (self-repair daemon port) — layering
- **Supersedes:** none (amends the placement implied by ADR-141 Decision 1)
- **Governing constraint:** user layering rule (verbatim, 2026-09-25):
  *"Tektos-Ultima had some functions that were specific to it as a coding
  agent that should remain in Kosmos-LMS Tektos, and others that should be
  elevated to Kosmos-LMS's shared/common infrastructure, and it was for you
  to determine what was most optimal."*

## Context

ADR-141 R1–R6 ported the donor self-repair daemon (2,465-LOC package)
entirely under `plugins/tektos/self_repair/`. When the user re-stated the
layering rule on 2026-09-25, the under-application was acknowledged: the
port had treated the whole subsystem as Tektos-specific when it actually
splits by **nature** into two classes.

## Decision

The subsystem is split at the substrate/policy boundary:

| Piece | Nature | Home |
|---|---|---|
| `SelfRepairEngine` (daemon lifecycle: diagnose → repair → verify → learn, degradation ladder, callbacks) | generic self-healing machinery | `kernel/reliability/engine.py` |
| `HealthMonitor` (score aggregation, status math, trend) | generic | `kernel/reliability/health_monitor.py` |
| `RepairEffectivenessTracker` (success-rate ledger, memory entries) | generic | `kernel/reliability/effectiveness.py` |
| Data models (`RepairRecord`, `RepairStatus`, `RepairStrategy`, `DegradationLevel`, `RepairResult`, `HealthSnapshot`, `DegradationPlan`) | generic | `kernel/reliability/models.py` |
| 8 concrete repair strategies (resource exhaustion, context overflow, loop detection, prompt injection, …) | Tektos threat-model policy | `plugins/tektos/self_repair/strategies.py` |
| 6 healing workflows (GPU thermal crisis, context collapse, loop recovery, …) | Tektos threat-model policy | `plugins/tektos/self_repair/workflows.py` |
| `SelfRepairProposer` (ADR-095 propose-only surface) | Tektos plugin flow | `plugins/tektos/self_repair/proposer.py` (unchanged) |

This puts the substrate in the same class as the existing kernel subsystems
(`kernel/tektos_immune.py`, `tektos_thermal_watchdog.py`, `tektos_telemetry.py`)
— self-repair was the odd one out while living under the plugin.

### DI seam (ADR-007: kernel must not import plugins)

`SelfRepairEngine.__init__` accepts optional keyword parameters
`strategy_registry` and `healing_workflows`. The composition root
(`kernel/app.py` boot block) imports both sides and injects the plugin's
`get_strategy_registry()` + `get_healing_workflows()` at boot. Degradation
is honest, never a crash:

- `strategy_registry=None` → `list_strategies()` returns empty; every
  repair escalates (`escalate_to_user` + `EMERGENCY` degradation).
- `healing_workflows=None` → workflow execution raises; repair degrades.

`reset_self_repair_engine()` is substrate-only (engine + substrate
singletons); plugin singletons reset from `tests/plugins/` (tests may import
the plugin).

### Provenance note

The vendor file `adapters/tektos/vendor/self_repair_models_donor.py` was
`git mv`'d to `kernel/reliability/models.py` (R2 had extended it with
`RepairResult`/`HealthSnapshot`/`DegradationPlan`); the vendor directory
retains only `self_improve_models_donor.py`.

## Verification (2026-09-25)

- Substrate imports standalone: zero `plugins.*` modules loaded after
  `import kernel.reliability` (ADR-007 clean).
- WIRED engine (DI injection) reproduces donor behavior exactly:
  95°C resource-exhaustion ctx → `throttle_workload` → completed → verified;
  8 strategies + 6 workflows registered.
- BARE engine (no injection): `escalate_to_user` + `EMERGENCY` — honest.
- Full test suite green (PYTEST_EXIT=0, only opt-in skips).
- Kernel restart: `/health` ok, no self-repair boot error.

## Execution trail

| Step | Commit |
|---|---|
| Substrate re-home + DI seam | `94cf998` |
| R7: kernel routes (`/status` dual-surface, `/history`, `/repair`, `/health`) | `5cb5f46` |
| R8: ops self-repair tab fully kernel-native + 16 route tests | `20343da` |

**ADR-139 split status: CLOSED** — status, history, and trigger are all
served by the kernel; the tab no longer touches the ADR-109 gateway.

## Consequences

- The remaining `plugins/tektos/self_repair/` is pure Tektos threat-model
  policy — clean for the Stage 14.5 `main.py` deletion gate.
- Any future shared self-healing consumer (other plugins, Zetesis) can reuse
  the substrate without importing Tektos policy.
