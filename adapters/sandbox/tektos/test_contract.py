"""Contract tests for ``TektosSandboxAdapter`` (ADR-082, ADR-093).

Verifies:

1. Protocol conformance.
2. Real subprocess execution (echo returns stdout).
3. Wall-time limit enforcement (``sleep`` past the timeout classifies as
   ``killed_by="limit"``).
4. Every ``run()`` publishes ``sandbox.started`` + one of
   ``sandbox.completed`` / ``sandbox.killed`` on the event bus.
5. Every ``SandboxResult`` writes ``MemoryPort`` with
   ``provenance="sandbox"``, ``confidence=1.0``.
6. ``kill()`` is idempotent; ``close()`` cascades and flips
   ``is_healthy()``.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
from typing import Any

import pytest

from adapters.sandbox.tektos.adapter import TektosSandboxAdapter
from ports.event_envelope import EventEnvelope
from ports.sandbox import SandboxLimits, SandboxPort, SandboxRequest, SandboxResult


class _RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return f"evt-{len(self.published)}"


class _RecordingMemory:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        self.writes.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "provenance": provenance,
                "confidence": confidence,
                "attributes": attributes or {},
            }
        )
        return f"mem-{len(self.writes)}"


def _echo_request(network: str = "full") -> SandboxRequest:
    # Use network="full" by default so contract tests don't depend on
    # `unshare(1)` being present or the kernel allowing unprivileged
    # netns. The network-fail-closed path has its own dedicated test.
    return SandboxRequest(
        command="/bin/echo",
        argv=("/bin/echo", "hi"),
        cwd="/tmp",
        env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        limits=SandboxLimits(
            max_wall_seconds=5,
            max_memory_mb=64,
            max_cpu_percent=100,
            network=network,  # type: ignore[arg-type]
        ),
    )


def test_tektos_adapter_satisfies_sandbox_port() -> None:
    assert isinstance(TektosSandboxAdapter(), SandboxPort)


@pytest.mark.skipif(shutil.which("echo") is None, reason="/bin/echo missing")
def test_tektos_run_executes_argv() -> None:
    adapter = TektosSandboxAdapter()
    result = asyncio.run(adapter.run(_echo_request()))
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert "hi" in result.stdout
    assert result.killed_by == "exit"


@pytest.mark.skipif(shutil.which("sleep") is None, reason="/bin/sleep missing")
def test_tektos_run_enforces_wall_time_limit() -> None:
    adapter = TektosSandboxAdapter()
    req = SandboxRequest(
        command="sleep",
        argv=("sleep", "5"),
        cwd="/tmp",
        env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        limits=SandboxLimits(
            max_wall_seconds=1,
            max_memory_mb=64,
            max_cpu_percent=100,
            network="full",
        ),
    )
    result = asyncio.run(adapter.run(req))
    assert result.killed_by == "limit", f"expected timeout classification, got {result}"
    # subprocess convention: SIGKILL -> exit code -9 on Linux; on macOS
    # the donor's timeout path also uses -9.
    assert result.exit_code != 0


def test_tektos_run_publishes_started_and_terminal_envelope() -> None:
    bus = _RecordingEventBus()
    adapter = TektosSandboxAdapter(event_bus=bus)
    asyncio.run(adapter.run(_echo_request()))
    event_types = [env.event_type for env in bus.published]
    assert event_types[0] == "sandbox.started"
    assert event_types[-1] in ("sandbox.completed", "sandbox.killed")
    # correlation_id must live inside payload (ADR-086); EventEnvelope
    # has no top-level correlation_id.
    for env in bus.published:
        assert "correlation_id" in env.payload
        assert env.payload["correlation_id"] == env.payload["run_id"]
        assert env.producer_plugin == "tektos_sandbox_adapter"


def test_tektos_run_writes_memory_with_sandbox_provenance() -> None:
    mem = _RecordingMemory()
    adapter = TektosSandboxAdapter(memory=mem)
    asyncio.run(adapter.run(_echo_request()))
    assert len(mem.writes) == 1
    write = mem.writes[0]
    assert write["provenance"] == "sandbox"
    assert write["confidence"] == 1.0
    assert write["object"] in ("exit", "limit", "user")


def test_tektos_kill_is_idempotent() -> None:
    adapter = TektosSandboxAdapter()

    async def _run() -> None:
        await adapter.kill("nonexistent-1")
        await adapter.kill("nonexistent-2")

    asyncio.run(_run())


def test_tektos_close_flips_healthy_and_is_idempotent() -> None:
    adapter = TektosSandboxAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False
    asyncio.run(adapter.close())


def test_tektos_empty_argv_rejected() -> None:
    adapter = TektosSandboxAdapter()
    req = SandboxRequest(
        command="",
        argv=(),
        cwd="/tmp",
        env={},
        limits=SandboxLimits(
            max_wall_seconds=1,
            max_memory_mb=8,
            max_cpu_percent=100,
            network="full",
        ),
    )
    with pytest.raises(ValueError):
        asyncio.run(adapter.run(req))


@pytest.mark.skipif(
    platform.system() == "Linux" and shutil.which("unshare") is not None,
    reason="fail-closed path only fires when unshare(1) is unavailable",
)
def test_tektos_network_none_fails_closed_when_unshare_missing() -> None:
    bus = _RecordingEventBus()
    mem = _RecordingMemory()
    adapter = TektosSandboxAdapter(event_bus=bus, memory=mem)
    result = asyncio.run(adapter.run(_echo_request(network="none")))
    assert result.killed_by == "limit"
    assert result.exit_code == 126
    event_types = [env.event_type for env in bus.published]
    assert "sandbox.isolation_unavailable" in event_types
