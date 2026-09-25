# ADR-143: self-improvement learning substrate + Hegelian loop — kernel substrate / plugin policy (T3)

- **Status:** Ratified (2026-09-25)
- **Scope:** ADR-141 T3 (self-improvement read surface) + the donor self-improvement
  learning machinery it depends on — layering
- **Supersedes:** none
- **Governing constraint:** user layering rule (verbatim, 2026-09-25): coding-agent-specific
  functions stay in the Tektos plugin; generic/shared machinery is elevated to Kosmos kernel
  shared infrastructure; Charles decides the optimal split per item.

## Context

ADR-141's exit gate lists **T3 — self-improvement read surface** (5 routes: status /
metrics / report / experiences / enqueue) pairing with the ADR-134 hindsight read-side. The
donor (`tektos-ultima/src/tektos/agents/self_improvement/` + `main.py`) provides that surface
on top of three layers: a **learning substrate** (experience ledger + meta-learning metrics),
a **background driver** (env-gated periodic cycle queue), and a **Hegelian loop**
(thesis→antithesis→synthesis: plan a self-improvement spec, execute it, reflect, synthesize,
store the experience). None of it had a Kosmos referent.

## Decision

Split at the substrate/policy boundary (same pattern as ADR-142 self-repair):

| Piece | Nature | Home |
|---|---|---|
| `LearningEngine` (experience ledger JSONL + meta-learning metrics: total_tasks, total_improvements, learning_velocity, model_rankings, best_model_for_coding, success/failure streaks) | generic experience/learning substrate | `kernel/learning/engine.py` |
| `LearningDriver` (bounded queue + env-gated background cycle loop, `TEKTOS_SELF_IMPROVEMENT_ENABLED` default OFF, `INTERVAL` default 1800 s, `get_status()`/`enqueue()`/`run_now()`/`clear_queue()`) | generic scheduling machinery | `kernel/learning/driver.py` |
| `ExperienceRecord` (donor dataclass verbatim: session_id/task/model_used/success/created_at, `to_dict()` wire shape) | shared data model | `kernel/learning/models.py` |
| `SelfImprovementLoop` (Hegelian plan→execute→reflect→synthesize cycle over the 5 Tektos engines + substrate write-back) | Tektos coding-agent policy | `plugins/tektos/self_improve/loop.py` |
| hindsight `retain` (write leg, sync httpx, donor-faithful) | shared infra leg | `kernel/tektos_hindsight.py` |

### DI seam (ADR-007: kernel must not import plugins)

`LearningEngine.__init__` accepts `tick_emitter` (TickEmitter protocol) + `hindsight_retainer`
(HindsightRetainer protocol). The composition root (`kernel/app.py` boot block, after the
self-repair boot) imports both sides: the tick emitter wraps `event_bus.publish`, the retainer
wraps `tektos_hindsight.retain`, and the plugin `SelfImprovementLoop` (DI'd with the 5 Tektos
engines + the learning engine) is handed to a `LearningDriver`. Unwired → honest degraded
`wired:false` on every route, never a crash.

### Donor wire-shape fidelity (the T3 gate)

Five kernel routes replace the :8020 gateway proxy, byte-compatible with the donor
(`main.py`) and the UI selfimp tab:

| Route | Donor referent | Kernel referent |
|---|---|---|
| `GET /api/self_improvement/status` | L4555 | `driver.get_status()` (orchestrator_ready, pending, cycles_completed, last_cycle, enabled) |
| `GET /api/self_improvement/experiences` | L3144 | `engine.get_experience(top_k)` → `[record.to_dict()]` |
| `GET /api/self_improvement/metrics` | L3200 | `engine.get_learning_metrics()` (donor keys verbatim) |
| `GET /api/self_improvement/report` | L3220 | `engine.get_report()` (composite) |
| `POST /api/self_improvement/enqueue` | L4595 | `{prompt, run_now?}` → `driver.enqueue` / `driver.run_now` |

All return `wired:false` when `registry.tektos_self_improve`/`registry.tektos_learning` are
unwired (never 500). Shutdown stops the driver before the event bus closes (tick emitter
dependency).

## Execution

- **S2** — `LearningEngine` port (donor-faithful: `on_session_completed`/`on_session_failed`
  write API; `on_session_failed` does NOT write a benchmark file — donor semantics). 16 tests.
- **S3** — `LearningDriver` (queue + env-gated background cycle). 15 tests.
- **S4** (`ce6b60b`) — plugin `SelfImprovementLoop` (sync facade over `asyncio.run`;
  `_guidance` async to avoid nested loops; failed-substrate feed unconditional even when
  `spec is None`). 11 tests.
- **S5a** (`0d05a8e`) — boot block (substrate DI: tick emitter→event bus, hindsight retainer;
  loop→driver; `registry.tektos_learning` + `registry.tektos_self_improve`) + hindsight
  `retain` write leg.
- **S5b** — 5 kernel routes (donor wire shapes) + `wired:false` degrade.
- **S5c** — driver shutdown before event-bus close.
- **S5d** — 9 route tests (live TestClient, donor wire assertions) + full kernel suite green
  (518 passed).

Verified: ADR-143 suite 51/51 green; full `tests/kernel/` 518 passed, 0 failed.
