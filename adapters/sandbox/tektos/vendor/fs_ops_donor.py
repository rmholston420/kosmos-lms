# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/providers/sandbox_provider.py
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole copyright).
# Modifications from upstream:
#   * Only ``_safe_path``, ``_format_file_read`` extracted; the surrounding
#     ``SandboxProvider`` class (docker exec, shell dispatch, LLM prompt
#     surface, file caching, delegation) is intentionally NOT vendored.
#   * ``_safe_path`` renamed ``resolve_within_root`` and takes ``root``
#     as an explicit argument (upstream read ``self.fs_root`` — bound to
#     process-global env var; explicit-argument form is DI-friendly and
#     testable).
#   * ``resolve_within_root`` returns ``ResolveOutcome`` (dataclass with
#     ``resolved`` + ``reason``) instead of ``Path | None`` — the
#     path-traversal detector needs the reason string for its evidence
#     field, which upstream discarded to the ``log.warning`` sink.
#   * Removed ``log.warning(...)`` side-effect on escape; caller (detector)
#     is responsible for logging via ``ImmunePort`` publish + MemoryPort.
#   * Symlink escape check strengthened: upstream ``str.startswith`` check
#     only catches lexical escapes; this version uses
#     ``Path.is_relative_to`` on the resolved path against the resolved
#     root, which handles ``/tmp/link -> /etc`` cases when the link is
#     inside the sandbox root.
#   * ``_format_file_read`` copied verbatim (produces the
#     paged, self-describing file_read result the donor was careful about).
# See docs/adrs/ADR-094-tektos-tool-surface-reconciliation-and-filesystem-tools.md
# and PORTING_LEDGER.md.
"""Vendored filesystem primitives from Tektos-Ultima SandboxProvider.

This module carries the minimum surface needed by
``plugins/tektos/tools/filesystem.py`` (Stage 4.8): a safe-path resolver
that returns a reason string on escape, and the ``file_read`` paging
formatter. Everything else in the upstream ``SandboxProvider`` — docker
exec, shell dispatch, delegation, LLM prompt surface, caching, tool
registration — is intentionally NOT vendored; those responsibilities
live in ``TektosToolRegistry`` (ADR-093), ``TektosSandboxAdapter``
(ADR-082/-093), and ``MCPToolBridge`` (this ADR).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "ResolveOutcome",
    "resolve_within_root",
    "format_file_read_page",
    "DEFAULT_READ_LIMIT_LINES",
    "DEFAULT_READ_MAX_BYTES",
]


DEFAULT_READ_LIMIT_LINES: Final[int] = 2000
"""Default line-limit for a single ``file_read`` page (matches upstream)."""

DEFAULT_READ_MAX_BYTES: Final[int] = 256 * 1024
"""Byte-cap for a single ``file_read`` page — hard truncation ceiling."""


@dataclass(frozen=True, slots=True)
class ResolveOutcome:
    """Result of ``resolve_within_root``.

    ``resolved`` is the resolved absolute path when the input path is
    within ``root``, else ``None``. ``reason`` is a short machine-readable
    tag when the path is rejected; empty on success. The two-field shape
    (rather than upstream's ``Path | None``) lets the path-traversal
    detector emit the exact reason as ``DetectorHit.evidence``.
    """

    resolved: Path | None
    reason: str


def resolve_within_root(path: str, *, root: Path) -> ResolveOutcome:
    """Resolve ``path`` relative to ``root`` and verify containment.

    Rejection reasons (returned in ``ResolveOutcome.reason``):

    - ``"empty_path"`` — input is falsy or whitespace-only.
    - ``"dotdot_component"`` — input contains ``..`` as a path component
      (lexical check; catches most escapes before resolution).
    - ``"absolute_escape"`` — resolved path is not under ``root``.
    - ``"symlink_escape"`` — resolved-via-symlink path is not under
      ``root`` (catches ``/root/link -> /etc/passwd``).

    On success, ``resolved`` is the canonical absolute path (with
    symlinks followed via ``Path.resolve()``) and ``reason`` is ``""``.

    Args:
        path: User-supplied path (relative or absolute).
        root: Sandbox root — must already be an absolute, resolved path.
    """
    if not path or not path.strip():
        return ResolveOutcome(resolved=None, reason="empty_path")

    # 1. Lexical .. check — catches escapes before we touch the filesystem.
    #    (A resolved path never contains .. so this is a pre-check on the
    #    *input*, not the resolved form.)
    parts = Path(path).parts
    if ".." in parts:
        return ResolveOutcome(resolved=None, reason="dotdot_component")

    # 2. Compose + resolve. If ``path`` is absolute, Path composition
    #    discards ``root`` — that's fine, because the containment check
    #    below will reject it.
    try:
        candidate = (root / path).resolve()
    except OSError as exc:
        # Broken symlinks, permission errors during resolve. Rare, but
        # opaque — treat as an escape to fail-closed.
        return ResolveOutcome(resolved=None, reason=f"resolve_error:{exc.errno}")

    # 3. Containment check via is_relative_to (Python 3.9+). This is
    #    stricter than upstream's str.startswith — it correctly handles
    #    the /rootfoo vs /root/foo prefix-collision case.
    try:
        candidate.relative_to(root)
    except ValueError:
        # If the input was absolute *and* landed outside root, that's an
        # absolute_escape; if it was relative but resolved out via a
        # symlink, that's a symlink_escape. Distinguish by re-composing
        # without resolve():
        raw_composed = (root / path)
        try:
            raw_composed.relative_to(root)
        except ValueError:
            return ResolveOutcome(resolved=None, reason="absolute_escape")
        # raw_composed *lexically* under root, but resolve() escaped it →
        # symlink or ``..`` we missed.
        return ResolveOutcome(resolved=None, reason="symlink_escape")

    return ResolveOutcome(resolved=candidate, reason="")


def format_file_read_page(
    *,
    path: str,
    content: str,
    offset: int,
    limit: int,
    max_bytes: int = DEFAULT_READ_MAX_BYTES,
) -> str:
    """Return a paged, self-describing ``file_read`` result.

    Vendored verbatim from ``SandboxProvider._format_file_read`` (upstream
    reasoning preserved): splits ``content`` on newlines so ``offset``
    and ``limit`` are line-based (matches the model's mental model when
    it says 'read lines 200-400'). The header carries the total line
    count and the exact range served so the model can page
    deterministically instead of guessing.
    """
    lines = content.splitlines()
    total_lines = len(lines)
    total_bytes = len(content)

    start = max(1, offset)
    if start > total_lines:
        start = total_lines + 1
    end = min(total_lines, start + max(1, limit) - 1)

    selected = lines[start - 1 : end]
    body = "\n".join(selected)

    truncated_by_bytes = False
    if len(body) > max_bytes:
        body = body[:max_bytes]
        truncated_by_bytes = True

    truncated = truncated_by_bytes or end < total_lines

    header = (
        f"file_read path={path} total_lines={total_lines} "
        f"total_bytes={total_bytes} start_line={start} end_line={end} "
        f"truncated={'true' if truncated else 'false'}\n"
        f"--- content ---\n"
    )
    footer = ""
    if truncated and end < total_lines:
        footer = (
            f"\n--- end of window ---\n"
            f"[{total_lines - end} more lines. Call file_read again with "
            f"offset={end + 1} to continue.]"
        )
    elif truncated_by_bytes:
        footer = (
            f"\n--- end of window ---\n"
            f"[Output byte cap reached ({max_bytes} bytes). "
            f"Narrow the range with a smaller limit or a later offset.]"
        )
    return header + body + footer
