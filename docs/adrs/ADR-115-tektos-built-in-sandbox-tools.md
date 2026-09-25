# ADR-115 — Tektos built-in sandbox tools: bash, directory_create, search (Stages 9.2 + 9.3)

**Status:** Ratified
**Date:** 2026-09-25
**Stage:** v2 Stage 9.2 + 9.3 (Plan §9.2–9.3, lines 107–190)
**Discharges:** Stage 3.13/4.8 deferral (the donor's `load_built_in` tool factory was trimmed at vendor time — the three built-in tools `bash`, `directory_create`, `search` were never landed); Stage 9 exit-gate DoD "7 tools invocable".

---

## Context

Stage 4.8 (ADR-094) landed four filesystem tools (`read_file`, `write_file`, `patch` plus the `TektosToolRegistry` surface) with the path-traversal pre-approval detector. The donor's built-in tool factory (`tool_registry_donor.py`) was trimmed to a marker during vendoring — the canonical definitions of `bash`, `directory_create`, and `search` (Tektos `src/tektos/tools/registry.py` L160–305) were never ported. Stage 9.2 closes that gap so the exit-gate DoD (12 detectors + 7 tools invocable) can be met.

Canonical donor semantics:

| Tool | Donor behavior |
|---|---|
| `bash` | `bash -c <command>` with timeout, cwd pinning, captured stdout/stderr/exit_code |
| `directory_create` | `mkdir -p <path>` relative to the configured namespace root |
| `search` | `rg --line-number` (ripgrep) with case-sensitivity and result-count limits, scoped under the namespace root |

Alternatives considered:

1. **Vendor the donor factory verbatim.** Rejected — the donor factory imports its own `ToolDefinition` dataclass and its own handler signatures that do not match Kosmos's `ToolDescriptor` + `SandboxPort` layering; ADR-094 already set the rewrite-over-vendor precedent for this tool surface.
2. **Implement `bash` as `shell` + separate `command` tools.** Rejected — the donor's single `bash -c` tool matches the MCP tool surface the orchestrator's terminal agent already dispatches against (ADR-114 D2); splitting would break parity.

## Decision

### D1 — One module, three tools

`plugins/tektos/tools/builtin.py` defines `register_builtin_tools(registry)` which registers all three tools as `ToolDescriptor` entries with the same `ToolDescriptor` pattern as `filesystem.py`. Helpers `invoke_bash`, `invoke_directory_create`, `invoke_search` are thin argv-building wrappers that route through `registry.invoke` so every call passes the approval gate + pre-approval detectors + sandbox uniformly.

### D2 — Execution via SandboxPort, never raw subprocess

All three tools build argv lists (no `shell=True`) and execute through the bound `SandboxPort` — the registry's existing execution path (ADR-094 R1 precedent). `bash` receives `argv=["bash", "-c", command]`; `directory_create` receives `["mkdir", "-p", target]` where `target = <namespace_root>/<path>`; `search` receives `["rg", "--line-number", ...flags, query, scope]`. No new execution surface, no new sandbox bypass.

### D3 — Path safety for the two path-bearing tools

`directory_create` and `search` resolve their path arguments under the `FilesystemToolConfig.namespace_root` using the existing `resolve_within_root` helper (the same helper `write_file` uses). Escape attempts are blocked **before** sandbox dispatch: (a) the `PathTraversalDetector` is extended — `FILESYSTEM_TOOL_NAMES` gains `directory_create` and `search` so the detector's argv-scan fires on the pre-approval pass; (b) `resolve_within_root` raises `PathTraversalDetected` as the defense-in-depth layer for any argument the detector's scan cannot see. `bash` is intentionally NOT path-scoped — it inherits the sandbox's own isolation policy (network policy + rlimits) and the `DangerousCommand` immune detector for command-level screening; scoping `bash` cwd to the namespace root is preserved from the donor.

### D4 — Tier map

All three tools are registered at the same approval tier the filesystem tools use (per `_TIER_MAP` in `tool_policy.py`): `directory_create` = `AUTONOMOUS` (non-destructive), `search` = `AUTONOMOUS` (read-only), `bash` = `HUMAN_REQUIRED` (arbitrary command execution — ADR-094 D3 ceiling). The tier is resolved by the existing registry approval path; no new tier logic.

### D5 — DoD test (Stage 9.3)

`plugins/tektos/tools/test_builtin.py` (11 tests) pins: registration (3 descriptors present, idempotent re-register), per-tool invocation via the real `TektosSandboxAdapter` for argv shape proof, `bash` timeout + exit-code propagation, `directory_create` nested creation, `search` match count + `--line-number` output shape, path-traversal blocking on both path-bearing tools (detector + resolver layers), and a 7-tool exit-gate test proving all of `read_file`, `write_file`, `patch`, `bash`, `directory_create`, `search` (+ the registry surface) are invocable on one registry.

### D6 — Environment finding (documented, not fixed here)

During live verification, `SandboxPort` network-isolated runs (`network="none"`, the wrapper `unshare --user --map-root-user --net`) fail on the Collosus host with `write failed /proc/self/uid_map: Operation not permitted` even for a bare `unshare --user` from a plain shell — a host-level user-namespace restriction (kernel.unprivileged_userns_clone=1 but uid_map writes denied). This is pre-existing and affects the Stage 8.7 terminal agent path identically. Contract tests and argv-shape proof run with `network="full"` (isolation gate bypassed at the adapter level by design — the adapter's own `_network_guard` pre-check is what enforces the policy, and full never guards). Fixing the host userns policy is an ops task, out of scope here.

---

## Consequences

- 7 built-in tools invocable through `TektosToolRegistry` — Stage 9 exit-gate DoD tool half complete.
- `PathTraversalDetector` file grows one constant entry (`directory_create`, `search`); no new detector class.
- `bash` remains the highest-risk tool in the surface; its risk is bounded by the `HUMAN_REQUIRED` tier + sandbox rlimits + `DangerousCommand` immune detector (Stage 9.1).
- The host userns restriction (D6) leaves `network="none"` isolation unavailable on Collosus until an ops fix; orchestrator terminal tasks fail-closed to `sandbox.isolation_unavailable` (exit 126) by design — no fail-open hole introduced.

## Open questions

- None — host userns policy is tracked as an ops task (D6), not an ADR question.
