# Kosmos-LMS Architecture Report

## Executive design

    Kosmos-LMS should be structured across three independent dimensions:

1.  **`VSM functions`**` ``—```` the recursive cybernetic governance roles.`

2.  **`Technical architecture`**` ``—```` the shared substrate, integration layer, and middleware.`

3.  **`Capability subsystems`**` ``—```` deployable domain systems that may support multiple VSM functions.`

<!-- -->

    The governing rule is:

**`LLMs investigate, interpret, plan, critique, and propose; deterministic systems authorize, execute, verify, persist, and promote consequential work.`**

## Final nomenclature

### VSM functions

|  |  |  |
|----|----|----|
| **`VSM role`** | **`Designation`** | **`Core responsibility`** |
| `S1` | **`Praxis`** | `Primary operational work and value production` |
| `S2` | **`Harmonia`** | `Coordination, synchronization, deconfliction, anti-oscillation` |
| `S3` | **`Kybernesis`** | `Operational control, resource bargains, workflow governance` |
| `S3*` | **`Euthyna`** | `Independent inspection, audit, accountability, verification` |
| `S4` | **`Pronoia`** | `Environmental intelligence, foresight, adaptation, strategy` |
| `S5` | **`Telos`** | `Purpose, identity, constitution, values, ultimate policy` |
| `Algedonic Channel` | **`Sema`** | `Exceptional viability signals and direct escalation` |

### Architecture

|  |  |  |
|----|----|----|
| **`Layer`** | **`Designation`** | **`Core responsibility`** |
| `Shared/common infrastructure` | **`Koinon`** | `Kernel, trust, state, workflows, artifacts, observability` |
| `Integration layer` | **`Syndesmos`** | `Contracts, schemas, interoperability, integration semantics` |
| `Middleware` | **`Mesiteia`** | `Transport, routing, brokering, gateways, protocol mediation` |

### Major subsystems

|  |  |
|----|----|
| **`Subsystem`** | **`Responsibility`** |
| **`Zetesis`** | `Deep research` |
| **`Synedrion`** | `Structured multi-model council` |
| **`Gnosis`** | `Knowledge management and knowledge bases` |
| **`Poros`** | `Resource management` |
| **`Epimeleia`** | `Agent lifecycle and runtime management` |
| **`Tekton`** | `Autonomous software engineering and app construction` |
| **`Axiomeon`** | `Axiom discovery, formalization, testing, and governance` |
| **`Holon`** | `Ontologies, systems models, and GUToE construction` |
| **`Agora`** | `A2A discovery, discussion, negotiation, and collaboration forum` |
| **`Asphaleia`** | `Security, identity, capabilities, secrets, trust, integrity` |
| **`Noesis`** | `Model registry, inference management, and routing` |

### Koinon domains

|                      |                                                    |
|----------------------|----------------------------------------------------|
| **`Domain`**         | **`Responsibility`**                               |
| **`Mneme`**          | `Memory and persistence`                           |
| **`Aisthesis`**      | `Observability, telemetry, traces, and sensorium`  |
| `Workflow engine`    | `Durable orchestration and recovery`               |
| `Artifact service`   | `Immutable, content-addressed artifact custody`    |
| `Provenance service` | `Lineage, signatures, hashes, and reproducibility` |

# VSM governance model

## Praxis — operations

    Praxis is the S1 operational field: the systems that directly perform work and create value.

    Praxis contains:

- `Zetesis research operations.`

- `Tekton software engineering.`

- `Holon ontology and theory construction.`

- `Gnosis knowledge-curation operations.`

- `Axiomeon axiom-engineering operations.`

- `Future domain systems such as Hygieia.`

`Praxis is a `**`category of operational systems`**`, not one central application or agent.`

    Every major Praxis subsystem should recursively contain:

- `Local planning.`

- `Domain execution.`

- `Tool use.`

- `Local coordination.`

- `Budget and lifecycle control.`

- `Verification.`

- `Audit hooks.`

- `Environmental observation.`

- `Policy interpretation.`

- `Sema escalation.`

## Harmonia — coordination

    Harmonia performs S2 coordination among autonomous Praxis systems.

    It should manage:

- `Task dependencies.`

- `Shared resource contention.`

- `Repository and artifact leases.`

- `Concurrency limits.`

- `Backpressure.`

- `Scheduling cadence.`

- `Duplicate-work detection.`

- `Deadlock detection.`

- `Oscillation detection.`

- `Context exchange.`

- `Cross-plugin synchronization.`

`Harmonia does `**`not`**` define priorities, approve policy exceptions, promote code, or decide purpose.`

## Kybernesis — operational control

    Kybernesis is the S3 controller for the present internal system.

    It owns:

- `Authoritative workflow state.`

- `Operational contracts.`

- `Work prioritization.`

- `Resource bargain approval.`

- `Acceptance criteria.`

- `Artifact promotion.`

- `Deployment authorization.`

- `Rollback.`

- `Incident coordination.`

- `Current-state optimization.`

- `Service-level commitments.`

<!-- -->

    Core components:

    Kybernesis

    ├── Operations Controller

    ├── Workflow Lifecycle Controller

    ├── Portfolio Workflow

    ├── Resource Controller

    ├── Acceptance Gate

    ├── Promotion Gate

    ├── Change-Control Workflow

    ├── Incident Workflow

    ├── Recovery Coordinator

    ├── Rollback Service

    ├── Commitment Registry

    └── Operational State Projector

## Euthyna — independent audit

    Euthyna is the S3* direct inspection channel. It should test claims independently rather than trusting normal operational reporting.

    It owns:

- `Compliance verification.`

- `Clean-room builds and testing.`

- `Evidence validation.`

- `Source verification.`

- `Artifact provenance.`

- `Security review.`

- `Red-team exercises.`

- `Resource-account reconciliation.`

- `Drift detection.`

- `Regression checks.`

- `Random inspection.`

- `Remediation verification.`

<!-- -->

    Euthyna must have:

- `Separate contexts from producers.`

- `Separate execution environments where feasible.`

- `Direct access to artifacts and evidence.`

- `Independent telemetry.`

- `Tamper-evident audit records.`

- `Direct escalation routes to Kybernesis, Telos, and Sema.`

## Pronoia — intelligence and foresight

    Pronoia handles the wider environment and future adaptation.

    It should contain:

- `Environmental Scanning Agent.`

- `Strategic Research Agent.`

- `Technology Scouting Agent.`

- `Scenario-Planning Agent.`

- `Systems Architecture Agent.`

- `Threat-Modeling Agent.`

- `Opportunity Analysis Agent.`

- `Strategic Critic Agent.`

- `Alternative-Generation Agent.`

- `Experiment-Design Agent.`

- `Strategic Synthesis Function.`

<!-- -->

    Pronoia can recommend, simulate, and conduct sandboxed experiments. It cannot deploy changes directly.

## Telos — policy and identity

    Telos is the S5 constitutional layer. It establishes what Kosmos is, what it is for, what it may not become, and where human authority remains final.

    Telos owns:

- `Constitutional documents.`

- `Identity and purpose statements.`

- `Values and prohibitions.`

- `Policy hierarchy.`

- `Capability ceilings.`

- `Human authorization.`

- `Constitutional amendment workflow.`

- `Exception policy.`

- `S3-S4 arbitration.`

- `Long-term coherence.`

<!-- -->

    Its authority chain should be:

    Human authority

            ↓

    Signed constitutional artifacts

            ↓

    Deterministic policy engine

            ↓

    Bounded interpretation functions

            ↓

    Authorization workflow

            ↓

    Capability enforcement

## Sema — exceptional signals

    Sema carries exceptional pain or opportunity signals that bypass normal communication pathways.

    Sema includes:

- `Threshold Monitor.`

- `Integrity Tripwire.`

- `Anomaly Detector.`

- `Severity Classifier.`

- `Circuit Breaker.`

- `Escalation Router.`

- `Incident Snapshotter.`

- `Recovery Monitor.`

- `Alert Deduplicator.`

- `Tamper-evident Sema Ledger.`

<!-- -->

    Sema should trigger on events such as:

- `Credential exposure.`

- `Sandbox escape.`

- `Gate or policy tampering.`

- `Unauthorized self-modification.`

- `Corrupted provenance.`

- `Irrecoverable data-loss risk.`

- `Runaway resource consumption.`

- `Severe security compromise.`

- `Perishable, unusually high-value opportunity.`

<!-- -->

    It must function even if LLM inference is unavailable.

# Koinon architecture

## Koinon

    Koinon is the common substrate, not a competing domain plugin.

    It owns the trusted shared mechanisms:

    Koinon

    ├── Kernel and lifecycle

    ├── Contracts and schemas

    ├── Durable workflows

    ├── Event log

    ├── Operational state

    ├── Artifact service

    ├── Provenance service

    ├── Plugin registry

    ├── Configuration

    ├── Secret interfaces

    ├── Identity and capability enforcement

    ├── Sandbox provisioning

    ├── Observability

    ├── Runtime adapters

    ├── Sema transport

    ├── Mneme

    ├── Aisthesis

    └── Syndesmos

    Koinon supplies mechanisms. VSM elements govern how those mechanisms are used.

## Syndesmos

    Syndesmos is the integration layer. It defines the semantic and contractual framework through which subsystems interoperate.

    It owns:

- `Canonical schemas.`

- `Commands and events.`

- `Compatibility rules.`

- `Service discovery.`

- `Capability discovery.`

- `Adapter contracts.`

- `Version negotiation.`

- `Dependency semantics.`

- `Cross-plugin routing.`

- `Protocol translation rules.`

- `Integration validation.`

<!-- -->

    Syndesmos is broader than middleware because it includes architecture, meaning, contracts, and compatibility—not merely transport.

## Mesiteia

    Mesiteia is the middleware infrastructure that implements parts of Syndesmos.

    It owns:

- `Event bus.`

- `Message broker.`

- `API gateway.`

- `Request/reply transport.`

- `Pub/sub transport.`

- `A2A transport.`

- `MCP transport.`

- `Service discovery transport.`

- `Serialization.`

- `Correlation identifiers.`

- `Delivery retries.`

- `Transport authentication.`

- `Rate limits.`

- `Backpressure.`

<!-- -->

    The relationship is:

    Koinon

    └── Syndesmos

        ├── Contracts

        ├── Schemas

        ├── Integration semantics

        ├── Adapters

        └── Mesiteia

            ├── Event transport

            ├── Message brokering

            ├── API gateway

            ├── A2A

            └── MCP

# Capability systems

## Zetesis

`Zetesis is a deep-research `**`system`**`, not one ``“````research agent.``”```

    Zetesis

    ├── Research Agent

    ├── Question Analysis Function

    ├── Research Planning Function

    ├── Query Generation Function

    ├── Source Discovery Agent

    ├── Source Acquisition Workflow

    ├── Source Capture Service

    ├── Evidence Extraction Function

    ├── Source Evaluation Function

    ├── Fact-Checking Workflow

    ├── Contradiction Mapping Function

    ├── Citation Verification Gate

    ├── Coverage Audit Workflow

    ├── Report Composition Workflow

    └── Research Provenance Service

    Zetesis should provide evidence-backed research to Pronoia, Gnosis, Holon, Synedrion, Euthyna, and human users.

## Synedrion

    Synedrion is the structured multi-model council.

    It should support:

- `Independent first-pass analysis.`

- `Diverse model assignments.`

- `Domain-specialist delegates.`

- `Adversarial critique.`

- `Proposal defense.`

- `Devil``’````s advocate positions.`

- `Evidence mapping.`

- `Agreement and disagreement analysis.`

- `Confidence calibration.`

- `Consensus synthesis.`

- `Minority reports.`

<!-- -->

    Synedrion’s outputs are advisory. It cannot become a binding authority through model voting.

## Gnosis

    Gnosis manages semantic, curated, retrievable knowledge with provenance.

    It should include:

- `Source ingestion.`

- `Parsing and normalization.`

- `Entity extraction.`

- `Relation extraction.`

- `Ontology alignment.`

- `Deduplication.`

- `Lexical indexing.`

- `Vector indexing.`

- `Graph indexing.`

- `Retrieval.`

- `Reranking.`

- `Contradiction detection.`

- `Temporal knowledge.`

- `Knowledge curation.`

- `Trust assessment.`

- `Staleness detection.`

- `Access-controlled projections.`

`Gnosis is `**`not every database`**`.`

|                          |                            |
|--------------------------|----------------------------|
| **`Data`**               | **`Primary owner`**        |
| `Current workflow state` | `Koinon/Mneme`             |
| `Event history`          | `Koinon/Mneme`             |
| `Semantic knowledge`     | `Gnosis`                   |
| `Research captures`      | `Zetesis`                  |
| `Audit evidence`         | `Euthyna`                  |
| `Resource telemetry`     | `Poros/Aisthesis`          |
| `Agent sessions`         | `Epimeleia/Mneme`          |
| `Constitutional records` | `Telos`                    |
| `Artifacts`              | `Koinon artifact service`  |
| `Ontologies`             | `Holon, indexed by Gnosis` |

## Poros

    Poros manages resources, capacity, budgeting, allocation, reclamation, and operating margins.

    It should cover:

- `GPU.`

- `VRAM.`

- `CPU.`

- `RAM.`

- `Storage.`

- `Network.`

- `Inference capacity.`

- `API quotas.`

- `Token and context budgets.`

- `Financial limits.`

- `Energy use.`

- `Thermal limits.`

- `Reservation leases.`

- `Capacity forecasting.`

- `Resource reclamation.`

- `Retention policy.`

<!-- -->

    The authority separation is:

    Poros measures and recommends

    Kybernesis authorizes

    Harmonia coordinates access

    Sema escalates dangerous conditions

## Epimeleia

    Epimeleia manages the lifecycle of cognitive agents and their runtime environments.

    It owns:

    Epimeleia

    ├── Agent Manifest Registry

    ├── Agent Factory

    ├── Hermes Runtime Adapter

    ├── Future Runtime Adapters

    ├── Capability Broker

    ├── Context Assembler

    ├── Skill Resolver

    ├── Toolset Resolver

    ├── Model Assignment Client

    ├── Session Registry

    ├── Lifecycle Controller

    ├── Checkpoint Manager

    ├── Recovery Workflow

    ├── Termination Controller

    ├── Result Normalizer

    └── Agent Telemetry Emitter

    Epimeleia should treat Hermes as a cognitive backend. It must retain external control of identity, permissions, lifecycle, state, resource envelope, telemetry, and termination.

## Tekton

    Tekton is the autonomous software-engineering system. It wraps OpenHands for repository-level work but retains Kosmos governance outside OpenHands.

    Tekton

    ├── Specification Analysis Function

    ├── Clarification Agent

    ├── Repository Cartography Function

    ├── Architecture Planning Agent

    ├── Task Decomposition Function

    ├── OpenHands Adapter

    ├── Coding Workers

    ├── Test Design Function

    ├── Test Worker

    ├── Static Analysis Worker

    ├── Code Review Function

    ├── Security Review Function

    ├── Performance Analysis Function

    ├── Documentation Function

    ├── Quality Gate

    ├── Clean-Room Build Worker

    ├── Scope Audit

    ├── Integration Workflow

    ├── Promotion Workflow

    ├── Release Service

    └── Rollback Service

### Non-bypassable coding governance

    Agent produces candidate commit

            ↓

    Protected quality gate runs

            ↓

    Formatting and linting

            ↓

    Type checking

            ↓

    Unit and integration tests

            ↓

    Architecture and security rules

            ↓

    Clean-room build and test

            ↓

    Euthyna review when required

            ↓

    Kybernesis accepts or rejects

    The coding agent may repair code, but cannot:

- `Mark its own work as accepted.`

- `Skip validation.`

- `Alter the authoritative gate.`

- `Disable tests silently.`

- `Weaken policy files.`

- `Push unverified work.`

## Axiomeon

    Axiomeon is an intentional Kosmos neologism for axiom engineering.

    It should:

- `Extract assumptions.`

- `Identify implicit premises.`

- `Formalize candidate axioms.`

- `Classify axioms.`

- `Map dependencies.`

- `Detect contradictions.`

- `Test independence.`

- `Explore consequences.`

- `Generate counterexamples.`

- `Compile invariants into executable tests.`

- `Maintain provenance.`

- `Draft amendments.`

<!-- -->

    Its governance flow is:

    Axiomeon proposes

            ↓

    Pronoia models consequences

            ↓

    Synedrion critiques

            ↓

    Euthyna verifies

            ↓

    Telos accepts, rejects, or requests revision

    Axiomeon may not make its own axioms constitutional.

## Holon

    Holon builds and compares ontologies, causal models, systems models, and GUToE candidates.

    It should include:

- `Ontology Engineering Function.`

- `Ontology Alignment Function.`

- `Cross-Domain Mapping Agent.`

- `Theory Generation Agent.`

- `Theory Comparison Workflow.`

- `Causal Modeler.`

- `Systems Modeler.`

- `Mathematical Formalization Function.`

- `Simulation Workflow.`

- `Prediction Generator.`

- `Falsification Designer.`

- `Anomaly Curator.`

- `Contradiction Mapper.`

- `Explanatory-Gap Detector.`

- `Theory Version Service.`

- `Pluralism Guard.`

<!-- -->

    Holon must preserve competing theories rather than collapse them into a single mutable truth system.

## Agora

    Agora replaces Ekklesia as the open A2A communication, exchange, discovery, and negotiation forum.

    It should provide:

- `Participant discovery.`

- `Capability discovery.`

- `Topic spaces.`

- `Informal discussion.`

- `Proposal publication.`

- `Evidence attachment.`

- `Requests for help.`

- `Collaboration discovery.`

- `Negotiation.`

- `Informal consensus indications.`

- `Dissent recording.`

- `Escalation into formal workflows.`

<!-- -->

    Agora is not:

- `Mesiteia.`

- `The event bus.`

- `Synedrion.`

- `Kybernesis.`

- `Telos.`

- `A binding voting body.`

- `A durable workflow engine.`

`If you later need a formal jurisdictional assembly with motions, quorum, and binding decisions, you can restore `**`Ekklesia`**` as a separate governance subsystem above Agora.`

## Asphaleia

    Asphaleia is the security and trust subsystem.

    It should manage:

- `Identity.`

- `Authentication.`

- `Authorization.`

- `Capability tokens.`

- `Secret brokerage.`

- `Encryption keys.`

- `Data classification.`

- `Access-control policy.`

- `Sandbox policy.`

- `Network policy.`

- `Dependency verification.`

- `Supply-chain verification.`

- `Integrity monitoring.`

- `Credential rotation.`

- `Security event handling.`

- `Tampering detection.`

<!-- -->

    The central rule:

**`All code, agents, plugins, tools, and hooks operate through narrow, explicit capabilities``—````not ambient authority.`**

## Noesis

    Noesis owns model and inference management.

    It should manage:

- `Model registry.`

- `Quantization registry.`

- `Inference providers.`

- `vLLM adapters.`

- `Local backend adapters.`

- `Model-routing policy.`

- `Fallback chains.`

- `Context-window policy.`

- `Sampling profiles.`

- `Tool-calling compatibility.`

- `Health checks.`

- `Load balancing.`

- `Benchmark profiles.`

- `Cost and latency profiles.`

- `Model provenance.`

- `Model deprecation.`

<!-- -->

    The relationship is:

    Epimeleia requests cognitive work

    Noesis selects an eligible model

    Poros grants a resource envelope

    Asphaleia validates access

    Mesiteia routes the inference request

    Aisthesis records telemetry

# Koinon domains

## Mneme

    Mneme is the persistence and memory domain.

|                         |                                     |
|-------------------------|-------------------------------------|
| **`Memory type`**       | **`Kosmos example`**                |
| `Working memory`        | `Current task context`              |
| `Episodic memory`       | `Past tasks, runs, incidents`       |
| `Semantic memory`       | `Curated knowledge in Gnosis`       |
| `Procedural memory`     | `Skills and validated procedures`   |
| `Operational memory`    | `Active workflow and service state` |
| `Constitutional memory` | `Policies and amendment history`    |
| `Audit memory`          | `Findings and remediation`          |
| `Resource memory`       | `Usage and allocation history`      |

    Mneme provides durable storage mechanisms. Gnosis provides knowledge curation and semantic retrieval.

## Aisthesis

    Aisthesis is the sensorium and observability domain.

    It should collect:

- `Logs.`

- `Metrics.`

- `Traces.`

- `Agent trajectories.`

- `Tool invocations.`

- `Inference telemetry.`

- `Workflow transitions.`

- `System health.`

- `Resource telemetry.`

- `User interaction events.`

- `External environmental observations.`

- `Timestamps and correlation IDs.`

<!-- -->

    The division is:

    Aisthesis observes

    Poros accounts

    Euthyna audits

    Kybernesis controls

    Sema escalates

    Gnosis learns

## Workflow engine

    The Koinon workflow engine should provide:

- `Durable execution.`

- `Idempotent commands.`

- `Checkpointing.`

- `Resumption.`

- `Timeouts.`

- `Cancellation.`

- `Retry policy.`

- `Compensation.`

- `Versioning.`

- `Human approvals.`

- `Event-driven continuation.`

- `Restart recovery.`

- `Typed inputs and outputs.`

<!-- -->

    Agents can operate inside workflows but must not replace workflow state machines.

## Artifact service

    The artifact service should provide:

- `Content-addressed storage.`

- `Immutable accepted versions.`

- `Hashes.`

- `Signatures.`

- `Schema typing.`

- `Producer identity.`

- `Workflow identity.`

- `Source lineage.`

- `Promotion stages.`

- `Retention policy.`

- `Access policy.`

- `Reproduction metadata.`

# Agent taxonomy

`Use `**`Agent`**` only for a goal-directed LLM loop that dynamically selects actions, tools, delegation, or stopping conditions.`

|                   |                                              |
|-------------------|----------------------------------------------|
| **`Designation`** | **`Meaning`**                                |
| `Agent`           | `LLM controls dynamic reasoning/action loop` |
| `Function`        | `One bounded LLM inference`                  |
| `Workflow`        | `Code controls a multistep process`          |
| `Controller`      | `Authoritative state-transition owner`       |
| `Service`         | `Persistent deterministic capability`        |
| `Tool`            | `Bounded executable operation`               |
| `Worker`          | `Sandboxed task executor`                    |
| `Monitor`         | `Continuous observation`                     |
| `Detector`        | `Recognition of defined conditions`          |
| `Gate`            | `Authoritative pass/fail decision`           |
| `Registry`        | `Definition and identity resolver`           |
| `Hook`            | `Typed response to an event`                 |
| `Adapter`         | `External-interface translator`              |

    Decision rule:

    Can deterministic code solve it reliably?

    ├── Yes → tool, service, monitor, gate, worker, or workflow

    └── No

        └── Is one bounded semantic judgment sufficient?

            ├── Yes → cognitive function

            └── No

                └── Must the model dynamically choose actions?

                    ├── Yes → agent

                    └── No → hybrid workflow or human decision

# Runtime allocation

## Hermes via Epimeleia

    Use Hermes for:

- `Research.`

- `Planning.`

- `Semantic interpretation.`

- `Critique.`

- `Synthesis.`

- `Negotiation.`

- `Open-ended tool use.`

- `Research agents.`

- `Strategy agents.`

- `Synedrion delegates.`

- `Agora participants.`

- `Red-team agents.`

- `Dynamic troubleshooting.`

## OpenHands via Tekton

    Use OpenHands for:

- `Repository navigation.`

- `Code editing.`

- `Refactoring.`

- `Debugging.`

- `Migration.`

- `Test implementation.`

- `Code/test iteration.`

## Custom deterministic implementation

    Implement in Koinon or subsystem services:

- `Policy enforcement.`

- `Capabilities.`

- `Secrets.`

- `Authentication.`

- `Artifact custody.`

- `Workflow durability.`

- `Leases.`

- `Scheduling.`

- `Event routing.`

- `Resource accounting.`

- `Quality gates.`

- `Test execution.`

- `Promotion.`

- `Rollback.`

- `Audit storage.`

- `Sema.`

- `Observability.`

- `Model-serving operations.`

- `Transport and middleware.`

# Extension organization

    kosmos-lms/

    ├── koinon/

    │   ├── src/koinon/

    │   │   ├── kernel/

    │   │   ├── contracts/

    │   │   ├── workflows/

    │   │   ├── policy/

    │   │   ├── capabilities/

    │   │   ├── tools/

    │   │   ├── hooks/

    │   │   ├── artifacts/

    │   │   ├── mneme/

    │   │   └── aisthesis/

    │   └── tests/

    │

    ├── plugins/

    │   ├── zetesis/

    │   ├── synedrion/

    │   ├── gnosis/

    │   ├── poros/

    │   ├── epimeleia/

    │   ├── tekton/

    │   ├── axiomeon/

    │   ├── holon/

    │   ├── agora/

    │   ├── asphaleia/

    │   └── noesis/

    │

    ├── skills/

    │   └── shared/

    │

    ├── policies/

    │   ├── constitution/

    │   ├── capabilities/

    │   ├── protected-paths/

    │   ├── model-use/

    │   └── exceptions/

    │

    ├── extensions/

    │   └── adapters/

    │       ├── hermes/

    │       ├── openhands/

    │       ├── vllm/

    │       ├── mcp/

    │       └── a2a/

    │

    └── tests/

        ├── architecture/

        ├── integration/

        ├── policy/

        └── conformance/

## Placement principles

- **`Skills teach`**` procedures.`

- **`Tools act`**` through bounded interfaces.`

- **`Hooks react`**` to typed events.`

- **`Workflows coordinate`**` durable multistep execution.`

- **`Plugins own`**` domain semantics.`

- **`Koinon owns`**` shared mechanisms and authority boundaries.`

- **`Epimeleia owns`**` runtime adaptation and agent lifecycle.`

- **`Tekton owns`**` software-engineering governance.`

- **`Noesis owns`**` models and inference.`

- **`Asphaleia owns`**` trust and capability boundaries.`

- **`Git owns`**` canonical source definitions.`

- **`Runtime projections are disposable.`**

- **`Agent-generated extensions enter quarantine first.`**

# Biological correspondence

|                         |                                           |
|-------------------------|-------------------------------------------|
| **`Biological system`** | **`Kosmos implementation`**               |
| `Genome/constitution`   | `Telos and Axiomeon`                      |
| `Nervous system`        | `Epimeleia, Pronoia, Synedrion, Harmonia` |
| `Sensorium`             | `Aisthesis and Zetesis`                   |
| `Memory`                | `Mneme and Gnosis`                        |
| `Circulation`           | `Mesiteia`                                |
| `Metabolism`            | `Poros and Noesis`                        |
| `Homeostasis`           | `Poros, Harmonia, Kybernesis`             |
| `Immune system`         | `Asphaleia, Euthyna, Sema`                |
| `Regeneration`          | `Kybernesis, Tekton, Mneme, Euthyna`      |
| `Adaptation`            | `Pronoia, Gnosis, Synedrion, Tekton`      |
| `Development`           | `Pronoia, Tekton, Telos`                  |
| `Effectors`             | `Praxis systems and tools`                |
| `Nociception`           | `Sema`                                    |

# Implementation roadmap

## Phase 1: Koinon core

- `Kernel.`

- `Typed contracts.`

- `Event envelopes.`

- `Mneme persistence.`

- `Artifact custody.`

- `Provenance.`

- `Workflow engine.`

- `Plugin registry.`

- `Baseline Aisthesis telemetry.`

## Phase 2: Asphaleia

- `Identity.`

- `Authentication.`

- `Capability model.`

- `Secrets.`

- `Sandboxes.`

- `Protected paths.`

- `Audit logging.`

- `Trust boundaries.`

## Phase 3: Syndesmos and Mesiteia

- `Canonical schemas.`

- `Event bus.`

- `Service discovery.`

- `Command routing.`

- `API gateway.`

- `MCP adapter.`

- `A2A adapter.`

- `Correlation and tracing.`

## Phase 4: Poros and Noesis

- `Resource telemetry.`

- `GPU and model-server management.`

- `Model registry.`

- `Inference routing.`

- `Resource budgets.`

- `Capacity forecasting.`

- `Backpressure.`

- `Health checks.`

## Phase 5: Epimeleia

- `Agent manifests.`

- `Hermes adapter.`

- `Skill resolver.`

- `Tool gateway.`

- `Session lifecycle.`

- `Checkpoints.`

- `Termination.`

- `Telemetry.`

## Phase 6: Zetesis, Gnosis, Synedrion, Agora

- `Research workflows.`

- `Evidence capture.`

- `Citation gates.`

- `Knowledge indexing.`

- `Council protocol.`

- `Informal A2A exchange.`

- `Provenance integration.`

## Phase 7: Tekton and Euthyna

- `OpenHands adapter.`

- `Isolated worktrees.`

- `Python quality gates.`

- `Clean-room verification.`

- `Regression gates.`

- `Artifact promotion.`

- `Release and rollback.`

## Phase 8: Higher-order intelligence

- `Axiomeon.`

- `Holon.`

- `Pronoia strategy workflows.`

- `Telos amendment workflows.`

- `Controlled self-improvement.`

- `Homeostasis, immunity, regeneration, and adaptation loops.`

# Non-negotiable invariants

- **`Praxis performs.`**

- **`Harmonia coordinates.`**

- **`Kybernesis governs current operations.`**

- **`Euthyna independently verifies.`**

- **`Pronoia anticipates.`**

- **`Telos defines identity and purpose.`**

- **`Sema interrupts when viability is threatened.`**

- `VSM functions are recursive, not merely central services.`

- `Agents do not own authoritative state.`

- `Agents do not grant themselves capabilities.`

- `Agents do not accept their own output.`

- `Producers are not their sole auditors.`

- `Deterministic mechanisms perform reliable deterministic work.`

- `Policy cannot be silently weakened.`

- `Sema must operate without LLM availability.`

- `Agora is nonbinding discussion.`

- `Synedrion is advisory deliberation.`

- `Poros measures and recommends; Kybernesis authorizes.`

- `Noesis manages models; Epimeleia manages agents.`

- `Tekton governs software work; OpenHands is an implementation backend.`

- `Skills have no ambient authority.`

- `Tools require capabilities.`

- `Agent-created tools, hooks, skills, and policies enter quarantine.`

- `Accepted artifacts require immutable identity, such as a content hash or commit SHA.`

- `Self-improvement proceeds through proposal, controlled experiment, independent verification, and authorized promotion.`
