# ADR-077 — Kosmos-LMS integration cut (Tektos-Ultima absorption)

**Status:** Ratified
**Lock-in phase:** Stage 0
**Supersedes:** —
**Amends:** ADR-041 (Tektos plugin bootstrap — scope extended from Stage 3.7 scaffold to full runtime absorption)

## Context

Two active repositories under `rmholston420` express one intended architecture:

- `rmholston420/kosmos` — sovereign local-first Life Management System with a formal kernel, 15 ports, 15+ adapters, ratified plugin scaffold at `plugins/tektos/` (ADR-036/037/038/041/042/044/045/046/063/065).
- `rmholston420/tektos-ultima` — autonomous coding agent with multi-iteration runtime, 12-detector immune system, 3-tier loop safety, PID thermal control, 4-tier memory model, planner, self-improvement / self-repair, gateway proxy, and 40 status panels.

Tektos was always intended to be the coding-agent plugin for Kosmos. The two grew in parallel; Kosmos scaffolded the port-integration surface, Tektos-Ultima built the runtime.

Continuing both repos separately duplicates work, drifts contracts, and blocks Kosmos's remaining stages (Stage 1.7+) that depend on Tektos capabilities.

## Decision

Create `rmholston420/kosmos-lms` (public, MIT-licensed) as a full fork of `rmholston420/kosmos` and absorb `rmholston420/tektos-ultima` into it as **the** implementation of the Tektos plugin.

Scope of the absorption:

1. `kosmos-lms` is MIT-licensed at repo root. All Tektos-derived modules are relicensed at port-in by the sole copyright holder (rmholston420) — PORTING_LEDGER entries cite the author as the relicensor.
2. The existing Kosmos `plugins/tektos/` scaffold (ratified by ADR-036/037/038/041/042/044/045/046/063/065) is **preserved and extended**, not replaced. Tektos-Ultima's runtime, immune, loop-safety, planner, self-improvement, self-repair, thermal, sandbox, and memory subsystems land as sub-packages under `plugins/tektos/`.
3. Six new formal ports are proposed under separate ADRs: `ImmunePort` (ADR-079), `LoopSafetyPort` (ADR-080), `ThermalPort` (ADR-081), `SandboxPort` (ADR-082), `VoicePort` (ADR-083), `VisionPort` (ADR-084). `MemoryPort` is extended with `search_hybrid` (ADR-085). `EventBusPort` envelope taxonomy is formalised (ADR-086). Hermes LLM topology adapter is added (ADR-087). Loop-safety read-only budget interlock is formalised (ADR-088). `FrontendContractPort` gains `PanelKind.IFRAME` (ADR-089). `SelfModificationPort` is proposed but deferred (ADR-090).
4. Frontend strategy: the Kosmos Next.js shell (`ui/`, Next 16.2.11) hosts the Tektos Next.js UI (`plugins/tektos/frontend/`, Next 15.4) as an iframe/microfrontend, mounted by the kernel under `/tektos/frontend` on the same origin.
5. All Tektos-Ultima ADRs (both `ADR-LEDGER.md` and `adrs/README.md`, which conflict on ADR-004 and ADR-005) are discarded. Every Tektos-derived decision gets a fresh Kosmos ADR ID starting at ADR-077.
6. Tektos-Ultima's `.github/workflows/ci.yml` (six jobs: ruff, mypy, pytest, next build, eslint, Playwright chromium) becomes the kosmos-lms CI baseline, extended with Kosmos port-contract tests + AST plugin-isolation test.
7. Sunset markers on `rmholston420/kosmos` and `rmholston420/tektos-ultima` — kosmos-lms is the single ongoing home.

Kosmos discipline applies verbatim: ports/adapters, ADR authoring, PORTING_LEDGER, BUILD_LOG/DEBUG_LOG/KNOWN_ISSUES/SESSION_HANDOFF quartet, ADR-007 events-only cross-plugin coupling, MemoryPort zero-trust writes (`provenance` + `confidence` non-bypassable).

## Rationale

- **Full fork + rewrite** over subtree-vendoring or submodule: user directive, and the audit showed Kosmos's `plugins/tektos/` scaffold + Tektos-Ultima's runtime need to be surgically merged, not held side-by-side.
- **Preserve Kosmos scaffold + layer Tektos** over wholesale replacement: keeps 10 ratified ADRs valid, keeps 5,565 LOC of Stage-3 exit-gate tests green, and keeps Stage 3.12 alignment intact.
- **Iframe microfrontend** over unified Next.js shell: defers a Next 15 → Next 16 version reconciliation, keeps Tektos's 40 panels + Monaco + xterm + D3 dependencies untouched, and gives each app its own dev port.
- **MIT re-license at port-in** over adding a LICENSE to tektos-ultima first: same copyright holder, same practical effect, avoids modifying the source repo mid-fork.

## Consequences

- `rmholston420/kosmos-lms` created public, MIT, forked from `rmholston420/kosmos` at Stage 0.1.
- Files affected in Stage 0: `LICENSE` (new), `README.md` (edited to identify kosmos-lms), `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN.md` (new), `docs/plans/kosmos_tektos_audit_report.md` (new), `docs/adrs/ADR-077-kosmos-lms-integration-cut.md` (this file), `docs/adrs/README.md` (index row), `PORTING_LEDGER.md` (absorption section seeded), `BUILD_LOG.md` (Stage 0 entries), `SESSION_HANDOFF.md` (overwritten).
- Kosmos-Build-Spec-v25 is preserved as the baseline. ADR-078 cuts a v26 spec with §22 "Tektos absorption" appended and archives v25 to `archive/`.
- Downstream ADRs to author in Stage 1: ADR-078 through ADR-091 per §3–§4 of the integration plan.
- PORTING_LEDGER receives an "## Tektos-Ultima absorption" section with `PLANNED` entries for every Tektos module family to be ported in Stages 3–7.
- CI extended per Stage 0.5.

## Lock-in phase

Locked at Stage 0 (repository genesis). Superseded only by an explicit reversal ADR.

## References

- Integration plan: `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN.md`
- Source audit: `docs/plans/kosmos_tektos_audit_report.md`
- ADR-007 events-only cross-plugin coupling
- ADR-027 MemoryPort zero-trust write contract (`provenance` + `confidence`)
- ADR-036 Tektos coding agent shape (amended by this ADR)
- ADR-041 Tektos plugin bootstrap (scope extended by this ADR)
- Kosmos-Build-Spec-v25.md §17, §21
