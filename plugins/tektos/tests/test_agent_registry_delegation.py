"""Contract tests for ``TektosAgent.call_tool`` delegation (Stage 4.8 · ADR-094 §D1).

Verifies:
- When ``tool_registry`` is None, the legacy Stage-3.2 inline flow runs
  (regression guard — Stage 3.2 DoD tests already cover the positive
  path; this test only asserts the delegation branch is NOT taken).
- When ``tool_registry`` is set, ``call_tool`` delegates to
  ``TektosToolRegistry.invoke`` and returns a well-shaped ``TektosStep``.
- Delegation preserves the caller-supplied ``turn_id`` when passed.
- Registry-side denial surfaces as ``TektosToolCallPending`` (the same
  class Stage-3.2 callers already catch).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from adapters.sandbox.noop.adapter import NoOpSandboxAdapter
from plugins.tektos.agent import TektosAgent
from plugins.tektos.errors import TektosToolCallPending
from plugins.tektos.models import TektosStep
from plugins.tektos.tools.detectors.path_traversal import PathTraversalDetector
from plugins.tektos.tools.filesystem import (
    FilesystemToolConfig,
    register_filesystem_tools,
)
from plugins.tektos.tools.registry import (
    TektosToolRegistry,
    ToolDescriptor,
)
from ports.approval import (
    ApprovalRecord,
    ApprovalStatus,
    ChangeApprovalTier,
)
from ports.event_envelope import EventEnvelope


class _StubLLM:
    async def generate_text(self, *_a: Any, **_k: Any) -> str:
        return "unused"


class _RecordingMemory:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        source_citation: Any = None,
        pii_tier: str = "Public",
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        self.events.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "provenance": provenance,
                "confidence": confidence,
                "attributes": dict(attributes or {}),
            }
        )

        class _Id:
            id = f"mem-{len(self.events)}"

        return _Id()

    async def query_temporal(self, *_a: Any, **_k: Any) -> tuple[Any, ...]:
        return ()


class _StubGateway:
    def __init__(self) -> None:
        self.proposals: list[dict[str, Any]] = []

    async def propose(
        self,
        intention_id: str,
        delta: Mapping[str, Any],
        tier: ChangeApprovalTier,
        *,
        proposing_domain: str,
        diff_preview: Mapping[str, Any] | None = None,
    ) -> str:
        approval_id = f"appr-{len(self.proposals) + 1}"
        self.proposals.append({"approval_id": approval_id, "tier": tier})
        return approval_id


class _AutoResolver:
    async def get_by_id(self, approval_id: str) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=approval_id,
            intention_id="i",
            proposing_domain="tektos",
            tier=ChangeApprovalTier.AUTONOMOUS,
            delta={},
            status=ApprovalStatus.APPROVED,
            proposed_at=datetime.now(timezone.utc),
            reason=None,
        )

    async def resolve(self, *_a: Any, **_k: Any) -> ApprovalRecord:
        raise NotImplementedError

    async def list_pending(self, **_k: Any) -> tuple[ApprovalRecord, ...]:
        return ()


class _NoopBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return f"evt-{len(self.published)}"


def _mk_registry(
    tmp_root: Path,
    memory: _RecordingMemory,
    *,
    with_detector: bool = True,
) -> TektosToolRegistry:
    detectors: tuple[Any, ...] = ()
    if with_detector:
        detectors = (PathTraversalDetector(namespace_root=tmp_root),)
    return TektosToolRegistry(
        approval_gateway=_StubGateway(),
        approval_resolver=_AutoResolver(),
        sandbox=NoOpSandboxAdapter(),
        event_bus=_NoopBus(),
        pre_approval_detectors=detectors,
        memory=memory,
        detector_scan_source="tektos",
        approval_timeout_seconds=2,
    )


def test_call_tool_delegates_when_registry_present(tmp_path: Path) -> None:
    memory = _RecordingMemory()
    registry = _mk_registry(tmp_path, memory)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    agent = TektosAgent(
        llm=_StubLLM(),
        memory=memory,
        tool_registry=registry,
    )
    step = asyncio.run(
        agent.call_tool(
            name="file_read",
            arguments={
                "path": "hello.txt",
                "argv": ["cat", str(tmp_path / "hello.txt")],
            },
            turn_id="turn-delegate-1",
        )
    )
    assert isinstance(step, TektosStep)
    assert step.turn_id == "turn-delegate-1"
    assert step.tool_name == "file_read"
    # Memory event written with delegated_to marker.
    delegated_writes = [
        e for e in memory.events if e["attributes"].get("delegated_to")
    ]
    assert len(delegated_writes) == 1
    assert delegated_writes[0]["predicate"] == "tektos.tool.completed"


def test_call_tool_delegation_raises_pending_on_registry_denial(
    tmp_path: Path,
) -> None:
    memory = _RecordingMemory()
    registry = _mk_registry(tmp_path, memory, with_detector=True)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    agent = TektosAgent(
        llm=_StubLLM(),
        memory=memory,
        tool_registry=registry,
    )
    with pytest.raises(TektosToolCallPending) as excinfo:
        asyncio.run(
            agent.call_tool(
                name="file_read",
                arguments={"path": "../etc/passwd"},
                turn_id="turn-block",
            )
        )
    assert excinfo.value.tool_name == "file_read"


def test_call_tool_without_registry_falls_back_to_legacy_path() -> None:
    # Regression guard: no tool_registry passed → legacy path runs. Legacy
    # path raises RuntimeError because mcp/apex are also not passed; the
    # important behaviour is that the delegation branch is NOT taken (no
    # AttributeError, no coroutine leaked), and the error surface matches
    # Stage-3.2 documented behaviour.
    memory = _RecordingMemory()
    agent = TektosAgent(llm=_StubLLM(), memory=memory)
    with pytest.raises(RuntimeError, match="MCPPort"):
        asyncio.run(agent.call_tool(name="anything", arguments={}))


def test_call_tool_delegation_autogenerates_turn_id_when_omitted(
    tmp_path: Path,
) -> None:
    memory = _RecordingMemory()
    registry = _mk_registry(tmp_path, memory)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    agent = TektosAgent(
        llm=_StubLLM(),
        memory=memory,
        tool_registry=registry,
    )
    step = asyncio.run(
        agent.call_tool(
            name="file_read",
            arguments={
                "path": "notes.txt",
                "argv": ["cat", str(tmp_path / "notes.txt")],
            },
        )
    )
    assert step.turn_id.startswith("tektos-turn-")
