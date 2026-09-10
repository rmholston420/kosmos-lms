"""Filesystem tools for TektosToolRegistry (Stage 4.8 · ADR-094 §D3).

Registers four filesystem tool descriptors on a given
``TektosToolRegistry`` and exposes thin coroutine helpers that build the
argv for each and call ``registry.invoke``:

- ``file_read``  — AUTONOMOUS · ``["cat", <resolved-path>]``
- ``file_list``  — AUTONOMOUS · ``["ls", "-la", <resolved-path>]``
- ``file_write`` — HUMAN_REVIEW · ``["tee", <resolved-path>]`` with ``stdin=<content>``
- ``file_delete`` — HUMAN_REQUIRED · ``["rm", "-rf", <resolved-path>]``

Every descriptor sets ``scan_kind="tektos.tool.filesystem"``, so
``PathTraversalDetector`` (registered as a pre-approval detector on the
registry) runs and rejects escapes before the approval gate.

Tier assignments per ADR-094 §Rationale:
- reads/lists are AUTONOMOUS, budgeted by ADR-088 read-only budget.
- writes are HUMAN_REVIEW (reduced blast radius inside ``NamespaceRoot``).
- deletes are HUMAN_REQUIRED (irreversible).

All handlers execute via ``SandboxPort.run`` — argv-only, no shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from ports.approval import ChangeApprovalTier
from ports.sandbox import SandboxResult
from plugins.tektos.tools.registry import (
    TektosToolRegistry,
    ToolDescriptor,
)

__all__ = [
    "FILESYSTEM_SCAN_KIND",
    "FilesystemToolConfig",
    "register_filesystem_tools",
    "invoke_file_read",
    "invoke_file_list",
    "invoke_file_write",
    "invoke_file_delete",
]


FILESYSTEM_SCAN_KIND: Final[str] = "tektos.tool.filesystem"
"""ImmuneScanRequest.kind value the PathTraversalDetector filters on."""


class FilesystemToolConfig:
    """Deployment-time knobs for the four filesystem tool descriptors.

    Callers construct one instance per registry and pass it to
    ``register_filesystem_tools``. Every field has a sensible default
    aligned with ADR-094 §D3.
    """

    def __init__(
        self,
        *,
        namespace_root: Path,
        read_timeout_seconds: int = 30,
        write_timeout_seconds: int = 30,
        delete_timeout_seconds: int = 30,
        list_timeout_seconds: int = 15,
    ) -> None:
        resolved = Path(namespace_root).resolve()
        if not resolved.is_absolute():
            raise ValueError(
                f"FilesystemToolConfig.namespace_root must resolve absolute; "
                f"got {namespace_root!r}"
            )
        self.namespace_root: Path = resolved
        self.read_timeout_seconds = read_timeout_seconds
        self.write_timeout_seconds = write_timeout_seconds
        self.delete_timeout_seconds = delete_timeout_seconds
        self.list_timeout_seconds = list_timeout_seconds


def register_filesystem_tools(
    registry: TektosToolRegistry,
    *,
    config: FilesystemToolConfig,
) -> None:
    """Register file_read / file_list / file_write / file_delete on ``registry``.

    Idempotent-friendly: raises ``ValueError`` from
    ``TektosToolRegistry.register`` if any tool is already registered,
    matching the Stage 4.7 registry contract. Callers wanting reset
    semantics can unregister first.
    """
    registry.register(_FILE_READ_DESCRIPTOR)
    registry.register(_FILE_LIST_DESCRIPTOR)
    registry.register(_FILE_WRITE_DESCRIPTOR)
    registry.register(_FILE_DELETE_DESCRIPTOR)


# ── Descriptors ─────────────────────────────────────────────────────────


_FILE_READ_DESCRIPTOR: Final[ToolDescriptor] = ToolDescriptor(
    name="file_read",
    description=(
        "Read the contents of a file. Path is resolved relative to the "
        "registered NamespaceRoot; escapes (../, absolute paths outside "
        "root, symlink escapes) are blocked by the pre-approval "
        "path-traversal detector."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to NamespaceRoot",
            },
            "argv": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["path"],
    },
    approval_tier=ChangeApprovalTier.AUTONOMOUS,
    network="none",
    timeout_seconds=30,
    max_memory_mb=128,
    max_cpu_percent=50,
    scan_kind=FILESYSTEM_SCAN_KIND,
)


_FILE_LIST_DESCRIPTOR: Final[ToolDescriptor] = ToolDescriptor(
    name="file_list",
    description=(
        "List directory entries with long-form metadata. Path resolved "
        "relative to NamespaceRoot; escapes rejected pre-approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "argv": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["path"],
    },
    approval_tier=ChangeApprovalTier.AUTONOMOUS,
    network="none",
    timeout_seconds=15,
    max_memory_mb=64,
    max_cpu_percent=25,
    scan_kind=FILESYSTEM_SCAN_KIND,
)


_FILE_WRITE_DESCRIPTOR: Final[ToolDescriptor] = ToolDescriptor(
    name="file_write",
    description=(
        "Write content to a file. Requires HUMAN_REVIEW approval. Path "
        "resolved relative to NamespaceRoot; escapes rejected pre-approval. "
        "Content passed via stdin — never on the command line — to close "
        "the shell-injection surface."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "argv": {"type": "array", "items": {"type": "string"}},
            "stdin": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    approval_tier=ChangeApprovalTier.HUMAN_REVIEW,
    network="none",
    timeout_seconds=30,
    max_memory_mb=128,
    max_cpu_percent=50,
    scan_kind=FILESYSTEM_SCAN_KIND,
)


_FILE_DELETE_DESCRIPTOR: Final[ToolDescriptor] = ToolDescriptor(
    name="file_delete",
    description=(
        "Delete a file or directory recursively. Requires HUMAN_REQUIRED "
        "approval (irreversible). Path resolved relative to NamespaceRoot; "
        "escapes rejected pre-approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "argv": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["path"],
    },
    approval_tier=ChangeApprovalTier.HUMAN_REQUIRED,
    network="none",
    timeout_seconds=30,
    max_memory_mb=64,
    max_cpu_percent=50,
    scan_kind=FILESYSTEM_SCAN_KIND,
)


# ── Invocation helpers ──────────────────────────────────────────────────


async def invoke_file_read(
    registry: TektosToolRegistry,
    *,
    path: str,
    intention_id: str,
    config: FilesystemToolConfig,
    proposing_domain: str = "tektos",
) -> SandboxResult:
    """Invoke ``file_read`` on ``registry`` for ``path``.

    Builds argv ``["cat", <resolved-path>]`` where the resolved path is
    ``config.namespace_root / path``. The registry's pre-approval
    detector inspects the raw ``path`` argument — passing a resolved
    argv does NOT bypass the traversal check, because the detector reads
    ``arguments["path"]``, not ``arguments["argv"]``.
    """
    resolved = str(config.namespace_root / path)
    return await registry.invoke(
        "file_read",
        {"path": path, "argv": ["cat", resolved]},
        intention_id=intention_id,
        proposing_domain=proposing_domain,
    )


async def invoke_file_list(
    registry: TektosToolRegistry,
    *,
    path: str,
    intention_id: str,
    config: FilesystemToolConfig,
    proposing_domain: str = "tektos",
) -> SandboxResult:
    resolved = str(config.namespace_root / path)
    return await registry.invoke(
        "file_list",
        {"path": path, "argv": ["ls", "-la", resolved]},
        intention_id=intention_id,
        proposing_domain=proposing_domain,
    )


async def invoke_file_write(
    registry: TektosToolRegistry,
    *,
    path: str,
    content: str,
    intention_id: str,
    config: FilesystemToolConfig,
    proposing_domain: str = "tektos",
) -> SandboxResult:
    """Invoke ``file_write`` — content is passed via stdin (no shell)."""
    resolved = str(config.namespace_root / path)
    return await registry.invoke(
        "file_write",
        {
            "path": path,
            "content": content,
            "argv": ["tee", resolved],
            "stdin": content,
        },
        intention_id=intention_id,
        proposing_domain=proposing_domain,
    )


async def invoke_file_delete(
    registry: TektosToolRegistry,
    *,
    path: str,
    intention_id: str,
    config: FilesystemToolConfig,
    proposing_domain: str = "tektos",
) -> SandboxResult:
    resolved = str(config.namespace_root / path)
    return await registry.invoke(
        "file_delete",
        {"path": path, "argv": ["rm", "-rf", resolved]},
        intention_id=intention_id,
        proposing_domain=proposing_domain,
    )


# Keep the unused-import safety net: consuming ``Any`` in the module so
# static analyzers do not complain if descriptors evolve to reference it.
_ = Any
