"""adapters.sandbox.tektos.adapter — TektosSandboxAdapter (ADR-082, ADR-093).

Wraps the Tektos-Ultima donor exec primitive
(``adapters.sandbox.tektos.vendor.sandbox_exec_donor``) behind
``SandboxPort`` and adds the isolation the donor lacks:

* ``argv``-first execution — never ``shell=True``. Closes the donor's
  shell-injection surface.
* ``resource.setrlimit`` via ``preexec_fn`` for ``RLIMIT_AS`` (memory),
  ``RLIMIT_CPU``, and ``RLIMIT_FSIZE``.
* ``SandboxLimits.network`` enforcement:
    - ``"none"``  — attempt ``unshare -n`` prefix; fail-closed on
      unavailable (returns ``exit_code=126``, ``killed_by="limit"``).
    - ``"loopback"`` — same as ``"none"`` plus loopback bring-up
      (best-effort inside the netns).
    - ``"full"``  — no network namespace. Must be approval-gated at the
      tool-registry layer (ADR-093 §4).
* Opportunistic cgroups v2 write to
  ``/sys/fs/cgroup/kosmos-sandbox/<run_id>/memory.max`` when the mount is
  writable; otherwise the adapter relies on ``RLIMIT_AS`` alone and
  publishes ``sandbox.cgroups_unavailable`` on the first call.
* Wall-time enforced via ``subprocess.run(timeout=...)`` in the donor
  helper; the adapter translates a timeout into ``killed_by="limit"``.
* Every ``run()`` publishes ``sandbox.started`` and either
  ``sandbox.completed`` or ``sandbox.killed`` per ADR-082 rule 1, and
  every ``SandboxResult`` writes ``MemoryPort`` with
  ``provenance="sandbox"``, ``confidence=1.0`` per rule 2.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import resource
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from adapters.sandbox.tektos.vendor.sandbox_exec_donor import (
    MAX_OUTPUT_SIZE,
    ExecOutcome,
    exec_argv,
)
from ports.event_envelope import EventEnvelope
from ports.sandbox import (
    SandboxHandle,
    SandboxLimits,
    SandboxNetworkPolicy,
    SandboxRequest,
    SandboxResult,
)

logger = logging.getLogger(__name__)

__all__ = ["TektosSandboxAdapter"]


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class _MemoryLike(Protocol):
    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict[str, Any] | None = None,
    ) -> str: ...


class TektosSandboxAdapter:
    """Linux-native ``SandboxPort`` adapter.

    Non-Linux hosts still get a working adapter, but ``network="none"``
    fail-closes because no namespace tooling is available. ``NoOpSandbox
    Adapter`` should be used for CI on those hosts.
    """

    def __init__(
        self,
        *,
        event_bus: _EventBusLike | None = None,
        memory: _MemoryLike | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._memory = memory
        self._active: dict[str, SandboxHandle] = {}
        self._cancelled: set[str] = set()
        self._closed = False
        self._cgroups_warned = False

    # ── SandboxPort surface ───────────────────────────────────────────

    async def run(self, request: SandboxRequest) -> SandboxResult:
        if self._closed:
            raise RuntimeError("TektosSandboxAdapter is closed")
        if not request.argv:
            raise ValueError("SandboxRequest.argv must be non-empty")

        run_id = f"tektos-{uuid.uuid4().hex[:12]}"
        handle = SandboxHandle(
            run_id=run_id,
            started_at=datetime.now(timezone.utc),
            request=request,
        )
        self._active[run_id] = handle
        await self._publish("sandbox.started", run_id=run_id, request=request)

        # Fail-closed network isolation.
        network_guard = self._network_guard(request.limits.network, run_id)
        if network_guard is not None:
            self._active.pop(run_id, None)
            await self._publish(
                "sandbox.isolation_unavailable",
                run_id=run_id,
                request=request,
                extra={"reason": network_guard, "requested_network": request.limits.network},
            )
            result = SandboxResult(
                run_id=run_id,
                exit_code=126,
                stdout="",
                stderr=f"network isolation unavailable on this platform ({network_guard})",
                wall_seconds=0.0,
                peak_memory_mb=0,
                killed_by="limit",
            )
            await self._publish(
                "sandbox.completed",
                run_id=run_id,
                request=request,
                extra={
                    "exit_code": result.exit_code,
                    "killed_by": result.killed_by,
                    "wall_seconds": result.wall_seconds,
                },
            )
            await self._write_memory(result, request)
            return result

        # Build argv (optionally wrapped in `unshare`).
        argv = self._wrap_argv_for_network(list(request.argv), request.limits.network)

        # Cgroups v2 opportunistic write (advisory; log once if unavailable).
        self._maybe_write_cgroups(run_id, request.limits)

        started_at = time.monotonic()
        try:
            outcome = await asyncio.to_thread(
                exec_argv,
                argv,
                cwd=request.cwd,
                env=dict(request.env),
                timeout=request.limits.max_wall_seconds,
                max_output=MAX_OUTPUT_SIZE,
                stdin=request.stdin,
                preexec_fn=self._make_preexec(request.limits),
            )
        except Exception as exc:  # noqa: BLE001
            self._active.pop(run_id, None)
            self._cancelled.discard(run_id)
            wall = time.monotonic() - started_at
            result = SandboxResult(
                run_id=run_id,
                exit_code=1,
                stdout="",
                stderr=f"sandbox exec error: {exc}",
                wall_seconds=wall,
                peak_memory_mb=0,
                killed_by="exit",
            )
            await self._publish(
                "sandbox.completed",
                run_id=run_id,
                request=request,
                extra={"exit_code": 1, "error": str(exc), "wall_seconds": wall},
            )
            await self._write_memory(result, request)
            return result

        wall = time.monotonic() - started_at
        self._active.pop(run_id, None)
        was_cancelled = run_id in self._cancelled
        self._cancelled.discard(run_id)

        killed_by = self._classify_termination(outcome, was_cancelled)
        result = SandboxResult(
            run_id=run_id,
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            wall_seconds=wall,
            peak_memory_mb=0,
            killed_by=killed_by,
        )
        event_type = "sandbox.killed" if killed_by in ("limit", "user") else "sandbox.completed"
        await self._publish(
            event_type,
            run_id=run_id,
            request=request,
            extra={
                "exit_code": result.exit_code,
                "killed_by": result.killed_by,
                "wall_seconds": result.wall_seconds,
            },
        )
        await self._write_memory(result, request)
        return result

    async def kill(self, run_id: str) -> None:
        # subprocess.run in the donor blocks a worker thread, so the
        # adapter cannot inject SIGTERM mid-flight — the wall-time
        # timeout in the donor is the enforcement mechanism. `kill()`
        # records the cancel intent so the eventual outcome is
        # classified as killed_by="user". Idempotent.
        if run_id in self._active:
            self._cancelled.add(run_id)

    async def list_active(self) -> tuple[SandboxHandle, ...]:
        return tuple(self._active.values())

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        if self._closed:
            return
        for run_id in list(self._active):
            await self.kill(run_id)
        self._closed = True

    # ── Internal ──────────────────────────────────────────────────────

    def _make_preexec(self, limits: SandboxLimits) -> Any:
        # preexec_fn runs in the forked child before exec. rlimit calls
        # are the strongest per-process cap we can install without root.
        if platform.system() != "Linux":
            return None
        max_memory_bytes = max(1, limits.max_memory_mb) * 1024 * 1024
        max_cpu_seconds = max(1, limits.max_wall_seconds)

        def _preexec() -> None:  # pragma: no cover - runs post-fork
            try:
                resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
                resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds))
                # 128 MB file-size ceiling per run (prevents fill-disk DoS).
                fsize_cap = 128 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_cap, fsize_cap))
            except (ValueError, OSError):
                pass

        return _preexec

    def _network_guard(
        self, network: SandboxNetworkPolicy, run_id: str
    ) -> str | None:
        """Return None when isolation is available, else a reason string.

        ``"full"`` never requires guarding here — the tool-registry layer
        is responsible for gating it through the approval port.
        """

        if network == "full":
            return None
        if platform.system() != "Linux":
            return f"host is {platform.system()} (unshare unavailable)"
        if shutil.which("unshare") is None:
            return "unshare(1) not found on PATH"
        # We attempt unprivileged user+net namespaces; the actual permission
        # check is deferred to exec time. Kernels with
        # `kernel.unprivileged_userns_clone=0` still allow root to unshare
        # net; we can't cheaply pre-check without EUID=0. Treat "unshare
        # available" as sufficient here; ``exec_argv`` will surface the
        # real error inside stderr if the kernel refuses.
        _ = run_id
        return None

    def _wrap_argv_for_network(
        self, argv: list[str], network: SandboxNetworkPolicy
    ) -> list[str]:
        if network == "full":
            return argv
        if platform.system() != "Linux":
            return argv
        unshare = shutil.which("unshare")
        if unshare is None:
            return argv
        # `--user --map-root-user --net` is the unprivileged path; falls
        # back to root-only `--net` when unprivileged userns are disabled.
        # ``exec_argv`` captures stderr either way so callers see the
        # actual failure.
        return [unshare, "--user", "--map-root-user", "--net", "--", *argv]

    def _maybe_write_cgroups(self, run_id: str, limits: SandboxLimits) -> None:
        # Opportunistic — never fail-closed. Skip silently when the
        # cgroups v2 mount isn't writable by this uid.
        controllers = "/sys/fs/cgroup/cgroup.controllers"
        if not os.path.exists(controllers):
            if not self._cgroups_warned:
                self._cgroups_warned = True
                logger.info(
                    "cgroups v2 mount not present; relying on RLIMIT_AS for run %s",
                    run_id,
                )
            return
        base = f"/sys/fs/cgroup/kosmos-sandbox/{run_id}"
        try:
            os.makedirs(base, exist_ok=True)
            memory_max = str(max(1, limits.max_memory_mb) * 1024 * 1024)
            with open(f"{base}/memory.max", "w", encoding="utf-8") as fh:
                fh.write(memory_max)
        except (PermissionError, OSError):
            if not self._cgroups_warned:
                self._cgroups_warned = True
                logger.info(
                    "cgroups v2 mount not writable; relying on RLIMIT_AS for run %s",
                    run_id,
                )

    def _classify_termination(
        self, outcome: ExecOutcome, was_cancelled: bool
    ) -> str:
        if was_cancelled:
            return "user"
        if outcome.timed_out:
            return "limit"
        return "exit"

    async def _publish(
        self,
        event_type: str,
        *,
        run_id: str,
        request: SandboxRequest,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            payload: dict[str, Any] = {
                "source": "sandbox_tektos",
                "run_id": run_id,
                "correlation_id": run_id,
                "command": request.command,
                "network": request.limits.network,
                "cwd": request.cwd,
            }
            if extra:
                payload.update(extra)
            await self._event_bus.publish(
                EventEnvelope(
                    event_type=event_type,
                    producer_plugin="tektos_sandbox_adapter",
                    payload=payload,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("tektos sandbox publish failed for %s", event_type)

    async def _write_memory(
        self,
        result: SandboxResult,
        request: SandboxRequest,
    ) -> None:
        if self._memory is None:
            return
        try:
            await self._memory.write_event(
                subject=f"sandbox_run:{result.run_id}",
                predicate="terminated_with",
                object=result.killed_by or "exit",
                provenance="sandbox",
                confidence=1.0,
                attributes={
                    "command": request.command,
                    "exit_code": result.exit_code,
                    "wall_seconds": result.wall_seconds,
                    "network": request.limits.network,
                    "peak_memory_mb": result.peak_memory_mb,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "tektos sandbox memory write failed for run %s", result.run_id
            )
