# Implementation Blueprint for a Cybernetic Autonomous Coding System

## Executive recommendation

The strongest implementation is **not** seven LLM personas mapped one-to-one onto the Viable System Model. Build a **deterministic cybernetic control kernel** with five separable concerns—purpose and policy, durable execution, independent evidence, world-model state, and user-facing projection—then use models only inside bounded operational cells. This preserves the design’s core insight while avoiding “agent theater,” recursive bureaucracy, and a control plane whose safety depends on generated prose.

The first production-worthy release should be a **modular monolith with isolated workers**, not a distributed multi-agent platform. It should complete one vertical loop:

> Charter → bounded change → isolated build → independent check → product preview → signed candidate → user decision → reversible release

Only split services when measured load, trust boundaries, or team ownership requires it. The best initial target is a local-first Linux desktop application with a Python domain core, a PySide6/QML frontend, PostgreSQL plus pgvector for authoritative and semantic state, an append-only domain-event journal, a policy decision point, and sandboxed execution workers. PySide6 is Qt’s official Python binding; QML provides a declarative UI layer and Qt’s deployment tooling supports Linux, Windows, and macOS.[^1][^2][^3]

## What to preserve

The source design gets five important things right and they should remain architectural invariants:

- **The user governs purpose, not implementation.** Product purpose, beneficiaries, non-negotiables, acceptable consequences, and constitutional change remain human-authorized.
- **Claims require evidence.** “Ready,” “safe,” and “fixed” are projections over current evidence, never declarations emitted by the implementing model.
- **Execution and audit are separated.** The process that creates a change cannot confer independent verification on itself.
- **Unknown is a first-class state.** Missing or stale observation must never collapse into green.
- **Containment outranks completion.** Repeated failure, unexpected authority expansion, or threshold breach narrows autonomy rather than granting more tools.

These invariants align with current agent-security guidance: prominent risks include goal hijacking, tool misuse, delegated-identity abuse, memory poisoning, insecure inter-agent communication, cascading failures, and rogue-agent behavior. NIST’s generative-AI profile similarly recommends governing, mapping, measuring, and managing risks, including confabulation, privacy, information security, human–AI configuration, and component integration.[^4][^5][^6][^7]

## Simplify the VSM

Treat VSM names as **logical responsibilities**, not processes or agents.

| Function | Implementation | Must be deterministic? | May use an LLM? |
|---|---|---:|---:|
| Nomos | Versioned charter, policy bundles, authority grants | Yes for enforcement | Yes for drafting/explanation |
| Phronesis | Environmental ingest, forecasts, experiments | No | Yes |
| Kratos | Scheduler, budgets, release gates, capability issuance | Yes | Yes for recommendations only |
| Elechos | Independent checks, contradiction detection, evidence grading | Mixed | Yes, but never as sole proof |
| Syndesmos | Leases, dependencies, backpressure, conflict detection | Yes | Rarely |
| Energeia | Bounded mission workers | Mixed | Yes |
| Algedon | Threshold evaluator, containment playbooks, emergency UI | Yes | No for trigger/enforcement |

This mapping should exist at the project and mission levels, but most lower recursions should be **latent**. A small task does not need seven components; it needs the same guarantees through shared services. Instantiate a nested control unit only when a mission has independent resources, multiple concurrent workers, a meaningful environment, or a separate release decision.

## Reference architecture

```text
┌──────────────────────────────── Desktop application ───────────────────────────────┐
│ PySide6/QML                                                                       │
│ Cockpit · Product · Progress · Proof · Foresight · Charter · Live · Expert         │
│                       │ AG-UI-compatible projection stream                         │
└───────────────────────┼─────────────────────────────────────────────────────────────┘
                        ▼
┌──────────────────────────── Control kernel ────────────────────────────────────────┐
│ Command API │ Projector │ Policy PDP/PEP │ Workflow controller │ Release controller│
│ Charter     │ Claims    │ Budgets        │ Leases              │ Algedon            │
└──────────────┬───────────────┬───────────────────┬──────────────────────────────────┘
               │               │                   │
               ▼               ▼                   ▼
       Append-only events   PostgreSQL views   Artifact/provenance store
       + transactional      + pgvector         content-addressed, signed
       outbox
               │
               ▼
┌──────────────────────────── Isolated execution plane ──────────────────────────────┐
│ Mission worker │ model gateway │ MCP adapters │ shell/browser/test/build workers   │
│ per-task capability token │ network policy │ ephemeral secrets │ worktree/sandbox  │
└──────────────────────────────┬──────────────────────────────────────────────────────┘
                               ▼
                    Independent verification plane
             clean checkout · deterministic tests · scanners · journey probes
```

The frontend should consume **projections**, not raw workflow state. AG-UI already defines an ordered stream of typed lifecycle, text, tool, state, activity, and subagent events, making it a useful edge protocol for UI synchronization. Internally, domain events should use a CloudEvents-compatible envelope because CloudEvents standardizes event identity, source, version, type, payload, and transport bindings across services.[^8][^9][^10][^11][^12]

## Core domain model

Use a small set of durable aggregates. Do not begin with a universal knowledge graph.

| Aggregate | Purpose | Key invariants |
|---|---|---|
| `Project` | System in focus | One active charter version; explicit boundary and owner |
| `Charter` | Purpose and constitutional policy | Agent cannot self-approve a new version |
| `Mission` | One bounded outcome | Scope, budget, capability set, stop conditions required |
| `Claim` | Desired/inferred/observed proposition | Scope, version, environment, freshness, confidence required |
| `Evidence` | Observation supporting or contradicting a claim | Immutable result; producer and method recorded |
| `Artifact` | Code, build, image, report, screenshot, test output | Content digest and provenance required |
| `EssentialVariable` | Product condition with acceptable bands | Sensor, threshold, hysteresis, recovery action required |
| `Decision` | Consequential choice | Alternatives, authority, rationale, affected scope recorded |
| `CapabilityGrant` | Temporary permission | Least privilege, expiry, mission binding, revocation required |
| `Release` | Candidate promoted to an environment | Exact artifact digest must equal audited digest |
| `Incident` | Viability breach | Containment state, evidence preservation, recovery path required |

### Claim lifecycle

```text
PROPOSED → ACCEPTED_AS_REQUIREMENT → EVIDENCE_PENDING
         → SUPPORTED | CONTRADICTED | UNKNOWN | WAIVED
         → STALE when version, environment, or time invalidates evidence
```

A claim’s displayed status should be computed from evidence, not stored as a mutable label. Recommended fields are:

```json
{
  "claim_id": "clm_...",
  "project_id": "prj_...",
  "scope": {"artifact": "sha256:...", "environment": "preview"},
  "statement": "Only invited members can read private documents",
  "kind": "security_property",
  "impact": "critical",
  "source": {"type": "user", "id": "..."},
  "freshness_policy": "on_every_candidate",
  "required_evidence": ["journey", "authorization_matrix", "independent_probe"]
}
```

### Evidence model

Evidence is stronger when it is fresh, reproducible, relevant to the exact artifact, and independent of the implementation path. Store:

- Observation and expected result.
- Method and executable check definition.
- Exact input, environment, tool versions, and artifact digest.
- Producer identity and independence class.
- Timestamp and expiry rule.
- Raw artifact links and normalized finding.
- Claims supported or contradicted.
- Reproduction command or workflow reference.

Use a W3C PROV-inspired relationship model—entities, activities, and agents—because PROV was designed for interoperable provenance and supports attribution, processing steps, derivation, versioning, and reproducibility. For release artifacts, add SLSA provenance: SLSA requires provenance to identify outputs by digest and describe how they were produced, while stronger levels add authentic and unforgeable provenance plus build isolation.[^13][^14][^15][^16]

## Event architecture

### One event, three views

Separate three concepts that are often conflated:

1. **Domain events** are authoritative business facts such as `MissionAuthorized`, `ClaimContradicted`, or `SafeStateEntered`.
2. **Workflow history** reconstructs durable execution and retry decisions.
3. **Telemetry** diagnoses runtime behavior through traces, metrics, and logs.

Do not make OpenTelemetry the source of truth. Use it for causality and diagnosis. OpenTelemetry semantic conventions standardize names across traces, metrics, logs, events, resources, and profiles, improving correlation across components. Its developing GenAI conventions include agent invocation, planning, workflow, and tool-execution spans; mark these fields as versioned because the agent conventions remain under development.[^17][^18][^19][^20]

### Canonical event envelope

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
    "confidence": 0.99,
    "schema_version": 1
  }
}
```

Required engineering rules:

- Events are immutable; corrections append superseding events.
- Commands contain idempotency keys.
- A transactional outbox commits aggregate state and publication intent atomically.
- Consumers maintain checkpoints and tolerate duplicate delivery.
- Schemas are versioned; old readers must ignore unknown optional fields.
- Sensitive payloads are referenced by encrypted artifact IDs, not copied into events.
- Every user-visible status can name the events and evidence from which it was projected.

## Durable execution

Use a durable workflow engine once work survives process restarts, waits for humans, or spans multiple external systems. Temporal is a strong fit: workflow state is reconstructed through replay, activities have declarative retry policies, and nondeterministic work such as API and LLM calls belongs in activities rather than workflow logic. Temporal also recommends idempotent activities because an activity may execute more than once before the workflow records completion.[^21][^22][^23]

For a small local prototype, implement the same contract behind a lightweight state-machine adapter and keep migration possible. The boundary should be:

```python
class WorkflowPort(Protocol):
    async def start(self, definition, input, workflow_id): ...
    async def signal(self, workflow_id, signal, payload): ...
    async def query(self, workflow_id, projection): ...
    async def cancel(self, workflow_id, reason): ...
```

### Mission state machine

```text
DRAFT
  → FRAMED
  → AUTHORIZED
  → EXECUTING
  → CANDIDATE_READY
  → AUDITING
  → READY_TO_TRY
  → ACCEPTED
  → RELEASED
  → OBSERVING

Any active state → PAUSED | BLOCKED | CONTAINED | CANCELLED
CONTAINED → RECOVERING → RESTORED | EXPERT_ESCALATION
```

State transitions require predicates, not model assertions. For example, `AUDITING → READY_TO_TRY` requires the candidate digest to match every mandatory evidence item, zero open critical contradictions, required checks within freshness limits, and no essential variable outside policy.

### Retry taxonomy

- **Transient:** network interruption, provider throttling, worker crash; retry with bounded exponential backoff.
- **Deterministic defect:** compilation or test failure; return to diagnosis, not blind retry.
- **Policy denial:** never retry until authority or context changes.
- **Ambiguity:** request domain clarification if the user has unique information.
- **Oscillation:** repeated opposite patches or recurring failure signature; freeze affected scope and escalate strategy.
- **Unknown side effect:** contain and reconcile before another attempt.

Every side-effecting operation must have an idempotency key, a precondition, a postcondition, and where possible a compensation. Deployment, payment, messaging, deletion, credential changes, and publication must never be hidden inside an unconstrained model tool call.

## Policy and authority

### Enforce outside the model

Use a policy decision point and policy enforcement points around every capability boundary. OPA is designed to separate declarative policy decisions from enforcement and evaluates structured input supplied by an application. A request should include:[^24][^25]

```json
{
  "principal": "agent:energeia/mis_789",
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
  "evidence": ["approval:dec_456"]
}
```

The response should be more than allow/deny: `{decision, obligations, expiry, reason_code}`. Obligations can require redaction, an approval, read-only mode, an isolated worker, a maximum spend, or post-action verification.

### Capability rules

- Issue a unique machine identity per mission and worker.
- Mint short-lived, audience-bound capability tokens per tool and action.
- Do not pass the user’s broad credentials into workers.
- Default-deny filesystem, network, secrets, and external writes.
- Separate discovery from mutation permissions.
- Require step-up approval for irreversible, public, financial, identity, or high-impact data actions.
- Revoke all mission grants on pause, cancellation, containment, or charter change.
- Sign policy bundles and record their digest in decisions.

MCP authorization uses OAuth-based transport authorization, HTTPS, PKCE, token validation, and audience restrictions, but authorization is optional in MCP implementations; therefore, the host must not assume that connecting through MCP creates an adequate security boundary. Current MCP security guidance recommends progressive least-privilege scopes, strict redirect validation, safe URL handling, and validation of untrusted server content.[^26][^27][^28]

## Sandboxed execution

Use a tiered isolation model:

| Risk | Recommended isolation | Typical work |
|---|---|---|
| Low, local read-only | Bubblewrap + namespaces + seccomp + read-only mounts | Repository analysis |
| Medium, code execution | Rootless OCI container under gVisor | Tests, package builds, browsers |
| High or multi-tenant | Firecracker microVM + egress gateway | Untrusted generated code, release builds |

Bubblewrap constructs an empty mount namespace and exposes only explicitly mounted paths, but its own documentation emphasizes that it is a low-level tool rather than a complete sandbox policy. gVisor inserts a userspace application kernel and exposes an OCI runtime, reducing direct access to the host kernel. Firecracker provides VM boundaries and defense in depth, but egress must still be filtered at the host because Firecracker does not filter guest network traffic.[^29][^30][^31][^32][^33]

Each worker should receive:

- A clean Git worktree or checkout at a pinned commit.
- A writable overlay limited to the mission.
- No host home-directory mount.
- Empty environment except explicit variables.
- Ephemeral secret files mounted only when needed.
- CPU, memory, process, disk, wall-clock, and token budgets.
- Network deny-by-default with host, method, and byte quotas.
- Full stdout/stderr capture with secret redaction.
- A kill path controlled by the supervisor, not the worker.

## Storage strategy

### Authoritative store

Use PostgreSQL for projects, charters, missions, claims, evidence metadata, grants, decisions, releases, incidents, event offsets, and read-model projections. Row-level security can restrict rows visible or writable per user or tenant, and a table with RLS enabled but no applicable policy defaults to deny. Enable `FORCE ROW LEVEL SECURITY` for tenant-bearing tables and ensure application roles cannot use `BYPASSRLS`.[^34][^35]

### Semantic retrieval

Use pgvector initially rather than a separate vector database. It keeps embeddings beside relational metadata, supports exact and approximate search with HNSW and IVFFlat, and can combine vector search with PostgreSQL full-text search for hybrid retrieval. Keep retrieval metadata filters explicit; global approximate indexes may apply metadata predicates after ANN traversal, so benchmark filtered recall and use partitioning or partial indexes where isolation or selectivity requires it.[^36][^37]

### Graph projections

Do not make Neo4j mandatory in the first release. Add a graph database only after concrete traversals—cross-project entity history, causal dependency exploration, or relationship-heavy GraphRAG—prove awkward or slow in PostgreSQL. Neo4j is suited to graph traversal, hybrid retrieval, and persistent entity-oriented memory, but introducing it early creates another consistency and authorization surface.[^38][^39]

### Artifacts

Store large artifacts outside the relational database in a content-addressed directory or S3-compatible store:

```text
objects/sha256/ab/cd/<digest>
manifests/<artifact-id>.json
```

Sign promoted release manifests and verification bundles. Sigstore’s Cosign can sign and verify containers, release files, binaries, SBOMs, and generic blobs; its bundle can include the signature, certificate, and transparency-log proof.[^40][^41]

## Independent assurance

Elechos should use an **evidence ladder** rather than one generic “confidence” number.

| Grade | Evidence | Suitable claim |
|---|---|---|
| E0 | Model assertion only | Never user-facing as proven |
| E1 | Static observation | Style, structure, dependency inventory |
| E2 | Deterministic test in worker workspace | Local functional behavior |
| E3 | Clean-checkout reproduction | Build and installation claims |
| E4 | Independent journey/security probe against exact candidate | Release readiness |
| E5 | Canary/production observation | Live behavior |
| E6 | Longitudinal evidence | Reliability, cost, adoption, maintenance |

Independence dimensions should be explicit: separate process, clean state, distinct credentials, distinct implementation, different model family where model judgment is unavoidable, and production observation. More model votes are not equivalent to independent empirical evidence.

### Required test layers

- Domain-unit tests for policies, thresholds, and state transitions.
- Contract tests for adapters and typed event schemas.
- Property-based tests for authorization, budgeting, idempotency, and event reduction.
- Stateful tests for workflow transitions and crash/retry sequences; Hypothesis can generate sequences of state-machine actions and shrink failures to simpler reproductions.[^42][^43]
- Hermetic integration tests with fake model/tool providers.
- Golden journey tests from user-visible outcomes.
- Adversarial prompt-injection and tool-output tests.
- Sandbox escape, secret-leak, and egress tests.
- Restore drills and candidate-to-release digest checks.
- Accessibility and performance budgets on the product and the control UI.

Use TLA+ selectively for invariants where concurrency errors are catastrophic: “an unaudited digest is never released,” “a revoked capability cannot authorize a later action,” “only one active lease owns a mutable resource,” and “containment eventually stops all affected workers.” TLC explores reachable states of a finite model and reports a trace when an invariant fails.[^44][^45]

## Ecological frontend

Use PySide6/QML and treat the event-derived application state as the only frontend model. QML is declarative and integrates with Python through QtQml/QtQuick, while Qt Quick uses a retained scene graph that can render through multiple graphics backends.[^46][^47][^3]

### Default information architecture

- **Product:** live preview and core journeys.
- **Progress:** causal feedback loops, not token/tool activity.
- **Proof:** claims, supporting and contradicting evidence, scope, freshness.
- **Foresight:** upcoming disturbances and decision deadlines.
- **Charter:** purpose, affected parties, boundaries, authority.
- **Live:** releases, health, cost, recovery, incidents.
- **Expert:** diffs, commands, traces, policies, artifacts, raw events.

### UI projection contract

The UI should receive semantic events such as:

```json
{
  "type": "status.card.updated",
  "scope": "mission:mis_789",
  "now": "Independent access checks are running",
  "meaning": "The feature works locally but privacy is not yet proven",
  "next": "If all role combinations pass, the preview will become ready to try",
  "severity": "informational",
  "evidence_refs": ["evd_1", "evd_2"],
  "fresh_until": "2026-09-26T11:00:00Z"
}
```

Never synthesize this card directly from a model’s private reasoning. Generate it from state transitions, policy results, evidence, and bounded explanation templates. AG-UI can carry activity and shared-state updates, but the authoritative state stays in the control kernel.[^10][^48]

### Accessibility rules

- Every viability visualization has an equivalent ordered text view.
- Never encode state by color alone.
- Keyboard navigation covers every decision and emergency action.
- Focus order follows purpose → current state → boundaries → next action.
- Status changes use accessible announcements without flooding.
- Motion is optional and honors reduced-motion preferences.
- “Unknown,” “contradicted,” “stale,” and “outside policy” remain visually distinct.

## Observability and privacy

Instrument the control kernel, workers, policy decisions, model gateway, tool adapters, audits, and release path with OpenTelemetry. Trace a mission through model calls, tool calls, evidence generation, policy decisions, and UI projections using common resource and span attributes.[^49][^50]

Recommended high-value metrics:

- Mission lead time and queue time.
- Tool/model error and retry rates.
- Time spent outside each essential-variable envelope.
- Contradictions found before versus after release.
- Autonomous repair success and recurrence.
- Oscillation count and wasted execution cost.
- Evidence freshness and independent-evidence coverage.
- Capability denials, step-ups, and unused grants.
- Containment latency and restore success.
- User interruption count and decision latency.
- Prediction error for Phronesis forecasts.

Do not record prompts, tool payloads, file contents, or secrets by default. OpenTelemetry’s GenAI guidance can record prompt and tool content when enabled, which makes explicit opt-in, redaction, retention limits, and data classification necessary.[^51]

Use DORA’s delivery measures as supporting operational signals—change lead time, deployment frequency, failed-deployment recovery time, change fail rate, and deployment rework rate—but never as the product’s viability score. The system’s own measures must prioritize escaped intent defects, policy escapes, false-ready declarations, recovery, and user comprehension.[^52][^53]

## Learning without drift

Implement learning as a controlled promotion pipeline:

```text
Observation → candidate lesson → offline replay → benchmark
→ security review → canary policy/skill → monitored promotion → rollback option
```

Partition writable memory:

- Operational cells may write mission notes and candidate techniques.
- Auditors may write evidence and escaped-defect patterns.
- Foresight may write signals, hypotheses, and forecasts.
- Only a charter workflow with human authority may alter purpose or constitutional policy.
- No retrieved document, tool response, or model output may write long-term memory without validation and provenance.

Memory poisoning is a recognized agentic risk, alongside tool misuse and insecure delegation. Therefore every long-term memory item needs origin, scope, confidence, expiry, sensitivity, conflict state, and a revocation path.[^4]

Use feature flags for controlled rollout of routing rules, skills, policies, and UI projections. OpenFeature provides a vendor-neutral feature-flag API and separates application-facing evaluation from the underlying provider. Never use a flag to bypass a constitutional invariant; flags select among already-authorized behaviors.[^54][^55]

## Phased roadmap

### Phase 0 — Invariants and threat model

**Duration:** 2–3 weeks.

- Write a one-page charter schema and authority matrix.
- Define 10–15 safety and correctness invariants.
- Threat-model the runtime, memory, retrieval, tool registry, approvals, workers, and audit trail.
- Create an agent-specific abuse suite for prompt injection, memory poisoning, tool confusion, credential relay, and unsafe delegation.
- Specify event schemas and retention classes.

**Exit:** Every authority-changing action has an identified enforcement point; every critical invariant has a planned test or model.

### Phase 1 — Thin vertical slice

**Duration:** 5–8 weeks.

- PySide6/QML shell with Product, Progress, Proof, Charter, and Emergency surfaces.
- PostgreSQL schema, append-only events, transactional outbox, and projections.
- One mission workflow and one isolated worker.
- Git worktree lifecycle and Bubblewrap sandbox.
- Model gateway with one provider plus a deterministic fake.
- Policy decision point with mission-bound capability grants.
- Claim/evidence model and clean-checkout audit.
- Content-addressed artifacts and exact-digest preview.

**Demo:** A user requests one bounded UI change, watches outcome-level progress, tries the candidate, sees independent evidence, and can accept or restore without viewing code.

**Exit:** Every external action is attributable, authorized, replay-safe, and connected to a purpose and artifact digest.

### Phase 2 — Safety and release

**Duration:** 6–10 weeks.

- gVisor execution tier and network egress broker.
- Short-lived secret issuance and redaction.
- Release controller, canary, rollback, and safe-state playbooks.
- Signed manifests, SBOM, and SLSA-style provenance.
- Accessibility, security, dependency, and browser-journey audits.
- Algedon threshold engine and incident evidence preservation.
- Property/stateful testing and initial TLA+ models.

**Exit:** Fault-injection exercises demonstrate containment, candidate/release identity, restart recovery, token revocation, and rollback.

### Phase 3 — Parallel work and coordination

**Duration:** 8–12 weeks.

- Multiple bounded workers.
- File/symbol/schema/resource leases.
- Dependency-aware scheduling and backpressure.
- Conflict and oscillation detection.
- Typed agent handoff contracts.
- Budget allocation and model routing.
- Independent sampling of low-risk autonomous work.

**Exit:** Parallelism improves completed verified outcomes without increasing escaped defects, policy violations, or recovery time.

### Phase 4 — Foresight and controlled learning

**Duration:** 8–12 weeks, then continuous.

- Environmental signal ingestion and expiry.
- Forecasts with calibration and prediction-error tracking.
- Offline replay corpus from real missions.
- Candidate-skill generation and promotion pipeline.
- Feature-flagged policy and routing experiments.
- Viability-debt inventory and maintenance horizon.

**Exit:** At least one recurring task class improves on quality-adjusted cost or lead time with no degradation in charter compliance, security, or user comprehension.

## Acceptance gates

### Kernel gate

- All state changes arise from validated commands and immutable events.
- Every command is authenticated, authorized, scoped, and idempotent.
- Replay produces the same aggregate and projection state.
- Event schema compatibility is tested.
- Policy failure is fail-closed for mutation.

### Worker gate

- No inherited user credentials or home-directory access.
- Default-deny network with observable exceptions.
- Resource limits and supervisor kill work after restart.
- Outputs are untrusted until normalized and checked.
- Mission cancellation revokes capabilities and stops workers.

### Evidence gate

- User-visible “proven” claims name exact scope, artifact, environment, and freshness.
- Implementer-produced evidence is labeled non-independent.
- Contradictory evidence opens a conflict rather than averaging confidence.
- Candidate and audited artifact digests match.
- Critical claims cannot be waived by the implementing agent.

### UX gate

- In usability tests, nontechnical users can identify current state, major uncertainty, next likely action, and recovery option.
- No critical action requires reading code, logs, scanner output, or chain of thought.
- Every emergency card states containment already taken, visible impact, confidence, and safe choices.
- Every ecological visualization has keyboard and text equivalence.

### Release gate

- Clean build and independent journey suite pass.
- Artifact provenance and signature verify.
- Required claims have fresh evidence.
- No critical contradiction or policy exception is open.
- Rollback is tested against the candidate environment.
- Post-release sensors and automatic containment are active.

## Experiments that matter

| Hypothesis | Primary measure | Guardrail |
|---|---|---|
| Viability Cockpit improves comprehension | Correct answers to now/meaning/next scenarios | Time and cognitive load |
| Purpose-to-evidence links reduce drift | Escaped intent defects per mission | User interruption count |
| Independent audit reduces false-ready states | False-ready rate | Lead time and audit cost |
| Adaptive autonomy reduces burden | Decisions requested per mission | Policy escapes and incidents |
| Coordination reduces oscillation | Reversed patches and repeated failure signatures | Completed verified outcomes |
| Foresight prevents surprise work | Disturbances handled before impact | False alarms and ignored alerts |
| Controlled learning improves execution | Quality-adjusted cost and success by task class | Charter and safety regression |

Run shadow mode before autonomy increases: let the new controller recommend without acting, compare its decisions against actual outcomes, then canary by project and risk class. Smaller changes are easier to reason about and recover from, consistent with DORA’s recommendation to reduce batch size.[^52]

## Major anti-patterns

- **One LLM per VSM box:** expensive, slow, hard to secure, and falsely anthropomorphic.
- **Chat as system of record:** loses authority, provenance, schema, and replay semantics.
- **A universal confidence score:** allows excellent low-risk results to mask one catastrophic unknown.
- **Agent-created policy enforcement:** lets the same probabilistic component interpret and enforce its own limits.
- **Self-review as audit:** creates correlated failure and false assurance.
- **Raw MCP access from the model:** confuses protocol interoperability with authorization and containment.
- **Vector memory as truth:** similarity is not validity, authority, freshness, or permission.
- **Distributed services from day one:** multiplies failure modes before domain boundaries stabilize.
- **Visible multi-agent choreography:** exposes implementation noise rather than product state.
- **Autonomous charter evolution:** converts learning into purpose drift.
- **Retry everything:** amplifies deterministic defects, duplicated side effects, and cost.
- **Green by absence of telemetry:** turns blindness into confidence.

## Build order

If only ten implementation items can be funded, build them in this order:

1. Charter, authority, and invariant schemas.
2. Mission state machine with stop and containment paths.
3. Append-only domain events plus deterministic projections.
4. Capability-based policy enforcement outside the model.
5. Isolated execution worker with default-deny network and secrets.
6. Claim/evidence/provenance model tied to artifact digests.
7. Independent clean-checkout verification.
8. Product-facing cockpit with now–meaning–next projections.
9. Reversible release with signed artifact and tested rollback.
10. Evaluation harness for intent drift, false-ready states, policy escape, recovery, and user comprehension.

This order produces a system that is useful before it is complex, governable before it is highly autonomous, and testable before it begins learning from itself.

---

## References

1. [Qt for Python¶](https://doc.qt.io/qtforpython-6/)

2. [Tools - Qt for Python - Qt Documentation](https://doc.qt.io/qtforpython-6/tools/index.html)

3. [Python-QML integration - Qt for Python](https://doc.qt.io/qtforpython-6/tutorials/qmlintegration/qmlintegration.html)

4. [Addressing the OWASP Top 10 Risks in Agentic AI ...](https://www.microsoft.com/en-us/security/blog/2026/03/30/addressing-the-owasp-top-10-risks-in-agentic-ai-with-microsoft-copilot-studio/) - Agentic AI introduces new security risks. Learn how the OWASP Top 10 Risks for Agentic Applications ...

5. [[PDF] Artificial Intelligence Risk Management Framework: Generative ...](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) - AI RMF profiles assist organizations in deciding how to best manage AI risks in a manner that is wel...

6. [AI Risk Management Framework - NIST](https://www.nist.gov/itl/ai-risk-management-framework) - The profile can help organizations identify unique risks posed by generative AI and proposes actions...

7. [Agentic Security Initiative - OWASP Gen AI Security Project](https://genai.owasp.org/initiatives/agentic-security-initiative/) - What’s New Resources Learning Videos Blog Download Now Download Now Download Now Download Now Downlo...

8. [CloudEvents Specification](https://github.com/cloudevents/spec) - CloudEvents is a specification for describing event data in common formats to provide interoperabili...

9. [Azure Event Grid Namespaces - support for CloudEvents schema](https://learn.microsoft.com/en-us/azure/event-grid/namespaces-cloud-events) - Describes how Event Grid Namespaces support CloudEvents schema, which is an open source standard for...

10. [Events - Agent User Interaction Protocol](https://docs.ag-ui.com/concepts/events) - The Agent User Interaction Protocol uses a streaming event-based architecture. Events are the fundam...

11. [Specification - Agent User Interaction Protocol](https://docs.ag-ui.com/spec/1.0)

12. [AG-UI Overview - Agent User Interaction Protocol](https://docs.ag-ui.com/introduction) - AG-UI is an open, lightweight, event-based protocol that standardizes how AI agents connect to user-...

13. [PROV-Overview - dvcs.w3.org](https://dvcs.w3.org/hg/prov/raw-file/default/overview/prov-overview.html)

14. [PROV-DM: The PROV Data Model - W3C](https://www.w3.org/TR/prov-dm/)

15. [Build: Requirements for producing artifacts - SLSA.dev](https://slsa.dev/spec/v1.2/build-requirements) - This page covers the detailed technical requirements for producing artifacts at each SLSA level. The...

16. [Builddefinition](https://slsa.dev/spec/v1.2/build-provenance) - Description of SLSA build provenance specification for verifying where, when, and how something was ...

17. [General Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/general/) - This document defines general Semantic Conventions for spans, metrics, logs and events. The followin...

18. [OpenTelemetry semantic conventions 1.44.0](https://opentelemetry.io/docs/specs/semconv/) - The Semantic Conventions define a common set of (semantic) attributes which provide meaning to data ...

19. [Semantic Conventions for GenAI agent and framework spans - GitHub](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md) - Contribute to open-telemetry/semantic-conventions-genai development by creating an account on GitHub...

20. [open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) - Contribute to open-telemetry/semantic-conventions-genai development by creating an account on GitHub...

21. [What is a Temporal Retry Policy?](https://docs.temporal.io/encyclopedia/retry-policies) - Optimize your Workflow and Activity Task Executions with a custom Retry Policy on Temporal. Understa...

22. [Activity Definition | Temporal Documentation](https://docs.temporal.io/activity-definition) - Learn how to define a Temporal Activity; Activity Types, parameters, constraints, idempotency, and r...

23. [Checking Workflow Execution...](https://docs.temporal.io/workflow-execution) - A Temporal Workflow Execution is a durable, reliable, and scalable function execution and the main u...

24. [Open Policy Agent (OPA)](https://www.openpolicyagent.org/docs) - The Open Policy Agent (OPA, pronounced "oh-pa") is an open source,

25. [Open Policy Agent - Homepage | Open Policy Agent](https://www.openpolicyagent.org/)

26. [Authorization - What is the Model Context Protocol (MCP)?](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

27. [Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)

28. [Security Best Practices - What is the Model Context Protocol (MCP)?](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)

29. [Introduction to gVisor security](https://gvisor.dev/docs/architecture_guide/intro/)

30. [README.md - containers/bubblewrap](https://github.com/containers/bubblewrap/blob/main/README.md) - Low-level unprivileged sandboxing tool used by Flatpak and similar projects - containers/bubblewrap

31. [containers/bubblewrap: Low-level unprivileged sandboxing ... - GitHub](https://github.com/containers/bubblewrap) - Low-level unprivileged sandboxing tool used by Flatpak and similar projects - containers/bubblewrap

32. [GitHub - google/gvisor: Application Kernel for Containers](https://github.com/google/gvisor) - Application Kernel for Containers. Contribute to google/gvisor development by creating an account on...

33. [firecracker/docs/design.md at main - GitHub](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md) - Secure and fast microVMs for serverless computing. - firecracker-microvm/firecracker

34. [5.9. Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) - 5.9. Row Security Policies # In addition to the SQL-standard privilege system available through GRAN...

35. [CREATE POLICY](https://www.postgresql.org/docs/current/sql-createpolicy.html) - CREATE POLICY CREATE POLICY — define a new row-level security policy for a table Synopsis CREATE POL...

36. [GitHub - pgvector/pgvector: Open-source vector similarity ...](https://github.com/pgvector/pgvector) - Open-source vector similarity search for Postgres. Contribute to pgvector/pgvector development by cr...

37. [Feature Request: Filtered HNSW / Segment-Level Indexes ...](https://github.com/pgvector/pgvector/issues/980) - Description Many modern vector databases support efficient vector search with metadata filters by ma...

38. [Neo4j](https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/context-providers/neo4j) - Use Neo4j context providers for GraphRAG over existing knowledge graphs and persistent agent memory.

39. [Neo4j Agent Memory](https://neo4j.com/labs/agent-memory/) - Neo4j Agent Memory gives your agent three distinct memory layers — all connected in a single knowled...

40. [Overview](https://docs.sigstore.dev/) - Documentation for Sigstore

41. [Signing Blobs - Sigstore](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/) - You can use Cosign for signing and verifying standard files and blobs (or binary large objects), in ...

42. [Stateful tests - Hypothesis 6.168.0 documentation](https://hypothesis.readthedocs.io/en/latest/stateful.html)

43. [hypothesis/hypothesis-python/docs/index.rst at master · HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis/blob/master/hypothesis-python/docs/index.rst) - The property-based testing library for Python. Contribute to HypothesisWorks/hypothesis development ...

44. [Welcome - TLA+ By Example](https://learning.tlapl.us/intro/platform/) - Learn TLA+ specifications through interactive examples in your browser

45. [Behind the Scenes: Sleeping soundly with the help of TLA+](https://blogs.oracle.com/cloud-infrastructure/sleeping-soundly-with-the-help-of-tla) - Oracle Cloud Infrastructure (OCI)’s verification team uses formal methods—in particular, a language ...

46. [PySide6.QtQml - Qt for Python](https://doc.qt.io/qtforpython-6/PySide6/QtQml/index.html)

47. [Qt Quick Scene Graph - Qt Documentation](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html)

48. [Agents - Agent User Interaction Protocol](https://docs.ag-ui.com/concepts/agents)

49. [Trace semantic conventions - OpenTelemetry](https://opentelemetry.io/docs/specs/semconv/general/trace/) - Status: Mixed In OpenTelemetry spans can be created freely and it’s up to the implementer to annotat...

50. [OpenTelemetry - Observability Stack - OpenSearch](https://observability.opensearch.org/docs/send-data/opentelemetry/) - Understand OpenTelemetry signals, protocols, and how OTel integrates with the observability stack

51. [Explore traces](https://opentelemetry.io/blog/2026/genai-observability/) - Your AI agent just took 45 seconds to answer a simple question. Was it the model? A slow tool call? ...

52. [DORA's software delivery performance metrics](https://dora.dev/guides/dora-metrics/) - DORA is a long running research program that seeks to understand the capabilities that drive softwar...

53. [Refining Definitions...](https://dora.dev/insights/dora-metrics-history/) - DORA is a long running research program that seeks to understand the capabilities that drive softwar...

54. [Introduction | OpenFeature](https://openfeature.dev/docs/reference/intro/) - OpenFeature is an open specification that provides a vendor-agnostic, community-driven API for featu...

55. [open-feature/spec: OpenFeature specification](https://github.com/open-feature/spec) - OpenFeature specification. Contribute to open-feature/spec development by creating an account on Git...

