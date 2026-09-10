"""MCPToolBridge — discover MCP tools + register onto TektosToolRegistry.

Stage 4.8 · ADR-094 §D2.

Translates ``MCPPort.list_tools()`` results into ``ToolDescriptor``
registrations on a ``TektosToolRegistry``. Preserves the Stage-3.2-locked
``TEKTOS_TOOL_TIER_MAP`` (ADR-037) as the seed default: known tools
inherit their locked tier; unknown tools fail-closed to
``DEFAULT_TIER=HUMAN_REQUIRED``.

The bridge is a plugin-scoped composition — it sits above both the
Stage-3.2 ``MCPPort`` and the Stage-4.7 ``TektosToolRegistry`` and does
not add a new port. Every registered MCP tool executes **through** the
registry (which routes through ``SandboxPort.run``), so MCP tool calls
inherit the full Stage 4.7 isolation boundary rather than executing
directly against the MCP server.

Wire-through model:
  MCP server declares tool T with JSON schema S.
  Bridge translates → ToolDescriptor(name=T.name, parameters=S,
                                      approval_tier=map.get(T.name, DEFAULT_TIER),
                                      network=<policy from tier>)
  Bridge stores handler: mcp.call_tool(name, arguments).
  On registry.invoke(T.name, arguments):
    → JSON-schema validate (registry does this using S)
    → Pre-approval detectors run (path-traversal for filesystem tools)
    → ApprovalGatewayPort.propose(tier)
    → SandboxPort.run  ← for now this executes a placeholder ``true``
      command; the actual mcp.call_tool bridge happens in Stage 4.8+1
      when SandboxPort adds a ``pass_through`` mode for in-process
      handlers. Registered MCP tools thus arrive at approval but do
      NOT yet execute the underlying MCP call — that is the Stage
      4.8+1 seam. This split keeps ADR-093 §Decision "all tool
      execution flows through SandboxPort.run" invariant during 4.8.

Tests exercise the discover + register + approval-gate paths, plus
the tier-map fail-closed behavior for unknown MCP tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Mapping

from ports.approval import ChangeApprovalTier
from ports.mcp import MCPPort, MCPTool
from ports.sandbox import SandboxNetworkPolicy
from plugins.tektos.mcp.tool_policy import (
    DEFAULT_TIER,
    TEKTOS_TOOL_TIER_MAP,
)
from plugins.tektos.tools.registry import (
    TektosToolRegistry,
    ToolDescriptor,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MCPToolBridge",
    "MCPToolBridgeResult",
    "network_policy_for_tier",
]


# ── Tier → network policy default table ────────────────────────────────
#
# Not a hard lock; a caller-supplied ``network_policy`` override wins.
# Rationale: HUMAN_REQUIRED tools are the most dangerous, so their
# sandbox defaults to ``network="none"``. AUTONOMOUS tools (browser
# tools in the locked map) need loopback for local MCP servers.
_DEFAULT_NETWORK_BY_TIER: Final[Mapping[ChangeApprovalTier, SandboxNetworkPolicy]] = {
    ChangeApprovalTier.AUTONOMOUS: "loopback",
    ChangeApprovalTier.HUMAN_REVIEW: "loopback",
    ChangeApprovalTier.HUMAN_REQUIRED: "none",
}


def network_policy_for_tier(
    tier: ChangeApprovalTier,
) -> SandboxNetworkPolicy:
    """Return the default sandbox network policy for a tier.

    Callers can override via ``MCPToolBridge(network_override=...)``.
    """
    return _DEFAULT_NETWORK_BY_TIER.get(tier, "none")


@dataclass(frozen=True, slots=True)
class MCPToolBridgeResult:
    """Report from ``MCPToolBridge.discover_and_register``.

    Attributes:
        registered: Tool names successfully registered on the registry.
        skipped: Tool names skipped (already registered on the target
            registry) — logged but not raised.
        tier_by_tool: Resolved tier for every registered tool (for
            audit).
    """

    registered: tuple[str, ...]
    skipped: tuple[str, ...]
    tier_by_tool: Mapping[str, ChangeApprovalTier]


class MCPToolBridge:
    """Discover MCP tools + register onto a TektosToolRegistry.

    Composition-only — carries no port surface of its own. The tier map
    is injected at construction so tests can substitute a smaller map
    without patching module globals.

    Args:
        mcp: Any ``MCPPort`` adapter (Stage 3.2 in_process / stdio).
        registry: The Stage 4.7 registry to receive registrations.
        tier_map: Tool-name → tier mapping (default: locked Stage-3.2
            ``TEKTOS_TOOL_TIER_MAP``).
        default_tier: Fallback for tools absent from ``tier_map``
            (default: ``DEFAULT_TIER = HUMAN_REQUIRED`` per ADR-037).
        network_override: Optional single ``SandboxNetworkPolicy`` that
            overrides ``network_policy_for_tier`` for every registered
            tool (useful for tests that want ``network="none"``
            everywhere).
        default_timeout_seconds: Sandbox wall-time budget for every
            registered tool (default 60 s).
    """

    def __init__(
        self,
        *,
        mcp: MCPPort,
        registry: TektosToolRegistry,
        tier_map: Mapping[str, ChangeApprovalTier] = TEKTOS_TOOL_TIER_MAP,
        default_tier: ChangeApprovalTier = DEFAULT_TIER,
        network_override: SandboxNetworkPolicy | None = None,
        default_timeout_seconds: int = 60,
    ) -> None:
        self._mcp = mcp
        self._registry = registry
        self._tier_map: Mapping[str, ChangeApprovalTier] = dict(tier_map)
        self._default_tier = default_tier
        self._network_override = network_override
        self._default_timeout_seconds = default_timeout_seconds

    async def discover_and_register(self) -> MCPToolBridgeResult:
        """Call ``MCPPort.list_tools`` and register every returned tool.

        Idempotent on the ``skipped`` axis: tools already registered on
        the target registry are skipped and reported in ``skipped``
        without raising, so a bridge that re-runs after a partial
        registration converges.
        """
        tools: tuple[MCPTool, ...] = await self._mcp.list_tools()
        registered: list[str] = []
        skipped: list[str] = []
        tier_by_tool: dict[str, ChangeApprovalTier] = {}

        for tool in tools:
            tier = self._tier_map.get(tool.name, self._default_tier)
            descriptor = self._descriptor_for(tool, tier)
            try:
                self._registry.register(descriptor)
            except ValueError:
                # Already registered — treat as idempotent no-op.
                skipped.append(tool.name)
                logger.info(
                    "mcp_tool_bridge: skipped already-registered tool %r",
                    tool.name,
                )
                continue
            registered.append(tool.name)
            tier_by_tool[tool.name] = tier

        return MCPToolBridgeResult(
            registered=tuple(registered),
            skipped=tuple(skipped),
            tier_by_tool=dict(tier_by_tool),
        )

    def _descriptor_for(
        self, tool: MCPTool, tier: ChangeApprovalTier
    ) -> ToolDescriptor:
        network: SandboxNetworkPolicy = (
            self._network_override
            if self._network_override is not None
            else network_policy_for_tier(tier)
        )
        # If the MCP-declared schema is empty, degrade to a permissive
        # object schema so registry.invoke's validate_arguments does not
        # reject callers. Real MCP servers ship non-empty schemas.
        parameters: dict[str, Any] = dict(tool.input_schema) or {
            "type": "object",
            "properties": {
                "argv": {"type": "array", "items": {"type": "string"}}
            },
        }
        return ToolDescriptor(
            name=tool.name,
            description=tool.description,
            parameters=parameters,
            approval_tier=tier,
            network=network,
            timeout_seconds=self._default_timeout_seconds,
            scan_kind=None,  # generic — path-traversal detector self-filters
        )
