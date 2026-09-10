"""Contract tests for ``TektosToolRegistry`` (Stage 4.7 DoD, ADR-093 §4).

DoD verb: "an approval-required tool call blocks until ApprovalPort
decision returns; tektos.tool.* envelopes carry provenance=tektos_tool
and confidence=1.0."
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest

from adapters.sandbox.noop.adapter import NoOpSandboxAdapter
from plugins.tektos.tools import (
    TektosToolRegistry,
    ToolApprovalDenied,
    ToolDescriptor,
    ToolNotFound,
)
from ports.approval import (
    ApprovalRecord,
    ApprovalStatus,
    ChangeApprovalTier,
)
from ports.event_envelope import EventEnvelope
from ports.sandbox import SandboxResult


class _StubApprovalGateway:
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
                "intention_id": intention_id,
                "delta": dict(delta),
                "tier": tier,
                "proposing_domain": proposing_domain,
                "diff_preview": dict(diff_preview or {}),
            }
        )
        return approval_id


class _ProgrammableResolver:
    """Resolver that returns a scripted sequence per approval_id."""

    def __init__(self) -> None:
        self._scripts: dict[str, list[ApprovalStatus]] = {}

    def program(self, approval_id: str, statuses: list[ApprovalStatus]) -> None:
        self._scripts[approval_id] = list(statuses)

    async def get_by_id(self, approval_id: str) -> ApprovalRecord:
        script = self._scripts.get(approval_id) or [ApprovalStatus.APPROVED]
        status = script.pop(0) if len(script) > 1 else script[0]
        return ApprovalRecord(
            approval_id=approval_id,
            intention_id="intent",
            proposing_domain="tektos",
            tier=ChangeApprovalTier.HUMAN_REQUIRED,
            delta={},
            status=status,
            proposed_at=datetime.now(timezone.utc),
            reason=None if status is not ApprovalStatus.REJECTED else "denied by test",
        )

    async def resolve(self, *_args: Any, **_kwargs: Any) -> ApprovalRecord:  # noqa: D401
        raise NotImplementedError

    async def list_pending(self, **_kwargs: Any) -> tuple[ApprovalRecord, ...]:
        return ()


class _RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return f"evt-{len(self.published)}"


def _autonomous_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        name="bash_autonomous",
        description="autonomous echo",
        parameters={
            "type": "object",
            "properties": {"argv": {"type": "array"}},
            "required": ["argv"],
        },
        approval_tier=ChangeApprovalTier.AUTONOMOUS,
        network="full",
    )


def _human_required_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        name="bash_human_required",
        description="human-required echo",
        parameters={
            "type": "object",
            "properties": {"argv": {"type": "array"}},
            "required": ["argv"],
        },
        approval_tier=ChangeApprovalTier.HUMAN_REQUIRED,
        network="full",
    )


def _mk_registry(
    gateway: _StubApprovalGateway,
    resolver: _ProgrammableResolver,
    bus: _RecordingEventBus | None = None,
    *,
    approval_timeout_seconds: int = 2,
) -> TektosToolRegistry:
    return TektosToolRegistry(
        approval_gateway=gateway,
        approval_resolver=resolver,
        sandbox=NoOpSandboxAdapter(),
        event_bus=bus,
        approval_timeout_seconds=approval_timeout_seconds,
    )


def test_autonomous_tier_runs_synchronously() -> None:
    gateway = _StubApprovalGateway()
    resolver = _ProgrammableResolver()
    bus = _RecordingEventBus()
    registry = _mk_registry(gateway, resolver, bus)
    registry.register(_autonomous_descriptor())

    result = asyncio.run(
        registry.invoke(
            "bash_autonomous",
            {"argv": ["/bin/echo", "hi"]},
            intention_id="turn-1",
        )
    )
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    # One propose call, tier AUTONOMOUS.
    assert len(gateway.proposals) == 1
    assert gateway.proposals[0]["tier"] is ChangeApprovalTier.AUTONOMOUS
    event_types = [env.event_type for env in bus.published]
    assert event_types[0] == "tektos.tool.invoked"
    assert "tektos.tool.completed" in event_types
    # AUTONOMOUS path skips approved/denied envelopes.
    assert "tektos.tool.approved" not in event_types
    assert "tektos.tool.denied" not in event_types


def test_completed_envelope_carries_provenance_and_confidence() -> None:
    gateway = _StubApprovalGateway()
    resolver = _ProgrammableResolver()
    bus = _RecordingEventBus()
    registry = _mk_registry(gateway, resolver, bus)
    registry.register(_autonomous_descriptor())

    asyncio.run(
        registry.invoke(
            "bash_autonomous",
            {"argv": ["/bin/echo", "hi"]},
            intention_id="turn-1",
        )
    )
    completed = [env for env in bus.published if env.event_type == "tektos.tool.completed"]
    assert completed, "expected tektos.tool.completed envelope"
    payload = completed[-1].payload
    assert payload["provenance"] == "tektos_tool"
    assert payload["confidence"] == 1.0


def test_human_required_blocks_until_resolver_approves() -> None:
    gateway = _StubApprovalGateway()
    resolver = _ProgrammableResolver()
    bus = _RecordingEventBus()
    registry = _mk_registry(gateway, resolver, bus)
    registry.register(_human_required_descriptor())

    # Program resolver: PENDING twice, then APPROVED.
    resolver.program(
        "appr-1",
        [ApprovalStatus.PENDING, ApprovalStatus.PENDING, ApprovalStatus.APPROVED],
    )
    result = asyncio.run(
        registry.invoke(
            "bash_human_required",
            {"argv": ["/bin/echo", "gated"]},
            intention_id="turn-2",
        )
    )
    assert result.exit_code == 0
    event_types = [env.event_type for env in bus.published]
    assert "tektos.tool.invoked" in event_types
    assert "tektos.tool.approved" in event_types
    assert "tektos.tool.completed" in event_types
    # Approved envelope references the approval id.
    approved = [env for env in bus.published if env.event_type == "tektos.tool.approved"][0]
    assert approved.payload["approval_id"] == "appr-1"


def test_human_required_denied_raises_and_publishes_denied_envelope() -> None:
    gateway = _StubApprovalGateway()
    resolver = _ProgrammableResolver()
    bus = _RecordingEventBus()
    registry = _mk_registry(gateway, resolver, bus)
    registry.register(_human_required_descriptor())

    resolver.program("appr-1", [ApprovalStatus.REJECTED])
    with pytest.raises(ToolApprovalDenied) as excinfo:
        asyncio.run(
            registry.invoke(
                "bash_human_required",
                {"argv": ["/bin/echo", "nope"]},
                intention_id="turn-3",
            )
        )
    assert excinfo.value.status is ApprovalStatus.REJECTED
    event_types = [env.event_type for env in bus.published]
    assert "tektos.tool.denied" in event_types
    assert "tektos.tool.completed" not in event_types


def test_human_required_timeout_raises_review_missed() -> None:
    gateway = _StubApprovalGateway()
    resolver = _ProgrammableResolver()
    bus = _RecordingEventBus()
    registry = _mk_registry(
        gateway, resolver, bus, approval_timeout_seconds=0
    )  # instant timeout
    registry.register(_human_required_descriptor())

    # Resolver always returns PENDING.
    resolver.program("appr-1", [ApprovalStatus.PENDING])
    with pytest.raises(ToolApprovalDenied) as excinfo:
        asyncio.run(
            registry.invoke(
                "bash_human_required",
                {"argv": ["/bin/echo", "slow"]},
                intention_id="turn-4",
            )
        )
    assert excinfo.value.status is ApprovalStatus.REVIEW_MISSED


def test_unknown_tool_raises_tool_not_found() -> None:
    gateway = _StubApprovalGateway()
    resolver = _ProgrammableResolver()
    registry = _mk_registry(gateway, resolver)
    with pytest.raises(ToolNotFound):
        asyncio.run(
            registry.invoke(
                "no_such_tool",
                {"argv": ["/bin/echo", "hi"]},
                intention_id="turn-5",
            )
        )


def test_invalid_arguments_rejected_before_approval() -> None:
    gateway = _StubApprovalGateway()
    resolver = _ProgrammableResolver()
    registry = _mk_registry(gateway, resolver)
    registry.register(_autonomous_descriptor())
    with pytest.raises(ValueError):
        asyncio.run(
            registry.invoke(
                "bash_autonomous",
                {},  # missing required argv
                intention_id="turn-6",
            )
        )
    assert gateway.proposals == []  # approval NOT called on invalid input
