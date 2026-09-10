"""Contract tests for filesystem tool descriptors (Stage 4.8 · ADR-094).

Exercises the pre-approval detector on TektosToolRegistry.invoke end-to-end:

- happy-path: registering + invoking file_read/list/write/delete
- traversal-block: file_read with ``../etc/passwd`` publishes
  ``immune.verdict.block`` + writes MemoryPort event with
  ``provenance='immune_verdict'`` + publishes ``tektos.tool.denied``
  + raises ``PathTraversalDetected``
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from adapters.sandbox.noop.adapter import NoOpSandboxAdapter
from plugins.tektos.tools.detectors.path_traversal import (
    PathTraversalDetected,
    PathTraversalDetector,
)
from plugins.tektos.tools.filesystem import (
    FilesystemToolConfig,
    invoke_file_delete,
    invoke_file_list,
    invoke_file_read,
    invoke_file_write,
    register_filesystem_tools,
)
from plugins.tektos.tools.registry import TektosToolRegistry
from ports.approval import ApprovalRecord, ApprovalStatus, ChangeApprovalTier
from ports.event_envelope import EventEnvelope


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
        self.proposals.append(
            {
                "approval_id": approval_id,
                "tier": tier,
                "delta": dict(delta),
                "diff_preview": dict(diff_preview or {}),
            }
        )
        return approval_id


class _AutoApproveResolver:
    async def get_by_id(self, approval_id: str) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=approval_id,
            intention_id="turn-1",
            proposing_domain="tektos",
            tier=ChangeApprovalTier.HUMAN_REQUIRED,
            delta={},
            status=ApprovalStatus.APPROVED,
            proposed_at=datetime.now(timezone.utc),
            reason=None,
        )

    async def resolve(self, *_args: Any, **_kwargs: Any) -> ApprovalRecord:
        raise NotImplementedError

    async def list_pending(self, **_kwargs: Any) -> tuple[ApprovalRecord, ...]:
        return ()


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return f"evt-{len(self.published)}"


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

    async def query_temporal(self, *_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ()


def _mk_registry(
    tmp_root: Path,
    *,
    with_detector: bool = True,
) -> tuple[TektosToolRegistry, _StubGateway, _RecordingBus, _RecordingMemory]:
    gateway = _StubGateway()
    resolver = _AutoApproveResolver()
    bus = _RecordingBus()
    memory = _RecordingMemory()
    detectors: tuple[Any, ...] = ()
    if with_detector:
        detectors = (PathTraversalDetector(namespace_root=tmp_root),)
    registry = TektosToolRegistry(
        approval_gateway=gateway,
        approval_resolver=resolver,
        sandbox=NoOpSandboxAdapter(),
        event_bus=bus,
        pre_approval_detectors=detectors,
        memory=memory,
        detector_scan_source="tektos",
        approval_timeout_seconds=2,
    )
    return registry, gateway, bus, memory


def test_register_filesystem_tools_registers_all_four(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_filesystem_tools(
        registry, config=FilesystemToolConfig(namespace_root=tmp_path)
    )
    registered_names = {d.name for d in registry.list_tools()}
    assert registered_names >= {
        "file_read",
        "file_list",
        "file_write",
        "file_delete",
    }


def test_file_read_happy_path(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello world")
    registry, gateway, bus, _ = _mk_registry(tmp_path)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    result = asyncio.run(
        invoke_file_read(
            registry,
            path="notes.txt",
            intention_id="turn-1",
            config=config,
        )
    )
    assert result.exit_code == 0  # NoOp always exits 0
    assert len(gateway.proposals) == 1
    assert gateway.proposals[0]["tier"] is ChangeApprovalTier.AUTONOMOUS
    event_types = [env.event_type for env in bus.published]
    assert "tektos.tool.invoked" in event_types
    assert "tektos.tool.completed" in event_types


def test_file_write_requires_human_review(tmp_path: Path) -> None:
    registry, gateway, _, _ = _mk_registry(tmp_path)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    asyncio.run(
        invoke_file_write(
            registry,
            path="new.txt",
            content="body",
            intention_id="turn-2",
            config=config,
        )
    )
    assert gateway.proposals[0]["tier"] is ChangeApprovalTier.HUMAN_REVIEW


def test_file_delete_requires_human_required(tmp_path: Path) -> None:
    registry, gateway, _, _ = _mk_registry(tmp_path)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    asyncio.run(
        invoke_file_delete(
            registry,
            path="doomed.txt",
            intention_id="turn-3",
            config=config,
        )
    )
    assert gateway.proposals[0]["tier"] is ChangeApprovalTier.HUMAN_REQUIRED


def test_file_list_happy_path(tmp_path: Path) -> None:
    registry, gateway, _, _ = _mk_registry(tmp_path)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    asyncio.run(
        invoke_file_list(
            registry,
            path=".",
            intention_id="turn-4",
            config=config,
        )
    )
    assert gateway.proposals[0]["tier"] is ChangeApprovalTier.AUTONOMOUS


def test_dotdot_path_is_blocked_end_to_end(tmp_path: Path) -> None:
    registry, gateway, bus, memory = _mk_registry(tmp_path)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    with pytest.raises(PathTraversalDetected) as excinfo:
        asyncio.run(
            invoke_file_read(
                registry,
                path="../etc/passwd",
                intention_id="turn-block",
                config=config,
            )
        )
    assert excinfo.value.detector_reason == "dotdot_component"
    assert excinfo.value.offending_path == "../etc/passwd"

    # ADR-079 rule 1: immune.verdict.block published pre-approval.
    event_types = [env.event_type for env in bus.published]
    assert "immune.verdict.block" in event_types
    assert "tektos.tool.denied" in event_types
    # Approval gate never reached.
    assert gateway.proposals == []

    # ADR-079 rule 2: MemoryPort write with provenance='immune_verdict'.
    immune_writes = [
        e for e in memory.events if e["provenance"] == "immune_verdict"
    ]
    assert len(immune_writes) == 1
    assert immune_writes[0]["confidence"] == 1.0
    assert immune_writes[0]["predicate"] == "immune.verdict.block"
    assert immune_writes[0]["object"] == "path_traversal"


def test_absolute_path_escape_is_blocked_end_to_end(tmp_path: Path) -> None:
    registry, gateway, bus, memory = _mk_registry(tmp_path)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    with pytest.raises(PathTraversalDetected) as excinfo:
        asyncio.run(
            invoke_file_read(
                registry,
                path="/etc/passwd",
                intention_id="turn-abs",
                config=config,
            )
        )
    assert excinfo.value.detector_reason == "absolute_escape"
    assert gateway.proposals == []
    assert any(env.event_type == "immune.verdict.block" for env in bus.published)


def test_registry_without_detector_registers_but_does_not_block(
    tmp_path: Path,
) -> None:
    # Regression guard: a registry without pre_approval_detectors
    # (Stage-4.7 construction) must NOT crash when filesystem tools are
    # registered, and it must NOT block traversal (this documents that
    # the detector wiring is the enforcement seam, not the descriptors).
    registry, gateway, _, _ = _mk_registry(tmp_path, with_detector=False)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)

    result = asyncio.run(
        invoke_file_read(
            registry,
            path="../etc/passwd",
            intention_id="turn-unguarded",
            config=config,
        )
    )
    # NoOpSandbox never actually reads /etc/passwd; assertion is that
    # no PathTraversalDetected was raised and the approval gate ran.
    assert result.exit_code == 0
    assert gateway.proposals[0]["tier"] is ChangeApprovalTier.AUTONOMOUS
