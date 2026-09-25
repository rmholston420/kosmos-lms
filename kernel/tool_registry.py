"""kernel.tool_registry — the dynamic tool registry (ADR-141 T5a).

Donor-faithful port of ``tektos-ultima/src/tektos/tools/registry.py``
(``ToolDefinition`` + ``ToolRegistry``, ~170 LOC). The donor's registry is a
pure generic substrate — a name→definition map with schema validation,
execution, call stats, and event-bus emissions. No Tektos-specific policy
lives in it (the built-in tool set + their sandbox handlers are the
coding-agent-specific half and live in ``plugins/tektos/tools/`` per the
porting layering rule — substrate here, policy in the plugin).

Differences from the donor (documented, wire-preserving):

- **Event-bus API.** The donor published
  ``event_bus.publish(event_type, producer, payload)`` on its in-memory bus.
  The kernel bus is ``EventBusPort`` (``publish(envelope: EventEnvelope)``),
  so each emission is wrapped in an ``EventEnvelope`` with the SAME
  ``event_type`` (``tool.registered`` / ``tool.unregistered`` /
  ``tool.executed``), producer (``"tool-registry"``) and payload dict as the
  donor — subscribers see the donor wire. Emissions are best-effort: a
  missing/dead bus must never break a tool call (the kernel bus may be
  offline while the registry is up).
- **No MCP client.** The donor's ``MCPClient`` (dynamic external tool
  discovery) is a separate subsystem (the MCP family already has its own
  kernel surface) and is not part of T5's 5 management routes.

Wire shapes preserved verbatim:

- ``ToolDefinition.to_dict()`` → ``{name, description, parameters, enabled,
  timeout, call_count, last_call}``
- ``ToolRegistry.list_tools(enabled_only)`` → ``list[to_dict()]``
- ``ToolRegistry.to_tools_schema()`` → OpenAI-compatible function schema list
- ``ToolRegistry.execute(name, params)`` → ``str`` result (``"Unknown tool:
  …"`` / ``"Tool '…' is disabled"`` / ``"Error: …"`` on failure)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger("kosmos.tools")


# ─── Tool Definition ────────────────────────────────────────────────────────


class ToolDefinition:
    """A single tool definition with schema and handler.

    Donor ``ToolDefinition`` — plain class (not a dataclass) so the routes
    can flip ``enabled`` in place (donor enable/disable semantics).
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[[dict[str, Any]], str],
        enabled: bool = True,
        timeout: int = 30,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema dict
        self.handler = handler
        self.enabled = enabled
        self.timeout = timeout
        self.call_count: int = 0
        self.last_call: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API/JSON serialization (donor wire verbatim)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "timeout": self.timeout,
            "call_count": self.call_count,
            "last_call": self.last_call,
        }


# ─── Tool Registry ──────────────────────────────────────────────────────────


class ToolRegistry:
    """Registry for all available tools (donor ``ToolRegistry`` port).

    Manages tool definitions, validation, execution, and event emissions.
    ``event_bus`` is the kernel ``EventBusPort`` (``publish(envelope)``) or
    ``None`` when the bus is not booted — emissions are best-effort.
    """

    def __init__(self, event_bus: Any | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._event_bus = event_bus

    # ── event bus ──────────────────────────────────────────────────────────

    def set_event_bus(self, event_bus: Any | None) -> None:
        """Late-bind the kernel event bus (wired at boot, ADR-141 T5)."""
        self._event_bus = event_bus

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Best-effort emission of a donor ``tool.*`` event.

        Same event_type/producer/payload the donor published; wrapped in the
        kernel ``EventEnvelope`` (ADR-023). Never raises — a dead bus must
        not break a tool call.

        The kernel ``EventBusPort`` is async (ADR-023), but the registry's
        call sites are sync (the donor registry was sync too). Bridge:
        fire-and-forget ``create_task`` on the running loop when one exists
        (all kernel call sites run under FastAPI's loop); when there is no
        loop (bare unit tests, CLI) the event is dropped with a debug log —
        the donor's unwired-bus behavior.
        """
        if self._event_bus is None:
            return
        try:
            import asyncio

            from ports.event_envelope import EventEnvelope

            coro = self._event_bus.publish(
                EventEnvelope(
                    event_type=event_type,
                    producer_plugin="tool-registry",
                    payload=payload,
                )
            )
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                coro.close()
                log.debug(
                    "tool-registry: dropped %s event (no running loop)", event_type
                )
                return

            def _done(task):  # pragma: no cover — defensive
                if not task.cancelled() and task.exception() is not None:
                    log.debug("tool-registry: %s publish failed", event_type)

            loop.create_task(coro).add_done_callback(_done)
        except Exception as exc:  # noqa: BLE001 — best-effort, by design
            log.debug("tool-registry event emission failed: %s", exc)

    # ── lifecycle ──────────────────────────────────────────────────────────

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool in the registry (donor semantics)."""
        self._tools[tool.name] = tool
        log.info("Registered tool: %s", tool.name)
        self._emit("tool.registered", {"tool_name": tool.name, "enabled": tool.enabled})

    def unregister(self, tool_name: str) -> bool:
        """Unregister a tool. Returns True if found and removed."""
        if tool_name in self._tools:
            del self._tools[tool_name]
            log.info("Unregistered tool: %s", tool_name)
            self._emit("tool.unregistered", {"tool_name": tool_name})
            return True
        return False

    def get(self, tool_name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(tool_name)

    def list_tools(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        """List all registered tools (donor ``list_tools`` wire)."""
        return [
            t.to_dict()
            for t in self._tools.values()
            if t.enabled or not enabled_only
        ]

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool by name with given input (donor ``execute``)."""
        tool = self._tools.get(tool_name)
        if not tool:
            return f"Unknown tool: {tool_name}"
        if not tool.enabled:
            return f"Tool '{tool_name}' is disabled"

        # Validate input against schema (best-effort, donor parity).
        if not self._validate_input(tool, tool_input):
            log.warning("Input validation failed for tool %s", tool_name)

        # Execute with timeout.
        start = time.time()
        try:
            result = tool.handler(tool_input)
            tool.call_count += 1
            tool.last_call = time.time()
            elapsed = time.time() - start
            self._emit(
                "tool.executed",
                {
                    "tool_name": tool_name,
                    "duration": round(elapsed, 3),
                    "success": True,
                },
            )
            return result
        except Exception as exc:  # noqa: BLE001 — donor catches all
            elapsed = time.time() - start
            log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            self._emit(
                "tool.executed",
                {
                    "tool_name": tool_name,
                    "duration": round(elapsed, 3),
                    "success": False,
                    "error": str(exc),
                },
            )
            return f"Error: {exc}"

    def _validate_input(self, tool: ToolDefinition, params: dict[str, Any]) -> bool:
        """Validate input against JSON Schema (best-effort, donor parity)."""
        required = tool.parameters.get("required", [])
        return all(field in params for field in required)

    def to_tools_schema(self) -> list[dict[str, Any]]:
        """Export all enabled tools as OpenAI-compatible tools schema."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
            if t.enabled
        ]
