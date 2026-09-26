# ADR-078 — Kosmos-Build-Spec v26 cut (Tektos absorption)

**Status:** Ratified
**Locked:** ADR-145 (2026-09-26) — Stage 14 program freeze; this ADR is locked (see ADR-145).
**Lock-in phase:** Stage 1
**Supersedes:** Kosmos-Build-Spec-v25.md (archived, not deleted)

## Context

ADR-077 ratified the kosmos-lms integration cut — full fork of `rmholston420/kosmos`, absorption of `rmholston420/tektos-ultima` as **the** implementation of the `plugins/tektos/` scaffold, six new formal ports proposed under ADR-079 through ADR-084, five existing-port amendments under ADR-085 through ADR-089, and one deferred proposal (ADR-090 SelfModificationPort).

Kosmos-Build-Spec-v25.md is the current authoritative baseline. It contains no reference to the Tektos-Ultima runtime, no reference to the six new ports, no reference to the iframe/microfrontend frontend strategy, and no reference to the loop-safety / immune / thermal / sandbox subsystems that Tektos-Ultima brings.

Continuing to treat v25 as authoritative while ADRs 077–090 accumulate would create the exact silent-duplication failure mode that `kosmos-spec-diff` forbids: decisions ratified in ADRs would not appear in the spec's §17 summary, and the §21 rollout plan would not sequence them.

## Decision

Cut **Kosmos-Build-Spec-v26.md** and archive v25.

### v26 changes relative to v25

1. **Header rewrite** — status becomes "Ratified. Stage-1-executable. kosmos-lms (Tektos-Ultima absorbed).", supersedes chain adds v25, baseline-resolution rule preserved verbatim.
2. **§3 Repo Inventory** — table gains one row: `rmholston420/tektos-ultima` marked **ABSORBED (2026-09-10)** with ADR-077 reference; `rmholston420/kosmos` marked **SUPERSEDED by rmholston420/kosmos-lms (2026-09-10)** with ADR-077 reference.
3. **§4 Longevity Architecture — Ports and Adapters** — six new formal ports appended to the port inventory table with their governing ADR IDs and lock-in stages: `ImmunePort` (ADR-079 · Stage 3), `LoopSafetyPort` (ADR-080 · Stage 3), `ThermalPort` (ADR-081 · Stage 3), `SandboxPort` (ADR-082 · Stage 4), `VoicePort` (ADR-083 · Stage 6), `VisionPort` (ADR-084 · Stage 6). Total formal ports: 15 → 21.
4. **§17 ADR Consolidated Summary** — appends rows for ADR-077 through ADR-090 mirroring the ADR-index format. `docs/adrs/README.md` and §17 remain in agreement per `kosmos-spec-diff` fan-out rule.
5. **§18 Tektos — Full Build Specification** — scope extended: existing §18 (which specified the plugin-scaffold shape ratified by ADR-036/037/038/041/042/044/045/046/063/065) is preserved. A new §18.10 "Absorbed Tektos-Ultima runtime" enumerates the runtime subsystems now owned by `plugins/tektos/`: iteration runtime, immune (12 detectors), loop safety (3-tier + read-only budget), planner, self-improvement + self-repair (gated behind ADR-090), thermal control (yellow/cap/red PID), hindsight bridge memory adapter, gateway proxy, tool registry, 40-panel Next.js frontend.
6. **§21 Rollout Plan v26** — inserts Stages 3.13 (immune + loop-safety + thermal port-in), 4.7 (sandbox + planner + tool registry port-in), 5.6 (self-improvement gated port-in), 6.5 (voice + vision port-in), 7.4 (hindsight migration H1 → H2, DozerDB primary) per `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN.md`. Existing Stage numbering preserved; new stages slotted at natural DoD boundaries.
7. **§25 Tektos absorption (new section)** — appended between §24 (Program Sign-Off) and the v25 Addendum. Contents:
   - §25.1 Absorption principle (one paragraph).
   - §25.2 Frontend strategy (Kosmos Next 16.2.11 shell hosts Tektos Next 15.4 UI as iframe/microfrontend under `/tektos/frontend`, same-origin via reverse proxy; adds `FrontendContractPort.PanelKind.IFRAME` per ADR-089).
   - §25.3 Hindsight decision (bridge adapter H1 in Stages 3–5, migrate to H2 DozerDB primary in Stage 7).
   - §25.4 Provenance taxonomy — 13 entries required on Tektos-side `MemoryPort` writes (`tektos_agent`, `tektos_reflection`, `tektos_planner`, `tektos_self_modification`, `immune_system`, `immune_verdict`, `loop_safety`, `thermal`, `sandbox`, `hindsight_bridge`, `tektos_tool`, `tektos_gateway`, `tektos_frontend`). Every entry MUST supply `confidence` per §7 zero-trust.
   - §25.5 Kernel boot order after Stage 3.13 (new sequence): immune → loop_safety → thermal → notification → frontend_contract → resource → event_bus → approval → sandbox → mcp → memory → llm → phrouros → praxis → zetesis → tektos.
   - §25.6 Loop safety read-only budget interlock (ADR-088 summary).
   - §25.7 Tektos ports (8020 backend, 8765 gateway, 5556 frontend, 8095 llama-server hindsight, 9000 hindsight-api) reserved in `ports.toml`. `HindsightConfig` default `:9177` → `:9000` at port-in (Tektos-Ultima source bug fix).
8. **v25 Addendum** — preserved verbatim at the end of v26. All seven post-ADR-057 rules survive unchanged.
9. **v25 archived** — `docs/Kosmos-Build-Spec-v25.md` moves to `docs/archive/Kosmos-Build-Spec-v25.md`. New file `docs/archive/README.md` explains the archive rule (never referenced from live code, sequence, or ADRs). `docs/Kosmos-Build-Spec-v26.md` is the new live spec.
10. **Kosmos-Build-Sequence-v25.md** — renamed to `docs/Kosmos-Build-Sequence-v26.md` with new stages 3.13, 4.7, 5.6, 6.5, 7.4 inserted at the natural DoD boundaries per the integration plan. v25 sequence archived alongside the v25 spec.

## Rationale

- **New section rather than renumbering** avoids invalidating every existing "spec §7 zero-trust" reference in the codebase (search hits: `ports/memory.py`, `ports/data.py`, `ports/resource.py`, hundreds of adapter docstrings and log entries). Renumbering would fan out into a hundred stale references.
- **v26 cut rather than v25 amendment** because 14 ADRs (077 + 078 + 079..090) is a significant surface change — enough to trigger the `kosmos-spec-diff` "version bump" workflow.
- **Preserve v25 addendum verbatim** because all seven rules remain load-bearing (llama-swap-only routing, MoltMCP transport pinning, OpenHands pattern-vendor floor, Zetesis inner-loop lock, source-diversity as audit signal, A2A+AGUI protocol pinning, dark-first GUI).
- **Archive not delete** — `docs/archive/Kosmos-Build-Spec-v25.md` and `docs/archive/Kosmos-Build-Sequence-v25.md` retained for provenance; git history preserved either way but a physical file makes the supersession explicit for readers who haven't cloned.

## Consequences

- Files created: `docs/Kosmos-Build-Spec-v26.md`, `docs/Kosmos-Build-Sequence-v26.md`, `docs/archive/README.md`, `docs/adrs/ADR-078-kosmos-build-spec-v26-cut.md` (this file).
- Files moved (git mv): `docs/Kosmos-Build-Spec-v25.md` → `docs/archive/Kosmos-Build-Spec-v25.md`, `docs/Kosmos-Build-Sequence-v25.md` → `docs/archive/Kosmos-Build-Sequence-v25.md`.
- Files edited: `docs/adrs/README.md` (ADR-078 status Proposed → Ratified), `BUILD_LOG.md` (Stage 1.1 + 1.2 entries), `SESSION_HANDOFF.md` (overwrite at session end).
- The 14 ADRs authored under ADR-077's plan (ADR-077 already Ratified, ADR-078 this file, ADR-079..090 to author in Stage 1.3) all become referenced from v26 §17. Any subsequent code change referencing "spec v25" must be updated to "spec v26" — grep target for future work.
- All spec-reference tooling (`Kosmos-ADRs-Bundle.md`, `Kosmos-Perplexity-Skills-Bundle.md`, skill instructions) continues to point at v25 file names in their prose until re-bundled. The bundled MDs are convenience artifacts, not authoritative — no immediate fan-out required.

## Lock-in phase

Locked at Stage 1.2. Superseded only by ADR-### that cuts a v27 spec.

## References

- ADR-077 (kosmos-lms integration cut) — the parent decision this spec codifies
- `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN.md` §5 (Stage 1)
- `kosmos-spec-diff` skill — governs this edit
- Kosmos-Build-Spec-v25.md (archived) — the direct predecessor
