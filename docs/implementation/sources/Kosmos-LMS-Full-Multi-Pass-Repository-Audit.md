# Kosmos-LMS Full Multi-Pass Repository Audit

**Repository:** `rmholston420/kosmos-lms`  
**Audit date:** September 26, 2026  
**Authoritative branch:** `main`  
**Audited code revision:** `b0fd6626097fe3e6d1e42932ec9195d201891a4f`  
**Later observed HEAD:** `c8215cbf46a06e5ddf2190f83dfa1517830e008b`  
**HEAD delta:** One documentation-only line; all code findings remain applicable  
**Priority order:** Reliability, architecture, security, roadmap

## Executive assessment

Kosmos-LMS is a substantial, unusually well-documented local-first agent system with a real ports/adapters/plugin architecture, extensive ADR coverage, approximately 2,259 Python test definitions, and significant working behavior. It is not release-ready at the audited revision.

The dominant problem is no longer lack of implementation. It is the mismatch between implemented capability and operational assurance. The repository contains two unauthenticated host-command execution paths, persistently failing CI, mutually incomplete test scopes, a broken wheel, known vulnerable dependencies, severe type and lint debt, and contradictory deployment documentation.

**Overall grade: C-.** The system is conditionally functional and architecturally promising, but the current `main` branch should be treated as a **no-go for release or broader network exposure** until the execution plane and CI contract are repaired.

## Scope and method

The audit used multiple independent passes rather than relying on repository claims or logs:

- Cloned the public default branch and pinned the audited commit.
- Inventoried source, tests, CI, dependencies, documentation, vendored assets, runtime state, and generated artifacts.
- Installed the project into a fresh Python 3.12 virtual environment.
- Ran configured and CI-specific pytest scopes.
- Ran Ruff, Ruff format, mypy, Bandit, pip-audit, npm audit, TypeScript checking, frontend build, and package builds.
- Calculated raw and production-only coverage.
- Built the Python wheel, installed it into a clean environment, and attempted core imports.
- Inspected GitHub Actions status for the audited revision and preceding `main` runs.
- Reviewed command-execution, PTY, sandboxing, authentication, service hardening, SQL construction, secrets, and dependency exposure.
- Performed static package-graph and import-cycle analysis.
- Compared README, systemd, CI, `pyproject.toml`, code behavior, and current repository structure.

Repository code and reproducible execution results were treated as authoritative over BUILD_LOG, README, ADR completion declarations, and CI summary labels.

## Repository profile

| Metric | Result |
|---|---:|
| Tracked files | 1,049 |
| Python files | 669 |
| TypeScript/JavaScript files | 76 |
| Markdown files | 210 |
| Python test definitions | Approximately 2,259 |
| Colocated test files outside root `tests/` | 126 |
| Root `tests/` files | 105 |
| Commits at audited revision | 295 |
| Commits during preceding seven days | 136 |
| Production Python statements measured | 26,705 |
| Production-only coverage | 61.28% |
| Raw coverage including tests | 74.31% |

## Scorecard

| Area | Grade | Assessment |
|---|---:|---|
| Functional depth | B+ | Large amount of implemented and exercised behavior |
| Python tests | B | 1,826 tests passed after installing declared PostgreSQL support |
| Test strategy | C | Two disconnected test universes and major CI blind spots |
| Reliability | C- | CI persistently red; deployment contract contains stale dependencies |
| Security | D | Two unauthenticated command-execution surfaces |
| Architecture | C+ | Strong boundaries in principle; 10,015-line application monolith in practice |
| Frontend | C- | Production compilation works, but lint is absent and type checking fails |
| Packaging | F | Wheel builds but omits essential runtime packages |
| Dependencies | D+ | Known vulnerabilities, missing runtime dependencies, no project-level Python lock |
| Documentation | C | Excellent ADR depth but contradictory operational state |
| Overall | **C-** | Strong system constrained by weak verification and containment |

## Stop-ship security findings

### Unauthenticated PTY WebSocket

`kernel/app.py` exposes `/ws/pty`. The handler accepts a WebSocket, forks a PTY, and executes the operator account's login shell. The route has no authentication, capability check, feature flag, approval gate, or WebSocket `Origin` validation.

The systemd service binds Uvicorn to `127.0.0.1`, which reduces exposure but does not close the boundary. A malicious page opened in the local browser may attempt cross-site WebSocket access; any compromised local process can connect; and later SSH forwarding, proxying, container exposure, or bind-address changes could make the route remotely reachable.

**Required remediation:**

- Disable the route by default.
- Require an authenticated operator capability distinct from normal application access.
- Validate WebSocket `Origin` against a strict allow-list.
- Require an explicit environment flag for route registration.
- Execute a restricted shell through `TektosSandboxAdapter`, not the host login shell.
- Apply idle timeout, session concurrency limits, audit events, process-group termination, and output bounds.

### Unauthenticated tool execution

`POST /api/tools/{tool_name}/execute` directly invokes `ToolRegistry.execute()` without authentication, authorization, APEX approval, or per-tool policy enforcement at the HTTP boundary.

The boot path injects `plugins.tektos.tools.sandbox_provider.SandboxProvider`, whose default filesystem root is `/`. Its bash handler uses `shell=True`, runs as the kernel service user, and automatically retries some permission failures with `sudo -n`. The same registry exposes file read, write, delete, directory, and search operations.

A safer `TektosSandboxAdapter` already exists with argv-first execution, resource limits, optional network namespaces, event publication, and memory records. The high-risk HTTP route does not use it.

**Required remediation:**

- Remove the direct `SandboxProvider` HTTP execution path.
- Route all execution through `SandboxPort` and `TektosSandboxAdapter`.
- Default the filesystem root to the selected repository workspace, never `/`.
- Remove automatic sudo retry.
- Require APEX approval for shell execution, file mutation, deletion, full network, and privilege-sensitive actions.
- Enforce argv-first execution; permit shell parsing only as a separately approved capability.
- Add symlink-escape, path traversal, command injection, environment leakage, and cancellation tests.

## CI and verification

### Audited GitHub run

The audited revision's workflow failed. Job status was:

| Job | Result |
|---|---:|
| Python lint | Failed |
| Python type check | Failed |
| Python tests | Skipped because lint failed |
| Port contract tests | Passed |
| Plugin isolation | Passed |
| Frontend build | Passed |
| Frontend lint | Failed |
| Frontend E2E | Failed |
| CI Summary | Reported success |

The last ten visible `main` workflow runs were failures. The `summary` job uses `if: always()` and prints dependency results but never exits nonzero. This makes the summary check green despite failed dependencies. GitHub Actions supports writing human-readable job summaries through `$GITHUB_STEP_SUMMARY`; the required aggregate gate must still signal failure with a nonzero exit or explicit failure command.[^1]

### Python quality gates

Reproducing the actual CI commands produced:

- `ruff check ports/ kernel/ tests/ scripts/`: 365 errors.
- Broad Ruff scan: 805 errors, 566 automatically fixable.
- CI-scope format check: 116 files would be reformatted.
- Broad format check: 281 files would be reformatted.
- `mypy ports/ kernel/`: 86 errors across 28 files.
- Broad mypy execution stops early because two evaluation fixtures resolve to duplicate `hello` modules.

The mypy findings include meaningful correctness risks: variables changing between `str` and `Path`, missing names, optional values dereferenced without checks, conflicting domain model classes, incorrect container typing, and undeclared imported packages.

### Split test universes

`pyproject.toml` configures these pytest roots:

```toml
testpaths = ["ports", "adapters", "kernel", "plugins", "ops"]
```

GitHub CI instead runs:

```bash
pytest tests/ -v --tb=short
```

Therefore:

- Plain `pytest` runs colocated component tests but omits root `tests/`.
- CI runs root `tests/` but omits most colocated adapter and plugin tests.
- Neither command verifies the complete repository.
- The primary CI test job is skipped whenever lint fails because it declares `needs: [python-lint]`.

The root suite currently fails during collection because `tests/kernel/test_adr141_s133_axioms_routes.py` hard-codes `/home/user/dev/kosmos-lms/plugins/tektos/axioms`. The configured suite had one environment-layout failure because a Stage 3.12 test expects Ruff and Bandit specifically under `.venv/bin/`.

### Full-suite result

After installing PostgreSQL support, the configured suite produced:

- 1,826 passed.
- 21 skipped.
- 1 failed.
- 6 warnings.

Exposing the audit virtual environment at the expected `.venv` path made the remaining Stage 3.12 test pass. This confirms that the underlying implementation is substantially healthier than CI suggests, while the verification contract is brittle and workspace-dependent.

## Coverage analysis

Raw coverage was 74.31%, but that figure includes test modules. Test files themselves were 96.53% covered, inflating the headline. Production-only coverage was 61.28%: 16,364 of 26,705 measured statements.

Important low-coverage production surfaces include:

| Component | Coverage |
|---|---:|
| `kernel/schema_evolution_full.py` | 0% |
| `kernel/session_state.py` | 0% |
| `kernel/evaluation_framework.py` | 0% |
| `kernel/tektos_prompt_sse.py` | 0% |
| `kernel/tektos_replay.py` | 0% |
| `kernel/tektos_telemetry.py` | 0% |
| `kernel/tektos_immune.py` | 0% |
| `plugins/tektos/tools/sandbox_provider.py` | 13.65% |
| `plugins/tektos/orchestrator/engine.py` | 17.79% |
| `kernel/skills/manager.py` | 18.05% |
| `kernel/skills/registry.py` | 19.95% |
| `kernel/rag_retriever.py` | 20.93% |
| `kernel/db_manager.py` | 21.85% |
| PostgreSQL relational-memory adapter | 23.91% |

Coverage is weakest around state, databases, orchestration, skill execution, and host-command execution—the areas with the highest operational and security cost.

## Dependency security

### DiskCache

The installed environment contains `diskcache==5.6.3`. The relevant advisory concerns unsafe pickle deserialization; an attacker able to write into the cache directory may obtain code execution when a victim later reads the cache.[^2][^3][^4]

Kosmos uses DiskCache in the repository-map subsystem under repository-controlled `.kosmos.repomap.cache.*` directories. That threat is material for an autonomous coding system because Tektos processes and modifies potentially untrusted repositories.

**Remediation:** avoid pickle-backed cache values, authenticate or recreate cache contents, place caches outside untrusted repositories, and reject cache directories with unsafe ownership or permissions.

### Frontend dependencies

The UI pins Next.js 16.2.11. `npm audit` reported one critical Next.js issue plus high-severity PostCSS and Sharp/libvips issues. Next.js has continued publishing security advisories and patched releases during 2026.[^5][^6][^7]

Static export reduces some server-side runtime exposure when only generated assets are deployed, but development servers, CI builds, and image-processing paths still require remediation. Upgrade to the latest compatible fixed Next.js release and rerun build, TypeScript, and Playwright verification.

### Bandit results

Bandit reported 209 findings:

| Scope | High | Medium | Low |
|---|---:|---:|---:|
| Production code | 2 | 48 | 120 |
| Tests | 0 | 12 | 18 |
| Vendored code | 1 | 0 | 8 |

The two high-severity production findings are the `shell=True` calls in `plugins/tektos/tools/sandbox_provider.py`. Forty-two production B608 findings identify dynamic SQL construction. These are not automatically 42 exploitable injection defects, but identifier interpolation, table selection, ordering, migrations, and user-derived expressions require an explicit allow-list audit.

## Packaging

The source distribution and wheel build successfully, but the resulting wheel is unusable.

A clean installation produced:

```text
import kernel.app
ModuleNotFoundError: No module named 'kernel'

import plugins.tektos.agent
ModuleNotFoundError: No module named 'plugins.tektos.tools'

import adapters.relational_memory.postgres.adapter
ModuleNotFoundError: No module named 'adapters.relational_memory'

import plugins.zetesis.plugin
ModuleNotFoundError: No module named 'plugins.zetesis'
```

The manually maintained `tool.setuptools.packages` list names 52 packages while at least 111 importable non-test package directories exist. Sixty-three package trees are omitted, including `kernel`, most Tektos engines, Zetesis, relational memory, sandbox, vision, voice, and thermal adapters. At the same time, numerous test modules are packaged.

**Remediation:** replace the static package list with setuptools package discovery, explicitly exclude tests and vendored evaluation fixtures, include required non-Python assets, and add a clean-wheel import/startup job to CI.

## Dependency model and reproducibility

The dependency declarations do not match runtime behavior:

- `kernel.app` requires FastAPI, but FastAPI is only in optional `ui`.
- The systemd service invokes Uvicorn, also only in `ui`.
- `kernel.mcp_client` imports `aiohttp`, which is undeclared.
- PostgreSQL test collection imports PostgreSQL support, but CI installs only `.[dev]`.
- Most Python dependencies have lower bounds but no lock or upper constraint.
- The only detected `uv.lock` belongs to vendored Open Deep Research, not Kosmos.
- The UI tracks both `package-lock.json` and `pnpm-lock.yaml`.

Define deployable groups such as `runtime`, `dev`, `postgres`, `hindsight`, `evaluation`, and `ingestion`; generate a root Python lock; use one Node package manager; and verify each supported installation profile independently.

## Frontend

Positive results:

- `npm ci` completed.
- Next.js compiled successfully.
- Static generation completed all 22 pages.
- GitHub's frontend-build job passed.

Defects:

- `npm run lint` fails because no `lint` script exists.
- ESLint is not declared.
- Standalone TypeScript checking fails in `tests/03-tektos-plan-workflow.spec.ts` because `string | undefined` is passed where `undefined` is prohibited.
- Hosted Playwright E2E failed.
- The E2E workflow installs `.[dev]` and then invokes Uvicorn, which is declared only under `.[ui]`.
- A local build completed compilation and static generation but ran out of audit-environment disk space while copying final output; this final ENOSPC was environmental rather than a demonstrated source defect.

## Architecture

### Strengths

- Clear ports/adapters/plugin model.
- Extensive ADR and porting provenance.
- Plugin-isolation gate passes.
- Approximately 366 production modules had only one detected strongly connected import cycle: `plugins.tektos.tools.registry` and `plugins.tektos.tools.detectors.path_traversal`.
- Real-service tiers exist for Ollama, PostgreSQL, DozerDB, Pier, DeepSWE, Docling, Playwright MCP, and large-repository mapping.
- The systemd kernel service binds to loopback and enables `NoNewPrivileges`, `PrivateTmp`, and `ProtectSystem=strict`.
- The test corpus exercises substantially more behavior than CI currently exposes.

### Kernel monolith

`kernel/app.py` is approximately 10,015 lines and owns all 182 application routes. It combines application construction, lifespan handling, adapter construction, plugin wiring, data-service probes, middleware, database APIs, tools, MCP, skills, voice, vision, RAG, telemetry, PTY, and static frontend serving.

This is the principal architectural bottleneck. It raises the cost of security review, startup-failure diagnosis, route ownership, isolated testing, and incremental replacement.

Recommended extraction order:

1. `kernel/routers/tools.py`
2. `kernel/routers/pty.py`
3. `kernel/routers/database.py`
4. `kernel/routers/skills.py`
5. `kernel/routers/inference.py`
6. `kernel/routers/tektos.py`
7. `kernel/boot/services.py`
8. `kernel/boot/plugins.py`
9. `kernel/security/operator_auth.py`

Keep `kernel/app.py` as a thin composition root and preserve route behavior one bounded context at a time.

## Operations

The systemd unit contains a contradictory startup contract:

- Comments state that the DozerDB dependency was removed after a PostgreSQL reland.
- `ExecStartPre` still waits up to approximately 60 seconds for DozerDB on port 7687 and fails startup if unavailable.
- The systemd README instructs deployment through `/etc/kosmos/kernel.env`.
- The actual unit reads `ops/systemd/kosmos-kernel.local.env` from the repository.

This can block an otherwise valid PostgreSQL-backed deployment and makes the documented procedure diverge from committed runtime behavior.

The repository also tracks four database WAL/SHM sidecars despite ignore rules, publicly includes a development DozerDB password, and has no committed project-level secret-scanning gate.

## Documentation integrity

The README begins with `PROGRAM COMPLETE`, then later says:

- Stage 0 is complete.
- Stage 1 is next.
- v25 files are current even though current files are v26 or archived.
- ADR-010 is the only open ADR.

The status section, repo layout, launch procedure, security assumptions, dependency profiles, test command, deployment guide, and current spec version should be regenerated from the current tree rather than incrementally appended.

Repository hygiene concerns include an approximately 873 KB BUILD_LOG, duplicated ADR/spec bundles, tracked runtime database sidecars, committed benchmark artifacts, and large result JSONL files.

## Prioritized remediation plan

| Rank | Move | Priority | Completion test |
|---:|---|---:|---|
| 1 | Disable and secure PTY and arbitrary tool execution | P0 | Anonymous and wrong-origin requests rejected; routes disabled by default |
| 2 | Replace CI topology with one truthful required gate | P0 | Aggregate check fails for every failed/skipped required job |
| 3 | Unify test roots and remove path/venv assumptions | P0 | One canonical command collects and runs every intended test |
| 4 | Correct runtime dependency closure and lock it | P1 | Clean runtime, dev, and PostgreSQL installs pass `pip check` |
| 5 | Upgrade vulnerable frontend dependencies and harden DiskCache | P1 | Dependency audits have no high/critical runtime findings |
| 6 | Fix package discovery and wheel smoke testing | P1 | Clean wheel imports kernel, Tektos, Zetesis, and adapters |
| 7 | Decompose `kernel/app.py` | P1 | Thin composition root; routers independently testable |
| 8 | Raise risk-weighted production coverage | P1 | 70% overall production; 85% execution/state/database surfaces |
| 9 | Repair frontend lint, TypeScript, and E2E | P1 | All frontend CI jobs pass from clean checkout |
| 10 | Reconcile README, systemd, backend, and v26 docs | P2 | One authoritative deployment and status contract |

## Canonical verification target

After dependency and path corrections, use one local and hosted gate:

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
  --cov=kernel \
  --cov=ports \
  --cov=adapters \
  --cov=plugins \
  --cov=ops \
  --cov-report=term-missing \
  --cov-fail-under=70

.venv/bin/bandit -r kernel ports adapters plugins ops scripts \
  -c pyproject.toml
.venv/bin/pip-audit --progress-spinner off

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
/tmp/kosmos-wheel-smoke/bin/python -c \
  'import kernel.app, plugins.tektos.agent, plugins.zetesis.plugin'
```

## Release criteria

Kosmos-LMS should not be declared complete or release-ready until:

- PTY and arbitrary command execution are disabled by default and operator-authenticated.
- The aggregate CI gate is green on three consecutive `main` revisions.
- No required test job is skipped because an unrelated lint job failed.
- Root and colocated tests run under one canonical command.
- Ruff, formatting, mypy, frontend lint, TypeScript, and E2E all pass.
- No known high or critical runtime dependency vulnerability remains.
- Production coverage reaches at least 70%, with critical execution modules above 85%.
- A clean wheel imports and boots the kernel plus primary plugins and adapters.
- Colossus completes every live-service gate from a clean checkout and fresh virtual environment.
- README, systemd, dependencies, current ADRs, and v26 status all describe the same system.

## Final judgment

Kosmos-LMS has crossed the threshold from scaffold to serious working system. The strongest evidence is not the completion language in its documents, but the 1,826 passing configured tests, successful frontend compilation, passing port contracts, clean plugin-isolation gate, and broad implemented surface.

Its immediate risk comes from combining autonomous-agent capability with a verification and security boundary that has not kept pace. The right next phase is not additional feature absorption. It is consolidation: secure the execution plane, make CI truthful, close dependency and packaging gaps, split the kernel monolith, and convert the existing test volume into reliable release evidence.

---

## References

1. [Workflow commands for GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands) - You can use workflow commands when running shell commands in a workflow or in an action's code.

2. [PYSEC-2026-2447 - Vulnerability-Lookup](https://db.gcve.eu/vuln/pysec-2026-2447) - Details of the vulnerability PYSEC-2026-2447 from pysec on Vulnerability-Lookup.

3. [CVE-2025-69872](https://scout.docker.com/vulnerabilities/id/CVE-2025-69872) - DiskCache (python-diskcache) through 5.6.3 uses Python pickle for serialization by default. An attac...

4. [lazyllm-lmdeploy | PyPI](https://deps.dev/pypi/lazyllm-lmdeploy/0.7.1rc0) - DiskCache has unsafe pickle deserialization. PYSEC-2026-2447. More details. Similar advisories. Disk...

5. [Releases · vercel/next.js](https://github.com/vercel/next.js/releases) - The React Framework. Contribute to vercel/next.js development by creating an account on GitHub.

6. [Security Advisories · vercel/next.js](https://github.com/vercel/next.js/security/advisories) - GitHub is where people build software. More than 150 million people use GitHub to discover, fork, an...

7. [CVE-2026-64646 - GitHub Advisory Database](https://github.com/advisories/GHSA-4c39-4ccg-62r3) - Next.js: Unbounded Server Action payload in Edge runtime

