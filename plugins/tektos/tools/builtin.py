"""Built-in sandbox tools for TektosToolRegistry (Stage 9.2 · plan-v2 §9.2).

Ports the three built-in tools that Stage 3.13/4.8 did not land (the
donor's ``load_built_in`` factory was trimmed at Stage 3.2 — see
``adapters/sandbox/tektos/vendor/tool_registry_donor.py`` header). This
module completes the donor's 7-tool built-in surface:

- ``bash``             — HUMAN_REQUIRED · ``["bash", "-c", <command>]``
  (donor ``shell_exec`` tier; ADR-037 fail-closed for arbitrary shell)
- ``directory_create`` — HUMAN_REQUIRED · ``["mkdir", "-p", <resolved-path>]``
  (mutation; same tier as ``file_write``/``file_delete`` per ADR-094)
- ``search``           — AUTONOMOUS · ``["rg", "--line-number", <query>, <path>]``
  (read-only, budgeted — same tier class as ``file_read``/``file_list``)

Conventions inherited from Stage 4.8 (ADR-094):

- Every execution flows through ``SandboxPort.run`` with argv — no
  ``shell=True``. The ``bash`` tool's shell semantics are explicit:
  ``["bash", "-c", command]`` is the argv the sandbox executes; the
  sandbox boundary (limits, network policy, ADR-114) still applies.
- ``directory_create`` / ``search`` carry ``scan_kind="tektos.tool.filesystem"``
  and a ``path`` argument, so the pre-approval ``PathTraversalDetector``
  guards their paths exactly like the four Stage 4.8 tools (the guard
  set was extended in the same stage — see
  ``plugins/tektos/tools/detectors/path_traversal.py``).
- ``bash`` takes an explicit ``command`` string (donor semantics) and
  resolves an optional ``cwd`` against the namespace root. Its
  ``scan_kind`` is ``tektos.tool.shell`` so the filesystem detector
  does not misroute it; the 12-detector immune scan (Stage 9.1) sees
  the full ``arguments`` map for every invocation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from ports.approval import ChangeApprovalTier
from ports.sandbox import SandboxResult
from plugins.tektos.tools.registry import TektosToolRegistry, ToolDescriptor

__all__ = [
    "BUILTIN_TOOL_NAMES",
    "NamespaceRootConfig",
    "SHELL_SCAN_KIND",
    "register_builtin_tools",
    "invoke_bash",
    "invoke_directory_create",
    "invoke_search",
]


@runtime_checkable
class NamespaceRootConfig(Protocol):
    """Any config exposing ``namespace_root: Path`` (Stage 9.2).

    ``FilesystemToolConfig`` (Stage 4.8) satisfies this structurally;
    narrower per-call configs can too.
    """

    namespace_root: Path

BUILTIN_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {"bash", "directory_create", "search"}
)
"""Stage 9.2 tool names; combined with the four Stage 4.8 tools this is
the complete donor 7-tool built-in surface."""

SHELL_SCAN_KIND: Final[str] = "tektos.tool.shell"
"""ImmuneScanRequest.kind for bash invocations (Stage 9.1 detectors)."""

_FILESYSTEM_SCAN_KIND: Final[str] = "tektos.tool.filesystem"


# ── Descriptors ─────────────────────────────────────────────────────────


_BASH_DESCRIPTOR: Final[ToolDescriptor] = ToolDescriptor(
    name="bash",
    description=(
        "Execute a shell command in the sandbox via ['bash', '-c', command]. "
        "Returns stdout + stderr + exit_code. HUMAN_REQUIRED — arbitrary "
        "shell is the highest-blast-radius built-in (donor shell_exec tier, "
        "ADR-037). The command string is passed as one argv element — the "
        "sandbox executes bash directly, nothing goes through a second shell."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "argv": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
        },
        "required": ["command"],
    },
    approval_tier=ChangeApprovalTier.HUMAN_REQUIRED,
    network="none",
    timeout_seconds=60,
    max_memory_mb=512,
    max_cpu_percent=100,
    scan_kind=SHELL_SCAN_KIND,
)


_DIRECTORY_CREATE_DESCRIPTOR: Final[ToolDescriptor] = ToolDescriptor(
    name="directory_create",
    description=(
        "Create a directory and any missing parents (mkdir -p). Path is "
        "resolved relative to the registered NamespaceRoot; escapes "
        "(../, absolute paths outside root, symlink escapes) are blocked "
        "by the pre-approval path-traversal detector. HUMAN_REQUIRED — "
        "filesystem mutation (same tier class as file_write/file_delete, "
        "ADR-094)."
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
    timeout_seconds=15,
    max_memory_mb=64,
    max_cpu_percent=25,
    scan_kind=_FILESYSTEM_SCAN_KIND,
)


_SEARCH_DESCRIPTOR: Final[ToolDescriptor] = ToolDescriptor(
    name="search",
    description=(
        "Search file contents with a regex pattern (ripgrep). Path is "
        "resolved relative to the registered NamespaceRoot; escapes "
        "rejected pre-approval. Read-only + budgeted (max_results, "
        "timeout) — AUTONOMOUS, same tier class as file_read/file_list."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string"},
            "case_sensitive": {"type": "boolean"},
            "max_results": {"type": "integer"},
            "argv": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
    },
    approval_tier=ChangeApprovalTier.AUTONOMOUS,
    network="none",
    timeout_seconds=30,
    max_memory_mb=256,
    max_cpu_percent=50,
    scan_kind=_FILESYSTEM_SCAN_KIND,
)


def register_builtin_tools(registry: TektosToolRegistry) -> None:
    """Register bash / directory_create / search on ``registry``.

    Idempotency contract matches Stage 4.8: raises ``ValueError`` if any
    name is already registered (callers unregister first for reset).
    """
    registry.register(_BASH_DESCRIPTOR)
    registry.register(_DIRECTORY_CREATE_DESCRIPTOR)
    registry.register(_SEARCH_DESCRIPTOR)


# ── Invocation helpers ──────────────────────────────────────────────────


async def invoke_bash(
    registry: TektosToolRegistry,
    *,
    command: str,
    intention_id: str,
    cwd: str | None = None,
    proposing_domain: str = "tektos",
) -> SandboxResult:
    """Invoke ``bash`` for ``command``.

    Builds argv ``["bash", "-c", command]`` (donor semantics). ``cwd``
    defaults to the sandbox's working directory when omitted.
    """
    arguments: dict[str, object] = {
        "command": command,
        "argv": ["bash", "-c", command],
    }
    if cwd is not None:
        arguments["cwd"] = cwd
    return await registry.invoke(
        "bash",
        arguments,
        intention_id=intention_id,
        proposing_domain=proposing_domain,
    )


async def invoke_directory_create(
    registry: TektosToolRegistry,
    *,
    path: str,
    intention_id: str,
    config: NamespaceRootConfig,
    proposing_domain: str = "tektos",
) -> SandboxResult:
    """Invoke ``directory_create`` for ``path`` (mkdir -p).

    ``config.namespace_root`` is used to resolve argv — the detector
    reads the raw ``path`` argument, so this does not bypass the
    traversal check (same pattern as the Stage 4.8 helpers).
    """
    resolved = str(Path(config.namespace_root) / path)
    return await registry.invoke(
        "directory_create",
        {"path": path, "argv": ["mkdir", "-p", resolved]},
        intention_id=intention_id,
        proposing_domain=proposing_domain,
    )


async def invoke_search(
    registry: TektosToolRegistry,
    *,
    query: str,
    intention_id: str,
    config: NamespaceRootConfig,
    path: str = ".",
    case_sensitive: bool = False,
    max_results: int = 50,
    proposing_domain: str = "tektos",
) -> SandboxResult:
    """Invoke ``search`` (ripgrep) for ``query`` under ``path``.

    argv: ``["rg", "--line-number", [-s?], query, resolved-path]`` —
    case-insensitive by default (donor semantics).
    """
    resolved = str(Path(config.namespace_root) / path)
    argv = ["rg", "--line-number"]
    if not case_sensitive:
        argv.append("-i")
    argv.extend([query, resolved])
    return await registry.invoke(
        "search",
        {
            "query": query,
            "path": path,
            "case_sensitive": case_sensitive,
            "max_results": max_results,
            "argv": argv,
        },
        intention_id=intention_id,
        proposing_domain=proposing_domain,
    )
