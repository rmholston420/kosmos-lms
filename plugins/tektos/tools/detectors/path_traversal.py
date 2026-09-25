"""Path-traversal detector for TektosToolRegistry filesystem tools.

Stage 4.8 · ADR-094 §D3.

The detector implements the ``Detector`` Protocol from ``ports/immune.py``
and is passed to ``TektosToolRegistry`` at construction time via the new
``pre_approval_detectors`` kwarg. It runs before
``ApprovalGatewayPort.propose`` — a malicious path never reaches the
approval queue.

Applies only to scan requests with ``kind == "tektos.tool.filesystem"``
and the tool being one of ``file_read`` / ``file_list`` / ``file_write``
/ ``file_delete``. Every other scan returns an empty tuple (no hits).

The detector delegates path resolution to
``adapters.sandbox.tektos.vendor.fs_ops_donor.resolve_within_root``,
which returns a machine-readable reason string surfaced verbatim as
``DetectorHit.evidence`` (``empty_path``, ``dotdot_component``,
``absolute_escape``, ``symlink_escape``, ``resolve_error:*``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Final

from adapters.sandbox.tektos.vendor.fs_ops_donor import (
    ResolveOutcome,
    resolve_within_root,
)
from ports.approval import ApprovalStatus
from ports.immune import DetectorHit, DetectorSeverity, ImmuneScanRequest
from plugins.tektos.tools.registry import ToolApprovalDenied

__all__ = [
    "FILESYSTEM_TOOL_NAMES",
    "PathTraversalDetected",
    "PathTraversalDetector",
]


FILESYSTEM_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "file_read",
        "file_list",
        "file_write",
        "file_delete",
        # Stage 9.2 (plan-v2 §9.2): path-bearing built-in tools —
        # ``directory_create`` and ``search`` resolve their ``path``
        # argument against the same namespace root and carry the same
        # ``tektos.tool.filesystem`` scan_kind, so they get the same
        # pre-approval guard.
        "directory_create",
        "search",
    }
)
"""Tool names guarded by the path-traversal detector.

MCP-discovered tools with matching names (e.g. an MCP server named its
tool ``file_write``) are guarded too — the tier map from ADR-037 then
correctly resolves them to ``HUMAN_REQUIRED``, and the detector runs
before that gate.
"""


class PathTraversalDetected(ToolApprovalDenied):
    """Raised when the path-traversal detector blocks an invocation.

    Subclass of ``ToolApprovalDenied`` so callers can catch either
    uniformly (``except ToolApprovalDenied``) or specifically
    (``except PathTraversalDetected``).

    Attributes:
        reason: One of the machine-readable tags emitted by
            ``resolve_within_root`` (e.g. ``"dotdot_component"``).
        offending_path: The exact path the caller tried to reach.
    """

    def __init__(self, *, offending_path: str, reason: str) -> None:
        super().__init__(
            approval_id="",
            status=ApprovalStatus.REJECTED,
            reason=f"path_traversal:{reason}:{offending_path}",
        )
        self.offending_path = offending_path
        # Note: `.reason` is set by the parent __init__ to the composed
        # string above. We keep the short tag on `.detector_reason` for
        # tests that want to inspect it without splitting.
        self.detector_reason = reason


class PathTraversalDetector:
    """Pre-approval detector guarding filesystem tools.

    Implements the ``Detector`` Protocol from ``ports/immune.py``.

    Attributes:
        name: Stable detector identifier (``"path_traversal"``).
        severity_ceiling: Always ``"block"`` — this detector only emits
            block hits (or no hits at all).
        namespace_root: Absolute, resolved path — the sandbox boundary
            every filesystem-tool path must resolve within.
    """

    name: ClassVar[str] = "path_traversal"
    severity_ceiling: ClassVar[DetectorSeverity] = "block"

    def __init__(self, *, namespace_root: Path) -> None:
        # Resolve at construction time so callers cannot pass a relative
        # or symlink-based root that would silently escape.
        resolved_root = Path(namespace_root).resolve()
        if not resolved_root.is_absolute():
            raise ValueError(
                f"PathTraversalDetector.namespace_root must resolve to an "
                f"absolute path; got {namespace_root!r}"
            )
        self.namespace_root: Path = resolved_root

    async def evaluate(
        self, request: ImmuneScanRequest
    ) -> tuple[DetectorHit, ...]:
        """Return zero or one hits for ``request``.

        Contract (ADR-079):
        - Empty tuple on scans this detector does not guard.
        - Empty tuple on scans it guards where the path is safe.
        - Single hit with ``severity="block"`` on scans it guards where
          the path escapes ``namespace_root``.
        """
        if request.kind != "tektos.tool.filesystem":
            return ()

        payload: dict[str, Any] = request.payload
        tool_name = str(payload.get("tool_name", ""))
        if tool_name not in FILESYSTEM_TOOL_NAMES:
            return ()

        arguments = payload.get("arguments", {}) or {}
        path = str(arguments.get("path", ""))
        outcome: ResolveOutcome = resolve_within_root(
            path, root=self.namespace_root
        )
        if outcome.resolved is not None:
            return ()

        # Block. Evidence carries the reason tag + the offending path +
        # the root — sufficient for a human reviewing the immune log to
        # reconstruct exactly what the tool tried to reach.
        evidence = (
            f"reason={outcome.reason} path={path!r} "
            f"namespace_root={str(self.namespace_root)!r} tool={tool_name}"
        )
        return (
            DetectorHit(
                detector_name=self.name,
                severity="block",
                evidence=evidence,
            ),
        )
