# ADR-106 — Tektos spec-planner + task-decomposer engines (Stage 8.4)

**Status:** Ratified v25
**Lock-in phase:** Stage 8.4
**Supersedes:** —

## Context

Stage 8.4 lands the next two Tektos-donor absorption slices per Plan v2:

1. **Spec planner** — the 5-stage NL-→-spec pipeline (language-game → disambiguator → translator → template-selector → spec-generator) from donor `tektos-ultima/src/tektos/agents/planner/`. The Stage 4.7 `TektosTurnPlanner` seed (ADR-093 §3) is a scripted 3-node plan graph; it does not translate NL prompts into structured `BuildSpec` objects. The `PORTING_LEDGER.md` PLANNED row "Tektos planner (full donor absorption)" (Stage 4.7+1) is the mandate this ADR satisfies.
2. **Task decomposer** — the heuristic sub-task breakdown from donor `tektos-ultima/src/tektos/runtime/task_decomposer.py`. Breaks a natural-language task into numbered, sequential `SubTask` entries with expected-output verification and recommended-tool hints. High-ROI for Terminal-Bench-style multi-step tasks per the donor's own docstring.

ADR-105 D9 recorded a forward-looking mention that "PlannerPort → Stage 8.4". This ADR revisits that mention and rejects it: no new formal port is required at 8.4 (see D11 below).

### Donor state (verified 2026-09-10)

- `src/tektos/agents/planner/language_game.py` (216 lines) — pure-function `classify_language_game(text) -> LanguageGame` over three domain keyword signatures (SOFTWARE_ENGINEERING, SYSTEMS_ARCHITECTURE, BUDDHIST_PHILOSOPHY) with GENERAL fallback. Zero LLM calls, zero external I/O. Directly portable.
- `src/tektos/agents/planner/disambiguator.py` (254 lines) — pure-function `find_ambiguities(text, language_game) -> list[Ambiguity]`, `find_vague_terms(text) -> list[Ambiguity]`, `resolve_ambiguities(ambiguities, user_input) -> (list[Ambiguity], list[AmbiguityResolution])`, `generate_clarifying_questions(...)`. Rule-based over a static domain-ambiguity dictionary. Zero LLM calls.
- `src/tektos/agents/planner/translator.py` (234 lines) — pure-function `translate_to_technical_english(text) -> str` + `add_spec_context(text, context) -> str`. Static filler/vague-term dictionaries with regex substitution. Zero LLM calls.
- `src/tektos/agents/planner/template_selector.py` (180 lines) — pure-function `choose_best_template(requirements, user_preference) -> ArchitectureChoice`. Four hardcoded `ArchitectureTemplate` entries (`vertical_slice`, `horizontal_layered`, `kernel_extensions`, `microservices`) with a keyword-match scorer.
- `src/tektos/agents/planner/spec_generator.py` (264 lines) — pure-function `generate_spec(...) -> BuildSpec`. Composes upstream outputs into a structured spec with default 3-phase decomposition (MVP → improvements → polish).
- `src/tektos/agents/planner/orchestrator.py` (152 lines) — `Planner` class stitching the five stages together. Depends only on the sibling pure-function modules.
- `src/tektos/agents/planner/models.py` (232 lines) — pydantic `BaseModel` schema (`LanguageGame`, `Ambiguity`, `ClarifyingQuestion`, `ArchitectureTemplate`, `ArchitectureChoice`, `SpecPhase`, `W5H1M`, `BuildSpec`, `PlannerOutput`).
- `src/tektos/agents/planner/repo_map.py` (489 lines) — repo-map generator; **out of scope** at 8.4 per §5 below.
- `src/tektos/runtime/task_decomposer.py` (326 lines) — `TaskDecomposer.decompose(task, task_id) -> DecompositionPlan` with 5 rule-branch decompositions (build/code-generation/regex/download-build/generic). Zero LLM calls.
- `src/tektos/runtime/planner_orchestrator.py` (100 lines) — thin `PlannerOrchestrator` that stores `Plan` objects; superseded by the donor `agents/planner/orchestrator.py`. **Rejected** — no unique behaviour worth preserving.

### Prior Kosmos state

- `plugins/tektos/planner/` already exists (Stage 4.7 seed) — contains `TektosTurnPlanner` scripted 3-node plan generator + `Plan`, `PlanNode`, `PlanNodeKind` frozen slotted dataclasses. **Not deleted or renamed** — this ADR extends the package, not replaces it. Field name conflict resolved by naming the new class `TektosSpecPlanner` and the plugin dataclass field `spec_planner`.
- `plugins/tektos/experience/models.py` — `ExperienceRecord.context` accepts an arbitrary `dict[str, Any]`; ADR-105 D9 mentioned but did not enforce a `LanguageGame` enum. This ADR introduces the enum and permits (but does not require) `ExperienceRecord.context["language_game"]` to carry the enum value.
- `LLMPort` (`ports/llm.py`) — surface accepts `model: str | None` per-call; no formal role-routing port. Role-routing at the port level (ADR-087 Hermes topology) is not landed. **Not required at 8.4** — donor pipeline is 100% rule-based.
- `RelationalMemoryPort` (ADR-102, Stage 8.0) — the persistence sink for every plan + decomposition record, consistent with the ADR-105 pattern.
- `EventBusPort` (ADR-086, envelope-first per ADR-023) — the fan-out substrate.
- `TektosPlugin` dataclass — already carries `turn_loop`, `reflection`, `synthesis`, `experience` optional `object | None` fields; adding `spec_planner` and `decomposer` follows the same shape.

## Decision

### D1 — Scope: two new sibling engine surfaces, no repo_map, no orchestrator port

Two Kosmos-native engine slices at 8.4:

1. **`plugins/tektos/planner/spec_planner.py`** (extends the existing package) — `TektosSpecPlanner` class composing five rewritten pure-function modules that live alongside as `plugins/tektos/planner/{language_game.py, disambiguator.py, translator.py, template_selector.py, spec_generator.py, spec_models.py}`. `TektosSpecPlanner.generate_spec(*, prompt, context=None, user_preference=None, confidence=None) -> (PlannerOutput, str | None)` returns a `PlannerOutput` + optional `narrative_id`.
2. **`plugins/tektos/decomposer/`** (new package) — `TaskDecomposer` engine that decomposes a natural-language task into `DecompositionPlan` with numbered `SubTask` entries. `TaskDecomposer.decompose(*, session_id, task, task_id=None, confidence=None) -> (DecompositionPlan, str | None)`.

**Rejected D1 alternatives:**
- Fold decomposer into the planner package — the two have different call sites (planner produces `BuildSpec` from prompts; decomposer produces `DecompositionPlan` from arbitrary task strings). Different envelope types, different plugin-dataclass fields, different router prefixes. Kept separate for the same reason ADR-105 kept reflection/synthesis/experience separate.
- Vendor the donor `repo_map.py` at 8.4 — 489-line file that reads real filesystem state; requires a new `RepoMapPort` and an sandbox-adapter integration. Deferred to Stage 8.5 (executor helpers).
- Land the donor `agents/planner/repo_map.py` unmodified as an internal helper — violates ADR-007 (no cross-plugin imports; the module would be plugin-internal but reading arbitrary filesystem state without a port is out-of-scope for a plugin at 8.4).
- Absorb `runtime/planner_orchestrator.py` (100 lines) — donor's own comment says its `Plan`/`PlanStep` shape is superseded by `agents/planner/`; no unique behaviour. Rejected wholesale.

### D2 — Fidelity vs rewrite: rewrite (same pattern as ADR-105 D2)

Runtime tier rewritten from pydantic + in-memory `_plans: dict` to:
- Frozen slotted dataclasses (`LanguageGame` stays as `str, Enum`; every other model rewritten as `@dataclass(frozen=True, slots=True)`).
- `RelationalMemoryPort.write_narrative` (ADR-102) as the persistence sink (donor uses in-memory dict).
- In-memory `deque(maxlen=100)` ring buffer as fallback (same pattern as ADR-104/105).

Donor's rule-based analytic core preserved **verbatim in logic**:
- `_DOMAIN_SIGNATURES` keyword dictionaries (all four language games).
- `_AMBIGUITY_DICTIONARY` (nine ambiguous terms × four domain mappings + criticality heuristics).
- `_FILLERS` + `_VAGUE_TO_PRECISE` translator maps.
- Four `ArchitectureTemplate` entries (`vertical_slice`, `horizontal_layered`, `kernel_extensions`, `microservices`) with donor's keyword-match scorer.
- Five decomposer branches (build / code-generation / regex / download-build / generic) with donor's sub-task lists verbatim.

**Rejected D2 alternatives:**
- Vendor donor `models.py` unmodified as `plugins/tektos/planner/vendor/planner_models.py` — pulls pydantic into the Tektos plugin surface (no other engine on the plugin uses pydantic; frozen slotted dataclasses are the established shape per ADR-105 D2).
- Fidelity port with pydantic behind a thin dataclass wrapper — costs both the pydantic dependency footprint and a translation layer for zero benefit at the callsites (Kosmos code never round-trips these models through the wire; they land on `RelationalMemoryPort.write_narrative` as JSON strings).

### D3 — Write sink: `RelationalMemoryPort.write_narrative` for both engines

Every spec + decomposition persists via `RelationalMemoryPort.write_narrative(...)`:
- `title` prefixed with the engine's ADR-106 predicate.
- `tags` always include the engine's provenance + domain context (`session_id`, `spec_id` or `plan_id`, `language_game`).
- `body` is JSON-serialised dataclass (via `dataclasses.asdict` + `json.dumps`).
- `provenance` + `confidence` locked to the engine's D4 constants.
- Every call wrapped in `try/except Exception` with `log.exception(...)` per D9.

### D4 — Locked constants (6 total, all `∈ (0, 1]` per ADR-008)

**Spec planner (3 constants):**
```python
TEKTOS_SPEC_PLANNER_PROVENANCE = "tektos.planner"
TEKTOS_SPEC_PLANNER_PREDICATE = "tektos.planner.spec_generated"
TEKTOS_SPEC_PLANNER_DEFAULT_CONFIDENCE = 0.75
```

**Decomposer (3 constants):**
```python
TEKTOS_DECOMPOSER_PROVENANCE = "tektos.decomposer"
TEKTOS_DECOMPOSER_PREDICATE = "tektos.decomposer.plan_generated"
TEKTOS_DECOMPOSER_DEFAULT_CONFIDENCE = 0.75
```

`0.75` pre-Reflexion default per ADR-036 — mirrors ADR-105 D4 across all three engines.

### D5 — `TektosPlugin` dataclass grows two optional fields

Two new fields added to `plugins/tektos/plugin.py` after the ADR-105 D5 block:

```python
# Stage 8.4 (ADR-106 D5): optional handles to the kernel-wired
# spec-planner + task-decomposer engines. Populated at kernel-boot
# time by ``kernel/app.py::_boot_tektos_{spec_planner,decomposer}``
# when the corresponding
# ``KOSMOS_TEKTOS_{SPEC_PLANNER,DECOMPOSER}=on`` env-gate is set
# and ``registry.relational_memory`` is bound. Each stays ``None``
# when the engine is off, unwired, or degrade-suppressed. Typed as
# ``object | None`` for the same ADR-007 reason as ``turn_loop``.
spec_planner: object | None = field(default=None)
decomposer: object | None = field(default=None)
```

**Naming rationale for `spec_planner` (not `planner`):** the existing `plugins/tektos/planner/` package already exports `TektosTurnPlanner` (Stage 4.7 ADR-093 seed) used elsewhere. Adding a `planner` field on the plugin dataclass would shadow both the package and the seed, breaking `plugins/tektos/plugin.py` type-checker introspection. `spec_planner` names the NL-→-spec generator distinctly from the plan-graph turn-planner.

### D6 — Kernel wiring + env-gates

Two new `_BootRegistry` slots after the ADR-105 D6 block:

```python
self.tektos_spec_planner: Any = None
self.tektos_decomposer: Any = None
```

Two `@_try(...)` boot functions using the ADR-105 `_boot_stage_8_3_engine` shared helper (renamed at 8.4 to `_boot_stage_8_x_engine` — same signature, no behavioural change; a rename this small does not warrant its own ADR):

- `_boot_tektos_spec_planner` — env-gate `KOSMOS_TEKTOS_SPEC_PLANNER={off,on}` (default `off` silent); unknown → `RuntimeError` captured in `registry.errors`; `on` requires `registry.relational_memory` non-None (ADR-101 degrade to `None` with WARN log); plugin field `spec_planner`.
- `_boot_tektos_decomposer` — env-gate `KOSMOS_TEKTOS_DECOMPOSER={off,on}`; identical shape; plugin field `decomposer`.

Boot slots inserted between `registry.tektos_experience = _boot_tektos_experience` (Stage 8.3 last slot) and the Gnosis seeder.

### D7 — EventBusPort surface

Two new event types, envelope-first per ADR-023:
- `tektos.planner.spec_generated` — payload: `session_id`, `spec_id`, `language_game` (str), `architecture` (str), `phase_count` (int), `narrative_id | None`.
- `tektos.decomposer.plan_generated` — payload: `session_id`, `plan_id`, `task` (str, truncated to 500 chars), `subtask_count` (int), `phase` (str), `narrative_id | None`.

Every publish call wrapped in `try/except` with `log.exception(...)` per D9.

### D8 — FastAPI router surface

Two router factories per `plugins/tektos/{spec_planner,decomposer}/api.py`:
- `build_spec_planner_router(engine)` — `POST /tektos/api/spec-planner/plan` + `GET /tektos/api/spec-planner/recent`.
- `build_decomposer_router(engine)` — `POST /tektos/api/decomposer/decompose` + `GET /tektos/api/decomposer/recent`.

Missing engine → `503 {"detail": "ADR-106 degrade: <engine> not wired", "adr": "ADR-106"}` via a `_guard()` closure inside each factory (same shape as ADR-105 D8).

Note: the spec-planner router lives under `plugins/tektos/planner/api.py` since the package already exists. The URL prefix `/tektos/api/spec-planner/` distinguishes it from any future `/tektos/api/planner/` router that might expose `TektosTurnPlanner` (Stage 4.7 seed).

### D9 — Fail-open pattern + `LanguageGame` enum introduction

Every `write_narrative` and `event_bus.publish` wrapped in `try/except Exception` with `log.exception(...)` — mirror of ADR-105 D9. Engine functionality never blocked by port failures; in-memory ring buffer (`maxlen=100`) always populated as fallback.

**`LanguageGame` enum lands at 8.4** (per ADR-105 D9 forward-looking deferral "LanguageGame enum on ExperienceRecord.context → Stage 8.4 planner"). Defined in `plugins/tektos/planner/spec_models.py` as `class LanguageGame(str, Enum)` with four values: `SOFTWARE_ENGINEERING`, `SYSTEMS_ARCHITECTURE`, `BUDDHIST_PHILOSOPHY`, `GENERAL`.

`plugins/tektos/experience/models.py::ExperienceRecord.context` remains typed as `dict[str, Any] | None` — no schema change. The convention (documented in the engine's docstring) is that `context["language_game"]` MAY carry the enum's `.value` string when set by the spec-planner integration. No experience-engine code change required at 8.4.

**Explicit deferrals (D9):**
- Full LLM-driven translator/disambiguator/spec_generator (donor's pipeline is 100% rule-based; LLM-side prompt synthesis remains a Stage 8.4+ item pending ADR-087 role-routing on the critical path).
- Repo-map port (`RepoMapPort`) — Stage 8.5 executor helpers.
- Filesystem-reading tools (`file_read`, `file_write`, path-traversal detector) — Stage 8.5.
- Reflexion actor-evaluator confidence per ADR-039 — Stage 5.X (donor `PlannerOutput.synthesis_guidance` field accepts a string but 8.4 doesn't wire the actor-evaluator scoring loop).
- Interactive user-question loop for `ClarifyingQuestion` presentation — Stage 8.5+ frontend integration.
- Real `BuildSpec` execution against `TektosTurnLoop` — Stage 8.5 executor helpers.
- MCP-based tool discovery in decomposer's `tools_needed` output — Stage 8.5 wires MCP.

### D10 — Rejected: making the engines required

The engines stay optional (`object | None = None` fields). Reasons:
- Breaks Stage 3.7 + 3.13 + 4.7 test surface — several tests currently pass without any 8.4 engine wired.
- Kernel boot must degrade cleanly when `KOSMOS_TEKTOS_SPEC_PLANNER=off` — mandatory wiring precludes the `off` default.
- Consistent with ADR-104 D11 + ADR-105 D5 pattern.

### D11 — Rejected: introducing a `PlannerPort` at 8.4

ADR-105 D9 mentioned "PlannerPort → Stage 8.4" as forward-looking scope. This ADR rejects that scope for four reasons:

1. **No cross-plugin consumer exists at 8.4.** Only Tektos calls the planner. A formal port is a coupling surface for OTHER plugins/adapters — Praxis, Phrouros, Zetesis do not consume the planner. Introducing a port with a single implementer is premature abstraction.
2. **The `TektosPlugin.spec_planner: object | None` field IS the coupling surface.** ADR-104 (turn_loop) and ADR-105 (reflection/synthesis/experience) both used this pattern instead of introducing new formal ports.
3. **Port surface would be near-empty.** `PlannerPort.generate_spec(prompt, context, user_preference) -> BuildSpec` — one method, wraps a plugin-internal class. Formal ports carry cross-adapter contract weight (`SessionPort`, `MemoryPort`, `LLMPort` all have multiple implementers).
4. **PORTING_LEDGER PLANNED row does not require it.** ADR-093's ledger entry names `LLMPort` + `EventBusPort` + `RepoMapPort` — no PlannerPort. This ADR closes the PLANNED row by delivering the donor absorption; the port list stays as declared.

If a future plugin (e.g. Zetesis at Stage 6.3+) needs to invoke the spec-planner, that consumption pattern will surface a real port requirement and warrant its own ADR.

### D12 — Rejected: requiring `LLMPort` at 8.4

Donor pipeline is 100% rule-based (verified above — every donor pure-function module has zero LLM calls). Consuming `LLMPort` at 8.4 would:
- Force `LLMPort` role-routing (ADR-087) onto the Stage 8.4 critical path, which ADR-093 explicitly rejected for Stage 4.7 with identical reasoning.
- Add a fake LLM dependency to a pipeline that doesn't need one.
- Break the Stage 8.4 DoD if LLM adapters are unhealthy.

The donor's `spec_generator._extract_requirements` heuristic + `_default_phases` rule-based decomposition is DoD-sufficient. LLM-side synthesis (which would materially improve translator + disambiguator quality) stays a Stage 8.4+1 item.

## Rationale

- **Extend the existing `plugins/tektos/planner/` package rather than replace it.** The Stage 4.7 `TektosTurnPlanner` seed (ADR-093 §3) is still wired at ADR-093's DoD anchor. Deleting it would break Stage 4.7 tests without adding capability. Adding `TektosSpecPlanner` alongside is a strictly additive change.
- **Rewrite over fidelity port** — same reasoning as ADR-105 D2. Donor's pydantic runtime tier doesn't mirror to a `RelationalMemoryPort` sink without adapter rewrite; the rule-based analytic core is what carries the value and is preserved verbatim.
- **`spec_planner` name** — necessary to avoid colliding with the existing `planner` package export. Mirrors the naming discipline established at ADR-092 (Stage 3.13 `TektosTurnLoop` vs older loop wrappers).
- **No PlannerPort at 8.4** — port surfaces are cross-adapter contracts; a single-implementer port is speculation, not a decision.
- **`LanguageGame` enum landing at 8.4** — the enum was deferred from ADR-105 D9 to "the Stage 8.4 planner"; this is that stage. The enum is genuinely needed on the spec-planner surface and OPTIONAL on the experience surface (backward-compatible convention).
- **Consistent kernel-wiring pattern with ADR-105** — reusing the same `_boot_stage_8_x_engine` shared helper (renamed one letter — same signature, same behaviour) is a rename-only fanout, not a re-authored function.
- **Fail-open pattern** — mirrors ADR-104 D2 SessionPort + ADR-105 D9. Engine functionality must never be blocked by port failures.

### Alternatives considered and rejected

- **Introduce `PlannerPort` at 8.4** — see D11.
- **Absorb `runtime/planner_orchestrator.py`** — donor's own comment marks it as superseded; no unique behaviour.
- **Vendor donor `models.py` unmodified with pydantic** — see D2.
- **Fold decomposer into planner** — see D1.
- **Introduce `LanguageGame` enum on `ExperienceRecord.context` as a required field** — breaking change to Stage 8.3 test surface; convention-only is sufficient.
- **Wire `LLMPort` at 8.4** — see D12.
- **Land `RepoMapPort` at 8.4** — donor's `repo_map.py` is 489 lines and requires filesystem access via a formal port; premature at 8.4, warrants its own ADR when it lands at Stage 8.5.
- **Require the engines on kernel boot** — see D10.

## Consequences

**Files created (this ADR):**
- `docs/adrs/ADR-106-tektos-spec-planner-and-task-decomposer-engines.md`

**Files planned (Stage 8.4 implementation):**
- `plugins/tektos/planner/spec_models.py` (frozen slotted dataclasses + `LanguageGame` enum)
- `plugins/tektos/planner/language_game.py` (rewritten from donor)
- `plugins/tektos/planner/disambiguator.py` (rewritten from donor)
- `plugins/tektos/planner/translator.py` (rewritten from donor)
- `plugins/tektos/planner/template_selector.py` (rewritten from donor)
- `plugins/tektos/planner/spec_generator.py` (rewritten from donor)
- `plugins/tektos/planner/spec_planner.py` (`TektosSpecPlanner` engine composing the above)
- `plugins/tektos/planner/api.py` (`build_spec_planner_router`)
- `plugins/tektos/decomposer/{__init__.py, models.py, engine.py, api.py}` (new package)
- `plugins/tektos/tests/test_stage_8_4_spec_planner_engine.py`
- `plugins/tektos/tests/test_stage_8_4_decomposer_engine.py`
- `plugins/tektos/tests/test_stage_8_4_engine_routers.py`
- `tests/kernel/test_stage_8_4_engine_wiring.py`

**Files amended (Stage 8.4 implementation):**
- `plugins/tektos/planner/__init__.py` (re-exports `TektosSpecPlanner`, `LanguageGame`, `BuildSpec`, `PlannerOutput`, etc. alongside the existing `TektosTurnPlanner` seed exports)
- `plugins/tektos/plugin.py` (two new `object | None` fields per D5)
- `kernel/app.py` (two new `_BootRegistry` slots + two `@_try` boot functions per D6)
- `docs/adrs/README.md` (ADR-106 row inserted)
- `docs/Kosmos-Build-Spec-v26.md` §17 (ADR-106 row inserted above ADR-105)
- `docs/Kosmos-Build-Sequence-v26.md` (Stage 8.4 stanza appended after Stage 8.3)
- `PORTING_LEDGER.md` (Tektos planner full donor absorption row moves from PLANNED to VENDORED; task-decomposer VENDORED row added)
- `BUILD_LOG.md` (Stage 8.4 completion entry appended)
- `SESSION_HANDOFF.md` (overwrite)

**No new formal port added.** No `PORTING_LEDGER.md` port-list change (LLMPort, EventBusPort, RepoMapPort mentions in the existing PLANNED row are updated to reflect what actually landed: RelationalMemoryPort + EventBusPort; LLMPort + RepoMapPort deferred to Stage 8.4+1 / 8.5).

**Preserved invariants:**
- **ADR-007** — every new module imports only from `ports.*` and its own subpackage (`plugins.tektos.planner.*` for planner-internal modules; `plugins.tektos.decomposer.*` for decomposer-internal modules). AST-scan test enforces this at test time.
- **ADR-008** — every `write_narrative` supplies locked `provenance` + `confidence ∈ (0, 1]`.
- **ADR-023** — envelope-first `EventBusPort.publish` upheld; never positional args.
- **ADR-036** — 0.75 pre-Reflexion confidence default preserved for both engines.
- **ADR-086** — new event types use the `tektos.{engine}.{action}` shape.
- **ADR-092** — Stage 3.13 event-shape backward compatibility preserved; no existing event types renamed.
- **ADR-093** — Stage 4.7 `TektosTurnPlanner` unchanged; the ADR-093 PORTING_LEDGER PLANNED row closes.
- **ADR-101** — degrade pattern for optional kernel-boot collaborators + request-time degrade in FastAPI routers.
- **ADR-102** — `RelationalMemoryPort` is the persistence substrate for both engines.
- **ADR-103** — `SessionPort` transitions consumed elsewhere; engines carry `session_id` in every narrative + event.
- **ADR-104** — turn loop stays Kosmos-owned; spec-planner does NOT invoke the turn loop.
- **ADR-105** — three reflection/synthesis/experience engines unchanged; convention that `ExperienceRecord.context["language_game"]` MAY carry the enum's `.value` is documented in the experience engine's docstring at 8.4.

## Lock-in phase

Locked at Stage 8.4.

## References

- ADR-036 (0.75 pre-Reflexion confidence default)
- ADR-086 (EventBusPort envelope taxonomy — `tektos.*` namespace)
- ADR-087 (Hermes LLM topology — role-routing, deferred at 8.4 per D12)
- ADR-092 (Stage 3.13 absorption scope — vendor+adapter pattern lineage)
- ADR-093 (Stage 4.7 sandbox + planner seed + tools — closes the "Tektos planner full donor absorption" PLANNED row)
- ADR-101 (degrade pattern for optional kernel-boot collaborators)
- ADR-102 (RelationalMemoryPort — Stage 8.0 persistence substrate)
- ADR-103 (SessionPort — Stage 8.1)
- ADR-104 (Tektos turn loop grows with SessionPort/LLMPort/SandboxPort/ResourcePort — Stage 8.2)
- ADR-105 (Tektos reflection + synthesis + experience-replay engines — Stage 8.3; establishes the pattern this ADR extends)
- `PORTING_LEDGER.md` (Tektos planner PLANNED row updated to VENDORED at 8.4 landing; task-decomposer VENDORED row added)
- `plugins/tektos/planner/turn_planner.py` (Stage 4.7 seed, unchanged)
