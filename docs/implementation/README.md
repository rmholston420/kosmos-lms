# docs/implementation — Architecture program execution documents

| File | Purpose |
|---|---|
| `TEKTOS_HERMES_IMPLEMENTATION_PLAN.md` | **The execution contract** for the Kosmos architecture conformity & migration program (Stage 15.0 → 15.15, Stage 16 outline), written for the local Hermes Agent. Version 2.0 (2026-09-28) — conformed to the Kosmos-LMS Architecture Report v1. Read §0 first (rules, sixteen invariants, precedence), §2.2 (canonical nomenclature), then the stage named in `SESSION_HANDOFF.md`. The file name keeps "Tektos" for continuity with PR #1; the subsystem is **Tekton** from v2.0 on. |
| `baseline/README.md` | Compact reproduction log of the audited baseline (`main@7e7b1e3`, 2026-09-28): test, lint, type, security, packaging numbers. |
| `sources/` | The eight source documents the plan reconciles (verbatim copies). Precedence (plan §0.3): 1 `kosmos-lms_architecture-v1.md` (Architecture Report) · 2 Unified Workbench Specification · 3 Hermes implementation plan · 4 the two audits · 5 Implementation Blueprint · 6 cybernetic architecture · 7 cybernetic GUI/UX. They may be removed from the repo once the plan is ratified; the plan is standalone. |

Authority: the **Kosmos-LMS Architecture Report** (`sources/kosmos-lms_architecture-v1.md`) is authoritative for target architecture; the Unified Workbench Specification supplies mechanisms where the report is silent (user decisions of 2026-09-28, 10:26 EDT; to be ratified as ADR-147 in Stage 15.0). Where the sources conflict, plan §0.3 is binding. Coding backend: OpenHands SDK primary, Tektos-native fallback (`CodingWorkerPort`, Stage 15.12). Agent runtime: hermes-agent through its API server on loopback (`AgentRuntimePort`, Stage 15.10).
