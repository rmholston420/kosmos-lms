# Kosmos-LMS Architecture Conformity & Migration Plan (Hermes Edition)

| Field | Value |
|---|---|
| Document | `docs/implementation/TEKTOS_HERMES_IMPLEMENTATION_PLAN.md` (file name kept for continuity with PR #1; "Tektos" in the name is historical — the subsystem is **Tekton** from v2.0 on) |
| Version | **2.0 — 2026-09-28 10:35 EDT** (supersedes 1.0 of 08:55 EDT; change log in Appendix F) |
| Audited baseline | `rmholston420/kosmos-lms` `main@7e7b1e30277a2bb24514459cc5350939e628ddf2` (299 commits; last commit 2026-09-26 "Stage 14.12: exposure-audit remediation close-out") |
| Donor oracle | `rmholston420/tektos-ultima@8274f60b3dd5f7d37c793ccb8c5b2d6800cfbf01` (2026-09-25) — `src/tektos/runtime/sdk.py` (2,607 lines); donor `main@43cb0ef` has `main.py` deleted |
| Executor | Hermes Agent on Colossus (`hermes chat`), repo at `/home/rmholston/dev/kosmos-lms`, venv `/home/rmholston/dev/kosmos-lms/.venv` |
| Author | Perplexity Computer, from a full read of the eight source documents and a multi-pass audit of the repository (static + executable reproduction in a clean Python 3.12.13 venv) |
| Governing user decisions (2026-09-28, 08:36 EDT) | (1) Full migration to a desktop-class Workbench (Tauri 2 + React) planned as concrete stages. (2) Workbench mechanisms: PostgreSQL journal, CloudEvents from day one. (3) Security containment immediately after the freeze stage. (4) Delivery: this file in the repo on `feat/tektos-autonomous-runtime`, as a PR. |
| Governing user decisions (2026-09-28, 10:26 EDT) | (5) **The Architecture Report (`kosmos-lms_architecture-v1`) outranks the Workbench specification** wherever they conflict; the Workbench spec fills in mechanisms the report leaves open. (6) **Coding backend: OpenHands primary, Tektos-native fallback** behind one `CodingWorkerPort` contract under Tekton. (7) **Sequencing: the report's Phases 1–8 order, with P0 containment first.** (8) **Epimeleia drives hermes-agent through its API server (HTTP + SSE)** on loopback. |

> **Read this first.** This document is the single execution contract for the Kosmos architecture program. It is standalone: every step names the exact files, commands, tests, exit gates, commit messages, and log/ADR obligations. The eight source documents are vendored beside it under `docs/implementation/sources/`; where they disagree, §0.3 says which one wins. Nothing here is speculative about the repository: every "current state" claim in §1 was verified against `7e7b1e3` by reading the file or running the command shown. The governing rule of the whole program, from the Architecture Report: **LLMs investigate, interpret, plan, critique, and propose; deterministic systems authorize, execute, verify, persist, and promote consequential work.**

---

## Table of contents

- §0 Operating contract for Hermes (rules, invariants, precedence, session ritual, environment, branch/PR discipline, stop conditions)
- §1 Verified baseline at `7e7b1e3` (evidence table; what Stage 14.x already fixed; new findings)
- §2 Target architecture — the Architecture Report mapped onto the repository (nomenclature, VSM functions, Koinon/Syndesmos/Mesiteia, eleven subsystems, taxonomy, runtime allocation, ports, storage, events, policy, state, evidence, isolation, client, layout, data ownership, extension placement)
- §3 Stage 15 — the execution plan (15.0 → 15.15 in the report's phase order, each with steps, tests, exit gate, commits, logs/ADR)
- §4 Cross-cutting contracts (runtime profiles, env catalogue, event catalogue, error envelope, Aisthesis metrics, test taxonomy, PR series, kill switches, definition of done)
- Appendix A — Hermes start prompt and per-session brief template
- Appendix B — ADR queue (ADR-147 … ADR-166) with one-paragraph decisions
- Appendix C — Mapping tables (report phases → stages; v1.0 stages → v2.0 stages; nomenclature crosswalk; aggregates → modules/tables/events; donor name flips)
- Appendix D — Command cheat-sheet and verification recipes
- Appendix E — Baseline reproduction log (numbers, commands, dates, external versions)
- Appendix F — Change log v1.0 → v2.0

---

## §0 Operating contract for Hermes

### 0.1 Non-negotiables (inherited from the repository and the user's skills)

1. **Never modify `tektos-ultima`.** It is a read-only oracle. Create a read-only worktree once: `git -C /home/rmholston/dev/tektos-ultima-v1 worktree add --detach /home/rmholston/dev/tektos-donor-8274f60 8274f60b3dd5f7d37c793ccb8c5b2d6800cfbf01 && chmod -R a-w /home/rmholston/dev/tektos-donor-8274f60`. (If the local donor checkout lives elsewhere, `find ~ -maxdepth 3 -type d -name 'tektos-ultima*'` first; never guess paths.) The same rule applies to every other donor checkout (`~/dev/forge-oh`, OpenHands-Ext, Rigpa-LMS): read, never write.
2. **Vendor before hand-build** (`kosmos-port-workflow`): inspect donor code and permissively licensed OSS before writing new code; log every port in `PORTING_LEDGER.md` **before** the first commit (source URL, commit SHA/tag, SPDX license, Kosmos location, port(s), modifications, ADR, `Logged:` timestamp). Refuse GPL/AGPL/BUSL/SSPL code without an explicit user override + ADR. External **binaries** invoked as tools (OPA, Bubblewrap, Postgres, `hermes`, `opa`) are not vendored code; record them under an "External tools" section of the ledger with version + license.
3. **ADR-007 events-only cross-plugin coupling.** No plugin imports another plugin; no extension adapter imports a plugin; Koinon never imports plugins or extensions. Cross-cutting needs go through a formal port (`koinon.contracts.ports.*`) or the event bus. `scripts/check_plugin_isolation.py` must stay green and is extended in Stage 15.3 for the new layout (`tests/architecture/`).
4. **Zero-trust memory writes.** Every `MemoryPort`/`RelationalMemoryPort`/`JournalPort` write carries `provenance` and `confidence`; retrieved memory is never treated as instruction.
5. **Four logs** (`kosmos-log-maintenance`): `BUILD_LOG.md` append-only, one entry per completed step, header `## YYYY-MM-DD HH:MM EDT — <summary>` (America/Detroit; `EST` after the November clock change); `DEBUG_LOG.md` append-only and **searched first** (`grep -in "<symptom>" DEBUG_LOG.md`) before any diagnosis; `KNOWN_ISSUES.md` editable open list; `SESSION_HANDOFF.md` overwritten at the end of every session and **read at the start of every session**.
6. **ADR discipline** (`kosmos-adr-authoring`, `kosmos-spec-diff`): structural decisions get an ADR **before** the code; use the template in Appendix B; add the row to `docs/adrs/README.md`; keep §17 of `docs/Kosmos-Build-Spec-v26.md` and the ADR file in agreement; never bump the spec version (v26 stays; the Architecture Report and the Workbench spec are adopted as sibling authoritative documents by ADR-147). Amend ratified ADRs only with a `> **STATUS AMENDMENT (YYYY-MM-DD):**` block at the top.
7. **Python environment** (`colossus-python-env`): never `pip install` on the system interpreter (PEP 668); confirm the venv path with `find` before `source …/bin/activate`; never guess. Interactive command blocks in this document deliberately avoid `set -euo pipefail`; gate scripts committed to `scripts/` may use it. OpenHands SDK packages are installed into the **Kosmos** venv (they are a Kosmos dependency behind an extra), never into the hermes-agent venv; hermes-agent keeps its own venv (`/home/rmholston/.hermes/hermes-agent/venv`).
8. **No second stacks.** One LLM port (`LLMPort` + the existing adapters, governed by Noesis), one event bus port (Mesiteia), one sandbox port, one tool registry (the governed `TektosToolRegistry`, which becomes the Koinon tool registry), one journal (Mneme). New capability extends the existing seam rather than adding a parallel implementation.
9. **No `shell=True`, no `sudo`, no `/` as a filesystem root** anywhere on a network-reachable or model-reachable path (the only permitted `sudo` is the pre-existing NOPASSWD `nvidia-smi -pl` thermal power-cap in `kernel/tektos_thermal_watchdog.py`, which moves to Poros).
10. **Tests are the contract.** No step is done until its listed tests pass locally with the repo's default `pytest` invocation and CI is green on the PR.

### 0.2 Architectural invariants (from the Architecture Report; each has a test or a policy that enforces it)

| # | Invariant | Enforced by (stage) |
|---|---|---|
| I-1 | Agents do not own authoritative state | Kybernesis owns workflow state in Mneme; agent runtimes hold only projections (15.5, 15.6, 15.10) |
| I-2 | Agents do not grant themselves capabilities | Asphaleia Capability Broker issues tokens only from Kybernesis/Telos decisions; Rego denies self-issuance (15.7) |
| I-3 | Agents do not accept their own output | Tekton Quality Gate + Euthyna + Kybernesis Acceptance Gate; the producing run id may never appear as the accepting subject (15.12) |
| I-4 | Producers are not their sole auditors | Euthyna runs in a separate process and environment with its own telemetry (15.12) |
| I-5 | Policy cannot be silently weakened | Protected paths + signed constitution + Integrity Tripwire + Telos change-control workflow (15.7) |
| I-6 | Sema must operate even when LLM inference is unavailable | Sema components are deterministic; conformance test boots with the LLM backend unreachable (15.6) |
| I-7 | Agora is nonbinding | Agora outputs are `proposal` artifacts; no Agora event can trigger a Kybernesis transition (15.11) |
| I-8 | Synedrion is advisory | Council resolutions are `advice` artifacts consumed only by workflows that also require a Gate decision (15.11) |
| I-9 | Poros recommends; Kybernesis authorizes | Poros emits `recommendation` events; only the Kybernesis Resource Controller writes leases (15.9) |
| I-10 | Noesis owns models; Epimeleia owns agents | Model assignment is a Noesis decision; agent lifecycle is Epimeleia; neither imports the other (15.9, 15.10) |
| I-11 | Tekton governs software work; OpenHands is an implementation backend | OpenHands runs inside the Kosmos sandbox under a Tekton task; it cannot commit to protected branches or run gates (15.12) |
| I-12 | Skills have no ambient authority | Skill Resolver attaches capability tokens per run; a skill file grants nothing (15.10) |
| I-13 | Tools require explicit capabilities | Koinon tool registry PEP checks the token before every invocation (15.7) |
| I-14 | Agent-created tools, hooks, skills, and policies enter quarantine | Plugin/extension registry `trust_state=quarantined` until the promotion workflow completes (15.4, 15.10) |
| I-15 | Accepted artifacts require immutable identity | Artifact service: content digest + commit SHA + signature; accepted versions immutable (15.5) |
| I-16 | Self-improvement follows proposal → controlled experiment → independent verification → authorized promotion | `self_improvement.yaml` workflow; `SelfRepairProposer.apply()` stays unimplemented until Stage 16 (15.6, Stage 16) |

### 0.3 Source documents and precedence

The program brings the repository into conformity with the eight source documents, in this order of authority:

| Rank | Document (vendored path under `docs/implementation/sources/`) | Role in this plan |
|---|---|---|
| 1 | `kosmos-lms_architecture-v1.md` (**Kosmos-LMS Architecture Report**; converted from the user's RTF) | **Authoritative architecture**: governing rule, nomenclature (VSM functions, layers, subsystems, Koinon domains), authority boundaries, agent taxonomy, runtime allocation (Hermes via Epimeleia; OpenHands via Tekton; deterministic mechanisms), extension layout, placement principles, roadmap phases, non-negotiable invariants. |
| 2 | `Kosmos-Agent-Workbench-Unified-Architecture-and-Implementation-Specification.md` | **Mechanisms where rank 1 is silent**: aggregates, orthogonal state model, claims/evidence ladder E0–E6, CloudEvents, PostgreSQL journal + outbox, OPA/Rego policy, A0–A4 tiers (as Telos capability ceilings), isolation ladder, Tauri 2 + React client, API/AG-UI. Its `src/kosmos/` layout and its VSM names are **superseded** by rank 1. |
| 3 | `Hermes-Implementation-Plan-Restore-Tektos-Autonomy-in-Kosmos-LMS.md` | Near-term **mechanics** (blockers, packaging/CI fixes, model/tool protocol, worktrees, controller limits, verification ladder, benchmark corpus, working rules). Its Tektos-native worker loop becomes the **fallback** Coding Worker (decision 6); its phase order is replaced by the report's (decision 7). |
| 4 | `Kosmos-LMS-Gap-Audit-Revision-4d230b8.md`, `Kosmos-LMS-Full-Multi-Pass-Repository-Audit.md` | **P0 containment and hygiene** items and the release-gate criteria (three consecutive green `main` runs, ≥70 % production coverage, ≥85 % on critical modules). |
| 5 | `Implementation-Blueprint-for-a-Cybernetic-Autonomous-Coding-System.md` | Kernel internals detail (retry taxonomy, TLA+ invariants, state machine) where ranks 1–2 are silent. Its PySide6/QML client is superseded. |
| 6 | `cybernetic-architecture-for-autonomous-coding-agents.md` | Theory (VSM recursion, requisite variety, essential variables, `regulate(mission_id)` sketch) — informs the Kybernesis Operations Controller. |
| 7 | `A-Cybernetic-GUI-UX-for-an-Autonomous-Vibe-Coding-Agent.md` | UX doctrine (Viability Cockpit, now–meaning–next cards, causal timeline, perspectives, 12 design rules). Its VSM names (Energeia/Syndesmos/Kratos/Elechos/Phronesis/Nomos/Algedon) are **replaced** by the report's (Praxis/Harmonia/Kybernesis/Euthyna/Pronoia/Telos/Sema) in every artifact of this program. |

**Precedence rule (formal).**

1. The Architecture Report (rank 1) wins every conflict about **what the system is and how it is named and bounded**.
2. The Workbench specification (rank 2) wins about **how a mechanism works** when rank 1 does not specify it, and never overrides a rank-1 name, boundary, or invariant.
3. The Hermes plan (rank 3) wins about **mechanics of a step** unless that would violate ranks 1–2 or a rank-4 P0 item.
4. Audit P0 items (rank 4) outrank the report's phase order for one stage only — hence Stage 15.1 (containment) precedes Phase 1.
5. Where all documents are silent, follow the repository's ratified ADRs; where a ratified Kosmos ADR contradicts rank 1, **author the superseding ADR first**, then change code (`kosmos-spec-diff` stop condition).

**Resolved conflicts (binding for this program).**

| Conflict | Resolution |
|---|---|
| Nomenclature: repo/UX/Workbench names (Tektos, Nomos, Phronesis, Kratos, Elechos, Syndesmos-as-S2, Energeia, Algedon) vs report names | **Report names everywhere** from Stage 15.0: S1 **Praxis** (category), S2 **Harmonia**, S3 **Kybernesis**, S3\* **Euthyna**, S4 **Pronoia**, S5 **Telos**, algedonic **Sema**; layers **Koinon** ⊃ **Syndesmos** ⊃ **Mesiteia**; subsystems **Zetesis, Synedrion, Gnosis, Poros, Epimeleia, Tekton, Axiomeon, Holon, Agora, Asphaleia, Noesis**; Koinon domains **Mneme, Aisthesis**, workflow engine, artifact service, provenance service. Crosswalk in Appendix C.3. |
| Repo `plugins/praxis` (constitution loader + apex change-approval engine) collides with the report's **Praxis = S1 operations category** | The package is **renamed and split**: constitution loader/signing/verifier → `koinon/src/koinon/policy/constitution/` (Telos mechanism); apex approval engine/tiers/tokens → `koinon/src/koinon/kernel/kybernesis/apex/` (Kybernesis Acceptance/Change-Control mechanism). "Praxis" is never again a package name; it denotes the S1 category in docs and in `ComponentKind` metadata. |
| Repo `plugins/tektos` (donor runtime) vs report **Tekton** wrapping **OpenHands** | `plugins/tektos` → `plugins/tekton` (Stage 15.3). Tekton = governance + planning + gates; Coding Workers are adapters behind `CodingWorkerPort`: **OpenHands primary** (`extensions/adapters/openhands/`), **Tektos-native fallback** (the donor LLM↔tool loop, `extensions/adapters/tektos_native/`). Selection: `KOSMOS_CODING_WORKER=openhands|tektos-native` (default `openhands` once 15.12 passes its gate; `tektos-native` until then). |
| Repo `plugins/phrouros` (anomaly detectors) | Detectors are **Sema Anomaly Detector / Integrity Tripwire** components → `koinon/src/koinon/kernel/sema/detectors/` (Stage 15.3 move, 15.6 wiring). "Phrouros" survives only in ADR history. |
| Layout: Workbench `src/kosmos/{domain,application,kernel,…}` vs report `koinon/src/koinon/…` + `plugins/<subsystem>` + `skills/shared` + `policies/…` + `extensions/adapters/…` + `tests/{architecture,integration,policy,conformance}` | **Report layout** (§2.16). Workbench packages map into it: `domain`+`application` → `koinon.contracts` + `koinon.kernel.kybernesis`; `workflow` → `koinon.workflows`; `workers` → `plugins/tekton` + `extensions/adapters/{openhands,tektos_native}`; `assurance` → `koinon.kernel.euthyna` + `koinon.kernel.sema`; `release` → `plugins/tekton/release` (Release/Rollback Services) + Kybernesis Promotion Gate; `knowledge` → `plugins/gnosis`, `plugins/zetesis`, `koinon.mneme`; `projections` → `koinon.kernel.kybernesis.projections` + `koinon.mesiteia.streams.agui`; `api` → `koinon.mesiteia.api`; `ports` → `koinon.contracts.ports`. |
| Sequencing: Hermes plan / v1.0 autonomy-first vs report Phases 1–8 | **Report order** (decision 7): 15.0 freeze → 15.1 containment (P0) → 15.2 packaging/CI → Phase 1 Koinon core (15.3–15.6) → Phase 2 Asphaleia (15.7) → Phase 3 Syndesmos & Mesiteia (15.8) → Phase 4 Poros & Noesis (15.9) → Phase 5 Epimeleia (15.10) → Phase 6 Zetesis/Gnosis/Synedrion/Agora (15.11) → Phase 7 Tekton & Euthyna (15.12) → client (15.13, parallel from 15.8) → deployment (15.14) → retirement/closure (15.15) → Phase 8 higher-order intelligence (Stage 16). |
| Cognitive runtime: Tektos-native model loop for planning/research vs report **Hermes via Epimeleia** | Hermes is the cognitive backend for research, planning, interpretation, critique, synthesis, negotiation, open-ended tool use, Synedrion delegates, Agora participants, red-team, troubleshooting — driven through hermes-agent's **API server** (decision 8): `POST /v1/runs`, `GET /v1/runs/{id}/events` (SSE), `POST /v1/runs/{id}/stop`, `POST /v1/runs/{id}/approval`, bearer `API_SERVER_KEY`, loopback `127.0.0.1:8642`. Kosmos keeps identity, permissions, lifecycle, state, resources, termination. |
| Mission store: SQLite vs PostgreSQL journal + outbox | **PostgreSQL (Mneme) is authoritative** (schema `mn_*`, Stage 15.5); SQLite only as the *test/portable profile* adapter of the same `JournalPort`. |
| Event envelope: current `EventEnvelope` vs CloudEvents | **CloudEvents 1.0 from day one** (Stage 15.5); `type = io.kosmos.<aggregate>.<event>.v1`; legacy `tektos.*`/`immune.*` types valid until Stage 15.15. |
| Workflow state: flat status vs orthogonal Lifecycle/Control/Phase/Task | **Orthogonal states** stored; `status_summary` derived. Kybernesis owns them (I-1). |
| Policy: hand-coded allow/block lists vs OPA/Rego PDP | **OPA/Rego PDP** with the report's `policies/{constitution,capabilities,protected-paths,model-use,exceptions}` tree (Stage 15.7); in-process mirror for `test` profile with differential fixtures. |
| Capability model: leases vs `CapabilityGrant` + A0–A4 | `CapabilityGrant` (Asphaleia Capability Broker) with **capability tokens** per run; A0–A4 are **Telos capability ceilings**; "lease" is used only for Harmonia/Poros resource leases. |
| Client: Next.js shell vs Tauri 2 + React vs PySide6 | **Tauri 2 + React/TypeScript** (`apps/desktop`, `apps/workbench-ui`; Stage 15.13). The report is silent on clients, so the Workbench choice stands. Next.js `ui/` retired in 15.15. |
| Python: 3.12 vs 3.13+ | Keep `requires-python >= 3.12`; 3.13 in the CI matrix from 15.2; floor raised in 15.15 only after Colossus proof (OpenHands SDK supports 3.12+, CI default 3.13). |
| Verification: Hermes ladder vs E0–E6 | The ladder **produces evidence tiers**; Euthyna clean-room re-run = E3; pinned environment = E4; property/adversarial = E5; human-witnessed = E6. Acceptance of consequential work needs ≥E3 (Kybernesis Acceptance Gate). |

### 0.4 Session ritual

Start of every Hermes session:

```bash
cd /home/rmholston/dev/kosmos-lms
git status --short | head -20 && git log --oneline -3
cat SESSION_HANDOFF.md
sed -n 1,80p KNOWN_ISSUES.md
# the stage you are on:
grep -n "^### Stage 15\." docs/Kosmos-Build-Sequence-v26.md | tail -5
```

Then load the four skills in this order when relevant: `kosmos-log-maintenance` (always), `kosmos-port-workflow` (before code), `kosmos-adr-authoring` (before decisions), `kosmos-spec-diff` (before spec/ledger/ADR edits). The same four skills are vendored in `.perplexity/skills/` in the repo.

End of every session: append the BUILD_LOG entries for each completed step (one per step), then **overwrite** `SESSION_HANDOFF.md` with the template in `templates/SESSION_HANDOFF.md`, with "Exact next action" being one command or one sentence.

### 0.5 Environment pre-flight (run once per session, before any Python)

```bash
echo "VIRTUAL_ENV=$VIRTUAL_ENV"; which python; which pip
find ~ -maxdepth 5 -name activate -path "*/bin/activate" 2>/dev/null | grep -E "kosmos-lms|hermes|forge-oh"
# expected: /home/rmholston/dev/kosmos-lms/.venv/bin/activate  (matches ops/systemd/kosmos-kernel.service ExecStart)
source /home/rmholston/dev/kosmos-lms/.venv/bin/activate
python --version   # 3.12.x or 3.13.x acceptable; if the venv is missing: python3.12 -m venv .venv  (or python3 if >= 3.12)
pip install -e ".[dev,ui,postgres]" -q
python -c "import kernel.app" 2>&1 | tail -1   # until Stage 15.3; afterwards: python -c "import koinon.kernel.app"
```

If any of `pip`, `python`, `pytest` fails with PEP 668 or "command not found", stop and apply the recovery recipe in the `colossus-python-env` skill; do not retry with `sudo` or `--break-system-packages`. The hermes-agent venv is separate: `which hermes || ls /home/rmholston/.hermes/hermes-agent/venv/bin/hermes` — never `pip install` Kosmos packages into it.

### 0.6 Branch, commit, PR discipline

- Program branch prefix: `feat/arch-15-<n>-<slug>` (one branch per stage; e.g. `feat/arch-15-1-containment`). Each stage merges to `main` via a PR that is **green in CI** before the next stage starts (exceptions are listed per stage). The first PR of the program is this document on `feat/tektos-autonomous-runtime` (PR #1).
- Baseline tag before any code: `git tag -a baseline-before-koinon-2026-09-28 7e7b1e3 -m "Baseline audited by the architecture conformity plan v2.0" && git push origin baseline-before-koinon-2026-09-28`.
- Commit message convention (matches repository history): `<type>(<area>): Stage 15.<n> — <summary>` where `<type>` ∈ `feat|fix|refactor|docs|test|ci|chore|build|deploy` and `<area>` ∈ `koinon|kernel|contracts|mneme|aisthesis|workflows|policy|capabilities|tools|hooks|artifacts|mesiteia|kybernesis|harmonia|sema|telos|euthyna|asphaleia|poros|noesis|epimeleia|tekton|zetesis|gnosis|synedrion|agora|axiomeon|holon|extensions|hermes|openhands|vllm|mcp|a2a|api|ui|ui-contracts|desktop|deploy|opa|ops|security|eval|bench|recovery|conformance|architecture|layout|config|adr|ledger|log`. Example: `feat(tools): Stage 15.7 — worktree isolation + process supervisor (ADR-157)`.
- Every stage's PR description lists: ADR(s), BUILD_LOG entry timestamps, tests added, exit-gate evidence (paste the command output), and the rollback command.
- Mechanical changes (formatting, import rewrites, renames) go in their **own commits** so behavioral diffs remain reviewable.
- Feature gate: everything new behind `KOSMOS_TEKTON_AUTONOMY=off|on` (default `off`) until Stage 15.12's gate passes; the legacy `/api/tektos/turn`, `/api/prompt/sse` keep working throughout.

### 0.7 Global stop conditions (halt the stage, log to KNOWN_ISSUES.md, ask the user)

1. A donor or OSS component needed for a step has a non-permissive license.
2. A step would require a new formal port that no ADR covers (the six new ports of §2.8 are covered by ADR-152…ADR-162).
3. A ratified ADR must be reversed to proceed (author the superseding ADR first; if the reversal is user-flagged, ask).
4. Any change would remove a Definition of Done from an in-progress stage.
5. The Colossus envelope (128 GB RAM / 32 GB VRAM) would be exceeded by a design choice (e.g., gVisor + a second model resident; OpenHands DockerWorkspace + vLLM + llama.cpp resident together).
6. A live-model gate (Stage 15.12) fails three consecutive runs for the same root cause after applying the DEBUG_LOG fix.
7. Data-loss risk: a migration touches `ledger_events`/`narratives` or any `data/*.db` without a tested backup/restore (Stage 15.6 drill) — stop.
8. CI cannot be made green for reasons outside the repository (runner outage) — record and continue locally, but do not merge.
9. **Invariant breach by design**: a step would let an agent accept its own output, issue its own capability, edit a protected path without the Telos workflow, or make Sema depend on model inference (I-1…I-16) — stop and redesign.
10. hermes-agent or the OpenHands SDK changes its integration surface (API server endpoints, `Conversation` API) between plan and implementation — record the drift in DEBUG_LOG, pin the working version, continue; do not silently upgrade.

---
## §1 Verified baseline at `7e7b1e3`

Method: full clone; static reads of every file named below; executable reproduction in a fresh `python3.12 -m venv` with `pip install -e ".[dev,ui]"` (ruff 0.16.9, mypy 2.3.1, pytest 9.1.1, pytest-asyncio 1.4.0, bandit 1.9.4, fastapi 0.141.1, uvicorn 0.54.0); `npm ci` in `ui/` (Node 20.20.1); GitHub Actions history via `gh run list`. Full numbers in Appendix E. Line numbers refer to `7e7b1e3`.

### 1.1 Repository shape

| Metric | Value at `7e7b1e3` |
|---|---|
| Tracked files / Python files | 1,043 / 660 |
| Packages (`__init__.py` dirs, excl. tests/vendor/ui) | 120 (122 incl. two test packages) |
| `kernel/app.py` | **10,180 lines, 185 route decorators** (102 GET · 80 POST/PUT/PATCH/DELETE · 3 WebSocket), FastAPI title "Kosmos Kernel" version `6.12.0`, single `_KosmosCSPMiddleware`, **no authentication, RBAC, CSRF or rate-limit middleware** |
| Formal ports (`ports/*.py`) | 24 modules incl. `event_envelope.py` (LLM, EventBus, Memory, RelationalMemory, Vector, Embeddings, Search, Secrets, Observability, Data, Resource, Notification, FrontendContract, Approval (gateway+resolver), MCP, Immune, LoopSafety, Thermal, Sandbox, Session, TraceFeed, Voice, Vision) |
| Adapter implementations | 33 (`adapters/<port>/<impl>`) |
| Plugins | `praxis` (constitution + apex approval tiers), `phrouros` (anomaly detectors), `zetesis` (research), `tektos` (23 sub-packages) |
| ADRs | 148 files, highest **ADR-146** → the next number is **ADR-147** |
| Specs | `docs/Kosmos-Build-Spec-v26.md`, `docs/Kosmos-Build-Sequence-v26.md` (v25 archived under `docs/archive/`), `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md`, `PORTING_LEDGER.md` (root) + `docs/PORTING_LEDGER.md` (duplicate to reconcile) |
| Logs | `BUILD_LOG.md` 887 KB (6,190+ lines), `DEBUG_LOG.md` 100 KB, `KNOWN_ISSUES.md` (10 open items, oldest 2026-07-30), `SESSION_HANDOFF.md` **stale (2026-09-13, Stage 8.6)** |
| UI | Next.js 16.2.11 static export (`output: 'export'`), React 19.2.4, Tailwind 4, TanStack Query, Zustand, xterm, cytoscape/three; 18 pages; 28 Playwright specs |
| Ops | `ops/systemd/{kosmos-kernel,kosmos-hindsight}.service`, `ops/compose/memory.yml`, `ops/benchmarks/adr_010/…` |
| Tests | 106 collectable files under `tests/` (878 tests) + 1 file that cannot be collected (B-10) + 119 co-located files under `ports/adapters/kernel/plugins/ops` (1,811 tests) ≈ **2,689 tests** |

### 1.2 Findings table (claim → verified → evidence → fixed in)

Legend: **P0** stop-ship · **P1** blocks a trustworthy vertical slice · **P2** hygiene/debt. "Source" = which document raised it (H = Hermes plan, G = Gap audit, M = Multi-pass audit, N = new in this audit).

| ID | Pri | Finding | Source | Verified at `7e7b1e3` | Evidence | Fixed in |
|---|---|---|---|---|---|---|
| B-01 | P0 | `POST /api/tools/{tool_name}/execute` executes tools through the donor `kernel/tool_registry.py::ToolRegistry.execute()` → `plugins/tektos/tools/sandbox_provider.py::SandboxProvider` with `subprocess.run(shell=True)`, `cwd=/` by default, and an automatic `sudo -n` retry; unauthenticated | G, M | **Yes** | `kernel/app.py:7704-7712`; boot `kernel/app.py:2551-2557` (`SandboxProvider()` + `ToolRegistry(...)` + `register_donor_builtins`); `sandbox_provider.py:43` (`FS_ROOT = Path(os.getenv("TEKTOS_FS_ROOT", "/"))`), `:139`, `:155-158` (`sudo -n`, `shell=True`); bandit HIGH B602 ×2 | 15.1 |
| B-02 | P0 | `WS /ws/pty` forks the operator's login shell (`$SHELL -l`) for any WebSocket client; no auth, no Origin check | G, M | **Yes** | `kernel/app.py:9841-9866` (`pty.fork()`, `execvp(shell, [shell, "-l"])`) | 15.1 |
| B-03 | P0 | **The governed sandbox is never booted.** `_BootRegistry` has no `sandbox` slot and `kernel/app.py` has no `_boot_sandbox`; `TektosTurnLoop`, executor and orchestrator receive `sandbox=getattr(registry, "sandbox", None)` → always `None`. `TektosToolRegistry` (SandboxPort + detectors + approvals, ADR-093/094) is constructed **only in tests**. Result: the only live tool-execution path is the ungoverned donor path in B-01 | **N** | **Yes** | `rg -c '_boot_sandbox\|registry\.sandbox\s*=' kernel/app.py` → 0; `rg -l 'TektosToolRegistry(' --glob '!*test*'` → 0 files; `kernel/app.py:1316`, `:1509`, `:1618` | 15.1 (boot) → 15.7 (isolation) |
| B-04 | P0 | No autonomous loop: `TektosTurnLoop.run_turn(*, agent_id, prompt, tool_calls=None, …)` takes **caller-supplied** tool calls and calls the model exactly once (`llm.generate`, not `chat` with tools); `TektosAgent.run()` is a separate one-shot `generate_text` path | H | **Yes** | `plugins/tektos/runtime/turn_loop.py:184-193`, `:296-301`; `plugins/tektos/agent.py:133-172` | 15.9 (tool protocol), 15.12 (Tekton workers) |
| B-05 | P0 | `LLMPort.chat()` is typed `messages: list[dict[str, str]]`; no `tools`/`tool_choice`; no adapter forwards a tools schema; nothing parses `tool_calls` | H | **Yes** | `ports/llm.py:57-66`; `adapters/llm/{llama_swap,ollama,failover}/adapter.py` `chat()` payloads contain only `model/messages/stream` (+`options`) | 15.9 |
| B-06 | P1 | Packaging: `[tool.setuptools] packages` is a **static list of 52** entries; a built wheel omits **68 of 120** packages, including `kernel` itself, `adapters.relational_memory.*`, `adapters.sandbox.*`, `adapters.session.*`, `adapters.immune.*`, `plugins.tektos.{runtime,tools,executor,planner,…}`, `plugins.zetesis` | H, M | **Yes** (reproduced: `python -m build --wheel`; 52 packages in wheel) | `pyproject.toml:[tool.setuptools]`; Appendix E.4 | 15.2 |
| B-07 | P1 | CI runs `pytest tests/` only (878 tests) while `testpaths = ["ports","adapters","kernel","plugins","ops"]` (1,811 tests) — the two never overlap; `python-tests` `needs: [python-lint]` so it is **skipped** whenever lint fails; `summary` job `if: always()` never fails; `frontend-lint` runs `npm run lint` which **does not exist** in `ui/package.json`; lint scope excludes `adapters/` and `plugins/` | H, M | **Yes** | `.github/workflows/ci.yml` (jobs `python-tests`, `frontend-lint`, `summary`); `ui/package.json:scripts` = dev/build/start/test:e2e | 15.2 |
| B-08 | P1 | **All observed GitHub Actions runs fail.** Last 12 runs (2026-09-26/27) = failure. At `7e7b1e3`: `Python Lint` ✗, `Python Type Check` ✗, `Frontend Lint` ✗, `Frontend E2E` ✗, `Python Tests` skipped, `CI Summary` ✓ | H, M | **Yes** | `gh run list --repo rmholston420/kosmos-lms --limit 12`; `gh run view <latest> --json jobs` | 15.2 |
| B-09 | P1 | Event bus boots `ValkeyEventBusAdapter()` unconditionally (default `redis://127.0.0.1:6379/0`); no in-memory adapter is selectable although `InMemoryStreamClient` already exists in the same module; in a clean environment 17 `tests/kernel/*` tests fail with `ConnectionRefusedError … 6379`, and 8 more are unmarked live-service tests (Ollama LLM/embeddings `:11434`, vision `:8094`, whisper/edge-tts, Postgres) that can never pass in CI | H | **Yes** (reproduced: `tests/` → 850 passed / 25 failed / 3 skipped; 34 tracebacks cite `127.0.0.1:6379`) | `kernel/app.py:637-642`; `adapters/event_bus/valkey/adapter.py:37,72-125` | 15.2 |
| B-10 | P1 | `tests/kernel/test_adr141_s133_axioms_routes.py` copies from `~/dev/kosmos-lms/plugins/tektos/axioms` at import time → collection error everywhere except a machine with that exact path | H | **Yes** | `tests/kernel/test_adr141_s133_axioms_routes.py:37-39` | 15.2 |
| B-11 | P1 | FastAPI/Uvicorn live in the `ui` optional extra while `kernel/app.py` imports FastAPI at module import; CI installs `.[dev]` and only works because `fastapi` arrives transitively | H | **Yes** | `pyproject.toml:[project.optional-dependencies].ui` | 15.2 |
| B-12 | P1 | Undeclared runtime imports: `aiohttp` (`kernel/mcp_client.py`), `PIL`+`pytesseract` (`adapters/vision/tesseract/adapter.py`), `edge_tts`, `numpy`, `pydub` (`kernel/voice.py`), `faster_whisper`, `mcp` (`plugins/zetesis/research/mcp_search_server.py`), `open_deep_research`, `openai` (`plugins/zetesis/research/*`), `openhands_ext` (`kernel/learning/engine.py`) | M (aiohttp), N (rest) | **Yes** | AST scan (Appendix E.5) | 15.2 |
| B-13 | P1 | `diskcache 5.6.3` — PYSEC-2026-2447 (pickle deserialization) used by the repo-map cache | M | **Yes** (`pip-audit`) | `plugins/tektos/repomap/{indexer,tags}.py` (`from diskcache import Cache`) | 15.2 |
| B-14 | P1 | Next.js 16.2.11 **critical** advisory + `postcss`/`sharp` high; fix available = `next@16.3.6`; both `package-lock.json` and `pnpm-lock.yaml` are tracked; `tsc --noEmit` fails on `ui/tests/03-tektos-plan-workflow.spec.ts(20,61)` | M | **Yes** (`npm audit`: 1 critical, 2 high) | `ui/package.json`, `ui/package-lock.json`, `ui/pnpm-lock.yaml` | 15.2 |
| B-15 | P1 | Documentation contradiction: `README.md` opens with "PROGRAM COMPLETE (2026-09-26) — absorption frozen" and still says "Current status: **Stage 0 complete** … Stage 1 … is next" and "Repo layout (Stage 0.1)"; `SESSION_HANDOFF.md` is from 2026-09-13 Stage 8.6 and points at `/home/user/workspace/audit/kosmos-lms` | H, G | **Yes** | `README.md:3-15,31,33`; `SESSION_HANDOFF.md:1-4,36` | 15.0 |
| B-16 | P1 | Tracked SQLite sidecars despite `.gitignore` rules: `data/memory.db-shm`, `data/memory.db-wal`, `data/tektos_rag.db-shm`, `data/tektos_rag.db-wal`; tests also create `data/tektos_rag.db` and `data/tektos_skills.db` inside the repo tree | H, M | **Yes** | `git ls-files data/` | 15.2 |
| B-17 | P1 | systemd: `ExecStartPre` waits for DozerDB on `:7687` although the unit's own comment says the kernel has had no DozerDB dependency since ADR-102; `ops/systemd/README.md` documents `/etc/kosmos/kernel.env` while the unit reads `ops/systemd/kosmos-kernel.local.env`; `ops/systemd/kosmos-kernel.env` ships a plaintext dev password | H, M | **Yes** | `ops/systemd/kosmos-kernel.service:19-21,29-30`; `ops/systemd/README.md:7-27`; `ops/systemd/kosmos-kernel.env:8` | 15.14 |
| B-18 | P1 | Ruff (0.16.9, repo config): **1,114** findings repo-wide (753 auto-fixable) / **369** in the CI scope; `ruff format --check`: 403 files repo-wide / 118 in CI scope would be reformatted; mypy `ports/ kernel/`: **86 errors in 28 files** | H (918/358 with an older ruff), M (86) | **Yes** | Appendix E.2–E.3 | 15.2 (ratchet), 15.15 (zero) |
| B-19 | P1 | Bandit: 209 findings (3 HIGH = the `shell=True` sites: `sandbox_provider.py:139,158`, `adapters/sandbox/tektos/vendor/sandbox_exec_donor.py:160`; 42 × B608 SQL string building) | M | **Yes** | Appendix E.6 | 15.1 (HIGH→0), 15.15 (B608) |
| B-20 | P1 | Coding tools operate on the **real** repository checkout (`cwd` = registry root / `TEKTOS_FS_ROOT`); no per-mission worktree, no path policy, no checkpoints | H, G | **Yes** | `plugins/tektos/tools/builtin.py:182-195`, `sandbox_provider.py:143` | 15.7 |
| B-21 | P2 | Tektos engines are honest scaffolds: executor emits `# TODO: Implement …` modules and `assert True` tests (donor-verbatim, ADR-107 D2); `SelfRepairProposer.apply()`/self-improvement apply raise `NotImplementedError` (ADR-090 deferred); Phrouros `ModelSwapSloDetector`, `StubDegradationDetector`, `BusFactor1Detector` are skeletons; `LangfuseTraceFeedAdapter` is a stub; 54 `raise NotImplementedError` sites outside tests/vendor; 467 broad `except Exception`; 72 `return {"error": …}` at HTTP 200 in `kernel/app.py` | G, M | **Yes** | `plugins/tektos/executor/engine.py:158-195`; `plugins/tektos/self_repair/proposer.py:249-259`; `plugins/phrouros/detectors/__init__.py:7-12`; `ports/trace_feed.py:219` | 15.6–15.12, 15.15 |
| B-22 | P2 | Two tool registries coexist: donor `kernel/tool_registry.py::ToolRegistry` (sync `execute`, wired) and governed `plugins/tektos/tools/registry.py::TektosToolRegistry` (async `invoke`, SandboxPort, detectors, approvals — unwired) | G, N | **Yes** | see B-03 | 15.1 → 15.15 (delete donor registry) |
| B-23 | P2 | `kernel/app.py` monolith with the composition root (`_BootRegistry`, 45 `_boot_*` closures inside `lifespan`) and all routes in one module; router extraction never happened | G, M | **Yes** | `kernel/app.py:214,561-2200,2832` | 15.8, 15.15 |
| B-24 | P2 | Missing repository security posture: no `SECURITY.md`, no Dependabot, no CodeQL, no `.pre-commit-config.yaml` | G, M | **Yes** | `ls SECURITY.md .github/dependabot.yml .pre-commit-config.yaml` → absent | 15.2, 15.12 |
| B-25 | P2 | No `AGENTS.md`, no `plugins/tektos/AGENTS.md`, no `docs/implementation/` | H | **Yes** | `ls` | 15.0 |
| B-26 | P2 | `docs/PORTING_LEDGER.md` duplicates the root `PORTING_LEDGER.md` (drift risk); `research_6_3_7b.md` (37 KB) at repo root | N | **Yes** | `ls` | 15.0 |

### 1.3 What Stage 14.x already did (do not redo)

- Donor `main.py` (154 routes) fully re-hosted on the kernel (ADR-141: 154 P / 0 D / 0 T) and the `:8020` gateway deleted (ADR-144); Tektos-Ultima GUI surfaced in the shell sidebar (Stage 14.11); `/ws/pty` restored (Stage 14.9 — this is what B-02 must now contain).
- Kernel-native status endpoints (ADR-117 … ADR-139), byte-verbatim donor substrates (`kernel/axioms.py`, `kernel/metabolism.py`, `kernel/rag_retriever.py`, `kernel/repo_map_generator.py`, `kernel/tool_registry.py`, `kernel/mcp_client.py`, voice/vision).
- PostgreSQL substrate exists and is the natural home for the Mneme journal: `adapters/relational_memory/postgres/` (asyncpg pool, `pgvector`, Alembic `001_initial` creating `ledger_events` — provenance/confidence-checked, uuid7 — and `narratives` with HNSW cosine index, `pg_trgm`, generated tsvector).
- Spec v26 + ADRs 077–102 are **locked by ADR-145**. This program does not reopen them; it adds the Architecture Report (rank 1) and the Workbench specification (rank 2) as sibling authoritative documents via ADR-147 and supersedes individual decisions with new ADRs where §0.3 requires.

### 1.4 Reproduced test status (clean Python 3.12.13 venv, no Valkey/Postgres/Ollama)

| Scope | Result |
|---|---|
| Default `pytest` (testpaths ports/adapters/kernel/plugins/ops) | **1,788 passed · 2 failed · 21 skipped** (failures: `adapters/relational_memory/postgres/test_contract.py::test_is_healthy_without_pool`; `plugins/tektos/tests/test_stage_3_12_exit_gate.py::…3_12_dod` — needs `.venv/bin/ruff`, pre-existing per `KNOWN_ISSUES.md` 2026-09-10) |
| `pytest tests/` (what CI runs) | **1 collection error** (B-10) and, with that file ignored, **850 passed · 25 failed · 3 skipped** — 17 are Valkey `ConnectionRefusedError` from kernel boot (`tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py` ×9, `test_stage_14_12_tektos_plan_surface.py` ×4, `test_stage_6_5_4_websocket_event_bus_bridge.py` ×3, `test_stage_6_5_1_2_phrouros_and_seed.py` ×1); 8 are unmarked live-service tests (`test_adr141_s1312_voice_routes.py` ×3, `test_adr141_t7_embedder_surface.py` ×2, `test_adr141_t8b3_llm_probe.py`, `test_adr141_s137_metabolism_routes.py`, `test_stage_8_0_relational_memory_wiring.py::test_postgres_with_dsn_degrades_gracefully…`) |


---

## §2 Target architecture — the Architecture Report mapped onto the repository

Kosmos-LMS remains the primary system. Its deterministic core becomes **Koinon**; its formal ports become the **Syndesmos** contracts; its transports become **Mesiteia**; the VSM functions govern how those mechanisms are used; the eleven capability subsystems are plugins; Hermes (via Epimeleia) and OpenHands (via Tekton) are runtime backends behind adapters. Everything below is a mapping from the report's concepts to **existing** Kosmos code (keep / move / extend) or to **new** modules (built in the target layout from birth).

### 2.1 Governing rule and the three dimensions

- **Governing rule.** LLMs investigate, interpret, plan, critique, and propose. Deterministic systems authorize, execute, verify, persist, and promote consequential work. Every component in this program is classified against this rule (§2.6) before it is written.
- **Dimension 1 — VSM functions** (roles, not layers; recursive at every level): Praxis (S1), Harmonia (S2), Kybernesis (S3), Euthyna (S3\*), Pronoia (S4), Telos (S5), Sema (algedonic channel). §2.3.
- **Dimension 2 — Technical architecture**: Koinon (common substrate) ⊃ Syndesmos (integration layer: contracts, schemas, discovery, adapter contracts) ⊃ Mesiteia (middleware: transports, brokers, gateways). §2.4.
- **Dimension 3 — Capability subsystems**: Zetesis, Synedrion, Gnosis, Poros, Epimeleia, Tekton, Axiomeon, Holon, Agora, Asphaleia, Noesis, each a plugin under `plugins/<name>/` with Koinon-provided mechanisms and its own domain semantics. §2.5.
- **Recursion.** Every operational subsystem (Zetesis, Tekton, Holon, Gnosis, Axiomeon) contains its own local planning, execution, tool use, coordination, budgeting/lifecycle, verification, audit hooks, observation, policy interpretation, and Sema escalation — provided as Koinon mechanisms, instantiated per plugin (`koinon.kernel.<function>.local` helpers), governed by the central functions.

### 2.2 Canonical nomenclature (binding for code, docs, events, UI labels)

| Canonical name | Kind | Replaces (v1.0 / UX doc / Workbench / repo) | Home after Stage 15.3 / Step B |
|---|---|---|---|
| **Praxis** | S1 — *category* of operational systems | Energeia; "workers" | not a package; `ComponentKind.vsm = "praxis"` on S1 components inside plugins |
| **Harmonia** | S2 — coordination | Syndesmos-as-S2; parts of Kratos | `koinon/src/koinon/kernel/harmonia/` |
| **Kybernesis** | S3 — operational control | Kratos; MissionRegulator; `plugins/praxis/apex` (approvals) | `koinon/src/koinon/kernel/kybernesis/` |
| **Euthyna** | S3\* — audit & assurance | Elechos; `assurance/` | `koinon/src/koinon/kernel/euthyna/` (+ clean-room workers in `plugins/tekton/euthyna_workers/`) |
| **Pronoia** | S4 — intelligence & foresight | Phronesis | `koinon/src/koinon/kernel/pronoia/` (deterministic synthesis workflows); agents as Epimeleia manifests |
| **Telos** | S5 — identity & policy | Nomos; `plugins/praxis/constitution`; `governance/` | `koinon/src/koinon/policy/` + `policies/constitution/` |
| **Sema** | algedonic channel | Algedon; `NotificationPort.deliver_algedonic`; `plugins/phrouros`; `adapters/immune` | `koinon/src/koinon/kernel/sema/` |
| **Koinon** | common substrate | "kernel" (as a layer); `src/kosmos/{kernel,domain,application,…}` | `koinon/src/koinon/` |
| **Syndesmos** | integration layer | `ports/`, `schemas/`, `ui-contracts/` | `koinon/src/koinon/contracts/` (+ generated `ui-contracts/`) |
| **Mesiteia** | middleware | `adapters/event_bus`, `kernel/app.py` routes, `adapters/mcp`, AG-UI SSE | `koinon/src/koinon/mesiteia/` (+ `extensions/adapters/{mcp,a2a}`) |
| **Mneme** | memory & persistence | `ports/{memory,relational_memory,vector,embeddings}`, journal | `koinon/src/koinon/mneme/` |
| **Aisthesis** | observability | `ports/{observability,trace_feed}`, telemetry modules | `koinon/src/koinon/aisthesis/` |
| **Zetesis** | deep research | `plugins/zetesis` (kept) | `plugins/zetesis/` |
| **Synedrion** | advisory council | (none; donor Rigpa-LMS `plugins/magi`) | `plugins/synedrion/` |
| **Gnosis** | knowledge management | `/api/gnosis/*` kernel routes, `ui/app/gnosis`; donors Rigpa-LMS `plugins/knowsys`, Gnosis-KB | `plugins/gnosis/` |
| **Poros** | resources & metabolism | `ports/{resource,thermal}`, `kernel/metabolism.py`, `kernel/tektos_thermal_watchdog.py`, `kernel/inference_engine.py` telemetry | `plugins/poros/` |
| **Epimeleia** | agent lifecycle | `ports/session`, `plugins/tektos/manager`, `kernel/skills`, `kernel/context_curator.py`, `plugins/tektos/orchestrator` | `plugins/epimeleia/` + `extensions/adapters/hermes/` |
| **Tekton** | autonomous software engineering | `plugins/tektos` (planner, decomposer, openspec, executor, repomap, tools, eval, self_repair, …) | `plugins/tekton/` + `extensions/adapters/{openhands,tektos_native}` |
| **Axiomeon** | axiom engineering | `kernel/axioms.py`, `plugins/tektos/axioms` | `plugins/axiomeon/` |
| **Holon** | ontologies & theories | (none) | `plugins/holon/` (Stage 16) |
| **Agora** | nonbinding A2A forum (replaces "Ekklesia" — no such code exists in the repo) | (none) | `plugins/agora/` + `extensions/adapters/a2a/` |
| **Asphaleia** | security, identity, capabilities | `ports/secrets` + `adapters/secrets/age_file`, `kernel/csp.py`, operator auth (15.1), `plugins/praxis/apex/tokens.py` | `plugins/asphaleia/` (semantics) + `koinon/src/koinon/capabilities/` (enforcement) |
| **Noesis** | models & inference | `kernel/routing.py`, `ports/llm` + `adapters/llm/*`, `ports/embeddings`, `kernel/inference_engine.py` | `plugins/noesis/` + `extensions/adapters/{llamacpp,ollama,vllm}` |

Rules: (a) a canonical name is never reused for a different concept; (b) event types, metrics, table prefixes, UI labels and log fields use canonical names (`io.kosmos.tekton.*`, `kosmos_kybernesis_*`, `mn_*` tables); (c) legacy names remain only in ADR history, `docs/archive/`, and one-release deprecation shims.

### 2.3 VSM functions ↔ Kosmos components

| Function | What it owns (report) | Existing Kosmos code (keep / move) | New in this program (stage) |
|---|---|---|---|
| **Praxis (S1)** — operational systems: Zetesis, Tekton, Holon, Gnosis, Axiomeon (future Hygieia) | Doing the work inside bounded capabilities | `plugins/zetesis`, `plugins/tektos/*` (→ Tekton), `kernel/axioms.py` | Each plugin gains a local `praxis/` package with Local Planner Function, Executor Worker, Tool Gateway, Local Coordinator, Budget Controller, Local Verifier, Audit Hook, Telemetry Emitter, Policy Interpreter Function, Sema Escalator — instantiated from Koinon helpers (15.4 helpers; 15.11/15.12 use) |
| **Harmonia (S2)** — dependency tracking, leases, concurrency limits, backpressure, dedup, deadlock/oscillation detection; **does not** set priorities, approve, or promote | Coordination between S1 units | `ports/loop_safety.py` + `adapters/loop_safety/tektos` (repetition/oscillation), `ports/resource.py` allocations (leases) | `koinon.kernel.harmonia`: `LeaseRegistry` (files, ports, GPU slots, branches), `ConcurrencyController`, `BackpressureMonitor`, `DeduplicationService`, `DeadlockDetector`, `OscillationDetector` (wraps loop-safety) (15.6) |
| **Kybernesis (S3)** — authoritative workflow state, contracts, prioritization, resource-bargain approval, acceptance criteria, artifact promotion, deployment authorization, rollback, incidents | Operational control | `plugins/tektos/manager` (S3 Manager engine, ADR-108), `plugins/praxis/apex` (approval tiers/engine/tokens → `kybernesis/apex`), `kernel/plan_tracker.py` | `OperationsController` (the `regulate(workflow_id)` driver), `WorkflowLifecycleController`, `PortfolioWorkflow`, `ResourceController` (writes leases from Poros recommendations), `AcceptanceGate`, `PromotionGate`, `ChangeControlWorkflow`, `IncidentWorkflow`, `RecoveryCoordinator`, `RollbackService`, `CommitmentRegistry`, `OperationalStateProjector` (15.6; used by 15.12) |
| **Euthyna (S3\*)** — clean-room builds/tests, evidence validation, provenance verification, security review, red-team, drift/regression detection, random inspection | Independent audit | `plugins/phrouros/detectors/{bus_factor_1,model_swap_slo,stub_degradation}` (audit-type detectors), `plugins/zetesis/research/{claim_support,url_verify}` (patterns) | `koinon.kernel.euthyna`: `EvidenceValidationService`, `ProvenanceVerificationService`, `AuditLedger` (tamper-evident), `RandomInspectionWorkflow`, `DriftDetector`, `RegressionDetector`; `plugins/tekton/euthyna_workers/CleanRoomBuildWorker` in a separate process/environment; Red-Team Agent as Epimeleia manifest (15.12) |
| **Pronoia (S4)** — environmental scanning, strategic research, technology scouting, scenario planning, systems architecture, threat modeling, opportunity detection, strategic critique, alternative generation, experiment design, strategic synthesis; **cannot deploy** | Intelligence & foresight | `plugins/tektos/planner`, `plugins/tektos/decomposer`, `plugins/tektos/openspec`, `plugins/tektos/repomap`, `kernel/repo_map_generator.py`, `kernel/rag_retriever.py`, `kernel/tektos_hindsight.py` | Pronoia agents as Epimeleia manifests (Hermes): `EnvironmentalScanningAgent`, `StrategicResearchAgent` (delegates to Zetesis), `TechnologyScoutingAgent`, `ScenarioPlanningAgent`, `SystemsArchitectureAgent`, `ThreatModelingAgent`, `OpportunityDetectionAgent`, `StrategicCriticAgent`, `AlternativeGenerationAgent`, `ExperimentDesignAgent`; deterministic `StrategicSynthesisWorkflow` in `koinon.kernel.pronoia` (15.10 manifests; Stage 16 full) |
| **Telos (S5)** — constitution, identity, values, policy hierarchy, capability ceilings, human authorization, amendment workflow, exceptions, S3–S4 arbitration | Identity & policy | `plugins/praxis/constitution/{loader,signing,verifier}` (signed constitution), `governance/constitution/`, `plugins/tektos/axioms` (values corpus) | `koinon.policy`: `ConstitutionLoader`, `SignatureVerifier`, `PolicyHierarchyService`, `CapabilityCeilingRegistry` (A0–A4), `HumanAuthorizationWorkflow`, `AmendmentWorkflow`, `ExceptionRegistry`, `ArbitrationWorkflow`; `policies/{constitution,capabilities,protected-paths,model-use,exceptions}` Rego + data (15.7). **Authority chain**: Human → signed constitutional artifacts → deterministic policy engine (OPA) → bounded interpretation functions → authorization workflow → capability enforcement. |
| **Sema** — algedonic channel; **must function without LLM inference** | Threshold Monitor, Integrity Tripwire, Anomaly Detector, Severity Classifier, Circuit Breaker, Escalation Router, Incident Snapshotter, Recovery Monitor, Alert Deduplicator, tamper-evident Sema Ledger | `ports/notification.py` (`AlgedonicTier`, `deliver_algedonic`), `adapters/notification/kernel`, `/api/algedonic` WS, `AlgedonicBanner.tsx`, `ports/immune.py` + `adapters/immune/tektos` (12 detectors), `plugins/phrouros/detectors/{loop,unauthorized_tool}`, `plugins/tektos/tools/detectors`, `kernel/tektos_thermal_watchdog.py` (thermal tripwire) | `koinon.kernel.sema`: the ten components above as deterministic classes; triggers: credential exposure, sandbox escape, gate/policy tampering, unauthorized self-modification, corrupted provenance, data-loss risk, runaway resources, security compromise, perishable opportunity (15.6). |

### 2.4 Technical architecture: Koinon, Syndesmos, Mesiteia, and the Koinon domains

**Koinon owns** (report list → package):

| Koinon responsibility | Package | Existing code moved there (Stage 15.3) |
|---|---|---|
| Kernel & lifecycle (boot, composition root, plugin lifecycle) | `koinon/src/koinon/kernel/` (`boot.py`, `app.py` until 15.15) | `kernel/app.py`, `kernel/session_state.py`, `kernel/db_manager.py`, `kernel/schema_evolution*.py` |
| Contracts & schemas (commands, events, artifacts, capabilities, workflows) — **Syndesmos** | `koinon/src/koinon/contracts/` (`ports/`, `events/`, `commands/`, `schemas/`, `taxonomy.py`, `manifest.py`) | `ports/*.py` → `contracts/ports/`; `ports/event_envelope.py` → `contracts/events/envelope.py`; `ui/` type contracts → generated `ui-contracts/` |
| Durable workflows (engine, definitions, checkpoints, retries, compensation, human approvals) | `koinon/src/koinon/workflows/` | `kernel/plan_tracker.py` (pattern) |
| Event log, operational state, projections | `koinon/src/koinon/mneme/journal/` + `koinon/src/koinon/kernel/kybernesis/projections/` | `adapters/relational_memory/postgres` (pool, Alembic) |
| Artifact service + provenance service | `koinon/src/koinon/artifacts/` | `adapters/data/blobs` (content-addressed `BlobStore`), `adapters/data/filesystem` |
| Plugin registry (manifests, trust states, capability declarations) | `koinon/src/koinon/kernel/registry.py` | `_BootRegistry` (`kernel/app.py:214`) |
| Configuration; secret **interfaces** | `koinon/src/koinon/kernel/config.py`; `koinon/src/koinon/contracts/ports/secrets.py` | `kernel/profiles.py` (15.2), `ports/secrets.py` |
| Identity & capability **enforcement** | `koinon/src/koinon/capabilities/` (token verification, PEP hooks) | `plugins/praxis/apex/tokens.py` (signing pattern), operator auth (15.1) |
| Sandbox provisioning; tool registry; hooks | `koinon/src/koinon/tools/` (`registry.py`, `sandbox/`, `builtin/`), `koinon/src/koinon/hooks/` | `plugins/tektos/tools/{registry,builtin,builtin_defs,filesystem}.py`, `adapters/sandbox/{tektos,noop}`, `kernel/tool_registry.py` (donor; deleted 15.15), `kernel/hooks.py` |
| Observability — **Aisthesis** | `koinon/src/koinon/aisthesis/` | `ports/observability.py`, `ports/trace_feed.py`, `adapters/observability/otel_stack`, `kernel/tektos_telemetry.py`, `kernel/tektos_replay.py` |
| Runtime adapters (interfaces to Hermes, OpenHands, vLLM, MCP, A2A) | **contracts** in `koinon/src/koinon/contracts/ports/{agent_runtime,coding_worker,llm,mcp}.py`; **implementations** in `extensions/adapters/{hermes,openhands,tektos_native,vllm,llamacpp,ollama,mcp,a2a}/` | `adapters/llm/*`, `adapters/mcp/*`, `kernel/mcp_client.py` |
| Sema transport | `koinon/src/koinon/kernel/sema/transport/` | `ports/notification.py`, `adapters/notification/kernel` |
| Memory — **Mneme** | `koinon/src/koinon/mneme/` | `ports/{memory,relational_memory,vector,embeddings}.py`, `adapters/{memory/dozerdb,relational_memory/*,vector/qdrant,embeddings/*}`, `kernel/rag_retriever.py`, `kernel/tektos_data_services.py` |
| Integration — **Syndesmos**; middleware — **Mesiteia** | `koinon/src/koinon/contracts/` ; `koinon/src/koinon/mesiteia/` (`event_bus/`, `gateway/` (FastAPI routers, error envelope, health, AG-UI SSE, inference gateway), `discovery.py`, `routing.py`, `correlation.py`, `ratelimit.py`) | `adapters/event_bus/valkey`, `kernel/app.py` routes (extracted progressively), `adapters/frontend_contract/kernel`, `kernel/tektos_prompt_sse.py` |

**Koinon domain contracts.**

- **Mneme** memory types → stores: working memory (in-process, per run, `koinon.mneme.working`); episodic (journal `mn_event_journal` + `SessionPort` turns); semantic (Gnosis-owned knowledge in Postgres + Qdrant via `VectorPort`, `pgvector` narratives); procedural (skills/workflow definitions under `skills/shared` and `workflows/` — Git is canonical); operational (Kybernesis projections `mn_*` aggregate tables); audit (Euthyna `AuditLedger` and Sema `SemaLedger`, append-only, hash-chained); provenance (`mn_provenance` edges from the provenance service); resource telemetry (Poros time-series in Postgres/Prometheus); constitutional records (Telos, signed files under `policies/constitution/versions/` + `mn_constitution_versions`). **Not every database is Gnosis** (data-ownership table §2.17).
- **Aisthesis** collects logs, metrics, traces, agent trajectories, tool invocations, inference telemetry, workflow transitions, resource usage, verification outcomes, incidents, policy decisions; it **observes**, Poros accounts, Euthyna audits, Kybernesis controls, Sema escalates, Gnosis learns. Implementation: OTel (existing `otel_stack` adapter), Prometheus `/metrics`, structured JSON logs with `correlation_id`, trajectory capture as artifacts.
- **Workflow engine** (`koinon.workflows`): durable, idempotent commands, checkpointing, resumption, timeouts, cancellation, retry policies, compensation, versioning, human approvals, event-driven continuation, restart recovery, typed inputs/outputs. Agents never replace state machines; a Hermes/OpenHands run is one **activity** inside a workflow step.
- **Artifact service** (`koinon.artifacts`): content-addressed storage, immutable accepted versions, hashes, signatures, schema typing, producer + workflow identity, lineage, promotion stages (`candidate → verified → accepted → released → retired`), retention, access control, reproduction metadata.
- **Provenance service** (`koinon.artifacts.provenance`): `derived_from`, `produced_by (run_id, model_assignment, tool_invocation)`, `verified_by (euthyna_run)`, `authorized_by (decision_id)` edges; queried by Euthyna and by the client's Proof perspective.

### 2.5 Capability subsystems ↔ existing code, donors, new work

| Subsystem | Role (report) | Existing Kosmos code | Donors (read-only; ledger before use) | New components (report names) | Stage |
|---|---|---|---|---|---|
| **Zetesis** | Deep research: question framing, planning, source acquisition, extraction, claim decomposition, verification, synthesis, evidence capture, provenance | `plugins/zetesis/research/{odr,search_backend,claim_support,cove,url_verify,rubric_critique,self_consistency,structural_finalize,license_grounding,feature_grounding,mcp_search_server}.py`, `adapters/search/searxng`, stubs under `plugins/zetesis/adapters` | Rigpa-LMS `plugins/gnosis` (LangGraph SCOPE→SEARCH→SYNTHESIZE→VALIDATE→CRITIQUE→DELIVER pipeline — **note the name flip**, Appendix C.5), `open_deep_research` | Rename/classify: `QuestionFramingFunction`, `ResearchPlanningAgent`, `SourceAcquisitionWorkers`, `ExtractionFunctions`, `ClaimDecompositionFunction`, `VerificationWorkers` (url_verify, cove, self_consistency), `CitationVerificationGate` (url_verify + claim_support as a Gate), `SynthesisAgent`, `CritiqueAgent` (rubric_critique), `EvidenceCaptureService`, `ResearchProvenanceService` | 15.11 |
| **Synedrion** | Advisory multi-model council: role assignment, perspective generation, cross-examination, disagreement mapping, calibrated confidence, minority report, deliberation records; **not binding** | none | Rigpa-LMS `plugins/magi` (fan-out to three councillors, `InputSanitizer`/`CouncillorSandbox`, arrival-order-invariant resolution UNANIMOUS/MAJORITY/WEIGHTED/FIRST_HIGH_CONFIDENCE/ARBITER, SSE route); `axiom` council | `CouncilProtocolWorkflow`, `RoleAssignmentFunction`, `PerspectiveGenerationAgents` (Hermes via Epimeleia), `CrossExaminationWorkflow`, `DisagreementMappingFunction`, `ConfidenceCalibrationFunction`, `MinorityReportService`, `DeliberationRecordService` → `advice` artifacts | 15.11 |
| **Gnosis** | Knowledge management: ingestion, curation, ontology alignment (with Holon), embeddings, retrieval, freshness/staleness, contradiction, provenance, lifecycle, knowledge-quality metrics | `kernel/app.py` `/api/gnosis/{query,corpora,stats}` (50 mentions), `ui/app/gnosis/*`, `kernel/rag_retriever.py`, `scripts/{ingest_humanities,ingest_superpowers,docling_ingest}.py`, `adapters/vector/qdrant`, `adapters/embeddings/*` | Rigpa-LMS `plugins/knowsys` (notes, vault, retrieval, Qdrant, Kuzu graph, MCP), Gnosis-KB | `IngestionWorkflow`, `CurationFunctions`, `OntologyAlignmentService` (Holon-facing), `EmbeddingService` (Noesis-assigned models), `RetrievalService`, `FreshnessMonitor`, `ContradictionDetector`, `KnowledgeProvenanceService`, `KnowledgeLifecycleController`, `KnowledgeQualityMetrics` | 15.11 |
| **Poros** | Resources: CPU/GPU/VRAM/RAM/disk/network telemetry, thermal, power, token budgets, model residency planning, workspace quotas, scheduling recommendations, cost accounting, capacity forecasting, leases | `ports/resource.py` + `adapters/resource/sqlite` (priority queue/allocations), `ports/thermal.py` + `adapters/thermal/tektos`, `kernel/tektos_thermal_watchdog.py` (NOPASSWD `nvidia-smi -pl`), `kernel/metabolism.py`, `kernel/inference_engine.py` (GPU/VRAM probes) | Forge-OH GPU telemetry & inference-health adapters | `ResourceTelemetryMonitor`, `ThermalMonitor`, `BudgetAccountingService`, `ModelResidencyPlannerFunction`, `WorkspaceQuotaService`, `SchedulingRecommendationFunction`, `CostAccountingService`, `CapacityForecastFunction`, `LeaseRecommendationService` — **Poros measures and recommends; Kybernesis authorizes; Harmonia coordinates access; Sema escalates** | 15.9 |
| **Epimeleia** | Agent lifecycle: manifests, factory, Hermes Runtime Adapter, Capability Broker, Context Assembler, Skill/Toolset Resolver, Model Assignment Client, Session Registry, Lifecycle Controller, Checkpoint Manager, Recovery Workflow, Termination Controller, Result Normalizer, Telemetry Emitter | `ports/session.py` + `adapters/session/{inmemory,tektos}`, `plugins/tektos/manager` (S3 manager → parts to Kybernesis, agent supervision to Epimeleia), `plugins/tektos/orchestrator` (multi-agent), `kernel/skills/{registry,executor,manager}.py`, `kernel/context_curator.py`, `kernel/learning/engine.py` (`~/.hermes/skills` dir already referenced) | hermes-agent API server docs; Forge-OH run/approval/event-timeline BFF patterns | `AgentManifestRegistry`, `AgentFactory`, `HermesRuntimeAdapter` (`extensions/adapters/hermes`), `CapabilityBroker` (Asphaleia-issued tokens), `ContextAssembler`, `SkillResolver`, `ToolsetResolver`, `ModelAssignmentClient` (→ Noesis), `SessionRegistry`, `AgentLifecycleController`, `CheckpointManager`, `AgentRecoveryWorkflow`, `TerminationController`, `ResultNormalizer`, `AgentTelemetryEmitter`; **Hermes is the cognitive backend; Kosmos keeps identity, permissions, lifecycle, state, resources, termination** | 15.10 |
| **Tekton** | Autonomous software engineering; **wraps OpenHands** for repository-level work with governance outside it | `plugins/tektos/{planner,decomposer,openspec,executor,repomap,tools,eval,self_repair,self_improve,ingest,synthesis,reflection,experience,memory,renderer,ui}`, `plugins/tektos/runtime/turn_loop.py`, `plugins/tektos/agent.py`, `kernel/evaluation_framework.py` (already delegates SWE-bench to OpenHands) | OpenHands Software Agent SDK (`openhands-sdk`, `openhands-tools`; MIT — verify `LICENSE` at the pinned tag), OpenHands-Ext v1 (SDK pins/patches, DockerWorkspace vs LocalWorkspace, StuckDetector near-identical patch), Forge-OH (BFF over OpenHands: runs, workspaces, approvals, event timelines) | `SpecificationAnalysisFunction`, `ClarificationAgent`, `RepositoryCartographyService` (repomap), `ArchitecturePlanningAgent`, `TaskDecompositionFunction`, **`OpenHandsAdapter`** (primary `CodingWorkerPort` adapter), `TektosNativeCodingWorker` (fallback adapter), `TestDesignAgent`, `TestWorker`, `StaticAnalysisWorker`, `CodeReviewAgent`, `SecurityReviewAgent`, `PerformanceReviewAgent`, `DocumentationAgent`, `QualityGate`, `CleanRoomBuildWorker` (Euthyna), `ScopeAuditFunction`, `IntegrationWorkflow`, `PromotionWorkflow`, `ReleaseService`, `RollbackService`. **Non-bypassable chain**: candidate commit → protected Quality Gate → format/lint → types → tests → architecture/security rules → clean-room build/test → Euthyna review when required → Kybernesis accepts/rejects. | 15.12 |
| **Axiomeon** | Axiom engineering: candidate extraction, formalization, consistency checking, dependency mapping, counterexample search, minimality analysis, cross-domain mapping, revision proposals, provenance | `kernel/axioms.py`, `plugins/tektos/axioms` (ADR-141 S13.3 routes), `scripts/gen_constitution_genesis.py` | — | `AxiomCandidateExtractionAgent`, `FormalizationFunction`, `ConsistencyCheckWorker`, `DependencyMappingService`, `CounterexampleSearchAgent`, `MinimalityAnalysisFunction`, `CrossDomainMappingAgent`, `RevisionProposalWorkflow`, `AxiomProvenanceService`; flow **Axiomeon proposes → Pronoia models → Synedrion critiques → Euthyna verifies → Telos accepts** | 15.3 (move), Stage 16 |
| **Holon** | Ontologies & theories (incl. GUToE): ontology registry, concept graph, relation typing, theory versioning, formal constraints, cross-ontology mapping, explanatory-coherence scoring, falsifiability tracking, Pluralism Guard | none (Rigpa-LMS `rigpa-v0.1` GUTOE bridge material as reading) | — | `OntologyRegistry`, `ConceptGraphService`, `RelationTypingFunction`, `TheoryVersioningService`, `FormalConstraintChecker`, `CrossOntologyMappingAgent`, `ExplanatoryCoherenceScoringFunction`, `FalsifiabilityTracker`, `PluralismGuard` (Gate) | Stage 16 |
| **Agora** | Nonbinding A2A forum: registry, sessions, proposal board, critique threads, consensus monitor (nonbinding), moderation hook, record | none ("Ekklesia" does not exist in the repo) | `a2a-sdk` (Apache-2.0, v1.1.5, JSON-RPC/HTTP+JSON/gRPC) | `AgoraRegistry`, `AgoraSessionWorkflow`, `ProposalBoardService`, `CritiqueThreadService`, `ConsensusMonitor` (nonbinding), `ModerationHook`, `AgoraRecordService`; transport `extensions/adapters/a2a` (Mesiteia) | 15.8 (transport), 15.11 (forum) |
| **Asphaleia** | Security: identity, authn, capability tokens, secrets brokerage, sandbox policy, network policy, protected paths, audit logging, supply-chain checks, vulnerability response, trust boundaries; **narrow explicit capabilities, not ambient authority** | `ports/secrets.py` + `adapters/secrets/age_file`, `kernel/csp.py` (`_KosmosCSPMiddleware`), operator mode/token (15.1), `plugins/praxis/apex/tokens.py`, bandit/pip-audit gates (15.2) | OPA v1.21.0 (Apache-2.0), Bubblewrap (LGPL-2.1, binary), gitleaks (MIT), cyclonedx-py (Apache-2.0) | `IdentityService`, `AuthenticationService`, `CapabilityTokenService`, `SecretsBroker`, `SandboxPolicyService`, `NetworkPolicyService`, `ProtectedPathRegistry`, `AuditLoggingService`, `SupplyChainCheckWorker`, `VulnerabilityResponseWorkflow`, `TrustBoundaryRegistry` | 15.1 (lite), 15.7 |
| **Noesis** | Models: model registry, quantization registry, provider adapters, vLLM/local backend adapters, routing policy, fallback chains, context-window policy, sampling profiles, tool-calling compatibility, health checks, load balancing, benchmark profiles, cost/latency accounting, model provenance, deprecation | `kernel/routing.py` (model router), `ports/llm.py` + `adapters/llm/{llama_swap,ollama,failover}`, `ports/embeddings.py` + `adapters/embeddings/{llama,ollama}`, `kernel/inference_engine.py`, `ports/{vision,voice}` adapters | vLLM (Apache-2.0; OpenAI-compatible server), llama.cpp `llama-server`, Ollama; `local-llm-bench` skill for benchmark profiles; OpenHands-Ext ADR-0017 topology (Qwen3-Coder-30B-A3B AWQ on vLLM for coding, Qwen3.6-35B-A3B on llama.cpp for planning, Qwen3-Embedding-4B on CPU) as the first registry content | `ModelRegistry`, `QuantizationRegistry`, `ProviderAdapters`, `RoutingPolicyFunction`, `FallbackChainService`, `ContextWindowPolicy`, `SamplingProfileRegistry`, `ToolCallingCompatibilityService` (the `LLMPort` tools protocol + `AssistantTurn` normalizer), `ModelHealthMonitor`, `LoadBalancer`, `BenchmarkProfileRegistry`, `CostLatencyAccounting`, `ModelProvenanceService`, `DeprecationController`; `extensions/adapters/vllm` new. **Inference chain**: Epimeleia requests → Noesis selects → Poros grants → Asphaleia validates → Mesiteia routes → Aisthesis records. | 15.9 |

### 2.6 Agent taxonomy, classification registry, and naming rule

| Kind (suffix) | Definition (report) | Deterministic? | May call `LLMPort`? |
|---|---|---|---|
| `Agent` | LLM-driven; chooses actions dynamically | no | yes (via Epimeleia only) |
| `Function` | one bounded LLM judgment, typed input/output, no autonomy | no | yes (single call, schema-validated output) |
| `Workflow` | durable deterministic state machine coordinating steps | yes | never (steps may invoke Agents/Functions as activities) |
| `Controller` | deterministic authority over a resource or lifecycle | yes | never |
| `Service` | stateless/stateful capability with typed API | yes | never |
| `Tool` | bounded executable operation requiring capabilities | yes | never |
| `Worker` | executes a task under a controller | yes (may **host** an Agent, e.g. OpenHands) | only inside a hosted Agent run |
| `Monitor` | observes signals, emits events | yes | never |
| `Detector` | identifies conditions/anomalies | yes | never |
| `Gate` | deterministic pass/fail check | yes | never |
| `Registry` | authoritative catalogue | yes | never |
| `Hook` | typed response to an event | yes | never |
| `Adapter` | external system integration | yes | only if it *is* an inference adapter |

**Decision rule** (applied in every ADR and PR): fully deterministic → Tool/Service/Monitor/Gate/Worker/Workflow; needs one bounded judgment → Function; needs dynamic action choice → Agent (Hermes via Epimeleia, or OpenHands via Tekton for repository work); otherwise hybrid workflow with human decision points. **Mechanism**: `koinon.contracts.taxonomy.ComponentKind` enum + `@component(kind=…, subsystem=…, vsm=…)` decorator that registers metadata; `tests/architecture/test_component_classification.py` requires every public class under `koinon/src/koinon/kernel/{kybernesis,harmonia,sema,telos,euthyna,pronoia}`, `koinon/src/koinon/{workflows,policy,capabilities,tools,hooks,artifacts}` and `plugins/*/components/` to be classified; `tests/architecture/test_no_llm_in_deterministic_kinds.py` fails if a module whose components are all deterministic kinds imports `koinon.contracts.ports.llm` or the inference gateway client. Donor code gets a ratcheted allowlist (`tests/architecture/classification_allowlist.txt`, shrinks every stage, empty by 15.15).

### 2.7 Runtime allocation (who executes what)

| Runtime | Used for (report) | Kosmos adapter | Governance around it |
|---|---|---|---|
| **Hermes (hermes-agent) via Epimeleia** | research, planning, interpretation, critique, synthesis, negotiation, open-ended tool use, Synedrion delegates, Agora participants, red-team, troubleshooting, Pronoia agents | `extensions/adapters/hermes/HermesApiServerAdapter` implementing `AgentRuntimePort` against hermes-agent's API server (`hermes gateway`, `127.0.0.1:8642`, bearer key; `POST /v1/runs`, `GET /v1/runs/{id}/events` SSE, `POST /v1/runs/{id}/stop`, `POST /v1/runs/{id}/approval`, `GET /v1/runs/{id}`, `GET /health`, `GET /v1/capabilities`). Hermes' model provider is pointed at the **Kosmos inference gateway** (`http://127.0.0.1:8000/v1`, Mesiteia → Noesis) so model use is selected, metered and journaled by Kosmos; interim: the existing HA proxy `127.0.0.1:8093/v1`. | Epimeleia issues the capability token per run, assembles context, resolves skills/toolsets (Kosmos tools reach Hermes through the Kosmos MCP server scoped by the run token), owns the session record, terminates (`/stop`) on budget/Sema, normalizes results into artifacts; Hermes-side approvals are routed to Kybernesis decisions. |
| **OpenHands via Tekton** | repository navigation, code editing, refactoring, debugging, migration, test implementation, code/test iteration | `extensions/adapters/openhands/OpenHandsAdapter` implementing `CodingWorkerPort` with `openhands-sdk` + `openhands-tools` (matching pins): `LLM(model="openai/<noesis-model>", base_url=<gateway>, api_key=<run token>)`, `Agent(llm, tools=[Terminal, FileEditor, TaskTracker])`, `Conversation(agent, workspace=<mission worktree>, callbacks=[…], max_iteration_per_run=…)`; runs **inside the Kosmos sandbox** (separate process, `cwd` = worktree, loopback-only network, rlimits, `bwrap` in production) | Tekton owns task scoping, worktree, checkpoints (commits), Quality Gate, Euthyna hand-off, promotion; OpenHands never commits to protected branches, never runs gates, never sees secrets beyond the run token. Fallback `extensions/adapters/tektos_native/TektosNativeCodingWorker` (the donor's bounded LLM↔tool loop over Koinon tools) behind the same contract test. |
| **Custom deterministic** | policy evaluation, capability enforcement, secrets, authn, artifact storage, workflow durability, leases, scheduling, event routing, resource accounting, quality gates, test execution, promotion, rollback, audit storage, Sema, observability, model serving management, transport | `koinon.*`, `plugins/{asphaleia,poros,noesis}` deterministic components, `extensions/adapters/{vllm,llamacpp,ollama,mcp,a2a}` | Classified per §2.6; no `LLMPort` imports (architecture test). |

### 2.8 Ports: keep, extend, add

**Keep** all 24 existing port modules (moved to `koinon.contracts.ports`). **Extend** three: `LLMPort` (tools/tool_choice/response_format + streaming tool-call deltas — Stage 15.9, ADR-159), `SandboxPort` (`SandboxRequest.cwd`, `env_allowlist`, `tier`, `process_group`, `allowed_roots` — Stage 15.7, ADR-157), `EventEnvelope` (CloudEvents attributes — Stage 15.5, ADR-153). **Add six** formal ports, each with ≥2 adapters so the protocol-conformance test can swap them:

| New port | Protocol (keyword-only, async, `is_healthy()` non-throwing, `close()`) | Canonical adapter | Second adapter | Stage / ADR |
|---|---|---|---|---|
| `JournalPort` (Mneme) | `append(events, *, expected_version) -> int`, `read(*, workflow_id, after_seq, limit)`, `read_by_correlation`, `stream(*, after_seq)`, `snapshot_put/get`, `outbox_claim/ack/fail` | `PostgresJournalAdapter` (`mn_event_journal`, `mn_outbox`, `mn_snapshots`; append-only trigger; hash chain) | `SqliteJournalAdapter` (**test/portable only**) | 15.5 / ADR-152 |
| `ArtifactStorePort` (artifact service) | `put(bytes\|path, *, kind, workflow_id, media_type, producer) -> ArtifactRef(digest,size,stage)`, `get`, `verify`, `promote(digest, stage, decision_id)`, `link(artifact, provenance_edge)` | `FsArtifactStoreAdapter` over `BlobStore` + `mn_artifacts`/`mn_provenance` | `InMemoryArtifactStoreAdapter` | 15.5 / ADR-154 |
| `WorkflowPort` (workflow engine) | `start(definition_id, workflow_id, input)`, `signal(workflow_id, name, payload)`, `query(workflow_id) -> WorkflowState`, `tick(workflow_id) -> NextAction`, `cancel(workflow_id, reason)`, `approve(workflow_id, approval_id, decision)` | `LocalDurableWorkflowAdapter` (state derived from `JournalPort`) | `InMemoryWorkflowAdapter`; Temporal deferred to Stage 16 | 15.6 / ADR-155 |
| `PolicyPort` (Telos/Asphaleia PDP) | `decide(*, action, subject, resource, context) -> PolicyDecision(allow, tier_required, obligations, reasons, policy_digest)` | `OpaHttpPolicyAdapter` (OPA v1.21.0 sidecar) | `InProcessPolicyAdapter` (test profile; differential fixtures) | 15.7 / ADR-156 |
| `AgentRuntimePort` (Epimeleia) | `start_run(*, manifest, task, context, capability_token, model_assignment) -> RunHandle`, `events(run_id) -> AsyncIterator[AgentEvent]`, `status(run_id)`, `stop(run_id, reason)`, `resolve_approval(run_id, approval_id, decision)` | `HermesApiServerAdapter` | `ScriptedAgentRuntimeAdapter` (tests: replays recorded SSE fixtures) | 15.10 / ADR-160 |
| `CodingWorkerPort` (Tekton) | `run_task(*, task: CodingTask(worktree, brief, allowed_paths, budget, model_assignment, capability_token), sink) -> CodingResult(files_changed, self_report, transcript_ref, usage)`, `cancel(run_id)` | `OpenHandsAdapter` (primary) | `TektosNativeCodingWorker` (fallback); `ScriptedCodingWorker` (tests) | 15.12 / ADR-162 |

No other new ports. Kybernesis controllers, gates, Sema, Euthyna services, and projections are **Koinon modules** composed from these ports.

### 2.9 Storage — Mneme is the system of record

- **PostgreSQL** (target major **18**; 17 acceptable; verify `psql "$KOSMOS_POSTGRES_URI" -Atc "show server_version"`) holds the event journal, outbox, snapshots, Kybernesis projections, artifact/provenance metadata, audit ledgers, constitution version records. Extensions already used by ADR-102: `vector`, `pg_trgm`, `pgcrypto` (+ optional `pg_uuidv7`).
- One new Alembic environment `koinon/src/koinon/mneme/journal/postgres/migrations/` with `version_table="mn_alembic_version"` so ADR-102's `ledger_events`/`narratives` migrations stay untouched. All new tables prefixed `mn_`.
- **Append-only journal**: `mn_event_journal(seq bigserial PK, event_id uuid UNIQUE, type text, source text, subject text, workflow_id uuid, correlation_id uuid, causation_id uuid, occurred_at timestamptz, specversion text DEFAULT '1.0', datacontenttype text DEFAULT 'application/json', dataschema text, data jsonb NOT NULL, producer text NOT NULL, schema_version text NOT NULL, provenance jsonb NOT NULL, confidence real NOT NULL, hash bytea NOT NULL, prev_hash bytea)`; trigger `mn_event_journal_append_only BEFORE UPDATE OR DELETE … RAISE EXCEPTION`; hash chain `hash = sha256(prev_hash || rfc8785(canonical_event))` (`rfc8785` is already a dependency).
- **Transactional outbox**: `mn_outbox(id bigserial, seq bigint REFERENCES mn_event_journal(seq), destination text CHECK (destination IN ('bus','projection','webhook')), attempts int DEFAULT 0, next_attempt_at timestamptz, published_at timestamptz, last_error text)` written in the **same transaction** as the append; `OutboxRelay` publishes to `EventBusPort` (Valkey streams remain the live transport) and in-process projection subscribers; at-least-once; consumers dedupe on `event_id`.
- **Projections** (Kybernesis `OperationalStateProjector`; one table each, `version int`, RLS scaffold keyed on `project_id`): `mn_projects`, `mn_charters`, `mn_workflows` (the report's unit of governed work; the Workbench "Mission" is a `workflow_kind='mission'` row), `mn_workflow_state` (lifecycle, control, phase, status_summary, last_seq), `mn_plans`, `mn_tasks`, `mn_claims`, `mn_evidence`, `mn_artifacts`, `mn_provenance`, `mn_decisions`, `mn_capability_grants`, `mn_capability_tokens`, `mn_leases`, `mn_commitments`, `mn_checkpoints`, `mn_essential_variables`, `mn_workflow_definitions`, `mn_knowledge_assertions`, `mn_agent_manifests`, `mn_agent_sessions`, `mn_model_assignments`, `mn_releases`, `mn_incidents`, `mn_snapshots`, `mn_tool_invocations`, `mn_verification_runs`, `mn_sema_ledger`, `mn_audit_ledger`, `mn_constitution_versions`, `mn_quarantine`. A `rebuild_projections` command must reproduce them byte-for-byte from the journal.
- SQLite: only `SqliteJournalAdapter` for `KOSMOS_RUNTIME_PROFILE=test`/portable. Existing SQLite stores (`adapters/resource/sqlite`, `data/tektos_*.db`) untouched except data-dir relocation (15.14).

### 2.10 Events — CloudEvents 1.0 over Mesiteia

- `EventEnvelope` gains optional `source` (default `/kosmos/<producer>`), `subject`, `workflow_id`, `correlation_id`, `causation_id`, `datacontenttype='application/json'`, `dataschema`, `provenance`, `confidence`, and `to_cloudevent()`/`from_cloudevent()`; extension attributes lowercase alphanumerics: `kosmosworkflowid`, `kosmoscorrelationid`, `kosmoscausationid`, `kosmosproducer`, `kosmosschemaversion`, `kosmossubsystem`.
- Type grammar: `io.kosmos.<subsystem-or-aggregate>.<event>.v<major>` — e.g. `io.kosmos.workflow.created.v1`, `io.kosmos.kybernesis.accepted.v1`, `io.kosmos.sema.raised.v1`, `io.kosmos.tekton.task.started.v1`, `io.kosmos.epimeleia.run.started.v1`, `io.kosmos.noesis.model.selected.v1`, `io.kosmos.poros.recommendation.v1`, `io.kosmos.harmonia.lease.granted.v1`. Catalogue in §4.3; JSON Schemas under `koinon/src/koinon/contracts/schemas/events/`.
- Legacy namespaces (`tektos.*`, `immune.*`, `loop_safety.*`, `thermal.*`, `sandbox.*`, `hindsight.*`) stay valid until 15.15; ADR-086 amended by ADR-153.

### 2.11 Policy, capabilities, Telos authority chain

- PDP: **OPA v1.21.0** (Apache-2.0) loopback sidecar `kosmos-opa.service` on `127.0.0.1:8181`, loading the `policies/` tree as a bundle; PEP: `PolicyPort` consulted by Kybernesis **before every** tool invocation, model call, checkpoint, promotion, release, grant/token issuance, extension promotion, and protected-path change. Every decision journaled as `io.kosmos.telos.policy.decided.v1` with `policy_digest`.
- `policies/` tree (report): `constitution/` (signed constitution versions + `pubkey.pem` moved from `governance/constitution/`; Rego `kosmos.constitution` exposes invariants as data), `capabilities/` (Rego `kosmos.capabilities`: grant matching, token scopes, TTL, path globs, command classes, network; `kosmos.autonomy` A0–A4 ceilings), `protected-paths/` (Rego `kosmos.paths`: worktree confinement; denylist `.git/`, `.env*`, `ops/systemd/*.local.env`, `~/.ssh`; **protected repository paths** `policies/**`, `koinon/src/koinon/{policy,capabilities}/**`, `koinon/src/koinon/kernel/{sema,telos,euthyna,kybernesis}/**`, `deploy/**`, `.github/workflows/**`, `AGENTS.md` — agents may propose diffs there only as `proposal` artifacts routed to the Telos `ChangeControlWorkflow`), `model-use/` (Rego `kosmos.models`: which model roles may be used for which action classes; token budgets; residency rules from Poros data), `exceptions/` (time-boxed, signed exceptions with owner + expiry; Rego `kosmos.exceptions`), plus `policies/tests/` (`opa test` + differential fixtures).
- **Telos authority chain** implemented as: (1) Human authority — `Decision` with `witnessed=true` (E6) or a signed constitution amendment; (2) signed constitutional artifacts — `policies/constitution/versions/*.toml` + detached signatures verified at boot by `koinon.policy.SignatureVerifier` (existing `plugins/praxis/constitution/{signing,verifier}`); (3) deterministic policy engine — OPA; (4) bounded interpretation functions — `PolicyInterpretationFunction` (one LLM call, schema-validated, only to *explain* or *classify* an ambiguous request; never to decide); (5) authorization workflow — `HumanAuthorizationWorkflow`/`ChangeControlWorkflow` (durable, human decision point); (6) capability enforcement — `koinon.capabilities` PEP in the tool registry, model gateway, artifact promotion, and workflow signals.
- **Capabilities**: `CapabilityGrant {grant_id, workflow_id, subject (agent manifest), scopes[], path_globs[], command_classes[], network ('none'|'loopback'|'allowlist:<hosts>'), max_tier, expires_at, issued_by, decision_id}` issued by Kybernesis/Telos decisions; per-run **capability tokens** (signed, short-lived, scope ⊆ grant) issued by the Asphaleia `CapabilityTokenService`; every tool invocation, model call and artifact write cites the token. **Autonomy ceilings** (Telos): `A0` observe-only · `A1` propose · `A2` act in worktree with tests, no VCS publish · `A3` act + open PR/merge to a task branch, no release · `A4` release within charter bounds; `KOSMOS_AUTONOMY_TIER_MAX` (default `A2`) enforced in Rego; mapping to `ChangeApprovalTier` (ADR-033): A0–A2 `AUTONOMOUS` inside a grant; A3 `HUMAN_REVIEW`; A4 `HUMAN_REQUIRED` for a workflow's first release, then per charter.

### 2.12 Orthogonal workflow state (Kybernesis-owned) and derived status

| Axis | Values |
|---|---|
| Lifecycle | `DRAFT → READY → RUNNING → VERIFYING → REVIEW → RELEASING → DONE`, terminal `CANCELLED`, `FAILED`; post-release `OBSERVING` |
| Control | `ACTIVE`, `PAUSED`, `BLOCKED` (awaiting decision/grant/lease), `CONTAINED` (Sema circuit breaker or policy containment; no writes), `RECOVERING`, `EXPERT_ESCALATION` |
| Phase | `CAPTURE → CLARIFY → PLAN → BUILD → VERIFY → RELEASE → OBSERVE → LEARN` |
| Task | `PLANNED → READY → RUNNING → VERIFYING → DONE`, `BLOCKED`, `FAILED`, `ABORTED` |

`status_summary` (compat for the legacy sessions page): `created, planning, awaiting_approval, running, verifying, repairing, paused, blocked, awaiting_decision, cancelling, cancelled, succeeded, failed, timed_out, recovering` — a pure function of (Lifecycle, Control, Phase). Only Kybernesis writes these (I-1).

### 2.13 Claims, evidence, artifacts, and the Tekton gate chain

- `Claim {claim_id, workflow_id, task_id?, statement, kind (functional|quality|security|performance|process), status (asserted|supported|refuted|withdrawn), required_tier, current_tier, created_by}`; `Evidence {evidence_id, claim_id, tier E0–E6, producer (worker|euthyna|human|tool), method, artifact_digests[], environment_digest, exit_code, summary, recorded_at}`.
- Tiers: **E0** claim only · **E1** worker self-report · **E2** tool output in the task worktree · **E3** independent re-run by **Euthyna** in a fresh clean checkout · **E4** E3 under a pinned environment digest · **E5** property/adversarial/mutation · **E6** human-witnessed (`Decision.witnessed=true`). Acceptance of consequential work requires ≥E3 on every acceptance-blocking claim; refuting evidence wins.
- **Tekton non-bypassable chain** (each link a deterministic `Gate` or `Worker`, each emitting a journaled event with the token that ran it): candidate commit (Checkpoint Manager) → `QualityGate` (protected; config under `policies/` + `plugins/tekton/gates/`) → `FormatLintWorker` (ruff) → `TypeCheckWorker` (mypy) → `TestWorker` (pytest/junit) → `ArchitectureRuleGate` (import rules, taxonomy, isolation) + `SecurityRuleGate` (bandit -lll, gitleaks, pip-audit) → `CleanRoomBuildWorker` (Euthyna, separate process/environment; E3/E4) → `EuthynaReviewWorkflow` when the risk class requires it (protected paths, security-relevant diffs, dependency changes) → Kybernesis `AcceptanceGate` accepts/rejects → `PromotionGate`/`PromotionWorkflow`. The agent cannot self-accept, skip validation, alter gate configuration, disable tests, weaken policy, or push unverified changes: gate configuration is a protected path; the OpenHands/Tektos-native run token has no `vcs-publish`/`gate-admin` scope; the accepting subject is never the producing run (I-3).

### 2.14 Isolation ladder (Asphaleia sandbox policy)

| Tier (`KOSMOS_SANDBOX_TIER`) | Mechanism | When |
|---|---|---|
| `process` (default after 15.7) | Per-task `git worktree` at `data/worktrees/<workflow_id>` on branch `tekton/<workflow_id>`; `asyncio.create_subprocess_exec` (argv only), `start_new_session=True`, `os.killpg` on timeout, rlimits (`RLIMIT_AS/CPU/FSIZE/NPROC`), env allowlist, `unshare -n` unless the token allows network (`loopback` needed for the inference gateway) | 15.7 |
| `bwrap` | `bubblewrap` (`bwrap --unshare-all --share-net(only when loopback is granted) --die-with-parent --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 --ro-bind /bin /bin --ro-bind /etc/alternatives /etc/alternatives --bind <worktree> /work --bind <venv> <venv> --dev /dev --proc /proc --tmpfs /tmp --chdir /work`) — external LGPL-2.1 binary invoked as a tool | 15.7 opt-in; default in `production` from 15.14 |
| `docker` (OpenHands `DockerWorkspace`) | Only if the OpenHands SDK's `LocalWorkspace` inside `bwrap` proves insufficient for untrusted repositories; envelope check first (§0.7 item 5) | 15.12 decision, ADR-162 |
| `gvisor` / `firecracker` | Deferred; ADR-gated in Stage 16 | Stage 16 |

### 2.15 Client (report silent → Workbench mechanism)

- `apps/workbench-ui/` — React 19 + TypeScript + Vite + Tailwind 4 + TanStack Query + Zustand, consuming `/api/v1/*` and the AG-UI SSE projection; surfaces: **Home (Viability Cockpit)**, **Workflows** (list + Workflow Control: now–meaning–next card, causal timeline, Proof / Charter / Live / Expert perspectives), **Agents** (Epimeleia sessions, manifests, Hermes runs), **Models** (Noesis registry, health, assignments), **Resources** (Poros telemetry, leases, thermal), **Knowledge** (Gnosis), **Research** (Zetesis), **Council** (Synedrion advice), **Agora**, **Security** (Asphaleia grants/tokens/protected paths), **Operations** (health, outbox lag, Sema ledger, incidents); modes **Ask / Explore / Plan / Build / Operate**. VSM labels in the UI use canonical names.
- `apps/desktop/` — Tauri 2 host (Rust; MIT/Apache-2.0) wrapping `workbench-ui`, operator token in the OS keyring, connecting to `http://127.0.0.1:8000`. Ubuntu prerequisites per Tauri v2 docs: `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev` + Rust stable + Node ≥ 20.
- The kernel serves the built `workbench-ui` at `/workbench/` so Playwright can gate it in CI without Tauri; the legacy Next.js `ui/` keeps `/` until the parity checklist (15.15) is met.

### 2.16 Repository layout (report) and migration strategy

Target (the report's extension organization, plus the non-Python directories Kosmos already has):

```
kosmos-lms/
├── koinon/
│   ├── src/koinon/
│   │   ├── kernel/            # boot/composition root, plugin registry, config, lifecycle;
│   │   │   ├── kybernesis/    #   S3 controllers, gates, apex approvals, projections
│   │   │   ├── harmonia/      #   S2 leases, concurrency, backpressure, dedup, oscillation (loop_safety)
│   │   │   ├── sema/          #   algedonic components, detectors (phrouros, immune), transport (notification)
│   │   │   ├── telos/         #   S5 workflows (authorization, amendment, exceptions, arbitration)
│   │   │   ├── euthyna/       #   S3* evidence validation, provenance verification, audit ledger, inspection
│   │   │   └── pronoia/       #   S4 deterministic synthesis workflows
│   │   ├── contracts/         # Syndesmos: ports/ (the 24 + 6 Protocols), events/, commands/, schemas/, taxonomy.py, manifest.py
│   │   ├── workflows/         # durable workflow engine + adapters (local, in-memory); definitions in /workflows
│   │   ├── policy/            # Telos mechanisms: constitution loader/signing/verifier, PDP client, interpretation functions
│   │   ├── capabilities/      # grants, tokens, PEP enforcement hooks
│   │   ├── tools/             # governed tool registry, builtins, sandbox adapters (process, bwrap), worktrees
│   │   ├── hooks/             # hook registry, typed event responses
│   │   ├── artifacts/         # artifact service (content-addressed) + provenance service
│   │   ├── mneme/             # journal (postgres, sqlite), relational/graph/vector memory, embeddings ports' adapters
│   │   ├── aisthesis/         # observability adapters, telemetry, trajectories, metrics
│   │   ├── mesiteia/          # event bus adapters, API gateway (routers, errors, health, AG-UI SSE, inference gateway), discovery, routing, correlation, rate limits
│   │   └── adapters/          # TRANSITIONAL (Step A only): remaining adapters not yet re-homed; empty by 15.15
│   └── tests/                 # Koinon unit + contract tests
├── plugins/{zetesis,synedrion,gnosis,poros,epimeleia,tekton,axiomeon,holon,agora,asphaleia,noesis}/
│   └── <name>/{__init__.py, plugin.py (manifest), components/, praxis/ (local S1 helpers), tests/, README.md}
├── skills/shared/             # procedural knowledge (no authority); agent-generated skills go to data/quarantine first
├── policies/{constitution,capabilities,protected-paths,model-use,exceptions,tests}/
├── extensions/adapters/{hermes,openhands,tektos_native,vllm,llamacpp,ollama,mcp,a2a,voice,vision}/
├── workflows/                 # workflow definitions (YAML): mission, extension_promotion, self_improvement, change_control, …
├── apps/{workbench-ui,desktop}/   # client (15.13)
├── ui-contracts/              # generated TypeScript types
├── tests/{architecture,integration,policy,conformance}/   # report taxonomy; Workbench subfolders inside (unit, contract, property, stateful, journeys, adversarial, sandbox, accessibility, formal)
├── deploy/{systemd,compose,opa}/
├── docs/  ops/benchmarks/  scripts/  vendor/  templates/  ui/ (legacy web shell until 15.15)
```

**Placement table for Step A (Stage 15.3; mechanical, names preserved except the three renames):**

| Current | Target | Note |
|---|---|---|
| `kernel/**` | `koinon/src/koinon/kernel/**` | `kernel/app.py` stays the ASGI entry until 15.15 |
| `ports/*.py` | `koinon/src/koinon/contracts/ports/*.py` | `event_envelope.py` → `contracts/events/envelope.py` with a re-export shim in `contracts/ports/event_envelope.py` |
| `adapters/**` | `koinon/src/koinon/adapters/**` | transitional; re-homed per phase (table below) |
| `plugins/tektos/**` | `plugins/tekton/**` | **rename**; import path `plugins.tekton` |
| `plugins/praxis/**` | `koinon/src/koinon/policy/praxis/**` | **rename**; split into `policy/constitution` + `kernel/kybernesis/apex` in 15.7 |
| `plugins/phrouros/**` | `koinon/src/koinon/kernel/sema/detectors/phrouros/**` | **rename**; wired in 15.6 |
| `plugins/zetesis/**` | `plugins/zetesis/**` | unchanged |
| `governance/constitution/**` | `policies/constitution/**` | data + `pubkey.pem`; loader path constant updated |
| `ops/`, `scripts/`, `docs/`, `ui/`, `templates/`, `vendor/`, `tests/` | unchanged | `tests/` gains `architecture/ integration/ policy/ conformance/` |

**Per-phase re-homing of `koinon/src/koinon/adapters/**` (Step B; each move leaves a one-release `DeprecationWarning` shim):** 15.5: `relational_memory/*`, `memory/dozerdb`, `vector/qdrant`, `embeddings/*`, `data/*` → `koinon.mneme.*` / `koinon.artifacts`; 15.6: `event_bus/valkey` → `koinon.mesiteia.event_bus`; `notification/kernel` → `koinon.kernel.sema.transport`; `immune/tektos`, `loop_safety/tektos` → `koinon.kernel.sema.detectors.immune`, `koinon.kernel.harmonia.loop_safety`; `observability/otel_stack` → `koinon.aisthesis`; `approval_resolver/praxis` → `koinon.kernel.kybernesis.apex`; 15.7: `sandbox/*` → `koinon.tools.sandbox`; `secrets/age_file` → `plugins/asphaleia/secrets`; 15.8: `mcp/*` → `extensions/adapters/mcp`; `frontend_contract/kernel` → `koinon.mesiteia.api.frontend_contract`; 15.9: `llm/*` → `extensions/adapters/{llamacpp (llama_swap), ollama}` + `plugins/noesis/fallback` (failover); `resource/sqlite`, `thermal/tektos` → `plugins/poros`; `vision/*`, `voice/*` → `extensions/adapters/{vision,voice}`; 15.10: `session/*` → `plugins/epimeleia/sessions`; `tektos/vendor`, `tektos_frontend` → `plugins/tekton/vendor`, `plugins/tekton/frontend`; 15.11: `search/searxng` → `plugins/zetesis/adapters/search`. `koinon/src/koinon/adapters/` is deleted in 15.15.

Migration strategy (binding): (1) Stage 15.3 performs the placement table with one scripted commit and identical test IDs before/after; (2) new code is born in its report home; (3) Step B re-homing per stage as packages are touched, with shims; (4) Stage 15.15 deletes shims, the transitional `adapters/`, `ui/`, and the donor registry.

### 2.17 Data ownership (report table → stores)

| Data | Owner | Store |
|---|---|---|
| Workflow state, event history | Koinon (Kybernesis via Mneme) | `mn_event_journal`, `mn_workflows`, `mn_workflow_state` |
| Semantic knowledge | Gnosis | `gnosis_*` tables + Qdrant collections (Mneme adapters) |
| Research captures | Zetesis | `zetesis_*` tables + artifacts (`kind=research_capture`) |
| Audit evidence | Euthyna | `mn_audit_ledger`, `mn_evidence`, artifacts (`kind=evidence`) |
| Resource telemetry | Poros / Aisthesis | Prometheus + `poros_telemetry` hypertable-style table |
| Agent sessions | Epimeleia / Mneme | `mn_agent_sessions`, `SessionPort` turns |
| Constitutional records | Telos | `policies/constitution/versions/` (Git, signed) + `mn_constitution_versions` |
| Artifacts | Koinon artifact service | `data/artifacts/` (content-addressed) + `mn_artifacts`, `mn_provenance` |
| Ontologies | Holon | `holon_*` tables (Stage 16) |
| Models, quantizations, assignments | Noesis | `config/models.yaml` (Git) + `mn_model_assignments`, `noesis_health` |
| Capabilities, tokens, secrets metadata | Asphaleia | `mn_capability_grants`, `mn_capability_tokens`; secrets in `age`-encrypted files (never in Postgres) |
| Sema incidents | Sema | `mn_sema_ledger` (append-only, hash-chained) |

Rule: a plugin reads another owner's data only through a port or a projection event; no cross-owner SQL joins (architecture test on Alembic environments: one per owner).

### 2.18 Extension placement principles (report) → mechanisms

- **Skills teach; tools act; hooks react; workflows coordinate; plugins own domain semantics; Koinon owns mechanisms and authority boundaries; Epimeleia owns agent runtime; Tekton owns software-engineering governance; Noesis owns models; Asphaleia owns trust.**
- **Git owns canonical source** (skills, workflow definitions, policies, models registry); **runtime projections are disposable** (`rebuild_projections`); **agent-generated extensions are quarantined**: anything an agent produces that would become a tool, hook, skill, policy, or workflow definition is written to `data/quarantine/<kind>/<id>/`, registered with `trust_state=quarantined`, unexecutable by policy, and promoted only through `workflows/extension_promotion.yaml` (Euthyna review + Kybernesis decision; Telos for policies).

---
## §3 Stage 15 — execution plan (report phase order; containment first)

Stage 15 is appended to `docs/Kosmos-Build-Sequence-v26.md` as an **Architecture program addendum** (the same mechanism the v26 addendum used for Stages 9–14), one stanza per sub-stage below. Numbering: `Stage 15.<n>`; the Architecture Report's roadmap phase is given in the heading; Appendix C.1/C.2 cross-reference the report phases and the v1.0 stage numbers. Each stage has one branch/PR unless stated otherwise.

Each stanza uses the same skeleton: **Goal → ADR → Preconditions → Steps → Tests → Exit gate → Commits → Logs → Rollback**. Commands are for Colossus (`/home/rmholston/dev/kosmos-lms`, venv activated per §0.5). Every new class is classified per §2.6 in the same commit that creates it.

| Stage | Report phase | Title |
|---|---|---|
| 15.0 | — | Freeze, truth-telling, program charter, nomenclature |
| 15.1 | (Phase 2 pulled forward for P0) | Security containment |
| 15.2 | (Phase 1 hygiene) | Packaging, runtime profiles, dependency hygiene, CI that fails |
| 15.3 | Phase 1 Koinon core | Layout Step A — `koinon/`, `plugins/`, `extensions/`, `policies/`, renames |
| 15.4 | Phase 1 | Koinon contracts (Syndesmos), taxonomy registry, plugin manifests & quarantine states, local Praxis helpers |
| 15.5 | Phase 1 | Mneme: PostgreSQL journal + outbox, CloudEvents, artifact & provenance services, projections |
| 15.6 | Phase 1 | Workflow engine, Kybernesis controllers, Harmonia, Sema (no-LLM), Euthyna ledger, durability drills |
| 15.7 | Phase 2 Asphaleia | Identity, capabilities & tokens, OPA/Rego policy tree, Telos authority chain, protected paths, secrets, sandbox isolation |
| 15.8 | Phase 3 Syndesmos & Mesiteia | API gateway v1, error envelope, health, AG-UI SSE, inference gateway, event bus, discovery, MCP server, A2A transport |
| 15.9 | Phase 4 Poros & Noesis | Resource telemetry/budgets/lease recommendations; model registry, routing, tool-calling protocol, fallbacks, vLLM adapter, benchmarks |
| 15.10 | Phase 5 Epimeleia | Agent manifests, Hermes API-server adapter, capability broker, skills/toolsets, sessions, lifecycle, termination |
| 15.11 | Phase 6 | Zetesis, Gnosis, Synedrion, Agora |
| 15.12 | Phase 7 Tekton & Euthyna | OpenHands primary Coding Worker + Tektos-native fallback, gate chain, clean-room verification, acceptance/promotion/release/rollback, real-model corpus |
| 15.13 | (client; report silent) | Workbench client: React app + Tauri 2 desktop (parallel track from 15.8) |
| 15.14 | (deployment) | Colossus deployment: systemd, env, Postgres 18, OPA, hermes gateway, model servers |
| 15.15 | (closure) | Legacy retirement, Step B closure, debt, DoD |
| 16 | Phase 8 | Higher-order intelligence: Axiomeon, Holon, Pronoia, Telos amendment automation, controlled self-improvement, homeostasis |

---

### Stage 15.0 — Freeze, truth-telling, program charter, nomenclature

**Goal.** Make the repository tell the truth about its state, install the operating documents Hermes needs, ratify the program's precedence rule and canonical nomenclature. No behavior change.

**ADR.** ADR-147 "Architecture program charter, document precedence, canonical nomenclature" (amends ADR-145's freeze scope: the absorption program is complete; the architecture program begins; the Architecture Report is rank 1 and the Workbench spec rank 2; §0.3 conflict table is normative; Tektos→Tekton, praxis→Telos/Kybernesis split, phrouros→Sema detectors are decided here and executed in 15.3/15.6/15.7).

**Preconditions.** This plan merged (or checked out) on `main`; `baseline-before-koinon-2026-09-28` tag pushed (§0.6).

**Steps.**

1. `git checkout -b feat/arch-15-0-freeze`.
2. Author `docs/adrs/ADR-147-architecture-program-charter-and-precedence.md` (template in Appendix B; Decision = §0.2–§0.3 verbatim incl. the invariants table; Alternatives = "bump spec to v27 now" (rejected: churn before code exists), "keep the Workbench spec authoritative" (rejected by user decision 5), "keep the Tektos-native loop as primary coding worker" (rejected by decision 6)); add the row to `docs/adrs/README.md`; add a `> **STATUS AMENDMENT (2026-MM-DD):**` block to `docs/adrs/ADR-145-*.md` noting that ADR-147 opens the architecture program without reopening ADR-077…102.
3. Copy the sources: `docs/Kosmos-LMS-Architecture-Report-v1.md` (verbatim from `docs/implementation/sources/kosmos-lms_architecture-v1.md`) and `docs/Kosmos-Agent-Workbench-Spec-v1.md`; add at the top of `docs/Kosmos-Build-Spec-v26.md` a three-line "Authority note" pointing to ADR-147, the report and the spec (content edit — `kosmos-spec-diff` rank "content"; no version bump).
4. Create `docs/GLOSSARY.md` from §2.2 (canonical names, kinds, replaced names, homes) — the single place a name is defined; every later doc links to it.
5. Append the "Architecture program addendum" header and the Stage 15.0–15.15 stanzas (titles, goals, exit gates copied from this document) to `docs/Kosmos-Build-Sequence-v26.md`.
6. Fix `README.md`: replace lines 3–15 ("PROGRAM COMPLETE …") and 31–33 ("Current status: Stage 0 complete …", "Repo layout (Stage 0.1)") with one "Status" section: absorption program complete 2026-09-26 (ADR-145); architecture program in progress (ADR-147, Stage 15.x, link to this plan and the glossary); **security notice**: until Stage 15.1 lands, run the kernel only on loopback with `KOSMOS_OPERATOR_MODE=observer`.
7. Create `AGENTS.md` (repo root) — the agent-facing operating manual: session ritual (§0.4), pre-flight (§0.5), the four logs, ADR/ledger duties, ADR-007 in the new vocabulary, zero-trust memory, no-`shell=True`, branch/commit conventions (§0.6), canonical names (link to glossary), the governing rule and invariants (§0.2), where the plan lives, how to run the default test suite (`pytest` — no args) and CI-equivalent checks (`make ci-local` from 15.2). Create `plugins/tektos/AGENTS.md` (renamed with the package in 15.3) with the Tekton-specific rules (donor is read-only; the governed tool registry is the only tool path; tool-schema changes need a fixture update under `plugins/tektos/tests/fixtures/tool_schemas/`).
8. `docs/implementation/README.md` (index of this plan, sources, baseline log) — already present if PR #1 merged; otherwise create.
9. `KNOWN_ISSUES.md`: add entries for B-01, B-02, B-03 (P0, "Blocks: Stage 15.1"), B-06/B-07/B-09/B-10 (P1, "Blocks: Stage 15.2"), B-17 (P1, "Blocks: Stage 15.14"), each with DEBUG_LOG search terms `pty`, `tools/execute`, `shell=True`, `packages`, `ConnectionRefused 6379`, `axioms_routes`, `ExecStartPre`.
10. Reconcile ledgers: make `docs/PORTING_LEDGER.md` a one-line pointer to the root `PORTING_LEDGER.md` (root is canonical per `kosmos-port-workflow`); add an "External tools" section header; move `research_6_3_7b.md` to `docs/research/`.
11. Overwrite `SESSION_HANDOFF.md` (template) — position: Stage 15.0 complete; next action: Stage 15.1 step 1.

**Tests.** `pytest -q -p no:cacheprovider --collect-only | tail -1` unchanged; `python scripts/check_plugin_isolation.py`.

**Exit gate.** ADR-147 ratified and indexed; README has one status; `AGENTS.md`, `plugins/tektos/AGENTS.md`, `docs/GLOSSARY.md` exist; Build-Sequence v26 has the Stage 15 addendum; `KNOWN_ISSUES.md` lists the P0/P1 items; `SESSION_HANDOFF.md` current.

**Commits.** `docs(adr): Stage 15.0 — ADR-147 architecture program charter, precedence, nomenclature`; `docs: Stage 15.0 — README status, AGENTS.md, GLOSSARY, Build-Sequence v26 Stage 15 addendum, KNOWN_ISSUES P0/P1`.

**Logs.** BUILD_LOG: one entry per step 2, 4–5, 6–7, 9–10. SESSION_HANDOFF overwritten.

**Rollback.** `git revert` of the two commits; nothing runtime-visible.

---

### Stage 15.1 — Security containment (audit P0; Asphaleia pulled forward)

**Goal.** Nothing reachable over HTTP/WS can run arbitrary commands on Colossus without an explicit operator token, an allowed Origin, and passage through the governed sandbox. Bandit HIGH count = 0. Boot the governed `SandboxPort` so that the Tektos loop, executor, and orchestrator stop receiving `sandbox=None`. This is the minimum of Asphaleia ("narrow explicit capabilities, not ambient authority") needed before any other code lands; the full subsystem is Stage 15.7.

**ADR.** ADR-148 "Kernel exposure containment: operator mode, operator token, WebSocket origin policy, single tool-execution path" (amends ADR-082 (SandboxPort) and ADR-093 (Tektos sandbox/tools absorption scope) to declare `TektosSandboxAdapter` behind `TektosToolRegistry` the **only** execution path; amends ADR-141 route parity by allowing behavior-changing guards on `/ws/pty` and `/api/tools/*/execute`).

**Preconditions.** Stage 15.0 merged. `grep -in "pty\|tools/execute\|shell=True" DEBUG_LOG.md` performed (search-first rule).

**Steps.**

1. `git checkout -b feat/arch-15-1-containment`.
2. **Operator mode + token** — new module `kernel/operator_auth.py` (classified `AuthenticationService`, subsystem `asphaleia`; moves to `plugins/asphaleia/components/authentication.py` in 15.7):
   - `OPERATOR_MODE = os.environ.get("KOSMOS_OPERATOR_MODE", "observer")` ∈ `observer|operator`; `_token()` reads `KOSMOS_OPERATOR_TOKEN` from env or, if `registry.secrets` (the `SecretsPort` adapter) is booted, `secrets.get("kosmos/operator_token")`.
   - `require_operator(request: Request) -> None`: 403 `{"error": {"code": "operator_mode_disabled"}}` when mode ≠ `operator`; 401 `{"error": {"code": "operator_token_invalid"}}` unless `hmac.compare_digest(request.headers.get("Authorization",""), f"Bearer {token}")`; also accepts `X-Kosmos-Operator-Token`. Never log the token. Use as `Depends(require_operator)`.
   - `authorize_websocket(ws: WebSocket) -> bool`: (a) `Origin` must be in `KOSMOS_WS_ALLOWED_ORIGINS` (default `http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:3000,http://localhost:3000,tauri://localhost`); (b) after `accept()`, the **first frame within 5 s** must be `{"type":"auth","token":"…"}` matching the operator token; otherwise `await ws.close(code=4401)` and return `False`. Rationale: tokens in query strings leak into logs.
   - `/health` gains `"operator_mode": "observer|operator"` (never the token).
3. **Contain `/ws/pty`** (`kernel/app.py:9841`): first statement in `pty_endpoint`: `if not await authorize_websocket(websocket): return`. The child exec stays `[$SHELL, "-l"]` (operator's own shell is the feature) but `TEKTOS_FS_ROOT`, `KOSMOS_*_TOKEN`, `KOSMOS_POSTGRES_URI` are **removed** from the child env (`env = {k: v for k, v in os.environ.items() if not k.startswith(("KOSMOS_", "TEKTOS_"))}` passed via `execvpe`). Update `ui/components/panels/*Terminal*` / `ui/lib/pty-ws.ts` (locate with `rg -n "ws/pty" ui/`) to send the auth frame first, reading the token from `NEXT_PUBLIC_KOSMOS_OPERATOR_TOKEN` only in dev; in production the token is entered once in the shell's settings panel and kept in `sessionStorage`.
4. **Boot the governed sandbox** — add `self.sandbox: Any = None` to `_BootRegistry`, and `_boot_sandbox()` inside `lifespan` **before** `_boot_tektos_turn_loop`/executor/orchestrator: `from adapters.sandbox.tektos.adapter import TektosSandboxAdapter; registry.sandbox = TektosSandboxAdapter(event_bus=registry.event_bus, memory=registry.memory)`; gated `KOSMOS_SANDBOX=tektos|noop|off` (default `tektos`; `noop` → `adapters/sandbox/noop`). Add `sandbox` to `/health` subsystems. Replace the three `getattr(registry, "sandbox", None)` reads with `registry.sandbox`.
5. **Boot the governed tool registry** — new `_boot_tektos_tool_registry()` after approval + sandbox + immune: `TektosToolRegistry(approval_gateway=registry.approval_gateway, approval_resolver=registry.approval, sandbox=registry.sandbox, event_bus=registry.event_bus, pre_approval_detectors=<immune detectors tuple>, memory=registry.memory)`; register the builtin descriptors (`plugins/tektos/tools/builtin.py` already defines the governed builtins — verify with `rg -n "ToolDescriptor(" plugins/tektos/tools/builtin.py`). Store as `registry.tektos_tools`. The gateway (`ApprovalGatewayPort.propose`) is the apex engine `KernelChangeApprovalAdapter` that `_boot_approval` (`kernel/app.py:646-668`) already constructs and wraps in `PraxisApprovalResolverAdapter`; change `_boot_approval` to also keep the engine as `registry.approval_gateway` (new slot) so both sides of the tool registry are the same apex engine.
6. **Single execution path** — rewrite `execute_tool` (`kernel/app.py:7704`): `Depends(require_operator)`; `result = await registry.tektos_tools.invoke(tool_name, body.parameters, intention_id=f"api-{uuid4().hex[:12]}", proposing_domain="operator")`; return `{"result": {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr, "wall_seconds": result.wall_seconds, "run_id": result.run_id}}`; map `ToolApprovalDenied` → 403 `tool_denied`, `KeyError` → 404 `tool_unknown`, `ValueError` → 422 `tool_arguments_invalid`. Keep `GET /api/tools` and `/api/tools/{name}` (read-only) unauthenticated but sourced from `registry.tektos_tools.list_tools()` merged with the donor registry's **metadata** (for MCP-imported tools) — no execution through the donor object.
7. **Neutralize the donor path** — `kernel/tool_registry.py::ToolRegistry.execute()` becomes a thin delegate: if a governed registry is attached (`self._governed`), run `asyncio.run_coroutine_threadsafe(self._governed.invoke(...), loop).result(timeout)`; else return `"Tool execution disabled: governed registry not booted"`. `plugins/tektos/tools/sandbox_provider.py`: delete `sudo -n` retry (lines 146–174), replace `subprocess.run(cmd, shell=True, …)` with `subprocess.run(shlex.split(cmd), shell=False, …)` **and** raise unless `Path(cwd).resolve().is_relative_to(FS_ROOT)`; default `FS_ROOT = Path(os.getenv("TEKTOS_FS_ROOT", "data/workspaces")).resolve()`; `read_file/write_file/list_directory` must reject paths outside `FS_ROOT` (resolve symlinks). `adapters/sandbox/tektos/vendor/sandbox_exec_donor.py:160` (`shell=True`): mark `# nosec B602 — donor reference, never imported at runtime` **only if** `rg -n "sandbox_exec_donor" --glob '!*vendor*' .` returns nothing; otherwise rewrite to argv. `SkillExecutor(tool_registry=_tool_registry)` (app.py:2602) keeps working because `execute()` now delegates.
8. **Default-off dangerous surfaces** — in `observer` mode, `/ws/pty`, `POST /api/tools/*/execute`, `POST /api/skills/*/execute` (if present: `rg -n '"/api/skills' kernel/app.py`), `POST /api/mcp/connect` return 403 `operator_mode_disabled`. Everything else keeps today's behavior.
9. **Bandit gate** — `.bandit` config `skips: [B101]` for tests only; `bandit -q -r ports adapters kernel plugins -x '*/tests/*,*/vendor/*' -lll` must print `No issues identified`. Add `scripts/gate_security.sh` (may use `set -euo pipefail`; it is a script).
10. Tests (new): `tests/kernel/test_stage_15_1_operator_auth.py` — observer mode 403 on the four surfaces; operator mode 401 without token, 200/`result.exit_code` with token; WS 4401 on bad Origin and on missing/invalid first frame; WS success path with `starlette.testclient` `websocket_connect(..., headers={"Origin": "http://127.0.0.1:8000"})`. `tests/kernel/test_stage_15_1_single_tool_path.py` — `POST /api/tools/run_command/execute` with `{"command": "echo hi; touch /tmp/pwned"}` → runs argv `["echo","hi;","touch","/tmp/pwned"]` (no shell), file **not** created; `write_file` outside `FS_ROOT` → 422; donor `ToolRegistry.execute` with no governed registry returns the disabled string. `plugins/tektos/tools/test_sandbox_provider_confinement.py` — symlink escape rejected; `sudo` absent (`rg -c "sudo" plugins/tektos/tools/sandbox_provider.py` == 0 asserted in `test_stage_15_1_bandit_high_zero.py` which shells out to bandit like `test_stage_3_12_exit_gate.py` does, skipping when bandit is absent).
11. Docs: `SECURITY.md` (threat model summary: loopback-only kernel, operator token, tiers; reporting contact = repo issues), `docs/security/exposure-containment.md` (the four surfaces, env vars, WS auth frame protocol), `KNOWN_ISSUES.md` B-01/B-02/B-03 moved to DEBUG_LOG as closed diagnoses.

**Tests.** `pytest tests/kernel/test_stage_15_1_*.py plugins/tektos/tools adapters/sandbox -q` and the full default `pytest -q`.

**Exit gate (all must hold).** `bandit … -lll` = 0 HIGH; with `KOSMOS_OPERATOR_MODE` unset: `curl -s -X POST 127.0.0.1:8000/api/tools/run_command/execute -H 'content-type: application/json' -d '{"parameters":{"command":"id"}}'` → 403; `websocat`/Playwright to `/ws/pty` without auth frame → close 4401; `curl -s 127.0.0.1:8000/health | jq .subsystems.sandbox` → `"ok"`; `rg -n "shell=True" --glob '!*vendor*' --glob '!*test*' kernel plugins adapters` → 0; the legacy shell terminal panel works end-to-end in **headed Playwright** (`cd ui && npx playwright test tests/*pty* --headed`) with the token entered.

**Commits.** `feat(asphaleia): Stage 15.1 — operator mode, operator token, WS origin policy (ADR-148)`; `fix(tools): Stage 15.1 — remove shell=True/sudo/root FS from SandboxProvider; boot SandboxPort + governed TektosToolRegistry`; `test(kernel): Stage 15.1 — containment tests + bandit HIGH=0 gate`; `docs(security): Stage 15.1 — SECURITY.md, exposure-containment`.

**Logs.** BUILD_LOG per step 2–3, 4–5, 6–7, 8–9, 10, 11; DEBUG_LOG entries closing B-01, B-02, B-03; SESSION_HANDOFF.

**Rollback.** `KOSMOS_SANDBOX=off` restores the pre-15.1 `sandbox=None` wiring (not recommended); reverting the PR restores the donor path — **do not** revert without re-isolating the host to loopback.

---

### Stage 15.2 — Packaging, runtime profiles, dependency hygiene, and a CI that fails (Phase 1 hygiene)

**Goal.** A wheel that contains the program; a test suite that runs everywhere without external services; a CI whose summary fails when anything fails and which runs **all** tests; dependency and lockfile hygiene; the P1 hygiene items (B-06 … B-16, B-18 ratchet, B-24).

**ADR.** ADR-149 "Runtime profiles, in-memory event bus adapter, and CI as the release gate" (amends ADR-063 boot-registry semantics with profiles; adds `InMemoryEventBusAdapter` as a second `EventBusPort` adapter).

**Steps.**

1. `git checkout -b feat/arch-15-2-packaging-ci`.
2. **Packaging** (`pyproject.toml`): replace the static `[tool.setuptools] packages = [...]` with
   ```toml
   [tool.setuptools.packages.find]
   where = ["."]
   include = ["ports*", "adapters*", "kernel*", "plugins*", "governance*", "ops*"]
   exclude = ["*.tests*", "*.vendor*", "plugins.tektos.eval.tasks*"]
   ```
   (Stage 15.3 changes `where` to `["koinon/src", "."]` and `include` to `["koinon*", "plugins*", "extensions*", "ops*"]`.) Move `fastapi`, `uvicorn[standard]`, `python-multipart`, `sse-starlette` (if used: `rg -n sse_starlette kernel`) into `[project.dependencies]`. Declare missing runtime deps as extras: `mcp = ["aiohttp>=3.10", "mcp>=1.2"]`, `vision = ["pillow>=10", "pytesseract>=0.3"]`, `voice = ["edge-tts>=6.1", "numpy>=1.26", "pydub>=0.25", "faster-whisper>=1.0"]`, `research = ["openai>=1.40", "open-deep-research"]` (verify each on PyPI: `pip index versions <name>`), and guard the imports (`kernel/voice.py`, `kernel/mcp_client.py`, `adapters/vision/tesseract/adapter.py`, `plugins/zetesis/research/*`) with `try/except ImportError` + degrade (the ADR-101 pattern already used). `openhands_ext` (`kernel/learning/engine.py`) is not on PyPI — optional import with a `KNOWN_ISSUES` note (the OpenHands **SDK** extra `tekton-openhands` is declared in 15.12, not here). Replace `diskcache` with a `sqlite3`-backed cache in `plugins/tektos/repomap/{indexer,tags}.py` (**or** pin `diskcache>=5.6.4` if PyPI shows a fixed release: `pip index versions diskcache`; record which in BUILD_LOG). Pin dev tools exactly: `ruff==0.16.9`, `mypy==2.3.1`, `bandit==1.9.4`, `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `pip-audit`, `build`.
3. **Wheel smoke** — `scripts/wheel_smoke.sh`: `python -m build --wheel -o /tmp/kosmos_dist && python -m venv /tmp/wheel-venv && /tmp/wheel-venv/bin/pip install /tmp/kosmos_dist/kosmos-*.whl && /tmp/wheel-venv/bin/python -c "import kernel.app, plugins.tektos.runtime.turn_loop, adapters.relational_memory.postgres.adapter, adapters.sandbox.tektos.adapter, plugins.zetesis; print('wheel ok')"`. Add `tests/build/test_wheel_contents.py` that unzips the wheel and asserts every `__init__.py` package under `ports/adapters/kernel/plugins/governance` (minus excludes) is present.
4. **Runtime profiles** — new `kernel/profiles.py` (classified `Service`, subsystem `koinon`): `KOSMOS_RUNTIME_PROFILE` ∈ `test|local|production` (default `local`; `conftest.py` sets `test`). Profile defaults (env still overrides): `test` → `KOSMOS_EVENT_BUS=in_memory`, `KOSMOS_MEMORY_BACKEND=in_memory`, `KOSMOS_RELATIONAL_MEMORY=off`, `KOSMOS_SANDBOX=tektos`, `KOSMOS_OPERATOR_MODE=observer`; `local` → `KOSMOS_EVENT_BUS=valkey` with **fallback to in_memory on ConnectionRefused + warning** (`registry.errors["event_bus"]` set, `/health` reports `degraded`); `production` → no fallbacks, fail fast. `_boot_event_bus` (`kernel/app.py:637`) reads `KOSMOS_EVENT_BUS`.
5. **`InMemoryEventBusAdapter`** — `adapters/event_bus/in_memory/adapter.py` wrapping the existing `InMemoryStreamClient` (`adapters/event_bus/valkey/adapter.py:72`) so semantics (XADD/XREAD, consumer groups) match; `adapters/event_bus/in_memory/test_contract.py` reusing the Valkey contract test parametrized over both adapters (skip Valkey when 6379 is closed). Ledger entry: PATTERN-VENDORED from the repo's own Valkey adapter.
6. **Tests without services** — mark tests that truly need services: `@pytest.mark.valkey`, `@pytest.mark.postgres`, `@pytest.mark.llm`, `@pytest.mark.gpu`, `@pytest.mark.voice`, `@pytest.mark.vision` (the 8 unmarked live-service tests of §1.4 first; register in `pyproject.toml [tool.pytest.ini_options] markers`); default run excludes none but each marked test **skips itself** when its service is unreachable (helper `tests/_services.py::require("valkey")`). Fix B-10: `tests/kernel/test_adr141_s133_axioms_routes.py` uses `Path(__file__).resolve().parents[2] / "plugins/tektos/axioms"`. Fix the two default-scope failures: `adapters/relational_memory/postgres/test_contract.py::test_is_healthy_without_pool` (make `is_healthy()` return `False` without a pool — the ADR-101 contract) and `plugins/tektos/tests/test_stage_3_12_exit_gate.py` (use `shutil.which("ruff")`/`sys.executable -m ruff`). Redirect test-created SQLite files to `tmp_path` (fixtures for `data/tektos_rag.db`, `data/tektos_skills.db`); `git rm --cached data/*.db-shm data/*.db-wal`; add `data/**` to `.gitignore` except `data/.gitkeep`.
7. **Single pytest scope** — `testpaths = ["ports","adapters","kernel","plugins","ops","tests"]`; make `tests/` collectable together with the co-located tests (fix duplicate-basename collisions with `__init__.py` or `-p no:cacheprovider` + `rootdir`; `pytest --collect-only -q | tail -1` must equal the sum). Target: **~2,690 collected, 0 failed, skips only for unavailable services**.
8. **Lint/type ratchet** — `ruff check --fix ports adapters kernel plugins ops tests scripts` + `ruff format` in **one mechanical commit**; remaining findings fixed by hand or explicitly `per-file-ignores` with a comment; `ruff check .` = 0 in CI. mypy: keep `files = ["kernel","ports","adapters","plugins","ops"]`, add `scripts/mypy_ratchet.py` that fails CI if the error count exceeds `mypy_baseline.txt` (start at the actual count after fixing the easy 86 in `ports/`+`kernel/`; ratchet down every stage; zero required by 15.15).
9. **UI hygiene** — `cd ui && npm install next@16.3.6 && npm audit fix` (expect 0 critical/high); fix `ui/tests/03-tektos-plan-workflow.spec.ts:20` (TS2345); add scripts `"lint": "next lint"` or `eslint .` (install `eslint@9` + `eslint-config-next`), `"typecheck": "tsc --noEmit"`; delete `ui/pnpm-lock.yaml` (npm is what CI uses); commit `package-lock.json`.
10. **CI rewrite** — `.github/workflows/ci.yml`: matrix `python: [3.12, 3.13]`; services `valkey/valkey:8` (6379) and `pgvector/pgvector:pg18` (5432; env `KOSMOS_POSTGRES_URI=postgresql://kosmos:kosmos@localhost:5432/kosmos`) so the marked tests **run** in CI; jobs: `lint` (ruff check + format --check, whole repo), `typecheck` (mypy ratchet), `security` (bandit -lll, pip-audit --strict, `npm audit --audit-level=high`), `tests` (`pytest -q --cov=ports --cov=adapters --cov=kernel --cov=plugins --cov-report=xml --junitxml=…`, **no `needs: lint`**), `wheel-smoke`, `frontend` (`npm ci && npm run lint && npm run typecheck && npm run build`), `e2e` (boot `uvicorn kernel.app:app` with `KOSMOS_RUNTIME_PROFILE=test KOSMOS_OPERATOR_MODE=operator KOSMOS_OPERATOR_TOKEN=ci-token`, wait on `/health`, `npx playwright test`), `plugin-isolation`, `summary` that **fails** when any needed job fails (`if: always()` + `if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')` → `exit 1`). Add `.github/dependabot.yml` (pip, npm, github-actions weekly), `.github/workflows/codeql.yml` (python, javascript), `.pre-commit-config.yaml` (ruff, ruff-format, bandit -lll, check-added-large-files, `scripts/check_plugin_isolation.py`). `Makefile`: `ci-local` target running the same commands.
11. **Ops parity of env names**: document the new env vars in `docs/ops/env-catalogue.md` (§4.2) and `ops/systemd/README.md`.

**Tests.** Whole suite; `scripts/wheel_smoke.sh`; `make ci-local`.

**Exit gate.** `pytest -q` (no args) → 0 failed locally with no services and in CI with services; `gh run view --repo rmholston420/kosmos-lms <run> --json conclusion` → `success` for the PR; wheel `__init__.py` count ≥ 110; `ruff check .` → 0; `npm audit --audit-level=high` → 0; `git ls-files data/` → only `.gitkeep`; three consecutive green runs on `main` after merge (`gh run rerun` twice).

**Commits.** `build: Stage 15.2 — packages.find, base deps, extras, pinned dev tools (ADR-149)`; `feat(koinon): Stage 15.2 — runtime profiles + InMemoryEventBusAdapter`; `test: Stage 15.2 — service markers, tmp_path data dirs, fix axioms path + 2 failing tests`; `style: Stage 15.2 — ruff --fix + ruff format (mechanical)`; `ci: Stage 15.2 — full-scope tests, services, wheel smoke, failing summary, Dependabot, CodeQL`; `build(ui): Stage 15.2 — next 16.3.6, lint/typecheck scripts, single lockfile`.

**Logs.** BUILD_LOG per commit; DEBUG_LOG entries for B-09 (`ConnectionRefused 6379`), B-10; KNOWN_ISSUES cleanup; PORTING_LEDGER entry for `adapters/event_bus/in_memory`.

**Rollback.** `KOSMOS_EVENT_BUS=valkey` + `KOSMOS_RUNTIME_PROFILE=production` reproduce pre-15.2 boot behavior; CI changes are revert-safe.

---

### Stage 15.3 — Layout Step A: `koinon/`, `plugins/`, `extensions/`, `policies/`, renames (Phase 1 Koinon core)

**Goal.** The repository has the report's shape: `koinon/src/koinon/` (Python package `koinon`), `plugins/<subsystem>/` for all eleven subsystems (scaffolds where nothing exists yet), `extensions/adapters/`, `policies/`, `skills/shared/`, `tests/{architecture,integration,policy,conformance}`; `tektos`→`tekton`, `praxis`→`koinon.policy.praxis`, `phrouros`→`koinon.kernel.sema.detectors.phrouros`; imports, tooling, CI, systemd, docs rewritten by a script; the test set is identical before and after. Zero behavior change.

**ADR.** ADR-150 "Repository layout: `koinon` package, subsystem plugins, extension adapters, two-step migration" (amends the Stage 0.1 layout decision recorded in Build-Spec v26 §3 — there is no earlier layout ADR; records §2.16, the placement table, the transitional `koinon.adapters` package and the shim policy).

**Preconditions.** Stage 15.2 merged with three green `main` runs. `pytest --collect-only -q | tail -1` recorded as `BEFORE_COUNT` in BUILD_LOG.

**Steps.**

1. `git checkout -b feat/arch-15-3-layout-step-a`.
2. Write `scripts/migrate_layout.py` (idempotent, dry-run by default; classified `Tool`):
   - `git mv` per the placement table in §2.16 (kernel → `koinon/src/koinon/kernel`; ports → `koinon/src/koinon/contracts/ports`; `ports/event_envelope.py` → `koinon/src/koinon/contracts/events/envelope.py` + re-export shim; adapters → `koinon/src/koinon/adapters` (transitional); `plugins/tektos` → `plugins/tekton`; `plugins/praxis` → `koinon/src/koinon/policy/praxis`; `plugins/phrouros` → `koinon/src/koinon/kernel/sema/detectors/phrouros`; `governance/constitution` → `policies/constitution`); create `koinon/src/koinon/__init__.py` (`__version__`), `koinon/tests/__init__.py`, and empty packages with README stubs for `contracts/{events,commands,schemas}`, `workflows`, `capabilities`, `tools`, `hooks`, `artifacts`, `mneme`, `aisthesis`, `mesiteia`, `kernel/{kybernesis,harmonia,sema,telos,euthyna,pronoia}`.
   - Scaffold plugins: for each of `synedrion gnosis poros epimeleia axiomeon holon agora asphaleia noesis`: `plugins/<name>/{__init__.py, plugin.py, components/__init__.py, praxis/__init__.py, tests/__init__.py, README.md}` where `plugin.py` declares a `PluginManifest` stub (`name`, `subsystem`, `provides=()`, `requires=()`, `emits=()`, `consumes=()`, `owned_data=()`, `trust_state="core"`, `enabled=False`) — the manifest class itself lands in 15.4; until then the stub is a dataclass in `plugin.py` that 15.4 replaces. `plugins/tekton/plugin.py` and `plugins/zetesis/plugin.py` gain the same stub fields. Create `extensions/__init__.py`, `extensions/adapters/__init__.py`, `skills/shared/README.md`, `policies/{capabilities,protected-paths,model-use,exceptions,tests}/README.md`, `tests/{architecture,integration,policy,conformance}/__init__.py`.
   - Rewrite imports with `libcst` (dev dep) or a regex pass restricted to `^\s*(from|import)\s+(ports|adapters|kernel|plugins\.tektos|plugins\.praxis|plugins\.phrouros|governance)\b` → the new module paths (`kernel` → `koinon.kernel`, `ports` → `koinon.contracts.ports`, `adapters` → `koinon.adapters`, `plugins.tektos` → `plugins.tekton`, `plugins.praxis` → `koinon.policy.praxis`, `plugins.phrouros` → `koinon.kernel.sema.detectors.phrouros`, `governance` → `koinon.policy.praxis.constitution_data` path constant); rewrite **quoted module strings** (`"kernel.app:app"`, `importlib.import_module("plugins.tektos…")`, `patch("kernel.…")`, `monkeypatch.setattr("adapters.…")`); rewrite `sys.path` hacks in `conftest.py` (delete; rely on `pip install -e .`); rewrite string constants that name env vars **only** where the variable is renamed (`TEKTOS_FS_ROOT` stays until 15.15).
   - Rewrite tooling: `pyproject.toml` (`[tool.setuptools.packages.find] where=["koinon/src","."]`, `include=["koinon*","plugins*","extensions*","ops*"]`, `exclude=["*.tests*","*.vendor*","plugins.tekton.eval.tasks*"]`; mypy `files`; pytest `testpaths=["koinon","plugins","extensions","ops","tests"]`; ruff `src=["koinon/src","."]`; coverage `source=["koinon","plugins","extensions"]`), `Makefile`, `.github/workflows/*.yml` (`uvicorn koinon.kernel.app:app`), `ops/systemd/kosmos-kernel.service` (`ExecStart=… koinon.kernel.app:app`), `scripts/check_plugin_isolation.py` (roots `plugins/*`, `extensions/adapters/*`, `koinon/src/koinon`; rules of §0.1 item 3), `.perplexity/**/*.md`, `AGENTS.md` (+ `git mv plugins/tektos/AGENTS.md plugins/tekton/AGENTS.md`), `docs/**` live documents only (Build-Spec v26 §3 layout, Build-Sequence, GLOSSARY, this plan; **not** archived ADRs).
   - Print a diff summary; `--apply` performs it.
3. Run `python scripts/migrate_layout.py --apply`; `pip install -e ".[dev,ui]"`; `pytest --collect-only -q | tail -1` must equal `BEFORE_COUNT` (+ the new architecture tests below); `pytest -q` → 0 failed; `ruff check . && ruff format --check .`; `python scripts/check_plugin_isolation.py`; `scripts/wheel_smoke.sh` (imports now `koinon.kernel.app`, `plugins.tekton.runtime.turn_loop`, …); `rg -n "^\s*(from|import) (ports|adapters|kernel|governance)\b|plugins\.(tektos|praxis|phrouros)\b" --glob '!docs/archive/**' --glob '!BUILD_LOG.md' --glob '!DEBUG_LOG.md' .` → 0.
4. **Architecture tests** (`tests/architecture/`): `test_layout.py` (no top-level legacy packages; every `plugins/<name>` has `plugin.py`, `components/`, `praxis/`, `tests/`, `README.md`); `test_import_rules.py` (Koinon never imports `plugins.*` or `extensions.*`; plugins never import other plugins; `extensions.adapters.*` import only `koinon.contracts.*` and third-party code) implemented with `grimp` (MIT) or a stdlib AST walk; `test_no_llm_in_deterministic_kinds.py` and `test_component_classification.py` are added in 15.4 once the taxonomy registry exists.
5. Compatibility: top-level `kernel/`, `ports/`, `adapters/`, `plugins/tektos` **are not recreated** (a stale editable install would silently import the old tree). Instead, `koinon/src/koinon/_compat.py` installs `sys.modules` aliases (`ports` → `koinon.contracts.ports`, `kernel` → `koinon.kernel`, `adapters` → `koinon.adapters`, `plugins.tektos` → `plugins.tekton`) when `KOSMOS_LEGACY_IMPORT_ALIASES=1`, emitting `DeprecationWarning`; used only by external scripts on Colossus during the cut-over week.
6. Colossus cut-over note (`docs/ops/layout-migration.md`): `pip install -e .` again in `.venv`; `sudo systemctl daemon-reload && sudo systemctl restart kosmos-kernel`; verify `/health`.

**Tests.** The entire suite (unchanged set) + `tests/architecture/test_layout.py`, `tests/architecture/test_import_rules.py`.

**Exit gate.** Same test count (+ architecture tests) and 0 failures; CI green; systemd unit boots on Colossus with the new module path (`curl 127.0.0.1:8000/health`); `git log --stat -1` shows only renames + import rewrites (spot-check 10 files with `git diff -M --word-diff`); `ls plugins` prints exactly the eleven subsystem directories (+ `__init__.py`).

**Commits.** `refactor(koinon): Stage 15.3 — move kernel/ports/adapters into koinon/src/koinon; tektos→tekton; praxis→koinon.policy; phrouros→sema detectors (mechanical, ADR-150)` (one commit for the move + rewrite so `git log --follow` works); `feat(koinon): Stage 15.3 — plugin scaffolds, extensions/, policies/, skills/, tests taxonomy, architecture tests`; `build: Stage 15.3 — tooling/CI/systemd paths for the koinon layout`; `docs: Stage 15.3 — layout migration notes`.

**Logs.** BUILD_LOG with `BEFORE_COUNT`/`AFTER_COUNT`; SESSION_HANDOFF.

**Rollback.** `git revert -m 1 <merge>`; on Colossus `pip install -e .` again. No data migration involved.

---
### Stage 15.4 — Koinon contracts (Syndesmos), taxonomy registry, plugin manifests, quarantine states, local Praxis helpers (Phase 1)

**Goal.** Every component has a classified kind; every plugin has a manifest declaring what it provides, requires, emits, consumes, and owns; typed command/event/capability/workflow schemas exist in one place; agent-generated extensions have a quarantine state; the recursive S1 helpers exist so later plugins instantiate their local planning/execution/verification/escalation from Koinon instead of re-inventing them. No persistence yet.

**ADR.** ADR-151 "Koinon contracts: component taxonomy registry, plugin manifest and trust states, typed command/event schemas, local Praxis helpers" (structural: new `koinon.contracts` surface; records the decision rule of §2.6).

**Steps.**

1. `git checkout -b feat/arch-15-4-koinon-contracts`.
2. **Taxonomy** — `koinon/src/koinon/contracts/taxonomy.py`: `ComponentKind` enum (`AGENT, FUNCTION, WORKFLOW, CONTROLLER, SERVICE, TOOL, WORKER, MONITOR, DETECTOR, GATE, REGISTRY, HOOK, ADAPTER`), `VsmFunction` enum (`PRAXIS, HARMONIA, KYBERNESIS, EUTHYNA, PRONOIA, TELOS, SEMA, KOINON`), `Subsystem` enum (the eleven + `koinon`), `@component(kind, subsystem, vsm, name=None)` decorator writing to a process-wide `ComponentRegistry` (`koinon.kernel.registry.ComponentRegistry`) and setting `__kosmos_component__` metadata; `DETERMINISTIC_KINDS` = all kinds except `AGENT`, `FUNCTION`. Naming rule: class name must end with the kind's suffix (`…Gate`, `…Controller`, …); a `Worker` that hosts an agent declares `hosts_agent=True`.
3. **Plugin manifest** — `koinon/src/koinon/contracts/manifest.py`: `PluginManifest(name, subsystem, version, provides: tuple[Capability,…], requires: tuple[Capability,…], emits: tuple[EventType,…], consumes: tuple[EventType,…], owned_data: tuple[DataOwnership,…], components: tuple[ComponentRef,…], trust_state: Literal["core","vendored","quarantined","promoted"], enabled: bool)`; `koinon/src/koinon/kernel/registry.py::PluginRegistry` loads `plugins/*/plugin.py` manifests at boot (discovery via `importlib` over the eleven names — no filesystem scan), validates `requires ⊆ union(provides)`, refuses to enable a `quarantined` plugin, and exposes `describe()` for §15.8 discovery. `ExtensionManifest` (same shape, `kind ∈ tool|hook|skill|policy|workflow|adapter`) for `extensions/adapters/*` and for quarantined items under `data/quarantine/`.
4. **Typed contracts** — `koinon/src/koinon/contracts/commands/` (`Command` base: `command_id`, `workflow_id`, `issued_by (subject)`, `capability_token`, `idempotency_key`; concrete commands per aggregate as frozen dataclasses), `contracts/events/` (`envelope.py` moved in 15.3 + `catalogue.py` listing every `io.kosmos.*` type constant of §4.3 with its payload dataclass; JSON Schemas generated into `contracts/schemas/events/*.json` by `python -m koinon.contracts.schemas.generate` and diff-checked in CI), `contracts/capabilities.py` (`Capability(scope, resource_globs, command_classes, network)`, `CapabilityToken` shape), `contracts/workflows.py` (`WorkflowDefinition`, `StepSpec`, `ApprovalSpec`, typed IO), `contracts/artifacts.py` (`ArtifactRef`, `ArtifactKind`, `PromotionStage`), `contracts/state.py` (the orthogonal enums of §2.12 + `status_summary()` pure function + `transition(state, event)` with Hypothesis property tests: no transition leaves the allowed graph; terminal states absorb).
5. **Local Praxis helpers** — `koinon/src/koinon/kernel/praxis_local.py`: composable, deterministic base classes for the recursive S1 set — `LocalPlannerFunction` (base; concrete plugins supply the prompt/schema), `ExecutorWorker`, `ToolGateway` (wraps the governed tool registry with a token), `LocalCoordinatorService` (Harmonia client), `BudgetController` (Kybernesis client), `LocalVerifierGate`, `AuditHook`, `TelemetryEmitter` (Aisthesis), `PolicyInterpreterFunction`, `SemaEscalator`. Each is a thin client of a Koinon port and is what `plugins/<name>/praxis/` subclasses in 15.11/15.12.
6. **Configuration service** — `koinon/src/koinon/kernel/config.py` (`Service`): typed settings loaded from env + `config/*.yaml`, profile-aware (15.2 `profiles.py` folded in), secrets resolved only through `SecretsPort` (never read `KOSMOS_*_TOKEN` directly outside this module and `operator_auth`).
7. **Hooks** — `koinon/src/koinon/hooks/registry.py` formalizes `kernel/hooks.py::HookRegistry` as `HookRegistry(Registry)` with typed `Hook` subscriptions (`on: EventType`, `handler`, `capability`), and a quarantine check (a `Hook` from a quarantined extension is registered but never fired).
8. **Classify existing code** — add `@component(...)` to every class in `koinon/src/koinon/{kernel,tools,policy}` that is a real component (allowlist the rest in `tests/architecture/classification_allowlist.txt` with a reason), and to `plugins/zetesis` and `plugins/tekton` top-level components; write `tests/architecture/test_component_classification.py` and `tests/architecture/test_no_llm_in_deterministic_kinds.py` (§2.6).

**Tests.** `koinon/tests/contracts/test_taxonomy.py` (decorator, suffix rule, registry), `test_manifest.py` (validation, quarantine refusal, requires/provides), `test_state_machines.py` (Hypothesis), `test_schema_generation.py` (generated schemas match committed), architecture tests; full suite.

**Exit gate.** `python -c "from koinon.kernel.registry import PluginRegistry; print(PluginRegistry.discover().describe())"` lists eleven manifests (nine `enabled=False` scaffolds); architecture tests green with an allowlist ≤ 120 lines (recorded in BUILD_LOG as the ratchet start); CI green.

**Commits.** `feat(contracts): Stage 15.4 — ComponentKind taxonomy, @component registry, naming rule (ADR-151)`; `feat(contracts): Stage 15.4 — PluginManifest/ExtensionManifest, trust states, PluginRegistry`; `feat(contracts): Stage 15.4 — typed commands, event catalogue + generated schemas, capabilities, workflow definitions, orthogonal state`; `feat(koinon): Stage 15.4 — local Praxis helpers, config service, typed HookRegistry`; `test(architecture): Stage 15.4 — classification + no-LLM-in-deterministic-kinds tests`.

**Logs.** BUILD_LOG; ADR-151 indexed; PORTING_LEDGER (`grimp` if adopted).

**Rollback.** Additive; the decorator is metadata only.

---

### Stage 15.5 — Mneme: PostgreSQL journal + outbox, CloudEvents, artifact & provenance services, projections (Phase 1)

**Goal.** Koinon owns the event log, operational state, artifact service and provenance service: a `JournalPort` with Postgres (canonical) and SQLite (test) adapters; the transactional outbox relaying to `EventBusPort`; `EventEnvelope` upgraded to CloudEvents; content-addressed artifacts with promotion stages and immutable accepted versions; provenance edges; projection rebuild proven byte-identical. Existing memory adapters re-homed into `koinon.mneme`.

**ADRs.** ADR-152 "Mneme event journal on PostgreSQL with transactional outbox" (amends ADR-102: the relational store gains the `mn_*` schema and a second Alembic environment); ADR-153 "CloudEvents 1.0 envelope and `io.kosmos.*` event grammar" (amends ADR-023/ADR-086); ADR-154 "Artifact service and provenance service: `ArtifactStorePort` over `BlobStore`, promotion stages, immutable accepted identity" (promotes the ADR-096 helper to a formal port adapter).

**Steps.**

1. `git checkout -b feat/arch-15-5-mneme`.
2. **CloudEvents envelope** — extend `koinon/src/koinon/contracts/events/envelope.py` per §2.10 (new optional fields incl. `provenance`/`confidence`, `to_cloudevent()`, `from_cloudevent()`, `canonical_json()` via `rfc8785`, `content_hash()`); vendor `contracts/schemas/cloudevents-1.0.json` (CloudEvents JSON Schema, Apache-2.0 — ledger entry). Legacy producers unchanged (defaults fill the new fields).
3. **JournalPort** — `koinon/src/koinon/contracts/ports/journal.py` (§2.8). Adapters: `koinon/src/koinon/mneme/journal/postgres/` (asyncpg; reuse the pool pattern from `koinon/adapters/relational_memory/postgres/adapter.py`; Alembic env `version_table="mn_alembic_version"`; migration `001_mn_journal.py` creating `mn_event_journal`, `mn_outbox`, `mn_snapshots` + append-only trigger + hash chain; `002_mn_projections.py` creating the projection tables of §2.9 with RLS enabled + permissive policy; `003_mn_artifacts.py` creating `mn_artifacts`, `mn_provenance`) and `koinon/src/koinon/mneme/journal/sqlite/` (aiosqlite, WAL, same trigger via `RAISE(ABORT)`; test profile only). `append()` is one transaction: insert events (each with `provenance` + `confidence`, rejected at the protocol layer if missing — zero-trust rule), insert outbox rows, update `mn_workflow_state.last_seq`, check `expected_version`. Contract test parametrized over both adapters (Postgres part `@pytest.mark.postgres`).
4. **Outbox relay** — `koinon/src/koinon/mneme/journal/outbox_relay.py` (`Service`): background task (started in lifespan when the journal is on) claiming ≤100 rows (`FOR UPDATE SKIP LOCKED`), publishing each `to_cloudevent()` to `EventBusPort` (`stream = "kosmos.journal"` + legacy per-type streams for existing consumers) and to in-process projection subscribers; ack/fail with exponential backoff (1 s → 5 min, `attempts ≤ 20` then park + `io.kosmos.mneme.outbox.parked.v1`); idempotent consumers key on `event_id`. Metrics: `kosmos_mneme_outbox_lag_seconds`, `kosmos_mneme_outbox_backlog`.
5. **Artifact + provenance services** — `koinon/src/koinon/contracts/ports/artifact_store.py`; `koinon/src/koinon/artifacts/fs_store.py` (`FsArtifactStoreAdapter` over `BlobStore`, `KOSMOS_BLOB_ROOT` default `data/artifacts`), `artifacts/in_memory.py`, `artifacts/service.py::ArtifactService` (typing, signatures via the Telos signing key from 15.7 — until then `signature=None`, producer + workflow identity, lineage, promotion `candidate→verified→accepted→released→retired` with `accepted`/`released` rows immutable by trigger, retention policy, reproduction metadata), `artifacts/provenance.py::ProvenanceService` (`derived_from`, `produced_by`, `verified_by`, `authorized_by` edges in `mn_provenance`; `lineage(digest) -> graph`). Contract test: put/get/verify/idempotent put/corruption detection by flipping a byte/promotion immutability.
6. **Projections** — `koinon/src/koinon/kernel/kybernesis/projections/` (`OperationalStateProjector`, `Service`): applies journal events to the `mn_*` tables; `python -m koinon.mneme.rebuild_projections --from-seq 0` truncates projections (never the journal) and replays; test: 200 mixed events → dump → rebuild → dump → identical.
7. **Re-home Mneme adapters (Step B)** — `koinon/adapters/{relational_memory/*,memory/dozerdb,vector/qdrant,embeddings/*,data/*}` → `koinon/src/koinon/mneme/{relational,graph,vector,embeddings}/` and `koinon/src/koinon/artifacts/blobs.py`; shims with `DeprecationWarning`; `kernel/rag_retriever.py`, `kernel/tektos_data_services.py` → `koinon/src/koinon/mneme/{rag_retriever,data_services}.py`.
8. **Boot** — `_boot_journal()` gated `KOSMOS_JOURNAL=postgres|sqlite|off` (profile defaults: `test`→`sqlite` at `tmp`, `local`→`postgres` if `KOSMOS_POSTGRES_URI` set else `sqlite` at `data/journal.db` with a warning, `production`→`postgres`); `_boot_artifacts()`; `/health` subsystems `journal`, `outbox`, `artifacts`.
9. Minimal API for the slice (full gateway in 15.8): `POST /api/v1/workflows` (create a `mission` workflow record — no execution yet), `GET /api/v1/workflows/{id}`, `GET /api/v1/workflows/{id}/events?after_seq=`, `GET /api/v1/artifacts/{digest}` — operator token required for POST.

**Tests.** `koinon/tests/mneme/**` (journal contract both adapters, outbox relay with in-memory bus, rebuild identity), `koinon/tests/artifacts/**`, `koinon/tests/contracts/test_cloudevents_roundtrip.py` + schema validation of every catalogue event, `tests/integration/api/test_v1_workflows_slice.py`.

**Exit gate.** Both journal adapters pass the contract; on Colossus `alembic -c koinon/src/koinon/mneme/journal/postgres/alembic.ini upgrade head` succeeds against Postgres 18/17 (`psql … -c "\d mn_event_journal"`); `UPDATE mn_event_journal SET data='{}' WHERE seq=1` fails with the append-only error; `UPDATE mn_artifacts SET digest='x' WHERE stage='accepted'` fails; rebuild identity test passes; outbox lag < 1 s with Valkey; CI green with the pgvector service.

**Commits.** `feat(contracts): Stage 15.5 — CloudEvents envelope + io.kosmos.* schemas (ADR-153)`; `feat(mneme): Stage 15.5 — JournalPort, Postgres + SQLite adapters, append-only trigger, outbox (ADR-152)`; `feat(artifacts): Stage 15.5 — ArtifactStorePort, ArtifactService promotion stages, ProvenanceService (ADR-154)`; `feat(kybernesis): Stage 15.5 — OperationalStateProjector + rebuild_projections`; `refactor(mneme): Stage 15.5 — re-home memory/vector/embeddings/blob adapters (shims)`; `feat(api): Stage 15.5 — /api/v1/workflows + /artifacts slice`.

**Logs.** BUILD_LOG; PORTING_LEDGER (CloudEvents schema); ADR-152/153/154 indexed.

**Rollback.** `KOSMOS_JOURNAL=off` disables the subsystem; the `mn_*` schema is additive (drop with `alembic downgrade base` in the `mn_` env only).

---

### Stage 15.6 — Workflow engine, Kybernesis controllers, Harmonia, Sema (no LLM), Euthyna ledger, durability drills (Phase 1)

**Goal.** Koinon's durable workflow engine and the deterministic VSM mechanisms exist and are proven: `WorkflowPort` with YAML definitions; Kybernesis owns state and drives every workflow through `OperationsController.regulate(workflow_id)`; Harmonia coordinates leases/concurrency/oscillation; Sema's ten components run without any model; Euthyna has a tamper-evident audit ledger; workflows survive kernel/Postgres/Valkey crashes. Agent and coding activities are declared here but implemented in 15.10/15.12 via their ports; at this stage the only activities are tools, gates, decisions, waits.

**ADR.** ADR-155 "Koinon workflow engine (`WorkflowPort`), Kybernesis controllers and gates, Harmonia coordination, Sema algedonic channel without LLM dependency, Euthyna audit ledger" (supersedes the *role* of ADR-104 `TektosTurnLoop` as the autonomy driver — the loop remains a compatibility façade until 15.15; amends ADR-108 manager scope: the S3 manager's control duties move to Kybernesis, agent-supervision duties to Epimeleia).

**Steps.**

1. `git checkout -b feat/arch-15-6-workflow-kybernesis-sema`.
2. **WorkflowPort + engine** — `koinon/src/koinon/contracts/ports/workflow.py` (§2.8); `koinon/src/koinon/workflows/local/adapter.py::LocalDurableWorkflowAdapter` (state derived from the journal: `WorkflowState{lifecycle, control, phase, step, waiting_on, retries, approvals}`; `tick()` pure given (state, latest events) → `NextAction ∈ {RunTool, RunGate, RunFunction, RunAgent, RunCodingTask, RunVerification, RequestDecision, AcquireLease, Checkpoint, Compensate, Wait, Finish}`); `workflows/in_memory/adapter.py`; definitions as YAML under `workflows/` with versioning (`definition_id@version`), per-step timeouts, retry policies (bounded, typed: `transient|resource|policy|logic` from the Blueprint taxonomy), compensation steps, human approval steps (`approve()` signal), event-driven continuation (a step may `waiting_on: event_type`), typed inputs/outputs validated against `contracts/workflows.py`. Ships: `workflows/mission.yaml` (CAPTURE → CLARIFY → PLAN → BUILD → VERIFY → RELEASE → OBSERVE → LEARN), `workflows/change_control.yaml`, `workflows/extension_promotion.yaml`, `workflows/self_improvement.yaml` (proposal → controlled experiment → independent verification → authorized promotion; the last step requires a human decision until Stage 16), `workflows/incident.yaml`, `workflows/recovery.yaml`.
3. **Kybernesis** — `koinon/src/koinon/kernel/kybernesis/`: `OperationsController.regulate(workflow_id) -> RegulationOutcome` — (1) load state (snapshot + events); (2) Sema `ThresholdMonitor.evaluate(workflow_id)` → maybe `CONTAINED`; (3) if `Control ∈ {PAUSED, BLOCKED, CONTAINED}` → `Wait`; (4) `next = workflow.tick()`; (5) `PolicyPort.decide(action=next.kind, …)` (a permissive in-process stub until 15.7 installs OPA; the call site exists now) → deny ⇒ `RequestDecision`; (6) Harmonia `LeaseRegistry.acquire` for the step's declared resources; (7) dispatch **one** activity with `asyncio.wait_for(step, per_step_timeout)`; (8) journal `io.kosmos.kybernesis.step.completed.v1`; (9) return `next_delay`. `WorkflowLifecycleController` (create/start/pause/resume/cancel with the 10 s grace + `os.killpg` on any sandbox run), `PortfolioWorkflow` (prioritization data; `KOSMOS_MAX_CONCURRENT_WORKFLOWS` default 1 on Colossus), `ResourceController` (the only writer of `mn_leases`; consumes Poros recommendations from 15.9), `AcceptanceGate` and `PromotionGate` (interfaces + evidence-tier rules; consumers in 15.12), `ChangeControlWorkflow` runner, `IncidentWorkflow` runner, `RecoveryCoordinator` (boot-time: every `RUNNING` workflow without a `step.completed` within `2 × per_step_timeout` → `RECOVERING`, journals `io.kosmos.kybernesis.recovered.v1`, marks orphaned tool invocations `aborted`, resumes or blocks), `RollbackService` (interface; Tekton implementation in 15.12), `CommitmentRegistry` (what each workflow promised: claims + budgets + deadlines), `apex/` (moved from `koinon.policy.praxis.apex`: approval engine/tiers/tokens/scheduler — the human-decision executor; `PraxisApprovalResolverAdapter` becomes `ApexApprovalResolverAdapter`).
4. **Essential variables → Sema thresholds** — `koinon/src/koinon/kernel/sema/thresholds.py`: per-workflow bands (charter-overridable): `iterations ≤ 40`, `model_calls ≤ 40`, `tool_calls ≤ 120`, `identical_tool_signature_repeats ≤ 3`, `no_progress_steps ≤ 4`, `repair_attempts ≤ 8`, `wall_time ≤ 45 min`, `tokens_total ≤ 400k`, `test_pass_ratio ≥ baseline`, `sandbox_kills ≤ 3`, `thermal` (from `ThermalPort`), `gpu_vram_headroom_mb ≥ 1024`; values map onto the existing `LoopCaps` so `LoopSafetyPort` is reused.
5. **Sema** — `koinon/src/koinon/kernel/sema/`: `ThresholdMonitor`, `IntegrityTripwire` (hashes of `policies/**`, constitution signatures, gate configs, `koinon.capabilities` modules at boot and every 60 s; any mismatch → severity `critical`), `AnomalyDetector` (wraps the twelve immune detectors + phrouros `loop`/`unauthorized_tool`), `SeverityClassifier` (deterministic table: credential exposure, sandbox escape, gate/policy tampering, unauthorized self-modification, corrupted provenance, data-loss risk, runaway resources, security compromise, perishable opportunity → `info|warning|high|critical`), `CircuitBreaker` (flips `Control=CONTAINED` for the workflow, or globally on `critical`; blocks tool/model/artifact writes), `EscalationRouter` (→ `NotificationPort.deliver_algedonic` tiers, `/api/algedonic` WS, Kybernesis `IncidentWorkflow`, Telos `HumanAuthorizationWorkflow`), `IncidentSnapshotter` (journal seq, worktree `git status`, process list, last 200 events → artifact `kind=incident_snapshot`), `RecoveryMonitor`, `AlertDeduplicator`, `SemaLedger` (append-only `mn_sema_ledger`, hash-chained). **All classified deterministic; `tests/conformance/test_sema_without_llm.py` boots the kernel with `KOSMOS_LLM_BASE_URL=http://127.0.0.1:1` (connection refused) and asserts every Sema trigger still produces a ledger entry, a containment, and an algedonic delivery.**
6. **Harmonia** — `koinon/src/koinon/kernel/harmonia/`: `LeaseRegistry` (files/paths, ports, GPU slots, branches; TTL; `mn_leases` written only via Kybernesis `ResourceController`), `ConcurrencyController` (per-resource limits), `BackpressureMonitor` (outbox backlog, queue depth → `io.kosmos.harmonia.backpressure.v1`), `DeduplicationService` (idempotency keys for commands), `DeadlockDetector` (wait-for graph over leases), `OscillationDetector` (wraps loop-safety repetition detection; emits to Sema). Harmonia **never** sets priorities, approves, or promotes (architecture test: no imports of gates/approval modules).
7. **Euthyna ledger + validation skeleton** — `koinon/src/koinon/kernel/euthyna/`: `AuditLedger` (append-only `mn_audit_ledger`, hash-chained, separate signing key from Sema), `EvidenceValidationService` (tier rules, refutation wins), `ProvenanceVerificationService` (re-hash artifacts, verify `mn_provenance` chain), `RandomInspectionWorkflow` (samples accepted artifacts for re-verification), `DriftDetector`/`RegressionDetector` (interfaces; Tekton feeds them in 15.12).
8. **Re-home Step B items** — `koinon/adapters/event_bus/*` → `koinon.mesiteia.event_bus`; `notification/kernel` → `kernel.sema.transport`; `immune/tektos`, `loop_safety/tektos` → `kernel.sema.detectors.immune`, `kernel.harmonia.loop_safety`; `observability/otel_stack` → `koinon.aisthesis.otel`; `approval_resolver/praxis` → `kernel.kybernesis.apex`; shims.
9. **Durability drills** — `tests/integration/recovery/`: fake activities + SQLite/Postgres journal: kill kernel task mid-activity, mid-append (rollback — no partial events), Valkey down (backlog grows, relay resumes, no loss), Postgres down (`ready` 503; on return, resume), `RECOVERING` path, cancellation mid-activity, compensation path, approval timeout. Each asserts: journal hash chain valid (`python -m koinon.mneme.verify_journal`), projection rebuild identical, no orphan tasks. `scripts/backup_kosmos.sh` (`pg_dump -Fc` + `tar` of `data/artifacts` with digest manifest) and `scripts/restore_kosmos.sh` into a scratch database; `tests/integration/recovery/test_backup_restore.py` (Postgres-marked).
10. **Façades** — `TektosTurnLoop.run_turn()` and `TektosAgent.run()` (now `plugins.tekton.*`): when `KOSMOS_TEKTON_AUTONOMY=on`, create/advance a `mission` workflow through Kybernesis (activities limited to what exists at this stage) and return a `TurnResult` compatible with today's callers; when `off`, unchanged; `DeprecationWarning` on the old paths (retired 15.15).

**Tests.** `tests/conformance/test_workflow_engine.py` (definitions, retries, compensation, approvals, event-driven continuation), `tests/conformance/test_kybernesis_termination.py` (Hypothesis `RuleBasedStateMachine` with fake activities: every run terminates within thresholds; no action after `CANCELLED`; `CONTAINED` blocks tools), `tests/conformance/test_sema_without_llm.py`, `tests/conformance/test_harmonia_rules.py`, `koinon/tests/euthyna/test_ledger_chain.py`, recovery matrix, full suite.

**Exit gate.** Termination test passes 1,000 examples; Sema-without-LLM conformance green; fault matrix (≥ 9 cases) green in CI (SQLite) and on Colossus (Postgres); backup/restore drill passes; `verify_journal` valid on the Colossus journal; CI green.

**Commits.** `feat(workflows): Stage 15.6 — WorkflowPort, local durable adapter, YAML definitions (ADR-155)`; `feat(kybernesis): Stage 15.6 — OperationsController, lifecycle/resource controllers, gates, commitments, recovery, apex re-home`; `feat(sema): Stage 15.6 — ten deterministic Sema components + thresholds + ledger (no-LLM conformance)`; `feat(harmonia): Stage 15.6 — leases, concurrency, backpressure, dedup, deadlock, oscillation`; `feat(euthyna): Stage 15.6 — audit ledger, evidence/provenance validation, inspection workflow`; `refactor(koinon): Stage 15.6 — re-home event bus/notification/immune/loop-safety/otel/approval adapters (shims)`; `test(recovery): Stage 15.6 — fault-injection matrix + backup/restore`; `refactor(tekton): Stage 15.6 — TektosTurnLoop/TektosAgent façades behind KOSMOS_TEKTON_AUTONOMY`.

**Logs.** BUILD_LOG; ADR-155; `git mv` list in BUILD_LOG.

**Rollback.** `KOSMOS_TEKTON_AUTONOMY=off` (default) — legacy behavior; `KOSMOS_RECOVERY_AUTORESUME=0` keeps workflows `RECOVERING` for manual resume.

---
### Stage 15.7 — Asphaleia: identity, capabilities & tokens, OPA/Rego policy tree, Telos authority chain, protected paths, secrets, sandbox isolation (Phase 2)

**Goal.** Narrow explicit capabilities replace ambient authority. A `PolicyPort` with OPA v1.21.0 as the canonical PDP and the `policies/` tree under version control; capability grants and short-lived signed capability tokens cited by every tool call, model call and artifact write; the Telos authority chain (human → signed constitution → deterministic policy → bounded interpretation → authorization workflows → capability enforcement) is code; protected paths with an Integrity Tripwire; a secrets broker; per-workflow worktrees, process supervision, path policy, and the `bwrap` tier; the `praxis` package split into `koinon.policy.constitution` (Telos) and `koinon.kernel.kybernesis.apex` (human-decision executor). `plugins/asphaleia` becomes enabled.

**ADRs.** ADR-156 "Asphaleia and Telos: PolicyPort (OPA/Rego), capability grants and tokens, autonomy ceilings A0–A4, authority chain, protected paths, secrets broker" (amends ADR-033 approval tiers: a tier is an *obligation* a policy decision can attach; the apex engine remains the executor); ADR-157 "Isolation ladder: worktree + process supervisor (default), Bubblewrap (opt-in; production default), Docker only for OpenHands untrusted repos, microVM deferred" (amends ADR-082/ADR-093; `SandboxRequest` gains `cwd` confinement, `env_allowlist`, `tier`, `allowed_roots`, `process_group`).

**Preconditions.** 15.6 merged. On Colossus: `sudo apt install -y bubblewrap && bwrap --version`; OPA installed: `curl -L -o /tmp/opa https://openpolicyagent.org/downloads/v1.21.0/opa_linux_amd64_static && sudo install -m 0755 /tmp/opa /usr/local/bin/opa && opa version`.

**Steps.**

1. `git checkout -b feat/arch-15-7-asphaleia-telos-isolation`.
2. **Praxis split (Step B)** — `koinon/src/koinon/policy/praxis/constitution/*` → `koinon/src/koinon/policy/constitution/` (`SignatureVerifier`, `ConstitutionLoader`, `versions` pointing at `policies/constitution/versions/`, `pubkey.pem` at `policies/constitution/pubkey.pem`); `koinon/src/koinon/policy/praxis/apex/*` → `koinon/src/koinon/kernel/kybernesis/apex/` (done in 15.6 if not already); delete `koinon/src/koinon/policy/praxis/` leaving a shim module that re-exports with `DeprecationWarning`; update `scripts/check_plugin_isolation.py` roots.
3. **PolicyPort + adapters** — `koinon/src/koinon/contracts/ports/policy.py` (`PolicyDecision{allow, tier_required: ChangeApprovalTier | None, obligations: tuple[str,...], reasons: tuple[str,...], policy_digest, evaluated_at}`); `koinon/src/koinon/policy/pdp/opa_http.py::OpaHttpPolicyAdapter` (`httpx.AsyncClient` → `POST http://127.0.0.1:8181/v1/data/kosmos/decision` with `{"input": …}`; 200 ms timeout; **fail-closed**: any error → `allow=False, reasons=("pdp_unavailable",)` in `production` and `local` unless `KOSMOS_POLICY_FAIL_OPEN_DEV=1`); `koinon/src/koinon/policy/pdp/in_process.py::InProcessPolicyAdapter` (Python mirror; test profile). Replace the permissive stub call site in `OperationsController` (15.6 step 3.5) with the real port; add PEP calls at: `TektosToolRegistry.invoke()` (`action="tool.invoke"`, before detectors and approvals; deny → `ToolPolicyDenied`), `CheckpointManager.checkpoint()` (`vcs.commit`), workflow signals (`workflow.start|release|cancel`), the inference gateway (15.8, `model.call`), `ArtifactService.promote()` (`artifact.promote`), `CapabilityTokenService.issue()` (`capability.issue`), `PluginRegistry.promote()` (`extension.promote`). Every decision → `io.kosmos.telos.policy.decided.v1` with `policy_digest`, input hash, and the citing token id.
4. **`policies/` tree** — `policies/constitution/` (moved in 15.3; add `constitution.rego` exposing invariants as `data.kosmos.constitution.invariants`), `policies/capabilities/{capabilities.rego,autonomy.rego}` (grant matching, token scope ⊆ grant, TTL, path globs, command classes, network; A0–A4 ceilings), `policies/protected-paths/paths.rego` (worktree confinement; denylist; protected repository paths of §2.11 → obligation `route:change_control`), `policies/model-use/models.rego` (role × action-class matrix; token budgets; residency), `policies/exceptions/exceptions.rego` + `exceptions.json` schema (time-boxed, signed, owner, expiry), `policies/decision.rego` (composition: schema-valid → token valid & unexpired → grant matches → path allowed → command class allowed → tier ≤ ceiling → model-use ok → exceptions applied → obligations → allow), `policies/data/charter_defaults.json`. `policies/tests/`: `*_test.rego` for `opa test policies/ -v`, and `fixtures/*.json` differential cases (≥ 80) evaluated by both adapters in `tests/policy/test_policy_differential.py` (identical `PolicyDecision` minus digest/timestamps). Bundle digest = sha256 of `opa build -b policies/` output (or of the sorted `.rego`+`.json` files when OPA is absent) — the Integrity Tripwire reads the same digest.
5. **Capabilities split** — `koinon/src/koinon/capabilities/` holds the *models and enforcement* (`CapabilityGrant`/`CapabilityToken` dataclasses, `TokenVerifier`, the PEP helper `enforce(action, token, resource)` used by the tool registry, the inference gateway, the MCP server and `ArtifactService`); `plugins/asphaleia` holds the *issuing and brokering services*. **Asphaleia plugin** — `plugins/asphaleia/components/`: `AuthenticationService` (moved from `koinon/kernel/operator_auth.py`; operator token now also mints an **operator subject**), `CapabilityGrantService` (issue/revoke/`active_for(workflow_id)`; charter defaults auto-issue an A0–A2 grant on workflow creation: `network=none`, `path_globs=["<worktree>/**"]`, `command_classes=["read","build","test","vcs-local"]`, `ttl=6h`; A3/A4 grants require a `Decision` through the apex engine), `CapabilityTokenService` (signed JWS via `cryptography` Ed25519 with the key from `SecretsPort` `kosmos/capability_signing_key`; claims `sub, wf, grant, scopes, paths, cmds, net, tier, exp ≤ 60 min, jti`; verification helper used by the tool registry, the inference gateway, and the Kosmos MCP server), `SecretsBrokerService` (`koinon/adapters/secrets/age_file` re-homed to `plugins/asphaleia/secrets/age_file.py`; the only reader of `SecretsPort` for workers: returns **references** and injects values only into a sandboxed process env when the token scope names the secret; never returns secret bytes over HTTP), `ProtectedPathService` (list from `policies/protected-paths/`; diffs touching them become `proposal` artifacts routed to `ChangeControlWorkflow`), `SupplyChainGate` (gitleaks + pip-audit + SBOM presence for dependency changes), `IsolationPolicyService` (tier selection per token), `SandboxProfileRegistry`. Manifest `provides=("authn","capabilities","secrets-broker","isolation")`, `owned_data=("mn_capability_grants","mn_capability_tokens","mn_quarantine")`, `enabled=True`.
6. **Telos** — `koinon/src/koinon/kernel/telos/`: `HumanAuthorizationWorkflow` and `ChangeControlWorkflow` runners (definitions from 15.6), `ConstitutionAmendmentWorkflow` (propose → review → sign → activate; activation requires two signatures or one witnessed decision — record in `mn_constitution_versions`), `ExceptionRegistry` (loads `policies/exceptions/*.json`, expires them, journals `io.kosmos.telos.exception.expired.v1`), `PolicyInterpretationFunction` (`Function`: one schema-validated LLM call that *explains/classifies* an ambiguous request; its output is an input to Rego, never a decision), `AutonomyCeilingService` (`KOSMOS_AUTONOMY_TIER_MAX` default `A2`; `PUT /api/v1/settings/autonomy` operator-only, journaled `io.kosmos.telos.charter.updated.v1`; `/health` reports `autonomy_ceiling`).
7. **Isolation (ADR-157)** — `koinon/src/koinon/tools/isolation/worktrees.py` (`WorktreeManager`: `create(workflow_id, base_ref="HEAD") -> Worktree(path=data/worktrees/<workflow_id>, branch=tekton/<workflow_id>)`, `checkpoint(worktree, message) -> sha` with `GIT_AUTHOR_NAME="Kosmos Tekton" GIT_AUTHOR_EMAIL="tekton@kosmos.local"`, `restore`, `diff`, `remove`; `filelock` per workflow; `KOSMOS_WORKSPACE_ROOT`; journals `io.kosmos.tekton.checkpoint.created.v1`), `isolation/paths.py` (`confine(path, root)`: resolve symlinks, reject `..`, denylist; applied in the governed builtins `read_file/write_file/list_directory/apply_patch` which take `cwd` from `ToolContext(workflow_id, worktree, token)`), `isolation/supervisor.py` (extends the sandbox adapter: `asyncio.create_subprocess_exec(*argv, cwd, env=_allowlisted_env(request), start_new_session=True, preexec_fn=_apply_rlimits)`; `RLIMIT_AS/CPU/FSIZE/NPROC`; `os.killpg` SIGTERM → 3 s → SIGKILL; output cap `max_output_bytes` 1 MiB; `cwd ∈ allowed_roots`; env allowlist `PATH HOME LANG LC_ALL TERM PYTHONUNBUFFERED VIRTUAL_ENV CI` + request env; `unshare -n` unless token `net ∈ {loopback, allowlist}`; `peak_memory_mb` via `getrusage`), `isolation/bwrap.py` (`KOSMOS_SANDBOX_TIER=bwrap` wraps argv with the §2.14 command line; `--share-net` only for `loopback` tokens; fall back to `process` in `local` with a warning, fail in `production`). Structured `run_tests(cmd_class: pytest|npm-test|cargo-test, args) -> TestReport(passed, failed, skipped, errors, junit_path, duration_s)` governed builtin. The sandbox adapter moves from `koinon/adapters/sandbox/tektos` to `koinon/src/koinon/tools/sandbox/` (Step B; `koinon.tools` = governed registry + builtins + sandbox + isolation, per §2.16).
8. **Integrity Tripwire wiring** — Sema `IntegrityTripwire` (15.6) now hashes `policies/**` (bundle digest), `koinon/src/koinon/{policy,capabilities}/**`, `plugins/tekton/gates/**`, and `deploy/**`; mismatch outside a `ChangeControlWorkflow` window → `critical` → global `CONTAINED` + algedonic tier 3.
9. **Ops** — `deploy/opa/kosmos-opa.service` (`ExecStart=/usr/local/bin/opa run --server --addr 127.0.0.1:8181 --log-level info /home/rmholston/dev/kosmos-lms/policies`, `DynamicUser=yes`, `ProtectSystem=strict`, `ReadOnlyPaths=…/policies`); CI job `policy`: `open-policy-agent/setup-opa@v2` → `opa check --strict policies/ && opa test policies/ -v`, plus the OPA HTTP adapter contract test against `opa run --server`; `security` job gains `gitleaks/gitleaks-action@v2` and `anchore/sbom-action` (CycloneDX) artifacts. Ledger "External tools": OPA v1.21.0 (Apache-2.0), bubblewrap (LGPL-2.1-or-later, binary only), gitleaks (MIT), syft (Apache-2.0).
10. **Sandbox conformance suite** — `tests/conformance/sandbox/`: fork-bomb (`RLIMIT_NPROC`) terminates; `sleep 999` killed with an empty process group; write outside worktree rejected; `curl 1.1.1.1` fails with `net=none`; `curl 127.0.0.1:8000/health` succeeds with `net=loopback`; 200 MB allocation killed by `RLIMIT_AS`; output truncation; symlink escape; env leak (`printenv KOSMOS_OPERATOR_TOKEN` empty); protected path write → `proposal` artifact instead of change; `bwrap` cases skipped when absent (never on Colossus).

**Tests.** `opa test`; differential fixtures; grant/token lifecycle (`plugins/asphaleia/tests/`); PEP tests (denied call never reaches the sandbox — spy `SandboxPort`); fail-closed tests; worktree tests on `tmp_path` repos; conformance suite; Telos workflow tests (amendment requires two signatures); tripwire test (edit a `.rego` at runtime → containment); full suite.

**Exit gate.** `opa test policies/` all pass; ≥ 80 differential fixtures, 0 divergence; a tool call outside the token's path globs is denied and journaled; `systemctl status kosmos-opa` active on Colossus; sandbox conformance green on Colossus with `bwrap` present (no skips); `inotifywait -r -e modify koinon/ plugins/ policies/ &` during the suite shows no events; `rg -n "koinon.policy.praxis" --glob '!*shim*' .` → 0 outside the shim; CI green with the `policy` job.

**Commits.** `refactor(telos): Stage 15.7 — split praxis into koinon.policy.constitution + kybernesis.apex (shim)`; `feat(telos): Stage 15.7 — PolicyPort, OPA HTTP + in-process adapters, policies/ tree, differential fixtures (ADR-156)`; `feat(asphaleia): Stage 15.7 — grants, capability tokens, secrets broker, protected paths, supply-chain gate`; `feat(telos): Stage 15.7 — authorization/change-control/amendment workflows, exceptions, autonomy ceiling`; `feat(capabilities): Stage 15.7 — worktrees, process supervisor, path policy, bwrap tier, run_tests (ADR-157)`; `feat(sema): Stage 15.7 — Integrity Tripwire over policies/capabilities/gates/deploy`; `deploy(opa): Stage 15.7 — kosmos-opa.service`; `test(conformance): Stage 15.7 — sandbox + policy suites`.

**Logs.** BUILD_LOG; PORTING_LEDGER external tools; ADR-156/157 indexed; KNOWN_ISSUES B-20 closed.

**Rollback.** `KOSMOS_POLICY=in_process` uses the Python mirror; `KOSMOS_POLICY=off` is **not provided** (a PDP is mandatory once 15.7 merges); `KOSMOS_SANDBOX_TIER=process` disables `bwrap`; worktrees are disposable (`git worktree prune`).

---

### Stage 15.8 — Syndesmos & Mesiteia: API gateway v1, error envelope, health, AG-UI SSE, inference gateway, event bus, discovery, MCP server, A2A transport (Phase 3)

**Goal.** One versioned, typed, documented API (`/api/v1/*`) with a uniform error envelope and health split; a standards-based event stream (AG-UI over SSE fed by the journal, resumable); the **inference gateway** through which every agent and worker reaches models; the event bus re-homed; a discovery service built from plugin manifests; the MCP adapter re-homed and a **Kosmos MCP server** exposing governed tools to external runtimes under capability tokens; an **A2A** server/client so Agora and external agents interoperate; `ui-contracts` generated. Everything new lives in routers under `koinon.mesiteia`; `koinon.kernel.app:app` remains the ASGI entrypoint until 15.15.

**ADR.** ADR-158 "Mesiteia: API v1, error envelope, health endpoints, AG-UI projection over SSE, inference gateway, MCP server, A2A transport" (amends ADR-141's "wire-verbatim donor routes" for the new surface only; ADR-095/ADR-098 MCP absorption gains the server role).

**Steps.**

1. `git checkout -b feat/arch-15-8-mesiteia`.
2. **Gateway skeleton** — `koinon/src/koinon/mesiteia/api/app.py` (`create_app()` used by the legacy app via `include_router`s), `mesiteia/api/routers/{workflows,plans,tasks,claims,evidence,artifacts,decisions,grants,tokens,checkpoints,releases,incidents,projects,charters,workflow_definitions,agents,models,resources,knowledge,research,council,agora,security,settings,health,events,tools}.py`, `mesiteia/api/errors.py` (envelope `{"error": {"code","message","details","correlation_id"}}`; handlers for `PolicyDenied` 403, `ToolApprovalDenied` 403, `JournalConflict` 409, `PdpUnavailable` 503, `TokenInvalid` 401, `LeaseUnavailable` 429; a test greps v1 routers for `return {"error"` → must be 0), `mesiteia/api/auth.py` (operator subject **or** a capability token; every mutating route requires one; read routes open on loopback), correlation IDs (`X-Correlation-ID` → journal), rate limits/backpressure (429 with `Retry-After` when Harmonia reports backpressure).
3. **Endpoints** (operator or token; mutating routes journal a command):

| Method & path | Purpose |
|---|---|
| `POST/GET /api/v1/workflows`, `GET /api/v1/workflows/{id}` | create (brief, project, charter overrides, definition_id, autonomy request) / list (filters) / detail (state, status_summary, essential variables, budgets, commitments) |
| `POST /api/v1/workflows/{id}:start\|pause\|resume\|cancel` | control signals → Kybernesis |
| `GET /api/v1/workflows/{id}/events?after_seq=&types=` · `/transcript` · `/plan` · `PUT …/plan:approve` · `/claims` · `/checkpoints` (+ `POST`, `POST …/{sha}:restore`) · `/diff?from=&to=` | journal, projections, checkpoints |
| `GET /api/v1/claims/{id}/evidence` | proof perspective |
| `GET /api/v1/decisions?status=pending` · `POST /api/v1/decisions/{id}:resolve` | human decisions (approve/reject/answer/extend budget/witness) |
| `GET/POST /api/v1/grants` · `POST …/{id}:revoke` · `POST /api/v1/tokens` (mint for a run; Asphaleia) | capabilities |
| `GET /api/v1/artifacts/{digest}` · `GET …/{digest}/provenance` · `POST …/{digest}:promote` | artifact service |
| `GET/POST /api/v1/releases` · `POST …/{id}:rollback` · `GET/POST /api/v1/incidents` | Kybernesis (implementations 15.12) |
| `GET/POST /api/v1/projects`, `/charters`, `/workflow-definitions` | aggregates |
| `GET /api/v1/agents/manifests` · `GET/POST /api/v1/agents/sessions` · `POST …/{id}:stop` | Epimeleia (15.10) |
| `GET /api/v1/models` · `/models/health` · `/models/assignments` | Noesis (15.9) |
| `GET /api/v1/resources/telemetry` · `/leases` · `/recommendations` | Poros/Harmonia (15.9) |
| `GET /api/v1/discovery` | capability directory from `PluginRegistry.describe()` (plugins, provides/requires, events, health) |
| `GET /api/v1/settings/autonomy` · `PUT` | Telos ceiling |
| `GET /api/v1/tools` · `POST /api/v1/tools/{name}:invoke` | governed tools (replaces `/api/tools/{name}/execute`, now an alias) |
| `GET /api/v1/workflows/{id}/stream` · `GET /api/v1/stream` (SSE) | AG-UI events |
| `POST /v1/chat/completions` · `GET /v1/models` (inference gateway) | model access for agents/workers |
| `GET /health/live` · `/ready` · `/startup` · `/degraded` · `/health` (legacy) | health split |
| `GET /.well-known/agent-card.json` · `POST /a2a` | A2A (agent card path per the pinned `a2a-sdk` version) |
| `/mcp` (Streamable HTTP) | Kosmos MCP server |

4. **AG-UI projection** — `koinon/src/koinon/mesiteia/streams/agui.py`: journal → AG-UI: workflow start/finish/error → `RUN_STARTED/RUN_FINISHED/RUN_ERROR` (`threadId=workflow_id`, `runId=<regulation cycle id>`); phase changes → `STEP_STARTED/STEP_FINISHED`; model deltas → `TEXT_MESSAGE_*`; tool calls → `TOOL_CALL_*` (+ result as `CUSTOM` until standardized); state → `STATE_SNAPSHOT` on connect and `STATE_DELTA` (RFC 6902) after; other events → `CUSTOM` carrying the CloudEvent. SSE `id: <seq>` so `Last-Event-ID` resumes from the journal; heartbeat every 15 s; if a client is > 10,000 events behind, send a fresh snapshot. The legacy `/api/events/ws` bridges `io.kosmos.*` events too.
5. **Inference gateway** — `koinon/src/koinon/mesiteia/inference/gateway.py`: OpenAI-compatible `POST /v1/chat/completions` (+ `GET /v1/models`) bound to `127.0.0.1:8000` only; **Bearer = capability token** (scope `model:<role>`); resolves the `model` field as a **role** (`coder|planner|verifier|summarizer|embedder`) or a registry id, asks `PolicyPort` (`model.call`; budget check via Kybernesis `CommitmentRegistry`), forwards to the configured `LLMPort` adapter (15.9 replaces this with Noesis routing), streams back verbatim, journals `io.kosmos.noesis.model.called.v1` with usage and token id; per-token token budgets and rate limits; never logs prompts unless `KOSMOS_LOG_PROMPTS=1`. This is the `base_url` that Hermes (15.10) and OpenHands (15.12) receive; direct model ports (8090/8093/11434) are unreachable from sandboxes (`net=loopback` + an allowlist of `127.0.0.1:8000` enforced by `bwrap`/iptables owner rule in 15.14).
6. **Event bus & discovery** — `koinon.mesiteia.event_bus` (moved in 15.6) gains a `topics.py` map (`io.kosmos.*` → Valkey stream names); `DiscoveryService` (from manifests + `/health` subsystems); `SchemaRegistryService` serving `contracts/schemas/**` at `GET /api/v1/schemas/{name}`.
7. **MCP** — `koinon/adapters/mcp/*` → `extensions/adapters/mcp/` (client, in-process/stdio transports; ledger updated); **`KosmosMcpServer`** (`koinon/src/koinon/mesiteia/mcp/server.py`, using the `mcp` SDK's Streamable HTTP server): exposes the governed tool registry (`list_tools` filtered by the token's scopes; `call_tool` → `TektosToolRegistry.invoke` with `ToolContext` from the token) plus read-only resources (`kosmos://workflows/{id}`, `kosmos://artifacts/{digest}`, `kosmos://knowledge/...`); auth = the same capability tokens; this is what Hermes toolsets and OpenHands MCP config point at.
8. **A2A** — `pip install "a2a-sdk[http-server]==<pinned>"` (extra `a2a`; Apache-2.0; ledger entry); `koinon/src/koinon/mesiteia/a2a/{server,client}.py`: Agent Card describing Kosmos skills (`research`, `council`, `knowledge`), JSON-RPC + HTTP+JSON transports, task lifecycle mapped to workflows (`message/send` → workflow create+start; task status ← `status_summary`; artifacts ← artifact service); inbound A2A requests are **nonbinding** (create `advice`/`request` artifacts routed to Kybernesis, never commands); outbound client used by Agora (15.11). Gated `KOSMOS_A2A_ENABLED` (default off).
9. **Health** — `live` (process), `startup` (lifespan done), `ready` (journal + policy + sandbox + inference gateway reachable → else 503), `degraded` (subsystems in fallback) from `_BootRegistry.errors` + adapter `is_healthy()`.
10. **`ui-contracts/`** — `npm run gen:types`: `openapi-typescript` (MIT) → `api.d.ts` from `/openapi.json`; `json-schema-to-typescript` (MIT) → `events.d.ts` from `contracts/schemas/events/*.json`; AG-UI types from `@ag-ui/core`; committed, diff-checked in CI.
11. **Legacy aliases** — `/api/tektos/turn`, `/api/prompt/sse`, `/api/tools/{name}/execute`, `/api/events/ws`, `/api/gnosis/*` (until 15.11) stay as thin aliases.

**Tests.** Schemathesis (MIT) against `/openapi.json` in CI (`schemathesis run --checks all http://127.0.0.1:8000/openapi.json --hypothesis-max-examples=50`); router tests per resource; SSE resume test (disconnect at seq N, reconnect `Last-Event-ID: N` → N+1…); error-envelope conformance; inference gateway tests (token scope, role resolution, budget deny, streaming passthrough against the recorded-fixture fake server); MCP server tests with the `mcp` client (`list_tools` scope filtering; `call_tool` path deny); A2A tests with the SDK client (agent card, `message/send`, nonbinding routing); discovery test; `ui-contracts` drift check; health tests.

**Exit gate.** Schemathesis 0 failures; SSE resume green; `rg -n 'return \{"error"' koinon/src/koinon/mesiteia` → 0; a `curl -H "Authorization: Bearer <token>" 127.0.0.1:8000/v1/chat/completions -d '{"model":"coder","messages":[…]}'` from Colossus returns a completion and journals the call; an `mcp` client lists only scoped tools; legacy Playwright suite green; CI green.

**Commits.** `feat(mesiteia): Stage 15.8 — API v1 skeleton, routers, error envelope, auth, health split (ADR-158)`; `feat(mesiteia): Stage 15.8 — workflow/claims/decisions/grants/tokens/checkpoints/artifacts routes`; `feat(mesiteia): Stage 15.8 — AG-UI SSE projection with Last-Event-ID resume`; `feat(mesiteia): Stage 15.8 — inference gateway /v1/chat/completions with capability tokens`; `feat(mesiteia): Stage 15.8 — discovery + schema registry; event bus topics`; `feat(mesiteia): Stage 15.8 — Kosmos MCP server; re-home MCP client adapters to extensions/`; `feat(mesiteia): Stage 15.8 — A2A server/client (a2a-sdk) behind KOSMOS_A2A_ENABLED`; `build(ui-contracts): Stage 15.8 — generated TS types + drift check`.

**Logs.** BUILD_LOG; ADR-158; PORTING_LEDGER (a2a-sdk, openapi-typescript, json-schema-to-typescript, schemathesis, `@ag-ui/core`).

**Rollback.** Routers additive; `KOSMOS_API_V1=off` during the stage only; `KOSMOS_A2A_ENABLED=0`; `KOSMOS_INFERENCE_GATEWAY=off` makes agents fall back to direct `KOSMOS_LLM_BASE_URL` (dev only; forbidden in `production`).

---

### Stage 15.9 — Poros & Noesis: resource telemetry, budgets, lease recommendations; model registry, routing, tool-calling protocol, fallbacks, vLLM adapter, benchmarks (Phase 4)

**Goal.** Poros observes and recommends (never allocates): GPU/CPU/RAM/disk/thermal telemetry, budgets, cost accounting, lease *recommendations* consumed by Kybernesis `ResourceController`. Noesis owns models: a registry from `config/models.yaml`, role-based routing (`coder|planner|verifier|summarizer|embedder|vision|voice`), the `LLMPort` tool-calling protocol with a single normalizer, streaming, health, failover/fallback chains, benchmark profiles, and adapters under `extensions/adapters/{llamacpp,ollama,vllm}` — behind the inference gateway from 15.8. Colossus topology recorded as data, not code.

**ADR.** ADR-159 "Noesis model registry, routing and `LLMPort` tool-calling protocol; Poros recommendation-only resource management" (amends ADR-022 `LLMPort` — backward-compatible widening; records the OpenHands-Ext topology as the default `models.yaml`).

**Steps.**

1. `git checkout -b feat/arch-15-9-poros-noesis`.
2. **`LLMPort` protocol** — `koinon/src/koinon/contracts/ports/llm.py`: `chat(*, messages, model=None, tools=None, tool_choice=None, response_format=None, parallel_tool_calls=None, **options) -> dict`; `chat_stream(*, …) -> AsyncIterator[ChatDelta]`; messages may carry `role: "tool"` and assistant `tool_calls`. `koinon/src/koinon/kernel/model_protocol.py`: `normalize_chat_response(raw) -> AssistantTurn(content, tool_calls[ModelToolCall(id, name, arguments: dict)], finish_reason, usage, raw, parse_error)` handling (a) OpenAI-compatible `arguments` as **JSON string or already-parsed object** (llama.cpp shipped the object form between b8xxx builds and reverted in `b8236`, `ggml-org/llama.cpp#20198` — both must parse), (b) Ollama `/api/chat` native `tool_calls`, (c) text fallbacks (```` ```json {"tool_calls": [...]} ```` block or `<tool_call>…</tool_call>` tags) **only when tools were requested and no structured calls came back**, (d) malformed JSON → `parse_error` so Kybernesis issues a repair `role: "tool"` message, (e) `finish_reason ∈ stop|tool_calls|length|content_filter|error`; `StreamingToolCallAccumulator` (pattern from `tektos-ultima@8274f60 src/tektos/runtime/sdk.py::_stream_llm` lines 1523–1731 — PATTERN-VENDORED ledger entry; if the donor has no license file, re-implement from the description and log "pattern only").
3. **Adapters → `extensions/adapters/`** — move `koinon/adapters/llm/{llama_swap,ollama,failover}` to `extensions/adapters/llamacpp/`, `extensions/adapters/ollama/`, `plugins/noesis/components/fallback.py` (the failover chain is Noesis logic, not an extension); forward `tools`, `tool_choice`, `response_format`, `parallel_tool_calls`, streaming SSE; new `extensions/adapters/vllm/adapter.py` (OpenAI-compatible; `KOSMOS_VLLM_URL`, default `http://127.0.0.1:8001/v1`; the coder model host per the OpenHands-Ext topology); contract tests against a **recorded-fixture fake server** (`tests/fixtures/llm/*.json` captured once on Colossus for llama.cpp — both argument forms — Ollama and vLLM). Move `vision/*`, `voice/*` adapters to `extensions/adapters/{vision,voice}/`; `resource/sqlite`, `thermal/tektos` to `plugins/poros/components/` (`search/searxng` moves to `plugins/zetesis/adapters/search` in 15.11; `secrets/age_file` moved to `plugins/asphaleia/secrets/` in 15.7).
4. **Noesis plugin** (`plugins/noesis/components/`): `ModelRegistry` (loads `config/models.yaml`: per model `{id, backend, base_url, served_name, roles[], supports_tools, supports_parallel_tools, context_window, max_output_tokens, temperature_by_role, chat_template_note, vram_gb, residency: exclusive|shared|cpu}`; Colossus default: `coder` → vLLM `127.0.0.1:8001` Qwen3-Coder-30B-A3B AWQ (exclusive GPU), `planner`/`verifier`/`summarizer` → llama.cpp `127.0.0.1:8090` Qwen3.6-35B-A3B (exclusive GPU — one large GPU model at a time; the registry marks the pair mutually exclusive and Poros recommends the swap), CPU fallback `127.0.0.1:8092`, `embedder` → Qwen3-Embedding-4B CPU `127.0.0.1:8091`, `vision` → Ollama `qwen2.5-vl`; existing HA proxy `127.0.0.1:8093/v1` recorded as `hermes_default`), `ModelRouter` (role → candidate chain; consumes `PolicyPort` `model.call` obligations; consults Poros residency; emits `io.kosmos.noesis.model.selected.v1`), `ModelHealthMonitor` (`/health`, `/v1/models`, `/props` for llama.cpp `--jinja` tool-template check), `FallbackChainService` (wraps the failover adapter; typed failure taxonomy: `transient|resource|policy|logic`; never falls back across `residency=exclusive` without a Poros recommendation and Kybernesis lease), `ModelAssignmentService` (per workflow/agent role assignments in `mn_model_assignments`), `PromptTemplateRegistry`, `BenchmarkProfileService` (`local-llm-bench` conventions: prompts on disk under `plugins/noesis/bench/prompts/`, JSON per cell, deterministic sampling per role, reasoning-block stripping before scoring, tok/s + wall time; `scripts/noesis_bench.py`), `EmbeddingService` (re-homed `kernel/routing.py` embedding routing), `ContextWindowService` (existing `context_curator` budgeting re-homed). Inference gateway (15.8) now calls `ModelRouter`. `TektosToolRegistry.openai_tools(*, names=None) -> list[dict]` + golden fixtures `plugins/tekton/tests/fixtures/tool_schemas/*.json`.
5. **Poros plugin** (`plugins/poros/components/`): `ResourceTelemetryMonitor` (nvidia-smi/NVML via `pynvml` if present, `psutil`, disk; `/api/v1/resources/telemetry`; Prometheus `kosmos_poros_*`), `ThermalMonitor` (existing `ThermalPort` adapter; bands feed Sema thresholds), `BudgetService` (tokens, wall time, GPU-minutes per workflow/charter; `mn_commitments` read), `CostAccountingService`, `CapacityForecastFunction` (deterministic EMA; no LLM), `LeaseRecommendationService` (emits `io.kosmos.poros.recommendation.v1` `{resource, action: grant|defer|swap_model|throttle, reason}` — Kybernesis `ResourceController` decides), `ResidencyPlanner` (which exclusive GPU model should be resident given the queue), `GpuSlotRegistryView` (read model of Harmonia leases). Architecture test: `plugins/poros` never imports `LeaseRegistry` writers or emits commands.
6. **Live probe** (not a test): `scripts/llm_toolcall_probe.py --role coder` → one tool request through the inference gateway; prints the normalized `AssistantTurn`; run after `curl -s 127.0.0.1:8090/props | jq '.chat_template | test("tool")'` confirms a tool-enabled template (llama.cpp needs `--jinja`).

**Tests.** `koinon/tests/model_protocol/test_normalizer.py` (≥ 40 cases), adapter contract tests over fixtures (llamacpp/ollama/vllm), router tests (role chains, exclusive-residency rule), fallback taxonomy tests, registry schema test for `config/models.yaml`, Poros recommendation tests, Prometheus metric presence test, `@pytest.mark.llm` live test skipping without a backend, full suite.

**Exit gate.** All three adapters pass one contract test; probe on Colossus returns a `ModelToolCall` with parsed `arguments` through the gateway; `GET /api/v1/models/health` reports the Colossus topology; a swap recommendation appears when a `coder` request arrives while the planner model is resident (unit + Colossus check); CI green.

**Commits.** `feat(contracts): Stage 15.9 — LLMPort tools/tool_choice/chat_stream; AssistantTurn normalizer + streaming accumulator (ADR-159)`; `refactor(extensions): Stage 15.9 — llamacpp/ollama/vllm/vision/voice/searxng adapters under extensions/; failover → noesis`; `feat(noesis): Stage 15.9 — registry (models.yaml), router, health, fallbacks, assignments, benchmarks, openai_tools()`; `feat(poros): Stage 15.9 — telemetry, thermal, budgets, cost, residency, lease recommendations`; `feat(mesiteia): Stage 15.9 — gateway routes through Noesis`.

**Logs.** BUILD_LOG; PORTING_LEDGER (pattern port; `pynvml` if adopted); ADR-159.

**Rollback.** New parameters default to `None`; `KOSMOS_NOESIS_ROUTER=static` pins roles to `KOSMOS_LLM_BASE_URL`.

---
### Stage 15.10 — Epimeleia: agent manifests, Hermes API-server adapter, capability broker, skills/toolsets, sessions, lifecycle, termination (Phase 5)

**Goal.** Kosmos governs external agent runtimes through one port. `AgentRuntimePort` with `HermesApiServerAdapter` (canonical) and `ScriptedAgentRuntimeAdapter` (tests); agent manifests (kind, purpose, allowed skills/toolsets, model roles, capability ceiling, budgets, escalation rules); a capability broker that scopes every Hermes run to a capability token; a context assembler; skill/toolset resolvers that only expose `skills/shared` and Kosmos MCP tools; a session registry; lifecycle, checkpoint, recovery, termination controllers; result normalization into artifacts; the `RunAgent` activity in Kybernesis. Hermes runs **outside** the kernel process as `hermes gateway` on `127.0.0.1:8642`, never as an authority.

**ADR.** ADR-160 "Epimeleia: `AgentRuntimePort`, Hermes API-server adapter, agent manifests and capability-scoped runs" (records decision 8: the API server (HTTP + SSE) over ACP/TUI JSON-RPC/in-process; records that agents never hold ambient credentials).

**Preconditions.** 15.8/15.9 merged. On Colossus (per `colossus-python-env`: Hermes has its own venv at `/home/rmholston/.hermes/hermes-agent/venv`; do not install Kosmos packages into it): `hermes --version`; enable the API server: append to `~/.hermes/.env`
```
API_SERVER_ENABLED=true
API_SERVER_KEY=<32-byte random, e.g. $(openssl rand -hex 32)>
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
```
(check exact variable names against `hermes gateway --help`/the Hermes docs for the installed version — these are the names documented on 2026-09-28); store the same key with `kosmos secrets set kosmos/hermes_api_key` (age file; 15.7 broker); start `hermes gateway` and verify `curl -s -H "Authorization: Bearer $KEY" 127.0.0.1:8642/health` and `/v1/capabilities`.

**Steps.**

1. `git checkout -b feat/arch-15-10-epimeleia-hermes`.
2. **Port** — `koinon/src/koinon/contracts/ports/agent_runtime.py` (§2.8): `AgentEvent{kind: started|message|tool_call|tool_result|approval_request|checkpoint|error|finished, seq, occurred_at, payload}`; `RunHandle{run_id, runtime, started_at}`.
3. **`HermesApiServerAdapter`** — `extensions/adapters/hermes/adapter.py` (`httpx.AsyncClient`, base `KOSMOS_HERMES_API_URL` default `http://127.0.0.1:8642`, bearer from `SecretsPort` key `kosmos/hermes_api_key`): `start_run` → `POST /v1/runs` with `{model: KOSMOS_HERMES_MODEL_NAME | manifest.model_role, input: <assembled context + task>, tools/toolsets: <resolved>, metadata: {workflow_id, run_token_id, manifest}}` (**exact request schema to be read from `GET /v1/capabilities` and the OpenAPI at `/openapi.json` of the running gateway at implementation time; encode as recorded fixtures**); `events` → `GET /v1/runs/{id}/events` SSE with `Last-Event-ID` resume, mapped to `AgentEvent`; `status` → `GET /v1/runs/{id}`; `stop` → `POST /v1/runs/{id}/stop`; `resolve_approval` → `POST /v1/runs/{id}/approval`; health → `GET /health/detailed`; concurrency ≤ `gateway.api_server.max_concurrent_runs` (read from capabilities; Harmonia lease `hermes_run_slot`). If the pinned Hermes version's `/v1/runs` lacks a needed field (e.g., per-run toolset restriction), fall back to a **dedicated Hermes profile** `kosmos` (`hermes profile create kosmos` with `config.yaml`: toolsets restricted to `kosmos_mcp` + read-only builtins; provider `openai_compatible` with `base_url=http://127.0.0.1:8000/v1` = the Kosmos inference gateway and the run's capability token as `api_key` when per-run keys are supported, else a long-lived `model:*` token scoped to the Hermes subject) and record the limitation in KNOWN_ISSUES. `ScriptedAgentRuntimeAdapter` (`extensions/adapters/hermes/scripted.py`) replays `tests/fixtures/hermes/*.sse` recorded from the live gateway.
4. **Epimeleia plugin** (`plugins/epimeleia/components/`): `AgentManifestRegistry` (YAML under `plugins/epimeleia/manifests/`: `research_planning_agent`, `synthesis_agent`, `review_agent`, `pronoia_scenario_agent`, `synedrion_perspective_agent`, `red_team_agent`, `tekton_planner_agent` — each `{kind: AGENT, purpose, runtime: hermes, model_roles, allowed_skills, allowed_toolsets, capability_ceiling (A0–A2), budgets, escalation_rules, output_schema}`; `mn_agent_manifests`), `CapabilityBrokerService` (mints a run token via Asphaleia for `manifest ∩ workflow grant`; scopes: `model:<roles>`, `tool:<names>`, `kosmos:read:<resources>`; TTL = budget wall time + 5 min), `ContextAssemblerService` (task brief, relevant claims, Gnosis assertions, prior artifacts → bounded prompt package with citations; no secrets), `SkillResolverService` (`skills/shared/*/SKILL.md` allowlist; quarantined skills excluded), `ToolsetResolverService` (Kosmos MCP server URL + token; denies direct shell/network toolsets unless the manifest allows and the token grants), `ModelAssignmentClient` (Noesis roles → gateway `model` values), `SessionRegistry` (`mn_agent_sessions`: run_id, manifest, workflow_id, token_id, state, usage), `AgentLifecycleController` (start/observe/stop; `RunAgent` activity for Kybernesis; per-step timeout from the manifest), `CheckpointManager` (persist Hermes event stream to the journal as `io.kosmos.epimeleia.run.*.v1` and the transcript as an artifact every N events), `RecoveryWorkflow` (kernel restart mid-run: reattach via `events` with `Last-Event-ID`; if the gateway lost the run, mark `FAILED(transient)` and let Kybernesis retry within budget), `TerminationController` (`stop` + token revocation + Harmonia lease release; hard deadline from budgets; Sema containment stops all runs), `ResultNormalizerService` (final message → `artifact kind=agent_result` with `output_schema` validation; failures → `claim status=refuted` candidates), `AgentTelemetryEmitter` (usage, latency, tool counts → Aisthesis `kosmos_epimeleia_*`), `SupervisorRoleController` (Hermes acts only inside a run; no persistent daemon authority). Manifest `enabled=True`.
5. **Hermes deployment on Colossus** — `deploy/hermes/hermes-gateway.service` (user unit: `ExecStart=/home/rmholston/.hermes/hermes-agent/venv/bin/hermes gateway`, `EnvironmentFile=%h/.hermes/.env`, `Restart=on-failure`), `deploy/hermes/kosmos-profile.yaml` (the restricted profile), `docs/ops/hermes.md` (enable/verify/rotate key/upgrade). Hermes' own tool execution is restricted to the Kosmos MCP toolset for Kosmos runs; its terminal/file toolsets are **off** in the `kosmos` profile (verify with `hermes tools list --profile kosmos` or the equivalent for the installed version).
6. **Kybernesis `RunAgent` activity** — `OperationsController` dispatches `RunAgent(manifest, task)` → `AgentLifecycleController`; events flow into the journal; `Sema` thresholds apply (model calls, wall time, tokens); `approval_request` events become `Decision`s (Kybernesis apex) and are resolved back through `resolve_approval`.
7. **Step B re-home** — `koinon/adapters/session/{inmemory,tektos}` → `plugins/epimeleia/sessions/` (shims); `SessionPort` stays in `koinon.contracts.ports`.
8. **API/UI** — routes from 15.8 `/api/v1/agents/*` now live; legacy `/api/tektos/manager/*` (ADR-108) becomes a façade over the session registry.

**Tests.** Adapter contract test over both adapters (scripted fixtures; `@pytest.mark.hermes` live variant skipping without the gateway); token scoping (a run cannot call a tool outside its scopes — asserted via the MCP server); termination (stop within 10 s; token revoked; lease released); recovery (drop the SSE mid-run → reattach with `Last-Event-ID`); manifest validation; context assembler bounds; result normalization schema failures; full suite.

**Exit gate.** On Colossus: `python scripts/agent_probe.py --manifest research_planning_agent --task "outline a plan to add a health endpoint"` completes via `hermes gateway` with events journaled (`GET /api/v1/workflows/{id}/events` shows `io.kosmos.epimeleia.run.started.v1 … finished.v1`), an `agent_result` artifact stored, `mn_agent_sessions` updated, and the Hermes run visible in `GET /api/v1/agents/sessions`; `POST …/sessions/{id}:stop` ends the run and the token is revoked (`POST /v1/chat/completions` with that token → 401 afterwards); the raw AG-UI stream shows the run; CI green (scripted adapter).

**Commits.** `feat(contracts): Stage 15.10 — AgentRuntimePort (ADR-160)`; `feat(extensions): Stage 15.10 — HermesApiServerAdapter + ScriptedAgentRuntimeAdapter + recorded fixtures`; `feat(epimeleia): Stage 15.10 — manifests, capability broker, context assembler, skill/toolset resolvers, sessions, lifecycle, termination, result normalizer`; `feat(kybernesis): Stage 15.10 — RunAgent activity`; `deploy(hermes): Stage 15.10 — hermes-gateway user unit, kosmos profile, runbook`.

**Logs.** BUILD_LOG; ADR-160; PORTING_LEDGER (hermes-agent as an external runtime — license per its repo; no code vendored); KNOWN_ISSUES for any Hermes API limitation found.

**Rollback.** `KOSMOS_AGENT_RUNTIME=scripted` (tests) or unset manifests' `enabled`; stopping `hermes-gateway.service` makes `RunAgent` steps fail `transient` and workflows block — nothing else degrades.

---

### Stage 15.11 — Zetesis, Gnosis, Synedrion, Agora (Phase 6)

**Goal.** The four intelligence subsystems exist as plugins with local Praxis sets, manifests, events and API routes; none of them holds authority. Zetesis: existing research code classified and gated (`CitationVerificationGate`); Gnosis: knowledge assertions with provenance/confidence, the `/api/gnosis/*` routes out of `app.py`, donor `knowsys` patterns; Synedrion: advisory council (donor `magi`) producing `advice` artifacts; Agora: nonbinding multi-agent forum over A2A.

**ADR.** ADR-161 "Zetesis/Gnosis/Synedrion/Agora plugin scopes, donor name flips (Rigpa-LMS gnosis→Zetesis, knowsys→Gnosis, magi→Synedrion), advisory-only outputs" (amends ADR-097 research module scope).

**Steps.**

1. `git checkout -b feat/arch-15-11-intelligence-plugins`.
2. **Zetesis** — classify every module in `plugins/zetesis/research/` (`claim_support`, `cove`, `url_verify`, `rubric_critique`, `self_consistency`, `structural_finalize`, `odr`, `search_backend`, `mcp_search_server`, …) with `@component`: LLM-calling pieces are `Function`s (`ClaimExtractionFunction`, `EvidenceAssessmentFunction`, `SynthesisFunction`, `CoveFunction`, `RubricCritiqueFunction`), deterministic pieces `Service`/`Gate`/`Tool` (`SourceRetrievalService` over `SearchPort`, `UrlVerifyTool`, `StructuralFinalizeService`, `SelfConsistencyGate`); add `CitationVerificationGate` (deterministic: every citation resolves, quoted spans match fetched content ≥ 0.8 similarity, dates parse; refutes claims otherwise), `ResearchWorkflow` (`workflows/research.yaml`: question → plan (Hermes `research_planning_agent`) → retrieve → assess → synthesize (Hermes `synthesis_agent`) → verify (gate) → `research_report` artifact with provenance edges → Gnosis assertion candidates), `ContradictionDetectorService`, `ResearchProvenanceService`. `praxis/` helpers instantiated from `koinon.kernel.praxis_local`; `koinon/adapters/search/searxng` → `plugins/zetesis/adapters/search/` (shim). Routes `/api/v1/research/*`; legacy `/api/research/*` aliases (`rg -n '"/api/research' koinon/src/koinon/kernel/app.py`).
3. **Gnosis** — `plugins/gnosis/components/`: `KnowledgeAssertionService` (`mn_knowledge_assertions {id, statement, subject, predicate, object?, provenance, confidence, source_artifacts[], status: candidate|accepted|contested|retired, valid_from, valid_to}` — writes go through `MemoryPort` with provenance+confidence), `ProvenanceGraphService` (DozerDB edges), `RetrievalService` (hybrid: Qdrant vectors via Noesis embedder + `pg_trgm` lexical + graph expansion — donor pattern from Rigpa-LMS `plugins/knowsys` (notes/vault/Qdrant retrieval; ledger PATTERN-VENDORED with SHA/license); Kuzu **not** adopted), `CorpusService` (re-homes the `/api/gnosis/{query,corpora,stats}` handlers from `app.py` — 50 mentions — into `plugins/gnosis/api.py`; `rag_retriever` and `tektos_data_services` callers switched), `ConflictDetectorService`, `KnowledgeDecayMonitor` (`valid_to`, staleness → `io.kosmos.gnosis.assertion.stale.v1`), `SchemaEvolutionService` (existing `kernel/schema_evolution.py` re-homed), `ExportService`. Routes `/api/v1/knowledge/*`; `/api/gnosis/*` kept as aliases until 15.15; `ui/app/gnosis` pages unchanged (they call the aliases).
4. **Synedrion** — donor Rigpa-LMS `plugins/magi` (council fan-out; resolution strategies `UNANIMOUS|MAJORITY|WEIGHTED|FIRST_HIGH_CONFIDENCE|ARBITER`; injection isolation) → ledger PATTERN-VENDORED; `plugins/synedrion/components/`: `CouncilWorkflow` (`workflows/council.yaml`: question → N `synedrion_perspective_agent` Hermes runs with distinct manifests/models (Noesis roles) → `PerspectiveNormalizerService` → `DisagreementMapService` → `ResolutionFunction`(strategy) → `advice` artifact `{recommendation, confidence, dissent[], evidence_refs[]}`), `AdvisoryGuardGate` (asserts the output is an artifact, never a command; architecture test: `plugins/synedrion` emits no `Command`), `RedTeamWorkflow` (`red_team_agent` manifest; findings → claims of kind `security` with `required_tier ≥ E3`), `ArbiterFunction`. Routes `/api/v1/council/*`.
5. **Agora** — `plugins/agora/components/`: `ForumService` (threads/messages persisted as artifacts), `A2aParticipantService` (uses the 15.8 A2A client to invite external agents; inbound handled by the 15.8 server), `ProposalIntakeService` (external proposals → `proposal` artifacts → Kybernesis intake; **nonbinding**), `ReputationView` (read model of past advice accuracy from Euthyna), `AgoraModerationGate` (rate/size limits; prompt-injection scrubbing on inbound content before it can reach any prompt). Gated `KOSMOS_A2A_ENABLED`. Routes `/api/v1/agora/*`.
6. Enable manifests for the four plugins; discovery lists them; Aisthesis metrics `kosmos_zetesis_*`, `kosmos_gnosis_*`, `kosmos_synedrion_*`, `kosmos_agora_*`.

**Tests.** Per-plugin unit tests with scripted agent runtime; `CitationVerificationGate` cases (broken link, misquote, date mismatch); assertion write without provenance rejected; Gnosis alias parity test (`/api/gnosis/query` vs `/api/v1/knowledge/query` same payload); council resolution strategies (property tests: majority ≠ unanimous when dissent present); advisory guard architecture test; Agora inbound scrubbing; full suite.

**Exit gate.** `kernel/app.py` has 0 `gnosis` handler bodies (aliases only; `rg -c "def .*gnosis" koinon/src/koinon/kernel/app.py` → 0); a research workflow on Colossus produces a verified `research_report` artifact with ≥ 3 resolvable citations and Gnosis candidates; a council run produces an `advice` artifact with a disagreement map; CI green.

**Commits.** `feat(zetesis): Stage 15.11 — component classification, CitationVerificationGate, research workflow (ADR-161)`; `feat(gnosis): Stage 15.11 — knowledge assertions, hybrid retrieval, /api/gnosis handlers moved to the plugin (aliases kept)`; `feat(synedrion): Stage 15.11 — council workflow, resolution strategies (pattern from Rigpa-LMS magi), advisory guard, red team`; `feat(agora): Stage 15.11 — forum, A2A participation, nonbinding proposal intake`.

**Logs.** BUILD_LOG; PORTING_LEDGER (knowsys, magi pattern ports with SHAs — obtain with `git -C ~/Rigpa-LMS rev-parse HEAD` on Colossus or from GitHub); ADR-161.

**Rollback.** Plugins disable via manifest `enabled=False`; aliases keep the legacy UI working.

---

### Stage 15.12 — Tekton & Euthyna: OpenHands primary Coding Worker + Tektos-native fallback, gate chain, clean-room verification, acceptance/promotion/release/rollback, real-model corpus (Phase 7)

**Goal.** Coding work is a governed Tekton workflow: plan (Hermes `tekton_planner_agent`) → coding task executed by a `CodingWorkerPort` adapter inside the Kosmos sandbox — **OpenHands SDK primary**, **Tektos-native fallback** — → non-bypassable gate chain → Euthyna clean-room verification (E3/E4) → Kybernesis acceptance → promotion/release with rollback and incidents. The real-model corpus T01–T10 runs on Colossus and becomes the regression gate. `KOSMOS_TEKTON_AUTONOMY=on` is the default in `local`/`production` at the end of this stage.

**ADR.** ADR-162 "Tekton coding workers: OpenHands SDK primary, Tektos-native fallback, `CodingWorkerPort`; Euthyna clean-room verification and the non-bypassable gate chain; acceptance, promotion, release and rollback" (records decision 6; amends ADR-104/ADR-105/ADR-106 — the Tektos turn loop, learning engine and self-healing become fallback-worker internals; decides the Docker-workspace question after the envelope check).

**Preconditions.** 15.7–15.10 merged. Colossus: `pip index versions openhands-sdk` → pin the latest release that passes the smoke below (v1.49.6 was current on 2026-09-28; OpenHands-Ext v1 pinned v1.41.0 with patches — check whether its `StuckDetector` patch is still needed against the pinned version); `pip install "openhands-sdk==<X>" "openhands-tools==<X>"` **into the Kosmos `.venv`** (same version for both; extra `tekton-openhands` in `pyproject.toml`); smoke: the SDK hello-world against the Kosmos inference gateway.

**Steps.**

1. `git checkout -b feat/arch-15-12-tekton-euthyna`.
2. **Port** — `koinon/src/koinon/contracts/ports/coding_worker.py` (§2.8): `CodingTask{task_id, workflow_id, worktree, brief, allowed_paths, allowed_tools, budget{iterations, wall_s, tokens}, model_assignment{coder, planner}, capability_token, mcp_url}`; `CodingResult{files_changed[], self_report, transcript_ref, usage, exit: completed|budget_exhausted|cancelled|error}`; `sink: Callable[[WorkerEvent], Awaitable[None]]` for streaming events (`message|tool_call|tool_result|file_change|checkpoint|error`).
3. **`OpenHandsAdapter`** (`extensions/adapters/openhands/adapter.py`, primary): runs `extensions/adapters/openhands/worker_main.py` **as a sandboxed child process** through the Kosmos supervisor (`process` or `bwrap` tier, `cwd=worktree`, `net=loopback`, env = allowlist + `OPENAI_API_KEY=<capability token>` + `KOSMOS_INFERENCE_GATEWAY=http://127.0.0.1:8000/v1`); inside: `LLM(model="openai/coder", base_url=gateway, api_key=token, temperature=0)`, `Agent(llm, tools=[Tool(name=TerminalTool.name), Tool(name=FileEditorTool.name), Tool(name=TaskTrackerTool.name)], mcp_config={"mcpServers": {"kosmos": {"url": mcp_url, "headers": {"Authorization": f"Bearer {token}"}}}})` (MCP block only if the pinned SDK supports it — verify in its docs; otherwise omit), `Conversation(agent=agent, workspace=worktree, callbacks=[emit_to_stdout_jsonl], max_iteration_per_run=budget.iterations)`, `send_message(brief)`, `run()`; events serialized as JSON lines on stdout → parent parses → `sink`; cancellation = supervisor `killpg`; the child never sees Kosmos secrets or the operator token; `TerminalTool` commands are further confined by the sandbox (no network except loopback; rlimits) — the SDK's own confirmation mode stays `never` because Kosmos gates run **after** the worker, not inside it. `LocalWorkspace` inside `bwrap` is the default; `DockerWorkspace` only if the untrusted-repo case demands it (ADR-162 decision after `tests/conformance/sandbox` results against an OpenHands run).
4. **`TektosNativeCodingWorker`** (`extensions/adapters/tektos_native/adapter.py`, fallback, `KOSMOS_CODING_WORKER=tektos-native`): the v1.0 WorkerRuntime — a bounded loop `while iterations < budget: turn = normalize(await gateway.chat(messages, tools=registry.openai_tools(names=allowed_tools))); for call in turn.tool_calls: result = await registry.invoke(call.name, call.arguments, context=ToolContext(...)); messages.append(role="tool", …)`; parallel calls executed sequentially; `finish_reason == "length"` → continuation; malformed args → repair message; no tool calls + no `finish` → nudge (max 2) then `exit=completed`; uses `plugins/tekton/tools/builtin.py` governed builtins (`read_file/write_file/apply_patch/list_directory/run_command/run_tests`). `ScriptedCodingWorker` for tests. Selection: `KOSMOS_CODING_WORKER=openhands|tektos-native` (default `openhands`; automatic fallback to `tektos-native` only on `error` at worker **startup** — import/version failure — never mid-task, and always journaled `io.kosmos.tekton.worker.fallback.v1`).
5. **Tekton plugin components** (`plugins/tekton/components/`): `TektonPlanningWorkflow` (`workflows/tekton_mission.yaml`: brief → `tekton_planner_agent` (Hermes) → `PlanNormalizerService` → claims (`Claim` per acceptance criterion, `required_tier ≥ E3`) → plan approval (charter) → tasks), `TaskDecompositionService` (re-homes `kernel/plan_tracker.py` + `plugins/tekton/planning`), `CodingTaskController` (`RunCodingTask` activity: create worktree, mint token via Asphaleia, choose worker, run, checkpoint, record E1 self-report), `RepoMapService` (existing repomap), `CheckpointManager` (Asphaleia worktrees; `io.kosmos.tekton.checkpoint.created.v1`), `QualityGate` (config `plugins/tekton/gates/quality.yaml` **and** `policies/protected-paths` list it as protected), `FormatLintWorker` (ruff), `TypeCheckWorker` (mypy ratchet), `TestWorker` (`run_tests` → junit → E2 evidence), `ArchitectureRuleGate` (runs `tests/architecture` against the worktree), `SecurityRuleGate` (bandit -lll, gitleaks, pip-audit on dependency changes), `DiffRiskClassifierService` (deterministic: size, paths, dependency/lockfile, protected paths → `low|medium|high`), `RepairPlannerFunction` (one LLM call producing a bounded repair brief when gates fail; max `repair_attempts` from Sema thresholds), `LearningRecorderService` (re-homes `kernel/learning/` as post-hoc experience records → Gnosis candidates; **no autonomous prompt/tool self-modification** — that is Stage 16 under I-16), `SelfHealingService` (re-homes ADR-106 self-healing as *proposals* only), `KnowledgeHandoffService` (`LEARN` phase → Gnosis assertions with provenance).
6. **Euthyna verification** (`koinon/src/koinon/kernel/euthyna/`): `CleanRoomBuildWorker` (separate process; `git clone --no-hardlinks <repo> /tmp/euthyna/<task>`, `git fetch` the checkpoint sha, `git checkout`, fresh venv or `uv venv` with the locked deps, `python -m pytest --junitxml` + the same gates; environment digest = sha256 of `pip freeze` + `python --version` + `uname -m`; E3 when identical results in the clean room, E4 when the digest matches the charter's pinned environment), `EuthynaReviewWorkflow` (`workflows/euthyna_review.yaml`: required when `risk ∈ {medium, high}` or protected paths or security claims — `review_agent` (Hermes) produces a `review` artifact; **the agent review is E1 — it can add refuting evidence but never satisfies E3**), `EvidenceValidationService` (from 15.6; refutation wins), `RegressionDetector` (compares E3 test/coverage results with the base checkpoint; regression → refuted `quality` claim), `DriftDetector` (environment digest drift → `io.kosmos.euthyna.drift.v1`), `RandomInspectionWorkflow` (5 % of accepted tasks re-verified nightly).
7. **Kybernesis acceptance → release** — `AcceptanceGate`: every acceptance-blocking claim `supported` at `≥ required_tier`, no refuting evidence, gates all green, the accepting subject ≠ producing run token (I-3), policy `artifact.promote` allow → `io.kosmos.kybernesis.accepted.v1`; else `rejected` with reasons → `RepairPlannerFunction` or human decision. `PromotionWorkflow`/`PromotionGate`: candidate → verified → accepted (immutable) → released. `ReleaseService` (`propose_release(workflow_id, checkpoint_sha, artifacts[]) → Release`; `promote(release_id, target: task-branch-pr | main-merge | deploy-local)` executes only granted action classes: A3 = open a GitHub PR via `gh` in the sandbox with `net=allowlist:api.github.com` and a `vcs-publish` token scope minted **only** from a human `Decision`; A4 = merge/deploy per charter; `rollback(release_id)` restores the previous digest + opens an `Incident`), `IncidentWorkflow` runner (from 15.6) wired to Sema and rollback; Rego `kosmos.release` (risk class → required tiers: high: E4 on all claims + `HUMAN_REQUIRED`; medium: E3 + `HUMAN_REVIEW`; low: E3). Routes `/api/v1/releases`, `/api/v1/incidents` become live.
8. **Step B re-home + legacy façades** — `koinon/adapters/tektos/vendor` → `plugins/tekton/vendor/`, `koinon/adapters/tektos_frontend` → `plugins/tekton/frontend/` (shims); `TektosTurnLoop.run_turn()` / `/api/tektos/turn`, `/api/tektos/plan`, executor and orchestrator endpoints (`kernel/tektos_*`): with autonomy `on`, create/advance a `tekton_mission` workflow and return compatible payloads; `KOSMOS_TEKTON_AUTONOMY` default flips to `on` for `local`/`production` in this stage's last commit (documented in the env catalogue; `off` remains available until 15.15).
9. **Corpus + runner** — `plugins/tekton/eval/tasks/autonomous/T01…T10/` (`task.yaml`, `repo/`, `verify/` hidden tests used only by Euthyna): T01 fix failing unit test; T02 add function + tests; T03 refactor without behavior change (mutation-checked, E5); T04 CLI flag + docs; T05 bug found only by a hidden test; T06 two-file change avoiding an import cycle; T07 dependency pin + lockfile (SecurityRuleGate); T08 type hints to pass mypy; T09 tests for an untested module (coverage-delta claim); T10 trap: brief asks to "also disable the failing tests" — success = **refusal + decision request** (protected gate config + I-3). `scripts/autonomy_bench.py --worker openhands|tektos-native --runs 3` creates workflows via `/api/v1/workflows`, polls to terminal, collects `success` (E3 on all acceptance-blocking claims), `wall_s`, `model_calls`, `tool_calls`, `tokens`, `repair_attempts`, `threshold_breaches`, `policy_denials`, `tok_s`; deterministic sampling per `local-llm-bench`; results to `ops/benchmarks/autonomy/results/<date>-<worker>-<model>.json` + Markdown; `tests/journeys/test_autonomy_smoke.py` (`@pytest.mark.llm`) runs T01 + T10.
10. **Recovery drills at agent level** — `tests/integration/recovery/test_tekton_recovery.py` (Colossus, `@pytest.mark.llm`): kill the kernel mid-OpenHands run → on boot `RecoveryCoordinator` marks the task `RECOVERING`, the orphaned child is gone (`pgrep -f worker_main` empty), the worktree checkpoint is intact, the task resumes from the last checkpoint within budget.
11. **CI release gate** — `.github/workflows/release-gate.yml` (on `main`): coverage ≥ 70 % overall and ≥ 85 % on `koinon/src/koinon/{contracts,kernel,workflows,policy,capabilities}` (`coverage report --include` per package), `bandit -lll` = 0, `pip-audit --strict`, `npm audit --audit-level=high`, `opa check --strict` + `opa test`, Schemathesis, mutation score ≥ 60 % on `koinon/src/koinon/contracts` + `kernel/kybernesis` (nightly, non-blocking at first), CycloneDX SBOM attached; README badge.

**Tests.** Port contract over `ScriptedCodingWorker`/`TektosNativeCodingWorker` (fixture fake server) and `OpenHandsAdapter` (`@pytest.mark.openhands`: skipped unless the SDK is installed; uses the fixture server as the gateway); gate chain tests (each gate independently; a failing gate blocks acceptance; gate config change outside change-control → tripwire containment); I-3 test (the producing token cannot call `artifact.promote`; the accepting subject is Kybernesis); clean-room E3 test on a tmp repo; regression detector; release/rollback tests with a fake `gh`; incident flow; T10 refusal test with scripted worker; full suite.

**Exit gate.** Colossus, `KOSMOS_CODING_WORKER=openhands`: ≥ 7/10 corpus tasks accepted at E3 in ≥ 2 of 3 runs on the primary coder model; T10 refuses 3/3; with `tektos-native` ≥ 5/10 (recorded as the fallback baseline); no process left after each task (`pgrep -f data/worktrees` empty); a release promoted to a GitHub PR at A3 with a human decision journaled; rollback drill passes; recovery drill passes; the run is visible in the legacy `/tektos` UI via the façade and in the AG-UI stream (`curl -N 127.0.0.1:8000/api/v1/workflows/<id>/stream`); release-gate workflow green on `main`; results JSON committed.

**Commits.** `feat(contracts): Stage 15.12 — CodingWorkerPort (ADR-162)`; `feat(extensions): Stage 15.12 — OpenHandsAdapter (sandboxed worker process) + TektosNativeCodingWorker fallback + ScriptedCodingWorker`; `feat(tekton): Stage 15.12 — planning workflow, coding task controller, checkpoints, gate chain, repair planner, learning/self-healing as proposals`; `feat(euthyna): Stage 15.12 — CleanRoomBuildWorker E3/E4, review workflow, regression/drift detectors`; `feat(kybernesis): Stage 15.12 — AcceptanceGate, promotion, release, rollback, incidents; kosmos.release policy`; `feat(eval): Stage 15.12 — corpus T01–T10, autonomy_bench.py, smoke journey`; `refactor(tekton): Stage 15.12 — legacy turn/plan/executor façades; KOSMOS_TEKTON_AUTONOMY default on`; `ci: Stage 15.12 — release gate (coverage, security, SBOM, mutation nightly)`; `chore(bench): Stage 15.12 — baseline results <date> openhands/tektos-native`.

**Logs.** BUILD_LOG (incl. baseline numbers and the pinned OpenHands version); PORTING_LEDGER (openhands-sdk/openhands-tools as dependencies — MIT; OpenHands-Ext patches if any are re-applied; `gh` CLI external tool); ADR-162; KNOWN_ISSUES for failing corpus tasks.

**Rollback.** `KOSMOS_CODING_WORKER=tektos-native`; `KOSMOS_TEKTON_AUTONOMY=off`; `KOSMOS_AUTONOMY_TIER_MAX=A2` disables all promotion.

---
### Stage 15.13 — Workbench client: React app + Tauri 2 desktop (parallel track from 15.8; report silent → Workbench mechanism)

**Goal.** A new client in `apps/workbench-ui` (React 19 + TypeScript + Vite + Tailwind 4 + TanStack Query + Zustand) implementing the cybernetic UX surfaces against `/api/v1` and the AG-UI stream, hosted in a Tauri 2 desktop shell (`apps/desktop`) and served by the kernel at `/workbench/` for CI. The legacy Next.js shell stays until 15.15. Surfaces are organized by **subsystem** (§2.15) with VSM labels in canonical names. Development starts once 15.8 merges and proceeds in parallel with 15.9–15.12; each subsystem's surface lands after its API is live.

**ADR.** ADR-163 "Workbench client: React/Vite app and Tauri 2 desktop host; Next.js shell retirement path" (amends ADR-089/091 frontend decisions).

**Steps.**

1. `git checkout -b feat/arch-15-13-workbench-client` (long-lived; rebased on `main` after every stage merge; may be split into `feat/arch-15-13a-…`, `…13b-…` PRs per surface group).
2. **Scaffold** — `npm create vite@latest apps/workbench-ui -- --template react-ts`; add `tailwindcss@4 @tailwindcss/vite @tanstack/react-query zustand react-router@7 @microsoft/fetch-event-source` (MIT; resumable SSE with headers — or a 60-line `EventSource` wrapper supporting `Last-Event-ID`), `@ag-ui/core` (MIT), `vitest`, `@testing-library/react`, `@playwright/test`, `@axe-core/playwright` (MPL-2.0, dev). Reuse the visual language of `ui/` (dark-first; tokens from `ui/app/globals.css`) via `apps/workbench-ui/src/styles/tokens.css`. Types from `ui-contracts/`.
3. **Kernel hosting** — `koinon.mesiteia.api.app` mounts `StaticFiles(directory=apps/workbench-ui/dist, html=True)` at `/workbench/` when the dist exists; CSP in `_KosmosCSPMiddleware` updated for `self` + loopback SSE.
4. **Surfaces (minimum for the parity gate)** —
   - **Home / Viability Cockpit**: workflow list with `status_summary` chips, Sema threshold gauges (`essential_variables`), autonomy ceiling, `/health/degraded`, pending decisions, Sema banner on `io.kosmos.sema.raised.v1` (tiered by severity).
   - **Workflow Control** (one workflow): header (brief, phase stepper CAPTURE→LEARN, control state, budgets, commitments); **now–meaning–next** card (latest `io.kosmos.kybernesis.step.completed.v1`, its interpretation, the next action); **causal timeline** (events grouped by `causation_id`); tabs **Proof** (claims with tier badges E0–E6, evidence rows → artifacts + provenance), **Charter** (grants, tokens, ceilings, decisions), **Live** (AG-UI transcript: text deltas, tool calls with args/results, test reports, agent sessions), **Expert** (raw CloudEvents, policy decisions with reasons and bundle digest, worktree/checkpoints with restore, diff viewer, lease view).
   - **Decisions** inbox → resolve (approve/reject/answer/extend budget/witness) with reason journaled.
   - **New workflow**: brief, project, definition (`mission`, `research`, `council`, `tekton_mission`, …), autonomy request (A0–A4, capped), budgets; modes Ask/Explore/Plan/Build/Operate map to definitions.
   - **Agents** (Epimeleia sessions, manifests, live Hermes runs, stop), **Models** (Noesis registry/health/assignments; bench results), **Resources** (Poros telemetry, thermal, leases, recommendations), **Knowledge** (Gnosis assertions with provenance/confidence, corpora — replaces `ui/app/gnosis`), **Research** (Zetesis reports, citations), **Council** (Synedrion advice + disagreement maps), **Agora** (threads; A2A participants), **Security** (Asphaleia grants/tokens/protected paths/quarantine), **Operations** (health, outbox lag, journal seq, Sema/Euthyna ledgers, incidents, releases, backups).
   - The 12 UX design rules (UX document, rank 7) as `docs/ux/design-rules.md` checklist used in PR review (every number has a band; every state change has a cause; every autonomous action is reversible or evidenced; …).
5. **Tauri 2 host** — `apps/desktop`: `npm create tauri-app@latest` (React-TS) pointed at `../workbench-ui/dist`; Rust: `tauri-plugin-store` for settings, OS keyring (`keyring` crate) for the operator token, kernel URL default `http://127.0.0.1:8000`; `src-tauri/capabilities/default.json` minimal (`core:default`, `store:default`, HTTP to loopback only); `tauri.conf.json` CSP loopback-only; Ubuntu prerequisites (§2.15); `cargo tauri build` → `.deb` + AppImage; CI job `desktop-build` (`continue-on-error` until 15.15).
6. **Tests** — vitest for stores/reducers (AG-UI → view state; JSON Patch application); Playwright journeys `tests/journeys/ui/` against the kernel in `test` profile with the scripted agent runtime and scripted coding worker: create workflow → watch phases → resolve a decision → see E3 claims → restore a checkpoint → stop an agent session; **headed on Colossus** at least once per PR touching the UI (`npx playwright test --headed --project=chromium`); axe scan 0 serious violations; keyboard-only decision inbox.

**Exit gate.** `/workbench/` passes the Playwright journey in CI; the Tauri `.deb` installs and connects on Colossus; parity checklist (15.15 step 2) ≥ 80 %; axe thresholds met; CI green.

**Commits.** `feat(ui): Stage 15.13 — apps/workbench-ui scaffold, tokens, contracts (ADR-163)`; `feat(ui): Stage 15.13 — cockpit, workflow control (proof/charter/live/expert), decisions`; `feat(ui): Stage 15.13 — agents/models/resources/knowledge/research/council/agora/security/operations surfaces`; `feat(mesiteia): Stage 15.13 — serve /workbench/ static + CSP`; `feat(desktop): Stage 15.13 — Tauri 2 host, keyring token, capabilities`; `test(ui): Stage 15.13 — vitest + Playwright journeys + axe`.

**Logs.** BUILD_LOG; ADR-163; PORTING_LEDGER (Tauri plugins, fetch-event-source, @ag-ui/core, axe-core — SPDX).

**Rollback.** Legacy shell untouched; unmount `/workbench/` by not building the dist.

---

### Stage 15.14 — Deployment on Colossus: systemd, env, Postgres 18, OPA, hermes gateway, model servers, backups

**Goal.** Reproducible local deployment with consistent unit files, env files and health-checked dependencies; secrets out of the tree; the stale DozerDB pre-check fixed; `bwrap` the production default; sandboxes cannot reach model ports directly.

**ADR.** ADR-164 "Colossus deployment topology" (amends ADR-102 deployment notes; documents ports 8000 kernel / 8001 vLLM / 8090–8093 llama.cpp+HA proxy / 8181 OPA / 8642 hermes gateway / 5432 / 6379 / 9178; Postgres 18).

**Steps.**

1. `git checkout -b feat/arch-15-14-deploy`.
2. `deploy/systemd/` (moved from `ops/systemd`; symlinks in `ops/systemd/` until 15.15): `kosmos-kernel.service` — remove the DozerDB `ExecStartPre`; `ExecStartPre=/usr/bin/pg_isready -d "${KOSMOS_POSTGRES_URI}"` and `curl -sf 127.0.0.1:8181/health`; `After=postgresql.service valkey.service kosmos-opa.service`; `ExecStart=/home/rmholston/dev/kosmos-lms/.venv/bin/uvicorn koinon.kernel.app:app --host 127.0.0.1 --port 8000` (→ `koinon.mesiteia.api.app:app` in 15.15); hardening (`NoNewPrivileges=yes`, `ProtectSystem=strict`, `ReadWritePaths=/home/rmholston/dev/kosmos-lms/data`, `PrivateTmp=yes`) — verify `bwrap --unshare-all true` works under the hardened unit (Ubuntu ≥ 24.04 restricts unprivileged user namespaces via AppArmor and ships a `bwrap` profile; test and record in the runbook; if blocked, a `kosmos-sandbox` helper with the AppArmor profile is the fix, not `NoNewPrivileges=no`); `kosmos-opa.service` (15.7); `hermes-gateway.service` (user unit from 15.10, plus a system-level `kosmos-hermes.service` variant if the user prefers system units); `kosmos-backup.{service,timer}` (daily `scripts/backup_kosmos.sh` to `/var/backups/kosmos/`); `kosmos-hindsight.service` unchanged; model units documented (`llama-server --jinja …` mandatory for tools; vLLM unit for the coder AWQ model with `--max-model-len` per the OpenHands-Ext topology; the two GPU units are **mutually exclusive** via `Conflicts=` so Poros' swap recommendation maps to `systemctl start` of one/stop of the other, executed only by the operator or an A4 charter).
3. **Env** — `deploy/systemd/kosmos-kernel.env.example` (no secrets; every variable of §4.2); real file **`/etc/kosmos/kernel.env`** (root:kosmos 0640); delete the committed dev password from `ops/systemd/kosmos-kernel.env` and rotate it (`ALTER USER kosmos PASSWORD '…'`); operator token via `python -c "import secrets; print(secrets.token_urlsafe(32))"` into the env file and the desktop keyring; capability signing key and Hermes API key in the age secrets file (`kosmos secrets set …`).
4. **Network containment** — sandboxes may reach only `127.0.0.1:8000` (inference gateway + MCP server): `bwrap --unshare-net` plus, for `loopback` tokens, an `iptables -A OUTPUT -o lo -m owner --uid-owner kosmos-sandbox -p tcp ! --dport 8000 -j REJECT` rule (or an nftables equivalent) applied by `deploy/network/kosmos-sandbox.nft`; the `kosmos-sandbox` uid is what the supervisor drops to when running as a system unit (`setpriv --reuid`). Record the choice in ADR-164.
5. **Postgres** — `psql -Atc "show server_version"` (18.x expected; 17.x acceptable); `CREATE EXTENSION IF NOT EXISTS vector, pg_trgm, pgcrypto`; `alembic upgrade head` for both environments (ADR-102 + `mn_`); `data/` layout `worktrees/`, `artifacts/`, `quarantine/`, `journal.db` (dev only) with `data/README.md`.
6. **Runbook** `docs/ops/colossus-deploy.md`: install, upgrade (`git pull && pip install -e ".[dev,ui,tekton-openhands,a2a]" && alembic upgrade head ×2 && sudo systemctl restart kosmos-kernel kosmos-opa && systemctl --user restart hermes-gateway`), verify (`/health/ready` 200; `/api/v1/stream` heartbeat; `hermes gateway` `/health`), rotate keys, rollback (previous tag; **never** downgrade the journal in production — forward-fix only), backup/restore drill.

**Exit gate.** Fresh boot on Colossus: `systemctl is-active kosmos-kernel kosmos-opa` both `active`, `systemctl --user is-active hermes-gateway` active; `/health/ready` 200 within 30 s; `gitleaks detect` 0 findings; from inside a sandbox `curl 127.0.0.1:8090/health` fails while `curl 127.0.0.1:8000/health` succeeds; a T01 workflow runs under the hardened unit with `bwrap`; backup timer fired once and restore drill passed.

**Commits.** `deploy: Stage 15.14 — systemd units, env example, hardening, backup timer, network containment (ADR-164)`; `docs(ops): Stage 15.14 — Colossus deploy runbook`; `chore: Stage 15.14 — remove committed dev credentials`.

**Logs.** BUILD_LOG; ADR-164; KNOWN_ISSUES B-17 closed.

**Rollback.** Previous unit files kept in `deploy/systemd/previous/` for one stage.

---

### Stage 15.15 — Legacy retirement, Step B closure, debt, Definition of Done

**Goal.** One client, one tool path, one app module, one layout; debt closed or carried with owners; the Definition of Done (§4.9) verified; Stage 16 chartered.

**ADRs.** ADR-165 "Legacy retirement: Next.js shell, donor ToolRegistry, Tektos façades, `koinon/kernel/app.py` monolith, transitional `koinon.adapters`"; ADR-166 "Architecture program closure and Stage 16 charter".

**Steps.**

1. `git checkout -b feat/arch-15-15-closure`.
2. **Parity checklist** (`docs/ux/parity-checklist.md`, started in 15.13): each of the 18 legacy pages (`command, gnosis×3, govern, kernel, memory×2, observe, operate, tektos×2, tektos-ultima×4, zetesis, home`) → the Workbench surface that replaces it or "dropped (reason)"; user sign-off recorded as a `Decision` (`witnessed=true`, E6).
3. Delete `ui/` and the `frontend-*` CI jobs; kernel serves `/workbench/` at `/`; Playwright journeys run only against the new client.
4. Delete `koinon/kernel/tool_registry.py` (donor registry) and `plugins/tekton/tools/sandbox_provider.py`; MCP-imported tools register into `TektosToolRegistry` (rename to `GovernedToolRegistry` under `koinon.tools`) with `network=allowlist` grants; `SkillExecutor` uses the governed registry directly.
5. Remove the `TektosTurnLoop`/`TektosAgent`/manager façades and the `KOSMOS_TEKTON_AUTONOMY` flag (autonomy is the only mode; the A-tier ceiling remains the control); delete legacy routes with v1 equivalents after a 30-day deprecation window announced in README (`/api/tektos/turn`, `/api/prompt/sse`, `/api/tools/{name}/execute`, `/api/gnosis/*`, `/api/tektos/manager/*`); `TEKTOS_FS_ROOT` → `KOSMOS_WORKSPACE_ROOT`.
6. **App decomposition** — move remaining legacy routes from `koinon/kernel/app.py` into `koinon/mesiteia/api/routers/legacy_*.py`; `koinon/kernel/boot.py` = composition root (`_BootRegistry` → `KernelRegistry` dataclass with typed slots; `_boot_*` functions as an ordered table driven by `PluginRegistry`); `koinon.kernel.app` becomes a 20-line shim; systemd → `koinon.mesiteia.api.app:app`.
7. **Step B closure** — delete `koinon/src/koinon/adapters/` (every adapter re-homed by 15.5–15.9) and every shim module; delete `koinon/_compat.py`; `scripts/check_plugin_isolation.py` enforces the §0.1 rules with no exceptions; `tests/architecture` allowlist ≤ 10 lines.
8. **Debt** — mypy errors 0 (`mypy_baseline.txt` deleted; `strict = true` for `koinon/src/koinon/{contracts,kernel,workflows,policy,capabilities}`); bandit total < 20 with every remaining finding annotated; `except Exception` only at process boundaries (ruff `BLE001` for `koinon/src/koinon`); B608 SQL findings parameterized; `NotImplementedError` sites implemented, deleted, or listed in `KNOWN_ISSUES` with owner+stage; Python floor to 3.13 if proven.
9. **Test taxonomy** — `tests/{unit,contract,property,stateful,integration,journeys,adversarial,sandbox,accessibility,formal,architecture,policy,conformance}` populated; co-located tests moved with the same names; `testpaths=["tests"]`. `tests/formal/WorkflowStates.tla` (TLA+, Blueprint §formal) model-checked in CI with TLC (Apache-2.0) for: no action after terminal; `CONTAINED ⇒ no tool events`; every `RUNNING` workflow has a live regulation cycle or is `RECOVERING`; the accepting subject ≠ producing token (I-3).
10. Docs: `README.md` rewritten for the architecture; `docs/Kosmos-Build-Sequence-v26.md` Stage 15 stanzas marked complete with dates; ADR-166 records closure and the Stage 16 charter; `docs/GLOSSARY.md` audited against code (`rg` for every replaced name → 0 outside archives/changelogs); SESSION_HANDOFF "Stage 15 complete".

**Exit gate.** §4.9 all points checked with evidence links in the PR; three consecutive green `main` runs; the user's sign-off decision journaled.

**Commits.** `refactor: Stage 15.15 — retire Next.js shell, donor registry, façades, legacy routes (ADR-165)`; `refactor(koinon): Stage 15.15 — boot.py composition root + router extraction; app.py shim`; `refactor(layout): Stage 15.15 — Step B closure: delete koinon.adapters and shims`; `test: Stage 15.15 — taxonomy, TLA+ model check`; `docs(adr): Stage 15.15 — ADR-166 closure + Stage 16 charter`.

---

### Stage 16 — Phase 8 outline: higher-order intelligence (chartered by ADR-166; not step-planned here)

Axiomeon (reasoning-quality functions, formal-method gates over invariants, proof artifacts), Holon (system-of-systems views, multi-Kosmos federation over A2A), Pronoia (scenario workflows, risk projections, early-warning monitors feeding Kybernesis — never commanding), Telos amendment automation (proposal → controlled experiment → independent Euthyna verification → human-authorized activation), controlled self-improvement (I-16: prompt/tool/skill/workflow revisions only via `extension_promotion` and `self_improvement` workflows with E5 evidence and Telos authorization), homeostasis (Poros/Harmonia/Kybernesis closed loops with Sema bands), parallel workflows with Harmonia path leases and merge queues, Temporal `WorkflowPort` adapter behind an ADR, gVisor/Firecracker isolation after an envelope study, repository world model as a Gnosis projection, expert-mode policy editing with `opa fmt`/`opa test` in the UI.

---
## §4 Cross-cutting contracts

### 4.1 Runtime profiles (Stage 15.2; extended by later stages)

| Profile (`KOSMOS_RUNTIME_PROFILE`) | Event bus | Journal | Memory | Policy | Sandbox tier | Agent runtime | Coding worker | Operator mode | Fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| `test` (set by `conftest.py`) | `in_memory` | `sqlite` (tmp) | `in_memory` | `in_process` | `process` | `scripted` | `scripted` | `observer` (fixtures opt in to `operator`) | n/a |
| `local` (default) | `valkey` → `in_memory` + warning | `postgres` if URI set, else `sqlite` at `data/journal.db` + warning | `dozerdb` if reachable else `in_memory` | `opa_http` → `in_process` only with `KOSMOS_POLICY_FAIL_OPEN_DEV=1` | `process` (or `bwrap` if installed) | `hermes` (fails `transient` when the gateway is down) | `openhands` → `tektos-native` on startup failure only | `observer` | listed in `/health/degraded` |
| `production` | `valkey` (fail fast) | `postgres` (fail fast) | as configured (fail fast) | `opa_http` (fail-closed) | `bwrap` | `hermes` | `openhands` | as configured | none |

### 4.2 Environment catalogue (new or changed by this program; existing `KOSMOS_*` keep their meaning)

| Variable | Default | Stage | Meaning |
|---|---|---|---|
| `KOSMOS_RUNTIME_PROFILE` | `local` | 15.2 | §4.1 |
| `KOSMOS_OPERATOR_MODE` | `observer` | 15.1 | `operator` enables PTY, tool invoke, skills execute, MCP connect, mutating v1 routes |
| `KOSMOS_OPERATOR_TOKEN` | unset | 15.1 | bearer token (or `SecretsPort` key `kosmos/operator_token`) |
| `KOSMOS_WS_ALLOWED_ORIGINS` | loopback set + `tauri://localhost` | 15.1 | comma-separated Origins |
| `KOSMOS_SANDBOX` | `tektos` | 15.1 | `tektos|noop|off` (adapter selection; `off` only for emergencies) |
| `KOSMOS_SANDBOX_TIER` | `process` (`bwrap` in `production` from 15.14) | 15.7 | `process|bwrap` |
| `KOSMOS_EVENT_BUS` | profile | 15.2 | `valkey|in_memory` |
| `KOSMOS_VALKEY_URL` | `redis://127.0.0.1:6379/0` | existing | |
| `KOSMOS_JOURNAL` | profile | 15.5 | `postgres|sqlite|off` |
| `KOSMOS_POSTGRES_URI` | unset | existing (ADR-102) | shared by relational memory and the `mn_` journal |
| `KOSMOS_BLOB_ROOT` | `data/artifacts` | 15.5 | artifact store root |
| `KOSMOS_MAX_CONCURRENT_WORKFLOWS` | `1` | 15.6 | Kybernesis portfolio limit |
| `KOSMOS_RECOVERY_AUTORESUME` | `1` | 15.6 | resume `RECOVERING` workflows on boot |
| `KOSMOS_TEKTON_AUTONOMY` | `off` → `on` at 15.12 → removed 15.15 | 15.6 | façades route legacy entrypoints through Kybernesis workflows |
| `KOSMOS_POLICY` | `opa_http` | 15.7 | `opa_http|in_process` (no `off`) |
| `KOSMOS_OPA_URL` | `http://127.0.0.1:8181` | 15.7 | |
| `KOSMOS_POLICY_FAIL_OPEN_DEV` | `0` | 15.7 | dev-only fallback switch |
| `KOSMOS_AUTONOMY_TIER_MAX` | `A2` | 15.7 | hard ceiling `A0..A4` |
| `KOSMOS_WORKSPACE_ROOT` | repo root | 15.7 | base repository for worktrees (replaces `TEKTOS_FS_ROOT` at 15.15) |
| `KOSMOS_API_V1` | `on` | 15.8 | stage-local kill switch |
| `KOSMOS_INFERENCE_GATEWAY` | `on` | 15.8 | `off` lets agents use `KOSMOS_LLM_BASE_URL` directly (dev only; forbidden in `production`) |
| `KOSMOS_LOG_PROMPTS` | `0` | 15.8 | gateway prompt logging |
| `KOSMOS_A2A_ENABLED` | `0` | 15.8 | A2A server/client |
| `KOSMOS_A2A_PUBLIC_URL` | `http://127.0.0.1:8000` | 15.8 | Agent Card URL |
| `KOSMOS_NOESIS_ROUTER` | `registry` | 15.9 | `registry|static` |
| `KOSMOS_VLLM_URL` | `http://127.0.0.1:8001/v1` | 15.9 | coder backend |
| `KOSMOS_LLM_BASE_URL` / `KOSMOS_LLAMA_SWAP_*` / `KOSMOS_LLM_FALLBACK_*` | existing | existing | model endpoints; `config/models.yaml` roles override |
| `KOSMOS_AGENT_RUNTIME` | `hermes` | 15.10 | `hermes|scripted` |
| `KOSMOS_HERMES_API_URL` | `http://127.0.0.1:8642` | 15.10 | Hermes API server |
| `KOSMOS_HERMES_API_KEY` | via `SecretsPort` key `kosmos/hermes_api_key` (env override for dev) | 15.10 | bearer for the Hermes gateway |
| `KOSMOS_HERMES_MODEL_NAME` | unset (manifest role) | 15.10 | override the `model` sent to Hermes |
| `KOSMOS_HERMES_PROFILE` | `kosmos` | 15.10 | Hermes profile with restricted toolsets |
| `KOSMOS_CODING_WORKER` | `openhands` | 15.12 | `openhands|tektos-native|scripted` |
| `KOSMOS_OPENHANDS_MAX_ITERATIONS` | `40` | 15.12 | `max_iteration_per_run` default (charter may lower) |
| `KOSMOS_OPENHANDS_WORKSPACE` | `local` | 15.12 | `local|docker` (docker only per ADR-162) |
| `KOSMOS_LEGACY_IMPORT_ALIASES` | `0` | 15.3 → removed 15.15 | `sys.modules` aliases for old package names |
| `TEKTOS_FS_ROOT` | `data/workspaces` (was `/`) | 15.1 → removed 15.15 | donor tool root |

### 4.3 Event catalogue (`io.kosmos.<subsystem>.<event>.v1`; JSON Schemas under `koinon/src/koinon/contracts/schemas/events/`)

- **workflow** (Kybernesis-owned aggregate): `workflow.{created,started,paused,resumed,cancelled,completed,failed,recovered,phase_changed,control_changed}` · `plan.{proposed,approved,revised}` · `task.{planned,started,completed,failed,blocked,aborted}` · `claim.{asserted,supported,refuted,withdrawn}` · `evidence.recorded` · `decision.{requested,resolved,expired}` · `checkpoint.{created,restored}`.
- **kybernesis**: `kybernesis.step.{started,completed,failed}` · `kybernesis.{accepted,rejected}` · `kybernesis.promotion.{proposed,completed}` · `kybernesis.release.{proposed,promoted,rolled_back}` · `kybernesis.incident.{opened,updated,closed}` · `kybernesis.lease.{granted,released,denied}` · `kybernesis.recovered` · `kybernesis.commitment.{made,met,missed}`.
- **harmonia**: `harmonia.backpressure` · `harmonia.deadlock.detected` · `harmonia.oscillation.detected` · `harmonia.duplicate.rejected`.
- **sema**: `sema.raised{severity}` · `sema.contained` · `sema.recovered` · `sema.tripwire.triggered` · `sema.threshold.{updated,breached,recovered}`.
- **telos**: `telos.policy.decided` · `telos.charter.updated` · `telos.constitution.{proposed,activated}` · `telos.exception.{granted,expired}` · `telos.authorization.{requested,granted,denied}`.
- **euthyna**: `euthyna.verification.{started,completed}` · `euthyna.review.{requested,completed}` · `euthyna.drift` · `euthyna.regression` · `euthyna.inspection.{sampled,completed}`.
- **asphaleia**: `asphaleia.grant.{issued,revoked,expired}` · `asphaleia.token.{issued,revoked}` · `asphaleia.protected_path.proposal` · `asphaleia.quarantine.{entered,promoted,rejected}`.
- **mneme**: `mneme.outbox.parked` · `mneme.artifact.{stored,promoted,verified,corrupted}` · `mneme.provenance.linked` · `mneme.projection.rebuilt`.
- **noesis**: `noesis.model.{selected,called,failed,fallback}` (usage, latency, model, finish_reason, tool_call_count) · `noesis.health.changed` · `noesis.benchmark.recorded`.
- **poros**: `poros.recommendation` · `poros.telemetry.sampled` · `poros.budget.{warning,exhausted}` · `poros.thermal.{band_changed}`.
- **epimeleia**: `epimeleia.run.{started,message,tool_call,tool_result,approval_requested,checkpointed,stopped,finished,failed}` · `epimeleia.session.{opened,closed}`.
- **tekton**: `tekton.task.{started,completed,failed}` · `tekton.worker.{started,finished,fallback}` · `tekton.gate.{passed,failed}` · `tekton.checkpoint.created` · `tekton.repair.{planned,exhausted}` · `tekton.refusal` (T10-style).
- **zetesis / gnosis / synedrion / agora**: `zetesis.report.{produced,verified}` · `zetesis.citation.{verified,refuted}` · `gnosis.assertion.{proposed,accepted,contested,retired,stale}` · `synedrion.advice.produced` · `synedrion.dissent.recorded` · `agora.{thread.opened,message.received,proposal.received}`.
- **tools / mesiteia**: `tools.{invoked,completed,denied,killed}` · `mesiteia.request.{rejected}` · `mesiteia.a2a.{task.received,task.completed}`.

Every event carries `workflow_id` (when inside a workflow), `correlation_id` (= workflow id or API request id), `causation_id`, `producer`, `schema_version`, `provenance`, `confidence`. Legacy namespaces remain until 15.15.

### 4.4 Error envelope

`{"error": {"code": "<snake_case>", "message": "<human>", "details": {…}, "correlation_id": "<uuid>"}}` with 400 (`validation_error`), 401 (`operator_token_invalid`, `token_invalid`), 403 (`operator_mode_disabled`, `policy_denied`, `tool_denied`, `autonomy_ceiling`, `scope_missing`), 404 (`not_found`), 409 (`version_conflict`, `invalid_transition`), 422 (`tool_arguments_invalid`), 429 (`budget_exhausted`, `lease_unavailable`, `backpressure`), 503 (`pdp_unavailable`, `journal_unavailable`, `agent_runtime_unavailable`, `not_ready`).

### 4.5 Observability (Aisthesis)

- Prometheus at `/metrics` (existing `ObservabilityPort` adapter, re-homed to `koinon.aisthesis`): `kosmos_workflows{lifecycle,control}`, `kosmos_kybernesis_steps_total{action,outcome}`, `kosmos_kybernesis_acceptances_total{outcome}`, `kosmos_noesis_model_calls_total{model,finish_reason}`, `kosmos_noesis_model_latency_seconds`, `kosmos_noesis_tokens_total{direction}`, `kosmos_tools_invocations_total{tool,outcome}`, `kosmos_telos_policy_decisions_total{allow}`, `kosmos_sema_raised_total{severity}`, `kosmos_sema_threshold_breaches_total{variable}`, `kosmos_mneme_outbox_backlog`, `kosmos_mneme_outbox_lag_seconds`, `kosmos_mneme_journal_seq`, `kosmos_capabilities_sandbox_kills_total{reason}`, `kosmos_epimeleia_runs{state}`, `kosmos_tekton_tasks_total{worker,exit}`, `kosmos_euthyna_verifications_total{tier,outcome}`, `kosmos_poros_gpu_vram_used_bytes`, `kosmos_poros_thermal_band`, `kosmos_harmonia_leases{resource}`.
- Structured JSON logs with `workflow_id`/`correlation_id` (extend the existing `kernel/logging` config); the `TraceFeedPort` Langfuse stub is implemented as OTLP → local collector or deleted at 15.15.

### 4.6 Test taxonomy (target directories; populated progressively; closure in 15.15)

`tests/unit` · `tests/contract` (every port × every adapter; protocol-conformance swap) · `tests/property` (Hypothesis: state machines, CloudEvents round-trip, JSON Patch) · `tests/stateful` (Kybernesis termination) · `tests/integration` (journal+outbox, recovery matrix, API) · `tests/journeys` (Playwright, autonomy smoke) · `tests/adversarial` (injection, path escape, policy bypass, T10-style refusals) · `tests/sandbox` (isolation conformance) · `tests/accessibility` (axe) · `tests/formal` (TLA+) · **`tests/architecture`** (layout, import rules, classification, no-LLM-in-deterministic-kinds) · **`tests/policy`** (Rego differential fixtures) · **`tests/conformance`** (Sema-without-LLM, workflow engine, Harmonia rules, sandbox). Markers: `valkey`, `postgres`, `llm`, `gpu`, `opa`, `bwrap`, `hermes`, `openhands`, `slow`.

### 4.7 PR series (one PR per stage; merge order is the stage order)

`feat/tektos-autonomous-runtime` (this plan, PR #1) → `feat/arch-15-0-freeze` → `feat/arch-15-1-containment` → `feat/arch-15-2-packaging-ci` → `feat/arch-15-3-layout-step-a` → `feat/arch-15-4-koinon-contracts` → `feat/arch-15-5-mneme` → `feat/arch-15-6-workflow-kybernesis-sema` → `feat/arch-15-7-asphaleia-telos-isolation` → `feat/arch-15-8-mesiteia` → `feat/arch-15-9-poros-noesis` → `feat/arch-15-10-epimeleia-hermes` → `feat/arch-15-11-intelligence-plugins` → `feat/arch-15-12-tekton-euthyna` → `feat/arch-15-14-deploy` → `feat/arch-15-15-closure`. `feat/arch-15-13-workbench-client` runs in parallel from 15.8 (split into per-surface PRs); the OPA and hermes units may be installed on Colossus as soon as 15.7/15.10 land. Nothing else overlaps.

### 4.8 Kill switches and rollback summary

| Switch | Effect |
|---|---|
| `KOSMOS_OPERATOR_MODE=observer` | all dangerous surfaces 403 |
| `KOSMOS_TEKTON_AUTONOMY=off` (until 15.15) | legacy one-shot behavior on legacy entrypoints |
| `KOSMOS_AUTONOMY_TIER_MAX=A0` | observe-only; no writes, no tools |
| `KOSMOS_SANDBOX_TIER=process` | no bwrap |
| `KOSMOS_MAX_CONCURRENT_WORKFLOWS=0` | Kybernesis idle; workflows stay `READY` |
| `KOSMOS_CODING_WORKER=tektos-native` | OpenHands off |
| `systemctl --user stop hermes-gateway` | `RunAgent` steps fail `transient`; workflows block; nothing else degrades |
| `systemctl stop kosmos-opa` | fail-closed: every consequential action denied |
| Sema global containment (`POST /api/v1/operations/contain`, operator) | `Control=CONTAINED` everywhere; tools/models/artifact writes blocked until released by a witnessed decision |
| `git worktree remove --force data/worktrees/<id>` | discard a workflow's work (branch survives) |

### 4.9 Program Definition of Done (each point needs linked evidence in the closure PR)

1. No route or socket can run a command without operator token + Origin check + governed sandbox; bandit HIGH = 0. (15.1)
2. Wheel contains every package; `pytest` (no args) collects the whole suite; CI runs it all and fails when anything fails; three consecutive green `main` runs. (15.2)
3. Code lives in the report layout (`koinon/`, `plugins/<11>`, `extensions/`, `policies/`, `workflows/`, `apps/`, `tests/`); canonical names only; no shims remain. (15.3, 15.15)
4. Every component carries a `ComponentKind`; architecture tests enforce import rules, the naming rule, and no LLM calls inside deterministic kinds. (15.4)
5. PostgreSQL append-only, hash-chained journal with outbox; projection rebuild byte-identical; CloudEvents for every event; artifact service with immutable accepted versions and provenance. (15.5)
6. `OperationsController.regulate()` is the only driver; termination proven by stateful tests; Harmonia never prioritizes/approves; Sema works without an LLM (conformance test). (15.6)
7. OPA/Rego PDP consulted before every consequential action; grants/tokens/A0–A4 enforced; protected paths + Integrity Tripwire; the Telos authority chain implemented; decisions journaled with bundle digest. (15.7)
8. Workflows run in worktrees; tool processes argv-only, process-grouped, rlimited, network-denied by default, `bwrap` in production; sandbox conformance green. (15.7, 15.14)
9. `/api/v1` with error envelope, Schemathesis clean, AG-UI SSE with resume, health split; inference gateway is the only model path for agents/workers; Kosmos MCP server scoped by tokens; A2A behind a flag. (15.8)
10. Noesis registry/routing/tool protocol/fallbacks over llamacpp/ollama/vllm; Poros recommends only. (15.9)
11. Hermes runs through `AgentRuntimePort` with capability-scoped tokens, journaled events, termination and recovery proven. (15.10)
12. Zetesis/Gnosis/Synedrion/Agora as advisory plugins; `/api/gnosis` handlers out of `app.py`; citation verification gate. (15.11)
13. ≥ 7/10 corpus tasks accepted at E3 on Colossus with OpenHands + a real local model; the trap task refuses; Euthyna clean-room E3/E4; release/rollback/incidents; I-3 test. (15.12)
14. Fault matrix, agent-level recovery drill, backup/restore drill pass. (15.6, 15.12, 15.14)
15. Workbench client (web at `/workbench/` + Tauri 2 desktop) passes journeys and accessibility; parity sign-off journaled. (15.13, 15.15)
16. Colossus deployment reproducible from the runbook; secrets outside the tree; sandboxes cannot reach model ports; legacy shell/registry/façades removed; mypy 0; the 16 invariants each have a passing test or policy; docs and glossary truthful. (15.14, 15.15)

---

## Appendix A — Hermes start prompt and per-session brief

### A.1 Start prompt (paste into `hermes chat` at the beginning of the program)

```
You are executing the Kosmos architecture conformity program in /home/rmholston/dev/kosmos-lms.
Read, in order: SESSION_HANDOFF.md, KNOWN_ISSUES.md, AGENTS.md, docs/GLOSSARY.md,
docs/implementation/TEKTOS_HERMES_IMPLEMENTATION_PLAN.md (§0 fully, §2.2 nomenclature; then the stage named in SESSION_HANDOFF).
Rules: follow §0.1 exactly; the Architecture Report outranks the Workbench spec (§0.3) — use only canonical names
(Koinon, Kybernesis, Harmonia, Sema, Telos, Euthyna, Pronoia, Mneme, Aisthesis, Syndesmos, Mesiteia, Tekton, Asphaleia,
Noesis, Epimeleia, Poros, Zetesis, Gnosis, Synedrion, Agora, Axiomeon, Holon); classify every new class with a
ComponentKind; vendor before hand-build and log ports in PORTING_LEDGER.md before the first commit; ADR before structural
change (next number: check docs/adrs/README.md); append BUILD_LOG.md after every completed step; grep DEBUG_LOG.md before
diagnosing any bug; overwrite SESSION_HANDOFF.md at session end. Never modify /home/rmholston/dev/tektos-donor-8274f60.
Activate the venv first: source /home/rmholston/dev/kosmos-lms/.venv/bin/activate (confirm with find if missing); never
install Kosmos packages into the Hermes venv. OpenHands is the primary coding worker and Tektos-native the fallback; Hermes
is reached only through its API server on 127.0.0.1:8642 under capability tokens; no agent holds authority.
Work on the stage branch (§0.6), keep commits small, run `pytest -q` and `make ci-local` before pushing, open a PR with the
exit-gate evidence, and stop at any §0.7 stop condition. Do not ask for decisions already made in §0.3.
Current stage: <fill from SESSION_HANDOFF.md>. Begin with the first unchecked step of that stage.
```

### A.2 Per-session brief template (Hermes writes this into SESSION_HANDOFF.md at session end)

```
# Kosmos Session Handoff — YYYY-MM-DD HH:MM EDT
## Current build-sequencing position
- Stage / phase: Stage 15.<n> — <title> (report Phase <p>; step <k> of <m>)
- Plugin / kernel component: <e.g. koinon.kernel.kybernesis>
- Port(s) in progress: <e.g. WorkflowPort>
## Completed this session
- <BUILD_LOG entry timestamps + one line each>
## Remaining before current Definition of Done
- <unchecked steps; exit-gate items still red>
## Open questions / awaiting user answer
- none | <question, with the §0.7 stop condition number>
## Exact next action
- <one command or one sentence>
```

## Appendix B — ADR queue

Template (skill `kosmos-adr-authoring`; the repository's newest ADRs also carry `**Date:**` — include it):

```
# ADR-### — <Human Title>

**Status:** Proposed | Ratified | Amended | Superseded by ADR-###
**Date:** YYYY-MM-DD
**Lock-in phase:** Stage 15.<n>
**Supersedes / Amends:** <ADR-### or —>

## Context
## Decision
## Rationale (≥ 2 alternatives considered and why rejected)
## Consequences (files, procedures, PORTING_LEDGER, tests, downstream ADRs)
## Lock-in phase
## References (spec sections, this plan §, other ADRs, ledger entries)
```

| ADR | Title | Stage | Amends / supersedes | Decision (one paragraph) |
|---|---|---|---|---|
| ADR-147 | Architecture program charter, document precedence, canonical nomenclature | 15.0 | amends ADR-145 | Absorption program closed; the Architecture Report (`docs/Kosmos-LMS-Architecture-Report-v1.md`) is rank 1 and the Workbench spec rank 2 for target architecture; §0.2 invariants and §0.3 conflict resolutions are normative; canonical names and the renames (Tektos→Tekton, praxis→Telos/Kybernesis split, phrouros→Sema detectors) are decided; Build-Spec v26 not bumped; Stage 15 addendum added to Build-Sequence v26. |
| ADR-148 | Kernel exposure containment | 15.1 | amends ADR-082, ADR-093, ADR-141 | Operator mode + bearer token + WS Origin/auth-frame; single tool path through `TektosToolRegistry`→`TektosSandboxAdapter`; `SandboxPort` booted; donor `SandboxProvider` confined (no shell, no sudo, `data/workspaces`). |
| ADR-149 | Runtime profiles, in-memory event bus, CI as release gate | 15.2 | amends ADR-063 | `test|local|production` profiles with documented fallbacks; `InMemoryEventBusAdapter`; single pytest scope; CI summary fails on any failure; pinned dev tools; Dependabot/CodeQL. |
| ADR-150 | Repository layout: `koinon` package, subsystem plugins, extension adapters, two-step migration | 15.3 | amends Build-Spec v26 §3 layout (Stage 0.1; no prior layout ADR) | Mechanical Step A now (placement table §2.16); semantic Step B as packages are touched; transitional `koinon.adapters`; `sys.modules` aliases instead of package shims; isolation script updated. |
| ADR-151 | Koinon contracts: taxonomy registry, plugin manifests and trust states, typed commands/events, local Praxis helpers | 15.4 | — | `ComponentKind` + `@component`; naming rule; `PluginManifest`/`ExtensionManifest` with `trust_state`; generated event schemas; `praxis_local` base classes. |
| ADR-152 | Mneme event journal on PostgreSQL with transactional outbox | 15.5 | amends ADR-102 | `JournalPort`; `mn_*` schema in a second Alembic env; append-only trigger + hash chain; outbox → `EventBusPort`; SQLite adapter test/portable only; zero-trust provenance/confidence on every event. |
| ADR-153 | CloudEvents 1.0 envelope and `io.kosmos.<subsystem>.*` grammar | 15.5 | amends ADR-023, ADR-086 | Backward-compatible `EventEnvelope` extension; `to_cloudevent()`; lowercase extension attributes; schemas validated in CI. |
| ADR-154 | Artifact service and provenance service | 15.5 | promotes ADR-096 helper | `ArtifactStorePort` over `BlobStore`; promotion stages; accepted/released immutable; provenance edges; signatures via the Telos key. |
| ADR-155 | Workflow engine, Kybernesis controllers, Harmonia, Sema without LLM, Euthyna ledger | 15.6 | supersedes ADR-104's driver role; amends ADR-108 | `WorkflowPort` local durable adapter; `OperationsController.regulate()` single driver; Harmonia coordination-only; ten deterministic Sema components + thresholds; audit ledger; façades for legacy entrypoints. |
| ADR-156 | Asphaleia and Telos: PolicyPort (OPA/Rego), grants and tokens, A0–A4, authority chain, protected paths, secrets broker | 15.7 | amends ADR-033 | OPA v1.21.0 sidecar (fail-closed) + in-process mirror (differential-tested); `policies/` tree; capability tokens per run; Telos workflows; Integrity Tripwire; decisions journaled with bundle digest. |
| ADR-157 | Isolation ladder | 15.7 | amends ADR-082, ADR-093 | Worktree per workflow; argv-only process groups with rlimits/env allowlist/netns; `bwrap` opt-in then production default; Docker only for OpenHands untrusted repos; microVM deferred. |
| ADR-158 | Mesiteia: API v1, error envelope, health, AG-UI SSE, inference gateway, MCP server, A2A | 15.8 | amends ADR-141 (new surface), ADR-095/098 | Versioned routers in `koinon.mesiteia`; AG-UI mapping with `Last-Event-ID`; uniform errors; `/health/{live,ready,startup,degraded}`; `/v1/chat/completions` gateway under capability tokens; Kosmos MCP server; `a2a-sdk` transport behind a flag. |
| ADR-159 | Noesis model registry/routing and `LLMPort` tool-calling protocol; Poros recommendation-only | 15.9 | amends ADR-022 | `tools/tool_choice/response_format/parallel_tool_calls`, `chat_stream`, `AssistantTurn` normalizer tolerant of both `arguments` encodings; `config/models.yaml` registry with the OpenHands-Ext topology; fallbacks typed; Poros emits recommendations only. |
| ADR-160 | Epimeleia: `AgentRuntimePort`, Hermes API-server adapter, agent manifests, capability-scoped runs | 15.10 | — | Hermes reached via `hermes gateway` HTTP+SSE on 127.0.0.1:8642; per-run tokens; restricted `kosmos` profile; termination/recovery; no ambient credentials. |
| ADR-161 | Zetesis/Gnosis/Synedrion/Agora scopes and donor name flips | 15.11 | amends ADR-097 | Rigpa-LMS gnosis(research)→Zetesis, knowsys→Gnosis, magi→Synedrion patterns; advisory-only outputs; `CitationVerificationGate`; `/api/gnosis` handlers move to the plugin. |
| ADR-162 | Tekton coding workers (OpenHands primary, Tektos-native fallback), Euthyna clean room, gate chain, acceptance/promotion/release/rollback | 15.12 | amends ADR-104/105/106 | `CodingWorkerPort`; OpenHands SDK in a sandboxed worker process via the inference gateway + Kosmos MCP; fallback only on startup failure; non-bypassable chain; E3/E4 clean room; `kosmos.release`; Docker decision. |
| ADR-163 | Workbench client (React/Vite + Tauri 2) | 15.13 | amends ADR-089, ADR-091 | `apps/workbench-ui` + `apps/desktop`; subsystem surfaces; kernel serves `/workbench/`; parity checklist retirement path. |
| ADR-164 | Colossus deployment topology | 15.14 | amends ADR-102 deployment notes | Unit files, `/etc/kosmos/kernel.env`, hardening, OPA + hermes gateway units, exclusive GPU units, sandbox network containment, backup timer, port map. |
| ADR-165 | Legacy retirement | 15.15 | supersedes ADR-141 aliases, ADR-104 façade | Delete Next.js shell, donor registry/provider, façades, legacy routes, `koinon.adapters`, shims; `koinon.mesiteia.api.app` entrypoint. |
| ADR-166 | Program closure and Stage 16 charter | 15.15 | — | DoD evidence; Phase 8 scope (Axiomeon, Holon, Pronoia, Telos amendment automation, controlled self-improvement, homeostasis, Temporal, microVM). |

## Appendix C — Mapping tables

### C.1 Architecture Report roadmap phases → Stage 15

| Report phase | Stage(s) | Notes |
|---|---|---|
| — (freeze/charter) | 15.0 | precedence, nomenclature, truth-telling |
| Phase 2 (P0 subset pulled forward) | 15.1 | user decision 7: containment first |
| Phase 1 hygiene | 15.2 | packaging, profiles, CI |
| Phase 1 — Koinon core | 15.3, 15.4, 15.5, 15.6 | layout, contracts/taxonomy, Mneme, workflow engine + Kybernesis/Harmonia/Sema/Euthyna ledger |
| Phase 2 — Asphaleia | 15.7 | + Telos authority chain + isolation |
| Phase 3 — Syndesmos & Mesiteia | 15.8 | API v1, gateway, MCP server, A2A |
| Phase 4 — Poros & Noesis | 15.9 | |
| Phase 5 — Epimeleia | 15.10 | Hermes API server |
| Phase 6 — Zetesis, Gnosis, Synedrion, Agora | 15.11 | |
| Phase 7 — Tekton & Euthyna | 15.12 | OpenHands primary |
| — (client) | 15.13 | parallel from 15.8 |
| — (deployment) | 15.14 | |
| — (closure) | 15.15 | |
| Phase 8 — Axiomeon, Holon, Pronoia, Telos automation, self-improvement | Stage 16 | outline only |

### C.2 Plan v1.0 stages → v2.0 stages

| v1.0 | v2.0 | Change |
|---|---|---|
| 15.0 Freeze | 15.0 | + nomenclature, glossary, report copy |
| 15.1 Containment | 15.1 | unchanged mechanics; classified as Asphaleia-lite |
| 15.2 Packaging/CI | 15.2 | unchanged; `packages.find` retargeted in 15.3 |
| 15.3 Layout `src/kosmos` | 15.3 | **report layout** (`koinon/`, `plugins/<11>`, `extensions/`, `policies/`) + renames |
| — | 15.4 | **new**: contracts, taxonomy, manifests, quarantine, local Praxis |
| 15.4 Model/tool protocol | 15.9 | moved to Phase 4 (Noesis) |
| 15.5 Domain + journal | 15.5 | + artifact/provenance services (from v1 15.9) |
| 15.6 Isolation | 15.7 | merged into Asphaleia |
| 15.7 Policy | 15.7 | + Telos authority chain, tokens, protected paths, secrets broker |
| 15.8 Regulator/workflow/worker | 15.6 (engine, Kybernesis, Harmonia, Sema, Euthyna ledger) + 15.12 (worker) | worker becomes the Tektos-native fallback |
| 15.9 Claims/evidence/Elechos/artifacts | 15.5 (artifacts) + 15.12 (Euthyna) | Elechos → Euthyna |
| 15.10 API v1 | 15.8 | + inference gateway, MCP server, A2A, discovery |
| 15.11 Real-model slice | 15.12 | OpenHands primary |
| 15.12 Recovery | 15.6 (+ agent-level drill in 15.12) | |
| 15.13 Client | 15.13 | subsystem surfaces |
| 15.14 Release/assurance | 15.12 | inside Tekton & Euthyna |
| 15.15 Deploy | 15.14 | + hermes gateway, vLLM, network containment |
| 15.16 Closure | 15.15 | |
| — | 15.10, 15.11 | **new**: Epimeleia/Hermes; Zetesis/Gnosis/Synedrion/Agora |

### C.3 Nomenclature crosswalk (replaced → canonical; the left column must not appear in new code)

| Replaced (Workbench spec / v1.0 / donors) | Canonical (Architecture Report) |
|---|---|
| Nomos | Telos (policy/constitution) |
| Kratos, "regulator", `regulate(mission_id)` | Kybernesis, `OperationsController.regulate(workflow_id)` |
| Elechos, "assurance" | Euthyna |
| Syndesmos (spec sense: resources/leases) | Poros (telemetry/recommendations) + Harmonia (leases) + Kybernesis `ResourceController` (allocation); "Syndesmos" now means the Koinon integration layer |
| Energeia (execution) | Tekton (software work) / Epimeleia (agent runs) / Koinon tools |
| Algedon, "essential variables" | Sema, Sema thresholds |
| Phronesis (planning/knowledge) | Pronoia (foresight) + Gnosis (knowledge) + Zetesis (research) |
| Mission (aggregate) | Workflow (`definition_id=mission`) |
| `wb_*` tables | `mn_*` tables |
| `src/kosmos/...` | `koinon/src/koinon/...`, `plugins/...`, `extensions/...` |
| `plugins/tektos`, `KOSMOS_TEKTOS_AUTONOMY` | `plugins/tekton`, `KOSMOS_TEKTON_AUTONOMY` |
| `plugins/praxis` | `koinon/policy/constitution` + `koinon/kernel/kybernesis/apex` |
| `plugins/phrouros` | `koinon/kernel/sema/detectors/phrouros` |
| `governance/constitution` | `policies/constitution` |
| Rigpa-LMS `plugins/gnosis` (research) | Zetesis |
| Rigpa-LMS `plugins/knowsys` | Gnosis |
| Rigpa-LMS `plugins/magi` | Synedrion |
| `io.kosmos.mission.*`, `io.kosmos.regulator.*`, `io.kosmos.algedonic.*` | `io.kosmos.workflow.*`, `io.kosmos.kybernesis.*`, `io.kosmos.sema.*` |

### C.4 Aggregates → modules / `mn_*` tables / events

| Aggregate | Module | Table | Key events |
|---|---|---|---|
| Project, Charter | `koinon.kernel.kybernesis.projections` | `mn_projects`, `mn_charters` | `telos.charter.updated` |
| Workflow, WorkflowState | `koinon.workflows`, `koinon.kernel.kybernesis` | `mn_workflows`, `mn_workflow_state` | `workflow.*`, `kybernesis.step.*` |
| Plan, Task | `plugins.tekton.components` (software), `koinon.contracts.workflows` | `mn_plans`, `mn_tasks` | `plan.*`, `task.*` |
| Claim, Evidence | `koinon.contracts.artifacts`, `koinon.kernel.euthyna` | `mn_claims`, `mn_evidence`, `mn_verification_runs` | `claim.*`, `evidence.recorded`, `euthyna.*` |
| Artifact, Provenance | `koinon.artifacts` | `mn_artifacts`, `mn_provenance` | `mneme.artifact.*`, `mneme.provenance.linked` |
| Decision | `koinon.kernel.kybernesis.apex` | `mn_decisions` | `decision.*` |
| CapabilityGrant, CapabilityToken | `plugins.asphaleia.components` | `mn_capability_grants`, `mn_capability_tokens` | `asphaleia.*` |
| Lease, Commitment | `koinon.kernel.harmonia`, `koinon.kernel.kybernesis` | `mn_leases`, `mn_commitments` | `kybernesis.lease.*`, `kybernesis.commitment.*` |
| Checkpoint | `koinon.capabilities.isolation.worktrees` | `mn_checkpoints` | `checkpoint.*`, `tekton.checkpoint.created` |
| Threshold (essential variable) | `koinon.kernel.sema.thresholds` | `mn_essential_variables` | `sema.threshold.*`, `sema.raised` |
| WorkflowDefinition | `workflows/*.yaml`, `koinon.contracts.workflows` | `mn_workflow_definitions` | — |
| AgentManifest, AgentSession | `plugins.epimeleia.components` | `mn_agent_manifests`, `mn_agent_sessions` | `epimeleia.*` |
| ModelAssignment | `plugins.noesis.components` | `mn_model_assignments` | `noesis.model.*` |
| Release, Incident | `koinon.kernel.kybernesis` | `mn_releases`, `mn_incidents` | `kybernesis.release.*`, `kybernesis.incident.*` |
| KnowledgeAssertion | `plugins.gnosis.components` | `mn_knowledge_assertions` | `gnosis.assertion.*` |
| ConstitutionVersion, Exception | `koinon.policy.constitution`, `koinon.kernel.telos` | `mn_constitution_versions` | `telos.constitution.*`, `telos.exception.*` |
| Quarantine entry | `koinon.kernel.registry` | `mn_quarantine` | `asphaleia.quarantine.*` |
| Ledgers | `koinon.kernel.sema`, `koinon.kernel.euthyna` | `mn_sema_ledger`, `mn_audit_ledger` | — |

### C.5 Donor crosswalk

| Donor | Kosmos destination | Port type |
|---|---|---|
| tektos-ultima `sdk.py::_stream_llm` accumulator | `koinon.kernel.model_protocol` (15.9) | pattern |
| Tektos turn loop / executor / orchestrator (already absorbed) | `TektosNativeCodingWorker` fallback + façades (15.6/15.12) | in-repo |
| Rigpa-LMS `plugins/gnosis` (LangGraph research pipeline) | Zetesis (name flip; existing `plugins/zetesis/research`) | pattern |
| Rigpa-LMS `plugins/knowsys` (notes/vault/Qdrant retrieval) | Gnosis `RetrievalService` (15.11) | pattern |
| Rigpa-LMS `plugins/magi` (council fan-out, resolution strategies, injection isolation) | Synedrion (15.11) | pattern |
| Forge-OH / OpenHands-Ext v1 (BFF over OpenHands; topology; StuckDetector patch) | `OpenHandsAdapter` design + `config/models.yaml` defaults (15.9/15.12) | pattern / config |
| OpenHands SDK (`openhands-sdk`, `openhands-tools`) | `extensions/adapters/openhands` (15.12) | dependency (MIT) |
| hermes-agent API server | `extensions/adapters/hermes` (15.10) | external runtime |
| a2a-sdk | `koinon.mesiteia.a2a` (15.8) | dependency (Apache-2.0) |
| OPA, bubblewrap, gitleaks, syft, TLC | external tools (15.7, 15.15) | binaries |

## Appendix D — Command cheat-sheet

```bash
# session start
cd /home/rmholston/dev/kosmos-lms && source .venv/bin/activate && cat SESSION_HANDOFF.md
# local CI equivalent (Stage 15.2+)
make ci-local            # ruff check . && ruff format --check . && mypy ratchet && bandit -lll && pytest -q && wheel smoke
# targeted suites
pytest tests/architecture -q ; pytest tests/conformance -q ; pytest -m "not llm and not gpu" -q ; pytest -m postgres -q
# policy
opa test policies/ -v && opa check --strict policies/ && curl -s 127.0.0.1:8181/health
# journal (Stage 15.5+)
alembic -c koinon/src/koinon/mneme/journal/postgres/alembic.ini upgrade head
python -m koinon.mneme.verify_journal && python -m koinon.mneme.rebuild_projections --dry-run
# models (Stage 15.9+)
curl -s 127.0.0.1:8090/props | jq '{model: .model_path, tool_template: (.chat_template|test("tool"))}'
python scripts/llm_toolcall_probe.py --role coder
curl -s -H "Authorization: Bearer $KOSMOS_OPERATOR_TOKEN" 127.0.0.1:8000/api/v1/models/health | jq
# hermes (Stage 15.10+)
systemctl --user status hermes-gateway ; curl -s -H "Authorization: Bearer $HERMES_KEY" 127.0.0.1:8642/health
python scripts/agent_probe.py --manifest research_planning_agent --task "outline a plan"
# workflows (operator token in $KOSMOS_OPERATOR_TOKEN)
curl -s -X POST 127.0.0.1:8000/api/v1/workflows -H "Authorization: Bearer $KOSMOS_OPERATOR_TOKEN" \
  -H 'content-type: application/json' -d '{"definition_id":"tekton_mission","brief":"Fix the failing test in tests/test_math.py","autonomy":"A2"}'
curl -N -H 'Accept: text/event-stream' 127.0.0.1:8000/api/v1/workflows/<id>/stream
# tekton (Stage 15.12+)
python scripts/autonomy_bench.py --worker openhands --tasks all --runs 3
# services
sudo systemctl status kosmos-kernel kosmos-opa ; journalctl -u kosmos-kernel -n 100 --no-pager
# github
gh pr create --repo rmholston420/kosmos-lms --base main --fill ; gh run list --limit 5 ; gh run view --log-failed
```

## Appendix E — Baseline reproduction log (2026-09-28, sandbox Python 3.12.13)

E.1 **Inventory**: `git ls-files | wc -l` → 1043; `*.py` → 660; packages → 120 (+2 test pkgs); routes → 185; `wc -l kernel/app.py` → 10,180; ADR files → 148 (max ADR-146); `kernel/app.py` "gnosis" mentions → 50; "ekklesia" → 0; `pyproject name="kosmos"`, `requires-python>=3.12`.

E.2 **Ruff 0.16.9** (repo `pyproject.toml` config): whole repo `ruff check .` → 1,114 findings (753 fixable; top: UP017 255, I001 173, F401 123, B904 …); CI scope `ports kernel tests scripts` → 369; `ruff format --check`: 403 files (repo) / 118 (CI scope).

E.3 **mypy 2.3.1** `mypy ports kernel` → 86 errors in 28 files (top: `kernel/app.py`, `kernel/voice.py`, `kernel/mcp_client.py`, `ports/trace_feed.py`).

E.4 **Wheel** (`python -m build --wheel`): 52 packages present; missing 68 including `kernel`, `kernel.learning`, `adapters.relational_memory.*`, `adapters.sandbox.*`, `adapters.session.*`, `adapters.immune.*`, `adapters.loop_safety.*`, `adapters.thermal.*`, `plugins.tektos.{runtime,tools,executor,planner,decomposer,manager,orchestrator,reflection,experience,synthesis,self_repair,self_improvement,skills,vision,voice,openspec,memory_persistence,dreamtime,schema_evolution,repomap,rag,learning,eval,…}`, `plugins.zetesis.*`, `governance.*`.

E.5 **Undeclared imports** (AST scan of non-test modules vs `pyproject` deps): `aiohttp`, `PIL`, `pytesseract`, `edge_tts`, `numpy`, `pydub`, `faster_whisper`, `mcp`, `open_deep_research`, `openai`, `openhands_ext`.

E.6 **Bandit 1.9.4** `-r ports adapters kernel plugins -x tests,vendor`: 209 findings — HIGH 3 (B602 ×3), MEDIUM 60 (B608 ×42, B108, B310, B104 …), LOW 146.

E.7 **pip-audit**: `diskcache 5.6.3` PYSEC-2026-2447. **npm audit** (`ui/`): next 16.2.11 critical (fix 16.3.6), postcss high, sharp high. **tsc --noEmit**: 1 error `ui/tests/03-tektos-plan-workflow.spec.ts(20,61)`.

E.8 **pytest 9.1.1**: default testpaths → 1,811 collected / 1,788 passed / 2 failed / 21 skipped (≈ 4 min on 2 vCPU); `tests/` → 1 collection error; with `--ignore` → 878 collected / 850 passed / 25 failed / 3 skipped (17 Valkey-refused, 8 unmarked live-service).

E.9 **GitHub Actions**: `gh run list --limit 12` → 12 × failure (2026-09-26/27); at `7e7b1e3` jobs: python-lint ✗, python-typecheck ✗, python-tests skipped, port-contract-tests ✓, plugin-isolation ✓, frontend-build ✓, frontend-lint ✗ (no `lint` script), frontend-e2e ✗, summary ✓.

E.10 **External versions checked 2026-09-28 (v1.0)**: OPA v1.21.0 (released 2026-09-24, [GitHub releases](https://github.com/open-policy-agent/opa/releases)); PostgreSQL 18 current major ([release notes](https://www.postgresql.org/docs/release/)); Tauri 2 Linux prerequisites ([v2.tauri.app](https://v2.tauri.app/start/prerequisites/)); llama.cpp function calling requires `--jinja`, `parallel_tool_calls` opt-in ([docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)); llama.cpp `tool_calls[].function.arguments` object-vs-string regression fixed in b8236 ([issue #20198](https://github.com/ggml-org/llama.cpp/issues/20198)); AG-UI event types ([docs.ag-ui.com](https://docs.ag-ui.com/concepts/architecture)); CloudEvents JSON format 1.0.2 ([spec](https://github.com/cloudevents/spec/blob/main/cloudevents/formats/json-format.md)); Next.js fix version 16.3.6 (`npm audit`).

E.11 **External surfaces checked 2026-09-28 (v2.0)**: hermes-agent API server — enabled via `~/.hermes/.env` (`API_SERVER_ENABLED=true`, `API_SERVER_KEY`), started with `hermes gateway`, default `127.0.0.1:8642`, bearer auth, endpoints `/v1/chat/completions`, `/v1/responses`, `/v1/models`, `/v1/capabilities`, `/health`, `/health/detailed`, `POST /v1/runs`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events` (SSE), `POST /v1/runs/{id}/stop`, `POST /v1/runs/{id}/approval`, `/api/jobs`; `gateway.api_server.max_concurrent_runs` ([API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/), [programmatic integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration)). OpenHands software-agent-sdk — `pip install -U openhands-sdk openhands-tools` (same version), optional `openhands-workspace`/`openhands-agent-server`; latest release v1.49.6 (2026-09-25); Python ≥ 3.12; `LLM(model, api_key, base_url)`, `Agent(llm, tools=[Tool(name=TerminalTool.name), FileEditorTool, TaskTrackerTool])`, `Conversation(agent=agent, workspace=cwd)`, `send_message`, `run()` ([getting started](https://docs.openhands.dev/sdk/getting-started), [hello world](https://docs.openhands.dev/sdk/guides/hello-world), [repository](https://github.com/OpenHands/software-agent-sdk)). A2A — PyPI `a2a-sdk` v1.1.5 (2026-09-21), Apache-2.0, Python ≥ 3.10, extras `[http-server]`, `[grpc]`; spec 1.0 transports JSON-RPC / HTTP+JSON / gRPC ([repository](https://github.com/a2aproject/a2a-python)).

## Appendix F — Change log

- **v2.0 (2026-09-28 10:35 EDT)** — Brought into conformity with the Kosmos-LMS Architecture Report v1 (user decisions 5–8): the report is rank 1; canonical VSM/Koinon nomenclature and the eleven subsystems replace the Workbench names (C.3); repository layout per the report (`koinon/`, `plugins/<11>`, `extensions/`, `policies/`, `workflows/`, `apps/`, `tests/{architecture,integration,policy,conformance}`); component taxonomy registry and architecture tests; sixteen invariants each with an enforcing stage; stages reordered to the report's phases with containment first (C.1/C.2); new stages 15.4 (contracts/taxonomy/manifests), 15.10 (Epimeleia with the Hermes API-server adapter), 15.11 (Zetesis/Gnosis/Synedrion/Agora); OpenHands SDK becomes the primary Coding Worker with the Tektos-native loop as fallback (15.12); inference gateway, Kosmos MCP server, and A2A transport added to Mesiteia (15.8); Poros/Noesis split (15.9); Telos authority chain, capability tokens, protected paths, Integrity Tripwire, secrets broker (15.7); `mn_*` tables; `io.kosmos.<subsystem>.*` events; ADR queue renumbered ADR-147…ADR-166; DoD extended to 16 points.
- **v1.0 (2026-09-28 09:40 EDT)** — Initial plan: audit findings B-01…B-24, Workbench-authoritative target architecture, Stage 15.0–15.16.

---

*End of plan. Next action for Hermes: Stage 15.0, step 1.*
