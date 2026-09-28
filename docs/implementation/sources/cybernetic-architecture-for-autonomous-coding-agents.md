# Cybernetic Architecture for Autonomous Coding Agents

## Executive summary

The Viable System Model (VSM), cybernetics, and General Systems Theory provide a stronger foundation for autonomous coding agents than the prevailing architecture of a single language model operating a conversational tool loop. Their most useful contribution is not metaphorical terminology; it is a set of concrete design constraints for regulating complex work under uncertainty: requisite response variety, explicit feedback, operational autonomy bounded by cohesion, recursive organization, independent audit, environmental intelligence, adaptation, and preservation of essential variables.

The resulting agent should be designed as a **recursive viable software-engineering organization** rather than as a chatbot. Its operational units implement tasks; coordination prevents interference; control allocates resources and enforces current constraints; intelligence models the repository and changing environment; policy preserves identity and resolves conflicts between short-term delivery and long-term viability. Every viable task unit repeats the same pattern at its own scale.

The strongest synthesis is:

- **VSM provides organizational topology:** Systems 1–5, System 3*, recursion, autonomy, cohesion, and algedonic escalation.
- **First-order cybernetics provides operational regulation:** goals, essential variables, sensors, feedback, controllers, disturbances, delays, stability, and requisite variety.
- **Second-order cybernetics provides epistemic discipline:** the agent and its models are participants in the observed system, not neutral observers.
- **General Systems Theory provides boundary and relationship discipline:** open systems, hierarchy, emergence, equifinality, interdependence, and whole-system effects.
- **Soft Systems Methodology provides ambiguity handling:** stakeholder worldviews, root definitions, purposeful-activity models, and iterative accommodation.
- **System dynamics provides temporal reasoning:** stocks, flows, reinforcing and balancing loops, delays, nonlinear effects, and leverage points.
- **Organizational learning provides adaptation:** single-loop repair, double-loop revision of assumptions and policies, and learning how to improve the learning process.

Applied correctly, these traditions imply a deterministic mission kernel around stochastic models; typed commands and evidence rather than transcript-derived truth; isolated recursive task units; a persistent repository/environment model; independent verification; semantic progress regulation; effect-based security; algedonic exception channels; and governance that can change tactics without silently changing the system’s identity or goals.

## Intellectual foundations

### General Systems Theory

Ludwig von Bertalanffy developed General Systems Theory (GST) in opposition to explanations that reduced complex organisms to isolated component mechanisms. His work emphasized organismic organization and open systems that maintain themselves through continuous exchange with their environments.[^1][^2]

For an autonomous coding agent, the crucial GST correction is that neither the model, tool loop, repository, nor generated patch is the whole system. The operative system includes:

- User and stakeholder intentions
- Repository and dependency ecosystem
- Build and execution environments
- Agent workers and models
- Tools and sandboxes
- Tests and verification systems
- Version control and integration processes
- Deployment and production feedback
- Security and organizational policy
- Human review and exception handling

A locally correct patch can therefore be globally pathological. It may pass tests while degrading architectural integrity, operational reliability, security, maintainability, or the viability of dependent systems. The agent must regulate consequences across boundaries rather than optimize only the immediate code-generation task.

GST contributes several principles:

| Principle | Meaning | Coding-agent implication |
|---|---|---|
| Open system | The system exchanges information, resources, and effects with an environment | Continuously model dependencies, users, APIs, CI, deployment, and external change |
| Whole–part relation | Components are understood through their relationships within a whole | Evaluate patch impact across symbols, modules, services, tests, and workflows |
| Hierarchy | Systems contain subsystems and belong to supersystems | Recursively organize mission, project, task, and operation levels |
| Emergence | Global behavior is not reducible to isolated local behavior | Detect integration failures and architectural effects not visible in individual diffs |
| Equifinality | Different paths may produce equivalent outcomes | Generate and compare multiple implementation strategies |
| Boundary | Analysis depends on what is included or excluded | Make repository, mission, security, and stakeholder boundaries explicit |
| Dynamic equilibrium | Viability is maintained through continuing adjustment | Treat correctness as continuously regulated, not established once |

Emergence is especially relevant to multi-agent systems: higher-level patterns arise through local interactions, but their persistence also depends on top-down constraints and feedback. This argues against both extremes—one centralized omniscient agent and an unconstrained swarm. The design should combine bounded local autonomy with explicit global regulation.[^3][^4]

### Cybernetics

Cybernetics studies control and communication in animals, machines, and organizations. Wiener framed it around regulatory systems and feedback; negative feedback reduces deviation from desired ranges, while positive feedback amplifies change and can produce growth or instability.[^5][^6]

A cybernetic controller requires at least:

```text
Goal or viable range
        ↓
Controller → Action → Regulated system → Outcome
     ↑                                  ↓
     └──────────── Feedback ────────────┘
                   ↑
              Disturbances
```

Most present coding agents implement the action path but inadequately specify the regulatory path. A model edits code and runs tests, yet the system may lack explicit essential variables, trustworthy sensors, expected evidence, independent comparators, delay handling, and recovery policy. “The tests passed” becomes a weak proxy for a multidimensional viability condition.

Cybernetics changes the primary question from **“Can the model generate a solution?”** to **“Can the total system keep engineering outcomes inside acceptable bounds despite disturbances?”**

### Requisite variety

Ashby’s Law of Requisite Variety states that a regulator can control disturbances only to the extent that it possesses sufficient response variety; in its familiar form, only variety can absorb variety. Ashby also related regulatory capacity to communication-channel capacity, meaning a controller cannot respond to distinctions that its sensing and communication system cannot carry.[^7][^8][^9]

For coding agents, environmental variety includes:

- Languages, frameworks, build systems, and repository conventions
- Incomplete, ambiguous, and conflicting requirements
- Diverse failure modes
- Dependency and provider failures
- Security restrictions
- Legacy code and undocumented behavior
- Multiple execution platforms
- Human preferences and organizational policy
- Novel architectures and domain-specific constraints

Response variety does not mean one enormous model. It can be assembled through:

- Specialized models and actors
- Repository and language tooling
- Static and dynamic analyzers
- Search and retrieval
- Test generation
- Multiple strategies
- Human escalation
- Sandboxed experimentation
- Model routing and fallback
- Explicit recovery policies

The architecture must also **attenuate environmental variety** before it reaches expensive cognition. Typed tool outputs, repository indexes, symbol graphs, test-impact analysis, policy filters, relevance ranking, and error classification compress uncontrolled complexity into distinctions that the regulator can use. Conversely, it must **amplify regulatory variety** when existing responses fail by switching model, strategy, tool, decomposition, or authority level. VSM practice explicitly uses variety attenuation and amplification to meet environmental complexity.[^10][^11]

A practical variety budget can be represented as:

```text
Residual risk variety
  = disturbance variety
  - sensing/representation variety
  - available response variety
  + coordination loss
  + delay-induced uncertainty
```

This need not be numerically exact to be operationally useful. Every failed mission should identify which distinction, response, channel, or timing capability was missing.

### Good Regulator theorem

Conant and Ashby’s Good Regulator theorem establishes, under its stated conditions, that the simplest optimal regulator of a system must embody a model of that system. This has a direct architectural consequence: the agent requires an explicit and continuously updated model of the repository, task, environment, and its own capabilities.[^12][^13]

The regulator’s model should include:

- Requirements and acceptance criteria
- Repository topology
- Symbol and reference graph
- Dependency and build graph
- Test-to-symbol relationships
- Runtime and deployment topology
- Architectural decisions and invariants
- Current hypotheses and uncertainty
- Change sets and evidence freshness
- Model/tool capabilities and failure history
- User policy and permissions

A transcript is not an adequate system model. It is an episodic record whose contents are ordered by conversation rather than by the causal structure of the engineered system. Cybernetics therefore strongly supports a persistent **world model plus evidence graph**, with conversation treated as one input/output channel.

### First- and second-order cybernetics

First-order cybernetics concerns observed systems; second-order cybernetics includes the observing system and the consequences of the observer’s participation. This distinction is essential because coding agents alter the systems they observe:[^14][^15]

- Reading generated summaries affects subsequent interpretation.
- Selecting tests changes which failures become visible.
- Editing code changes repository retrieval results.
- Adding tests changes the apparent definition of correctness.
- Choosing a boundary determines which effects are ignored.
- Explanations influence human approval and subsequent requirements.

A second-order agent must represent its own observational limits and interventions. Every claim should record:

```text
claim
source evidence
observer/actor
method or tool
system boundary
confidence
known alternatives
contradicting evidence
change-set version
```

This produces epistemic humility through mechanism rather than prompting. The agent must distinguish source facts, tool observations, model inferences, user decisions, policies, and unresolved hypotheses.

### Autopoiesis and structural coupling

Maturana and Varela used *autopoiesis* to describe systems whose internal network produces and regenerates the components and boundary that constitute the system; structural coupling describes recurrent interaction through which systems and environments become congruent over time.[^16][^17]

A software agent is not biologically autopoietic, and the concept should not be applied literally. Its useful design analogy is **operational closure with environmental coupling**:

- The agent maintains its own mission state, schemas, policies, indexes, skills, and execution infrastructure.
- It exchanges observations and effects with repositories, humans, tools, and deployment systems.
- It preserves identity and invariants while adapting internal structures.
- It regenerates corrupted projections and reconstructs state from authoritative events.

This implies that self-improvement must be bounded. The agent may propose changes to prompts, policies, skills, routing, or code, but those modifications must pass a separate governance and evaluation loop before becoming part of the regulator that judges future changes.

## The Viable System Model

Stafford Beer’s VSM models the necessary organizational functions of a viable autonomous system. Its five systems distinguish operation, coordination, internal control, environmental intelligence, and identity/policy; System 3* supplies independent inquiry or audit.[^18][^19]

The VSM is recursive: each viable system belongs to a larger viable system and contains smaller viable systems. Viability depends on balancing local autonomy with whole-system cohesion.[^20][^19]

### VSM functions

| VSM function | Classical responsibility | Autonomous coding-agent responsibility |
|---|---|---|
| System 1 | Primary operational units | Task actors that inspect, design, edit, test, review, or integrate |
| System 2 | Coordination and oscillation damping | Scheduler, leases, ownership, merge coordination, rate limiting, shared conventions |
| System 3 | Inside-and-now control | Resource allocation, current plan execution, policy enforcement, integration, budgets |
| System 3* | Independent audit channel | Direct workspace inspection, hidden tests, security scans, provenance checks, telemetry |
| System 4 | Outside-and-then intelligence | Repository/environment model, dependency monitoring, architecture, scenario simulation |
| System 5 | Identity and policy | Mission purpose, ethical/security boundaries, acceptance policy, final conflict arbitration |

### System 1: autonomous operational units

System 1 contains the units that produce the system’s primary value. For a coding agent these are not necessarily “agents” in the marketing sense. They are bounded operational units such as:

- Requirement analyst
- Repository scout
- Failure reproducer
- Planner
- Implementer
- Test designer
- Reviewer
- Security analyst
- Performance analyst
- Integrator

Each System 1 unit requires:

- A defined transformation
- Inputs and expected outputs
- An isolated workspace
- A local environment model
- Capabilities and constraints
- Essential variables
- An evidence contract
- A budget
- A checkpoint and rollback policy
- An algedonic escalation channel

The transformation should be explicit. For example:

```text
Input: failing behavior, relevant repository slice, acceptance criteria
Transformation: diagnose and produce a minimal candidate change set
Output: patch, causal explanation, uncertainty, verification requirements
```

Operational autonomy means the implementer may choose detailed tactics inside its mandate. It does not mean it may silently alter requirements, write outside scope, waive tests, broaden network permissions, or declare the mission complete.

### System 2: coordination

System 2 dampens conflict and oscillation among System 1 units. This is the missing function in many multi-agent architectures, where several agents are launched and expected to coordinate through shared chat or shared files.

System 2 should provide:

- Git worktree or copy-on-write isolation
- File and symbol ownership leases
- Dependency ordering
- Resource reservations
- Shared formatting and build conventions
- Message and event schemas
- Conflict detection
- Duplicate-work suppression
- Backpressure
- Concurrency limits
- Merge sequencing
- Context-version and base-commit checks

Typical oscillations include:

- Two agents alternately undoing each other’s patches
- Planner and implementer repeatedly changing scope
- Tests driving implementation toward one behavior while review demands another
- Retrying a failing strategy with superficial variations
- Local optimization in two modules creating an integration failure

These are control problems, not failures of model intelligence. The scheduler should detect oscillation through state trajectories, repeated hypothesis patterns, patch reversals, and unchanged proof obligations rather than only exact repeated commands.

### System 3: operational control

System 3 optimizes the “inside and now.” It translates mission policy into current resource and execution decisions:

- Which tasks are active
- Which actor and model handle each task
- What compute and token budgets are available
- Which worktrees may be integrated
- Which verification gates are mandatory
- When to retry, replan, pause, or escalate
- Whether current work remains aligned with the approved plan

System 3 should not perform all work centrally. Its role is to negotiate resources, enforce constraints, and ensure the combined System 1 units produce a coherent whole.

A concrete System 3 service set is:

```text
Mission scheduler
Resource and model router
Capability-policy engine
Workspace transaction manager
Integration manager
Budget controller
Progress regulator
Evidence-gate controller
```

### System 3*: independent audit

System 3* gives management direct access to operational reality rather than relying only on reports produced through normal channels. VSM descriptions characterize it as an inquiry mechanism for timely, unfiltered information about operational units.[^18]

For coding agents, System 3* is indispensable because implementers and their generated tests share incentives and assumptions. It should independently:

- Inspect actual worktree state
- Recalculate diffs from Git
- Verify tool effects against declarations
- Run hidden or independently selected tests
- Check for unexpected files and processes
- Validate dependency and lockfile changes
- Scan security boundaries
- Compare reported and actual resource use
- Sample reasoning claims against primary evidence
- Detect fabricated or stale evidence
- Audit model and tool provenance

System 3* should use separate execution paths and, where valuable, a different model family. It must report directly to control and policy rather than through the implementer.

### System 4: intelligence and adaptation

System 4 models the “outside and then”: environmental change, future threats, opportunities, and adaptation. Coding agents commonly underbuild this function. Repository search is mistaken for environmental intelligence, while architectural evolution, dependency change, future maintenance, and downstream systems are ignored.[^19][^18]

System 4 should maintain:

- Incremental repository knowledge graph
- Architecture and subsystem boundaries
- External dependency intelligence
- API and schema compatibility model
- Build and deployment topology
- Historical defect and change patterns
- User and organizational preference model
- Model/tool capability profiles
- Scenario and counterfactual simulator
- Technology-obsolescence and migration signals
- Benchmark and production-performance trends

System 4 asks questions such as:

- Will this local solution remain viable under the next dependency version?
- Does the patch deepen an architectural liability?
- Which consumers may break even if repository tests pass?
- Is the current agent strategy becoming obsolete?
- Does repeated failure indicate a missing capability rather than a bad prompt?

### System 5: identity and policy

System 5 defines identity, ultimate policy, and the balance between present operations and future adaptation. It arbitrates conflict between System 3’s pressure to finish current work and System 4’s concern for future viability.[^18]

System 5 should contain:

- Mission purpose
- Non-negotiable safety and security rules
- Definition of accepted engineering quality
- Authority and escalation policy
- User intent and stakeholder commitments
- Permitted self-modification boundaries
- Trade-off policy among time, cost, quality, and risk
- Rules for waiving proof obligations
- Final delivery authority

This layer must be small, explicit, versioned, and difficult for operational actors to mutate. A model can recommend a policy change, but it should not silently redefine success to make its current patch acceptable.

### Algedonic signals

Beer used algedonic signals as exception channels that allow urgent positive or negative deviations to bypass ordinary reporting levels. In VSM-oriented accounts of Project Cybersyn, autonomous lower units handled routine conditions locally while escalating exceptions when critical thresholds were crossed.[^21][^22]

For a coding agent, algedonic events should include:

- Security policy violation
- Secret exposure
- Destructive or irreversible operation
- Unbounded cost or resource growth
- Loss of workspace integrity
- Repeated semantic non-progress
- Contradictory acceptance criteria
- Verification failure after integration
- Suspected benchmark or test gaming
- Environment drift invalidating evidence
- High-confidence discovery that the plan is fundamentally wrong
- Exceptional success revealing a reusable system improvement

An algedonic signal should be typed and actionable:

```json
{
  "severity": "critical",
  "source": "task-42/verifier",
  "essential_variable": "security.boundary_integrity",
  "observed": "outbound credential transmission attempted",
  "viable_range": "no credential egress",
  "causal_evidence": ["event-9182", "trace-338"],
  "automatic_action": "sandbox_frozen",
  "required_authority": "human_owner"
}
```

This is superior to burying urgent conditions in a transcript or terminal log.

### Recursion

Recursion is VSM’s most powerful contribution to multi-agent architecture. The same viable pattern should appear at several scales:

```text
Portfolio
└── Workspace/repository
    └── Mission
        └── Task
            └── Actor operation
```

At every level there are:

- Operations
- Coordination
- Current control
- Audit
- Future/environmental intelligence
- Identity/policy

The implementation need not instantiate five separate services at every level. Functions may be shared, but the responsibilities must be satisfiable at each recursion.

For example, a task actor is operational relative to the mission, but its own shell commands and tool calls are operational units relative to the actor. The actor therefore needs local coordination, control, audit, intelligence, and policy. This prevents an agent from being well governed at the mission level but chaotic within a task.

## Systems thinking extensions

### Soft Systems Methodology

Hard control methods assume the problem and goal are already known. Software requirements frequently violate that assumption. Soft Systems Methodology (SSM), developed by Checkland and collaborators, treats complex situations as inquiries involving different stakeholder viewpoints rather than as predefined technical problems.[^23][^24]

SSM seeks changes that are systemically desirable and culturally feasible, using problem-situation inquiry, explicit worldviews, purposeful-activity models, debate, and action.[^25][^26][^27]

A coding agent should invoke an SSM-style intake mode when it detects:

- Ambiguous success criteria
- Multiple stakeholder perspectives
- Conflicting requirements
- Organizational or political constraints
- A request framed as a solution rather than a problem
- Significant uncertainty about system boundaries
- Architectural work with no objective single answer

A practical root-definition schema can adapt CATWOE:

| Element | Agent question |
|---|---|
| Customers | Who benefits or suffers from the transformation? |
| Actors | Who performs and operates the changed system? |
| Transformation | What input state becomes what output state? |
| Worldview | Why is this transformation meaningful? |
| Owners | Who can authorize, stop, or redefine it? |
| Environment | Which constraints cannot the mission control? |

The result is not endless requirements discussion. It is a bounded clarification artifact that prevents the agent from efficiently solving the wrong problem.

### System dynamics

System dynamics models feedback, delays, stocks, flows, and nonlinear interactions. Software-development research using system dynamics has shown how feedback, delays, schedule pressure, and interconnected practices can create counterintuitive project behavior.[^28]

Important stocks for an autonomous coding system include:

- Unresolved requirements
- Unverified changes
- Technical debt
- Open hypotheses
- Stale knowledge
- Pending reviews
- Integration conflicts
- Human attention debt
- Accumulated reusable knowledge
- Trust

Important flows include:

- Requirements clarified per unit time
- Patches generated
- Findings resolved
- Tests added
- Evidence invalidated
- Defects discovered and escaped
- Review items opened and closed
- Knowledge promoted or deprecated

Typical loops include:

**Reinforcing failure loop**

```text
Schedule pressure
→ narrower verification
→ escaped defects
→ rework
→ greater schedule pressure
```

**Reinforcing context loop**

```text
Longer mission
→ more transcript
→ poorer retrieval
→ more mistaken actions
→ longer mission
```

**Balancing verification loop**

```text
Change risk
→ verification intensity
→ detected defects
→ corrective work
→ reduced residual risk
```

**Learning loop**

```text
Failure classified
→ reusable lesson
→ improved routing/policy
→ fewer comparable failures
→ higher-quality evidence for learning
```

Delays must be explicit. Test results, human approvals, dependency updates, production outcomes, and benchmark feedback arrive at different times. A fast controller reacting to delayed evidence can oscillate or overcorrect.

### Leverage points

Donella Meadows ranked intervention points from parameters and buffers through information flows, rules, self-organization, goals, and paradigms; goals and paradigms are among the deepest leverage points.[^29][^30][^31]

Applied to a coding agent:

| Low-leverage change | Higher-leverage alternative |
|---|---|
| Tune temperature | Improve task and evidence schemas |
| Increase token budget | Improve information flow and context compilation |
| Add retries | Classify failure and alter recovery rules |
| Add more agents | Redesign coordination and workspace isolation |
| Add another benchmark | Change the definition of accepted outcome |
| Strengthen system prompt | Move constraints into deterministic policy |
| Increase context window | Build a better regulator model and repository graph |
| Optimize patch count | Optimize accepted, non-regressing outcomes |

The central implication is that prompt tuning and model replacement are usually shallower interventions than changing feedback, information structure, rules, goals, and architecture.

### Single-, double-, and higher-loop learning

Argyris and Schön distinguish single-loop learning—correcting error while retaining governing assumptions—from double-loop learning, which questions and may change the governing variables, norms, policies, or objectives.[^32][^33][^34]

For an autonomous coding agent:

- **Single-loop:** A test fails; revise the patch.
- **Double-loop:** Repeated failures reveal that the plan, acceptance criterion, tool policy, decomposition, or architectural assumption is wrong; revise it.
- **Learning-to-learn:** Repeated mission classes reveal that the system’s failure-classification, evaluation, or improvement process is inadequate; change the learning architecture.

These levels require separate permissions. An implementer may perform single-loop repair. Plan revision requires mission-control authority. Policy, evaluation, or kernel changes require governance plus retrospective evaluation.

## A cybernetic reference architecture

```text
Human / organization / production environment
                         │
                  System 5: Policy
          identity, purpose, safety, acceptance
                         │
             ┌───────────┴───────────┐
             │                       │
      System 3: Control       System 4: Intelligence
      current execution       repository/environment
             │                       │
             └───────────┬───────────┘
                         │
               System 2: Coordination
        scheduling, ownership, conflict damping
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     System 1        System 1       System 1
      Scout          Implementer      Verifier
          │              │              │
          └──────── repository/workspaces ────────┘
                         │
            System 3*: independent audit
                         │
                 evidence / alarms
```

### Mission kernel

The authoritative kernel should be deterministic and event-sourced. Models propose actions; the kernel validates transitions, capabilities, budgets, and evidence requirements.

```python
async def regulate(mission_id):
    state = await mission_store.reconstruct(mission_id)
    deviation = comparator.compare(state.essential_variables)

    if deviation.algedonic:
        return await escalation.handle(deviation)

    command = controller.select_response(state, deviation)
    proposal = await actors.propose(command, state.compiled_context)
    authorized = policy.authorize(proposal, state)
    result = await executor.execute(authorized)
    evidence = await sensors.observe(result)

    events = transition_model.evaluate(state, proposal, result, evidence)
    await journal.commit(expected_version=state.version, events=events)
```

The LLM is part of the controller and intelligence apparatus, not the mission state machine, policy authority, effect broker, or final comparator.

### Essential variables

Ashby’s adaptive systems regulate essential variables within viable ranges. For autonomous coding, these should be explicit and multidimensional:[^35]

| Essential variable | Example viable range |
|---|---|
| Requirement satisfaction | All mandatory criteria evidenced or explicitly waived |
| Correctness | Selected targeted and regression tests pass |
| Workspace integrity | No undeclared or unauthorized effects |
| Security | No critical policy violations; risk below approved threshold |
| Scope discipline | Changes remain within justified impact boundary |
| Compatibility | Public contracts preserved or migration approved |
| Maintainability | Review findings below threshold; architecture rules satisfied |
| Resource use | Time, tokens, compute, and cost within budget |
| Epistemic integrity | Claims retain provenance; contradictions unresolved only if declared |
| Recoverability | Current work has a valid checkpoint and rollback path |
| Human control | Pause, inspect, veto, and escalation remain available |

Do not collapse these into one confidence score. A weighted scalar can conceal a catastrophic security failure behind good test performance. Use a vector of hard constraints, soft objectives, and uncertainty.

### Feedback hierarchy

The agent needs feedback at different time scales:

| Loop | Timescale | Examples |
|---|---|---|
| Tool loop | Seconds | Command exit, diagnostic, file change |
| Task loop | Minutes | Hypothesis tested, patch verified |
| Mission loop | Hours | Plan progress, integration, review |
| Project loop | Days/weeks | Maintainer acceptance, defects, architectural drift |
| System loop | Weeks/months | Model routing, policies, skills, evaluation design |

Each loop needs appropriate gain and delay handling. Immediate retries may be appropriate for transient provider errors but harmful for deterministic build failures. Production feedback should update strategy and evaluation, not retroactively rewrite historical evidence.

### Sensors and comparators

Sensors should be independent and heterogeneous:

- Git diff and tree state
- Compiler and type checker
- Test runner
- Static analyzer
- Security scanner
- Runtime telemetry
- Browser and UI observation
- Dependency and API compatibility analysis
- Human review
- External CI and production signals

A comparator maps observations to proof obligations and essential-variable ranges. The same model that generated a patch should not be the sole sensor or comparator for its correctness.

### Repository world model

Following the Good Regulator theorem, the repository model is core regulatory infrastructure rather than an optional retrieval plugin.[^12]

It should contain:

```text
Structural graph: files, symbols, references, imports, packages
Behavior graph: tests, coverage, runtime traces, API calls
Change graph: commits, blame, co-change, defects, ownership
Intent graph: requirements, ADRs, issues, project rules
Environment graph: dependencies, services, CI, deployment
Evidence graph: claims, tests, findings, change-set versions
Agent graph: capabilities, costs, reliability by task class
```

Every observation carries provenance and freshness. A patch updates the graph incrementally. Context compilation becomes a query over this model, not an uncontrolled concatenation of transcript and retrieved snippets.

### Multi-agent organization

Multi-agent research treats systems as organizations of autonomous actors with goals, dependencies, obligations, and global qualities; organization-oriented approaches seek to combine local autonomy with global assurance.[^36][^37]

The VSM synthesis requires:

- Agents organized around transformations, not personalities
- Explicit inter-agent dependencies
- Local autonomy within capability boundaries
- Independent workspaces
- Structured artifacts instead of prose handoffs
- System 2 coordination before parallelism
- System 3 resource and integration control
- System 3* audits
- System 4 environmental and architectural intelligence
- System 5 policy that agents cannot redefine

Agent communication should use typed artifacts:

```text
Finding
Hypothesis
Task proposal
Patch proposal
Test specification


---

## References

1. [On the history of Ludwig von Bertalanffy's “general ...](https://www.tandfonline.com/doi/abs/10.1080/03081079.2014.883743) - The history of “general system theory” is investigated in order to clarify its meanings, vocations, ...

2. [On the history of Ludwig von Bertalanffy's “General ...](https://www.tandfonline.com/doi/abs/10.1080/03081070601127961) - Ludwig von Bertalanffy was one of the first masterminds and advocates of a “general system theory”. ...

3. [EmergenceQuestions](https://arxiv.org/pdf/nlin.AO/0509049.pdf)

4. [Ten Questions about Emergence](https://arxiv.org/pdf/nlin/0509049.pdf)

5. [Homeostasis: The Underappreciated and Far Too Often ... - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7076167/) - The grand challenge to physiology, as was first described in an essay published in the inaugural iss...

6. [Cybernetics | IEEE Technology Navigator](https://technav.ieee.org/area/cybernetics/) - Cybernetics: Explore IEEE technology topics in this area including conferences, journals, standards,...

7. [Complex built-environment design: Four extensions to Ashby](https://variety-dynamics.org/images/docs/2007/TLTC_Kybernetes_preprint.pdf)

8. [W. Ross Ashby, Cybernetics and Requisite Variety (1956)](https://www.panarchy.org/ashby/variety.1956.html)

9. [An Introduction to Cybernetics (Ashby, 1956, 1957)](https://www.johnljerz.com/superduper/tlxdownloadsiteMAIN/id1562.html)

10. [Microsoft Word - 4 Dijkstra.doc](https://citeseerx.ist.psu.edu/document?repid=rep1&type=pdf&doi=4dcb34df4e37dbf548060a758dde08acae2d92f9)

11. [file://C:\Documents%20and%20Settings\Administrator\My%20Documen](https://journals.isss.org/index.php/proceedings50th/article/download/307/183/2021)

12. [TSYS_1970_v1_n1-4.pdf](http://www.theisticscience.com/papers/tree/BioRegulation/Conant-IJSS1970.pdf)

13. [A Primer For Conant And Ashby's Good-Regulator Theorem](https://cadia.ru.is/wiki/_media/public:t-720-atai:a_primer_for_conant_and_ashby_s_good-regulator_theorem.pdf)

14. [The purpose of second-order cybernetics - cepa.info](https://cepa.info/fulltexts/2294.pdf)

15. [Signs vol. 3: pp. 69-107, 2010](https://tidsskrift.dk/signs/article/download/26861/23621)

16. [Humberto Maturana and Francisco Varela's Contribution to ...](https://www.nesacenter.org/uploaded/conferences/FLC/2019/Handouts/Arpin_Humberto_Maturana_and_Francisco_Varela_Contribution_to_Media_Ecology_Autopoiesis.pdf)

17. [Cognitive Science Quarterly (2000) 1, 117-145](https://citeseerx.ist.psu.edu/document?repid=rep1&type=pdf&doi=ed7343e7350ab4e805e49c55ca8e4f4b07c5cc0a)

18. [Viable System Model - VSM Training](https://vsm-training.org/columns/) - About the VSM The Viable System Model (VSM) was first formulated in 1959 by Stafford Beer in his boo...

19. [[PDF] Viable Systems Modelling for climate change adaptation ... - MSSANZ](https://www.mssanz.org.au/modsim2011/H3/moore.pdf)

20. [Structural Design for Sustainability:](https://journals.isss.org/index.php/proceedings50th/article/download/339/88/1720)

21. [project Cybersyn and the intersection of information design ...](https://link.springer.com/article/10.1007/s00146-021-01346-2) - by S Vehlken · 2022 · Cited by 8 — In principle, however, the subsystems should act autonomously and...

22. [Designing freedom: Allende, Pinochet and the twin experiments in cyber-socialism and neoliberalism](https://www.tandfonline.com/doi/full/10.1080/03085147.2025.2513800) - During the twentieth century, cybernetics became entangled with the socialist and neoliberal transfo...

23. [Lancaster University - REF Impact Case Studies](https://impact.ref.ac.uk/casestudies/CaseStudy.aspx?Id=43586)

24. [Soft Systems Methodology - Institute for Manufacturing (IfM)](https://www.ifm.eng.cam.ac.uk/research/dstools/soft-systems-methodology/) - Soft Systems Methodology

25. [Reflective Applications of Soft Systems Methodology (SSM ...](https://link.springer.com/article/10.1007/s11213-025-09748-9?error=cookies_not_supported&code=cc205e18-757b-4fa9-85f5-076313a7bb00) - Reflective Applications of Soft Systems Methodology (SSM) Across Contexts. Soft Systems Methodology ...

26. [Rf.sEARCH](https://www.caluniv.ac.in/dj/BS-Journal/V-24/soft_systems.pdf)

27. [Soft systems methodology: A thirty year retrospective](https://www.betterevaluation.org/tools-resources/soft-systems-methodology-thirty-year-retrospective) - Soft Systems Methodology (SSM) can be used to gain understanding of complex relationship drive situa...

28. [Modeling Dynamics in Agile Software Development](https://calhoun.nps.edu/server/api/core/bitstreams/d9500920-cd00-42f1-85f2-b429eb0a9d93/content)

29. [The Systems Thinker  V16N2M](https://thesystemsthinker.com/wp-content/uploads/pdfs/160405pk.pdf)

30. [A Visual Approach to Leverage Points - The Donella Meadows Project](https://donellameadows.org/a-visual-approach-to-leverage-points/) - We are translating Dana's classic "Leverage Points" framework into a broadly-understood visual langu...

31. [DANA MEADOWS AND LEVERAGE POINTS - Sites at Dartmouth](https://sites.dartmouth.edu/climateaction/dana-meadows-and-leverage-points/)

32. [chris argyris, double-loop learning and organizational ...](https://is.muni.cz/el/1423/podzim2008/HEN572/um/6787670/200501_infed_argyris.pdf)

33. [Revitalizing double‐loop learning in organizational ...](https://onlinelibrary.wiley.com/doi/10.1111/emre.12615)

34. [[PDF] double-loop-learning-in-organizations Argylis](https://cmapspublic3.ihmc.us/rid=1NT8Y36L7-185BXTZ-1GHR/double-loop-learning-in-organizations%20Argylis.pdf)

35. [Interpreting Ashby -But which One? David Vernon](http://www.vernon.eu/publications/13_Vernon_Constructivist_Foundations_Franchi.pdf)

36. [[PDF] Socio-Intentional Architectures for Multi-Agent Systems: the Mobile ...](https://ceur-ws.org/Vol-57/id-15.pdf)

37. [[PDF] Modelling Multi-Agent Systems with Organizations in Mind](https://www.scitepress.org/Papers/2008/17379/17379.pdf)

