"""plugins.tektos.tools.sandbox_provider — the donor sandbox executor (T5b).

Donor-faithful port of ``tektos-ultima/src/tektos/providers/sandbox_provider.py``
(the 7 built-in tool handlers: bash, file_read, file_write, file_delete,
directory_list, directory_create, search). This is the coding-agent-specific
execution policy per the porting layering rule: the generic registry substrate
lives in ``kernel/tool_registry.py``; the WHAT-to-execute (shell commands,
filesystem ops, search — the Tektos threat model's toolset) stays in the Tektos
plugin.

Donor-faithful decisions:

- ``FS_ROOT`` defaults to ``/`` via ``TEKTOS_FS_ROOT`` (donor behavior — the
  agent loop runs on the real workspace; ``_safe_path`` resolves + keeps
  paths under the root).
- ``BASH_TIMEOUT`` defaults to 300 s via ``TEKTOS_BASH_TIMEOUT`` (donor).
- ``MAX_OUTPUT_SIZE`` = 100 000 bytes (donor).
- ``_execute_bash`` keeps the donor's recovery behaviors: permission-denied
  auto-retry with ``sudo -n`` (with the "no root access" note), and the PEP 668
  hint. The donor's Terminal-Bench Docker proxying (``docker_container``) is
  dropped — that is the Terminal-Bench evaluation harness, not Tektos
  functionality (exit-gate: no behavioral loss; the kernel's own
  ``TektosSandboxAdapter`` provides containerized execution where wanted).
- Only the 7 ``load_built_in`` tools are ported. The donor's
  ``_web_search``/``_web_extract``/``_web_fetch``/``_rag_query``/
  ``_delegate_task`` handlers belong to the search/rag/delegation subsystems
  (separate T-buckets), not to the built-in tool set.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("tektos.sandbox")

# FS_ROOT configurable via env var (donor PlexClaw bug #12 fix).
FS_ROOT = Path(os.getenv("TEKTOS_FS_ROOT", "/")).resolve()

# Security: max execution time for bash commands (seconds).
BASH_TIMEOUT = int(os.getenv("TEKTOS_BASH_TIMEOUT", "300"))

# Security: max output size (bytes).
MAX_OUTPUT_SIZE = 100_000


class SandboxProvider:
    """Real tool execution for the agent loop (donor ``SandboxProvider``).

    Provides safe execution of bash commands, file operations, and search
    within a configurable filesystem root (``TEKTOS_FS_ROOT`` env var).
    """

    def __init__(
        self,
        fs_root: Path | None = None,
        bash_timeout: int = BASH_TIMEOUT,
        max_output_size: int = MAX_OUTPUT_SIZE,
    ) -> None:
        self.fs_root = (fs_root or FS_ROOT).resolve()
        self.bash_timeout = bash_timeout
        self.max_output_size = max_output_size

        # Verify sandbox root exists
        if not self.fs_root.exists():
            log.warning("Sandbox root %s does not exist, creating it", self.fs_root)
            self.fs_root.mkdir(parents=True, exist_ok=True)

    # ── Provider lifecycle (no-op, donor parity) ────────────────────────────

    async def start(self) -> None:
        """No-op for the local sandbox; kept for :class:`ProviderPort`."""
        return None

    async def stop(self) -> None:
        """No-op for the local sandbox; kept for :class:`ProviderPort`."""
        return None

    async def health(self) -> bool:
        """Return ``True`` when the sandbox root is writable."""
        try:
            return self.fs_root.exists() and self.fs_root.is_dir()
        except OSError:
            return False

    # ── dispatch ────────────────────────────────────────────────────────────

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool by name with given input. Returns result string."""
        handlers = {
            "bash": self._execute_bash,
            "file_read": self._file_read,
            "file_write": self._file_write,
            "file_delete": self._file_delete,
            "directory_list": self._directory_list,
            "directory_create": self._directory_create,
            "search": self._search,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return f"Unknown tool: {tool_name}"

        try:
            result = handler(tool_input)
            return result
        except Exception as exc:  # noqa: BLE001 — donor catches all
            log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            return f"Error: {exc}"

    # ------------------------------------------------------------------
    # Bash execution
    # ------------------------------------------------------------------

    def _execute_bash(self, params: dict[str, Any]) -> str:
        """Execute a shell command within timeout.

        Recovery behaviors (donor, added for Terminal-Bench task success):
        - If the command fails with a permission error and does not already
          use sudo, automatically retry once with ``sudo -n`` (passwordless).
        - If the command fails with PEP 668 (externally-managed-environment),
          append a hint suggesting --break-system-packages or pipx/venv.
        """
        command = params.get("command", "")
        if not command:
            return "Error: No command provided"

        log.info("[TOOL: bash] %s", command[:200])
        note = ""

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.bash_timeout,
                cwd=str(self.fs_root),
            )

            # Permission denied without sudo -> auto-retry with sudo -n.
            # Piping to tail/head masks the exit code (pipe status = last
            # segment), so detect permission errors from the output text too.
            combined_out = (result.stdout or "") + (result.stderr or "")
            if "sudo" not in command.split()[0:2] and (
                (result.returncode != 0 and self._is_permission_error(result))
                or ("are you root?" in combined_out)
            ):
                log.info("[TOOL: bash] permission error, retrying with sudo -n")
                sudo_cmd = f"sudo -n {command}"
                result = subprocess.run(
                    sudo_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.bash_timeout,
                    cwd=str(self.fs_root),
                )
                if "interactive authentication is required" in (
                    (result.stdout or "") + (result.stderr or "")
                ):
                    note = (
                        "[auto-retried with sudo -n, but passwordless sudo is NOT available]\n"
                        "You do NOT have root access on this system. Do NOT attempt sudo again.\n"
                        "Work around it: install Python packages with pip --break-system-packages, "
                        "use user-level tools, or write code that avoids needing root.\n"
                    )
                else:
                    note = "[auto-retried with sudo -n]\n"

            output = ""
            if result.stdout:
                output += result.stdout[: self.max_output_size]
            if result.stderr:
                if output:
                    output += "\n--- stderr ---\n"
                output += result.stderr[: self.max_output_size]

            exit_code = result.returncode
            status = "success" if exit_code == 0 else "failed"

            # PEP 668 hint: pip install blocked by externally-managed-environment
            if exit_code != 0 and "externally-managed-environment" in output:
                output += (
                    "\n[HINT] This system uses PEP 668. To install a Python package, "
                    "use one of:\n"
                    "  pip install --break-system-packages <pkg>\n"
                    "  pipx install <pkg>\n"
                    "  python3 -m venv /tmp/venv && /tmp/venv/bin/pip install <pkg>\n"
                )

            return (
                f"{note}Exit {exit_code}: {status}\n{output}"
                if note
                else f"Exit {exit_code}: {status}\n{output}"
            )

        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {self.bash_timeout}s"
        except Exception as exc:  # noqa: BLE001 — donor catches all
            return f"Error executing command: {exc}"

    @staticmethod
    def _is_permission_error(result: subprocess.CompletedProcess) -> bool:
        """Detect permission-denied style failures in output."""
        text = (result.stdout or "") + (result.stderr or "")
        markers = (
            "Permission denied",
            "permission denied",
            "are you root?",
            "requires root",
            "insufficient permissions",
            "dpkg frontend lock",
            "interactive authentication is required",
        )
        return any(m in text for m in markers)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _file_read(self, params: dict[str, Any]) -> str:
        """Read file content with path validation and paging.

        Params:
            path (str, required): file path to read.
            offset (int, optional): 1-based starting line number. Default 1.
            limit  (int, optional): maximum number of lines to return.
                                    Default 2000. Use larger values for
                                    full-file reads.

        The returned string is always prefixed with a machine-readable header
        so the model can decide whether more paging is needed (prevents the
        'silent truncation loop').
        """
        file_path = params.get("path", "")
        if not file_path:
            return "Error: No path provided"

        # Coerce offset/limit — accept ints or numeric strings from the model.
        def _int_or(default: int, value: Any) -> int:
            try:
                if value is None or value == "":
                    return default
                iv = int(value)
                return iv if iv > 0 else default
            except (TypeError, ValueError):
                return default

        offset = _int_or(1, params.get("offset"))
        limit = _int_or(2000, params.get("limit"))

        resolved = self._safe_path(file_path)
        if not resolved:
            return f"Error: Path '{file_path}' is outside sandbox"

        if not resolved.exists():
            return f"Error: File not found: {file_path}"

        if not resolved.is_file():
            return f"Error: Not a file: {file_path}"

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            return self._format_file_read(str(resolved), content, offset, limit)
        except Exception as exc:  # noqa: BLE001 — donor catches all
            return f"Error reading file: {exc}"

    def _format_file_read(
        self, path: str, content: str, offset: int, limit: int
    ) -> str:
        """Return a paged, self-describing file_read result (donor verbatim)."""
        lines = content.splitlines()
        total_lines = len(lines)
        total_bytes = len(content)

        # 1-based, inclusive slice. Clamp to file bounds.
        start = max(1, offset)
        if start > total_lines:
            start = total_lines + 1  # empty slice; header still explains why
        end = min(total_lines, start + max(1, limit) - 1)

        selected = lines[start - 1 : end]
        body = "\n".join(selected)

        # Byte-level cap as a last-resort safety net so a pathological
        # single-line file cannot blow the LLM context.
        truncated_by_bytes = False
        if len(body) > self.max_output_size:
            body = body[: self.max_output_size]
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
                f"[Output byte cap reached ({self.max_output_size} bytes). "
                f"Narrow the range with a smaller limit or a later offset.]"
            )
        return header + body + footer

    def _file_write(self, params: dict[str, Any]) -> str:
        """Write file content with path validation (donor verbatim)."""
        file_path = params.get("path", "")
        content = params.get("content", "")
        mode = params.get("mode", "write")  # "write" or "append"

        if not file_path:
            return "Error: No path provided"

        resolved = self._safe_path(file_path)
        if not resolved:
            return f"Error: Path '{file_path}' is outside sandbox"

        # Create parent directories
        resolved.parent.mkdir(parents=True, exist_ok=True)

        try:
            if mode == "append":
                existing = resolved.read_text(encoding="utf-8", errors="replace")
                resolved.write_text(existing + content, encoding="utf-8")
            else:
                resolved.write_text(content, encoding="utf-8")

            log.info("[TOOL: file_write] %s (%d bytes)", file_path, len(content))
            return f"Written {len(content)} bytes to {file_path}"

        except Exception as exc:  # noqa: BLE001 — donor catches all
            return f"Error writing file: {exc}"

    def _file_delete(self, params: dict[str, Any]) -> str:
        """Delete a file or directory (donor verbatim)."""
        file_path = params.get("path", "")
        if not file_path:
            return "Error: No path provided"

        resolved = self._safe_path(file_path)
        if not resolved:
            return f"Error: Path '{file_path}' is outside sandbox"

        try:
            if resolved.is_dir():
                shutil.rmtree(resolved)
                log.info("[TOOL: file_delete] Deleted directory: %s", file_path)
                return f"Deleted directory: {file_path}"
            else:
                resolved.unlink()
                log.info("[TOOL: file_delete] Deleted file: %s", file_path)
                return f"Deleted file: {file_path}"

        except Exception as exc:  # noqa: BLE001 — donor catches all
            return f"Error deleting: {exc}"

    def _directory_list(self, params: dict[str, Any]) -> str:
        """List directory contents (donor verbatim)."""
        dir_path = params.get("path", ".")
        resolved = self._safe_path(dir_path)
        if not resolved:
            return f"Error: Path '{dir_path}' is outside sandbox"

        if not resolved.exists():
            return f"Error: Path not found: {dir_path}"

        if not resolved.is_dir():
            return f"Error: Not a directory: {dir_path}"

        try:
            entries = sorted(resolved.iterdir())
            lines = []
            for entry in entries:
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{'DIR' if entry.is_dir() else 'FILE'} {entry.name}{suffix}")
            return "\n".join(lines) if lines else "(empty directory)"
        except Exception as exc:  # noqa: BLE001 — donor catches all
            return f"Error listing directory: {exc}"

    def _directory_create(self, params: dict[str, Any]) -> str:
        """Create directory (and parents) (donor verbatim)."""
        dir_path = params.get("path", "")
        if not dir_path:
            return "Error: No path provided"

        resolved = self._safe_path(dir_path)
        if not resolved:
            return f"Error: Path '{dir_path}' is outside sandbox"

        try:
            resolved.mkdir(parents=True, exist_ok=True)
            return f"Created directory: {dir_path}"
        except Exception as exc:  # noqa: BLE001 — donor catches all
            return f"Error creating directory: {exc}"

    def _search(self, params: dict[str, Any]) -> str:
        """Search file contents (grep-like) (donor verbatim)."""
        query = params.get("query", "")
        path = params.get("path", ".")
        case_sensitive = params.get("case_sensitive", False)
        max_results = params.get("max_results", 50)

        if not query:
            return "Error: No search query provided"

        resolved = self._safe_path(path)
        if not resolved:
            return f"Error: Path '{path}' is outside sandbox"

        if not resolved.exists():
            return f"Error: Path not found: {path}"

        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(query), flags)

            matches: list[tuple] = []
            if resolved.is_file():
                matches = self._search_file(resolved, pattern, max_results)
            elif resolved.is_dir():
                # Path.walk() is only Python 3.12+; use os.walk for 3.10+
                # compatibility.
                for root_str, _dirs, files in os.walk(resolved):
                    root = Path(root_str)
                    for name in files:
                        if name.startswith("."):
                            continue
                        file_path = root / name
                        matches.extend(
                            self._search_file(file_path, pattern, max_results - len(matches))
                        )
                        if len(matches) >= max_results:
                            break
                    if len(matches) >= max_results:
                        break

            if not matches:
                return f"No matches for '{query}'"

            results = []
            for file_path, line_num, line in matches:
                results.append(f"{file_path}:{line_num}: {line.strip()}")
            return "\n".join(results)

        except Exception as exc:  # noqa: BLE001 — donor catches all
            return f"Error searching: {exc}"

    def _search_file(self, file_path: Path, pattern: re.Pattern, limit: int) -> list[tuple]:
        """Search a single file for pattern matches (donor verbatim)."""
        matches: list[tuple] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(content.split("\n"), 1):
                if pattern.search(line):
                    matches.append((str(file_path), i, line))
                    if len(matches) >= limit:
                        break
        except Exception as e:  # noqa: BLE001 — donor catches all
            log.warning("Sandbox operation failed: %s", e)
        return matches

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def _safe_path(self, path: str) -> Path | None:
        """Resolve and validate a path is within the sandbox root (donor verbatim)."""
        if not path:
            return None

        resolved = (self.fs_root / path).resolve()

        # Security: ensure path is within sandbox root
        if not str(resolved).startswith(str(self.fs_root)):
            log.warning("Path escape attempt: %s -> %s", path, resolved)
            return None

        return resolved
