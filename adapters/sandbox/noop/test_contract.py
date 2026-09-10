"""Contract tests for ``NoOpSandboxAdapter`` (ADR-082, ADR-093).

Verifies:

1. Protocol conformance (``isinstance(_, SandboxPort)``).
2. Synthetic ``SandboxResult`` shape.
3. ``sandbox.started`` + ``sandbox.completed`` publish on every ``run()``.
4. Every ``SandboxResult`` writes ``MemoryPort`` with
   ``provenance="sandbox"``, ``confidence=1.0``.
5. ``kill()`` is idempotent and ``close()`` cascades kills.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adapters.sandbox.noop.adapter import NoOpSandboxAdapter
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


def _req(network: str = "none") -> SandboxRequest:
    return SandboxRequest(
        command="/bin/echo",
        argv=("/bin/echo", "hi"),
        cwd="/tmp",
        env={"PATH": "/usr/bin:/bin"},
        limits=SandboxLimits(
            max_wall_seconds=5,
            max_memory_mb=64,
            max_cpu_percent=100,
            network=network,  # type: ignore[arg-type]
        ),
    )


def test_noop_adapter_satisfies_sandbox_port() -> None:
    assert isinstance(NoOpSandboxAdapter(), SandboxPort)


def test_noop_run_returns_synthetic_result() -> None:
    adapter = NoOpSandboxAdapter()
    result = asyncio.run(adapter.run(_req()))
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert result.killed_by == "exit"
    assert result.wall_seconds == 0.0
    assert result.peak_memory_mb == 0
    assert result.run_id.startswith("noop-")


def test_noop_run_publishes_started_and_completed() -> None:
    bus = _RecordingEventBus()
    adapter = NoOpSandboxAdapter(event_bus=bus)
    asyncio.run(adapter.run(_req()))
    event_types = [env.event_type for env in bus.published]
    assert event_types == ["sandbox.started", "sandbox.completed"]
    # correlation_id lives inside payload per ADR-086 shape (EventEnvelope
    # has no correlation_id field at the top level).
    started, completed = bus.published
    assert started.payload["run_id"] == completed.payload["run_id"]
    assert started.payload["correlation_id"] == started.payload["run_id"]
    assert started.producer_plugin == "sandbox_noop_adapter"


def test_noop_run_writes_memory_with_sandbox_provenance() -> None:
    mem = _RecordingMemory()
    adapter = NoOpSandboxAdapter(memory=mem)
    asyncio.run(adapter.run(_req()))
    assert len(mem.writes) == 1
    write = mem.writes[0]
    assert write["provenance"] == "sandbox"
    assert write["confidence"] == 1.0
    assert write["attributes"]["noop"] is True
    assert write["object"] in ("exit", "limit", "user")


def test_noop_kill_is_idempotent() -> None:
    adapter = NoOpSandboxAdapter()

    async def _run() -> None:
        await adapter.kill("nonexistent-1")
        await adapter.kill("nonexistent-2")

    asyncio.run(_run())


def test_noop_close_flips_healthy_and_is_idempotent() -> None:
    adapter = NoOpSandboxAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False
    asyncio.run(adapter.close())  # idempotent


def test_noop_run_after_close_raises() -> None:
    adapter = NoOpSandboxAdapter()
    asyncio.run(adapter.close())
    with pytest.raises(RuntimeError):
        asyncio.run(adapter.run(_req()))


def test_noop_list_active_returns_tuple() -> None:
    adapter = NoOpSandboxAdapter()
    active = asyncio.run(adapter.list_active())
    assert isinstance(active, tuple)
    assert active == ()
