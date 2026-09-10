"""adapters.sandbox.tektos.vendor.sandbox_exec_donor — subprocess exec primitives.

# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/providers/sandbox_provider.py
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole
#   copyright).
# Modifications from upstream: trimmed from 763 lines to ~180. Kept the
#   subprocess-based bash exec primitive, the output-size cap constant,
#   and the _docker_exec helper (retained for future Terminal-Bench
#   integration; NOT wired at Stage 4.7). Dropped: file_read / file_write /
#   file_delete / directory_list / directory_create tool handlers (Stage
#   4.8+), sudo auto-retry (leaks host state), PEP-668 hint injection
#   (Kosmos policy chooses at a higher layer), grep-based `search` tool
#   (deferred to RepoMapPort). Also dropped: `shell=True` bash entrypoint
#   at the module surface — adapter layer will exec argv directly. Kept a
#   `run_shell(command, ...)` compatibility helper for the Docker-exec
#   branch which still needs shell parsing on the container side.
# See docs/adrs/ADR-093-tektos-sandbox-planner-tools-absorption-scope.md
# and PORTING_LEDGER.md.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("tektos.sandbox.vendor")

# ── Constants (verbatim from upstream) ──────────────────────────────────────

# FS_ROOT configurable via env var (upstream PlexClaw bug #12 fix).
FS_ROOT = Path(os.getenv("TEKTOS_FS_ROOT", "/")).resolve()

# Max execution time for bash commands (seconds).
BASH_TIMEOUT = int(os.getenv("TEKTOS_BASH_TIMEOUT", "300"))

# Max captured stdout+stderr per stream (bytes).
MAX_OUTPUT_SIZE = 100_000


# ── Value objects ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExecOutcome:
    """Immutable outcome of a subprocess exec call."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


# ── Docker-exec helper (retained; unused at Stage 4.7) ─────────────────────


def _docker_exec(
    container: str,
    command: str,
    *,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    """Execute ``command`` inside a running Docker container.

    Verbatim from upstream. Wired at Stage 4.8+ Terminal-Bench integration.
    """

    return subprocess.run(
        ["docker", "exec", "-w", "/app", container, "bash", "-c", command],
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ── Core exec primitive ────────────────────────────────────────────────────


def exec_argv(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout: int,
    max_output: int = MAX_OUTPUT_SIZE,
    stdin: str | None = None,
    preexec_fn: Any = None,
) -> ExecOutcome:
    """Execute ``argv`` without a shell.

    The adapter layer supplies ``preexec_fn`` for ``resource.setrlimit``
    calls (memory, CPU, file-size). Output on each stream is truncated
    to ``max_output`` bytes. On timeout returns ``timed_out=True`` with
    ``exit_code=-signal.SIGKILL`` (via subprocess convention) and any
    partial stdout/stderr captured before the kill.
    """

    try:
        completed = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
            input=stdin,
            preexec_fn=preexec_fn,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):  # timeout paths may return bytes
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return ExecOutcome(
            exit_code=-9,  # SIGKILL convention
            stdout=stdout[:max_output],
            stderr=(stderr + f"\nkilled: timeout after {timeout}s")[:max_output],
            timed_out=True,
        )

    return ExecOutcome(
        exit_code=completed.returncode,
        stdout=(completed.stdout or "")[:max_output],
        stderr=(completed.stderr or "")[:max_output],
        timed_out=False,
    )


def run_shell(
    command: str,
    *,
    cwd: str,
    env: dict[str, str],
    timeout: int,
    max_output: int = MAX_OUTPUT_SIZE,
) -> ExecOutcome:
    """Shell-parsed compatibility helper.

    RETAINED FOR THE DOCKER-EXEC BRANCH ONLY. The kosmos adapter never
    calls this at Stage 4.7 — the adapter always exec's ``argv`` directly
    to close the shell-injection surface upstream exposed via
    ``shell=True``. This helper stays because the ``docker exec`` branch
    (Stage 4.8+ Terminal-Bench integration) needs shell parsing on the
    container side and cannot pre-split into argv.
    """

    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return ExecOutcome(
            exit_code=-9,
            stdout=stdout[:max_output],
            stderr=(stderr + f"\nkilled: timeout after {timeout}s")[:max_output],
            timed_out=True,
        )

    return ExecOutcome(
        exit_code=completed.returncode,
        stdout=(completed.stdout or "")[:max_output],
        stderr=(completed.stderr or "")[:max_output],
        timed_out=False,
    )


__all__ = [
    "BASH_TIMEOUT",
    "ExecOutcome",
    "FS_ROOT",
    "MAX_OUTPUT_SIZE",
    "_docker_exec",
    "exec_argv",
    "run_shell",
]
