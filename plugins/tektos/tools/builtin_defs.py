"""plugins.tektos.tools.builtin_defs — the 7 donor built-in tool definitions (T5c).

Donor-faithful port of the tool registrations in
``tektos-ultima/src/tektos/tools/registry.py`` ``load_built_in()``
(~130 LOC of ``ToolDefinition`` literals). Per the porting layering rule the
definitions live in the Tektos plugin (coding-agent toolset = Tektos threat
model); the registry substrate they register into is the kernel's
``kernel/tool_registry.ToolRegistry`` (ADR-141 T5a).

The composition root (``kernel/app.py``) calls
``register_donor_builtins(registry, sandbox)`` at boot — the kernel never
imports this module directly (ADR-007).

The donor's ``load_built_in`` gate (``self._built_in_tools_loaded`` instance
flag) is replicated here per registry instance (module-level ``_loaded_in``):
a double call on the same registry is a no-op; a fresh registry loads again.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.tool_registry import ToolRegistry
    from plugins.tektos.tools.sandbox_provider import SandboxProvider

log = logging.getLogger("tektos.builtins")

# Per-registry gate (donor parity: donor's ``load_built_in`` checks an
# instance flag ``self._built_in_tools_loaded`` — a double boot call on the
# SAME registry is a no-op, while a fresh registry loads again).
_loaded_in: "ToolRegistry | None" = None


def register_donor_builtins(
    registry: "ToolRegistry", sandbox: "SandboxProvider"
) -> None:
    """Register the 7 donor built-in sandbox tools (donor definitions verbatim)."""
    global _loaded_in
    if _loaded_in is registry:
        return
    _loaded_in = registry

    from kernel.tool_registry import ToolDefinition

    # Bash tool
    registry.register(
        ToolDefinition(
            name="bash",
            description="Execute a shell command in the sandbox. Returns stdout + stderr.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                },
                "required": ["command"],
            },
            handler=lambda params: sandbox.execute("bash", params),
            timeout=30,
        )
    )

    # File read
    registry.register(
        ToolDefinition(
            name="file_read",
            description="Read the contents of a file at the given path.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to sandbox root",
                    },
                },
                "required": ["path"],
            },
            handler=lambda params: sandbox.execute("file_read", params),
        )
    )

    # File write
    registry.register(
        ToolDefinition(
            name="file_write",
            description="Write content to a file. Creates parent directories if needed.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                    "mode": {"type": "string", "enum": ["write", "append"], "default": "write"},
                },
                "required": ["path", "content"],
            },
            handler=lambda params: sandbox.execute("file_write", params),
        )
    )

    # File delete
    registry.register(
        ToolDefinition(
            name="file_delete",
            description="Delete a file or directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to delete"},
                },
                "required": ["path"],
            },
            handler=lambda params: sandbox.execute("file_delete", params),
        )
    )

    # Directory list
    registry.register(
        ToolDefinition(
            name="directory_list",
            description="List contents of a directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path", "default": "."},
                },
                "required": ["path"],
            },
            handler=lambda params: sandbox.execute("directory_list", params),
        )
    )

    # Directory create
    registry.register(
        ToolDefinition(
            name="directory_create",
            description="Create a directory (and parent directories).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                },
                "required": ["path"],
            },
            handler=lambda params: sandbox.execute("directory_create", params),
        )
    )

    # Search
    registry.register(
        ToolDefinition(
            name="search",
            description="Search file contents using a regex pattern.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (regex)"},
                    "path": {"type": "string", "description": "Path to search", "default": "."},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "default": 50},
                },
                "required": ["query"],
            },
            handler=lambda params: sandbox.execute("search", params),
        )
    )

    log.info("Loaded %d built-in tools", 7)


def reset_loaded_flag() -> None:
    """Test hook: allow re-registration (donor: per-registry gate)."""
    global _loaded_in
    _loaded_in = None


__all__ = ["register_donor_builtins", "reset_loaded_flag"]
