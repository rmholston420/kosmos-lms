# Stage 8.3 Donor Audit — Reflection + Synthesis + Experience-Replay Engines

**Date:** 2026-09-10
**Stage:** Plan v2 · Stage 8.3 (Reflection + synthesis + experience-replay engines; ~2 sessions)
**Scope:** classify donor code under `tektos-ultima/src/tektos/{runtime,memory}/{reflection_engine,synthesis_engine,experience_replay}.py` as extend-vs-fidelity-port-vs-rewrite-vs-defer per the ADR-104 kill-switch pattern established at Stage 8.2.
**Precedent:** ADR-103 (SessionPort fidelity port + kill-switch), ADR-104 (Stage 8.2 turn-loop extension + explicit deferrals), ADR-102 (`RelationalMemoryPort.write_narrative` sink).

## Two donor tiers exist

The donor repo carries **two parallel implementations** of every Stage 8.3 subsystem. Correctly picking the donor set is the first decision.

| File | Lines | Class shape | External coupling | Consumers |
|---|---|---|---|---|
| `runtime/reflection_engine.py` | 104 | `@dataclass Reflection` + `ReflectionEngine` module-singleton | none — pure in-memory | **zero** (orphan) |
| `runtime/synthesis_engine.py` | 140 | `@dataclass SynthesisResult` + `SynthesisEngine` module-singleton | none — pure in-memory | **zero** (orphan) |
| `runtime/experience_replay.py` | 68 | `@dataclass Experience` + `ExperienceReplay` module-singleton | none — pure in-memory | **zero** (orphan) |
| `memory/reflection_engine.py` | 470 | pydantic `ReflectionInsight` + `ReflectionState` + `ReflectionEngine(memory_system, dreamtime_engine)` | `MemorySystem` (993 lines) + `DreamtimeEngine` + `Hemisphere` enum + `MemoryEntry` | `main.py:1206` (live) |
| `memory/synthesis_engine.py` | 312 | pydantic `SynthesisFeedback` + `SynthesisEngine(reflection_engine, memory_system)` | `memory.memory_system.MemorySystem` + `memory.reflection_engine.*` | `main.py:1216` (live) |
| `memory/experience_replay.py` | 351 | pydantic `ExperienceRecord` + `ExperienceReplay(max_records)` | `memory.synthesis_engine.SynthesisFeedback` + `agents.planner.models.LanguageGame` | `memory/synthesis_engine.py:79` |

**Consumer proof:** `grep -rn "reflection_engine\|synthesis_engine\|experience_replay" --include="*.py"` across the whole donor tree finds `runtime/*` engines are imported by exactly zero external files. `main.py` wires `memory.*` engines at boot lines 1206/1216 (line 1206: `ReflectionEngine(memory_system=..., dreamtime_engine=...)`).

**Conclusion:** the `runtime/*` engines are dead code — an earlier stub the codebase never rewired away from. The `memory/*` engines are the live path.

## The trap: the memory-tier engines drag in the whole 4-tier hemispheric memory system

The `memory/reflection_engine.py::ReflectionEngine` constructor demands `MemorySystem` — which is a 993-line domain model of the human brain's 4-tier memory (Sensory / Working / Long-Term / Procedural) with a bicameral (left/right hemisphere) split, a `MemoryEntry` pydantic model that carries a `hemisphere` field, a `DreamtimeEngine` background processor, and integrations with `Hindsight` (cross-session memory) and the `SelfImprovementLoop` orchestrator.

Fidelity-porting the memory tier means dragging in:
- `memory/memory_system.py` (993 lines) — `MemorySystem`, `MemoryTier`, `Hemisphere`, `MemoryEntry`, `DreamState`, `DreamtimeEngine`
- `memory/hindsight_client.py` (148 lines) — cross-session memory HTTP client
- `agents/planner/models.py` (`LanguageGame` enum consumed by `ExperienceRecord.context`)
- `agents/self_improvement/loop_orchestrator.py` (Hegelian dialectic driver — wires ReflectionEngine into SynthesisEngine into ExperienceReplay into Planner)

Total incremental port surface if the memory tier is chosen wholesale: **~2500+ lines**, none of which are in Plan v2 Stage 8.3 scope. Plan v2 explicitly lists `MemorySystem`, `DreamtimeEngine`, and `Hindsight` under **Stage 13 (Remaining donor subsystems)** or later.

## The port-consuming rewrite path

Kosmos already has the correct sink for what Stage 8.3 needs: `RelationalMemoryPort.write_narrative(session_id, agent_id, title, body, tags, embedding, confidence, provenance)` (ADR-102 §D3). This is the 5th memory layer's episodic-narrative store with tsvector + pgvector hybrid search — the exact substrate `ExperienceReplay` needs for "past syntheses as guidance."

The memory-tier engines' 4-tier hemispheric architecture is one *implementation* of an episodic memory. `RelationalMemoryPort` is Kosmos's *contract* for episodic memory. Stage 8.3 should sit above the port, not vendor a competing implementation.

### What each engine actually needs, expressed against Kosmos ports

**ReflectionEngine** — "generate an insight from a completed turn or session":
- Input: a `TurnOutcome` (already produced by Stage 8.2 `TektosTurnLoop`) or a completed session's transitions from `SessionPort`.
- Output: a `ReflectionInsight` (compact structured record: `insight_type`, `content`, `confidence`, `evidence`).
- Persistence: `RelationalMemoryPort.write_narrative(title="reflection.<type>", body=insight_text, tags=("reflection", <type>), confidence=..., provenance="tektos.reflection")` and/or `record_event(kind="tektos.reflection.completed", payload=..., provenance="tektos.reflection")`.
- LLM: **optional** — the runtime-tier donor engine is 100% rule-based (`_generate_insight` checks `success` + `error` keys); the memory-tier engine is also rule-based (hemispheric counts, keyword scan for `"execute"`/`"error"`/`"fail"`). Both are analytic, not generative. At Stage 8.3 the rule-based path is enough; an LLM `generate` hook is a Stage 8.4+ enhancement.

**SynthesisEngine** — "combine plan (spec) with execution feedback into a feed-forward lesson":
- Input: a spec (`TurnOutcome.llm_response` or planner spec — the planner isn't in scope until Stage 8.4, so at 8.3 the input is a completed `TurnOutcome` and a paired earlier spec dict).
- Output: a `SynthesisResult` (lessons list, recommendations list, confidence).
- Persistence: `RelationalMemoryPort.write_narrative(title="synthesis.<spec_id>", body=synthesis_text, tags=("synthesis", spec_id), confidence=..., provenance="tektos.synthesis")`.
- LLM: same as reflection — rule-based at 8.3, generative at 8.4+.

**ExperienceReplay** — "store synthesis feedback + retrieve relevant past experiences by context":
- Input: a `SynthesisResult`.
- Output: an `ExperienceRecord` list on `recall(context, limit)`.
- Persistence: `RelationalMemoryPort.write_narrative(title="experience.<cycle_id>", body=guidance_text, tags=("experience", context), confidence=..., provenance="tektos.experience")` for write; `search_narratives(query=context, tags=("experience",), limit=N)` for recall. **No separate in-memory `_records` list** — the ledger is the source of truth.

Every payload the memory-tier `ExperienceRecord` model carries (`cycle_id`, `insight_type`, `what_happened`, `what_was_expected`, `guidance`, `context`, `confidence`, `priority`, `timestamp`, `tags`) fits inside a narrative's `body` (JSON) + `tags` tuple. No new port needed.

## Recommended disposition (per subsystem)

| Donor subsystem | Recommended disposition | Rationale |
|---|---|---|
| `runtime/reflection_engine.py` | **Reject** — orphan code | Zero consumers; runtime tier was superseded by memory tier the codebase never cleaned up. |
| `runtime/synthesis_engine.py` | **Reject** — orphan code | Same. |
| `runtime/experience_replay.py` | **Reject** — orphan code | Same. |
| `memory/reflection_engine.py` | **Rewrite against `RelationalMemoryPort` + `SessionPort`** | The 470-line pydantic-heavy hemispheric model belongs to Stage 13's memory-system port-in. At 8.3 we take the *contract shape* (session-level reflection producing an insight record) and implement it against Kosmos's existing 5th-layer port. |
| `memory/synthesis_engine.py` | **Rewrite against `RelationalMemoryPort`** | Same reasoning. The Hegelian dialectic prose is preserved as ADR narrative + docstring; the Python shape is Kosmos-native. |
| `memory/experience_replay.py` | **Rewrite against `RelationalMemoryPort.search_narratives`** | Same. The ledger becomes the source of truth; the donor's in-memory `_records` list is dropped (fail-open reads from the port). |
| `memory/memory_system.py` | **Defer to Stage 13** | 993-line domain model outside Plan v2 Stage 8.3 scope. When it lands as a port-in at Stage 13, the Stage 8.3 rewrite either continues coexisting (rule-based path stays) or grows an optional `memory_system: MemorySystem | None = None` constructor slot for richer analytics. |
| `memory/hindsight_client.py` | **Defer to Stage 13** | Cross-session HTTP client; `RelationalMemoryPort` already provides cross-session narrative persistence for 8.3's needs. |
| `agents/planner/models.py::LanguageGame` | **Defer to Stage 8.4** | `LanguageGame` is planner-domain; Stage 8.4 lands the planner. At 8.3 `context` is a plain `str`. |
| `agents/self_improvement/loop_orchestrator.py` | **Defer to Stage 8.7** | The Hegelian loop orchestrator sits above reflection + synthesis + experience-replay + planner + coding-agent. Stage 8.7 (multi-agent orchestrator) is its correct home. |

## Kill-switch review (per ADR-103 discipline)

Every rewrite call above is defensible against three failure modes:

1. **Would fidelity-porting `memory/*_engine.py` be strictly better?** No — it drags ~2500 unrelated lines into Stage 8.3 (violating Plan v2 scope), duplicates the RelationalMemoryPort's episodic-memory role (violating ADR-008 single-responsibility for writes), and cross-imports between `memory/`, `agents/planner/`, and `runtime/` in ways that would break ADR-007 when translated to Kosmos plugin space.
2. **Would rewriting from scratch inside the port be too speculative?** No — the donor's rule-based analytic logic (`_generate_insight` / `_extract_lessons` / `_generate_recommendations`) is preserved verbatim as helper functions. The rewrite touches wiring (constructor takes ports; persistence goes through `write_narrative`), not analytic logic.
3. **Does the rewrite lose donor semantics we'll want later?** The rich pydantic models (`ReflectionInsight` with `is_direct_experience` + `trust_score` + `bias_detected` + `correction`; `SynthesisFeedback` with `insight_type` + `what_happened` + `what_was_expected` + `guidance`; `ExperienceRecord` with `cycle_id` + `priority`) survive as Kosmos-owned dataclasses in `plugins/tektos/reflection/models.py`, etc. The domain-language docstrings (Hegelian dialectic, yogic direct-experience, McKenna novelty) survive as module docstrings so the intent remains discoverable. Only the `MemorySystem`-bound machinery is dropped.

## Proposed Stage 8.3 slice

Three new plugin subpackages under `plugins/tektos/`:

```
plugins/tektos/
  reflection/
    __init__.py
    models.py            # ReflectionInsight dataclass (frozen slotted)
    engine.py            # ReflectionEngine(relational_memory, session_port)
    test_reflection.py
  synthesis/
    __init__.py
    models.py            # SynthesisResult dataclass
    engine.py            # SynthesisEngine(relational_memory)
    test_synthesis.py
  experience/
    __init__.py
    models.py            # ExperienceRecord dataclass
    replay.py            # ExperienceReplay(relational_memory) — search_narratives-backed
    test_experience.py
```

All three engines are **optional collaborators** (constructors accept `RelationalMemoryPort | None`; if `None`, engines run in memory-only mode and no persistence happens — mirrors the ADR-104 pattern for optional ports on `TektosTurnLoop`).

Locked write predicates (mirror ADR-036 / ADR-052 pattern):
- `TEKTOS_REFLECTION_PROVENANCE = "tektos.reflection"`
- `TEKTOS_REFLECTION_PREDICATE = "tektos.reflection.completed"`
- `TEKTOS_REFLECTION_DEFAULT_CONFIDENCE = 0.75` (matches ADR-036 pre-Reflexion default)
- `TEKTOS_SYNTHESIS_PROVENANCE = "tektos.synthesis"`
- `TEKTOS_SYNTHESIS_PREDICATE = "tektos.synthesis.completed"`
- `TEKTOS_SYNTHESIS_DEFAULT_CONFIDENCE = 0.75`
- `TEKTOS_EXPERIENCE_PROVENANCE = "tektos.experience"`
- `TEKTOS_EXPERIENCE_PREDICATE = "tektos.experience.recorded"`
- `TEKTOS_EXPERIENCE_DEFAULT_CONFIDENCE = 0.75`

Kernel wiring: three env-gates (`KOSMOS_TEKTOS_REFLECTION`, `KOSMOS_TEKTOS_SYNTHESIS`, `KOSMOS_TEKTOS_EXPERIENCE` — each `{off,on}`, default `off`). ADR-101 degrade pattern: if `on` but `registry.relational_memory` is None, boot slot degrades to `None` with WARN log; the engines still work in memory-only mode when constructed directly, but the kernel slots stay unwired until the ledger is available.

`TektosPlugin` dataclass grows three new optional fields:
- `reflection: object | None = None`
- `synthesis: object | None = None`
- `experience: object | None = None`

Two new event types added to the Stage 8.2 `tektos.agent.turn.*` fan-out:
- `tektos.reflection.completed` (payload: `session_id`, `insight_type`, `confidence`, `narrative_id?`)
- `tektos.synthesis.completed` (payload: `session_id`, `spec_id`, `confidence`, `narrative_id?`)
- `tektos.experience.recorded` (payload: `session_id`, `cycle_id`, `context`, `narrative_id?`)

## FastAPI endpoints (Plan v2 goal)

Plan v2 Stage 8.3 lists three endpoints: `POST /tektos/api/reflection/reflect`, `POST /tektos/api/synthesis/synthesize`, `GET /tektos/api/experience/recent`. Donor `main.py` does **not** define these — they are greenfield. At Stage 8.3 the code path lives at `plugins/tektos/reflection/api.py`, `plugins/tektos/synthesis/api.py`, `plugins/tektos/experience/api.py` (three thin FastAPI routers). The routes mount into the existing Tektos FastAPI app landed at Stage 3.11 (`plugins/tektos/ui/server.py`).

Mount point per ADR-045 UI-parity discipline: `/tektos/api/reflection/*`, `/tektos/api/synthesis/*`, `/tektos/api/experience/*`. Endpoint smoke tests exercise both engines wired (real narrative-id returned) and engines unwired (503 with `ADR-101 degrade` reason field).

## Explicit deferrals (for the ADR)

- **`_generate_insight` / `_extract_lessons` LLM path** — the donor is rule-based; a `LLMPort.generate` hook that produces richer natural-language insights is Stage 8.4+ scope (needs the planner to close the Hegelian loop). D9 defers.
- **Reflexion (Shinn et al. 2023) actor-evaluator-reflector triad** — ADR-036 pre-Reflexion `confidence=0.75` default is preserved; Reflexion itself lands at Stage 5.X per ADR-039 (deferred from Stage 3.5).
- **`SelfImprovementLoop` orchestrator** — Stage 8.7 (multi-agent). At 8.3 the three engines are decoupled and produced by hand-wiring or by `TektosTurnLoop` post-turn hooks (a Stage 8.4 wiring choice, not 8.3).
- **`Hindsight` cross-session client** — Stage 13 per Plan v2 §Stage 13 catalog.
- **`MemorySystem` 4-tier hemispheric model** — Stage 13.
- **`Dreamtime` background reflection scheduler** — Plan v2 audit report line 470 identifies this as a Stage 13 gap.
- **`LanguageGame` enum on `ExperienceRecord.context`** — Stage 8.4 (planner scope). At 8.3 `context` is a `str`.

## Test surface plan

Following the Stage 8.2 pattern (19 turn-loop tests + 7 kernel-wiring tests = 26 total):

- `plugins/tektos/reflection/test_reflection.py` — ~12 tests: dataclass frozen invariants (1), locked constants (3), engine construction with/without port (2), `reflect_on_turn(outcome)` produces insight + writes narrative when port present (2), category/confidence rule-based path (2), no-write when port absent (1), zero-trust validation reject (1).
- `plugins/tektos/synthesis/test_synthesis.py` — ~10 tests: dataclass invariants (1), locked constants (3), engine construction (1), `synthesize(spec, feedback)` produces result + narrative (2), lessons/recommendations extraction (2), no-write when port absent (1).
- `plugins/tektos/experience/test_experience.py` — ~10 tests: dataclass invariants (1), locked constants (3), engine construction (1), `record(synthesis)` writes narrative (1), `recall(context, limit)` searches narratives + filters by tag (2), no-write when port absent (1), fail-open recall on port exception (1).
- `tests/kernel/test_stage_8_3_engine_wiring.py` — ~8 tests: three engines × (unset / off / on-with-port / on-without-port) shape checks + boot-order proof + TektosPlugin field reflection.

Estimated total: **~40 new tests**. Full regression target: **1616 passed / 21 skipped / 1 deselected** (1576 baseline + 40 delta).

## Next step

Author ADR-105 with the following explicit decisions (D1–D9):
- D1: scope (reflection + synthesis + experience-replay as three plugin subpackages under `plugins/tektos/`)
- D2: donor-tier selection (rewrite from memory-tier semantics; reject runtime-tier orphan code; defer `MemorySystem` to Stage 13)
- D3: `RelationalMemoryPort.write_narrative` as the persistence sink; no new port
- D4: locked write predicates (three provenances, three predicates, three default confidences all 0.75)
- D5: `TektosPlugin` dataclass amendment (three optional fields)
- D6: kernel wiring (three env-gates, ADR-101 degrade)
- D7: two new event types on the EventBus (`tektos.reflection.completed`, `tektos.synthesis.completed`, `tektos.experience.recorded`)
- D8: FastAPI mount under `/tektos/api/{reflection,synthesis,experience}/*`
- D9: explicit deferrals (LLM path → 8.4; Reflexion → 5.X per ADR-039; SelfImprovementLoop → 8.7; MemorySystem/Hindsight/Dreamtime → 13; LanguageGame → 8.4)

Then implement, test, doc-fanout, commit, tag `stage-8-3-complete`, push.
