# Kosmos-LMS Gap Audit

**Repository:** `rmholston420/kosmos-lms`  
**Audited revision:** `4d230b84102c1c13eade59d1fc848a19c7654a2e`  
**Revision date:** 2026-09-26  
**Audit date:** 2026-09-26  
**Verdict:** **The repository is feature-rich but not functionally closed.** The strongest gaps are not missing architecture documents; they are incomplete execution paths, security boundaries, release verification, package integrity, and an audit process that classifies many preserved stubs as complete.

## Executive assessment

The repository’s ADR-141 ledger declares the preservation audit fully discharged at `154 P / 0 D / 0 T`, but direct inspection still finds numerous operational gaps. The completion claim appears to mean **donor behavior was preserved**, not **the behavior is production-complete**. This distinction matters because the preserved behavior includes scaffold generation, simulated self-repair, deferred anomaly detectors, in-memory persistence, unmapped UI methods, and fail-open execution.

The latest revision contains 1,049 tracked files, 669 Python files, 231 conventionally named Python test files, one CI workflow, a 10,015-line `kernel/app.py`, and 182 application route decorators in that file. Static inspection found 94 live `NotImplementedError` or related occurrences outside test and vendored trees, 71 backend sites that encode errors in normal return dictionaries, 449 broad `except Exception` catches, three explicitly unmapped frontend methods, four tracked database sidecars, and no CI coverage, dependency-audit, secret-scan, or wheel-smoke step.

### Priority matrix

| Priority | Gap | Consequence | Release effect |
|---|---|---|---|
| P0 | No authentication/authorization boundary around mutating APIs and WebSockets | Any process or browser origin reaching the loopback service can invoke privileged operations | Stop-ship |
| P0 | PTY and raw tool execution remain host-capable | Local command execution and filesystem mutation are exposed through HTTP/WebSocket surfaces | Stop-ship |
| P0 | CI cannot truthfully establish repository health | Tests are skipped after lint failure; the summary remains informational | Stop-ship |
| P0 | Built wheel omits 63 importable package trees | Distribution builds but cannot import the kernel or major plugins | Stop-ship |
| P1 | Core coding executor emits TODO scaffolds and tautological tests | “Execution” can report artifacts without implementing requested behavior | Blocks autonomous-coding claims |
| P1 | Self-repair is simulated and self-modification is propose-only | Recovery flags can change without any actual repair action | Blocks self-healing claims |
| P1 | Three Phrouros detectors and durable trace ingestion remain stubs | Major observability promises are structurally present but nonfunctional | Blocks full observability claims |
| P1 | Test topology is split and root collection is broken | Neither local default nor CI command validates the whole repository | Blocks dependable regression control |
| P1 | API error semantics and readiness are inconsistent | Clients can receive HTTP 200 for unavailable or failed operations | Blocks reliable automation |
| P2 | UI contains unmapped methods and placeholder slots | Visible surfaces can fail loudly or render empty shells | Product-completeness gap |
| P2 | Architecture and exception handling are over-centralized | Reviewability, ownership, and failure diagnosis deteriorate | Maintainability debt |
| P2 | ADR and porting ledgers retain stale stage claims | Completion metrics can hide deferred implementation | Governance gap |

## Methodology

The audit used five passes:

1. **Repository inventory:** revision, file counts, route counts, package discovery, test topology, workflows, ADR status, tracked runtime artifacts.
2. **Implementation-gap scan:** TODO/FIXME markers, explicit `NotImplementedError`, skeleton detectors, simulation-only behavior, no-op and in-memory defaults, unmapped frontend methods, placeholder panels, error swallowing.
3. **Executable verification:** isolated editable installation, test collection, Ruff, mypy, Bandit, wheel build, and clean-wheel imports.
4. **Control-plane review:** CI dependency graph, summary behavior, authentication indicators, mutating routes, WebSocket exposure, health semantics, package/dependency declarations.
5. **Claim reconciliation:** comparison of ADR-141’s “fully discharged” assertion with current executable behavior and the porting ledger’s remaining `PLANNED` and `DEFERRED` entries.

The audit distinguishes three categories:

- **Implemented:** behavior performs the claimed operation and is validated through a representative execution path.
- **Structurally present:** interfaces, routes, DTOs, or preserved donor behavior exist, but production behavior is simulated, scaffolded, in-memory, disabled, or incomplete.
- **Deferred:** source explicitly refuses, raises, or documents that implementation awaits another ADR or stage.

## Security-boundary gaps

### Unauthenticated control plane

The kernel exposes 182 routes directly from `kernel/app.py`: 101 GET, 67 POST, 6 DELETE, 4 PATCH, 3 WebSocket, and 1 PUT. Eighty-one are mutating or WebSocket surfaces. These include kill/resume, approval resolution, memory deletion, skill creation/execution, schema application, database DDL/DML/restore, tool execution, session mutation, self-repair, configuration mutation, terminal access, event streaming, and algedonic streaming.

No application-wide authentication, operator token, RBAC dependency, CSRF control, or rate limiter was found in the kernel route composition. Loopback binding is a useful deployment restriction but is not an authorization model: browsers, extensions, other local processes, SSH forwarding, reverse proxies, and future configuration changes can all cross that assumption.

WebSockets do not provide built-in authentication, and OWASP recommends explicit origin allowlisting and authentication checks on every handshake to prevent cross-site WebSocket hijacking. The three WebSocket routes therefore need the same operator identity and capability enforcement as the HTTP mutation plane.[^1]

### PTY and tool execution

`/ws/pty` forks a PTY and starts the service user’s shell. `/api/tools/{tool_name}/execute` dispatches directly through the tool registry. The registered sandbox provider supports shell execution and host filesystem operations; prior audit results also established `shell=True`, root-default filesystem scope, and automatic `sudo -n` retry behavior in that provider.

The presence of a safer sandbox adapter elsewhere in the repository does not secure a route that bypasses it. The gap is composition, not absence of technology: every command-bearing surface must route through one constrained adapter and one operator-authorization policy.

### Missing security automation

The sole workflow contains no Bandit job, dependency audit, npm audit, CodeQL, secret scanner, SBOM generation, container scan, or security-regression suite. Local Bandit execution found 4,072 findings across the broad scan—4,009 low, 60 medium, and 3 high—including two high-severity `shell=True` findings in the tool sandbox provider and one in the donor sandbox executor.

NIST’s SSDF recommends automated executable-code security testing and continuous code analysis, with discovered issues recorded and triaged in the development workflow. The repository currently has neither the automated gate nor issue templates/security policy needed to make that loop durable.[^2][^3]

### Required controls

- Introduce an operator-authentication middleware covering all `/api/*` mutations and every WebSocket handshake.
- Add capability scopes: `observe`, `approve`, `mutate_workspace`, `execute_process`, `admin_database`, `operate_kernel`.
- Validate WebSocket `Origin` against an explicit allowlist; reject missing/untrusted origins.
- Disable PTY, tool execution, database mutation, and schema mutation by default.
- Eliminate `shell=True`, sudo retry, and `/` filesystem defaults from the HTTP-reachable provider.
- Apply payload, output, connection, process, and rate limits.
- Add audit events before and after every security-sensitive operation; OWASP recommends audit logging around security events and semantically appropriate status codes rather than treating failures as HTTP 200.[^4]
- Add CI secret scanning, SAST, dependency auditing, SBOM generation, and security regression tests.

## Autonomous-coding gaps

### Executor generates scaffolds, not implementations

`plugins/tektos/executor/engine.py` describes itself as a spec executor, but its generation helpers emit:

- Python modules containing `# TODO: Implement ...`, an empty constructor, and `execute()` returning `{}`.
- Test modules whose assertions are `assert True`.
- Configuration and documentation artifacts containing TODO markers.

This behavior is explicitly tested, so it is not an accidental defect. The current executor can create syntactically plausible artifacts and execution records without satisfying a requested specification. This is a material semantic gap between “artifact generation” and “autonomous coding.”

### Planner and decomposer depth

The task decomposer is deterministic keyword dispatch over phrases such as `build`, `write`, `regex`, and `download`. The planner pipeline documents itself as pure heuristic. The hierarchical orchestrator can call `LLMPort.chat`, but it deliberately falls back to donor template strings when the LLM is absent or fails.

Deterministic fallback is desirable for availability, but the system needs an explicit capability/status contract so a heuristic fallback cannot be mistaken for model-planned execution. Every run should report `reasoning_backend`, `execution_backend`, `sandbox_strength`, and `degradation_reasons` in a machine-verifiable result envelope.

### Tool recovery omitted

The executor module explicitly records that `execute_with_recovery` and mutable tool-performance statistics were rejected at the current stage. Consequently, the architecture has routing but lacks a complete recovery loop linking failure classification, alternate-tool selection, retry budgets, verification, and durable outcome learning.

### Closure criteria

A coding task should not be marked successful unless:

- Generated source contains no unresolved generated TODOs or placeholder bodies.
- Generated tests contain no unconditional success assertions.
- The requested acceptance tests run inside the constrained sandbox.
- At least one independent verifier checks behavior against the original request.
- The run records exact files changed, commands executed, test results, diagnostics, and degradation state.
- Failure to obtain an LLM, sandbox, or verifier changes the run status to `degraded` or `blocked`, never silent success.

## Self-repair gaps

### Propose-only self-modification

`SelfImprovementProposer.apply()` and `SelfRepairProposer.apply()` always raise `NotImplementedError` because ADR-090 remains proposed/deferred. The approval, memory, and event plumbing is present, but no approved proposal can cross into an implementation adapter.

This is a legitimate safety decision, but it means the product should claim **self-repair proposal generation**, not autonomous self-repair or self-improvement.

### Simulated repair strategies

The self-repair strategy module states that built-in strategies mutate context recovery flags without syscalls. It stamps results as `[simulated]`; strict mode raises unless a real `RepairEffector` is supplied. No production wiring of `set_effector()` was found.

A simulation is useful for exercising policy and UI behavior, but simulated success must not affect operational health. Separate statuses should be used: `proposed`, `simulated`, `approved`, `applied`, `verified`, and `rolled_back`.

### Missing repair transaction model

Before ADR-090 is ratified, the design should define:

- Workspace snapshots and rollback handles.
- Allowed mutation scope and immutable protected paths.
- Approval binding to exact diff/hash, not just an intention identifier.
- Time-bounded execution capability.
- Independent post-apply verification.
- Automatic rollback after verification failure.
- Durable lineage from anomaly → diagnosis → proposal → approval → application → verification.

## Observability gaps

### Deferred Phrouros detectors

Three detectors remain explicit skeletons:

- `ModelSwapSloDetector`
- `StubDegradationDetector`
- `BusFactor1Detector`

Each `detect()` and `build_payload()` raises `DetectorNotImplementedError`. Their documentation still references future Stage 3+ or Stage 6.5 signals even though the repository now declares a Stage 14 close-out and an audit fully discharged.

### Durable trace feed absent

`InMemoryTraceFeedAdapter` is the boot default. `LangfuseTraceFeedAdapter` remains a stub whose operations raise `NotImplementedError`. Restarting the kernel therefore loses the default trace feed, and external trace ingestion is not available through the declared adapter.

### Error swallowing

The production tree contains 449 broad `except Exception` catches and numerous paths that return `None`, `[]`, `{}`, or continue after logging. Some are appropriate at shutdown or optional telemetry boundaries, but the volume makes operational fault isolation difficult and increases the probability that partial failure is reported as healthy degradation.

Each broad catch should be classified as one of:

- **Expected optional failure:** typed exception, metric, structured degradation reason.
- **Retryable dependency failure:** retry budget plus circuit state.
- **Fatal consistency failure:** fail startup or fail the operation.
- **Shutdown cleanup:** debug logging only, but counted and surfaced if repeated.

## Persistence gaps

The default boot graph still uses several in-memory or no-op components:

- In-memory approval storage.
- In-memory trace feed.
- In-memory temporal index.
- In-memory session adapter fallback.
- No-op relational memory fallback.
- No-op AMG policy.
- In-memory vector and stream backends in the Zetesis “real” factory.
- Stub OpenTelemetry backend in the Zetesis factory.

These defaults optimize development and graceful startup, but they make restart behavior and durability dependent on optional environment wiring. A local-first system needs a declared **durability profile** rather than silent fallback.

Recommended profiles:

| Profile | Intended use | Required behavior |
|---|---|---|
| `dev-ephemeral` | Tests and demos | In-memory allowed; UI displays EPHEMERAL badge |
| `local-durable` | Normal workstation use | SQLite/PostgreSQL/filesystem persistence required; startup fails on unavailable required stores |
| `full-stack` | Colossus deployment | PostgreSQL, durable event stream, persistent trace feed, real vector/memory adapters |
| `safe-observer` | Diagnostics | Read-only, no PTY/tools/schema/database mutation |

## API-contract gaps

### Error dictionaries at HTTP 200

Seventy-one return sites in `kernel/app.py` and plugin APIs return dictionaries containing `error` rather than raising a corresponding HTTP error. Examples include uninitialized thermal, metabolism, voice, memory, dreamtime, skills, database, Hindsight, orchestrator, and self-repair subsystems.

This creates ambiguous automation: transport success and operation failure share the same status. OWASP recommends semantically appropriate HTTP status codes, including 503 for temporarily unavailable services and 501 for operations not implemented.[^4]

Adopt a single error envelope:

```json
{
  "error": {
    "code": "SUBSYSTEM_UNAVAILABLE",
    "message": "Relational memory is not initialized",
    "retryable": true,
    "subsystem": "relational_memory",
    "correlation_id": "..."
  }
}
```

Use 400/409 for invalid state transitions, 401/403 for access failures, 404 for absent resources, 422 for validation, 429 for limits, 501 for intentionally unimplemented operations, and 503 for unavailable dependencies.

### Health is not readiness

The workflow waits for `/health` to return 200 before E2E tests, while many subsystems are permitted to be absent or degraded. Separate endpoints are needed:

- `/health/live`: process event loop responds.
- `/health/ready`: mandatory profile dependencies are available.
- `/health/degraded`: complete typed subsystem matrix.
- `/health/startup`: migrations and boot tasks completed.

## Frontend gaps

### Unmapped client operations

The Gnosis client explicitly stubs `getCorpusDetail`, `getProvenance`, and `traverse` through `_unmapped()`. Existing call sites therefore fail deliberately rather than reaching a backend route.

### Placeholder panels

`PanelGrid` still returns `PlaceholderPanel` for unregistered slots and for registered slots without a realized component. This is useful shell behavior, but a registered descriptor should not be counted as a completed UI surface until its lazy module resolves to a functional component.

### Missing frontend quality gate

The CI workflow runs `npm run lint`, but `ui/package.json` has no `lint` script and does not declare ESLint. It also lacks a `typecheck` script. These are contract gaps between the workflow and the project manifest, not merely current lint debt.

Required scripts:

```json
{
  "scripts": {
    "lint": "eslint . --max-warnings=0",
    "typecheck": "tsc --noEmit",
    "test:e2e": "playwright test",
    "build": "next build"
  }
}
```

## Test-strategy gaps

### Two disjoint test universes

The repository’s `testpaths` points at `ports`, `adapters`, `kernel`, `plugins`, and `ops`, while CI invokes `pytest tests/`. Pytest documents that `testpaths` controls default discovery when no explicit path is supplied. Therefore:[^5][^6]

- Plain `pytest` omits the root `tests/` tree.
- CI’s explicit `pytest tests/` omits colocated adapter/plugin tests.
- Neither command validates all repository tests.

Static counting found approximately 842 test definitions under root `tests/`, 1,767 under configured trees, and 3,674 across all conventionally discovered non-vendored files. Counts include parametrized and helper-like definitions differently than Pytest’s final item count, but they clearly establish that the suites are materially disjoint.

### Root collection is non-portable

`tests/kernel/test_adr141_s133_axioms_routes.py` copies data from `~/dev/kosmos-lms/plugins/tektos/axioms`. In a clean clone, root-suite collection stops with `FileNotFoundError` for `/home/user/dev/kosmos-lms/plugins/tektos/axioms`.

Replace it with a path relative to `__file__` or an `importlib.resources` lookup. Add a clean-checkout test that rejects hard-coded home/workspace paths.

### CI tests are downstream of lint

`python-tests` declares `needs: [python-lint]`. GitHub documents that if a prerequisite fails or is skipped, jobs needing it are skipped unless a condition overrides that behavior. Test execution should be independent of formatting and lint so a lint regression cannot hide runtime failures.[^7][^8]

### Informational summary can be green

The summary job uses `if: always()` and only echoes upstream statuses. It never exits nonzero after a failed or skipped requirement. GitHub’s job model exposes dependency results precisely so aggregate gates can check them.[^7]

### No risk-weighted coverage gate

There is no CI coverage command or threshold. A single repository-wide percentage would still be insufficient; command execution, authentication, approval, schema/database mutation, state persistence, and recovery need higher thresholds and branch coverage than low-risk DTO code.

## Static-quality gaps

At the audited revision:

- Ruff broad scope reported 917 errors, 659 automatically fixable.
- Mypy over `ports` and `kernel` failed with unresolved names, missing `aiohttp`, invalid assignments, optional dereferences, and conflicting model types.
- The project’s declared dev extra does not include all packages needed by its own configured test tree.
- The workflow’s lint scope omits `adapters`, `plugins`, and `ops` even though these contain most implementation code.

The immediate objective should not be suppressing all findings. Establish a clean baseline by fixing correctness-affecting errors first, then automatically formatting/fixing safe rules, and finally enabling ratcheted “no new debt” enforcement.

## Packaging gaps

The wheel builds successfully but is unusable. The explicit Setuptools list contains 52 packages while the repository contains at least 111 non-test importable package directories. Sixty-three are omitted, including `kernel`, relational-memory adapters, sandbox/vision/voice adapters, most Tektos engines, and Zetesis.

Clean-wheel imports fail for:

- `kernel.app`
- `plugins.tektos.agent`
- `plugins.zetesis.plugin`
- `adapters.relational_memory.postgres.adapter`

Setuptools disables automatic discovery when packages are explicitly configured. Its documented `find` directive supports scanning with include/exclude patterns and is more appropriate for this repository’s scale.[^9][^10][^11]

Add a wheel gate that installs into a fresh virtual environment and imports every production package plus boots the application in a safe test profile.

## Dependency gaps

The manifest has broad lower bounds for most dependencies and no root project lockfile. Runtime requirements are divided inconsistently:

- FastAPI and Uvicorn are optional despite `kernel.app` and the systemd service requiring them.
- `aiohttp` is imported but undeclared.
- PostgreSQL tests require `asyncpg`, but CI installs only `.[dev]`.
- UI tracks both npm and pnpm lockfiles while CI uses npm.
- No dependency audit executes in CI.

Choose one Python lock workflow and one Node package manager. Define `runtime`, `dev`, `postgres`, `eval`, `ingest`, and deployment profiles with tested dependency closure.

## Architecture gaps

### Composition-root monolith

`kernel/app.py` is 10,015 lines and contains 182 application route decorators. It combines boot wiring, adapters, lifecycle, security middleware, control-plane APIs, database administration, tools, skills, sessions, RAG, voice, vision, PTY, WebSockets, UI serving, and compatibility surfaces.

This does not invalidate the ports/adapters architecture, but it centralizes almost every trust boundary and makes review difficult. Extract bounded-context routers and boot modules while retaining `kernel/app.py` as a thin composition root.

Recommended order:

1. `kernel/security/operator_auth.py`
2. `kernel/routers/terminal.py`
3. `kernel/routers/tools.py`
4. `kernel/routers/database.py`
5. `kernel/routers/sessions.py`
6. `kernel/routers/skills.py`
7. `kernel/routers/inference.py`
8. `kernel/routers/observability.py`
9. `kernel/boot/profile.py`
10. `kernel/boot/services.py`

### Failure-policy inconsistency

The code mixes fail-open, fail-closed, empty-result degradation, `NotImplementedError`, no-op adapters, and HTTP-200 error dictionaries. Each port needs a declared failure policy:

| Port class | Default policy |
|---|---|
| Security/approval/sandbox/secrets | Fail closed |
| Mutation/state/database | Fail operation with typed error |
| Read-only observability | Degrade with explicit stale/unavailable metadata |
| Optional enrichment | Return partial result with degradation reasons |
| Shutdown cleanup | Best effort with structured diagnostic |

## Governance and documentation gaps

### Completion metric mismatch

The ADR-141 close-out classifies 154 audited items as preserved, with zero deferred or tombstoned. Yet the repository still contains:

- A formally deferred ADR-090.
- Three skeleton anomaly detectors.
- A stub Langfuse trace adapter.
- Propose-only self-modification.
- Simulation-only self-repair strategies.
- Scaffold-only executor output.
- Unmapped Gnosis client methods.
- Porting-ledger entries marked `PLANNED` and `DEFERRED`.

The likely root cause is that the audit’s unit of success is **preservation of donor semantics**, even when donor semantics are themselves stubs or simulations. Add a second dimension:

| Preservation | Production readiness | Meaning |
|---|---|---|
| Preserved | Complete | Behavior retained and operationally complete |
| Preserved | Partial | Behavior retained but only heuristic, simulated, or ephemeral |
| Preserved | Stub | Interface retained; operation deliberately unavailable |
| Replaced | Complete | Donor behavior superseded by validated implementation |
| Excluded | N/A | Intentionally absent with documented rationale |

### Missing project governance files

Only `.github/workflows/ci.yml` exists under `.github`. The repository lacks `SECURITY.md`, contribution guidance, issue templates, Dependabot configuration, CodeQL configuration, and a documented vulnerability-reporting path.

## Remediation plan

### Phase 0: Containment

- Disable PTY and HTTP tool execution by default.
- Add operator authentication and WebSocket origin validation.
- Remove host-shell provider wiring from remotely reachable routes.
- Add regression tests proving unauthenticated and cross-origin access is rejected.
- Make the aggregate CI job fail unless every required job succeeds.

### Phase 1: Truthful verification

- Fix the absolute test path.
- Establish one canonical all-suite command.
- Decouple tests from lint.
- Add frontend lint and typecheck scripts.
- Add wheel smoke tests.
- Add coverage, Bandit, dependency audits, secret scanning, and SBOM generation.
- Make clean checkout + clean virtual environment the only accepted release test context.

### Phase 2: Functional closure

- Replace executor TODO scaffolds with LLM/tool-driven implementation and independent verification.
- Implement or explicitly remove the three Phrouros skeleton detectors.
- Implement durable trace ingestion.
- Ratify ADR-090 or narrow product claims to propose-only self-modification.
- Wire a real repair effector with transaction, approval, verification, and rollback.
- Finish Gnosis detail/provenance/traversal mappings and realized panel components.

### Phase 3: Durability and release engineering

- Define boot profiles and required dependencies.
- Replace silent in-memory fallbacks in durable profiles.
- Repair Setuptools discovery and dependency declarations.
- Add a root lockfile and select one UI package manager.
- Remove tracked database sidecars and add migration/backup/restore verification.
- Publish signed artifacts and an SBOM only after clean-wheel and full-profile smoke gates pass.

### Phase 4: Architecture reduction

- Decompose `kernel/app.py` by trust boundary and bounded context.
- Replace broad exception handling with typed policy.
- Introduce typed operation-result and degradation envelopes.
- Generate route, dependency, and readiness documentation from code.

## Canonical release gate

```bash
set -euo pipefail

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e '.[dev,ui,postgres]'
.venv/bin/pip check

.venv/bin/ruff check kernel ports adapters plugins ops scripts tests
.venv/bin/ruff format --check kernel ports adapters plugins ops scripts tests
.venv/bin/mypy kernel ports adapters plugins ops

.venv/bin/pytest \
  tests ports adapters kernel plugins ops \
  --strict-config --strict-markers \
  --cov=kernel --cov=ports --cov=adapters --cov=plugins --cov=ops \
  --cov-branch --cov-report=term-missing --cov-fail-under=75

.venv/bin/bandit -r kernel ports adapters plugins ops scripts -c pyproject.toml
.venv/bin/pip-audit --progress-spinner off

git grep -nE '(/home/[^/]+/|~/dev/|/Users/[^/]+/)' \
  -- '*.py' '*.toml' '*.yml' '*.yaml' && exit 1 || true

(
  cd ui
  npm ci
  npm run lint
  npm run typecheck
  npm run build
  npm run test:e2e
  npm audit --omit=dev
)

.venv/bin/python -m build
python3.12 -m venv /tmp/kosmos-wheel-smoke
/tmp/kosmos-wheel-smoke/bin/pip install dist/*.whl
/tmp/kosmos-wheel-smoke/bin/python - <<'PY'
import kernel.app
import plugins.tektos.agent
import plugins.zetesis.plugin
import adapters.relational_memory.postgres.adapter
print('wheel smoke: OK')
PY
```

## Release acceptance criteria

The repository should not be labeled complete or release-ready until all conditions hold:

- Every privileged HTTP and WebSocket operation requires an authenticated capability.
- PTY and command execution are disabled by default and workspace-confined when enabled.
- No `shell=True` or sudo retry exists in an HTTP-reachable provider.
- One canonical test command collects both root and colocated suites from a clean clone.
- Required CI checks cannot become green after a required upstream failure or skip.
- Ruff, formatting, mypy, frontend lint, frontend typecheck, and E2E pass.
- Wheel installation and imports pass in a clean environment.
- No generated implementation contains TODO bodies or tautological tests.
- Self-repair reports `simulated` unless a real effect, verification, and rollback path executed.
- Deferred detectors and adapters are either implemented, removed, or visibly classified as unavailable.
- Durable profiles do not silently substitute in-memory/no-op stores.
- Error responses use typed envelopes and appropriate HTTP status codes.
- Security, dependency, secret, SBOM, and coverage gates run continuously.
- ADR close-out metrics distinguish preservation from production readiness.

## Final finding

Kosmos-LMS has substantial architectural and implementation depth, but its central gap is **semantic overstatement**: preserved interfaces, donor-compatible behavior, route presence, and passing narrow tests are often treated as equivalent to completed end-to-end capability. The next milestone should therefore be named **functional closure and containment**, not another preservation stage. Success should be measured by authenticated execution, durable state, clean installation, independent behavioral verification, and one truthful release gate.

---

## References

1. [WebSocket Security - OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html) - Website with the collection of all the cheat sheets of the project.

2. [Appendix C SSDF Analysis New — Secure Software ...](https://pages.nist.gov/nccoe-devsecops/appendix-c.html)

3. [Secure Software Development Framework (SSDF) Version ...](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218.pdf)

4. [REST Security - OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html) - Website with the collection of all the cheat sheets of the project.

5. [Configuration - pytest documentation](https://docs.pytest.org/en/stable/reference/customize.html)

6. [API Reference - pytest documentation](https://docs.pytest.org/en/stable/reference/reference.html)

7. [Using jobs in a workflow - GitHub Docs](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-jobs) - Use workflows to run multiple jobs.

8. [Defining Prerequisite Jobs](https://docs.github.com/en/enterprise-server@3.19/actions/how-tos/write-workflows/choose-what-workflows-do/use-jobs) - Use workflows to run multiple jobs.

9. [Package Discovery and Namespace Packages](https://setuptools.pypa.io/en/latest/userguide/package_discovery.html) - Setuptools provides powerful tools to handle package discovery, including support for namespace pack...

10. [Quickstart - setuptools 82.0.1 documentation](https://setuptools.pypa.io/en/latest/userguide/quickstart.html?highlight=FIND_PACKAGES)

11. [Configuring setuptools using pyproject.toml files](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html)

