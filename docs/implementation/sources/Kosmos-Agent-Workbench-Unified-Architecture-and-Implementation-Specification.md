# Kosmos Agent Workbench

**Unified architecture, product, UX, safety, and implementation specification**  
**Integrated from the Agent Workbench GUI/UX specification and the Cybernetic Autonomous Coding System blueprint — September 2026**

## Executive decision

Build **Kosmos Agent Workbench** as a local-first, evidence-governed coding environment whose authoritative core is a deterministic cybernetic control kernel and whose user interface is an intent-to-evidence workbench. The product is neither a chatbot with tools nor seven LLM personas arranged around a Viable System Model (VSM); it is a modular monolith with isolated workers, explicit authority, durable execution, independent verification, reversible releases, and coordinated views over one event-derived state model.[^1][^2]

The integrated operating loop is:

> **Purpose → Intent → Context → Contract → Authorize → Plan → Execute → Observe → Verify → Review → Accept → Release → Learn**

The first production-worthy vertical slice must complete this narrower loop:

> **Charter → bounded mission → isolated change → exact-digest candidate → independent audit → product preview → user decision → reversible release**

The central design rule is: **models may propose and operate inside bounded cells, but deterministic services own authority, state transitions, policy enforcement, budgets, leases, release gates, containment, and user-visible truth.** Claims such as “fixed,” “safe,” “ready,” and “released” are computed projections over evidence, never declarations accepted from model prose.[^2][^1]

## Integration decisions

The source documents are strongly complementary: the GUI/UX document defines the complete human-facing control plane, while the cybernetic blueprint supplies the authoritative kernel, safety invariants, assurance model, and implementation order. The following decisions reconcile their few material differences without discarding either design’s capabilities.[^1][^2]

| Question | Unified decision | Rationale |
|---|---|---|
| Primary system concept | **Mission** governed by a **Project Charter** | Mission remains the main unit of work; Charter supplies purpose, authority, beneficiaries, boundaries, and constitutional invariants. |
| System architecture | **Modular monolith plus isolated worker processes** | Preserves rich UX and all operational functions without premature distributed-system complexity. |
| VSM implementation | **Logical kernel responsibilities, not one LLM per VSM function** | Nomos, Phronesis, Kratos, Elechos, Syndesmos, Energeia, and Algedon remain visible in architecture and policy, but are instantiated as deterministic services or bounded capabilities. |
| Desktop stack | **Tauri 2 + React/TypeScript primary client; Python domain core; optional PySide6/QML projection client later** | The expert workbench needs Monaco, xterm.js, browser previews, accessible workflow canvases, and web-native extension surfaces. A protocol-stable projection API preserves the QML option without duplicating domain logic. |
| Authoritative data | **PostgreSQL plus append-only event journal and transactional outbox** | Supports durable aggregates, replayable projections, row-level security, hybrid retrieval, and migration to multi-user mode. SQLite may support a reduced portable profile, but not replace the canonical production schema. |
| Workflow execution | **Workflow port with a local durable state-machine implementation first; Temporal-compatible adapter when persistence or scale justifies it** | Avoids an early infrastructure burden while preserving durable semantics, idempotency, signals, retries, and migration. |
| UI transport | **AG-UI-compatible semantic projection stream over local WebSocket/Unix socket bridge** | The client receives meaningfully projected state, never owns workflow truth, and can reconnect or support alternative clients. |
| Event envelope | **CloudEvents-compatible domain envelope** | Standardizes identity, type, source, time, causality, schema version, and trace correlation. |
| Telemetry | **OpenTelemetry for diagnosis only** | Domain events remain authoritative; workflow history explains durable execution; telemetry explains runtime performance and causality. |
| Knowledge model | **Relational/provenance core with graph projections on demand** | Preserves rich knowledge and architecture navigation while avoiding a universal graph database in the first release. |
| Model/tool protocols | **Internal ports first; ACP, MCP, A2A, and provider APIs as adapters** | Prevents external protocols from defining internal authority or state semantics. |
| Evidence | **Criterion matrix plus E0–E6 assurance ladder** | Combines usable acceptance-state UX with explicit independence, freshness, artifact identity, and environment scope. |
| Autonomy | **A0–A4 UX tiers compiled into capability grants and policy obligations** | Keeps autonomy understandable to users while enforcement remains outside the model. |
| Release | **Exact artifact digest, signed manifest, tested rollback, and post-release observation** | Extends “commit and learn” into a controlled operational lifecycle without weakening the coding workflow. |

## Product doctrine

### Product thesis

Kosmos is an **intent-to-evidence control plane** combining:

- An IDE for precise code work.
- A mission-control system for autonomous and background execution.
- A workflow engine for repeatable processes.
- A scientific notebook for claims and evidence.
- A governed knowledge system for architecture, decisions, memory, and provenance.
- A version-control client for parallel branches, comparison, acceptance, and recovery.
- A cybernetic cockpit for purpose, essential variables, foresight, containment, and release health.[^2][^1]

The organizing object is a versioned `Mission`, not a chat message. Chat, voice, screenshots, sketches, selections, and commands are input modes; the durable commitments are contracts, plans, capability grants, patches, claims, evidence, decisions, artifacts, and releases.

### Non-negotiable invariants

1. **Human authority governs purpose.** Models may draft a charter change, but cannot approve purpose, beneficiaries, constitutional policy, or authority expansion.
2. **Outcome precedes prompting.** Every mission begins with an observable desired state, boundaries, affected parties, and success evidence.
3. **Read before write.** Read-only orientation may begin immediately; broad or consequential mutation requires an inspectable plan or an explicit policy-authorized exception.
4. **Every action has scope.** Repository, revision, worktree, filesystem roots, tools, network, secrets, environment, model route, time, compute, and cost are explicit.
5. **Every mutation is reversible where technically possible.** Checkpoints precede first writes, migrations, dependency changes, bulk refactors, and releases.
6. **Claims require evidence.** Status is derived from fresh, relevant evidence tied to an exact artifact and environment.
7. **Execution cannot self-certify.** Implementer evidence is labeled non-independent; consequential readiness requires a separate assurance path.
8. **Unknown is a first-class state.** Missing, stale, conflicting, or inconclusive evidence cannot become green.
9. **Containment outranks completion.** Authority narrows when failures repeat, scope expands unexpectedly, essential variables breach limits, or side effects become unknown.
10. **Every consequential command is authenticated, authorized, scoped, idempotent, and attributable.**
11. **Every durable fact has provenance.** Source, scope, applicable revision, confidence, freshness, sensitivity, conflicts, and invalidation rules are retained.
12. **Autonomy is granular.** It is configured by action class, scope, consequence, risk, and duration—not by one global switch.
13. **Every run is sufficiently replayable to audit.** Mission, plan, policy, model, tool, commands, events, patches, artifacts, decisions, and hashes are preserved subject to privacy policy.
14. **Every interruption is resumable.** Focus, selected object, open diff, pending decision, execution checkpoint, and a source-linked return briefing are retained.
15. **Accessibility is architectural.** All graphs, visualizations, drag operations, and asynchronous state changes have keyboard and ordered-text equivalents.[^1][^2]

## Cybernetic responsibilities

VSM terms describe responsibilities in the control kernel; they are not user-facing agent characters and do not imply a dedicated model invocation.

| Responsibility | Kernel realization | Model use | User-facing projection |
|---|---|---|---|
| **Nomos** | Charter service, invariant registry, policy bundles, authority graph | Draft and explain only | Charter, boundaries, authority, policy changes |
| **Phronesis** | Environmental signals, forecasts, experiments, staleness and prediction-error tracking | Analysis permitted | Foresight, upcoming disturbances, hypotheses |
| **Kratos** | Scheduler, budgets, capability issuance, release gates | Recommendations only | Plan, resources, budgets, release readiness |
| **Elechos** | Independent checks, contradiction handling, evidence grading | Bounded grading where deterministic checks are impossible | Proof, uncertainty, freshness, contradictions |
| **Syndesmos** | Dependencies, leases, backpressure, conflict and oscillation detection | Rare | Workflow constraints, blockers, critical path |
| **Energeia** | Bounded mission workers and agent runtime | Primary model execution | Work performed, artifacts, deviations |
| **Algedon** | Threshold evaluation, kill paths, safe-state and recovery playbooks | No trigger or enforcement role | Critical incident, containment, recovery choices |

VSM recursion is latent by default. A nested control unit is created only when a sub-mission owns independent resources, has multiple concurrent workers, observes its own meaningful environment, or requires a separate acceptance/release decision.[^2]

## Reference architecture

```text
┌──────────────────────────── Desktop Workbench ──────────────────────────────┐
│ Tauri 2 + React/TypeScript                                                  │
│ Home · Missions · Projects · Workflows · Knowledge · Agents · Operations   │
│ Code · Preview · Product · Progress · Proof · Foresight · Charter · Expert │
│ Monaco · xterm.js · accessible DAG/outline/table · command palette          │
└───────────────────────────┬──────────────────────────────────────────────────┘
                            │ AG-UI-compatible semantic projections
                            │ commands over authenticated local IPC
┌───────────────────────────▼──────────────────────────────────────────────────┐
│ Python modular-monolith control kernel                                      │
│ Command API · Aggregate repository · Projector · Intent compiler            │
│ Charter/Nomos · Scheduler/Kratos · Coordination/Syndesmos                   │
│ Claims/Elechos · Foresight/Phronesis · Thresholds/Algedon                   │
│ Policy PDP/PEP · Workflow controller · Release controller · Memory promotion│
└─────────────┬────────────────┬────────────────────┬──────────────────────────┘
              │                │                    │
              ▼                ▼                    ▼
     Append-only events   PostgreSQL views   Content-addressed artifacts
     + transactional      + pgvector/FTS     + provenance/signatures/SBOM
     outbox
              │
┌─────────────▼────────────────────────────────────────────────────────────────┐
│ Isolated execution plane                                                    │
│ Mission supervisor · bounded workers · model gateway · MCP/ACP adapters     │
│ shell/browser/test/build tools · worktrees · leases · capability tokens     │
│ Bubblewrap → rootless OCI/gVisor → Firecracker tiers · controlled egress    │
└───────────────────────────┬──────────────────────────────────────────────────┘
                            ▼
┌──────────────────── Independent verification plane ─────────────────────────┐
│ Clean checkout · deterministic tests · scanners · accessibility probes      │
│ browser journeys · security probes · exact-digest checks · rollback drills  │
└───────────────────────────┬──────────────────────────────────────────────────┘
                            ▼
                 Release, observation, and containment
```

### Architectural boundaries

- **Client boundary:** renders projections and emits commands; it never mutates authoritative workflow state directly.
- **Command boundary:** validates schema, identity, expected version, idempotency key, and authority before dispatch.
- **Aggregate boundary:** enforces domain invariants and emits immutable events.
- **Policy boundary:** wraps every capability crossing, including shell, filesystem, network, Git, secrets, models, MCP, external services, databases, deployments, and delegation.
- **Worker boundary:** treats repository content, prompts, tool output, generated code, and artifacts as untrusted.
- **Assurance boundary:** verifies a clean, pinned candidate rather than trusting the mutable implementation workspace.
- **Release boundary:** promotes only the audited artifact digest and binds provenance, signatures, rollback, and sensors to that digest.

## Core domain model

### Durable aggregates

| Aggregate | Purpose | Required invariants |
|---|---|---|
| `Project` | System in focus | Explicit owner, boundary, repositories, environments, and one active charter version |
| `Charter` | Purpose and constitutional policy | Versioned; human-authorized; models cannot self-approve changes |
| `Mission` | Bounded outcome | Contract, scope, baseline, budget, authority, stop conditions, workflow, and disposition |
| `Plan` | Versioned executable task graph | Acyclic unless explicit loop node; typed dependencies; write-conflict validation; criteria coverage |
| `Task` | Atomic schedulable unit | Inputs, outputs, scopes, policy, timeout, retries, idempotency, evidence, rollback |
| `Claim` | Desired, inferred, or observed proposition | Statement, kind, impact, source, exact scope, freshness, and required evidence |
| `Evidence` | Immutable observation | Method, producer, independence, environment, artifact digest, raw result, normalized finding |
| `Artifact` | Code, patch, build, image, report, screenshot, trace, SBOM, or test result | Content digest, media type, provenance, sensitivity, retention, and signature state |
| `Decision` | Consequential choice | Alternatives, authority, rationale, affected scope, and supersession chain |
| `CapabilityGrant` | Temporary permission | Least privilege, audience binding, mission/worker binding, expiry, obligations, and revocation |
| `Checkpoint` | Recoverable mission snapshot | Code revision, worktree state, plan, context manifest, environment declaration, data-migration state |
| `EssentialVariable` | Condition necessary for product viability | Sensor, acceptable band, hysteresis, stale policy, breach response, and recovery target |
| `WorkflowDefinition` | Reusable typed process | Version, schema, fixtures, tests, policies, migration path, and readable text form |
| `KnowledgeAssertion` | Durable project knowledge | Provenance, scope, confidence, freshness, conflicts, sensitivity, and invalidation |
| `AgentProfile` | Versioned worker configuration | Purpose, model route, tools, memory, sandbox, limits, stop rules, eval history |
| `Release` | Promoted candidate | Candidate digest equals audited digest; manifest, signature, environment, rollback, and sensors |
| `Incident` | Viability or policy breach | Containment action, preserved evidence, impact, recovery state, and postmortem |

### Mission contract

A `MissionContract` contains:

- Goal, user story, audience, beneficiary, and motivation.
- Observable success outcome.
- In-scope and out-of-scope boundaries.
- Functional and nonfunctional requirements.
- Negative requirements and prohibited paths.
- Acceptance criteria, impact, required evidence grade, and verification methods.
- Assumptions, unresolved questions, risks, and decisions.
- Context attachments and source provenance.
- Repository, baseline commit, branch/worktree, environment, and deployment target.
- Autonomy tier, capability ceiling, models/tools, budget, deadlines, and stop conditions.
- Recovery and rollback expectations.
- Charter and policy references.

### Claims and evidence

The claim lifecycle is:

```text
PROPOSED → ACCEPTED_AS_REQUIREMENT → EVIDENCE_PENDING
         → SUPPORTED | CONTRADICTED | UNKNOWN | WAIVED
         → STALE when artifact, environment, dependency, policy, or time changes
```

Claim status is recomputed from evidence. It is not a mutable label. A claim can have simultaneous supporting and contradicting evidence; the system opens a conflict rather than averaging the contradiction into a misleading confidence score.[^2]

Every evidence item records:

- Observation and expected result.
- Check definition and reproduction command/workflow.
- Input fixtures, environment, tool versions, and policy version.
- Exact candidate artifact digest.
- Producer identity and independence dimensions.
- Start/end time, freshness rule, and expiry.
- Raw artifact references and normalized result.
- Claims supported or contradicted.
- Completeness, limitations, and applicable scope.

### Evidence ladder

| Grade | Evidence | Permitted interpretation |
|---|---|---|
| **E0** | Model assertion only | Hypothesis; never “proven” |
| **E1** | Static observation | Structure, style, inventory, inferred architecture |
| **E2** | Deterministic test in worker workspace | Local implementation behavior |
| **E3** | Clean-checkout reproduction | Build, install, package, and integration behavior |
| **E4** | Independent journey/security/accessibility probe against exact candidate | Candidate readiness |
| **E5** | Canary or production observation | Live-environment behavior |
| **E6** | Longitudinal observation | Reliability, cost, adoption, and maintenance claims |

Independence is recorded dimensionally: separate process, clean state, distinct credentials, distinct implementation path, different model family where judgment is unavoidable, and real environment observation. Multiple correlated model votes do not equal independent empirical evidence.[^2]

## State and execution

### Orthogonal state model

To preserve the detailed UX workflow and the kernel’s release lifecycle without conflating them, Kosmos uses four orthogonal state dimensions.

| Dimension | Values | Purpose |
|---|---|---|
| **Lifecycle** | `DRAFT`, `FRAMED`, `AUTHORIZED`, `EXECUTING`, `CANDIDATE_READY`, `AUDITING`, `READY_TO_TRY`, `ACCEPTED`, `RELEASED`, `OBSERVING`, `CANCELLED` | Authoritative mission progression |
| **Control** | `ACTIVE`, `PAUSED`, `BLOCKED`, `CONTAINED`, `RECOVERING`, `EXPERT_ESCALATION` | Exceptional or supervisory condition |
| **Phase** | `CAPTURE`, `EXPLORE`, `PLAN`, `BUILD`, `VERIFY`, `REVIEW`, `COMMIT`, `RELEASE`, `LEARN` | Current work emphasis and UI projection |
| **Task state** | `PLANNED`, `READY`, `RUNNING`, `WAITING`, `APPROVAL_REQUIRED`, `VERIFYING`, `FAILED`, `COMPLETED`, `ABORTED` | Scheduling and execution status |

The familiar UI labels are projections: “Clarifying” maps to `DRAFT/FRAMED + CAPTURE`; “Planned” to `FRAMED + PLAN`; “Approved” to `AUTHORIZED`; “Running” to `EXECUTING`; “Verifying” to `AUDITING`; “Review” to `READY_TO_TRY`; and “Accepted” to `ACCEPTED`. The interface always shows the blocking reason—user, tool, test, dependency, quota, lease, network, policy, or worker—rather than overloading one status label.

### Transition predicates

Transitions are authorized by deterministic predicates. For example, `AUDITING → READY_TO_TRY` requires:

- Candidate digest equals every mandatory evidence item’s artifact digest.
- All required criteria meet their configured evidence grade and freshness.
- No open critical contradiction or policy exception exists.
- All mandatory checks are complete or explicitly waived by authorized humans.
- No essential variable is outside its permitted band.
- Rollback instructions are present for consequential candidates.

`ACCEPTED → RELEASED` additionally requires a verified manifest/signature, environment-specific authorization, deployment idempotency key, successful precondition checks, and active post-release sensors.

### Durable workflow port

```python
class WorkflowPort(Protocol):
    async def start(self, definition, input, workflow_id): ...
    async def signal(self, workflow_id, signal, payload): ...
    async def query(self, workflow_id, projection): ...
    async def pause(self, workflow_id, reason): ...
    async def resume(self, workflow_id, checkpoint_id): ...
    async def cancel(self, workflow_id, reason): ...
```

The first implementation uses a persisted state machine, append-only history, leases, timers, and an outbox. Temporal becomes the preferred adapter once missions routinely survive process restarts, wait for humans for long periods, or coordinate multiple external systems. Workflow code must remain deterministic; model, network, filesystem, and other nondeterministic operations execute as idempotent activities.[^2]

### Retry taxonomy

- **Transient:** bounded exponential backoff with jitter and total-attempt budget.
- **Deterministic defect:** return to diagnosis or repair; never blind-retry identical inputs.
- **Policy denial:** do not retry until authority, policy, or context changes.
- **Ambiguity:** request clarification only when the user has unique decision-relevant information.
- **Oscillation:** freeze affected scope after repeated opposite patches or recurring failure signatures.
- **Unknown side effect:** contain, preserve evidence, reconcile external state, then decide.
- **Budget breach:** pause or downgrade within prior authorization; never silently expand spend or data exposure.

Every side effect has an idempotency key, precondition, postcondition, expected side effects, and compensation where feasible. Deployment, publication, deletion, credential changes, financial actions, messaging, and database mutation are never buried inside an unconstrained model tool call.[^2]

## Event architecture

### Three distinct records

1. **Domain events** are authoritative facts such as `MissionAuthorized`, `CapabilityRevoked`, `ClaimContradicted`, or `SafeStateEntered`.
2. **Workflow history** records scheduling, timers, signals, retries, activity outcomes, and replay decisions.
3. **Telemetry** records diagnostic traces, metrics, logs, resource use, and latency.

OpenTelemetry is not the system of record. Trace IDs correlate all three records, but the application can rebuild domain projections without telemetry.[^1][^2]

### Canonical envelope

```json
{
  "specversion": "1.0",
  "id": "evt_01...",
  "source": "kosmos://project/prj_123/control-kernel",
  "type": "io.kosmos.claim.contradicted.v1",
  "time": "2026-09-26T10:00:00Z",
  "subject": "claims/clm_456",
  "datacontenttype": "application/json",
  "traceparent": "00-...",
  "data": {
    "project_id": "prj_123",
    "mission_id": "mis_789",
    "recursion_path": ["project", "mission"],
    "purpose_ref": "charter:v7#privacy-1",
    "actor": {"principal": "auditor:access-probe", "authority": "observe"},
    "causal_parents": ["evt_..."],
    "artifact_digest": "sha256:...",
    "schema_version": 1
  }
}
```

### Event rules

- Events are immutable; corrections append a superseding event.
- Commands carry idempotency keys and expected aggregate versions.
- Aggregate writes and outbox publication intent commit atomically.
- Consumers checkpoint and tolerate duplicate delivery.
- Schemas are versioned; readers ignore unknown optional fields.
- Sensitive data is stored as encrypted artifact references, not copied into event payloads.
- Every user-visible status can expose the events, policies, and evidence from which it was projected.
- Event retention and redaction are data-class aware.

### Event families

- Mission: `MissionCreated`, `ContractFramed`, `MissionAuthorized`, `MissionPaused`, `MissionContained`, `MissionAccepted`, `MissionCancelled`.
- Plan/task: `PlanProposed`, `PlanApproved`, `TaskReady`, `TaskStarted`, `TaskBlocked`, `TaskCompleted`, `TaskFailed`, `PlanDeviationRecorded`.
- Authority: `CapabilityRequested`, `PolicyDecided`, `CapabilityGranted`, `CapabilityRevoked`, `ApprovalRecorded`.
- Runtime: `AgentInvoked`, `ModelRouted`, `ModelCalled`, `ToolRequested`, `ToolCompleted`, `LeaseAcquired`, `LeaseReleased`.
- Change: `CheckpointCreated`, `PatchCreated`, `ArtifactProduced`, `CandidateSealed`.
- Assurance: `CriterionEvaluated`, `EvidenceAttached`, `ClaimSupported`, `ClaimContradicted`, `EvidenceStaled`.
- Release: `ReleaseAuthorized`, `ReleaseStarted`, `ReleaseCompleted`, `RollbackStarted`, `RollbackCompleted`.
- Knowledge: `MemoryProposed`, `MemoryPromoted`, `AssertionInvalidated`, `WorkflowVersionPublished`.
- Incident: `ThresholdBreached`, `SafeStateEntered`, `IncidentOpened`, `RecoveryStarted`, `SystemRestored`.

## Policy and autonomy

### User-facing tiers

| Tier | UX meaning | Default capability ceiling |
|---|---|---|
| **A0 Observe** | Read-only analysis | Repository search, inspection, explanation, no external writes |
| **A1 Suggest** | Produce plan, patch, or commands without applying | Local artifact creation only |
| **A2 Apply reversible** | Apply scoped, checkpointed changes | Tracked-file edits and tests in a worktree |
| **A3 Execute bounded** | Run preapproved workflows under quotas | Dependency upgrades, benchmarks, browser journeys, background tasks |
| **A4 Operate consequential** | Step-up approval for external or irreversible effects | Deploy, migrate, merge, publish, send, delete, credential changes |

The tier is a comprehensible preset, not the enforcement mechanism. It compiles into action-specific policy inputs and short-lived capability grants.[^1][^2]

### Policy request

A policy decision includes:

```json
{
  "principal": "agent:energeia/mis_789/worker_3",
  "human_sponsor": "user:123",
  "action": "tool.invoke",
  "resource": "mcp:github/create_pull_request",
  "project": "prj_123",
  "mission": "mis_789",
  "risk": "external_write",
  "environment": "preview",
  "data_class": ["source_code"],
  "network_destination": "github.com",
  "budget_remaining": {"usd": 3.12, "seconds": 480},
  "evidence": ["approval:dec_456"],
  "policy_digest": "sha256:..."
}
```

The response is `{decision, obligations, expiry, reason_code}` rather than a bare allow/deny. Obligations may require redaction, explicit approval, read-only mode, stronger isolation, a narrower path or host, a spending ceiling, a checkpoint, or post-action verification.

### Capability rules

- Unique machine identity per mission and worker.
- Short-lived, audience-bound token per tool/action.
- No inheritance of broad user credentials.
- Default-deny filesystem, network, secrets, external writes, and delegation.
- Discovery permissions remain separate from mutation permissions.
- Grants are revoked on pause, cancellation, containment, charter change, or worker termination.
- Policy bundles are signed; decisions record their digest.
- MCP interoperability never substitutes for host authorization, input validation, output sanitation, isolation, or audit.

### Permission UX

An approval card shows, while collapsed:

1. Exact action.
2. Why it is required and the criterion/task it serves.
3. Expected impact and side effects.
4. Resource, credential, environment, path/host, and duration scope.
5. Reversibility, checkpoint, and rollback.
6. Safer alternatives.
7. Decisions: approve once, approve for mission, narrow/edit, or deny.

Expanded content shows the command/API payload, redactions, policy evaluation, triggering agent, related diff, backup status, and compensation. Consequential cards never focus “Approve” by default.[^1]

### Risk engine

Risk is computed from read/write semantics, local/external effects, reversibility, credential and data sensitivity, scope breadth, tool/server/model novelty, environment, destructive patterns, prompt-injection indicators, policy, dependency trust, and historical behavior. The factors and resulting obligations are visible and correctable, but correction itself requires appropriate authority.

## Sandboxed execution

### Isolation tiers

| Risk | Isolation | Typical use |
|---|---|---|
| Low, local, read-only | Bubblewrap, namespaces, seccomp, read-only mounts | Repository orientation and indexing |
| Medium, code execution | Rootless OCI container under gVisor | Builds, tests, package operations, browsers |
| High or multi-tenant | Firecracker microVM plus egress gateway | Untrusted generated code, release builds, sensitive integration checks |

Each worker receives:

- A clean Git worktree or checkout pinned to a baseline commit.
- A writable overlay restricted to mission scope.
- No host home-directory mount.
- Empty environment except explicitly injected variables.
- Ephemeral, task-scoped secret files.
- CPU, RAM, VRAM, process, disk, wall-time, token, and cost budgets.
- Network deny-by-default with host, port, method, protocol, and byte quotas.
- Captured stdout/stderr with secret redaction.
- File-access, process, network, and tool audit events.
- A supervisor-owned kill path that survives worker failure.
- Controlled artifact export with normalization and malware/content checks.

Parallel writers never share a working tree. The scheduler classifies tasks as independent, read-shared/write-isolated, write-conflicting, dependency-sequential, or speculative alternatives. Leases protect files, symbols, schemas, resources, and environments; conflict forecasting occurs before execution and again before integration.[^1][^2]

## Mission experience

### Persistent modes

| Mode | Mutation | Tools | Primary result |
|---|---:|---:|---|
| **Ask** | No | Read-only | Answer linked to repository and knowledge sources |
| **Explore** | No | Read-only | Orientation packet, code map, hypotheses, risks |
| **Plan** | No by default | Read-only | Editable contract, task graph, criteria/evidence matrix |
| **Build** | Yes under policy | Yes | Patch, candidate artifacts, tests, verification request |
| **Operate** | Potentially consequential | Yes | Release, monitoring, incident response, rollback |

Mode is persistent near the composer, visible in the global bar, and logged on change. The system cannot silently turn exploration into mutation.[^1]

### Capture

The structured composer accepts natural language, slash commands, voice, images, screenshots, sketches, pasted logs, files, symbols, diffs, issues, URLs, trace spans, and knowledge nodes. Scope chips (`@repo`, `@file`, `@selection`, `@terminal`, `@issue`, `@run`, `@memory`) and constraint chips (“offline only,” “no new dependencies,” “preserve API,” “under 2 GB VRAM”) make intent explicit.[^1]

An intent compiler proposes a mission delta containing goal, audience, beneficiaries, scope, constraints, exclusions, criteria, assumptions, risks, and high-impact questions. Low-impact assumptions are batched for review rather than interrupting the user.

### Explore

Read-only exploration produces a source-linked orientation packet:

- Repository topology, build/runtime, and important entry points.
- Components, modules, data flows, and dependency boundaries.
- Relevant tests, conventions, policies, and hierarchical repository instructions.
- Existing implementations and duplication risks.
- Architecture constraints and likely affected symbols.
- Unknowns, security risks, migration concerns, and verification opportunities.

The packet is an artifact and a knowledge candidate, not a long chat transcript.

### Plan

Every plan has synchronized representations:

- Human-readable outline.
- Dependency DAG.
- Table of ownership, scope, policy, estimates, and state.
- Accessible ordered tree.
- Versioned machine-readable workflow definition.

Every node defines intent, expected output, preconditions, dependencies, typed inputs/outputs, read/write scope, assigned profile, model/tool route, acceptance criteria, evidence grade, verification command, risk, approval rule, estimate, timeout, retries, idempotency, cache policy, concurrency, rollback/compensation, and escalation. Before authorization, the planner rejects cycles, missing criteria, unsafe parallelism, write conflicts, unsupported rollback assumptions, and policy-incompatible tools.[^1]

### Execute

Execution occurs in scoped workers and worktrees. The default presentation is a compact lane timeline: planned, ready, running, waiting, approval required, verifying, failed, and completed. Routine activity collapses into meaningful summaries; anomalies, deviations, uncertainty, budget risk, and decision points remain prominent.[^1]

The user can independently pause, stop, checkpoint, detach, resume, reassign, or contain workers according to authority. `Stop` terminates active work; `Pause` preserves resumable state; `Checkpoint` snapshots recoverable state; `Detach` moves a run into durable background execution; `Rollback` restores a selected checkpoint.

### Verify

Verification is a separate mission phase. Each criterion maps to one or more evidence requirements:

| Criterion | Preferred evidence |
|---|---|
| Functional | Unit, integration, end-to-end, or journey test |
| Visual | Before/after screenshots, responsive/state variants, and visual diff |
| Performance | Reproducible benchmark with environment, baseline, distribution, and regression threshold |
| Security | Static/dynamic scanning, dependency audit, authorization matrix, and independent probe |
| Accessibility | Automated audit plus keyboard and screen-reader journey |
| Compatibility | Version/platform/configuration matrix |
| Architectural | Dependency and boundary rules checked against observed architecture |
| Operational | Health signals, traces, canary result, rollback drill, and post-release observation |

The criterion UI reports `Pass`, `Fail`, `Partial`, `Not run`, `Inconclusive`, `Waived`, `Stale`, or `Contradicted`. A required criterion cannot be green while evidence is absent, inconclusive, stale, attached to a different digest, or below its required independence grade.[^2][^1]

### Review and accept

Review is grouped by intent and criterion rather than file order. The stack contains the change summary, plan deviations, acceptance matrix, semantic change groups, file/AST/word diffs, runtime evidence, new dependencies, unresolved risks, implementer self-review, and independent audit.

Comments can target a line, symbol, task, criterion, screenshot region, trace span, policy decision, or evidence item and can be promoted directly into a repair task. Acceptance can commit locally, organize commits, open a pull request, merge under policy, export a patch/bundle, save a workflow/skill, promote knowledge, or add a failure to the evaluation suite.[^1]

### Release and observe

A release is distinct from accepting code. The release controller:

- Seals the candidate and computes its digest.
- Builds or reproduces it in a clean environment.
- Verifies required evidence against that exact digest.
- Produces provenance and an SBOM where applicable.
- Signs the release manifest.
- Executes environment-specific policy gates.
- Confirms rollback readiness.
- Deploys with an idempotency key.
- Activates post-release essential-variable sensors.
- Rolls back or contains automatically when authorized thresholds breach.

### Learn

Learning uses a controlled pipeline:

```text
Observation → candidate lesson → provenance review → offline replay
→ benchmark/security review → canary skill or policy → monitored promotion
→ retain, revise, or rollback
```

Memory promotion is never silent. The user reviews source, confidence, scope, applicable revision, expiry, sensitivity, conflict state, expected reuse, and revocation path. Only a charter workflow with human authority can modify purpose or constitutional policy.[^2][^1]

## Workbench information architecture

### Stable navigation

The left rail preserves the GUI specification’s seven destinations:

- **Home:** active missions, recent projects, alerts, schedules, and resume cards.
- **Missions:** bounded outcomes across projects.
- **Projects:** repositories, environments, charters, architecture, rules, and health.
- **Workflows:** typed task graphs, skills, triggers, versions, tests, and fixtures.
- **Knowledge:** memories, decisions, entities, sources, conflicts, provenance, and staleness.
- **Agents:** profiles, teams, tools, model routes, policies, and quality cards.
- **Operations:** queues, active workers, budgets, leases, traces, releases, incidents, and recovery.

Within a mission, the primary perspectives are:

- **Product:** live preview and user journeys.
- **Progress:** meaningful phases, blockers, causal flow, budgets, and next action.
- **Proof:** criteria, claims, evidence, contradictions, scope, and freshness.
- **Foresight:** expected disturbances, expiring evidence, dependency changes, and deadlines.
- **Charter:** purpose, affected parties, boundaries, authority, and invariants.
- **Live:** environment health, releases, cost, incidents, and recovery.
- **Expert:** code, terminal, diffs, tools, traces, policies, artifacts, and raw events.

These are coordinated perspectives, not separate products. The expert can expose all low-level surfaces, while a nontechnical user can remain in Product, Progress, Proof, Charter, and Live without losing access to the same authoritative state.[^2][^1]

### Adaptive shell

```text
┌──────────────────────────────── Global bar ─────────────────────────────────┐
│ Project/Mission | Mode | Worktree | Route | Budget | Risk | Run controls   │
├──────────────┬──────────────────────────────────────┬───────────────────────┤
│ Navigator    │ Primary workspace                    │ Inspector             │
│ Missions     │ Code / Product / Preview / Workflow │ Contract / Context    │
│ Files        │ Proof / Knowledge / Operations       │ Plan / Diff / Policy │
│ Symbols      │                                      │ Evidence / Approval  │
├──────────────┴──────────────────────────────────────┴───────────────────────┤
│ Activity: Terminal | Tests | Problems | Logs | Trace | Timeline | Leases  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Structured composer: mode · scope · constraints · criteria · send/queue   │
└─────────────────────────────────────────────────────────────────────────────┘
```

Panels can be hidden, moved, pinned, resized by keyboard, and saved as named layouts. Selecting an object synchronizes all views: a failed criterion highlights its task, changed symbols, evidence, causal trace, logs, responsible worker, capability decision, and candidate digest.[^1]

### Global bar

The bar displays repository and mission, explicit mode, branch/worktree with dirty/conflict state, actual model route and local/cloud boundary, context pressure and compaction, token/cost/time/compute budget, pending high-impact risk, execution controls, and connection/replay state. Silent model fallback is prohibited; a local-to-cloud route change requires disclosure of context leaving the machine and consent according to policy.[^1]

### Context inspector

Context is a versioned manifest listing:

- Included files, symbols, chunks, conversations, rules, memories, tool schemas, and attachments.
- Selection reason, path/span, score, timestamp, source, confidence, authority, and token estimate.
- Excluded, redacted, summarized, or truncated items.
- Applicable policy and data-classification boundaries.
- The exact manifest hash used for a model invocation.

Users may pin, remove, reorder, redact, mark authoritative, or narrow context. Compaction creates an inspectable event and artifact; summaries retain provenance links and never silently replace source authority.[^1]

## Coordinated visualizations

| Data | Default | Equivalent/alternate |
|---|---|---|
| Repository | Tree with status overlays | Package table or treemap |
| Symbols | Bounded dependency neighborhood | Searchable adjacency table |
| Workflow | Collapsed DAG | Outline, table, searchable accessible tree |
| Execution | Lane timeline | Span tree, Gantt, flame chart, event table |
| Changes | Semantic groups | File, unified, side-by-side, word, AST, commit diff |
| Tests/evidence | Criterion hierarchy | Environment matrix and raw export |
| Knowledge | Faceted document cards | Bounded local graph and relation table |
| Agents | Queue/board | Critical path, Gantt, and worker table |
| Viability | Essential-variable bands | Ordered textual state and incident history |

Graphs follow “overview first, zoom/filter, details on demand,” but no graph is the sole representation. Status always combines text, icon/shape, and color. Aggregates use honest fractions such as `18/22 required checks passed`, never a single green badge that hides unknowns.[^1]

## Workflow system

### Node types

- **Workflow node:** deterministic or bounded sequence.
- **Agent node:** dynamically pursues a delegated objective.
- **Tool node:** atomic capability behind policy enforcement.
- **Approval gate:** human or policy decision.
- **Evidence gate:** verification requirement.
- **Artifact node:** content-addressed output.
- **Loop node:** explicitly bounded iteration with convergence and oscillation rules.
- **Release gate:** exact-digest, signature, rollback, and environment checks.

Typed ports cover context, artifact, control, evidence, error, approval, capability, and observation. A node also declares timeout, retry class, idempotency, concurrency, leases, cache policy, compensation, escalation, and required isolation.

### Storage and versioning

Repository-shared workflows are readable text assets with a typed schema and stable IDs. The visual canvas, outline, table, and source view edit the same abstract syntax tree. Definitions have migrations, fixtures, contract tests, policy declarations, and semantic diffs.[^1]

Initial templates include feature implementation, bug reproduction/repair, dependency upgrade, security review, repository onboarding, release preparation, benchmark regression, incident diagnosis, documentation synchronization, accessibility audit, and model-route evaluation.

## Knowledge and memory

### Memory classes

| Class | Contents | Lifetime | Promotion rule |
|---|---|---|---|
| Working | Current mission context and scratch hypotheses | Run/session | Expires automatically |
| Episodic | Events, decisions, actions, and outcomes | Project history | Immutable/supersedable event record |
| Semantic | Stable project facts and relationships | Until invalidated | Evidence-backed and reviewed |
| Procedural | Workflows, skills, commands, playbooks | Versioned | Tested before trusted |
| Preference | User interaction and coding preferences | User-controlled | Explicit or reviewable inference |

No undifferentiated vector store is treated as memory or truth. Embeddings are retrieval aids over authoritative records; retrieval does not confer validity, freshness, permission, or authority.[^2][^1]

### Assertion model

Every `KnowledgeAssertion` carries source/span, extractor/creator, observation and creation time, confidence, verification state, repository revision, scope, expiry/refresh policy, sensitivity, conflicts, superseding claims, and provenance edges. Relations include imports, calls, implements, depends-on, supersedes, conflicts-with, satisfies, verifies, generated-by, derived-from, observed-in, owned-by, applicable-to, and invalidated-by.

The Knowledge Studio defaults to searchable faceted documents, a provenance panel, conflict inbox, staleness queue, decision timeline, retrieval simulator, and promotion queue. Graph views are bounded to selected neighborhoods or query results, avoiding an unreadable global hairball.[^1]

### Architecture model

Kosmos maintains a live model of system context, services/containers, components/modules, APIs, data contracts, runtime dependencies, ownership, policy boundaries, deployment topology, and architecture decisions. Derived structure is labeled observed or inferred. Human-authored constraints can compile into automated evidence gates, such as forbidden dependencies or required API compatibility.

## Agent and model orchestration

### Agent profiles

A versioned profile defines purpose, success criteria, model route and fallback, tools, policy, context strategy, memory scopes, workflows/skills, sandbox, time/token/cost/concurrency limits, escalation/stop rules, and evaluation history. Every mission records the exact profile and route versions used.

The default topology is one coordinator with specialized workers, not a theatrical swarm. Delegation is a typed, inspectable contract containing objective, input artifacts, scope, authority, budget, output schema, criteria, deadline, and escalation rules.[^2][^1]

### Model gateway

Model routes are policy names rather than hard-coded providers:

- Fast local completion.
- Private local code analysis.
- High-capability local agent.
- Specialized vision, embedding, reranking, or verification.
- Cloud escalation requiring policy and consent.
- Ordered fallback with explicit data-boundary consequences.

A `llama.cpp` adapter supports local OpenAI/Anthropic-compatible inference, embeddings, reranking, and metadata; a gateway adapter can add routing, cooldowns, retries, and provider fallbacks. The UI records the route requested, route selected, fallback reason, provider, model/version, quantization where available, context sent, latency, token counts, cost, and quality history.[^1]

## Visual coding

For UI missions, Plan mode adds an infinite design canvas with frames, variants, flows, annotations, and requirement links. The preview supports element-to-source breadcrumbs, scoped visual edits, selected-region language commands, breakpoint comparison, component-state matrices, fixture switching, accessibility tree/focus order, and console/network/performance overlays.[^1]

Visual edits first produce a preview patch. The user chooses whether the mutation targets a local instance, shared component, design token, or generated variant. The system discovers token hierarchy, component catalog, variants, spacing, typography, icon source, accessibility patterns, and duplicate components; it proposes reuse before invention and makes deviations reviewable.[^1]

## Storage and protocols

### Stores by workload

- **PostgreSQL:** aggregates, projections, policies, permissions, leases, indexes, claims, evidence metadata, incidents, releases, and event offsets.
- **Append-only event journal:** authoritative domain history with transactional outbox.
- **Content-addressed object store:** artifacts, screenshots, logs, traces, patches, manifests, SBOMs, and verification bundles.
- **PostgreSQL FTS plus pgvector:** lexical/semantic hybrid retrieval with explicit metadata filters.
- **Git:** source, text workflows, profile definitions, repository rules, and shared decisions.
- **Graph projection:** local relationship queries; add a graph database only after measured PostgreSQL limitations.
- **Secret manager:** OS keyring initially, Vault-compatible provider later; never store secrets in knowledge or events.

Tenant-bearing tables use row-level security and fail-closed policies. Retrieval indexes are scoped by authorization and project/revision; filtered approximate retrieval is benchmarked for recall before use in safety-critical context selection.[^2][^1]

### Protocol boundaries

| Boundary | Protocol or abstraction | Rule |
|---|---|---|
| UI ↔ kernel | AG-UI-compatible projection stream plus internal command API | UI protocol is not the domain model |
| Editor ↔ coding agent | ACP adapter | Internal mission contract remains richer |
| Agent ↔ tools/context | MCP adapter and trust registry | Host policy wraps every invocation |
| Agent ↔ agent | Internal typed delegation; optional A2A adapter | Use only where cross-platform delegation adds value |
| Events | CloudEvents-compatible envelope | Domain-specific schemas remain versioned |
| Telemetry | OpenTelemetry plus GenAI mappings | Diagnostic, never authoritative |
| Code intelligence | LSP, tree-sitter, ripgrep, language indexes | Sources and versions retained |
| Provenance | W3C PROV-inspired model; SLSA-style build provenance | Exact artifact digests are mandatory |
| Feature rollout | OpenFeature-compatible port | Flags cannot bypass invariants |

## Observability and privacy

Trace the control kernel, workflow activities, workers, policy decisions, model gateway, tool adapters, verification, release, and UI projections. High-value measures include mission lead/queue time, model/tool failures, retries, time outside essential-variable bands, contradictions caught before/after release, repair recurrence, oscillation, wasted cost, evidence freshness, independent-evidence coverage, capability denials/step-ups/unused grants, containment latency, restore success, interruption count, decision latency, and forecast error.[^2][^1]

Prompts, tool payloads, file contents, and secrets are not recorded by default. Content capture requires explicit opt-in, classification, redaction, encryption, retention, and deletion policy. DORA metrics may inform delivery, but product success is measured by verified outcomes per unit of human attention, constrained by escaped intent defects, policy escapes, false-ready states, maintainability, recovery, and comprehension.[^2][^1]

## Accessibility and language

Target WCAG 2.2 AA throughout, with stronger focus appearance and target sizing for stop, deny, containment, rollback, and release controls. All actions are available through keyboard and command palette; streaming does not steal focus or cause layout jumps; async announcements are prioritized; motion is optional; user font size, zoom, density, high contrast, and reduced motion are supported.[^2][^1]

Use operational language:

- “Needs approval,” not “The agent needs your help.”
- “Implemented, not verified,” not “Done.”
- “No evidence collected,” not “Likely works.”
- “Local model timed out; cloud fallback requires consent,” not “Retrying.”
- “Three files outside approved scope were proposed; none were modified,” not “Plan adjusted.”

## Recovery and incidents

Recovery is layered:

- Undo a visual edit.
- Revert a semantic patch group.
- Reset a task to checkpoint.
- Restore a mission checkpoint.
- Abandon a worktree.
- Revert a commit or pull request.
- Execute a workflow compensation.
- Roll back a release.
- Revoke/rotate credentials and quarantine artifacts.
- Enter a safe state and preserve incident evidence.

An incident card states the breached variable or invariant, containment already taken, visible impact, confidence and unknowns, affected artifact/environment, preserved evidence, safe choices, and recovery path. Algedon triggers and enforcement are deterministic; a model may explain evidence but cannot suppress containment.[^2][^1]

## Technical stack

| Layer | Selected implementation |
|---|---|
| Desktop shell | Tauri 2 on Linux first; signed cross-platform packaging later |
| UI | React, TypeScript, accessible headless primitives, TanStack Query/Table as appropriate |
| State | Projection cache plus command client; no authoritative client-side workflow state |
| Editor | Monaco behind `EditorPort` |
| Terminal | xterm.js connected to a scoped PTY service |
| Workflow canvas | SVG/Canvas hybrid with virtualized rendering and synchronized DOM outline/table |
| Domain core | Python 3.13+, asyncio, typed domain packages, Pydantic v2 at boundaries |
| IPC/API | Unix socket or loopback HTTPS/WebSocket with capability-bound sessions |
| Workflow | Local durable state-machine adapter first; Temporal adapter when justified |
| Policy | OPA/Rego policy decision point; enforcement in kernel, adapters, and supervisor |
| Database | PostgreSQL 17+ with RLS, FTS, and pgvector |
| Events | Append-only journal, transactional outbox, versioned CloudEvents envelopes |
| Artifacts | Content-addressed local store; optional S3-compatible backend |
| Execution | Bubblewrap, then rootless OCI/gVisor, then Firecracker by risk tier |
| Source isolation | Git worktrees and clean-checkout verification |
| Code intelligence | LSP, tree-sitter, ripgrep, language-specific indexes |
| Models | llama.cpp local adapter plus provider-neutral model gateway |
| Telemetry | OpenTelemetry collector with local-first storage/export policy |
| Secrets | OS keyring initially; Vault-compatible adapter later |
| Signing | Sigstore/Cosign-compatible manifest and artifact signing |

### Frontend choice rationale

The Tauri/React client wins the primary role because the complete UX depends on Monaco, xterm.js, browser preview instrumentation, accessible web component ecosystems, workflow canvas libraries, and possible web/mobile review projections. PySide6/QML remains a supported future client through the same semantic projection and command contracts; no kernel capability depends on React, Tauri, or browser-local state. This resolves the source documents’ only major stack conflict while preserving the ecological cockpit and all IDE-grade interactions.[^2][^1]

## Repository structure

```text
kosmos/
├── apps/
│   ├── desktop/                 # Tauri host
│   └── workbench-ui/            # React/TypeScript projections
├── src/kosmos/
│   ├── domain/                  # aggregates, commands, events, predicates
│   ├── application/             # use cases, ports, orchestration
│   ├── kernel/                  # charter, policy, scheduler, evidence, algedon
│   ├── workflow/                # durable engine adapter and definitions
│   ├── workers/                 # supervisor and bounded worker runtime
│   ├── assurance/               # clean verification and evidence grading
│   ├── release/                 # candidate sealing, signing, deploy, rollback
│   ├── knowledge/               # assertions, retrieval, promotion, staleness
│   ├── projections/             # UI/read models and semantic status cards
│   ├── adapters/
│   │   ├── models/              # llama.cpp and cloud providers
│   │   ├── tools/               # MCP and native tools
│   │   ├── agents/              # ACP/A2A adapters
│   │   ├── git/
│   │   ├── sandbox/
│   │   ├── storage/
│   │   ├── policy/
│   │   └── telemetry/
│   └── api/                     # command/query/projection transport
├── schemas/
│   ├── commands/
│   ├── events/
│   ├── workflows/
│   ├── projections/
│   └── policies/
├── policies/                    # signed Rego bundles and fixtures
├── workflows/                   # repository-shared workflow definitions
├── ui-contracts/                # generated TS/Python schema bindings
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── property/
│   ├── stateful/
│   ├── integration/
│   ├── journeys/
│   ├── adversarial/
│   ├── sandbox/
│   ├── accessibility/
│   └── formal/
└── deploy/
    ├── containers/
    ├── systemd/
    └── packaging/
```

Dependency direction is `domain ← application ← adapters/API`; the UI communicates only through published contracts. Kernel modules may share transaction and event infrastructure but cannot bypass one another’s enforcement ports.

## Testing and formal assurance

Required test layers:

- Domain unit tests for invariants, thresholds, status reductions, and transition predicates.
- Contract tests for ports, adapters, event schemas, workflow schemas, and UI projections.
- Property-based tests for authority, budgets, idempotency, replay, evidence reduction, and provenance.
- Stateful tests for crash/retry, pause/resume, revocation, outbox duplication, leases, and rollback.
- Hermetic integration tests with fake model/tool/provider implementations.
- Golden user journeys from intent through candidate, proof, acceptance, release, and recovery.
- Adversarial prompt injection, memory poisoning, tool confusion, credential relay, and unsafe delegation tests.
- Sandbox escape, secret leak, egress, resource exhaustion, and artifact exfiltration tests.
- Candidate-to-audit-to-release digest identity and restore drills.
- Accessibility journeys and UI performance budgets.
- Selective TLA+ models for critical concurrency invariants.[^2]

Formalize at minimum:

- An unaudited digest is never released.
- A revoked capability cannot authorize a later action.
- Only one active write lease owns a mutable resource.
- Containment eventually stops all affected workers.
- Replayed events produce the same aggregate and projection state.
- A critical contradiction prevents readiness unless resolved by authorized evidence.

## Phased implementation

### Phase 0 — Invariants and contracts

**Duration:** 2–3 weeks.

- Define Charter, authority matrix, Mission, Claim, Evidence, Artifact, CapabilityGrant, EssentialVariable, Release, and Incident schemas.
- Specify 10–15 safety/correctness invariants and transition predicates.
- Threat-model runtime, retrieval, memory, tool registry, approvals, workers, UI projection, and release.
- Define event, command, workflow, policy-input, and projection schemas with compatibility rules.
- Build deterministic fake model/tool adapters and the initial abuse corpus.
- Create architecture decision records for Tauri/React, Python kernel, PostgreSQL, local workflow adapter, and sandbox tiers.

**Exit:** every authority-changing action has an enforcement point; every critical invariant has a test or formal-model plan.

### Phase 1 — Trustworthy vertical slice

**Duration:** 6–9 weeks.

- Desktop shell with Home, Mission, Product, Progress, Proof, Charter, Expert, command palette, and accessible layouts.
- Structured composer, intent compiler, contract review, Ask/Explore/Plan/Build modes.
- PostgreSQL, append-only events, outbox, replay, projections, and AG-UI-compatible stream.
- One workflow, one worker, Git worktree lifecycle, Bubblewrap sandbox, scoped PTY, and kill path.
- One local model adapter plus deterministic fake; basic context inspector.
- OPA-backed policy decisions and mission-bound capability grants.
- Linear editable plan, checkpoints, pause/stop/resume/rollback.
- Claim/evidence matrix, clean-checkout E3 verification, semantic diff, exact-digest candidate preview.

**Demo:** request a bounded UI change, inspect plan and scope, watch outcome-level progress, try the exact candidate, see independent evidence, accept or restore.

**Exit:** every external action is attributable, authorized, replay-safe, reversible where promised, and linked to purpose, criterion, and artifact digest.

### Phase 2 — Safety, workflows, and release

**Duration:** 7–11 weeks.

- Typed DAG workflow editor with outline/table/text equivalents, fixtures, retries, compensation, and leases.
- gVisor tier, egress broker, ephemeral secrets, redaction, and stronger artifact normalization.
- Release controller, signed manifests, SBOM, provenance, canary, rollback, and essential-variable sensors.
- Security, accessibility, dependency, browser-journey, and policy audits through E4.
- Algedon threshold engine, incident cards, safe-state playbooks, and evidence preservation.
- Property/stateful test suites and first TLA+ specifications.
- Knowledge classes, promotion queue, provenance, staleness, and retrieval simulator.

**Exit:** fault injection demonstrates containment, restart recovery, capability revocation, exact-digest release, and tested rollback.

### Phase 3 — Expert UX and parallelism

**Duration:** 8–12 weeks.

- Full adaptive shell with Monaco, xterm.js, coordinated code/trace/evidence views, and saved density/layout presets.
- Multiple bounded workers, coordinator, typed handoffs, per-worker context/policy/budget/worktree.
- File/symbol/schema/resource leases, dependency scheduling, backpressure, conflict forecasting, and oscillation detection.
- Parallel/speculative alternatives with normalized comparison and selective cherry-pick.
- Background missions, durable notifications, heartbeat/checkpoint policy, reconnect, and resume briefings.
- Agent/model/tool quality cards and evaluation gates.
- ACP adapter, mature MCP host/trust registry, optional A2A boundary.

**Exit:** parallelism reduces time to verified outcomes without raising escaped defects, policy violations, conflicts, recovery time, or human attention.

### Phase 4 — Visual building and architecture knowledge

**Duration:** 8–12 weeks.

- Design canvas, variants, annotations, preview-to-source selection, scoped visual edits.
- Responsive, state, and data matrices; accessibility tree and visual regression evidence.
- Design-system discovery, component reuse, token-aware patches, and conformance checks.
- Live architecture model, decision records, relation projections, and compiled architecture gates.
- Advanced semantic/AST diffs and intent-grouped review.

**Exit:** visual iteration is faster than prompt-only work while generating cleaner, more consistent, accessible, and independently verified code.

### Phase 5 — Foresight and controlled learning

**Duration:** 8–12 weeks, then continuous.

- Environmental signal ingestion, expiry, forecasts, calibration, and prediction-error tracking.
- Offline replay corpus sourced from real failures and rejected patches.
- Candidate-skill generation, security review, shadow mode, canary promotion, and rollback.
- Cost/latency/quality routing policies and feature-flagged experiments.
- Viability-debt inventory, maintenance horizon, production E5 signals, and longitudinal E6 analysis.
- Optional QML or web review client against the stable projection API.

**Exit:** at least one recurring task class improves quality-adjusted cost or lead time without degrading charter compliance, security, evidence integrity, accessibility, recovery, or comprehension.

## Build priority

If only ten major capabilities can be funded, implement them in this order:

1. Charter, authority, invariants, and command schemas.
2. Mission state machine with pause, stop, containment, cancellation, and recovery.
3. Append-only events, transactional outbox, deterministic replay, and projections.
4. Capability policy enforcement outside models.
5. Isolated worktree worker with default-deny network/secrets and supervisor kill path.
6. Claim/evidence/provenance model tied to exact artifact digests.
7. Independent clean-checkout verification.
8. Product-facing cockpit plus expert diff/context views.
9. Reversible signed release with tested rollback and post-release sensors.
10. Evaluation harness for intent drift, false readiness, policy escape, recovery, accessibility, and comprehension.[^2]

## Acceptance gates

### Kernel gate

- All state changes originate from validated commands and immutable events.
- Commands are authenticated, authorized, scoped, version-checked, and idempotent.
- Replay reconstructs identical aggregate and projection state.
- Schema compatibility and upcasters are tested.
- Mutation fails closed on policy, identity, projection-version, or persistence failure.

### Worker gate

- No inherited user credentials or home-directory access.
- Network and filesystem are default-deny with observable exceptions.
- Resource limits and supervisor kill work after restart.
- Outputs remain untrusted until normalized and checked.
- Pause, cancel, containment, and charter change revoke grants and stop affected work.

### Evidence gate

- “Proven” names exact claim, artifact, environment, method, grade, and freshness.
- Implementer evidence is visibly non-independent.
- Contradictions open conflicts; they are never averaged away.
- Candidate, audited, previewed, and released digests match where policy requires.
- Implementing models cannot waive critical claims.

### UX gate

- Users can identify purpose, current state, major uncertainty, scope, next action, and recovery path.
- Critical decisions do not require reading code, logs, scanner output, or hidden reasoning.
- Every graph and ecological visualization has keyboard and text equivalence.
- Streaming, reconnect, background execution, and replay preserve focus and orientation.
- “Implemented,” “verified,” “accepted,” and “released” are visibly distinct.

### Release gate

- Clean build and independent journey suite pass.
- Required evidence is fresh and bound to the promoted digest.
- Provenance, signature, and policy digest verify.
- No critical contradiction, policy exception, or essential-variable breach remains open.
- Rollback is tested for the target environment.
- Post-release sensors and automatic containment are active.

## Product evaluation

The north-star is **verified outcomes per unit of human attention**, constrained by defect risk, maintainability, policy compliance, recovery, accessibility, and user control.[^1]

Track mission success, criteria passed without waiver, false-ready rate, escaped defects, rollback rate, first-useful-plan time, verified-outcome time, human active minutes, interruptions, approvals, permission rejection, plan deviation, patch acceptance/manual rewrite, evidence completeness/freshness, retrieval correction, failure recovery, cost/energy per verified mission, containment latency, stale-memory incidents, knowledge reuse, confidence calibration, and accessibility completion.

Run experiments in shadow mode before raising autonomy. Canary by project and risk class, compare recommendations with actual outcomes, and preserve a rollback path for model routes, workflows, skills, policies, and projections. Feature flags select only among already-authorized behavior; they cannot bypass constitutional invariants.[^2]

## Rejected anti-patterns

- Chat transcript as system of record.
- One LLM persona per VSM box.
- Agent-generated enforcement policy.
- Self-review presented as independent audit.
- Raw MCP access interpreted as authorization.
- Global autonomy switch.
- Retry-everything behavior.
- Parallel writers in one worktree.
- Vector similarity treated as truth.
- Universal confidence score.
- Green status caused by missing telemetry.
- Hidden mode or model-route changes.
- Graph-only workflow authoring.
- Unbounded knowledge graph.
- Activity theater and private-reasoning simulation.
- File-order-only diff review.
- Silent memory promotion.
- Distributed services before measured need.
- Cloud-only operation.
- Autonomous charter evolution.[^2][^1]

## Provenance and integration notes

### GUI/UX specification retained

The unified specification preserves the six workbench surfaces; mission-centric information architecture; Ask/Explore/Plan/Build/Operate modes; A0–A4 autonomy tiers; adaptive shell; structured composer; context inspector; synchronized plans and workflows; evidence matrix; semantic review; knowledge classes; multi-agent/worktree UX; visual design canvas; permission, checkpoint, and recovery interactions; ACP/MCP/A2A/OpenTelemetry protocol strategy; keyboard/accessibility requirements; notifications; resume briefing; metrics; interaction cards; design-system guidance; and implementation phases.[^1]

### Cybernetic blueprint retained

The unified specification preserves the deterministic kernel; human-governed charter; VSM as logical responsibilities; modular monolith; domain aggregates; computed claim lifecycle; evidence ladder; separation of domain events, workflow history, and telemetry; CloudEvents envelope; durable workflow port; transition predicates; retry taxonomy; external policy enforcement; capability grants; isolation tiers; PostgreSQL/pgvector and content-addressed artifacts; independent assurance; ecological Product/Progress/Proof/Foresight/Charter/Live/Expert views; controlled learning; Algedon containment; signed exact-digest release; phased roadmap; acceptance gates; and build order.[^2]

### Reconciled changes

- The GUI document’s `Mission` and the blueprint’s `Charter` are composed, not substituted: Charter governs enduring purpose; Mission governs bounded execution.
- The two mission state machines become orthogonal lifecycle, control, phase, and task dimensions, preserving every meaningful state without ambiguous transitions.
- The GUI criterion matrix and cybernetic E0–E6 ladder become one evidence model with both user-comprehensible status and assurance strength.
- A0–A4 autonomy becomes a policy preset compiled into capability grants, preserving usability and enforceability.
- The broad knowledge graph becomes a relational/provenance core with bounded graph projections, preserving the Knowledge Studio without introducing a premature database dependency.
- OpenTelemetry remains fully available for traces and GenAI diagnostics but is explicitly non-authoritative.
- AG-UI carries UI projections; CloudEvents wraps domain facts; ACP/MCP/A2A remain boundary adapters rather than internal architecture.
- Tauri/React is selected for the primary IDE-grade client, while the PySide6/QML ecological UI remains implementable as a second client over stable contracts.
- Temporal is deferred behind `WorkflowPort`, not rejected; durable semantics are required from the first local adapter.
- Release, essential-variable sensing, foresight, and containment extend the GUI workflow beyond commit without weakening its local coding and review experience.

## Definition of done

Kosmos Agent Workbench reaches its integrated product goal when a user can state an outcome, inspect compiled intent and context, authorize a bounded plan, supervise or background isolated execution, understand every consequential action, inspect intent-grouped changes, evaluate fresh independent evidence against exact artifacts, safely try and accept a candidate, release it reversibly, observe its viability, contain failures, and promote validated learning—while every state remains replayable, every authority remains explicit, every critical view is accessible, and no model can certify or enlarge its own power.

---

## References

1. [The-Best-Possible-GUI-UX-for-an-Intelligent-Vibe-Coding-Agent.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/57152701/569d7589-1bce-492c-94c2-bee849094b03/The-Best-Possible-GUI-UX-for-an-Intelligent-Vibe-Coding-Agent.md?AWSAccessKeyId=ASIA2F3EMEYET6KNGEUP&Signature=ZNZSMRCNroE01kZcfh8valHuZLE%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEDoaCXVzLWVhc3QtMSJIMEYCIQCmFi6uq2Po1zHXCh61HlT1S7swWkOtueHhlXhMXIhdjQIhAPCoNohcU3UUZzpimmRZ3pGYEbgIwNY070lAx4iOi10mKvMECAIQARoMNjk5NzUzMzA5NzA1IgyOCqEAou1Q7xp4pZMq0AQVqTun00R%2F9E5dHElTP6GEeE485VqCGlifX%2FTulshalP9uWO%2B5%2FvvwdRMcx%2BvEdqrihkluGQNwkBmgp0zg9GSwmuH60QdyC50%2FLLhaYZPI3iTT1EL3e5n%2FCad%2FCL8jyCxr2tez7U4m0KYomJcyfo0OChY4gw4pYBAolj3kkZubTCj2Xp1zL7Ll1YMfGJ2TCnJcBR1kvk%2BETup3W8steUCMNGEcg0EZIaz%2FK4FgbEHD4uz8lALTNYefC3YMQVz98Z4ZliaZpGlOyzcd%2FLPhbTcWiCMhAw2a22cAt17zj%2FY3hnOLBKA0EDhlwKHAqA64K0O%2BJD%2FB0oFwdnmDvhrV%2B%2F4Zx0V7bKPGHE9DGyUF%2Bn%2FTp4o1UVqybYV5qMLol8xpu3NKeuJozPaNnQUhXOHo28Q9wa9w5NkPpVtY2n%2BBTEXud2ul6r7JcQa66J92dm%2F9F2SzIkRZzb55LBFy0eMFjP9QmQ84Sbu7zQ5MK%2FqZuWbJiP7BGabHfG22xb0Fne54NU3rZAyx1PMVClfQSyDThoKRKmljIEunXNvzotu7mXyvTbMp1%2BYBWLpbqHJurRQqiA4HKH7ke3P7FlC1wZncbnrDqzLSjJn%2FZdwUV32eI1h%2BBSS%2Fl08xVmO8RajPsgp%2FSTZc19mY07bzFNBltgKcfGiEY3Koz7pNNIZSu1%2B7uwnd0fYmHKRHwTpI90vvUU4WqOz2JVBlaU5HZjH3frwc8jO0HWx4Ana3CkrSr5vaVYBh0jG0L6XH%2FwtOxpmm2X%2BcHHaztzdKlsteIW95LI1GxsF7MMGt3tUGOpcBmpc6pEETfcQPEGLylqlgNP%2By6t42%2BApyQhxzIuk2yLv09WO%2BTTFo6EP0TxXwoYiY25KK%2BNDwcjOfBPjlzgjlFG%2F8B8Dg%2BSiRkD%2B6XE5SrSfdIC%2BBXMTxbpk%2FxJI10XqvbjLwj0BUPxJtWZmfbdk5y9DJxqFcjkqFhyFhPati86wh%2BUTmDOow4aNu8Afge4bJHoPWP5T8nA%3D%3D&Expires=1790420116) - Research and design specification September 2026 TITLE The Best Possible GUIUX for an Intelligent Vi...

2. [Implementation-Blueprint-for-a-Cybernetic-Autonomous-Coding-System.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/57152701/58fdbf9b-36fe-480d-97ad-5c0d1e2d1554/Implementation-Blueprint-for-a-Cybernetic-Autonomous-Coding-System.md?AWSAccessKeyId=ASIA2F3EMEYET6KNGEUP&Signature=0l4voAcf0rw%2FJNnyfo%2FAunJzOIU%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEDoaCXVzLWVhc3QtMSJIMEYCIQCmFi6uq2Po1zHXCh61HlT1S7swWkOtueHhlXhMXIhdjQIhAPCoNohcU3UUZzpimmRZ3pGYEbgIwNY070lAx4iOi10mKvMECAIQARoMNjk5NzUzMzA5NzA1IgyOCqEAou1Q7xp4pZMq0AQVqTun00R%2F9E5dHElTP6GEeE485VqCGlifX%2FTulshalP9uWO%2B5%2FvvwdRMcx%2BvEdqrihkluGQNwkBmgp0zg9GSwmuH60QdyC50%2FLLhaYZPI3iTT1EL3e5n%2FCad%2FCL8jyCxr2tez7U4m0KYomJcyfo0OChY4gw4pYBAolj3kkZubTCj2Xp1zL7Ll1YMfGJ2TCnJcBR1kvk%2BETup3W8steUCMNGEcg0EZIaz%2FK4FgbEHD4uz8lALTNYefC3YMQVz98Z4ZliaZpGlOyzcd%2FLPhbTcWiCMhAw2a22cAt17zj%2FY3hnOLBKA0EDhlwKHAqA64K0O%2BJD%2FB0oFwdnmDvhrV%2B%2F4Zx0V7bKPGHE9DGyUF%2Bn%2FTp4o1UVqybYV5qMLol8xpu3NKeuJozPaNnQUhXOHo28Q9wa9w5NkPpVtY2n%2BBTEXud2ul6r7JcQa66J92dm%2F9F2SzIkRZzb55LBFy0eMFjP9QmQ84Sbu7zQ5MK%2FqZuWbJiP7BGabHfG22xb0Fne54NU3rZAyx1PMVClfQSyDThoKRKmljIEunXNvzotu7mXyvTbMp1%2BYBWLpbqHJurRQqiA4HKH7ke3P7FlC1wZncbnrDqzLSjJn%2FZdwUV32eI1h%2BBSS%2Fl08xVmO8RajPsgp%2FSTZc19mY07bzFNBltgKcfGiEY3Koz7pNNIZSu1%2B7uwnd0fYmHKRHwTpI90vvUU4WqOz2JVBlaU5HZjH3frwc8jO0HWx4Ana3CkrSr5vaVYBh0jG0L6XH%2FwtOxpmm2X%2BcHHaztzdKlsteIW95LI1GxsF7MMGt3tUGOpcBmpc6pEETfcQPEGLylqlgNP%2By6t42%2BApyQhxzIuk2yLv09WO%2BTTFo6EP0TxXwoYiY25KK%2BNDwcjOfBPjlzgjlFG%2F8B8Dg%2BSiRkD%2B6XE5SrSfdIC%2BBXMTxbpk%2FxJI10XqvbjLwj0BUPxJtWZmfbdk5y9DJxqFcjkqFhyFhPati86wh%2BUTmDOow4aNu8Afge4bJHoPWP5T8nA%3D%3D&Expires=1790420116) - The strongest implementation is not seven LLM personas mapped one-to-one onto the Viable System Mode...

