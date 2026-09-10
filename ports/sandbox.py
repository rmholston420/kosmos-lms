"""ports.sandbox — SandboxPort Protocol (ADR-082).

Formal Kosmos port for isolated command execution. Locked at Stage 4.7.
First adapter (Tektos-Ultima donor: Linux namespaces + cgroups v2) lands under
``adapters/sandbox/tektos/``. ``NoOpSandboxAdapter`` under
``adapters/sandbox/noop/`` returns synthetic results for CI where a real
sandbox is unavailable.

Enforcement rules (per ADR-082 + spec §25.4):

1. Every ``run()`` MUST publish ``sandbox.started`` and either
   ``sandbox.completed`` or ``sandbox.killed`` on ``EventBusPort``.
2. Every ``SandboxResult`` MUST be written to ``MemoryPort`` with
   ``provenance="sandbox"`` and ``confidence=1.0``.
3. ``SandboxLimits.network`` defaults to ``"none"`` (fail-closed).
   Loopback and full network access require explicit request; the tool
   registry (Stage 4.7) gates elevated network access through
   ``ApprovalPort``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "SandboxHandle",
    "SandboxKilledBy",
    "SandboxLimits",
    "SandboxNetworkPolicy",
    "SandboxPort",
    "SandboxRequest",
    "SandboxResult",
]


SandboxNetworkPolicy = Literal["none", "loopback", "full"]
"""Network isolation policy for a sandbox run — see ADR-082."""

SandboxKilledBy = Literal["exit", "limit", "user"]
"""Why a sandbox run terminated."""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Per-run isolation limits. Immutable. Fail-closed on network."""

    max_wall_seconds: int
    max_memory_mb: int
    max_cpu_percent: int
    network: SandboxNetworkPolicy = "none"


@dataclass(frozen=True, slots=True)
class SandboxRequest:
    """Immutable request for one sandboxed command execution.

    ``argv`` is a tuple (not a list) so the request is hashable and can be
    used as an idempotency key or cache lookup value.
    """

    command: str
    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]
    limits: SandboxLimits
    stdin: str | None = None


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """Immutable result of a sandbox run."""

    run_id: str
    exit_code: int
    stdout: str
    stderr: str
    wall_seconds: float
    peak_memory_mb: int
    killed_by: SandboxKilledBy | None = None


@dataclass(frozen=True, slots=True)
class SandboxHandle:
    """Handle for an in-flight sandbox run — returned by ``list_active``."""

    run_id: str
    started_at: datetime
    request: SandboxRequest


@runtime_checkable
class SandboxPort(Protocol):
    """Formal Kosmos contract for isolated command execution."""

    # ── Execution ─────────────────────────────────────────────────────────

    async def run(self, request: SandboxRequest) -> SandboxResult:
        """Execute ``request`` in isolation. Blocks until termination or limit
        breach. MUST publish sandbox lifecycle envelopes per ADR-082 rule 1.
        """
        ...

    async def kill(self, run_id: str) -> None:
        """Terminate an in-flight run. Idempotent — killing a finished run
        is a no-op."""
        ...

    async def list_active(self) -> tuple[SandboxHandle, ...]:
        """Return handles for every currently-running sandbox invocation."""
        ...

    # ── Health & lifecycle ────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Return True iff the adapter can execute new runs. Non-throwing."""
        ...

    async def close(self) -> None:
        """Release adapter resources. Idempotent. Kills any active runs."""
        ...
