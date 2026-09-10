# ADR-105 — Tektos Reflection + Synthesis + Experience-Replay Engines

**Status:** Ratified v25
**Lock-in phase:** Stage 8.3
**Supersedes:** —

## Context

Plan v2 Stage 8.3 ("Reflection + synthesis + experience-replay engines", ~2 sessions) lands three new plugin subpackages under `plugins/tektos/` that persist post-turn insights into Kosmos's 5th memory layer (`RelationalMemoryPort`, ADR-102). The Stage 8.2 `TektosTurnLoop` (ADR-104) now emits `TurnOutcome` records rich enough (session_id + llm_response + tool outcomes + stop_reason + resource_exhausted + error) to be the primary input to reflection, and the SessionPort (ADR-103) provides completed-session transitions as a second input.

The donor repo carries **two parallel implementations** of every 8.3 subsystem:

- `tektos-ultima/src/tektos/runtime/{reflection,synthesis,experience_replay}_engine.py` — 313 lines total, in-memory, zero external consumers (orphan code from an earlier stub).
- `tektos-ultima/src/tektos/memory/{reflection,synthesis,experience_replay}_engine.py` — 1133 lines, coupled to `MemorySystem` (993-line 4-tier hemispheric-brain model with `DreamtimeEngine` + `Hindsight` + `LanguageGame`), live path (`main.py:1206/1216`).

Fidelity-porting the memory tier drags in ~2500 lines of unrelated donor infrastructure that Plan v2 explicitly assigns to Stage 13. The runtime tier's simplicity loses the rich semantics (`is_direct_experience`, `trust_score`, `bias_detected`, `insight_type`, `what_happened`, `guidance`, `cycle_id`, `priority`) that make the memory tier interesting.

Kosmos already has `RelationalMemoryPort.write_narrative(session_id, agent_id, title, body, tags, embedding, confidence, provenance)` (ADR-102 §D3) — the exact substrate needed for episodic-narrative persistence with hybrid tsvector + pgvector search. The Stage 8.3 engines sit above this port, they do not replace it.

Full donor audit + kill-switch review: `docs/stage-8-3-donor-audit.md` (this session).

## Decision

Stage 8.3 lands three new plugin subpackages — `plugins/tektos/reflection/`, `plugins/tektos/synthesis/`, `plugins/tektos/experience/` — as **rewrites against `RelationalMemoryPort`** that preserve the donor's memory-tier semantics without dragging in `MemorySystem`, `DreamtimeEngine`, `Hindsight`, or `LanguageGame`. Runtime-tier orphan code is rejected wholesale. Nine explicit decisions (D1–D9) below.

### D1 — Scope (three plugin subpackages)

- `plugins/tektos/reflection/{__init__.py, models.py, engine.py, api.py, test_reflection.py}`
- `plugins/tektos/synthesis/{__init__.py, models.py, engine.py, api.py, test_synthesis.py}`
- `plugins/tektos/experience/{__init__.py, models.py, replay.py, api.py, test_experience.py}`

All three engines are constructor-injected with `relational_memory: RelationalMemoryPort | None = None` (**optional**). When `None`, engines run in memory-only mode with a fixed-size ring buffer (`max_records=100`) and log INFO on every would-write. When bound, persistence goes through `write_narrative`; recall goes through `search_narratives`.

### D2 — Donor-tier selection

- **Reject** `runtime/reflection_engine.py`, `runtime/synthesis_engine.py`, `runtime/experience_replay.py` — orphan code (zero external consumers). No PORTING_LEDGER entry; nothing vendored.
- **Rewrite** the semantics of `memory/reflection_engine.py`, `memory/synthesis_engine.py`, `memory/experience_replay.py` as Kosmos-owned Python — port the dataclass shapes (`ReflectionInsight`, `ReflectionState`, `SynthesisResult`, `ExperienceRecord`), the rule-based analytic logic (`_generate_insight`, `_extract_lessons`, `_generate_recommendations`), and the domain-language docstrings verbatim as module preambles. Drop everything else (constructors that demand `MemorySystem`, `Hemisphere` field on the models, `DreamtimeEngine` cross-references, pydantic `BaseModel` base class).
- **Defer to Stage 13** — `memory/memory_system.py`, `memory/hindsight_client.py`, and `Dreamtime` background scheduler.
- **Defer to Stage 8.4** — `agents/planner/models.LanguageGame` enum (at 8.3 `context` is `str`).
- **Defer to Stage 8.7** — `agents/self_improvement/loop_orchestrator.py`.

### D3 — Persistence sink is `RelationalMemoryPort.write_narrative`

No new port. No vendor entry in PORTING_LEDGER (this stage ports semantics, not code). Every persisted record from any of the three engines flows through `write_narrative` with:

- `session_id`: the session that produced the reflected-on turn (required by port).
- `agent_id`: `"tektos.reflection"` / `"tektos.synthesis"` / `"tektos.experience"` — engine identity.
- `title`: `f"{predicate}:{stable_slug}"` — e.g. `"tektos.reflection.completed:turn-abc123"`.
- `body`: JSON-serialised full record (all model fields), so nothing is lost on write.
- `tags`: `(<engine_name>, <insight_type_or_category>, <session_id>)` — enables per-session recall, per-category filtering.
- `embedding`: `None` at 8.3 (embedding-generation is a Stage 8.4+ enrichment).
- `confidence`: caller-supplied, must be in `(0, 1]` (zero-trust guard per ADR-008; the port itself validates).
- `provenance`: one of the D4 locked constants.

Experience recall uses `search_narratives(query=context, tags=("tektos.experience",), limit=N)` — the ledger is the source of truth; there is no separate in-memory `_records` list at persistence tier (the D1 memory-only fallback ring buffer is only for the `relational_memory=None` degrade mode).

### D4 — Locked write predicates (nine constants)

Mirrors the ADR-036 (Tektos MemoryPort) and ADR-052 (Zetesis MemoryPort) pattern:

- `TEKTOS_REFLECTION_PROVENANCE = "tektos.reflection"`
- `TEKTOS_REFLECTION_PREDICATE = "tektos.reflection.completed"`
- `TEKTOS_REFLECTION_DEFAULT_CONFIDENCE = 0.75`
- `TEKTOS_SYNTHESIS_PROVENANCE = "tektos.synthesis"`
- `TEKTOS_SYNTHESIS_PREDICATE = "tektos.synthesis.completed"`
- `TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE = 0.75`
- `TEKTOS_EXPERIENCE_PROVENANCE = "tektos.experience"`
- `TEKTOS_EXPERIENCE_PREDICATE = "tektos.experience.recorded"`
- `TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE = 0.75`

Each engine module `__init__.py` exports its three constants. Test surface asserts exact values (locked-constants tier — one test per constant).

`0.75` matches the ADR-036 Tektos pre-Reflexion default and the ADR-052 Zetesis default; Reflexion (ADR-039, deferred to Stage 5.X) replaces this with an actor-evaluator-reflector-derived confidence when it lands. Callers may override per-write but must stay in `(0, 1]` per ADR-008.

### D5 — `TektosPlugin` dataclass amendment (three optional fields)

Mirrors the ADR-104 D11 `turn_loop` pattern:

```python
@dataclass
class TektosPlugin:
    ...  # existing fields
    turn_loop: object | None = field(default=None)     # ADR-104 D11
    reflection: object | None = field(default=None)    # ADR-105 D5
    synthesis: object | None = field(default=None)     # ADR-105 D5
    experience: object | None = field(default=None)    # ADR-105 D5
```

Kernel reflects each engine onto the plugin via best-effort `setattr` when both boot slots are on (same mechanism as ADR-104 for `turn_loop`).

### D6 — Kernel wiring (three env-gates, ADR-101 degrade)

Three new `_BootRegistry` slots and three new boot functions in `kernel/app.py`:

- `_boot_tektos_reflection()` — env-gate `KOSMOS_TEKTOS_REFLECTION={off,on}` (default `off` silent). `on` requires `registry.relational_memory` to be non-None; missing degrades to `registry.tektos_reflection = None` with WARN log citing ADR-105.
- `_boot_tektos_synthesis()` — env-gate `KOSMOS_TEKTOS_SYNTHESIS={off,on}` (default `off` silent). Same degrade pattern.
- `_boot_tektos_experience()` — env-gate `KOSMOS_TEKTOS_EXPERIENCE={off,on}` (default `off` silent). Same degrade pattern.

Unknown env value on any of the three: `RuntimeError` captured in `registry.errors[<slot_name>]` enumerating the allowed set (same shape as ADR-103 `KOSMOS_SESSION` and ADR-104 `KOSMOS_TEKTOS_TURN_LOOP`).

Boot order: `_boot_relational_memory` → `_boot_session` → `_boot_tektos_turn_loop` → **`_boot_tektos_reflection` → `_boot_tektos_synthesis` → `_boot_tektos_experience`** → `_boot_gnosis_seeder`. Reflection/synthesis/experience come **after** turn-loop so they can consume the turn-loop's event fan-out if wiring code chooses; they come **before** the Gnosis seeder so nothing downstream depends on the seeder's completion.

After each engine boots successfully, if `registry.tektos` (the plugin) exists, the kernel does best-effort `setattr(registry.tektos, "<field>", engine)` — three new best-effort setattrs mirroring the ADR-104 D11 `turn_loop` reflection.

### D7 — Three new event types on the EventBus

Every successful persistence publishes an envelope-first event per ADR-023:

- `tektos.reflection.completed` — payload: `{"session_id": str, "insight_type": str, "confidence": float, "narrative_id": str | None}`. `narrative_id` is `None` when the engine ran in memory-only mode (relational_memory unbound); the event still fires so consumers see the reflection completed.
- `tektos.synthesis.completed` — payload: `{"session_id": str, "spec_id": str, "confidence": float, "narrative_id": str | None}`.
- `tektos.experience.recorded` — payload: `{"session_id": str, "cycle_id": str, "context": str, "narrative_id": str | None}`.

Publisher plugin field on the `EventEnvelope`: `"tektos.reflection"` / `"tektos.synthesis"` / `"tektos.experience"` respectively (matches the `provenance` locked in D4 and the `agent_id` written in D3).

Event-bus wiring is via constructor-injected `event_bus: EventBusPort | None = None`. When `None`, events do not fire but the engine still returns its result; when `event_bus.publish` raises, the exception is caught and logged but never re-raised (fail-open — mirrors ADR-104 D2 SessionPort try/except pattern).

### D8 — FastAPI routers mount under `/tektos/api/{reflection,synthesis,experience}/*`

Per ADR-045 UI-parity discipline, three routers land at `plugins/tektos/{reflection,synthesis,experience}/api.py`, each a `fastapi.APIRouter` factory `build_<engine>_router(engine)`. Routes locked at Stage 8.3:

- **Reflection:** `POST /tektos/api/reflection/reflect` (body: `{"session_id": str, "turn_outcome": dict, "focus": str | None}` → returns `ReflectionInsight` as dict + `narrative_id`); `GET /tektos/api/reflection/recent?limit=10` (returns list of recent insights).
- **Synthesis:** `POST /tektos/api/synthesis/synthesize` (body: `{"session_id": str, "spec": dict, "execution_feedback": dict}` → returns `SynthesisResult` as dict + `narrative_id`); `GET /tektos/api/synthesis/recent?limit=10`.
- **Experience:** `GET /tektos/api/experience/recent?context=<str>&limit=10` (returns list of `ExperienceRecord` matching the context tag); `POST /tektos/api/experience/record` (body: `{"session_id": str, "synthesis": dict}` → returns `ExperienceRecord` as dict + `narrative_id`).

Mount is via three new module-level lists in `plugins/tektos/ui/server.py` (or the nearest equivalent Stage 3.11 mount point); if the engine registry slot is `None` at request time, the router returns `503 {"detail": "ADR-105 degrade: <engine> not wired", "adr": "ADR-105"}` (mirrors the ADR-101 request-time degrade shape).

Recent-endpoints for reflection and synthesis fall back to the memory-only ring buffer when `relational_memory` is unbound; for experience, `recent` calls `search_narratives(query=context, ...)` when the port is bound and reads the ring buffer otherwise.

### D9 — Explicit deferrals (out of scope at 8.3)

- **LLM-driven insight generation** (using `LLMPort.generate` to produce natural-language insights richer than the rule-based path) — Stage 8.4+ (needs the planner to close the Hegelian loop).
- **Reflexion (Shinn et al. 2023) actor-evaluator-reflector triad** — Stage 5.X per ADR-039. The pre-Reflexion `confidence=0.75` default is preserved per ADR-036.
- **`SelfImprovementLoop` orchestrator** — Stage 8.7 (multi-agent scope). At 8.3 the three engines are decoupled; wiring them into a single loop is a Stage 8.4 or Stage 8.7 decision, not 8.3.
- **`Hindsight` cross-session HTTP client** — Stage 13 per Plan v2 §Stage 13.
- **`MemorySystem` 4-tier hemispheric model** — Stage 13. The Kosmos-owned `ReflectionInsight` model at 8.3 does **not** carry a `hemisphere` field; if `MemorySystem` lands at 13, `ReflectionInsight` grows an optional `hemisphere: Literal["left", "right"] | None = None` field then, not now.
- **`DreamtimeEngine` background scheduler** — Stage 13 (Plan v2 audit report line 470 lists this as a gap).
- **`LanguageGame` enum on `ExperienceRecord.context`** — Stage 8.4 (planner scope). At 8.3 `context` is a plain `str`.
- **Embedding generation on write_narrative** — Stage 8.4+. All 8.3 writes pass `embedding=None`; the port stores the record with a null embedding and search_narratives falls back to tsvector-only ranking per ADR-102 D3.
- **Turn-loop post-turn auto-reflection hook** — Stage 8.4. At 8.3 the three engines are called explicitly (via the FastAPI routers or via direct Python from `TektosTurnLoop` callers); no automatic subscription to `tektos.agent.turn.completed` events.

## Rationale

**Why rewrite rather than fidelity-port?** The Stage 8.3 audit surfaces that the memory-tier donor engines cross-import `memory.memory_system` (993 lines), `agents.planner.models` (planner domain), and pydantic-BaseModel through their entire dataclass hierarchy. Vendoring under `adapters/tektos/vendor/` (the ADR-103 fidelity-port pattern) would either need to also vendor those transitive dependencies (violating Plan v2 Stage 13 scope for `MemorySystem`, and Stage 8.4 scope for planner) or need import-rewriting of every constructor to inject Kosmos-shaped mocks (which is not fidelity, it's a partial rewrite pretending to be one). The full rewrite preserves the *domain semantics* (rule-based analytic logic, rich model shapes, domain-language intent as docstrings) without dragging in transitive donor infrastructure. This is the same call ADR-104 made when rejecting `_stream_llm` (1471 lines) — sometimes the honest answer is "the semantics port cleanly, but the code doesn't."

**Why `RelationalMemoryPort.write_narrative` and not `MemoryPort` (graph memory)?** `MemoryPort` (ADR-008) is a zero-trust triple store with typed edges and CIDOC-CRM-style claims — the right substrate for facts, not for narratives. `write_narrative` was designed at Stage 8.0 (ADR-102 §D3) precisely for episodic-narrative persistence with tsvector + pgvector hybrid search; the port summary explicitly names "Tektos reflection loop" as its intended first downstream consumer (Kosmos-Build-Sequence-v26.md line 566).

**Why optional collaborators (all four constructor params default `None`)?** Mirrors the ADR-104 pattern for `TektosTurnLoop`. The Stage 8.3 test surface stays fast (no port fixtures required for the analytic-logic tests) and every existing caller keeps working when the ports aren't wired. Wiring the ports is a kernel-boot concern, not an engine-construction concern.

**Why three separate env-gates instead of one?** The three engines have independent operational profiles. Reflection can run against every completed turn (high frequency). Synthesis pairs specs with execution feedback (lower frequency). Experience recall is read-heavy (invoked by planner on every new spec at Stage 8.4). Operators may want reflection on and synthesis off during A/B evaluation of the analytic logic; a single gate would forbid that. Independent gates cost three env-vars and three boot functions but preserve operator flexibility.

**Why 0.75 default confidence and not a per-engine differentiation?** Pre-Reflexion (ADR-039), we have no ground truth for confidence differentiation across the three engines. 0.75 matches every other pre-Reflexion Tektos write (ADR-036) and Zetesis (ADR-052). When Reflexion lands at Stage 5.X, each engine's confidence flow becomes actor-evaluator-derived and this default disappears; a per-engine differentiation now would be a decision without evidence.

### Rejected alternatives

- **A. Fidelity-port memory tier under `adapters/tektos/vendor/` (ADR-103 pattern).** Rejected — drags ~2500 lines of `MemorySystem` + `Hindsight` + `LanguageGame` into Stage 8.3, violating Plan v2 stage assignment. Would need import-rewrites of every constructor to inject Kosmos mocks (partial rewrite pretending to be fidelity port).
- **B. Fidelity-port runtime tier under `adapters/tektos/vendor/`.** Rejected — runtime tier is orphan code (zero external consumers per audit §"Two donor tiers exist"). Porting orphan code creates deletion debt at Stage 14 (retirement + freeze) with no operational value.
- **C. Use `MemoryPort` (graph memory) instead of `RelationalMemoryPort`.** Rejected — `MemoryPort` is a typed-edge triple store, not an episodic-narrative store. Reflection insights and synthesis feedback are narrative-shaped (long text, hybrid text + semantic search) which `write_narrative` was purpose-built for.
- **D. Introduce a new `ReflectionPort` / `SynthesisPort` / `ExperiencePort`.** Rejected — three new ports for what is fundamentally one persistence pattern (narrative writes + tag-filtered search) is port inflation. `RelationalMemoryPort.write_narrative` already exposes exactly the right surface.
- **E. Make the three engines required (non-None) at construction.** Rejected — breaks the Stage 3.13 test-surface pattern where callers construct engines without ports for unit-testing the analytic logic. Optional matches ADR-104.
- **F. Single kernel env-gate `KOSMOS_TEKTOS_ENGINES={off,all,reflection_only,synthesis_only,experience_only,...}`.** Rejected — combinatorially fragile. Three independent gates cost more env-vars but eliminate the parsing surface.
- **G. Auto-subscribe reflection to `tektos.agent.turn.completed` events at boot.** Rejected — cross-plugin event-driven side effects at boot violate the "explicit wiring" principle (ADR-007 spirit). Auto-subscription is a Stage 8.4 decision when the planner needs the automation loop.

## Consequences

### Files that will change

- **New:** `plugins/tektos/reflection/{__init__.py, models.py, engine.py, api.py, test_reflection.py}`
- **New:** `plugins/tektos/synthesis/{__init__.py, models.py, engine.py, api.py, test_synthesis.py}`
- **New:** `plugins/tektos/experience/{__init__.py, models.py, replay.py, api.py, test_experience.py}`
- **New:** `tests/kernel/test_stage_8_3_engine_wiring.py` — kernel-wiring acceptance tests (~8 tests)
- **Amend:** `plugins/tektos/plugin.py` — add three optional dataclass fields (`reflection`, `synthesis`, `experience`)
- **Amend:** `kernel/app.py` — add three `_BootRegistry` slots (`tektos_reflection`, `tektos_synthesis`, `tektos_experience`) + three `_boot_*` functions between `_boot_tektos_turn_loop` and `_boot_gnosis_seeder`
- **Amend:** `docs/Kosmos-Build-Spec-v26.md` §17 — add ADR-105 row ahead of ADR-104
- **Amend:** `docs/Kosmos-Build-Sequence-v26.md` — add Stage 8.3 stanza after the Stage 8.2 stanza
- **Amend:** `docs/adrs/README.md` — add ADR-105 row
- **Amend:** `BUILD_LOG.md` — append Stage 8.3 completion entry
- **Overwrite:** `SESSION_HANDOFF.md`

### PORTING_LEDGER.md

**No change.** Stage 8.3 ports semantics, not code; there is no vendored file. The audit doc (`docs/stage-8-3-donor-audit.md`) records the classification for durability.

### Downstream consumers

- Stage 8.4 (planner-orchestrator + task-decomposer): can call `ExperienceReplay.recall(context, limit)` when generating specs. The planner's `spec.metadata["synthesis_guidance"]` field (Plan v2 §Stage 8.4 obligation) reads from this recall path.
- Stage 8.5 (coding-agent executor): may call `ReflectionEngine.reflect_on_turn(turn_outcome)` after every commit-audit event.
- Stage 8.7 (multi-agent orchestrator): will introduce a `SelfImprovementLoop` that wires the three engines into the Hegelian dialectic (thesis-antithesis-synthesis-new-thesis cycle). At 8.3 the engines are decoupled by design.

### Invariants preserved

- **ADR-007** — every new file in `plugins/tektos/{reflection,synthesis,experience}/` imports only from `ports.*` and its own subpackage (never from another plugin). Test surface includes AST-guard tests mirroring the ADR-052 Zetesis pattern.
- **ADR-008** — every `write_narrative` call supplies `provenance` (non-empty) + `confidence` (in `(0, 1]`); the port validates. Zero-trust discipline preserved through the port, not re-implemented at the engine layer.
- **ADR-023** — every EventBus publish uses `EventEnvelope` (envelope-first); no positional publish.
- **ADR-036** — pre-Reflexion `confidence=0.75` default preserved.
- **ADR-039** — Reflexion deferred (Stage 5.X); pre-Reflexion default sits in `(0, 1]`.
- **ADR-045** — FastAPI routers mount under `/tektos/api/*` (UI-parity route prefix).
- **ADR-052** — Zetesis MemoryPort constants pattern mirrored (nine locked constants exported by engine `__init__.py`).
- **ADR-101** — degrade pattern for optional kernel-boot collaborators (WARN log + `registry.<slot>=None`).
- **ADR-102** — `RelationalMemoryPort.write_narrative` used as the sink for the first time by a Tektos runtime slice, discharging the ADR-102 §"Downstream call-site adoption" obligation for Stage 8.3.
- **ADR-103** — `SessionPort` remains the source of truth for session lifecycle; the engines consume `session_id` from `TurnOutcome` and never mutate FSM state.
- **ADR-104** — Stage 8.2 `TektosTurnLoop` unchanged at 8.3; no cross-file amendment to `turn_loop.py`.

## Lock-in phase

Stage 8.3.

## References

- `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md` §Stage 8.3
- `docs/stage-8-3-donor-audit.md` (this session)
- `docs/adrs/ADR-102-relational-memory-port.md` (5th memory layer + `write_narrative`)
- `docs/adrs/ADR-103-session-port-and-tektos-fidelity.md` (SessionPort as source of truth)
- `docs/adrs/ADR-104-tektos-turn-loop-session-and-llm-integration.md` (Stage 8.2 turn-loop as insight source)
- `docs/adrs/ADR-036-*.md` (Tektos pre-Reflexion `confidence=0.75` default)
- `docs/adrs/ADR-039-stage-3-4-and-3-5-defer.md` (Reflexion deferred to Stage 5.X)
- `docs/adrs/ADR-052-zetesis-plugin-skeleton.md` (locked-constants pattern mirrored)
- `docs/adrs/ADR-101-*.md` (degrade pattern for optional kernel-boot collaborators)
