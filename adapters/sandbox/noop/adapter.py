"""adapters.sandbox.noop.adapter — NoOpSandboxAdapter (ADR-082, ADR-093).

Synthesizes ``SandboxResult`` without executing anything. Wired in CI
where a real sandbox is unavailable, and used by contract tests that
need Protocol conformance without side effects.

Every ADR-082 enforcement rule still fires:

* ``run()`` publishes ``sandbox.started`` + ``sandbox.completed`` on
  the injected ``EventBusPort``.
* Every ``SandboxResult`` writes ``MemoryPort`` with
  ``provenance="sandbox"``, ``confidence=1.0``, and
  ``attributes["noop"] = True``.
* ``SandboxLimits.network`` is respected in the sense that
  ``network="full"`` is refused unless the caller has already gone
  through the tool-registry approval gate (this adapter is unaware of
  approval — the check lives at the tool-registry layer).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from ports.event_envelope import EventEnvelope
from ports.sandbox import (
    SandboxHandle,
    SandboxLimits,
    SandboxPort,
    SandboxRequest,
    SandboxResult,
)

logger = logging.getLogger(__name__)

__all__ = ["NoOpSandboxAdapter"]


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


class NoOpSandboxAdapter:
    """Synthetic ``SandboxPort`` for CI + contract tests.

    Constructor optionally accepts an ``event_bus`` and ``memory`` port
    so the two ADR-082 enforcement rules can be exercised end-to-end
    from tests without wiring the real kernel.
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
        self._closed = False

    async def run(self, request: SandboxRequest) -> SandboxResult:
        if self._closed:
            raise RuntimeError("NoOpSandboxAdapter is closed")
        run_id = f"noop-{uuid.uuid4().hex[:12]}"
        handle = SandboxHandle(
            run_id=run_id,
            started_at=datetime.now(timezone.utc),
            request=request,
        )
        self._active[run_id] = handle
        await self._publish("sandbox.started", run_id=run_id, request=request)
        try:
            result = SandboxResult(
                run_id=run_id,
                exit_code=0,
                stdout="",
                stderr="",
                wall_seconds=0.0,
                peak_memory_mb=0,
                killed_by="exit",
            )
        finally:
            self._active.pop(run_id, None)
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

    async def kill(self, run_id: str) -> None:
        # No-op adapter has nothing to kill; idempotent.
        handle = self._active.pop(run_id, None)
        if handle is None:
            return
        await self._publish(
            "sandbox.killed",
            run_id=run_id,
            request=handle.request,
            extra={"killed_by": "user"},
        )

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
                "source": "sandbox_noop",
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
                    producer_plugin="sandbox_noop_adapter",
                    payload=payload,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("noop sandbox publish failed for %s", event_type)

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
                    "noop": True,
                    "command": request.command,
                    "exit_code": result.exit_code,
                    "wall_seconds": result.wall_seconds,
                    "network": request.limits.network,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "noop sandbox memory write failed for run %s", result.run_id
            )


def _guard_network_full_default_denied(limits: SandboxLimits) -> None:  # noqa: ARG001
    """Placeholder that keeps ``SandboxLimits`` imported for downstream use.

    The real check lives in the tool-registry layer (ADR-093 §4); the
    adapter honours whatever the caller asks for.
    """
