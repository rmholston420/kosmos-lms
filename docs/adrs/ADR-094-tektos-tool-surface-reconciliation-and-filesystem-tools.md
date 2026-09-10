# ADR-094 — Tektos tool-surface reconciliation + filesystem tools with path-traversal detector

**Status:** Ratified (2026-09-10)
**Lock-in phase:** Stage 4.8
**Supersedes:** —
**Amends:** ADR-037 (§Locked constants preserved verbatim), ADR-093 (extends the Stage 4.7 tool registry with filesystem descriptors + MCP discovery bridge)

## Context

Two Tektos tool-execution surfaces exist in `kosmos-lms` after Stage 4.7 landed:

1. **Stage 3.2 surface** (ADR-037, landed) — `TektosAgent.call_tool(name, arguments, *, turn_id)` in `plugins/tektos/agent.py::call_tool` (lines 232-355). Resolves tier via `plugins/tektos/mcp/tool_policy.py::resolve_tier` against the hardcoded `TEKTOS_TOOL_TIER_MAP` (`browser_navigate`/`browser_snapshot`=AUTONOMOUS, `browser_click`/`browser_type`=HUMAN_REVIEW, `shell_exec`/`file_write`=HUMAN_REQUIRED). Emits `TraceEvent` on `TraceFeedPort` **before** the APEX gate (Phrouros observes every attempt). Calls `MCPPort.call_tool` directly on the injected adapter. Writes `MemoryPort` with `TEKTOS_TOOL_PREDICATE="tektos.tool.completed"` + `provenance=TEKTOS_AGENT_PROVENANCE="tektos_agent"` + confidence `0.75`.
2. **Stage 4.7 surface** (ADR-093, just landed) — `plugins/tektos/tools/registry.py::TektosToolRegistry.invoke(name, arguments, *, intention_id, proposing_domain="tektos")`. Per-descriptor `ToolDescriptor(approval_tier, network, timeout_seconds, ...)`. Routes every invoke through `ApprovalGatewayPort.propose` + polling `ApprovalResolverPort.get_by_id` for HUMAN_REVIEW/HUMAN_REQUIRED tiers. **Executes via `SandboxPort.run`** (never direct handler invocation). Publishes `tektos.tool.{invoked,approved,denied,completed}` on `EventBusPort` with `provenance="tektos_tool"` + `confidence=1.0`.

The two surfaces already share `"tektos.tool.completed"` as their envelope-predicate string (ADR-037 locked it; ADR-093 adopted it), so there is **no envelope-namespace collision**. What differs is:

| Concern | 3.2 surface (`agent.call_tool`) | 4.7 surface (`registry.invoke`) |
|---|---|---|
| Tier source | Hardcoded module-level map | Per-descriptor `ToolDescriptor.approval_tier` |
| Execution | Direct `MCPPort.call_tool` | `SandboxPort.run` with `SandboxLimits` |
| Trace-first (`TraceFeedPort`) | Yes — before APEX gate | No |
| Envelope shape | Not publishing to `EventBusPort` | `tektos.tool.{invoked,approved,denied,completed}` |
| Blocking model | Sync raise `TektosToolCallPending(approval_id)` on non-AUTONOMOUS | Async poll until terminal |
| MemoryPort provenance | `tektos_agent` + confidence `0.75` | `tektos_tool` + confidence `1.0` |
| Argument validation | None | JSON-schema via vendored `jsonschema` |

If Stage 4.8 lands filesystem tools on either surface without reconciling, the drift multiplies with every subsequent stage — Stage 5.6 self-modification, Stage 6.5 voice/vision, Stage 7.4 hindsight migration all interact with the tool substrate. And building filesystem tools **twice** — once on each surface — would violate `kosmos-port-workflow` §Stop conditions ("Two consecutive steps produce the same DEBUG_LOG symptom" — the projected symptom is "which registry does tool X live in?").

Stage 4.8 also needs to land **filesystem tools** with a **path-traversal detector**, per the Stage 4.7 PORTING_LEDGER deferrals (`Tektos filesystem tools` PLANNED Stage 4.8+) and the Kosmos-LMS integration plan (filesystem tools + MCP discovery are the two remaining Tektos runtime pieces before Stage 5.6 self-modification gates).

## Decision

**Three coupled decisions, all locked in Stage 4.8:**

### D1 — `TektosToolRegistry` is the single execution substrate

All Tektos tool invocations flow through `TektosToolRegistry.invoke()`. `TektosAgent.call_tool()` is preserved as a **compatibility shim** — its external API is unchanged (same signature, same `TektosStep` return, same `TektosToolCallPending` raise semantics on non-AUTONOMOUS tiers), but it delegates execution to the registry when constructed with the new optional `tool_registry` kwarg. When `tool_registry=None` (the Stage 3.2 construction path), the legacy inline flow is preserved unchanged — every existing Stage 3.2 + Stage 2.4 test continues to pass without modification.

### D2 — `MCPToolBridge` seeds the registry from `MCPPort.list_tools()`

A new `plugins/tektos/mcp/tool_bridge.py::MCPToolBridge` translates the `MCPTool` results of `MCPPort.list_tools()` into `ToolDescriptor` registrations on `TektosToolRegistry`. Tier resolution during translation uses `TEKTOS_TOOL_TIER_MAP` (the locked Stage 3.2 constant) as the seed default; tools absent from the map inherit `DEFAULT_TIER=HUMAN_REQUIRED` (fail-closed per ADR-037). The bridge preserves the MCP tool's original `MCPTool.name` + `MCPTool.description` + `MCPTool.input_schema` on the descriptor, and installs a handler that invokes `MCPPort.call_tool(name, arguments)` — so MCP tools execute **through** the sandbox by way of the registry, not around it.

### D3 — Filesystem tools land with path-traversal detector

Four filesystem tools register at `plugins/tektos/tools/filesystem.py`:

| Tool | Tier | Handler |
|---|---|---|
| `file_read` | AUTONOMOUS (read-only, budgeted per ADR-088) | argv `["cat", <resolved-path>]` via SandboxPort with `network="none"` |
| `file_list` | AUTONOMOUS (read-only, budgeted per ADR-088) | argv `["ls", "-la", <resolved-path>]` via SandboxPort with `network="none"` |
| `file_write` | HUMAN_REVIEW | argv `["tee", <resolved-path>]` with `stdin=<content>` via SandboxPort with `network="none"` |
| `file_delete` | HUMAN_REQUIRED | argv `["rm", "-rf", <resolved-path>]` via SandboxPort with `network="none"` (elevated tier reflects irreversibility per ADR-093 §Stop-conditions) |

Every filesystem-tool invocation runs a **path-traversal detector** (`plugins/tektos/tools/detectors/path_traversal.py::PathTraversalDetector` implementing the `Detector` Protocol from `ports/immune.py`) **before** the approval gate. The detector rejects:

1. Any path containing `".."` component
2. Any absolute path outside the constructor-provided `NamespaceRoot` (`Path.resolve()` starts-with check against the resolved root)
3. Any path that resolves through a symlink escaping the root (`Path.resolve(strict=True)` + starts-with re-check)

On block, the registry:
- Publishes `immune.verdict.block` on `EventBusPort` with the detector hit + `source_plugin="tektos"` + `kind="tektos.tool.filesystem"` per ADR-079 rule 1
- Writes `MemoryPort` with `provenance="immune_verdict"` + `confidence=1.0` per ADR-079 rule 2
- Publishes `tektos.tool.denied` with `payload["denial_reason"]="path_traversal"` + `provenance="tektos_tool"` + `confidence=1.0`
- Raises `PathTraversalDetected` (subclass of `ToolApprovalDenied` for uniform catch in callers)

The detector runs **before** `ApprovalGatewayPort.propose` — a malicious path never reaches the approval queue, satisfying zero-trust MemoryPort write discipline (ADR-008) and closing the "approve `../../etc/passwd`" attack vector.

## Rationale

**Alternative 1 rejected — Fold 4.7 registry into `TektosAgent.call_tool`.**
Reverse direction of D1. Would strand `SandboxPort.run` execution routing (`network="none"` via `unshare`, `resource.setrlimit`, cgroups v2) that Stage 4.7 explicitly landed. Also strands per-descriptor `SandboxLimits` (`timeout_seconds`, `max_memory_mb`), which is the whole point of adopting `SandboxPort` in Stage 4.7. Rejected.

**Alternative 2 rejected — Ship both surfaces indefinitely as siblings.**
Doubles the maintenance surface (every future tool needs two registration paths); guarantees drift ("which registry has tool X?"); violates the modular-swappable-components preference in `learned_user_context` and Kosmos-Build-Spec-v25 §Ports discipline. The Stage 4.7 PORTING_LEDGER deferral captured this explicitly: "Tektos MCP integration PLANNED Stage 4.8+" targets **the registry**, not a second agent-side path. Rejected.

**Alternative 3 rejected — Insert a new formal `ToolExecutionPort` and route both surfaces behind it.**
Adds a third layer without shrinking the first two. `TektosToolRegistry` already **is** the port-like surface (it consumes `SandboxPort` + `ApprovalGatewayPort` + `ApprovalResolverPort` + `EventBusPort` — every dependency injected as Protocol). A separate `ToolExecutionPort` would be a Protocol wrapping a class that already wraps only Protocols. Rejected as YAGNI.

**Alternative 4 rejected — Land filesystem tools without a detector, rely on `SandboxPort` unshare-based isolation.**
Sandbox isolation prevents damage to the host filesystem tree but does **not** prevent damage inside the sandbox's own bind-mounted workspace, which is where every real filesystem tool operates. The detector is what makes `NamespaceRoot` a real security boundary rather than a naming convention. Rejected.

**Alternative 5 rejected — Use OpenTelemetry / observability library instead of `ImmunePort` for path-traversal detection.**
`ImmunePort` is the Kosmos-native contract (ADR-079). Path traversal is a security event, not an observability event. `MemoryPort(provenance="immune_verdict", confidence=1.0)` is the durable audit trail. External telemetry libraries would violate ADR-007 (no cross-plugin coupling) and the "free, self-hosted, open-source tooling that runs on Linux" preference. Rejected.

**Why the tier assignments (§D3):**
- `file_read` + `file_list` are AUTONOMOUS because they are read-only and covered by the ADR-088 read-only tool-call budget interlock — a runaway agent hits `LoopSafetyPort` budget exhaustion long before it does damage.
- `file_write` is HUMAN_REVIEW (not HUMAN_REQUIRED) because ADR-037 already locked `file_write=HUMAN_REQUIRED` **for MCP-discovered `file_write` tools that come from arbitrary MCP servers**. The registry-native `file_write` is a different tool (Kosmos-native, sandboxed under `NamespaceRoot`, path-traversal-checked, argv-only, `tee`-based) — HUMAN_REVIEW reflects the reduced blast radius. This does **not** amend ADR-037; the MCP-side `file_write` tier map is unchanged.
- `file_delete` is HUMAN_REQUIRED because deletion is irreversible even inside `NamespaceRoot`.

**Why `tee`/`cat`/`ls`/`rm` argv instead of Python `Path.read_text()` etc:**
Stage 4.7 (ADR-093 §Decision) locked "all tool execution flows through `SandboxPort.run` — never direct handler invocation." Python-native `Path` operations would execute in the host process, bypassing `SandboxLimits` and the entire Stage 4.7 isolation boundary. Coreutils argv are the shortest path that keeps the isolation boundary intact. `stdin=<content>` for `file_write` avoids the shell-injection surface `tee` would introduce with `content` on the command line.

**Why the detector runs pre-approval:**
ADR-079 rule 2 requires `MemoryPort` writes for block verdicts with `confidence=1.0`. Running the detector post-approval would mean a proposal reaches APEX before being blocked — polluting the approval log with proposals that can never legally proceed. Pre-approval detection keeps APEX's queue signal-to-noise ratio high.

## Consequences

**Files affected:**

Created:
- `docs/adrs/ADR-094-tektos-tool-surface-reconciliation-and-filesystem-tools.md` (this file)
- `adapters/sandbox/tektos/vendor/fs_ops_donor.py` — vendored `_safe_path` + file_ops handlers from `providers/sandbox_provider.py`, trimmed for argv-first exec
- `plugins/tektos/tools/detectors/__init__.py`
- `plugins/tektos/tools/detectors/path_traversal.py` — `PathTraversalDetector(Detector)` + `PathTraversalDetected(ToolApprovalDenied)`
- `plugins/tektos/tools/detectors/test_path_traversal.py`
- `plugins/tektos/tools/filesystem.py` — `register_filesystem_tools(registry, *, namespace_root, sandbox)` factory that installs `file_read`/`file_list`/`file_write`/`file_delete` `ToolDescriptor`s
- `plugins/tektos/tools/test_filesystem.py`
- `plugins/tektos/mcp/tool_bridge.py` — `MCPToolBridge(mcp, registry, tier_map=TEKTOS_TOOL_TIER_MAP)` with `async discover_and_register()` method
- `plugins/tektos/mcp/test_tool_bridge.py`

Modified:
- `plugins/tektos/tools/registry.py` — `TektosToolRegistry.__init__` gains optional `pre_approval_detectors: tuple[Detector, ...] = ()` kwarg. Registry runs each detector's `evaluate()` sequentially before `ApprovalGatewayPort.propose`; on any `severity="block"` hit, publishes `immune.verdict.block` + `MemoryPort` write + `tektos.tool.denied` envelope + raises `PathTraversalDetected` (or generic `ToolApprovalDenied` for non-path-traversal detectors). Adds `PathTraversalDetected(ToolApprovalDenied)` subclass export.
- `plugins/tektos/agent.py::TektosAgent.__init__` — gains optional `tool_registry: TektosToolRegistry | None = None` kwarg. When set, `call_tool()` delegates to `tool_registry.invoke()` and shapes the return into `TektosStep` (preserving external API + `TektosToolCallPending` semantics). When `None`, the Stage 3.2 inline flow is preserved unchanged.
- `PORTING_LEDGER.md` — 2 rows flipped PLANNED→VENDORED (Tektos filesystem tools, Tektos MCP integration), 1 new VENDORED row (path-traversal detector)
- `docs/adrs/README.md` — ADR-094 row added; open-decisions sentence updated to note Stage 4.8 lands ADR-094
- `docs/Kosmos-Build-Sequence-v26.md` — new Stage 4.8 stanza inserted after Stage 4.7 (before Stage 5.6)
- `BUILD_LOG.md` — 8 append-only entries (one per Stage 4.8 subtask)
- `SESSION_HANDOFF.md` — overwritten with Stage 4.8 complete

**Ports affected:**
- `SandboxPort` — new consumer (filesystem tool handlers)
- `ImmunePort` — new consumer (path-traversal detector implements `Detector` Protocol; registry publishes `immune.verdict.*` envelopes)
- `EventBusPort` — new envelope kinds `immune.verdict.block` (ADR-079 rule 1) alongside existing `tektos.tool.*`
- `MemoryPort` — new write path (`provenance="immune_verdict"`, `confidence=1.0`) per ADR-079 rule 2

**PORTING_LEDGER impact:**
- `Tektos filesystem tools` PLANNED (Stage 4.8+) → **VENDORED (Stage 4.8)** with donor commit + adapter-layer modifications enumerated
- `Tektos MCP integration` PLANNED (Stage 4.8+) → **VENDORED (Stage 4.8)** — the Stage-3.2-locked `MCPPort` + `TEKTOS_TOOL_TIER_MAP` composed via `MCPToolBridge` onto Stage 4.7 registry
- New VENDORED row: `Tektos path-traversal detector` — Kosmos-native detector (donor `_safe_path` helper adapted into `Detector` Protocol form)

**Downstream ADR impact:**
- ADR-037 (Tektos tool-call policy) — NOT amended. Its locked constants (`TEKTOS_TOOL_TIER_MAP`, `TEKTOS_TOOL_PREDICATE`, `DEFAULT_TIER=HUMAN_REQUIRED`) are consumed verbatim by `MCPToolBridge`.
- ADR-088 (loop-safety read-only budget) — filesystem `file_read`/`file_list` classified read-only; consume budget when the registry is constructed with a `read_only_budget` reference (Stage 4.8+1 wiring).
- ADR-090 (SelfModificationPort — DEFERRED) — unblocked for Stage 5.6 filesystem-mutation guard, but not ratified here.
- ADR-093 (Stage 4.7 sandbox+planner+tool-registry scope) — extended, not amended: §5 exclusions "filesystem tools" and "MCP tool discovery" both close in Stage 4.8.

## Lock-in phase

Stage 4.8 locks:
1. The compatibility-preserving delegation path in `TektosAgent.__init__(tool_registry=...)` (D1).
2. `MCPToolBridge.discover_and_register()` as the sole path by which MCP-discovered tools enter `TektosToolRegistry` (D2).
3. The four filesystem-tool descriptors + tier assignments (D3) + `PathTraversalDetector` running pre-approval.

## References

- ADR-037 — Tektos MCP tool-call policy (Stage 3.2, LOCKED)
- ADR-079 — ImmunePort Protocol (Stage 3.13, RATIFIED)
- ADR-082 — SandboxPort Protocol (Stage 4.7, RATIFIED)
- ADR-088 — Loop-safety read-only budget (Stage 3.13, RATIFIED)
- ADR-093 — Stage 4.7 sandbox + planner + tool-registry absorption scope (Stage 4.7, RATIFIED)
- `plugins/tektos/mcp/tool_policy.py` (locked constants preserved by MCPToolBridge)
- `plugins/tektos/agent.py::TektosAgent.call_tool` (compatibility shim added, external API unchanged)
- `plugins/tektos/tools/registry.py::TektosToolRegistry` (pre-approval detectors added)
- Upstream donor: `github.com/rmholston420/tektos-ultima` @ commit `2b45cac1f9ac214c85ff53571b949445b5415209`, path `src/tektos/providers/sandbox_provider.py` (`_safe_path` + `_file_read` + `_file_write` + `_file_delete` + `_format_file_read`)
- `PORTING_LEDGER.md` (rows flipped VENDORED Stage 4.8)
- `docs/Kosmos-Build-Sequence-v26.md` (new Stage 4.8 stanza inserted)
