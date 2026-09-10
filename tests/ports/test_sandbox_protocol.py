"""Protocol conformance test for SandboxPort (ADR-082).

Any adapter satisfying ``SandboxPort`` MUST pass this test. Fast tier —
no real namespaces/cgroups. Uses a stub adapter that echoes the request.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ports.sandbox import (
    SandboxHandle,
    SandboxLimits,
    SandboxPort,
    SandboxRequest,
    SandboxResult,
)


class _StubSandboxAdapter:
    """Minimal SandboxPort implementation used only for protocol tests."""

    def __init__(self) -> None:
        self._closed = False
        self._active: dict[str, SandboxHandle] = {}
        self._next = 0

    async def run(self, request: SandboxRequest) -> SandboxResult:
        self._next += 1
        run_id = f"run-{self._next}"
        handle = SandboxHandle(
            run_id=run_id,
            started_at=datetime.now(timezone.utc),
            request=request,
        )
        self._active[run_id] = handle
        try:
            return SandboxResult(
                run_id=run_id,
                exit_code=0,
                stdout=f"stub:{request.command}",
                stderr="",
                wall_seconds=0.001,
                peak_memory_mb=1,
                killed_by="exit",
            )
        finally:
            self._active.pop(run_id, None)

    async def kill(self, run_id: str) -> None:
        self._active.pop(run_id, None)  # idempotent

    async def list_active(self) -> tuple[SandboxHandle, ...]:
        return tuple(self._active.values())

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        # Cascade kill any active runs (idempotent).
        for run_id in list(self._active):
            await self.kill(run_id)
        self._closed = True


def _mk_request() -> SandboxRequest:
    return SandboxRequest(
        command="/bin/echo",
        argv=("/bin/echo", "hi"),
        cwd="/tmp",
        env={"PATH": "/usr/bin"},
        limits=SandboxLimits(
            max_wall_seconds=5,
            max_memory_mb=64,
            max_cpu_percent=100,
            # network default MUST be "none" per ADR-082 fail-closed rule.
        ),
    )


def test_stub_adapter_satisfies_protocol_runtime_checkable() -> None:
    assert isinstance(_StubSandboxAdapter(), SandboxPort)


def test_sandbox_limits_network_defaults_to_none() -> None:
    # ADR-082 fail-closed default.
    limits = SandboxLimits(
        max_wall_seconds=1,
        max_memory_mb=1,
        max_cpu_percent=1,
    )
    assert limits.network == "none"


def test_run_returns_result_shape() -> None:
    adapter = _StubSandboxAdapter()

    result = asyncio.run(adapter.run(_mk_request()))
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert result.stdout.startswith("stub:")
    assert result.wall_seconds >= 0
    assert result.peak_memory_mb >= 0


def test_sandbox_request_argv_is_tuple() -> None:
    # ADR-082: SandboxRequest.argv is a tuple so subsequences and slicing
    # remain immutable across passing between kernel + adapter.
    req = _mk_request()
    assert isinstance(req.argv, tuple)


def test_kill_is_idempotent() -> None:
    adapter = _StubSandboxAdapter()

    async def _run() -> None:
        await adapter.kill("nonexistent")
        await adapter.kill("nonexistent")

    asyncio.run(_run())


def test_list_active_returns_tuple() -> None:
    adapter = _StubSandboxAdapter()
    active = asyncio.run(adapter.list_active())
    assert isinstance(active, tuple)


def test_is_healthy_never_raises() -> None:
    adapter = _StubSandboxAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False


def test_close_is_idempotent() -> None:
    adapter = _StubSandboxAdapter()

    async def _run() -> None:
        await adapter.close()
        await adapter.close()

    asyncio.run(_run())
