# ADR-082 — SandboxPort (new formal port)

**Status:** Ratified
**Lock-in phase:** Stage 4.7
**Supersedes:** —

## Context

Tektos-Ultima executes shell commands during coding-agent turns (build, test, lint, grep). In Tektos-Ultima these run in a namespaced + cgroup-limited Linux sandbox. In kosmos-lms this capability must sit behind a formal port so:

1. Approval-gated tools can route through `ApprovalPort` before invoking the sandbox.
2. Sandbox results are observable on `EventBusPort` (Phrouros anomaly detection can watch for suspicious command patterns).
3. Every sandbox result is a `MemoryPort` event with provenance so post-mortems are reproducible.
4. Non-Colossus deployments can substitute a different sandbox (e.g. `NoOpSandboxAdapter` for CI, `FirecrackerSandboxAdapter` if a future deployment needs VM isolation).

## Decision

Introduce **`SandboxPort`** as the 19th formal Kosmos port at `ports/sandbox.py`.

### Protocol surface

```python
@runtime_checkable
class SandboxPort(Protocol):
    async def run(self, request: SandboxRequest) -> SandboxResult: ...
    async def kill(self, run_id: str) -> None: ...
    async def list_active(self) -> tuple[SandboxHandle, ...]: ...
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...
```

Value objects (frozen dataclasses):

- `SandboxRequest{command: str, argv: tuple[str, ...], cwd: str, env: dict[str, str], limits: SandboxLimits, stdin: str | None = None}`.
- `SandboxLimits{max_wall_seconds: int, max_memory_mb: int, max_cpu_percent: int, network: Literal["none","loopback","full"] = "none"}`.
- `SandboxResult{run_id: str, exit_code: int, stdout: str, stderr: str, wall_seconds: float, peak_memory_mb: int, killed_by: Literal["exit","limit","user"] | None}`.
- `SandboxHandle{run_id: str, started_at: datetime, request: SandboxRequest}`.

### Enforcement rules

1. Every `run()` invocation MUST publish `sandbox.started` and `sandbox.completed` (or `sandbox.killed`) envelopes on `EventBusPort`.
2. Every `SandboxResult` MUST be written to `MemoryPort` with `provenance="sandbox"` and `confidence=1.0` per §25.4.
3. `SandboxLimits.network` defaults to `"none"`. Loopback and full network access require explicit request (approval-gated in Stage 4.7 tool registry).
4. Adapters live under `adapters/sandbox/<vendor>/`. The Tektos-Ultima adapter uses Linux namespaces + cgroups v2. `NoOpSandboxAdapter` returns synthetic results for CI where a real sandbox is unavailable.

## Rationale

- **Formal port over `subprocess.run` inline**: makes command execution observable and lets `ApprovalPort` gate it.
- **`SandboxLimits.network` default `"none"`**: fail-closed for network access.
- **`kill()` on the port** (rather than only inside the adapter): loop-safety needs to kill a runaway command from outside the tool that started it.
- **Rejected: fold into a generic `ExecPort`.** Sandbox implies isolation guarantees (cgroups/namespaces or equivalent); a generic exec port would elide those and callers would have no way to know what isolation they got.

## Consequences

- Files created (this ADR): `ports/sandbox.py`; `tests/ports/test_sandbox_protocol.py`.
- Files planned (Stage 4.7): `adapters/sandbox/tektos/adapter.py`, `adapters/sandbox/noop/adapter.py`, both with `test_contract.py`.
- Kernel boot order (§25.5) places `sandbox` after `approval` so gated writes route through both.
- Tektos tool registry (Stage 4.7) consumes `SandboxPort` for every command-executing tool.

## Lock-in phase

Locked at Stage 4.7.

## References

- ADR-077, ADR-078 (v26 §25.5)
- ADR-019 (Approval UX specification) — how approval gating composes
- ADR-023, ADR-027
