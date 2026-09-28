# Hermes Implementation Plan: Restore Tektos Autonomy in Kosmos-LMS

## Executive directive

Implement one production-grade Tektos mission runtime inside `rmholston420/kosmos-lms`. The runtime must own the complete autonomous cycle:

```text
user objective
  -> repository discovery
  -> model inference with native tool schemas
  -> tool-call parsing
  -> policy and approval decision
  -> isolated tool execution
  -> normalized observation
  -> next model inference
  -> deterministic verification
  -> repair loop
  -> reviewable diff
  -> explicit merge approval
```

Do not port the retired Tektos-Ultima application wholesale. Reuse its last intact runtime, commit `8274f60b3dd5f7d37c793ccb8c5b2d6800cfbf01`, as a behavioral oracle for tool-call accumulation, repeated inference, loop safety, recovery, and termination. Keep Kosmos ports, adapters, governance, event envelopes, UI, and service ownership authoritative.

The implementation must be delivered as a sequence of small, independently testable commits. No phase may begin until the preceding phase’s exit gate passes. Never claim completion based on unit tests alone: the final gate is a real local-model repair mission performed from a wheel-installed Kosmos service against a disposable Git repository.

## Final audit baseline

The final pass audited public `main` at commit [`7e7b1e30277a2bb24514459cc5350939e628ddf2`](https://github.com/rmholston420/kosmos-lms/commit/7e7b1e30277a2bb24514459cc5350939e628ddf2). The donor’s current `main`, commit [`43cb0ef97f8cc596be988b41b5fa4754048ab14d`](https://github.com/rmholston420/tektos-ultima/commit/43cb0ef97f8cc596be988b41b5fa4754048ab14d), deliberately deletes its old `main.py`; the usable donor reference is therefore its parent-era runtime at [`8274f60b`](https://github.com/rmholston420/tektos-ultima/blob/8274f60b3dd5f7d37c793ccb8c5b2d6800cfbf01/src/tektos/runtime/sdk.py).

### Confirmed blockers

| Severity | Finding | Implementation consequence |
|---|---|---|
| P0 | `TektosTurnLoop.run_turn()` accepts caller-supplied `tool_calls` and invokes the LLM only once | Replace it with a controller that derives calls from each model response and loops until a terminal condition |
| P0 | `TektosAgent.run()` is a separate one-shot text-generation path | Convert it to a compatibility facade over the mission controller; do not maintain two agent brains |
| P0 | `LLMPort.chat()` types messages as `list[dict[str, str]]` | Widen and normalize the contract so assistant `tool_calls`, nullable content, tool role messages, and `tool_call_id` are representable |
| P0 | Packaging explicitly declares 52 packages while 114 directories contain `__init__.py`; 62 packages are omitted | Replace the static package list with controlled discovery and test an installed wheel outside the checkout |
| P0 | CI runs only `pytest tests/`, while `pyproject.toml` points to colocated tests under `ports`, `adapters`, `kernel`, `plugins`, and `ops` | Make the complete test surface the primary CI job |
| P0 | CI installs `.[dev]` before starting `uvicorn`, while FastAPI/Uvicorn are in the `ui` extra | Make kernel runtime dependencies non-optional or install the correct runtime extra in every service job |
| P0 | The latest ten GitHub Actions runs on the audited branch failed | Establish a green baseline before autonomy work |
| P0 | The current event bus boots a real Valkey adapter unconditionally | Add a deterministic in-memory test mode; unit tests must never depend on local Redis, model, voice, embedding, or Postgres daemons |
| P0 | A test copies axioms from the absolute path `/home/user/dev/kosmos-lms/...` | Derive all repository paths from `Path(__file__)`, fixtures, or an injected workspace |
| P0 | Existing coding tools operate on a caller-supplied/real workspace rather than a mission-owned worktree | Introduce a per-mission Git worktree and make it the only writable root |
| P1 | `README.md` simultaneously says “PROGRAM COMPLETE” and “Stage 0 complete” | Replace contradictory status prose with one generated/current status document |
| P1 | Tracked SQLite `-wal` and `-shm` files are present | Remove them from Git and add ignore rules |
| P1 | The kernel composition root is roughly 10,000 lines and owns many route families | Add a Tektos mission router module; do not expand `kernel/app.py` with another large inline subsystem |

### Reproduced quality state

A final broad collection found 2,694 tests. The first run failed during collection because of the absolute `/home/user/dev/kosmos-lms` path. After temporarily satisfying that path, the run reached 100% and reported 25 failed tests and 24 skips. Many failures were caused by nondeterministic global boot behavior—especially attempts to contact Valkey on `127.0.0.1:6379`—rather than isolated unit contracts. This is evidence that test-environment construction must be fixed before interpreting the remaining failure count.

The same revision produced:

- 918 Ruff findings, 660 automatically fixable.
- 358 files requiring Ruff formatting.
- Mypy collection failure from duplicate `hello` modules inside the evaluation fixture tree.
- Four tracked SQLite sidecars: `data/memory.db-shm`, `data/memory.db-wal`, `data/tektos_rag.db-shm`, and `data/tektos_rag.db-wal`.
- No `lint` script in `ui/package.json`, although CI invokes `npm run lint`.

### Final architectural conclusion

The earlier audit conclusion is unchanged: Kosmos already contains most required components, but no component owns the iterative model/tool/observation cycle. The final pass adds three important corrections:

1. Fix test-environment isolation before treating the complete test count as a reliable product baseline.
2. Introduce a dedicated persistent `MissionStore`; the existing `SessionPort` FSM tracks connection/turn lifecycle but does not contain enough state to resume a coding mission safely.
3. Extend the existing `LLMPort.chat()` seam rather than introducing a second raw HTTP client. The current llama-swap adapter already forwards arbitrary chat options, so native `tools` and `tool_choice` can travel through that seam after the message and response contracts are normalized.

## Hermes execution contract

Hermes is well suited to this task because it provides terminal and file tools, persistent conversations, subagents, and saved trajectories, and it can also be embedded through its `AIAgent` API. Hermes itself emphasizes three practices that should govern this implementation: reproduce current behavior before editing, extend existing infrastructure instead of duplicating it, and prove I/O/security changes with end-to-end tests rather than mocks alone.[^1][^2][^3]

### Working rules

Hermes must obey these rules throughout the implementation:

- Work only in a new branch and never force-push.
- Never modify `tektos-ultima`; it is read-only reference material.
- Do not copy donor `main.py`, route tables, service units, stores, or UI wholesale.
- Do not create a second LLM stack, tool registry, approval engine, event bus, sandbox, or session manager.
- Do not implement self-improvement, multi-agent delegation, or new memory features until the single-agent vertical slice passes.
- Do not use `shell=True` in new process execution code.
- Never write outside a mission worktree in runtime code or tests.
- Never weaken immune, approval, sandbox, or path-containment checks to make a test pass.
- Never make network-backed services implicit requirements of unit tests.
- Do not bulk-fix all 918 Ruff findings in the same commits as semantic runtime changes.
- Preserve old API routes as compatibility adapters until parity tests prove the new controller.
- Record the exact commands and outputs used at every gate in `docs/implementation/TEKTOS_IMPLEMENTATION_LOG.md`.
- Stop and document the blocker if an exit gate cannot pass; do not continue stacking unverified phases.

### Branch setup

```bash
cd /home/rmholston/dev/kosmos-lms
git fetch --all --tags --prune
git switch main
git pull --ff-only

git tag -f audit-before-tektos-runtime-2026-09-28 \
  7e7b1e30277a2bb24514459cc5350939e628ddf2

git switch -c feat/tektos-autonomous-runtime

git status --short
git rev-parse HEAD
git submodule status || true
```

Create a read-only donor worktree:

```bash
cd /home/rmholston/dev/tektos-ultima-v1
git fetch --all --tags --prune
git worktree add --detach \
  /home/rmholston/dev/tektos-donor-8274f60 \
  8274f60b3dd5f7d37c793ccb8c5b2d6800cfbf01
chmod -R a-w /home/rmholston/dev/tektos-donor-8274f60
```

Create an implementation log immediately:

```bash
cd /home/rmholston/dev/kosmos-lms
mkdir -p docs/implementation
cat > docs/implementation/TEKTOS_IMPLEMENTATION_LOG.md <<'EOF'
# Tektos Autonomous Runtime Implementation Log

- Baseline: 7e7b1e30277a2bb24514459cc5350939e628ddf2
- Donor behavioral reference: 8274f60b3dd5f7d37c793ccb8c5b2d6800cfbf01
- Branch: feat/tektos-autonomous-runtime

## Gate results

EOF
```

### Hermes start prompt

Run Hermes from the Kosmos repository and provide this plan as its primary instruction. Hermes supports a non-interactive query mode through `hermes chat -q`, while interactive mode is preferable for approval checkpoints.[^2]

```bash
cd /home/rmholston/dev/kosmos-lms
hermes chat
```

Initial prompt:

```text
You are the implementation owner for the Tektos autonomous runtime in this repository.
Read the complete file docs/implementation/TEKTOS_HERMES_IMPLEMENTATION_PLAN.md before editing.
Then inspect AGENTS.md and every relevant nested AGENTS.md if present.
Work phase by phase and commit at every named commit boundary.
Do not skip exit gates. Do not modify the donor checkout.
Before each phase, restate its invariants and run its baseline tests.
After each phase, append commands, results, deviations, and the commit SHA to
TEKTOS_IMPLEMENTATION_LOG.md. If a gate fails, stop, diagnose the root cause,
fix it within the current phase, and rerun the full gate.
The final deliverable is not merely code: it is a wheel-installed, restartable,
worktree-isolated local-model coding mission that repairs a failing fixture,
runs verification, exposes a reviewable diff, and waits for merge approval.
Begin with Phase 0 only.
```

## Target architecture

### Narrow waist

Keep one narrow control path:

```text
FastAPI mission router
        |
        v
MissionService
        |
        v
MissionController  <---->  MissionStore (SQLite)
        |
        +---- ContextBuilder / RepoMap
        +---- LLMPort.chat(messages, tools, tool_choice)
        +---- ModelResponseNormalizer
        +---- ToolCallAssembler
        +---- CapabilityPolicy / ApprovalPort / ImmunePort
        +---- TektosToolRegistry
        +---- WorkspaceManager / SandboxPort
        +---- VerificationRunner
        +---- EventBusPort + in-process mission stream
```

Only `MissionController` may advance mission state. API handlers enqueue commands and read state; UI code never manipulates controller internals; tool implementations never choose the next state.

### Domain states

Use an explicit enum:

```python
class MissionStatus(StrEnum):
    CREATED = "created"
    PREPARING_WORKSPACE = "preparing_workspace"
    DISCOVERING = "discovering"
    PLANNING = "planning"
    AWAITING_SCOPE_APPROVAL = "awaiting_scope_approval"
    ACTING = "acting"
    OBSERVING = "observing"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    AWAITING_MERGE_APPROVAL = "awaiting_merge_approval"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXHAUSTED = "exhausted"
```

Do not overload `SessionPort.SessionState` with these values. A session is a transport/user interaction lifecycle; a mission is a durable coding transaction. Link them by `session_id`, but persist them separately.

### Required records

Define immutable or validation-enforced domain records:

```text
MissionSpec
- objective
- repository_path
- base_ref
- requested_model
- capability_request
- verification_profile
- limits

Mission
- mission_id
- session_id
- status
- version
- created_at / updated_at
- workspace_path
- base_commit / head_commit
- iteration
- model
- capability_lease_id
- pending_approval_id
- terminal_reason

ConversationMessage
- sequence
- role
- content
- tool_calls
- tool_call_id
- token estimate

ToolInvocation
- invocation_id
- model_call_id
- tool_name
- normalized arguments
- policy decision
- started_at / completed_at
- exit status
- stdout/stderr references
- changed paths
- checkpoint commit

VerificationResult
- profile
- command
- exit status
- duration
- stdout/stderr references
- affected paths

MissionEvent
- event_id
- mission_id
- sequence
- event_type
- causation_id
- correlation_id
- payload
- created_at
```

### Controller invariants

- Exactly one active controller task per `mission_id` in one process.
- Every state update uses optimistic version checking.
- Persist intent before starting an external side effect.
- Persist result immediately after the side effect.
- Replaying a completed `invocation_id` returns its stored result instead of executing again.
- The next inference sees the assistant tool call and matching tool result in correct order. Tool results must correspond to assistant tool calls; standard chat semantics require explicit tool-role messages matched by `tool_call_id`.[^4]
- A mission may write only beneath its canonical worktree root.
- Model text cannot bypass the tool policy.
- “Completed” is impossible unless required verification passed after the latest write.
- “Awaiting merge approval” is the only successful pre-merge terminal-like state.
- Cancellation terminates child process groups before setting `CANCELLED`.
- Recovery never blindly reruns an invocation whose durable result is already present.

## Phase 0: Freeze and document

### Objective

Create instructions that keep Hermes and later coding agents aligned while the code changes.

### Files

Create:

```text
AGENTS.md
plugins/tektos/AGENTS.md
docs/implementation/TEKTOS_HERMES_IMPLEMENTATION_PLAN.md
docs/implementation/TEKTOS_IMPLEMENTATION_LOG.md
```

Update:

```text
README.md
SESSION_HANDOFF.md
```

### Steps

1. Put repository-wide commands, safety rules, branch policy, and test tiers in root `AGENTS.md`.
2. Put the Tektos state-machine invariants, tool-call ordering, worktree boundary, and test matrix in `plugins/tektos/AGENTS.md`.
3. Replace contradictory README completion language with a short truthful statement: component absorption is complete; autonomous runtime integration is active work.
4. Point all status references to `docs/implementation/TEKTOS_IMPLEMENTATION_LOG.md`.
5. Do not rewrite historical ADRs. Add a new ADR for the runtime controller and reference superseded implementation assumptions.
6. Record all preexisting failures without marking them fixed.

### Exit gate

```bash
git diff --check
grep -RIn 'PROGRAM COMPLETE\|Current status: \*\*Stage 0' README.md SESSION_HANDOFF.md
```

The grep must return no contradictory live-status statement.

### Commit

```text
docs(tektos): establish autonomous-runtime execution contract
```

## Phase 1: Packaging and deterministic CI

### Objective

Make the installed artifact and CI trustworthy before changing behavior.

### Package discovery

Replace the manually enumerated `tool.setuptools.packages` array. Setuptools only performs automatic discovery when `packages`/`py_modules` are not explicitly supplied, and it supports controlled `find` include/exclude patterns in `pyproject.toml`.[^5]

Use controlled flat-layout discovery:

```toml
[tool.setuptools.packages.find]
where = ["."]
include = [
  "ports*",
  "adapters*",
  "kernel*",
  "plugins*",
  "governance*",
  "ops*",
]
exclude = [
  "tests*",
  "vendor*",
  "ui*",
  "data*",
]
namespaces = false
```

Verify package data remains included for Tektos UI and any non-Python runtime files. Add wheel-content assertions instead of trusting editable imports.

### Runtime dependencies

Because `kernel.app` imports FastAPI and the deployed executable is Uvicorn, move these into base dependencies:

```toml
"fastapi>=0.115",
"uvicorn>=0.32",
```

Add direct dependencies for libraries imported by production modules rather than relying on transitive installation. Add `types-PyYAML` to `dev`. Add a `[project.scripts]` entry only if a small stable launcher is created; otherwise keep the documented Uvicorn invocation.

### Test profile

Implement `KOSMOS_RUNTIME_PROFILE` with at least:

```text
test       deterministic in-memory/no-op collaborators; no network
local      local services and model endpoints
production explicit configured services; fail visibly when required dependencies are absent
```

Add an `InMemoryEventBusAdapter` conforming to `EventBusPort`. Under `test`, select it instead of Valkey. Select no-op voice/vision, fake embeddings, in-memory session, noop relational memory, and deterministic fake LLM only where individual tests do not inject collaborators.

Do not silently fall back from Valkey to memory in `production`; configuration errors must remain visible.

Update root `conftest.py` before importing `kernel.app`:

```python
os.environ.setdefault("KOSMOS_RUNTIME_PROFILE", "test")
```

Keep live tests opt-in and mark them:

```toml
markers = [
  "integration: multi-component test without external network",
  "live: requires a real external daemon or model",
  "slow: intentionally long-running",
]
```

Pytest recommends importlib mode for modern projects because it avoids mutating `sys.path`; migration is desirable, but first test it on a branch because this repository has many colocated test modules. Do not combine that migration with the runtime controller if it causes broad churn.[^6][^7]

### Path fixes

- Replace `/home/user/dev/kosmos-lms/plugins/tektos/axioms` in `test_adr141_s133_axioms_routes.py` with a path derived from the test file or an imported package resource.
- Replace `.venv/bin/ruff`, `.venv/bin/bandit`, and `.venv/bin/pytest` assumptions with `shutil.which()` or `[sys.executable, "-m", ...]`.
- Exclude `plugins/tektos/eval/tasks/` from mypy just as it is excluded from pytest; those directories intentionally contain duplicate fixture modules.

### CI rewrite

Use independent jobs so lint failure does not suppress tests:

```yaml
python-tests:
  steps:
    - run: pip install -e ".[dev,postgres]"
    - run: pytest ports adapters kernel plugins ops tests -m "not live" -v --tb=short
```

Add:

```yaml
wheel-smoke:
  steps:
    - run: python -m build
    - run: python -m venv /tmp/kosmos-wheel
    - run: /tmp/kosmos-wheel/bin/pip install dist/*.whl
    - run: cd /tmp && /tmp/kosmos-wheel/bin/python -c "import kernel.app; import plugins.tektos.runtime"
```

Add UI scripts:

```json
"lint": "eslint .",
"typecheck": "tsc --noEmit"
```

Change E2E installation to include runtime requirements. Make kernel startup print logs on failure and use a bounded health wait.

### Repository hygiene

```bash
git rm --ignore-unmatch \
  data/memory.db-shm data/memory.db-wal \
  data/tektos_rag.db-shm data/tektos_rag.db-wal
cat >> .gitignore <<'EOF'
*.db-shm
*.db-wal
*.db-journal
EOF
```

### Ruff strategy

Apply only mechanical import/fatal fixes first:

```bash
.venv/bin/ruff check ports adapters kernel plugins ops scripts tests \
  --select F,E9,I --fix
.venv/bin/ruff format ports adapters kernel plugins ops scripts tests
.venv/bin/ruff check ports adapters kernel plugins ops scripts tests
```

Keep this in a dedicated formatting commit. Review unsafe fixes manually.

### Exit gates

```bash
rm -rf .venv build dist
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip build
.venv/bin/pip install -e '.[dev,ui,postgres]'

KOSMOS_RUNTIME_PROFILE=test \
  .venv/bin/pytest ports adapters kernel plugins ops tests \
  -m 'not live' -v --tb=short

.venv/bin/ruff check ports adapters kernel plugins ops scripts tests
.venv/bin/ruff format --check ports adapters kernel plugins ops scripts tests
.venv/bin/mypy ports kernel plugins/tektos \
  --exclude 'plugins/tektos/eval/tasks/'

.venv/bin/python -m build
python3.12 -m venv /tmp/kosmos-wheel
/tmp/kosmos-wheel/bin/pip install dist/*.whl
cd /tmp
KOSMOS_RUNTIME_PROFILE=test \
  /tmp/kosmos-wheel/bin/python -c \
  'import kernel.app; import plugins.tektos.runtime; print("wheel-ok")'

cd /home/rmholston/dev/kosmos-lms/ui
npm ci
npm run lint
npm run typecheck
npm run build
```

### Commits

```text
fix(packaging): discover all runtime packages and validate wheel imports
fix(test): isolate kernel tests from external services and host paths
chore(lint): normalize existing Python formatting and imports
fix(ci): run complete backend, wheel, frontend lint, type, and e2e gates
```

## Phase 2: Model/tool protocol

### Objective

Create one typed transport-neutral model interface capable of native function calling.

### Files

Create:

```text
plugins/tektos/runtime/model_protocol.py
plugins/tektos/runtime/tool_call_assembler.py
plugins/tektos/runtime/test_model_protocol.py
plugins/tektos/runtime/test_tool_call_assembler.py
```

Modify:

```text
ports/llm.py
adapters/llm/llama_swap/adapter.py
adapters/llm/ollama/adapter.py
adapters/llm/failover/adapter.py
plugins/tektos/tools/registry.py
```

### Contract changes

Widen `LLMPort.chat()`:

```python
async def chat(
    *,
    messages: Sequence[Mapping[str, Any]],
    model: str | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    tool_choice: str | Mapping[str, Any] | None = None,
    **options: Any,
) -> Mapping[str, Any]: ...
```

Avoid provider-specific response dictionaries in the controller. Normalize them into:

```python
@dataclass(frozen=True, slots=True)
class AssistantTurn:
    content: str | None
    reasoning: str | None
    tool_calls: tuple[ModelToolCall, ...]
    finish_reason: str | None
    usage: TokenUsage | None
    raw_provider: str
```

Each `ModelToolCall` contains:

```text
id
name
arguments_json
arguments (validated mapping or None)
parse_error
```

### Tool schemas

Add a registry method:

```python
def openai_tools(self, *, lease: CapabilityLease) -> tuple[dict[str, Any], ...]:
    ...
```

Generate schemas from `ToolDescriptor`; do not keep a second manual `TOOLS_SCHEMA` list. Expose only tools allowed by the active capability lease.

Validate arguments in this order:

1. Complete fragmented JSON.
2. Parse JSON.
3. Require an object.
4. Validate against the descriptor schema.
5. Canonicalize paths relative to the mission worktree.
6. Run policy and immune checks.
7. Execute.

Never execute malformed or partially assembled arguments.

### Donor parity tests

Port behavior, not implementation, from donor `runtime/sdk.py`:

- Accumulate fragmented tool call IDs, names, and argument strings by index.
- Support multiple calls in one assistant message.
- Preserve assistant content that accompanies tool calls.
- Append exactly one assistant message followed by one tool message per call.
- Ignore duplicate terminal frames.
- Reject a tool call with missing name, ID, or invalid arguments.
- Preserve provider `finish_reason` without treating it as the sole source of truth.

### Exit gate

A fake LLM transcript must complete this sequence:

```text
assistant -> file_read
controller -> tool result
assistant -> file_write
controller -> tool result
assistant -> bash pytest
controller -> tool result
assistant -> final text
```

Assert the fake model receives the exact prior assistant/tool messages on every inference.

### Commit

```text
feat(tektos): add native model tool-call protocol and normalization
```

## Phase 3: Mission domain and store

### Objective

Create the durable source of truth required for restart-safe execution.

### Files

Create:

```text
plugins/tektos/runtime/mission.py
plugins/tektos/runtime/events.py
plugins/tektos/runtime/store.py
plugins/tektos/runtime/migrations/001_missions.sql
plugins/tektos/runtime/migrations/002_messages_tools.sql
plugins/tektos/runtime/test_store.py
plugins/tektos/runtime/test_recovery.py
```

### Storage decision

Use a dedicated SQLite database, default `data/tektos_missions.db`, with WAL mode at runtime but ignored sidecars. This store is operational state, not semantic memory. Mirror selected events to `RelationalMemoryPort` and `EventBusPort`, but do not depend on either mirror for recovery.

Tables:

```text
missions
mission_events
conversation_messages
tool_invocations
verification_runs
capability_leases
workspace_checkpoints
schema_migrations
```

Required database properties:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

Use transactions for state transition plus event append. Add a unique constraint on `(mission_id, sequence)` and on `invocation_id`. Store large stdout/stderr bodies as bounded artifact files with hashes, while keeping excerpts and references in SQLite.

### Recovery algorithm

At service startup:

1. Load missions in nonterminal states.
2. Acquire an in-process mission lock.
3. Inspect the last durable event and pending tool invocation.
4. If an invocation has a stored terminal result, append/reuse its observation.
5. If marked started but no result exists, classify by tool idempotency.
6. Retry only read-only/idempotent calls automatically.
7. For uncertain writes or process execution, stop in `BLOCKED` and request recovery approval unless a checkpoint proves the side effect.
8. Validate the worktree and baseline commit.
9. Resume the controller from the first incomplete transition.

### Exit gate

Property-style tests must kill and reconstruct the controller after every durable transition. No completed tool invocation may execute twice.

### Commit

```text
feat(tektos): persist mission state events messages and tool results
```

## Phase 4: Worktree and process isolation

### Objective

Guarantee that autonomous changes are transactional and repository-scoped.

### Files

Create:

```text
plugins/tektos/workspace/__init__.py
plugins/tektos/workspace/manager.py
plugins/tektos/workspace/models.py
plugins/tektos/workspace/process.py
plugins/tektos/workspace/path_policy.py
plugins/tektos/workspace/test_manager.py
plugins/tektos/workspace/test_process.py
plugins/tektos/workspace/test_path_policy.py
```

### Workspace lifecycle

For each mission:

1. Resolve and validate the source repository.
2. Require a clean or explicitly accepted source state.
3. Resolve `base_ref` to an immutable commit.
4. Create `data/worktrees/<mission_id>` using `git worktree add --detach`.
5. Create branch `tektos/<mission_id>` inside the worktree.
6. Record base commit, branch, path, and Git common directory.
7. Run all reads, writes, searches, and commands against this root.
8. After each successful mutating tool, record a checkpoint commit or durable patch/hash record.
9. Keep the worktree for review after success or failure.
10. Delete only through an explicit discard operation.

### Path policy

For every path:

- Reject NUL bytes and invalid encodings.
- Join relative paths to the worktree.
- Resolve the nearest existing parent.
- Reject `..` escape.
- Reject symlinks whose resolved target leaves the worktree.
- Reject access to `.git` internals except through approved Git commands.
- Reject absolute paths unless they canonicalize beneath the root.
- Return normalized repository-relative paths in events and results.

### Process runner

Use `asyncio.create_subprocess_exec` with an argument vector. Required controls:

- `cwd=worktree`.
- New process session/process group.
- Wall-clock timeout.
- Maximum stdout/stderr bytes with truncation metadata.
- Environment allowlist and secret redaction.
- Optional CPU, memory, file-size, open-file, and process-count limits.
- Kill the entire process group on timeout/cancellation.
- Capture exit code and signal.
- Record changed files before and after execution.
- Block interactive TTY commands in autonomous mode.

### Command policy

Initially allow only commands needed for repository work:

```text
git status/diff/log/show/branch/rev-parse
rg/find/sed/awk/head/tail/cat
python/python3/pytest/ruff/mypy/bandit
npm/npx with project scripts and bounded known subcommands
make with repository targets
```

Always block or require separate approval for:

```text
sudo/su
git push
git reset --hard
git clean -fdx
git checkout -- .
rm outside worktree
mount/unshare namespace changes initiated by model
systemctl/docker daemon changes
credential-store/keyring access
curl/wget or arbitrary network access
shell redirection to paths not validated by the path policy
```

### Exit gate

Tests must prove traversal, absolute-path escape, symlink escape, command timeout, child-process cancellation, output truncation, and post-command changed-file reporting.

### Commit

```text
feat(tektos): execute every mission in a constrained git worktree
```

## Phase 5: Capability leases and approvals

### Objective

Permit useful autonomy inside an approved scope without prompting for every harmless action.

### Files

Create:

```text
plugins/tektos/runtime/capabilities.py
plugins/tektos/runtime/policy.py
plugins/tektos/runtime/test_capabilities.py
```

### Lease model

A `CapabilityLease` must include:

```text
lease_id
mission_id
repository_root
worktree_root
allowed_tools
writable_globs
readable_globs
allowed_command_families
network_policy
maximum_iterations
maximum_tool_calls
maximum_wall_seconds
maximum_output_bytes
expires_at
approved_by / approved_at
```

Default coding lease:

- Read the entire worktree except secret patterns.
- Write only requested repository scopes.
- Use file, search, and bounded command tools.
- No network.
- No merge, push, service control, or credential access.
- Require approval for scope expansion.
- Require a separate final merge approval.

### Policy order

Every call must pass:

```text
schema validation
-> capability lease
-> path/command policy
-> immune scan
-> approval classification
-> resource/thermal/loop checks
-> execution
```

Do not make approval the first check; invalid or out-of-scope requests should be rejected rather than presented to the user as approvable.

### Exit gate

Prove that routine edits and test commands proceed without per-call prompts, while out-of-worktree writes, network, destructive Git, and merge/push actions cannot proceed without the correct explicit approval.

### Commit

```text
feat(tektos): add scoped autonomy leases and merge approval boundary
```

## Phase 6: Canonical mission controller

### Objective

Implement the actual autonomous loop.

### Files

Create:

```text
plugins/tektos/runtime/controller.py
plugins/tektos/runtime/context.py
plugins/tektos/runtime/termination.py
plugins/tektos/runtime/verification.py
plugins/tektos/runtime/prompts.py
plugins/tektos/runtime/test_controller.py
plugins/tektos/runtime/test_termination.py
plugins/tektos/runtime/test_verification.py
```

Refactor:

```text
plugins/tektos/runtime/turn_loop.py
plugins/tektos/agent.py
```

### Controller algorithm

```python
async def run(mission_id: str) -> Mission:
    mission = await store.load_for_update(mission_id)
    workspace = await workspace_manager.ensure(mission)
    lease = await capability_service.require_approved(mission)

    while True:
        await cancellation.raise_if_requested(mission_id)
        await limits.check(mission_id)

        context = await context_builder.build(mission_id)
        await store.record_model_request(mission_id, context)

        raw = await llm.chat(
            messages=context.messages,
            model=mission.model,
            tools=tool_registry.openai_tools(lease=lease),
            tool_choice="auto",
        )
        turn = model_protocol.normalize(raw)
        await store.append_assistant_turn(mission_id, turn)

        if turn.tool_calls:
            for call in turn.tool_calls:
                result = await execute_one(mission, lease, call)
                await store.append_tool_result(mission_id, call, result)
            continue

        decision = termination.evaluate(mission, turn)
        if decision.requires_verification:
            report = await verifier.run(mission)
            await store.append_verification(mission_id, report)
            if report.passed:
                return await transition_to_merge_review(mission, turn, report)
            await store.append_repair_observation(mission_id, report)
            continue

        if decision.terminal:
            return await store.transition(mission_id, decision.status, decision.reason)

        await store.append_recovery_nudge(mission_id, decision.nudge)
```

### Execution rules

- Execute tool calls sequentially initially. Parallel execution can be added later only for proven read-only calls.
- Check cancellation before inference, before each tool, after each tool, and before verification.
- Persist the assistant tool-call message before executing tools.
- Persist each tool result before the next inference.
- Keep full raw output in artifacts and bounded observations in context.
- Summarize only old observations; never summarize away the objective, current plan, changed-file list, latest diff, latest failures, pending approval, or capability scope.
- Inject recovery guidance as controller metadata/system context, not as a fake user message.

### Termination rules

Stop with `AWAITING_MERGE_APPROVAL` only when:

- The model has produced no pending tool calls.
- At least one post-change verification run exists.
- Required checks passed against the current workspace head.
- The final response names changed files and verification evidence.
- The diff contains no unresolved conflict markers or secret findings.

Stop with `EXHAUSTED` on configurable maximums:

```text
iterations: 40
model calls: 40
tool calls: 120
identical tool signature repetitions: 3
consecutive no-progress iterations: 4
repair cycles: 8
wall time: 45 minutes
```

Make defaults configurable through a typed settings object. Existing Kosmos is env-driven, but configuration parsing must occur once in the composition root rather than through scattered `os.environ` reads.

### Repetition and progress

Compute a canonical signature from tool name plus normalized arguments. Track progress using:

- Workspace tree/diff hash.
- New files read.
- New test output hash.
- Changed failing-test set.
- Plan/task state changes.

On first stall, tell the model exactly what repeated and request a different strategy. On the terminal threshold, stop; do not let the model promise to try again indefinitely.

### Verification ladder

Infer targeted commands from changed files, then run:

1. Syntax/compile check.
2. Targeted unit tests.
3. Targeted Ruff.
4. Targeted mypy when the touched area is typed.
5. Frontend lint/type/build for UI changes.
6. Package build for packaging changes.
7. Full non-live suite when budget permits or before merge.
8. `git diff --check`.
9. Secret scan and forbidden-path scan.

Every failed command becomes a structured observation:

```text
command
exit code
failing tests
first relevant traceback
stdout/stderr artifact
changed files
suggested next diagnostic, if deterministic
```

### Compatibility conversion

- Make `TektosAgent.run()` call `MissionService.create_and_run()`.
- Make `TektosAgent.invoke_tool()` a thin registry compatibility method or deprecate it.
- Make `TektosTurnLoop` wrap one mission iteration temporarily, then delete it after route/UI parity.
- Add deprecation warnings and tests; do not leave independent decision logic in either compatibility class.

### Exit gate

A deterministic fake-model test must perform a multi-turn repair with at least three model calls and prove exact message/tool ordering. A second test must fail verification once, consume the failure, repair the fixture, and pass.

### Commit

```text
feat(tektos): implement durable model-tool-observation mission loop
```

## Phase 7: API and event surface

### Objective

Expose the mission runtime without growing `kernel/app.py` further.

### Files

Create:

```text
kernel/routes/tektos_missions.py
kernel/schemas/tektos_missions.py
kernel/services/tektos_missions.py
tests/kernel/test_tektos_missions_api.py
```

If `kernel/routes` and `kernel/schemas` do not exist, create packages and move only the new surface. A later mechanical extraction may move legacy routes.

### Endpoints

```text
POST   /api/tektos/missions
GET    /api/tektos/missions
GET    /api/tektos/missions/{mission_id}
GET    /api/tektos/missions/{mission_id}/events
GET    /api/tektos/missions/{mission_id}/diff
GET    /api/tektos/missions/{mission_id}/artifacts
POST   /api/tektos/missions/{mission_id}/approve-scope
POST   /api/tektos/missions/{mission_id}/cancel
POST   /api/tektos/missions/{mission_id}/resume
POST   /api/tektos/missions/{mission_id}/retry
POST   /api/tektos/missions/{mission_id}/approve-merge
POST   /api/tektos/missions/{mission_id}/discard
GET    /api/tektos/missions/{mission_id}/stream
GET    /api/tektos/readiness
```

`stream` should use SSE with durable sequence IDs and `Last-Event-ID` replay. Do not make live SSE dependent on Valkey; publish to the bus for observers, but source replay and reconnect from `MissionStore`.

### Request contract

`POST /missions` accepts:

```json
{
  "objective": "Repair the failing parser tests without changing public behavior",
  "repository_path": "/home/rmholston/dev/kosmos-lms",
  "base_ref": "main",
  "model": null,
  "writable_globs": ["plugins/tektos/**", "tests/**"],
  "verification_profile": "python",
  "limits": {
    "max_iterations": 40,
    "max_tool_calls": 120,
    "max_wall_seconds": 2700
  }
}
```

Validate source repository and scope before creating a worktree.

### Compatibility routes

- Preserve `POST /api/prompt/sse`, but have it create or continue a mission and translate mission events to the donor-compatible OpenAI chunk format.
- Preserve `POST /api/tektos/turn` as a deprecated single-wait wrapper over a mission, not as an independent `run_turn()` path.
- Preserve current plan routes by mapping their approved plan into a mission objective/scope where possible.
- Add response headers or fields indicating deprecation and replacement route.

### Readiness

`/api/tektos/readiness` must report individual requirements:

```text
controller
mission_store
llm transport
native tool-call probe
session adapter
workspace root
sandbox/process runner
immune
approval
loop safety
thermal/resource state
event stream
```

Return `ready=false` with actionable reasons. Do not report Tektos ready because unrelated component slots are merely non-null.

### Exit gate

API tests must cover create, scope approval, event replay, cancel, resume, diff, final approval, invalid path, unknown mission, version conflict, and compatibility SSE.

### Commit

```text
feat(api): expose canonical Tektos mission lifecycle and event stream
```

## Phase 8: UI integration

### Objective

Turn the existing Tektos UI into a mission control surface.

### Files

Prefer extending:

```text
ui/app/tektos/page.tsx
ui/app/tektos/detail/page.tsx
ui/lib/kernel-client.ts
ui/components/panels/AgentTracePanel.tsx
ui/components/panels/ApprovalsQueuePanel.tsx
ui/components/KillSwitch.tsx
```

Add focused components:

```text
ui/components/tektos/MissionComposer.tsx
ui/components/tektos/MissionStatus.tsx
ui/components/tektos/MissionTimeline.tsx
ui/components/tektos/WorkspaceDiff.tsx
ui/components/tektos/VerificationPanel.tsx
ui/components/tektos/ScopeApproval.tsx
ui/components/tektos/MergeApproval.tsx
```

### Required behavior

- Create a mission with repository, base ref, objective, writable scope, and limits.
- Display explicit readiness failures before submission.
- Show current status, iteration, elapsed time, model, worktree, and budget use.
- Stream durable events with reconnect from the last sequence.
- Show model text separately from tool actions.
- Show command, cwd, duration, exit code, and bounded output.
- Show changed-file tree and unified diff.
- Show verification checks and latest failures.
- Expose cancel at all active states.
- Expose resume/retry only when legal.
- Require explicit scope and merge approvals.
- Preserve terminal events after page reload.

### Exit gate

Playwright must perform the entire fake-model flow through the real API and UI. It must reload mid-mission, reconnect, cancel a running command, resume a recoverable mission, review a diff, and approve or discard it.

### Commit

```text
feat(ui): operate and review durable Tektos coding missions
```

## Phase 9: Real local-model vertical slice

### Objective

Prove the deployed local model can use the exact tool protocol autonomously.

### Fixture repository

Create a temporary repository fixture outside the Kosmos checkout containing:

```text
pyproject.toml
src/example/parser.py
tests/test_parser.py
```

Introduce one clear defect with a failing test. The mission objective must describe desired behavior, not the exact code edit.

### Preflight

```bash
curl -fsS http://127.0.0.1:8090/v1/models | jq .
curl -fsS http://127.0.0.1:8000/api/tektos/readiness | jq .
```

Add an automated native tool-call probe that sends one harmless temporary tool schema and verifies that the model returns a structurally valid tool call. A healthy text completion is insufficient.

### Run

```bash
curl -N -X POST http://127.0.0.1:8000/api/tektos/missions \
  -H 'content-type: application/json' \
  -d @/tmp/tektos-mission.json
```

Observe the mission stream, but do not manually tell the model which tools to call.

### Required evidence

Archive:

- Mission record and event sequence.
- Full normalized model/tool transcript.
- Initial failing test.
- Tool calls selected by the model.
- Modified files.
- Failed verification and repair cycle if one occurs.
- Final passing verification.
- Unified diff.
- Resource and duration metrics.
- Final state waiting for merge approval.

### Failure classification

If the real model emits text pretending to call a tool, malformed JSON, or repeated ineffective calls, do not weaken validation. Record a protocol failure, improve prompts/adapter compatibility, and rerun the fixed corpus.

### Exit gate

The model must independently inspect, edit, test, observe, repair if needed, verify, and stop at `AWAITING_MERGE_APPROVAL` without caller-supplied tool calls.

### Commit

```text
test(tektos): prove autonomous repair with the local llama cpp lane
```

## Phase 10: Crash recovery and cancellation

### Objective

Prove operational autonomy, not just happy-path autonomy.

### Crash matrix

Kill the kernel after each point:

```text
after mission creation
while preparing worktree
after model response persisted
before tool execution
after tool process starts
immediately after tool exits
before tool result is appended to context
during verification
after verification passes
while waiting for merge approval
```

Restart the wheel-installed service and assert:

- State is reconstructed.
- Completed side effects are not repeated.
- Child processes are not orphaned.
- Worktree remains valid.
- Event sequence remains monotonic.
- SSE replay resumes from `Last-Event-ID`.
- Mission reaches the expected resumable, blocked, or terminal state.

### Cancellation matrix

Test cancellation during:

```text
model call
read-only tool
file write
long-running command
verification
approval wait
```

Cancellation must be idempotent and must kill the process group for commands.

### Exit gate

All crash/cancel cases pass automatically. Manual observation is supplemental, not the gate.

### Commit

```text
test(tektos): verify crash recovery idempotency and process cancellation
```

## Phase 11: Deployment profile

### Objective

Make the working runtime reproducible under systemd.

### Configuration

Add required local settings to the gitignored `ops/systemd/kosmos-kernel.local.env`. Existing flags that must be intentionally enabled include:

```ini
KOSMOS_RUNTIME_PROFILE=local
KOSMOS_SESSION=tektos
KOSMOS_TEKTOS_TURN_LOOP=on
KOSMOS_IMMUNE=on
KOSMOS_RELATIONAL_MEMORY=postgres
```

Add typed settings for mission DB, worktree root, limits, and autonomy feature gate. Never commit credentials.

Fix the service unit’s stale DozerDB assumptions. It currently declares a DozerDB-backed description and an `ExecStartPre` check on port 7687 despite comments saying the dependency was removed. Gate only services that the configured production profile truly requires.

### Safe rollout

1. Build and install from the branch.
2. Back up the mission database.
3. Run migrations.
4. Start with autonomy disabled and readiness enabled.
5. Run fake-model API smoke.
6. Enable autonomy.
7. Run disposable-repository local-model smoke.
8. Restart during a second disposable mission.
9. Confirm resume.
10. Enable normal UI access.

### Commands

```bash
cd /home/rmholston/dev/kosmos-lms
.venv/bin/python -m build
.venv/bin/pip install --force-reinstall dist/*.whl

sudo cp ops/systemd/kosmos-kernel.service \
  /etc/systemd/system/kosmos-kernel.service
sudo systemctl daemon-reload
sudo systemctl restart kosmos-kernel
sudo systemctl status --no-pager kosmos-kernel
journalctl -u kosmos-kernel -n 300 --no-pager

curl -fsS http://127.0.0.1:8000/health | jq .
curl -fsS http://127.0.0.1:8000/api/tektos/readiness | jq .
```

### Commit

```text
ops(tektos): deploy typed mission runtime and readiness profile
```

## Phase 12: Legacy retirement

### Objective

Remove duplicate behavior only after the new path proves parity.

### Retirement order

1. Mark `TektosTurnLoop.run_turn(tool_calls=...)` compatibility input deprecated.
2. Migrate all API callers to `MissionService`.
3. Migrate SSE mapping to mission events.
4. Migrate UI callers.
5. Prove no runtime imports of the old decision path.
6. Delete duplicated decision logic but retain wire-compatible adapters as needed.
7. Update ADRs and route manifest.
8. Remove stale Tektos-Ultima proxy/docs only if no supported client still uses them.

Use repository searches:

```bash
rg 'run_turn\(|TektosAgent\(|/api/tektos/turn|/api/prompt/sse' \
  kernel plugins adapters ui tests
```

### Exit gate

There must be one controller implementation and one tool registry. Compatibility routes may remain, but they must invoke the same mission service and must be covered by parity tests.

### Commit

```text
refactor(tektos): retire duplicate one-shot agent execution paths
```

## Test matrix

| Tier | Dependencies | Frequency | Required coverage |
|---|---|---|---|
| Unit | In-memory/fakes only | Every commit | State transitions, parser, policy, paths, termination, context |
| Component | SQLite/temp Git/fake LLM | Every commit | Controller, store, worktree, tools, verification, recovery |
| API | FastAPI TestClient + deterministic profile | Every commit | Mission lifecycle, validation, replay, compatibility |
| UI | Built Next.js + deterministic kernel | Every PR | Create, stream, cancel, resume, diff, approvals |
| Local-model | llama.cpp lane | Before merge/release | Native tool use and autonomous repair |
| Service | Wheel + systemd-like process | Before release | Startup, readiness, restart, persistence |
| Safety | Temp worktree + adversarial requests | Every PR | Traversal, symlink, commands, network, secrets, approvals |
| Benchmark | Fixed task corpus | Release candidate | Success rate, retries, duration, malformed calls, regressions |

## Required acceptance tests

### Autonomous loop

- The controller—not the caller—selects tool calls from model output.
- Tool results are returned to the same model conversation.
- At least three inference rounds occur in the canonical fake test.
- Multiple tool calls in one model response preserve order.
- Malformed calls never execute.

### Safety

- Writes outside the worktree fail.
- Symlink escapes fail.
- Destructive commands require explicit policy approval or remain forbidden.
- Secret-like environment variables are absent from child processes.
- Tool output is bounded and redacted.
- Merge and push never occur under the coding lease.

### Reliability

- Restart resumes every safe state.
- Completed calls are idempotent.
- Cancellation kills descendants.
- A disconnected SSE client does not lose the mission.
- Event replay is ordered and gap-detectable.
- Mission limits stop runaway execution.

### Correctness

- Verification runs after the latest mutation.
- A new mutation invalidates the previous passing verification.
- The final report matches the actual diff and command results.
- The mission cannot self-declare success after failed tests.
- A no-change informational mission may finish without mutation-specific verification only under an explicit read-only mission profile.

### Packaging and CI

- Wheel import works from `/tmp`.
- Unit tests contact no external daemon.
- Full non-live suite runs in CI.
- Frontend lint, typecheck, build, and Playwright gates exist.
- GitHub Actions is green on the implementation branch.

## Benchmark corpus

Create a fixed `plugins/tektos/eval/tasks/autonomous/` corpus containing at least:

1. Rename a Python function and update callers.
2. Repair a failing parser edge case.
3. Add a small typed feature with tests.
4. Fix a TypeScript compile error.
5. Diagnose but do not edit a read-only task.
6. Reject an out-of-scope file request.
7. Recover from a failed test after the first edit.
8. Stop on an impossible task with evidence rather than fabricate success.
9. Resume after a forced crash.
10. Handle a context-heavy repository map without losing the objective.

Record:

```text
success/failure
iterations
model calls
tool calls
malformed tool calls
repeated calls
repair cycles
wall time
time to first useful action
verification commands
changed lines
recovery outcome
```

Do not optimize prompts against only one fixture. Keep a holdout task set.

## Observability

Emit stable event names:

```text
tektos.mission.created
tektos.mission.state_changed
tektos.mission.model.started
tektos.mission.model.completed
tektos.mission.tool.requested
tektos.mission.tool.blocked
tektos.mission.tool.started
tektos.mission.tool.completed
tektos.mission.verification.started
tektos.mission.verification.completed
tektos.mission.checkpoint.created
tektos.mission.approval.required
tektos.mission.cancelled
tektos.mission.failed
tektos.mission.completed
```

Every event must carry `mission_id`, sequence, timestamp, correlation ID, and safe metadata. Never emit secrets or unbounded file contents. Keep Prometheus metrics low-cardinality; do not use mission IDs as metric labels.

Suggested metrics:

```text
tektos_missions_total{terminal_status}
tektos_active_missions
tektos_model_calls_total{backend,outcome}
tektos_tool_calls_total{tool,outcome}
tektos_verification_runs_total{profile,outcome}
tektos_recoveries_total{outcome}
tektos_mission_duration_seconds
tektos_tool_duration_seconds{tool}
tektos_malformed_tool_calls_total{backend}
```

## Pull-request structure

Do not produce one giant PR. Preferred sequence:

| PR | Scope | Merge condition |
|---|---|---|
| 1 | Packaging, deterministic test profile, CI, hygiene | Green complete non-live suite and wheel smoke |
| 2 | Model/tool protocol and registry schemas | Fake provider parity tests green |
| 3 | Mission domain, SQLite store, worktree manager | Recovery and containment tests green |
| 4 | Capability leases and canonical controller | Fake autonomous repair green |
| 5 | API, SSE replay, compatibility routes | API lifecycle and parity tests green |
| 6 | UI mission control | Playwright vertical slice green |
| 7 | Local-model, crash, service deployment | Real-model repair and restart gates green |
| 8 | Legacy retirement and documentation | One controller path; complete regression suite green |

Each PR description must include:

```text
Problem reproduced
Root cause
Design/invariants
Files changed
Tests run
Observed results
Known limitations
Rollback procedure
Next phase
```

## Rollback strategy

- Keep autonomy behind `KOSMOS_TEKTOS_AUTONOMY=off|on` until Phase 11 completes.
- Database migrations must be forward-only and backward-readable where practical.
- Keep legacy routes mapped to the old path only until the new compatibility tests pass; then switch them behind the feature gate.
- Never delete mission worktrees during automatic rollback.
- A deployment rollback must preserve the mission database and artifacts.
- If a new controller build fails readiness, disable autonomy and retain read-only mission inspection.

## Stop conditions for Hermes

Hermes must stop and request human review if any of these occurs:

- The source checkout has unexpected user changes.
- A required fix would weaken path, command, approval, immune, or secret controls.
- A database migration would discard persisted state.
- A live test attempts to modify the real Kosmos checkout rather than a disposable worktree.
- Donor behavior conflicts with a ratified Kosmos ADR and no new ADR resolves it.
- Native tool calling cannot be produced reliably by the configured local model.
- More than one controller path remains after the retirement phase.
- Final verification fails or the diff contains unrelated broad changes.

## Final definition of done

Tektos is working only when all of the following are true:

1. A clean wheel installation starts outside the source tree.
2. `/api/tektos/readiness` reports native tool-call capability and every required subsystem.
3. A user creates a mission for a disposable Git repository.
4. Tektos creates its own worktree and records the immutable base commit.
5. The model independently reads repository files through registered tools.
6. The model edits only approved paths.
7. The model runs the failing test and receives the actual observation.
8. The model repairs the defect in a later inference round.
9. Required verification passes against the latest workspace head.
10. The UI and API show the exact diff, commands, outputs, and event history.
11. The mission waits for explicit merge approval.
12. Killing and restarting the kernel at any tested intermediate point resumes safely.
13. Cancelling a command kills its descendant processes.
14. The complete non-live backend, frontend, wheel, API, safety, and Playwright gates pass in GitHub Actions.
15. The local-model acceptance corpus records a successful autonomous repair without caller-supplied tool calls.

Anything less is an intermediate milestone, not completion.

---

## References

1. [NousResearch/hermes-agent: The agent that grows with you - GitHub](https://github.com/nousresearch/hermes-agent) - The agent that grows with you. Contribute to NousResearch/hermes-agent development by creating an ac...

2. [hermes-agent/AGENTS.md at main](https://github.com/NousResearch/hermes-agent/blob/main/AGENTS.md) - The agent that grows with you. Contribute to NousResearch/hermes-agent development by creating an ac...

3. [Using Hermes as a Python Library](https://hermes-agent.nousresearch.com/docs/guides/python-library) - Embed AIAgent in your own Python scripts, web apps, or automation pipelines — no CLI required

4. [Moving from Completions to Chat Completions in the OpenAI API](https://help.openai.com/en/articles/7042661-moving-from-completions-to-chat-completions-in-the-openai-api) - How to get migrate from the legacy OpenAI Completions API to Chat Completions

5. [Package Discovery and Namespace Packages - Setuptools](https://setuptools.pypa.io/en/latest/userguide/package_discovery.html)

6. [Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)

7. [pytest import mechanisms and sys.path / PYTHONPATH](https://docs.pytest.org/en/stable/explanation/pythonpath.html)

