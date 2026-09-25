"""Kernel learning driver (ADR-143, T3 — queue + env-gated background cycle).

Donor-faithful port of the driver scaffolding in tektos-ultima-v1
``main.py:1224-1288``: an in-process prompt queue (populated by
``POST /api/self_improvement/enqueue``) watched by a background task that
runs one loop cycle per queued prompt at a fixed interval.

Donor semantics, preserved:
* ``TEKTOS_SELF_IMPROVEMENT_ENABLED`` (default ``false``) gates the
  background task — off by default so tests/cold boots don't burn cycles.
* ``TEKTOS_SELF_IMPROVEMENT_INTERVAL`` (default ``1800`` s) is the watch
  period; exactly ONE prompt is popped per wake (queue drains slowly).
* The loop's ``run(prompt)`` is synchronous → driven via
  ``asyncio.to_thread`` (donor used ``_asyncio.to_thread`` identically).
* If the orchestrator failed to initialize (donor: ``None``), the task
  keeps waking and skips — honest ``orchestrator_ready: false`` status.
* An empty queue raises ``IndexError`` between check and pop → swallowed
  (donor-faithful).

DI seam (ADR-007: substrate never imports plugins): the composition root
(``kernel/app.py``) injects the Tektos Hegelian loop
(``plugins.tektos.self_improve.loop``) via :meth:`set_loop`. The driver is
loop-agnostic — it only needs an object with ``run(prompt) -> cycle`` and
optional ``get_loop_health() -> dict`` / ``clear_cycles()`` / ``__len__``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from typing import Any, Optional

logger = logging.getLogger(__name__)

ENABLED_ENV = "TEKTOS_SELF_IMPROVEMENT_ENABLED"
INTERVAL_ENV = "TEKTOS_SELF_IMPROVEMENT_INTERVAL"
DEFAULT_INTERVAL = 1800.0  # 30 minutes (donor default)


class LearningDriver:
    """Queue + env-gated background driver for self-improvement cycles.

    The substrate half of the T3 self-improvement port: it owns the queue
    and the lifecycle of the background task, and delegates the actual
    cycle work to an injected loop (Tektos policy — S4).
    """

    def __init__(
        self,
        loop: Optional[Any] = None,
        enabled: Optional[bool] = None,
        interval: Optional[float] = None,
        max_queue: int = 100,
    ) -> None:
        self._loop = loop
        self._queue: deque[str] = deque()
        self._max_queue = max_queue
        self._enabled = (
            os.getenv(ENABLED_ENV, "false").lower() == "true"
            if enabled is None
            else enabled
        )
        self._interval = (
            float(os.getenv(INTERVAL_ENV, str(DEFAULT_INTERVAL)))
            if interval is None
            else float(interval)
        )
        self._task: Optional[asyncio.Task] = None
        # Cycle history — the last N completed cycles' summary dicts
        # (mirrors the donor loop's get_loop_health recent_cycles).
        self._cycle_log: deque[dict[str, Any]] = deque(maxlen=50)

    # ── DI seam ──────────────────────────────────────────────────────────

    def set_loop(self, loop: Any) -> None:
        """Inject the Hegelian loop (composition root, boot time)."""
        self._loop = loop

    # ── queue ────────────────────────────────────────────────────────────

    def enqueue(self, prompt: str) -> int:
        """Queue a prompt for a future cycle. Returns the queue length.

        Donor-faithful: the donor appended to ``app.state.self_improvement_queue``
        unboundedly; we cap at ``max_queue`` (drop-oldest) as a safety
        net — a runaway producer cannot OOM the kernel. The drop is logged.
        """
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("prompt must be a non-empty string")
        if len(self._queue) >= self._max_queue:
            dropped = self._queue.popleft()
            logger.warning(
                "[LEARNING-DRIVER] queue full (%d); dropping oldest: %s",
                self._max_queue,
                dropped[:80],
            )
        self._queue.append(prompt)
        return len(self._queue)

    def __len__(self) -> int:
        return len(self._queue)

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background task (only when enabled AND loop wired).

        Donor semantics: the task is created only when the env gate is on
        AND the orchestrator is not None. When disabled, nothing runs —
        the queue still accepts prompts (they simply wait; enabling later
        via :meth:`enable` starts the task).
        """
        if self._task is not None and not self._task.done():
            return
        if not self._enabled:
            logger.info(
                "[LEARNING-DRIVER] disabled (%s) — queue only; no cycles",
                ENABLED_ENV,
            )
            return
        if self._loop is None:
            logger.warning(
                "[LEARNING-DRIVER] enabled but no loop wired — "
                "cycles will be skipped until a loop is injected"
            )
            # Donor: task still created (it no-ops per wake). We do the
            # same so status reflects "enabled but not ready".
        self._task = asyncio.get_running_loop().create_task(
            self._driver(), name="tektos-self-improvement-driver"
        )
        logger.info(
            "[LEARNING-DRIVER] started (interval=%.0fs, loop_ready=%s)",
            self._interval,
            self._loop is not None,
        )

    async def stop(self) -> None:
        """Cancel the background task (kernel shutdown)."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    def enable(self) -> None:
        """Runtime opt-in (the env gate is read at construction)."""
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def loop_ready(self) -> bool:
        return self._loop is not None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── background task (donor _self_improvement_driver) ─────────────────

    async def _driver(self) -> None:
        """Pull one queued prompt per wake and run a cycle in a thread."""
        while True:
            await asyncio.sleep(self._interval)
            if self._loop is None:
                continue
            try:
                prompt = self._queue[0]
                self._queue.popleft()
            except IndexError:
                continue  # queue drained between check and pop (donor-faithful)
            try:
                cycle = await asyncio.to_thread(self._loop.run, prompt)
                summary = self._summarize_cycle(cycle)
                self._cycle_log.append(summary)
                logger.info(
                    "[LEARNING-DRIVER] cycle complete: id=%s status=%s",
                    summary.get("id", "?"),
                    summary.get("status", "?"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[LEARNING-DRIVER] cycle failed: %s", exc)
                self._cycle_log.append(
                    {"id": "?", "status": "failed", "error": str(exc)[:200]}
                )

    @staticmethod
    def _summarize_cycle(cycle: Any) -> dict[str, Any]:
        return {
            "id": getattr(cycle, "cycle_id", getattr(cycle, "id", "?")),
            "status": getattr(cycle, "status", "?"),
            "prompt": getattr(cycle, "prompt", None),
            "syntheses": len(getattr(cycle, "syntheses", []) or []),
            "experiences": len(getattr(cycle, "experience_stored", []) or []),
            "duration_seconds": getattr(cycle, "duration_seconds", None),
            "error": getattr(cycle, "error", None),
        }

    # ── status (feeds /api/self_improvement/status) ──────────────────────

    def get_status(self) -> dict[str, Any]:
        """Donor ``/self_improvement/status`` shape, kernel-adapted.

        Donor fields preserved: ``enabled``, ``interval_seconds``,
        ``queue_length``, ``orchestrator_ready`` + recent cycles; loop
        health (when wired) is merged under ``loop_health``.
        """
        status: dict[str, Any] = {
            "enabled": self._enabled,
            "driver_running": self.running,
            "interval_seconds": self._interval,
            "queue_length": len(self._queue),
            "queued_prompts": list(self._queue),
            "orchestrator_ready": self._loop is not None,
            "recent_cycles": list(self._cycle_log)[-5:],
        }
        if self._loop is not None:
            health = getattr(self._loop, "get_loop_health", None)
            if callable(health):
                try:
                    status["loop_health"] = health()
                except Exception:  # noqa: BLE001
                    logger.exception("[LEARNING-DRIVER] loop health failed")
            count = getattr(self._loop, "__len__", None)
            if callable(count):
                status["loop_cycles"] = count()
        return status

    # ── manual trigger (donor had none via queue only; keep minimal) ────

    async def run_cycle_now(self, prompt: str) -> dict[str, Any]:
        """Synchronous trigger: run one cycle for ``prompt`` immediately.

        The donor had no manual-trigger route (queue only), but the
        kernel's ``/api/self_improvement/enqueue`` can accept
        ``run_now=true`` for operator use. Degrades honestly when no
        loop is wired or the gate is off (the cycle simply cannot run).
        """
        if self._loop is None:
            return {
                "status": "skipped",
                "reason": "no loop wired (orchestrator_ready=false)",
            }
        cycle = await asyncio.to_thread(self._loop.run, prompt)
        summary = self._summarize_cycle(cycle)
        self._cycle_log.append(summary)
        return summary


# ── Module-level singleton (mirrors kernel.reliability) ─────────────────────

_driver: LearningDriver | None = None


def get_learning_driver(**kwargs: Any) -> LearningDriver:
    """Get or create the global learning driver (composition-root seam)."""
    global _driver
    if _driver is None:
        _driver = LearningDriver(**kwargs)
    return _driver


def reset_learning_driver() -> None:
    """Reset the global learning driver (for testing)."""
    global _driver
    _driver = None


__all__ = [
    "LearningDriver",
    "get_learning_driver",
    "reset_learning_driver",
    "ENABLED_ENV",
    "INTERVAL_ENV",
]
