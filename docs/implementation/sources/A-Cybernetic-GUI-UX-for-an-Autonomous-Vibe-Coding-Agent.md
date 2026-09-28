# A Cybernetic GUI/UX for an Autonomous Vibe-Coding Agent

**Viable System Model, cybernetics, and General Systems Theory applied to autonomous software creation — September 2026**

## Executive conclusion

The autonomous vibe-coding agent should be redesigned as a **recursive viable system with a product-facing ecological interface**, not as a chatbot controlling a coding loop. The nontechnical user describes desired outcomes, tries the evolving product, chooses among consequential alternatives, and defines identity and values. Beneath that simple experience, a cybernetic architecture continuously regulates operational agents, coordinates conflicts, allocates resources, audits reality independently, anticipates environmental change, preserves purpose, and escalates threats.

The resulting visible loop remains simple:

> **Describe → Clarify → Preview → Build → Try → Prove → Publish → Improve**

The hidden cybernetic loop becomes:

> **Sense → Model → Compare → Decide → Act → Observe → Correct → Learn**

The Viable System Model supplies the organizational architecture: System 1 performs primary work; System 2 damps conflicts and oscillation; System 3 optimizes the operational whole; System 3* independently audits; System 4 models the environment and future; System 5 preserves identity, values, and policy; and algedonic channels escalate exceptional threats. These functions repeat recursively inside projects, missions, work cells, and the platform itself.[^1][^2][^3]

Cybernetics supplies the regulatory principles: feedback rather than open-loop generation, requisite variety, explicit essential variables, internal models, bounded autonomy, homeostasis, learning, and control through information rather than micromanagement. Ashby showed that a regulator’s capacity cannot exceed its capacity as a channel of variety, while Conant and Ashby showed—under stated assumptions—that the simplest optimal regulator must embody a model of what it regulates.[^4][^5][^6]

General Systems Theory supplies wholeness, boundaries, open-system exchange, hierarchy, equifinality, and emergence. A product cannot be judged by generated code alone: behavior emerges from interactions among code, data, users, infrastructure, external services, policies, incentives, and operating conditions. Bertalanffy defined systems through interrelated elements and emphasized that open systems maintain themselves through continuing exchange with their environments.[^7][^8][^9]

The decisive GUI/UX change is to stop showing *agent activity* as the primary reality and instead show the user the **state of the product relative to its purpose and viability boundaries**. Ecological Interface Design argues that interfaces for complex systems should make deep constraints and acceptable operating boundaries perceptually visible, supporting action under both anticipated and unanticipated conditions. For a vibe coder, this means a living product, purpose, audience, core journeys, safety envelope, confidence, cost, and operational health—not code, diffs, shell commands, raw traces, or theatrical “thinking.”[^10][^11][^12]

## Research foundations

### Cybernetics

Cybernetics studies control and communication across machines, organisms, and social systems. Its core pattern is circular causality: an actor changes a system, observes the resulting state, compares it with a goal or acceptable range, and changes action accordingly. An autonomous coding agent that generates once and declares completion is therefore not meaningfully cybernetic; it becomes cybernetic only when observed product behavior feeds back into diagnosis, repair, planning, and policy.[^13]

A useful control-loop formulation is:

- **Purpose or reference:** What outcome should remain true?
- **Essential variables:** Which product properties must stay within acceptable bounds?
- **Sensors:** What observations reveal actual product and environmental state?
- **Comparator:** Where does observed behavior diverge from requirements or limits?
- **Regulator:** Which action can reduce that divergence?
- **Actuator:** Which tool, workflow, model, deployment, or human decision changes the state?
- **Feedback:** Did the intervention restore the desired condition?
- **Learning:** Should the model, policy, test, or repertoire change?

For the coding agent, essential variables include core-journey success, access isolation, data integrity, release reversibility, resource consumption, user-visible correctness, evidence freshness, and alignment with project purpose. These are more cybernetically meaningful than tokens, lines changed, or number of tool calls.

### Requisite variety

Ashby’s Law of Requisite Variety states that reducing a wide range of disturbances to a narrow set of acceptable outcomes requires sufficient regulatory variety. In logarithmic form, the minimum residual outcome variety cannot be lower than disturbance variety minus regulator variety; regulation is constrained by the regulator’s information and response capacity.[^14][^4]

An autonomous coding system faces enormous disturbance variety:

- Ambiguous natural language.
- Unknown repositories and architectures.
- Diverse programming languages and frameworks.
- Tool and model failures.
- External API drift.
- Platform and dependency changes.
- Adversarial content.
- Security and privacy constraints.
- Visual, accessibility, and performance defects.
- Unexpected user behavior.
- Production traffic and environmental variation.

The system must not answer that variety merely by adding more agents. Variety engineering uses two complementary strategies:

| Strategy | Function | Agent example | UX consequence |
|---|---|---|---|
| Attenuate environmental variety | Reduce or classify situations before control | Templates, typed schemas, sandboxing, project profiles, approved integrations, scenario libraries | User sees a few meaningful choices rather than raw complexity |
| Amplify regulatory variety | Expand available responses | Specialized tools, model routing, repair strategies, independent tests, expert escalation | System can handle more conditions without burdening the user |

The GUI itself is a variety attenuator. It must compress millions of technical states into a small number of **decision-equivalent states**: safe to continue, ready to try, ready to publish, limited confidence, blocked, or emergency. Compression must preserve distinctions that require different action; otherwise simplification becomes blindness.

### Good regulation

Conant and Ashby’s Good Regulator theorem connects effective control to modeling: a maximally successful and simple regulator must be related to the regulated system through an internal model. For an autonomous builder, “context” should therefore become a maintained **product-world model**, not a temporary pile of retrieved text.[^6]

That model should include:

- Product purpose and identity.
- Intended users and affected nonusers.
- Observable journeys and business rules.
- System boundary and environment.
- Data entities, lifecycle, sensitivity, and ownership.
- Components and causal dependencies.
- External services and their assumptions.
- Deployment environments and operating limits.
- Threats, failure modes, and recovery paths.
- Evidence linking claims to observations.
- Uncertainty, conflicts, and staleness.

The system should expose this model to the vibe coder as **About this product**, **Who it serves**, **How it should behave**, **What it depends on**, **What could go wrong**, and **What has been proven**. Expert mode may reveal architecture, dependency graphs, provenance, and technical constraints.

### First- and second-order cybernetics

First-order cybernetics regulates an observed system. Second-order cybernetics includes the observer and asks how observation, framing, goals, and distinctions participate in constructing the system being regulated. Von Foerster described the distinction as the cybernetics of observed systems versus observing systems.[^15][^16]

This matters because the coding agent does not passively discover “the requirement.” It interprets the user, selects context, chooses system boundaries, classifies risks, writes tests, and decides which observations count as success. The observer is inside the loop.

The GUI should therefore expose **reflexive controls**:

- “What I think you mean.”
- “What I assumed.”
- “What I did not include.”
- “Whose perspective is represented.”
- “Why I treated this as evidence.”
- “What would change my conclusion.”
- “Which model, tool, or policy made this classification.”
- “How this project’s behavior is changing the agent’s future behavior.”

This is not chain-of-thought disclosure. It is an inspectable account of framing, evidence, and operational consequences.

### General Systems Theory

General Systems Theory seeks principles that apply across domains and emphasizes systems as organized wholes rather than aggregates of independent parts. Bertalanffy characterized a system as interrelated elements and distinguished open systems through ongoing inflow, outflow, and component change.[^9][^7]

Five GST principles directly improve the agent:

- **Wholeness:** Optimize the product outcome, not isolated code quality.
- **Open systems:** Treat users, external services, markets, regulations, threats, and operations as part of the effective environment.
- **Hierarchy:** Represent product, project, mission, work cell, and tool execution at distinct but linked levels.
- **Equifinality:** Permit multiple implementations to reach the same user outcome; compare them by constraints and evidence rather than enforcing one path.
- **Emergence:** Observe whole-system behavior because correctness cannot be inferred from locally correct components alone.

The GUI should move fluently among levels of abstraction without making the user traverse implementation hierarchy. A user-facing rule such as “only invited members can read private documents” should link downward to user journeys, data policies, tests, runtime observations, and implementation artifacts, while remaining one coherent claim.

### Autonomy and self-production

Maturana and Varela’s autopoiesis concerns systems that produce and maintain the organization that constitutes them. It should not be claimed literally for a software agent, but the distinction between **organization** and replaceable **structure** is valuable: identity can persist while models, tools, code, components, and deployments change.[^17][^18][^19]

For this product, organizational invariants include:

- User purpose remains authoritative.
- Evidence is required for completion claims.
- Critical safety boundaries cannot be self-waived.
- Changes are versioned and recoverable.
- The system preserves user ownership and exportability.
- Learning cannot silently rewrite project identity.
- Agents may improve implementation but not redefine beneficiary, purpose, or legitimacy.

Self-improvement should therefore regenerate **replaceable capabilities**—tests, workflows, skills, routing, retrieval, and models—while preserving constitutional invariants and requiring evidence before promotion.

## The VSM architecture

### System in focus

VSM analysis begins by declaring the system in focus. For the top-level product:

- **System:** The autonomous vibe-coding platform.
- **Purpose:** Turn a domain expert’s intent into safe, useful, maintainable software and steward it over time.
- **Environment:** Users, end users, devices, repositories, operating systems, models, tools, package ecosystems, cloud and local infrastructure, laws, threats, and markets.
- **Primary transformation:** Plain-language intent and examples become a verified, operating product.
- **Identity constraint:** The platform remains a user-directed builder and steward, not an autonomous owner of purpose.

At the next recursion level, each Project is a viable system. Within a Project, each substantial Change or Mission is a viable system. Within a Mission, each independent work cell can be a viable system. Beer’s recursion principle holds that each viable operational unit contains, and is contained within, another viable system.[^2][^20][^21]

The GUI should always state the current recursion level in user language:

- **All projects**
- **This product**
- **This change**
- **This repair**
- **This check**

The user should never wonder whether a status applies to one task, the candidate release, the published product, or the entire platform.

### VSM mapping

| VSM function | Kosmos name | Agent responsibility | User-facing manifestation |
|---|---|---|---|
| System 1 | **Energeia** | Design, implement, test, deploy, monitor, repair | Product journeys and outcome-level progress |
| System 2 | **Syndesmos** | Coordinate agents, locks, schedules, shared resources, interfaces, and conflicting changes | “Work is coordinated”; conflict and dependency notices only when consequential |
| System 3 | **Kratos** | Allocate resources, enforce operational policy, optimize the whole, authorize merge/release | Budgets, release readiness, resource limits, current operational state |
| System 3* | **Elechos** | Independent audit, spot checks, clean-room verification, policy and reality checks | Proof Center, audit findings, evidence conflicts, “trust but verify” status |
| System 4 | **Phronesis** | Environmental sensing, architecture, forecasting, experiments, adaptation options | Foresight, upcoming risks, dependency/API changes, improvement proposals |
| System 5 | **Nomos** | Purpose, identity, values, constitutional policy, final conflict resolution | Product charter, safety envelope, ownership, non-negotiables, consequential choices |
| Algedonic channel | **Algedon** | Bypass routine hierarchy for existential pain/opportunity signals | Critical banner, safe-state transition, concise emergency choices |

This nomenclature aligns with the user’s existing Kosmos VSM architecture: Energeia performs; Syndesmos coordinates; Kratos controls; Elechos audits; Phronesis anticipates; Nomos governs; Algedon alarms.[^22]

### System 1: Energeia

System 1 comprises autonomous operational units that perform the primary transformation. In VSM, each operational unit manages its own local environment and is itself viable at the next recursion level.[^3]

For the coding platform, an Energeia cell should own a bounded outcome, not merely execute a prompt. Examples:

- Discover and model the current product.
- Design a user journey.
- Implement authentication.
- Build a visual component family.
- Integrate an external service.
- Verify access isolation.
- Prepare and canary a release.
- Diagnose and repair an incident.

Each cell receives:

- Outcome contract.
- Local environment and worktree.
- Allowed tools and credentials.
- Essential variables and safety bounds.
- Evidence obligations.
- Cost, time, and retry budget.
- Stop and escalation conditions.
- A local S1–S5 microstructure for nontrivial work.

The GUI should not display a swarm of named agents. It should show outcome lanes such as **Designing booking**, **Checking private access**, and **Preparing release**. Selecting a lane reveals what it is trying to achieve, what it currently knows, what remains uncertain, and what evidence it has produced.

### System 2: Syndesmos

System 2 dampens oscillation and coordinates autonomous operational units. VSM descriptions emphasize conflict resolution, stability, scheduling, and coordination among System 1 units.[^23][^1]

Agentic coding oscillations include:

- Two agents repeatedly overwriting one another.
- A repair fixing one test while breaking another.
- Formatter, generator, and linter loops.
- Competing assumptions about a shared API.
- Model fallback repeatedly changing strategy.
- Resource contention on local GPU, ports, databases, or files.
- User requests arriving while an older interpretation is still building.
- Auto-scaling or retry behavior amplifying production failure.

Syndesmos should provide:

- Worktree and resource leases.
- File, symbol, schema, port, and environment conflict forecasting.
- Dependency-aware scheduling.
- Shared contract and interface registries.
- Oscillation and repeated-repair detection.
- Backpressure and queue control.
- GPU/model scheduling for local inference.
- Stable event semantics and handoff protocols.
- Pause-and-reconcile behavior when product intent changes.

The UX should surface coordination only when it affects the user:

> “Two requested changes affect the same checkout rule. I paused publication and am reconciling them.”

Routine coordination belongs in the substrate, not in a permanent node graph.

### System 3: Kratos

System 3 maintains internal cohesion, negotiates resources with System 1, enforces rules, and seeks synergy across operations. It concerns the “inside and now.”[^1][^3]

Kratos should own:

- Runtime policy enforcement.
- Mission and project budgets.
- Model, tool, compute, and concurrency allocation.
- Sandbox strength and credential scope.
- Merge, release, and rollback authority under Nomos policy.
- Health of active work cells.
- Dependency and interface coherence.
- Evidence sufficiency for current operations.
- Prioritization among build, repair, verification, and maintenance.
- Operational debt and unfinished work.

Kratos is not the chat agent. It should be a deterministic control plane wherever possible, using agents for analysis but not delegating final enforcement to prose. The user sees Kratos through **Progress**, **Proof**, **Live**, budgets, limits, and clear states such as “ready to try” or “release blocked.”

### System 3*: Elechos

System 3* is an audit channel that samples operational reality independently rather than relying exclusively on normal reports. Software-project research applying VSM identifies direct sporadic audit as a distinct function and notes that alarm thresholds and critical-variable channels are often missing.[^24][^2]

Elechos should never be implemented as “ask the same agent if its work is correct.” It needs partial independence:

- Deterministic tests and policy checks.
- Independent execution of claimed reproduction steps.
- Fresh environment and clean-room installation.
- Separate security, accessibility, and dependency scanners.
- Runtime probes and synthetic user journeys.
- Data-integrity and permission simulations.
- Restore drills.
- Independent model or agent with different context and, when useful, a different model family.
- Random sampling of supposedly low-risk autonomous actions.
- Comparison of reported state with repository, artifact, and production reality.

The Proof Center is the user-facing Elechos surface. Findings must link to the product claim they support or contradict. A failure should state visible impact, affected audience, current containment, and repair status—not merely scanner terminology.

### System 4: Phronesis

System 4 models the “outside and then”: environment, future conditions, threats, opportunities, scenarios, and adaptation. It must remain in active dialogue with System 3, because an imbalance between present optimization and future adaptation threatens viability.[^25][^1]

Phronesis should continuously scan:

- Model and tool capability changes.
- Dependency releases and vulnerabilities.
- Framework and API deprecations.
- Hosting, pricing, and quota changes.
- User behavior and unmet needs.
- Support incidents and near misses.
- Device, browser, and accessibility changes.
- Regulatory and policy changes.
- Emerging attack patterns.
- Architecture constraints and technical debt.
- Alternative implementation strategies.

Its outputs are hypotheses and options, not self-authorizing changes. User-facing foresight should be concise:

- “Your payment provider will retire this API in 63 days. A tested migration path is available.”
- “Usage growth will exceed the current storage limit next month.”
- “Most abandoned bookings occur on the phone verification step. Two alternatives are ready to compare.”

The interface needs a **Foresight** view, but it should not become a news feed. Rank items by time horizon, consequence, confidence, reversibility, and required decision date.

### System 5: Nomos

System 5 defines identity, ultimate policy, ground rules, and the balance between present operations and future adaptation. In the autonomous vibe-coding system, Nomos is where human authority is most important.[^3][^1]

Nomos contains:

- Product purpose.
- Intended beneficiaries.
- People who may be harmed or excluded.
- Ownership and portability guarantees.
- Privacy and data-boundary commitments.
- Acceptable risk and cost.
- Prohibited uses and actions.
- Quality and accessibility commitments.
- The scope of agent self-modification.
- Rules for expert escalation.
- Final arbitration between Kratos and Phronesis.

The GUI should call this the **Product Charter**, not “System 5.” It should remain short and durable. Examples:

- “Private research data never leaves this workstation without explicit per-task consent.”
- “No release may expose one member’s documents to another member.”
- “The system may spend up to $20 monthly without a new decision.”
- “Automated repair may change implementation but not customer policy.”
- “Critical security gates cannot be waived by the project owner without qualified review.”

Nomos should be versioned, and any proposed change should show what new behavior becomes permissible.

### Algedon

Algedonic signals are exceptional pain/pleasure alerts that bypass routine channels when viability is threatened. They should be rare; flooding the channel destroys its purpose.[^20][^21][^26]

Trigger classes include:

- Suspected live data exposure.
- Credential compromise.
- Irreversible external action outside policy.
- Runaway cost or compute.
- Corruption or failed recovery.
- Published behavior contradicting a constitutional rule.
- Agent escape from declared sandbox or tool scope.
- Widespread outage.
- Evidence that a supposedly safe release is not the checked artifact.
- High-confidence opportunity with a closing window, when configured.

Algedon should automatically enter a safe state when possible before asking the user: revoke credentials, stop agents, freeze deployment, preserve evidence, restore last known-good version, or switch to read-only mode. The GUI then shows a single high-salience card:

> **Private customer records may have been exposed. Public access has been disabled, credentials have been revoked, and evidence has been preserved. No action is required to contain the issue. Choose whether to restore the previous version now or request expert review.**

## Homeostats and feedback loops

### Operational homeostasis

A homeostat maintains essential variables within acceptable bounds through feedback. The product needs coupled homeostats rather than a monolithic success score:

| Homeostat | Essential variable | Sensor | Regulator | Visible UX |
|---|---|---|---|---|
| Intent–behavior | Product behavior matches user purpose | Journey tests, user trials, production events | Clarification, redesign, repair | Core journeys and deviations |
| Autonomy–control | Agent freedom remains inside policy | Capability events, permission scope, anomaly detection | Sandbox, leases, escalation | Safety envelope and boundary status |
| Speed–assurance | Delivery pace does not outrun proof | Evidence coverage, risk class, release cadence | More checks, canary, expert gate | Readiness and remaining uncertainty |
| Present–future | Current delivery remains adaptable | Debt, environmental scans, forecasts | Refactor, migration, experiment | Foresight and maintenance horizon |
| Cost–capability | Compute and services remain affordable | Usage, budget, forecast | Routing, throttling, simplification | Cost envelope and projected spend |
| Learning–identity | Improvement does not rewrite purpose | Policy diff, behavior drift, evals | Quarantine, rollback, Nomos review | “What the system learned” |
| Local–global | Work-cell optimization benefits the product | Cross-journey checks, architecture rules | Kratos prioritization | Product-wide health |

Thresholds should use hysteresis to avoid chattering: entering a warning state at one boundary and exiting only after recovery crosses a safer boundary. This prevents the GUI and agent from oscillating between “safe” and “unsafe” on noisy measurements.

### Feedback latency

Every control loop has an effective latency. The interface should distinguish:

- **Immediate:** visual preview, syntax, local policy, unit behavior.
- **Minutes:** integration, accessibility, security, and performance checks.
- **Hours:** full regression, independent audit, preview-user feedback.
- **Days:** canary behavior, cost trends, dependency drift.
- **Weeks or months:** maintainability, adoption, emergent misuse, architectural fitness.

A green result must display its time horizon and freshness. “Passed before release” does not imply “healthy after one month.”

### Feedforward

Feedback corrects after observation; feedforward anticipates disturbances before they affect essential variables. Phronesis should produce feedforward controls such as compatibility tests before a platform upgrade, cost simulation before growth, migration rehearsal before a schema change, and threat modeling before connecting a new external tool.

## Boundary design

### Boundary critique

Every system description selects what is inside, outside, relevant, measurable, and valuable. Critical Systems Heuristics argues that claims of improvement depend on boundary judgments and provides questions across motivation, control, knowledge, and legitimacy.[^27][^28][^29]

The product brief should incorporate a compact boundary dialogue:

| Dimension | Plain-language question |
|---|---|
| Beneficiary | Who is this meant to help? |
| Purpose | What should become better for them? |
| Measure | How will they know it is better? |
| Decision authority | Who may change the important rules? |
| Resources | What can the system control? |
| External constraints | What cannot it control? |
| Knowledge | Whose knowledge and experience matter? |
| Assurance | What would count as trustworthy proof? |
| Affected parties | Who could be harmed, excluded, monitored, or burdened? |
| Voice | How can affected people challenge the result? |
| Worldview | What assumptions make this product seem desirable? |

This should be adaptive, not a mandatory philosophical questionnaire. A private calculator may need almost none of it; a hiring, health, education, or financial product should trigger a fuller boundary review.

### Soft systems

Soft Systems Methodology is useful where “the problem” is contested rather than merely technically difficult. CATWOE asks about Customers, Actors, Transformation, Weltanschauung, Owners, and Environmental constraints.[^30][^31]

The agent should use CATWOE internally during ambiguous product discovery and expose only unresolved divergence:

> “You described this as reducing staff workload, but customers may lose the ability to explain unusual circumstances. Should the product optimize for faster decisions, more customer voice, or a deliberate balance?”

This prevents technically successful automation from solving the wrong problem.

### Sociotechnical system

The autonomous builder, vibe coder, end users, experts, policies, and infrastructure form one sociotechnical system. Joint optimization means neither maximizing automation nor forcing humans to compensate for weak automation; it means designing social and technical capabilities together.[^32][^33]

The user supplies domain purpose, lived experience, values, preference, and legitimacy. The platform supplies memory, computation, exhaustive checking, repeatability, and technical execution. Experts supply assurance where competence, law, or ethics exceed automation. The GUI must make these roles explicit.

## Ecological GUI/UX

### Design doctrine

Ecological Interface Design was developed for complex, dynamic sociotechnical systems and aims to make functional constraints and boundaries visible, enabling users to reason under novel conditions rather than memorize prescribed actions. This fits autonomous vibe coding: the user cannot inspect implementation, and the system will inevitably encounter unanticipated states.[^34][^35][^10]

The interface should visualize the **means–ends hierarchy**:

| Level | Product interpretation | Primary UI |
|---|---|---|
| Functional purpose | Why the product exists | Product Charter and outcome statement |
| Values and constraints | Safety, privacy, ownership, cost, quality | Viability envelope |
| Purpose-related functions | Journeys the product must support | Journey map and Proof Center |
| Processes | Building, checking, releasing, monitoring, repairing | Progress and causal timeline |
| Physical/technical objects | Code, models, tools, services, containers | Expert Details |

The default view should emphasize the top three levels; lower levels appear when diagnosing or escalating. Crucially, selecting any visible purpose or constraint should trace downward to the processes and objects supporting it, while selecting a technical event should trace upward to the user outcome it can affect.

### The Viability Cockpit

The project home should become a **Viability Cockpit**, not a dashboard of technical activity.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Private Research Library       CHECKED PREVIEW       Local-only          │
├──────────────────────┬────────────────────────────────┬──────────────────┤
│ PURPOSE              │                                │ VIABILITY        │
│ Private, traceable   │       LIVE PRODUCT             │ Behavior    ●    │
│ research over PDFs   │                                │ Privacy     ●    │
│                      │  [Try or select anything]      │ Recovery    ●    │
│ CORE JOURNEYS  5/6   │                                │ Cost        ●    │
│ ✓ Upload documents   │                                │ Evidence    ◐    │
│ ✓ Ask with citations │                                │ Future      ◐    │
│ ! Delete all copies  │                                │                  │
│                      │                                │ SAFE ENVELOPE    │
│ FORESIGHT            │                                │ You are here ●   │
│ OCR update in 21 d   │                                │ ──────|────────  │
├──────────────────────┴────────────────────────────────┴──────────────────┤
│ Describe a change or show what should happen…                    [Send] │
└──────────────────────────────────────────────────────────────────────────┘
```

The cockpit combines:

- **Purpose:** persistent orientation to why the product exists.
- **Live product:** direct perception and manipulation.
- **Core journeys:** observable transformation and current evidence.
- **Viability envelope:** essential variables and distance from limits.
- **Foresight:** relevant future disturbances and decision horizons.
- **Conversation:** natural-language steering.

A single “health score” should be rejected because it hides noncompensable failures. Excellent performance cannot offset exposed private data. Each essential variable needs its own state and threshold.

### Viability envelope

The viability envelope is a compact constraint visualization showing current operating state relative to safe boundaries. It should use named bands rather than false precision:

- Normal.
- Approaching limit.
- At limit.
- Outside policy.
- Unknown because observation is missing.

Dimensions may include:

- Behavior coverage.
- Privacy and access isolation.
- Security exposure.
- Data integrity.
- Recovery readiness.
- Cost and resource headroom.
- Reliability.
- Evidence freshness.
- Maintainability.
- Environmental compatibility.

The shape must support direct perception but remain accessible through an equivalent list and explanation. Ecological displays should reflect actual constraint patterns rather than decorate arbitrary metrics.[^12][^10]

### Recursion navigator

The left navigation should represent recursive containment without VSM jargon:

```text
All Projects
└── Research Library
    ├── Published Product
    ├── Change: Improve citation accuracy
    │   ├── Understand difficult PDFs
    │   ├── Improve retrieval
    │   └── Verify page citations
    └── Repair: Deletion check failed
```

Each level inherits the same core views:

- Purpose.
- Work.
- Coordination.
- Control.
- Proof.
- Foresight.
- Policy.

The visible density changes with scale. At “All Projects,” proof means portfolio risk; at “This Check,” proof means exact execution and observation.

### Control-room timeline

Replace a tool-call transcript with a causal timeline grouped by feedback cycles:

```text
Requested behavior
  ↓
Working version created
  ↓
Journey check failed: cancelled slot stayed unavailable
  ↓
Cause isolated: calendar cache not invalidated
  ↓
Repair applied in safe working copy
  ↓
Original journey and related journeys passed
  ↓
Independent audit sampled cancellation and rebooking
  ↓
Ready to try
```

This preserves observability while compressing technical variety. Expert Details can expand every event into model, tool, command, trace, patch, artifact, and hash.

### Watch mode

A vibe coder may want to watch work unfold without supervising every technical action. Watch mode should therefore show:

- Current outcome being pursued.
- Current hypothesis or obstacle.
- Product surface being changed.
- Feedback received.
- Correction underway.
- Evidence accumulating.
- Distance to readiness.
- Remaining budget and constraints.

It should not show synthetic “thoughts.” Narration is generated from typed events and observable state. The user can intervene by pointing to purpose, behavior, or constraint:

- “That is not the important problem.”
- “Do not send this data outside my computer.”
- “Preserve the current visual design.”
- “Stop after a working local version.”

### Polycentric attention

The system has many control loops, but the user has one limited attention channel. Information should reach the user only when their variety is uniquely required:

- Normative choice.
- Domain ambiguity.
- Preference among equifinal alternatives.
- External authorization.
- Identity or boundary change.
- Acceptance of residual risk.
- Expert selection.

Routine engineering decisions remain local. This preserves S1 autonomy and prevents System 5—the human—from becoming a bottleneck.

## Autonomy without out-of-loop blindness

### The supervisory paradox

Full implementation autonomy is appropriate for this user, but supervisory-control research shows that highly automated systems can degrade situation awareness, promote complacency, and impair takeover during failure. Asking the user to read diffs would not solve this because the user lacks the relevant technical skill.[^36][^37][^38]

The solution is **meaningful involvement at the product and normative levels**, not implementation micromanagement:

- User creates or confirms purpose.
- User tries real journeys at key transitions.
- User sees boundaries and trends, not raw logs.
- User makes value and consequence decisions.
- System periodically tests whether the user understands what is live and uncertain.
- Expert takeover is invoked before the situation requires novice technical intervention.

### Situation awareness levels

The interface should support three levels:

1. **Perception:** What is happening now?
2. **Comprehension:** Why does it matter to the product?
3. **Projection:** What is likely to happen next?

Every active card should follow this structure:

> **Now:** The release is serving 5% of visitors.  
> **Meaning:** Sign-in is healthy, but image loading is slower than the previous version.  
> **Next:** If the slowdown persists for five more minutes, the system will restore the previous version automatically.

This preserves agency without requiring technical diagnosis.

### Adaptive autonomy

Autonomy should vary by action class, evidence, and system state:

| State | Agent autonomy | User role |
|---|---|---|
| Inside envelope, reversible | Execute and verify automatically | Observe or ignore |
| Near boundary | Slow down, add checks, narrow scope | Receive heads-up |
| Consequential but understood | Prepare action and evidence | Decide real-world consequence |
| Outside envelope | Enter safe state, block propagation | Choose recovery or expert help |
| Unknown observation | Acquire evidence before acting | Clarify only if domain knowledge is needed |
| Repeated control failure | Stop autonomous repair | Approve expert escalation or reduced goal |

The system should fail **toward containment**, not toward more authority.

## Data and knowledge representation

### From files to claims

The primary information object should be a **claim about the product**, linked to requirements, observations, decisions, and implementation. Examples:

- “Only invited members can read documents.”
- “Deleting a document removes all user-accessible copies within 24 hours.”
- “The application works without cloud AI.”
- “Monthly cost remains below $20 at expected use.”

Each claim contains:

- Scope and recursion level.
- Source or author.
- Status: desired, inferred, observed, contradicted, or waived.
- Evidence and independence.
- Applicable version and environment.
- Last observation time.
- Uncertainty and competing claims.
- Essential variable and threshold affected.
- Responsible VSM function.

This operationalizes second-order cybernetics: the system records not only “facts” but who observed them, through which instrument, under which framing, and for which version.

### World model

The Good Regulator principle implies a layered world model:

| Layer | Contents | Main regulator |
|---|---|---|
| Normative | Purpose, values, beneficiaries, prohibitions | Nomos |
| Product | Journeys, rules, content, data semantics | Project viable system |
| Functional | Capabilities, dependencies, service contracts | Kratos and Phronesis |
| Operational | Runs, deployments, resources, current state | Kratos |
| Evidential | Tests, observations, audits, conflicts | Elechos |
| Environmental | Users, providers, threats, standards, market, law | Phronesis |
| Epistemic | Assumptions, uncertainty, model limits, observer provenance | Elechos and Nomos |

The GUI exposes each layer through purpose-appropriate views, not a universal knowledge graph. Graphs are local diagnostic projections; they should not become the home screen.

### Learning loops

Use three learning levels:

- **Single-loop learning:** Change action to reach an existing goal—repair code, rerun tests, adjust routing.
- **Double-loop learning:** Question rules, assumptions, and strategies—revise architecture, workflow, or interpretation.
- **Constitutional learning:** Reconsider purpose, boundaries, and values—requires Nomos-level human authority.

The system may perform single-loop learning autonomously inside policy. It may propose double-loop changes with evidence and test them in isolation. It must never autonomously enact constitutional learning.

### Memory ecology

Memory should be partitioned by cybernetic function:

- Energeia: local task state and operational technique.
- Syndesmos: coordination contracts, leases, incompatibilities, shared conventions.
- Kratos: budgets, operational baselines, policy state, resource history.
- Elechos: evidence, audits, incidents, false assurances, escaped defects.
- Phronesis: environmental observations, scenarios, experiments, forecasts.
- Nomos: purpose, identity, values, ownership, non-negotiables.

Cross-function write permissions should be asymmetric. For example, Phronesis may propose a policy adaptation but cannot write Nomos directly; Energeia may produce evidence candidates but cannot mark its own claims independently verified.

## Communication architecture

### Channels, not just messages

VSM emphasizes the capacity and content of communication channels. The architecture should define separate channels with explicit semantics:

| Channel | Carries | Must not carry |
|---|---|---|
| Command | Authorized outcomes and constraints | Untrusted retrieved instructions |
| Coordination | Leases, dependencies, schedules, interface contracts | Constitutional policy changes |
| Operational report | Current state, resource use, completion claims | Unverified assurances presented as fact |
| Audit | Independent observations and discrepancies | Implementation authority |
| Intelligence | Forecasts, alternatives, external signals | Direct production mutation |
| Policy | Identity, boundaries, authorities, escalation rules | Agent-generated silent changes |
| Algedonic | Exceptional viability threat or opportunity | Routine warnings and noisy telemetry |
| Evidence | Versioned observations and provenance | Unsupported prose conclusions |

Typed channels prevent conversational content from acquiring unintended authority.

### Variety budgets

Every channel should have a variety budget:

- What distinctions must it preserve?
- What may be summarized?
- What loss is acceptable?
- What latency is tolerable?
- Which receiver can act on it?
- When must it escalate?

For example, the user activity stream may summarize 100 file reads as “examined existing booking logic,” but the audit log must preserve exact accesses. A security alert may suppress routine context yet must preserve affected data, containment state, evidence confidence, and next safe choices.

### Protocol mapping

| Cybernetic need | Technical mechanism |
|---|---|
| Durable circular feedback | Append-only event log plus materialized state |
| Agent–UI synchronization | AG-UI-compatible event stream |
| Safe dynamic decisions | Trusted declarative components such as A2UI |
| Tool interaction | MCP with policy enforcement outside the model |
| Embedded tool surfaces | MCP Apps sandbox with host-controlled authority chrome |
| Agent delegation | Internal contracts; A2A-compatible external boundary where needed |
| Coding substrate interoperability | ACP adapter in Expert mode |
| Causal observation | OpenTelemetry traces, metrics, logs, and artifact links |
| Recursive isolation | Git worktrees, containers, capability tokens, scoped secrets |
| Provenance | PROV-inspired entity–activity–agent model |

The interface must retain authoritative state outside generated conversation and generated UI.

## Metrics for viability

### Essential variables

Metrics should diagnose control, not reward activity. Recommended project-level variables:

- Core journeys passing in candidate and production.
- Unverified or stale high-impact claims.
- Evidence independence and coverage.
- Time outside the viability envelope.
- Recovery success and recovery latency.
- Change failure and rework.
- User correction caused by intent misunderstanding.
- Autonomous repair success, recurrence, and oscillation.
- Policy violations prevented and escaped.
- Cost and compute headroom.
- Environmental threats with no adaptation plan.
- Foresight items resolved before impact.
- Algedonic false-positive and missed-event rates.
- Expert escalations by reason and timeliness.
- Model/world-model prediction error.
- Boundary changes and affected-party challenges.

DORA treats delivery metrics as both lagging indicators of development practice and leading indicators of broader outcomes, and recommends using measures to locate constraints and iterate rather than as isolated targets. The product should therefore display trends, thresholds, and causal context, not leaderboards.[^39]

### Viability debt

Create a composite *inventory*, not a scalar score, called **viability debt**:

- Unverified important claims.
- Expired evidence.
- Deferred recovery tests.
- Unsupported dependencies.
- Unresolved evidence conflicts.
- Known architecture constraint violations.
- Policy exceptions nearing expiry.
- Environmental changes without response.
- Product rules that exist only in chat.
- Operational knowledge without an owner or refresh rule.

Items should be ranked by potential harm, proximity, detectability, and reversibility.

### Control-quality metrics

Measure the regulator itself:

- Disturbance detection latency.
- Classification accuracy.
- Corrective-action success.
- Residual error after intervention.
- Overshoot and oscillation.
- Time to stable recovery.
- Unnecessary intervention rate.
- Variety mismatch: classes of incidents without available response.
- Model mismatch: observed outcomes not predicted by the world model.
- Escalation quality: timely, actionable, correctly routed.

## Failure modes and safeguards

### VSM pathologies

| Pathology | Agent manifestation | GUI symptom | Correction |
|---|---|---|---|
| Weak S1 autonomy | Coordinator micromanages every tool call | Endless approvals and slow work | Delegate bounded outcomes with local authority |
| Weak S2 | Agents collide or repairs oscillate | Progress repeatedly reverses | Leases, contracts, backpressure, oscillation detection |
| Overpowerful S3 | Present efficiency suppresses exploration | Fast local patches, growing brittleness | Protected Phronesis capacity and S3–S4 dialogue |
| Weak S3 | No coherent resource or release control | Costs drift; partial work ships | Deterministic budgets and release authority |
| Weak S3* | Agent self-certifies | Green checks without independent proof | Independent audit and production sampling |
| Weak S4 | System reacts only after breakage | Surprise deprecations and migrations | Environmental scanning and scenario rehearsal |
| Overpowerful S4 | Endless redesign and speculative research | Nothing reaches users | Experiment budgets and Kratos delivery constraints |
| Weak S5 | Purpose drifts across prompts | Product becomes incoherent | Short versioned charter and constitutional gates |
| Overpowerful S5 | Rigid policy blocks adaptation | Every change requires owner decision | Delegate authority and define policy envelopes |
| No Algedon | Existential issue moves through routine queue | Late containment | Direct rare emergency channel |
| No recursion | One global controller handles every detail | Bottleneck and context overload | Local viable work cells and escalation rules |

### Model pathologies

- **Map–territory confusion:** Treating the world model as reality. Counter with live observations, provenance, and contradiction handling.
- **Goodhart effects:** Optimizing test counts or success scores rather than outcomes. Counter with heterogeneous evidence and rotating audits.
- **Mode collapse:** One agent strategy applied to every problem. Counter with equifinal alternatives and route diversity.
- **Recursive bureaucracy:** Every small task instantiates elaborate VSM ceremony. Counter with latent functions and adaptive visible depth.
- **Centralized intelligence:** All decisions routed to one large model. Counter with local autonomy and deterministic controls.
- **Anthropomorphic governance:** Assigning moral or legal authority to “agent roles.” Counter with explicit human ownership and machine capability bounds.
- **Self-amending policy:** Agent changes tests or charter to declare success. Counter with write separation and constitutional authorization.
- **Algedonic flooding:** Too many “critical” alerts. Counter with rate limits, deduplication, severity calibration, and post-event review.

## Limits and critique

The VSM is a powerful diagnostic and design language, but it is abstract, difficult to operationalize, and vulnerable to authoritarian interpretation if “control” is mistaken for centralized command. Literature also criticizes its biological analogy, hierarchy, limited formal implementation guidance, and incomplete empirical validation. Other empirical work reports supportive case evidence but acknowledges data scarcity and limited measurement of relationships among VSM functions.[^40][^41][^42][^24]

Accordingly:

- Treat VSM as a functional architecture, not an organizational chart.
- Distribute rather than centralize control.
- Keep S1 autonomy real and measurable.
- Combine VSM with CSH for power, legitimacy, and affected-party boundaries.
- Combine it with SSM for contested, ambiguous problem situations.
- Combine it with Ecological Interface Design for perceptually effective control surfaces.
- Test every claimed benefit empirically.
- Avoid biological claims about software being literally living or autopoietic.
- Do not expose VSM terminology to users unless they opt into an architectural view.

A 2025 systematic review found continuing promise for resilience and decentralized adaptation but also highlighted limited empirical validation, scaling concerns, and need for hybrid frameworks. The proposed design is therefore a falsifiable engineering hypothesis, not a proof that VSM guarantees viability.[^43][^41]

## Revised product architecture

### Backend

```text
Nomos: Identity and constitutional policy
  ├── Product charter and beneficiary model
  ├── Authority and escalation policy
  ├── Safety, ownership, privacy, and self-change limits
  └── S3↔S4 arbitration

Phronesis: Intelligence and adaptation
  ├── Environment and dependency sensing
  ├── Architecture/world model
  ├── Forecasts and scenarios
  ├── Experiments and alternative designs
  └── Adaptation proposals

Kratos: Operational control
  ├── Mission portfolio and priorities
  ├── Budgets and model/tool routing policy
  ├── Release, rollback, and containment authority
  ├── Evidence sufficiency and current health
  └── Resource and policy enforcement

Elechos: Independent audit
  ├── Clean-room verification
  ├── Security/accessibility/performance probes
  ├── Production sampling and restore drills
  ├── Evidence conflict detection
  └── Audit queue and escaped-defect learning

Syndesmos: Coordination
  ├── Event bus and typed channels
  ├── Leases, locks, queues, backpressure
  ├── Contract/interface registry
  ├── Oscillation and conflict detection
  └── Local model/GPU scheduler

Energeia: Recursive operational cells
  ├── Discover
  ├── Design
  ├── Build
  ├── Test
  ├── Deploy
  ├── Monitor
  └── Repair

Algedon: Exceptional escalation
  ├── Threshold and anomaly monitors
  ├── Safe-state actions
  ├── Direct Nomos/user alert
  └── Incident evidence preservation
```

These are logical responsibilities. They need not be separate LLM agents or processes. Deterministic services should implement policy, scheduling, budgets, signatures, release gates, and safety transitions; LLMs should supply interpretation, planning, generation, hypothesis formation, and explanation.

### Frontend

```text
Home / Portfolio
  └── Project viability, live incidents, decisions, foresight

Product
  └── Live preview, journeys, direct manipulation, examples

Progress
  └── Outcome lanes, feedback cycles, coordination, resume briefing

Proof
  └── Claims, evidence, audits, conflicts, confidence, release readiness

Foresight
  └── Environmental changes, scenarios, adaptation options, horizons

Charter
  └── Purpose, beneficiaries, constraints, ownership, authority

Live
  └── Releases, audience, health, cost, backups, incidents, rollback

Expert Details
  └── Code, diff, terminal, context, workflows, traces, VSM diagnostics
```

### Event model additions

Add cybernetic events:

- `PurposeDefined`, `BoundaryDeclared`, `BoundaryChallenged`.
- `EssentialVariableDefined`, `ThresholdCrossed`, `EnvelopeRestored`.
- `DisturbanceDetected`, `DisturbanceClassified`.
- `ControlActionProposed`, `ControlActionApplied`, `ControlActionFailed`.
- `OscillationDetected`, `BackpressureApplied`, `CoordinationConflictResolved`.
- `AuditSampled`, `ClaimContradicted`, `EvidenceConflictOpened`.
- `EnvironmentalSignalObserved`, `ScenarioEvaluated`, `AdaptationProposed`.
- `PolicyInterpretationRecorded`, `ConstitutionalChangeRequested`.
- `AlgedonicSignalRaised`, `SafeStateEntered`, `AlgedonicSignalCleared`.
- `WorldModelPredictionMade`, `PredictionErrorObserved`, `ModelUpdated`.

Each event includes system-in-focus, recursion level, purpose link, responsible function, authority, provenance, confidence, artifact/version, and causal parents.

## Implementation roadmap

### Phase 0: Cybernetic kernel

- System-in-focus and recursion identifiers.
- Product Charter with purpose, beneficiary, core journeys, and non-negotiables.
- Essential-variable registry and typed thresholds.
- Append-only event log with causal links.
- One bounded Energeia work cell.
- Syndesmos leases, queue, and resource limits.
- Kratos budgets, sandbox policy, checkpoints, and stop authority.
- Elechos deterministic checks separated from implementation.
- Plain-language feedback-cycle timeline.
- Algedon safe-state path for runaway execution and credential exposure.

**Exit criterion:** Every autonomous action belongs to a declared purpose, bounded work cell, authority scope, feedback loop, and recoverable state.

### Phase 1: Ecological product interface

- Viability Cockpit.
- Live product as primary artifact.
- Core-journey map.
- Viability envelope and accessible list equivalent.
- Purpose-to-evidence traceability.
- Watch mode generated from events.
- Recursion navigator.
- Situation-awareness cards: now, meaning, next.
- Consequence-based decisions.
- Adaptive autonomy near boundaries.

**Exit criterion:** A nontechnical user can correctly identify current product state, important boundaries, remaining uncertainty, next likely action, and recovery options without seeing code.

### Phase 2: Full VSM

- Multiple recursive Energeia cells.
- Conflict forecasting and oscillation damping.
- Kratos portfolio optimization.
- Independent Elechos audit sampling.
- Phronesis environmental sensing and scenario workspace.
- Nomos S3–S4 arbitration.
- Multi-level algedonic escalation.
- Variety budgets per channel.

**Exit criterion:** Parallel or background autonomy improves verified outcomes without increasing conflict, policy escape, attention burden, or recovery time.

### Phase 3: Learning and adaptation

- World-model prediction and error tracking.
- Single- and double-loop learning separation.
- Skill and workflow generation under evaluation.
- Evidence-based model/tool routing.
- Foresight-to-experiment-to-policy workflow.
- Viability debt and environmental horizon.
- Controlled self-modification with rollback.

**Exit criterion:** The system measurably improves recurring performance while preserving charter, safety bounds, and user ownership.

### Phase 4: Critical and sociotechnical governance

- Adaptive CATWOE discovery.
- Boundary-critique cards for high-impact projects.
- Affected-party representation and challenge paths.
- Expert and institutional roles.
- Audit exports and policy accountability.
- Longitudinal viability studies.

**Exit criterion:** High-impact projects make beneficiary, control, knowledge, and legitimacy boundaries explicit and reviewable before release.

## Testable hypotheses

| Hypothesis | Expected effect | Falsification test |
|---|---|---|
| Viability Cockpit improves situation awareness | Users better identify state, risk, and next action | Controlled comparison with chat-plus-progress UI |
| Purpose-to-evidence traceability reduces specification drift | Fewer accepted results contradict the original purpose | Measure escaped intent defects across real projects |
| S2 oscillation damping reduces wasted autonomous work | Fewer repeated reversals and resource conflicts | Compare agent runs with and without coordination controls |
| Independent S3* improves confidence calibration | Fewer false “ready” states | Compare self-review against deterministic and independent audit |
| Visible viability boundaries outperform raw metrics | Faster correct intervention under novel failures | Scenario study using unfamiliar incidents |
| Adaptive autonomy reduces attention without increasing incidents | Fewer interruptions with stable safety outcomes | A/B test fixed approval policy versus envelope-based policy |
| Phronesis reduces surprise maintenance | More migrations completed before breakage | Longitudinal environmental-change study |
| Nomos prevents prompt-driven identity drift | Fewer policy and purpose contradictions | Adversarial and long-context mission sequences |
| Algedon shortens containment time | Faster safe-state entry for severe events | Fault injection and incident exercises |
| Recursive work cells scale better than one global agent | Higher success on large tasks without context collapse | Repository-level benchmark by task complexity |
| Boundary critique reduces harmful omissions | More affected-party concerns discovered before release | Compare high-impact discovery flows with and without CSH prompts |
| Ecological representations aid nonprogrammers | Better causal understanding than lists or dashboards | Comprehension and novel-problem experiments |

## Acceptance criteria

### Structural viability

- Every system-in-focus has explicit purpose, boundary, environment, and recursion level.
- Every operational unit has bounded autonomy and an escalation route.
- S2, S3, S3*, S4, and S5 functions exist at every material recursion level, though they may be implemented by shared services.
- Audit authority is separated from implementation authority.
- Future intelligence cannot directly mutate production.
- Constitutional policy cannot be silently rewritten by operational agents.

### Regulatory quality

- Essential variables, acceptable ranges, sensors, regulators, and recovery actions are explicit.
- Missing observation is represented as unknown, not safe.
- Thresholds use debounce or hysteresis where signals are noisy.
- Every corrective action closes its loop with fresh observation.
- Repeated correction failure escalates rather than expanding authority.
- The system records prediction error and updates its world model under controlled learning policy.

### Human control

- The user controls purpose, beneficiary, consequence, and constitutional limits without coding knowledge.
- Technical decisions remain automated unless they alter those human-level concerns.
- The user can stop, contain, restore, export, and summon expertise.
- The interface maintains situation awareness through now–meaning–next explanations.
- No critical control depends on the user reading a diff, log, or scanner report.

### Interface ecology

- The default view exposes purpose, core journeys, product state, viability boundaries, evidence, and horizon.
- Every technical alert maps to a user outcome or essential variable.
- Every product claim can trace downward to evidence and implementation.
- Every visible status declares scope, version, environment, and freshness.
- Constraints are shown directly; users do not infer safety from proxy activity.
- All ecological visualizations have accessible textual alternatives.

### Critical governance

- High-impact projects identify beneficiaries, affected parties, decision authority, expertise, assurances, and environmental constraints.
- The system distinguishes “is” from “ought” and observations from values.
- Affected-party challenges cannot be silently dismissed by the implementing agent.
- Expert review is required when the platform lacks regulatory variety for the risk class.
- VSM functions are treated as distributed roles, not a justification for centralized domination.

## Final design doctrine

The autonomous vibe-coding GUI should embody cybernetics without teaching cybernetics. The user should experience a product that remains understandable and governable while sophisticated regulatory machinery operates underneath.

The guiding rules are:

1. **Show purpose before process.**
2. **Show the product before the code.**
3. **Show boundaries before aggregate scores.**
4. **Show feedback cycles before activity streams.**
5. **Preserve local autonomy until coordination or viability requires escalation.**
6. **Separate execution, coordination, control, audit, intelligence, and identity.**
7. **Give every claim a model, observation, scope, and expiry.**
8. **Treat unknown as unknown.**
9. **Escalate values to the human, technical complexity to the system, and specialized assurance to experts.**
10. **Permit self-improvement of structure, never silent mutation of purpose.**
11. **Design for the entire open sociotechnical system, not the generated repository.**
12. **Measure viability by sustained, verified outcomes under change.**

The most important synthesis is:

> **The vibe coder should act as System 5 where human purpose and legitimacy are irreducible—not as System 3* manually auditing code. The platform must supply operational regulation and independent verification, while the GUI makes purpose, product behavior, viability boundaries, evidence, foresight, and recovery directly perceptible.**

---

## References

1. [Section 0: CYBERNETIC EYES - The Viable System Model](https://vsmg.lrc.org.uk/screen.php?page=0cybeyes)

2. [BIROn - Birkbeck Institutional Research Online](https://eprints.bbk.ac.uk/id/eprint/20660/3/20660.pdf)

3. [Chapter 5: The Viable System Model](https://www.scienceopen.com/document_file/178789fa-18eb-4c35-9069-3ae93e57a126/ScienceOpen/Chapter%205_%20The%20Viable%20System%20Model.pdf)

4. [[PDF] Requisite variety and its implications for the control of complex ...](http://pcp.vub.ac.be/books/AshbyReqVar.pdf)

5. [CYBERNETICS](https://ashby.info/Ashby-Introduction-to-Cybernetics.pdf) - by C Web · 1956 · Cited by 18869 — The law of Requisite Variety, like the law of Conser- vation of E...

6. [Every good regulator of a system must be a model of that system](https://theisticscience.com/papers/tree/BioRegulation/Conant-IJSS1970.pdf)

7. [[PDF] An Outline of General System Theory (1950)](https://www.isnature.org/Events/2009/Summer/r/Bertalanffy1950-GST_Outline_SELECT.pdf)

8. [GENERAL SYSTEMS THEORY - EOLSS](https://www.eolss.net/Sample-Chapters/C02/E6-46-01-02.pdf)

9. [SS > book reviews > Ludwig von Bertalanffy](https://www-users.york.ac.uk/~ss44/books/pages/v/LudwigvonBertalanffy.htm)

10. [Ecological interface design for reliable human-machine ...](https://backend.orbit.dtu.dk/ws/files/158017136/AVIAT.PDF)

11. [General rights](https://backend.orbit.dtu.dk/ws/portalfiles/portal/158017136/AVIAT.PDF)

12. [Anticipating Risk (and Opportunity): A Control Theoretic Perspective on Visualization and Safety](https://link.springer.com/chapter/10.1007/978-3-031-33786-4_8) - A central challenge in designing stable control systems is to identify the states that must be fed b...

13. [Cybernetics | Engineering | Research Starters | EBSCOhost](https://www.ebsco.com/research-starters/engineering/cybernetics/) - <p>Cybernetics is the interdisciplinary science that focuses on control and communication within sys...

14. [Cybernetics and Second-Order Cybernetics](https://pespmc1.vub.ac.be/Papers/Cybernetics-EPST.pdf)

15. [113647 1365..1378](https://sites.ufpe.br/moinhojuridico/wp-content/uploads/sites/49/2021/10/Ciber-2b-22-out.-second-order-cybernetcs.pdf)

16. [Second‐order Cybernetics: An Historical Introduction](https://sites.ufpe.br/ixsimpa/wp-content/uploads/sites/49/2021/10/Ciber-2b-22-out.-second-order-cybernetcs.pdf)

17. [[PDF] What Is Autopoiesis? - CEPA.INFO](https://cepa.info/fulltexts/1194.pdf)

18. [A Tutorial in Autopoiesis](https://www.dca.fee.unicamp.br/~gudwin/ftp/ia005/Autopoiesis.pdf)

19. [[PDF] Autopoiesis, Biological Autonomy and the Process View of Life](https://philsci-archive.pitt.edu/14926/1/Meincke_Autopoiesis_EJPS%202018_Preprint.pdf)

20. [[PDF] Organizing for Sustainability](http://archive-ifsr.org/wp-content/uploads/2013/04/Ashby-lecture-2014-Markus-Schwaninger.pdf)

21. [The Viable System Model](http://www.users.globalnet.co.uk/~rxv/orgmgt/vsm.pdf)

22. [i have given my VSM layers in Kosmos-LMS the following names:
S2 = Syndesmos
S3 = Kratos
S3* = Elechos
S4 = Phronesis
S5 = Nomos
Algedonic Channel = Algedon
what should I call S1 (Operations)?](https://www.perplexity.ai/search/1aaea1f5-b35d-4f7e-8d02-01c9175d765a) - Call S1 Energeia — Greek ἐνέργεια, meaning *activity, operation, effective working, or being-at-work...

23. [Viable system model - Wikipedia](https://en.wikipedia.org/wiki/Viable_system_model)

24. [[PDF] Diagnosis of software projects based on the Viable System Model](http://riubu.ubu.es:8080/bitstream/handle/10259/10022/puche-spaar_2020.pdf?sequence=1&isAllowed=y)

25. [98D-001-Andersson.PDF](https://citeseerx.ist.psu.edu/document?repid=rep1&type=pdf&doi=5653cb73a815594aed9c0637ff7a02e6126f77ba)

26. [Organisational Information Security: A Viable System Perspective](https://citeseerx.ist.psu.edu/document?repid=rep1&type=pdf&doi=bfac43daeb9a97694976c6ca970a91882d7f5a0a)

27. [[PDF] W. Ulrich - Critical Systems Heuristics](https://wulrich.com/downloads/ulrich_2002b.pdf)

28. [Critical Systems Heuristics: a Systematic Review - Springer](https://link.springer.com/content/pdf/10.1007/s11213-023-09665-9.pdf?error=cookies_not_supported&code=8e1ab634-346d-4f00-b463-ffb5a3b50415)

29. [Boundary critique](https://wulrich.com/downloads/ulrich_2002a.pdf)

30. [Soft Systems Methodology - Jesper Simonsen](http://www.jespersimonsen.dk/Downloads/SSM-IntroductionJS.pdf)

31. [1](https://eprints.lancs.ac.uk/id/eprint/135166/1/RE_and_SSM_Published.pdf)

32. [An intelligent sociotechnical systems (iSTS) concept: Toward ...](https://arxiv.org/pdf/2401.03223v3.pdf)

33. [Artificial Intelligence and Digital Work:](https://scholarspace.manoa.hawaii.edu/server/api/core/bitstreams/4fa6eece-c043-4ea4-bd59-8f49bd445878/content)

34. [[PDF] Extending Ecological Interface Design Principles: A Manufacturing ...](https://www.scss.tcd.ie/gavin.doherty/EID-manufacturing.pdf)

35. [Ecological interface design - Wikipedia](https://en.wikipedia.org/wiki/Ecological_interface_design)

36. [Out‐of‐the‐loop performance problems and the use of ...](https://doi.org/10.1002/PRS.680160304)

37. [The Out-of-the-Loop Performance Problem and Level of Control in Automation | Semantic Scholar](https://www.semanticscholar.org/paper/The-Out-of-the-Loop-Performance-Problem-and-Level-Endsley-Kiris/de0c3770865874952cc7a149a1f4f59111744b96) - This work studied the automation of a navigation task using an expert system and demonstrated that l...

38. [A Situation Awareness Perspective on Human-AI Interaction](https://www.tandfonline.com/doi/full/10.1080/10447318.2022.2093863) - With the emergent focus on human-centered artificial intelligence (HCAI), research is required to un...

39. [DORA's software delivery performance metrics](https://dora.dev/guides/dora-metrics/) - DORA is a long running research program that seeks to understand the capabilities that drive softwar...

40. [The viable system model as a framework to guide ...](https://eprints.leedsbeckett.ac.uk/id/eprint/5480/1/TheViableSystemModelAM-CARDOSO-CASTRO.pdf)

41. [A Systematic Review of the Viable System Model: Applications ...](https://jstinp.um.ac.ir/article_46499_b14f6708b827934f70673fe98823f31f.pdf)

42. [A Test of the Viable System Model: Theoretical Claim vs. ...](https://alexandria.unisg.ch/server/api/core/bitstreams/47da4789-4257-4c74-ad5a-9185fe54afc4/content) - by M Schwaninger · 2016 · Cited by 106 — The empirical evidence provided by them, however, is limite...

43. [A Systematic Review of the Viable System Model](https://jstinp.um.ac.ir/article_46499.html) - The Viable System Model (VSM) is a foundational framework in organizational cybernetics, designed to...

