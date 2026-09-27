# ADR-146 — Tier-3 discharge: retire the 7 unmounted engine router factories

**Status:** ACCEPTED
**Date:** 2026-09-26
**Stage:** 14.12 (backend→frontend exposure audit remediation, Tier 3)
**Decider:** Charles (delegated split decision, per the governing layering rule)

## Context

The 2026-09-26 backend→frontend exposure audit
(`audit/audit-report-2026-09-26-backend-frontend-exposure.md`) classified all
201 live mounted routes. **Tier 3** covered routers that exist in code but are
never mounted: **8 `build_*_router` factories across 7 plugin packages
(`decomposer`, `executor` ×2, `experience`, `manager`, `planner`,
`reflection`, `synthesis`), 22 HTTP routes total**, each with only test call
sites (`plugins/tektos/tests/test_stage_8_3…8_6_engine_routers.py`).

The audit left the disposition open: *mount them* (reducing the exposure gap)
or *retire them* (per the ADR-141 discharge pattern). The governing constraint
("Kosmos-LMS Tektos must not lose any of the functionality of Tektos-Ultima")
makes the donor's own HTTP surface the deciding evidence.

## Evidence

1. **The donor never exposed these routes as HTTP.** Recovered
   `src/tektos/main.py` (6,025 lines, deleted at Stage 14.2 gate close,
   commit `43cb0ef`): it contains **zero `include_router` calls and zero
   references** to any of the 8 router factories. The donor's HTTP surface is
   154 flat `@app.*` routes — all 154 already adjudicated P in ADR-141
   (154 P / 0 D / 0 T, fully discharged). The 22 Tier-3 routes have no donor
   referent because they never existed as donor routes.
2. **All 8 underlying engines are live kernel/plugin functionality.** Each
   engine class is consumed outside its package and by the kernel:
   `ReflectionEngine` / `SynthesisEngine` / `ExperienceReplay` /
   `TektosManager` / `TektosSpecExecutor` (kernel/app.py, the self-improvement
   loop, the orchestrator's `coding=` injection per ADR-141 T1), `TaskDecomposer`,
   `TektosSpecPlanner` (planner pipeline — ADR-141 T4 ports its surface
   kernel-native at `/api/planner/plan|templates|language-games|status`),
   `TektosToolRouter` (executor engine). The engines keep their dedicated
   direct unit tests (`test_stage_8_3_*_engine.py`, `test_stage_8_4_*_engine.py`,
   `test_stage_8_5_*_engine.py`, `test_stage_8_6_manager_engine.py`, etc.) —
   only the HTTP-wrapper tests are retired.
3. **Mounting is a net negative.** The factories declare no `prefix=`, so
   7× `GET /recent`, plus `/plan`, `/execute`, `/route`, `/record`,
   `/reflect`, `/synthesize` would collide on mount — mounting would require
   redesigning every path, *inventing* a wire shape no consumer (donor or
   UI) ever had, then re-adding 22 routes to the exposure debt this audit is
   closing.

## Decision

**Retire.** Delete:

- `plugins/tektos/{decomposer,executor,experience,manager,planner,reflection,synthesis}/api.py`
  (8 factories, 22 routes)
- `plugins/tektos/tests/test_stage_8_3_engine_routers.py`
- `plugins/tektos/tests/test_stage_8_4_engine_routers.py`
- `plugins/tektos/tests/test_stage_8_5_engine_routers.py`
- `plugins/tektos/tests/test_stage_8_6_manager_router.py`

Kept: every engine package (`engine.py`/`models.py`/etc.), all direct engine
unit tests, and `plugins/tektos/orchestrator/api.py` (the one *mounted*
router — ADR-114 surface, consumed by the panels AgentsTab).

## Consequences

- No donor functionality lost (the donor had none of these routes).
- No UI gap created (the UI never called any of the 22 paths; verified in
  `ui_refs_final.json`).
- The kernel's live surfaces (`/api/planner/*`, `/api/skills/*`, orchestrator
  router, hindsight/dreamtime/self-improvement) are untouched — they ported
  the engine functionality kernel-native and do not depend on these wrappers.
- Tier 3 of the exposure audit is closed: 22 dead routes removed instead of
  22 newly mounted dead routes.

## Verification

- `grep` for all 8 factory names + `*.api import` paths: **zero dangling
  references** (package `__init__.py`s re-export engines only).
- Full pytest suite (Stage 14.12 batch, 2026-09-26): **1548 passed / 10
  skipped / 0 failed** (exit 0). The 4 retired router test files are the only
  test deletions; every engine unit test still runs green. See the BUILD_LOG
  Stage 14.12 entry for the live :8000 smoke and the full-batch verification.
