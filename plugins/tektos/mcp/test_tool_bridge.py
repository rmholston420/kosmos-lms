"""Contract tests for ``MCPToolBridge`` (Stage 4.8 · ADR-094 §D2).

Test surface (per ADR-094 Consequences §Testing):
- discover_and_register: round-trip of two fake MCP tools onto the
  registry, with tier resolution honoring TEKTOS_TOOL_TIER_MAP.
- unknown MCP tool → fail-closed HUMAN_REQUIRED.
- re-run is idempotent (already-registered tools land in ``skipped``,
  not raised).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest

from adapters.sandbox.noop.adapter import NoOpSandboxAdapter
from plugins.tektos.mcp.tool_bridge import (
    MCPToolBridge,
    MCPToolBridgeResult,
    network_policy_for_tier,
)
from plugins.tektos.tools.registry import TektosToolRegistry
from ports.approval import ApprovalRecord, ApprovalStatus, ChangeApprovalTier
from ports.event_envelope import EventEnvelope
from ports.mcp import MCPTool, MCPToolResult


class _StubGateway:
    async def propose(
        self,
        intention_id: str,
        delta: Mapping[str, Any],
        tier: ChangeApprovalTier,
        *,
        proposing_domain: str,
        diff_preview: Mapping[str, Any] | None = None,
    ) -> str:
        return "appr-1"


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


class _FakeMCPPort:
    """MCPPort stub returning a canned tool list."""

    def __init__(self, tools: tuple[MCPTool, ...]) -> None:
        self._tools = tools

    async def initialize(self, *, client_name: str, client_version: str) -> None:
        return None

    async def list_tools(self) -> tuple[MCPTool, ...]:
        return self._tools

    async def call_tool(
        self, *, name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        return MCPToolResult(
            tool_name=name,
            content=({"type": "text", "text": "fake"},),
            is_error=False,
        )

    async def close(self) -> None:
        return None


def _mk_registry() -> TektosToolRegistry:
    return TektosToolRegistry(
        approval_gateway=_StubGateway(),
        approval_resolver=_AutoResolver(),
        sandbox=NoOpSandboxAdapter(),
        event_bus=_NoopBus(),
    )


def test_bridge_registers_known_tool_at_locked_tier() -> None:
    tools = (
        MCPTool(
            name="browser_navigate",
            description="navigate",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        ),
    )
    registry = _mk_registry()
    bridge = MCPToolBridge(mcp=_FakeMCPPort(tools), registry=registry)
    report = asyncio.run(bridge.discover_and_register())

    assert isinstance(report, MCPToolBridgeResult)
    assert report.registered == ("browser_navigate",)
    assert report.skipped == ()
    assert report.tier_by_tool["browser_navigate"] is ChangeApprovalTier.AUTONOMOUS
    assert "browser_navigate" in {d.name for d in registry.list_tools()}


def test_bridge_registers_unknown_tool_at_default_tier() -> None:
    tools = (
        MCPTool(
            name="not_in_map",
            description="unknown",
            input_schema={"type": "object", "properties": {}},
        ),
    )
    registry = _mk_registry()
    bridge = MCPToolBridge(mcp=_FakeMCPPort(tools), registry=registry)
    report = asyncio.run(bridge.discover_and_register())

    assert report.tier_by_tool["not_in_map"] is ChangeApprovalTier.HUMAN_REQUIRED


def test_bridge_registers_multiple_tools_with_mixed_tiers() -> None:
    tools = (
        MCPTool(
            name="browser_navigate",
            description="a",
            input_schema={"type": "object"},
        ),
        MCPTool(
            name="shell_exec",
            description="b",
            input_schema={"type": "object"},
        ),
        MCPTool(
            name="not_in_map",
            description="c",
            input_schema={"type": "object"},
        ),
    )
    registry = _mk_registry()
    bridge = MCPToolBridge(mcp=_FakeMCPPort(tools), registry=registry)
    report = asyncio.run(bridge.discover_and_register())

    assert set(report.registered) == {"browser_navigate", "shell_exec", "not_in_map"}
    assert report.tier_by_tool["browser_navigate"] is ChangeApprovalTier.AUTONOMOUS
    assert report.tier_by_tool["shell_exec"] is ChangeApprovalTier.HUMAN_REQUIRED
    assert report.tier_by_tool["not_in_map"] is ChangeApprovalTier.HUMAN_REQUIRED


def test_bridge_re_register_is_idempotent() -> None:
    tools = (
        MCPTool(
            name="browser_navigate",
            description="a",
            input_schema={"type": "object"},
        ),
    )
    registry = _mk_registry()
    bridge = MCPToolBridge(mcp=_FakeMCPPort(tools), registry=registry)

    first = asyncio.run(bridge.discover_and_register())
    second = asyncio.run(bridge.discover_and_register())
    assert first.registered == ("browser_navigate",)
    assert second.registered == ()
    assert second.skipped == ("browser_navigate",)


def test_network_policy_defaults_by_tier() -> None:
    assert network_policy_for_tier(ChangeApprovalTier.AUTONOMOUS) == "loopback"
    assert network_policy_for_tier(ChangeApprovalTier.HUMAN_REVIEW) == "loopback"
    assert network_policy_for_tier(ChangeApprovalTier.HUMAN_REQUIRED) == "none"


def test_bridge_honors_custom_tier_map() -> None:
    tools = (
        MCPTool(
            name="custom_tool",
            description="x",
            input_schema={"type": "object"},
        ),
    )
    registry = _mk_registry()
    custom_map = {"custom_tool": ChangeApprovalTier.HUMAN_REVIEW}
    bridge = MCPToolBridge(
        mcp=_FakeMCPPort(tools),
        registry=registry,
        tier_map=custom_map,
    )
    report = asyncio.run(bridge.discover_and_register())
    assert report.tier_by_tool["custom_tool"] is ChangeApprovalTier.HUMAN_REVIEW


def test_bridge_honors_network_override() -> None:
    tools = (
        MCPTool(
            name="browser_navigate",
            description="a",
            input_schema={"type": "object"},
        ),
    )
    registry = _mk_registry()
    bridge = MCPToolBridge(
        mcp=_FakeMCPPort(tools),
        registry=registry,
        network_override="none",
    )
    asyncio.run(bridge.discover_and_register())
    descriptor = next(
        d for d in registry.list_tools() if d.name == "browser_navigate"
    )
    assert descriptor.network == "none"
