# ADR-093 — Tektos sandbox + planner + tool-registry absorption scope (Stage 4.7)

**Status:** Ratified
**Lock-in phase:** Stage 4.7
**Supersedes:** —

## Context

Stage 4.7 lands three coupled Tektos capabilities behind Stage 1 formal ports:

1. **SandboxPort** (ADR-082, 19th formal port) — the first non-stub adapter.
2. **Tektos planner** (`plugins/tektos/planner/`) — emits `tektos.plan.*` on `EventBusPort`, converts a prompt into a small graph of plan nodes.
3. **Tektos tool registry** (`plugins/tektos/tools/`) — declares tools with approval tiers, routes execution through `SandboxPort`, and gates elevated tiers through `ApprovalGatewayPort`.

The Tektos-Ultima donor at `rmholston420/tektos-ultima` @ `2b45cac1f9ac214c85ff53571b949445b5415209` offers:

- `src/tektos/providers/sandbox_provider.py` (763 lines) — a `subprocess.run(..., shell=True, timeout=..., cwd=fs_root)` wrapper with output-size cap, PEP-668 hint injection, sudo auto-retry, and a Docker-exec proxy branch for Terminal-Bench. **No namespaces, no cgroups, no rlimits.**
- `src/tektos/agents/planner/orchestrator.py` + `translator.py` + `disambiguator.py` + `spec_generator.py` + `models.py` + 4 more (~2000 lines total) — LLM-heavy planner that does language-game translation → disambiguation → spec generation → orchestration. Depends on `llm_client`, `repo_map`, `template_selector`.
- `src/tektos/tools/registry.py` (553 lines) — `ToolRegistry` + `ToolDefinition` with JSON-schema validation, MCP integration, event emission. Handlers are direct Python callables; no approval-tier field, no sandbox routing.

Three problems with wholesale-import:

- The donor sandbox has none of the isolation ADR-082 §Enforcement rule 4 assumes. Straight vendor would satisfy the port shape but violate the spirit of the port.
- The donor planner imports 5 sibling modules under `src/tektos/`; ADR-007 (events-only cross-plugin coupling) rejects wholesale-import.
- The donor tool registry has no approval-tier concept; the Stage 4.7 DoD requires approval-gated tiers via `ApprovalGatewayPort` — that's a genuine addition, not a port-in.

## Decision

Land the three capabilities as a **vendor-plus-adapter** slice per `kosmos-port-workflow`, with the sandbox capability split across **two SandboxPort adapters**:

### 1. Vendor donor snapshots

Two donor snapshots, each with SPDX-MIT + provenance banner (rmholston420/tektos-ultima @ `2b45cac1f9ac214c85ff53571b949445b5415209`, MIT re-license at port-in per scaffold policy; rmholston420 sole copyright):

- `adapters/sandbox/tektos/vendor/sandbox_exec_donor.py` — **trimmed** from `src/tektos/providers/sandbox_provider.py`: kept the `subprocess`-based `_bash_exec(command, *, cwd, env, timeout, max_output)` primitive, the output-cap constant, and the `_docker_exec` helper (unused at Stage 4.7 but retained for future Terminal-Bench integration). Dropped: file_read/write/delete/directory tools (Stage 4.8+), sudo auto-retry (leaks host state), PEP-668 hint injection (Kosmos policy chooses at a higher layer), `search` grep (RepoMapPort surface). Result: ~180 lines.
- `adapters/sandbox/tektos/vendor/tool_registry_donor.py` — **trimmed** from `src/tektos/tools/registry.py`: kept the `ToolDefinition` shape (`name`, `description`, `parameters` JSON schema, `handler` callable, `enabled`, `timeout`) and JSON-schema parameter validation. Dropped: MCP client integration (Stage 4.8+), REST API surface, direct event emission (kosmos routes envelopes through `EventBusPort`). Result: ~140 lines.

The planner receives **no donor snapshot** at 4.7. The 8-module donor planner is deeply LLM-coupled and depends on `llm_client`, `repo_map`, `template_selector`. Stage 4.7 lands a **minimal Kosmos-native planner seed** (`plugins/tektos/planner/turn_planner.py`, ~180 lines) that emits `tektos.plan.*` envelopes for a hand-authored plan graph. Full donor absorption (with LLM-based translator + disambiguator + spec_generator) lands after `LLMPort` gains role-routing at ADR-087's Colossus benchmark. Recorded as PLANNED in `PORTING_LEDGER.md`.

### 2. Two SandboxPort adapters

Both live under `adapters/sandbox/<vendor>/adapter.py`, both satisfy `SandboxPort` (ADR-082), and both are wired into the kernel boot order after `approval` per ADR-082 §Consequences.

**`adapters/sandbox/noop/adapter.py` — `NoOpSandboxAdapter`** (ADR-082 §Enforcement rule 4). Synthesises `SandboxResult` without executing anything: `exit_code=0`, `stdout=""`, `wall_seconds=0.0`, `peak_memory_mb=0`, `killed_by="exit"`. Publishes `sandbox.started` + `sandbox.completed` envelopes; writes `MemoryPort` with `provenance="sandbox"`, `confidence=1.0`, `attributes["noop"]=True`. Selected in CI where a real sandbox is unavailable and for contract tests that need Protocol conformance without side effects.

**`adapters/sandbox/tektos/adapter.py` — `TektosSandboxAdapter`**. Wraps donor `_bash_exec` behind `SandboxPort` and adds the isolation the donor lacks:

- `argv`-first execution — `subprocess.exec(argv, shell=False, ...)` — not `shell=True`. `SandboxRequest.command` becomes `argv[0]` when `argv[0]` isn't already set explicitly. This closes the donor's shell-injection surface.
- `resource.setrlimit` via `preexec_fn` for `RLIMIT_AS` (memory), `RLIMIT_CPU`, and `RLIMIT_FSIZE` per `SandboxLimits`.
- `SandboxLimits.network`:
  - `"none"` — default. Adapter attempts `unshare -n` prefix when available on Linux; when unavailable (Darwin, Windows, `unshare` missing, or CAP_SYS_ADMIN absent), the adapter **fails-closed**: publishes `sandbox.isolation_unavailable` envelope and returns a `SandboxResult` with `exit_code=126`, `killed_by="limit"`, `stderr="network isolation unavailable on this platform"`. This preserves ADR-082 §Enforcement rule 3 (fail-closed) rather than silently degrading.
  - `"loopback"` — best-effort `unshare -n` + loopback bring-up; same fallback rule.
  - `"full"` — no network namespace. Must be approval-gated at the tool-registry layer (Stage 4.7 §3 below).
- Cgroups v2 memory caps written to `/sys/fs/cgroup/kosmos-sandbox/<run_id>/memory.max` **only when** the mount is writable by the current uid; otherwise the adapter relies on `RLIMIT_AS` alone and publishes `sandbox.cgroups_unavailable` on the first call (throttled).
- Wall-time enforcement: `subprocess.wait(timeout=...)` in `asyncio.to_thread`; on `TimeoutExpired` the adapter escalates SIGTERM → SIGKILL, returns `killed_by="limit"`.
- Publishes `sandbox.started` + (`sandbox.completed` XOR `sandbox.killed`) on every `run()` per ADR-082 §Enforcement rule 1.
- Writes every `SandboxResult` to `MemoryPort` with `provenance="sandbox"`, `confidence=1.0` per ADR-082 §Enforcement rule 2 + §25.4. `subject="sandbox_run:<run_id>"`, `predicate="terminated_with"`, `object="exit"|"limit"|"user"`.
- `kill(run_id)` is idempotent; `close()` cascades-kill every active run then flips `is_healthy()`.

Both adapters live under formal `SandboxPort` per ADR-007 — plugins never import either directly.

### 3. Tektos planner (Kosmos-native seed)

`plugins/tektos/planner/turn_planner.py` — `TektosTurnPlanner.plan(prompt: str) -> Plan`. A `Plan` is a frozen `tuple[PlanNode, ...]`. `PlanNode` carries `node_id`, `kind` (Literal `"read"|"analyze"|"tool_call"|"summarize"`), `description`, `tool_name: str | None`, and `depends_on: tuple[str, ...]`.

At Stage 4.7 the planner is **hand-authored** — a fixed three-node plan `(read → analyze → summarize)` derived from the prompt with no LLM call. This satisfies the DoD verb ("a scripted plan node round-trips through `EventBusPort`") without pulling in `LLMPort` + role-routing (deferred to Stage 4.7+1).

Every `plan()` call publishes `tektos.plan.started`, one `tektos.plan.node` envelope per node, and `tektos.plan.completed` on `EventBusPort` per ADR-086. Envelopes carry `plan_id`, `node_id`, and `correlation_id=plan_id` inside `payload`.

### 4. Tektos tool registry (approval-gated)

`plugins/tektos/tools/registry.py` — `TektosToolRegistry` + `ToolDescriptor` (frozen dataclass extending the donor's shape with `approval_tier: ChangeApprovalTier` + `network: SandboxNetworkPolicy`).

Registration surface:

```python
registry.register(
    ToolDescriptor(
        name="bash",
        description="Run a shell command inside the sandbox.",
        parameters={"type": "object", "properties": {"argv": {"type": "array"}, ...}},
        approval_tier=ChangeApprovalTier.HUMAN_REVIEW,
        network="none",
    )
)
```

Execution surface:

```python
result = await registry.invoke(
    tool_name="bash",
    arguments={"argv": ["/bin/ls", "-la"]},
    intention_id="turn-abc-n0",
    proposing_domain="tektos",
)
```

`invoke` flow:

1. Look up `ToolDescriptor` by name — raise `ToolNotFound` if missing.
2. Validate arguments against `ToolDescriptor.parameters` JSON schema (donor helper).
3. Call `ApprovalGatewayPort.propose(intention_id, delta={...}, tier=descriptor.approval_tier, proposing_domain=proposing_domain)`.
   - `AUTONOMOUS` tier: `propose` returns synchronously; proceed.
   - `HUMAN_REVIEW` / `HUMAN_REQUIRED`: `propose` returns an opaque `approval_id`. Registry blocks on `ApprovalResolverPort.get_by_id(approval_id)` (polled every 100 ms with jittered backoff, hard cap `descriptor.timeout` seconds), then either proceeds on `APPROVED`/`MODIFIED` or raises `ToolApprovalDenied` on `REJECTED`/`REVIEW_MISSED`.
4. Build `SandboxRequest` from validated arguments + descriptor `network` policy + tool timeout.
5. Call `SandboxPort.run(request)`. Result flows back to the caller.
6. Publish `tektos.tool.{invoked,approved,denied,completed}` on `EventBusPort` per ADR-086. Every terminal envelope carries `provenance="tektos_tool"` and `confidence=1.0` in `payload` per Stage 4.7 DoD.

The registry accepts an injected `ApprovalGatewayPort` + `ApprovalResolverPort` + `SandboxPort` + optional `EventBusPort` at construction. Contract tests inject stubs; the real kernel wires Praxis APEX + Tektos sandbox adapter + Valkey event bus.

### 5. What Stage 4.7 explicitly does NOT ship

Deferred to Stage 4.7+1 or later:

- LLM-driven planner (`translator`, `disambiguator`, `spec_generator`, `orchestrator`, `template_selector`) — pending ADR-087 Colossus benchmark.
- File-system tools (`file_read`, `file_write`, `file_delete`, `directory_list`, `directory_create`) — pending path-traversal detector + write-approval flow.
- `search` tool — pending `RepoMapPort` surface.
- MCP tool discovery — pending Stage 4.8 MCP integration.
- Docker-exec proxy branch — retained in vendor snapshot but not wired; pending Terminal-Bench integration.
- Cgroups v1 fallback — Kosmos targets Linux 5.15+ (cgroups v2); v1-only hosts are out of scope.
- Firecracker / gVisor VM isolation — future `adapters/sandbox/firecracker/` per ADR-082 §Consequences.
- Real `ApprovalGatewayPort` wiring to Praxis APEX — the registry accepts an injected port; Stage 4.8 wires Praxis for real.

Each deferred item is captured as PLANNED in `PORTING_LEDGER.md` with a target stage.

## Rationale

- **Vendor + adapter over wholesale-import**: donor lacks isolation (sandbox) and approval tiering (tool registry); adapter layer is where those get added without editing donor code. Same pattern that landed Stage 3.13 cleanly.
- **Two sandbox adapters at once (NoOp + Tektos)**: ADR-082 §Enforcement rule 4 mandates both. Shipping only Tektos would leave CI unable to construct a `SandboxPort` on non-Linux/permission-limited runners; shipping only NoOp would defer the actual capability.
- **Kosmos-native planner seed instead of donor port**: the 8-module donor planner is 100% LLM-coupled. Landing it at 4.7 forces `LLMPort` role-routing (ADR-087) to land on the critical path; the DoD verb (a plan node round-trips through EventBusPort) does not require LLM inference. Deferred to Stage 4.7+1.
- **Approval-tier on `ToolDescriptor`**: the DoD explicitly requires "approval-required tool call blocks until `ApprovalPort` decision returns". Tier lives on the descriptor (not the call site) so a policy audit can enumerate exactly which tools require what. Uses the existing `ChangeApprovalTier` enum from `ports.approval` — no new tier concept.
- **Poll `ApprovalResolverPort.get_by_id` instead of registering a callback**: the resolver Protocol has no subscription surface. Polling with jittered backoff + hard timeout is the shape both Praxis APEX and the Stage 4.7 stub implement; a subscription surface is a separate ADR if adoption warrants it.
- **`sandbox.isolation_unavailable` fail-closed for `network="none"`**: the alternative — silently running without isolation — would violate ADR-082 §Enforcement rule 3. The envelope makes the degradation observable so an operator can either grant CAP_SYS_ADMIN or switch to the NoOp adapter deliberately.

### Alternatives considered and rejected

- **Wholesale-import of `src/tektos/providers/sandbox_provider.py` under `SandboxPort`.** Rejected because it satisfies the port shape without any of the isolation ADR-082 assumes; it would ship a false sense of security.
- **Firecracker-first for `TektosSandboxAdapter`.** Rejected because the donor doesn't use it, the Colossus workstation isn't provisioned for VM-in-VM, and every deferred alternative (namespaces+cgroups) is a strictly weaker guarantee. Firecracker becomes a separate `adapters/sandbox/firecracker/` when the deployment surface for it exists.
- **Fold approval-tier into `SandboxPort.run` (require every `SandboxRequest` to carry a tier).** Rejected because it couples the port to the approval surface — a future non-tool `SandboxPort` consumer (e.g. hindsight recall replay) would have no meaningful tier. Approval lives at the tool-registry layer, one hop up.
- **Wholesale-import of donor planner behind a thin adapter.** Rejected because ADR-007 forbids importing 5 sibling modules under `src/tektos/`, and the donor planner has no meaningful behaviour without a live `LLMPort` — the DoD would not pass without also landing ADR-087. Sequencing puts LLM role-routing at 4.7+1, planner-that-actually-plans at 4.7+2.

## Consequences

- Files created (this ADR): `docs/adrs/ADR-093-tektos-sandbox-planner-tools-absorption-scope.md`.
- Files planned (Stage 4.7):
  - `adapters/sandbox/tektos/vendor/sandbox_exec_donor.py` (donor snapshot)
  - `adapters/sandbox/tektos/vendor/tool_registry_donor.py` (donor snapshot)
  - `adapters/sandbox/{tektos,noop}/adapter.py` + `test_contract.py` + `__init__.py`
  - `plugins/tektos/planner/turn_planner.py` + `test_turn_planner.py` + `__init__.py`
  - `plugins/tektos/tools/registry.py` + `test_registry.py` + `__init__.py`
- `PORTING_LEDGER.md` gains three VENDORED rows (Tektos sandbox exec, Tektos tool registry seed, Tektos tool registry MCP integration→PLANNED) and one PLANNED row (Tektos planner full donor port).
- Kernel boot order (§25.5) remains unchanged — SandboxPort already sits after `approval`.
- Stage 4.7 DoD ("SandboxPort contract test proves resource limits enforced; a scripted plan node round-trips through EventBusPort; an approval-required tool call blocks until ApprovalPort decision returns; `tektos.tool.*` envelopes carry `provenance=tektos_tool` and `confidence=1.0`") — every clause satisfied by the artifacts above.

## Lock-in phase

Locked at Stage 4.7.

## References

- ADR-077, ADR-078 (Kosmos-Build-Sequence v26)
- ADR-082 (SandboxPort — target of this decision)
- ADR-086 (EventBusPort envelope taxonomy — `sandbox.*`, `tektos.plan.*`, `tektos.tool.*`)
- ADR-087 (Hermes LLM topology — planner ratification pre-condition for 4.7+1)
- ADR-092 (Stage 3.13 absorption scope — established the vendor+adapter pattern this ADR extends)
- ADR-007 (events-only cross-plugin coupling)
- `kosmos-port-workflow` skill (vendor-before-hand-build discipline)
