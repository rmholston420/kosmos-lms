"""Health Monitor — ADR-141 R4 (full donor port).

Donor: ``tektos.self_repair.health_monitor`` (tektos-ultima-v1, 261 lines).
Ported verbatim under the ADR-141 functionality-preservation constraint:
the donor self-repair engine runs a continuous health-monitoring loop
(``check_health`` on an interval → snapshot → threshold → callback) and the
UI self-repair tab's health data flows from it. The only change vs the donor
is the import target for :class:`HealthSnapshot` (vendored, ADR-141 R2).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from kernel.reliability.models import HealthSnapshot

log = logging.getLogger(__name__)


class HealthMonitor:
    """Continuous health monitoring with repair-triggering thresholds.

    Runs a background monitoring loop that:
        1. Collects health metrics
        2. Computes health score
        3. Triggers repairs when thresholds are breached
        4. Records health snapshots for trend analysis
    """

    def __init__(
        self,
        check_interval: float = 30.0,
        warning_threshold: float = 0.7,
        critical_threshold: float = 0.5,
        max_snapshots: int = 1000,
    ):
        self.check_interval = check_interval
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.max_snapshots = max_snapshots

        self._running = False
        self._task: asyncio.Task | None = None
        self._snapshots: list[HealthSnapshot] = []
        self._start_time = time.time()

        # Callbacks for health state changes
        self._on_warning: list[Any] = []
        self._on_critical: list[Any] = []

    def on_warning(self, callback: Any) -> None:
        """Register a callback for warning-level health."""
        self._on_warning.append(callback)

    def on_critical(self, callback: Any) -> None:
        """Register a callback for critical-level health."""
        self._on_critical.append(callback)

    async def start(self) -> None:
        """Start the monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        log.info("[HealthMonitor] Started (interval=%.1fs)", self.check_interval)

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        log.info("[HealthMonitor] Stopped")

    async def _monitoring_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                await self.check_health()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("[HealthMonitor] Monitoring loop error: %s", e)
                await asyncio.sleep(self.check_interval)

    async def check_health(
        self,
        gpu_score: float = 1.0,
        context_score: float = 1.0,
        loop_safety_score: float = 1.0,
        inference_score: float = 1.0,
        threat_level_score: float = 1.0,
        active_threats: int = 0,
        resolved_threats: int = 0,
        pending_repairs: int = 0,
        successful_repairs_24h: int = 0,
        failed_repairs_24h: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> HealthSnapshot:
        """Check system health and return a snapshot.

        Computes a weighted health score and triggers repairs
        when thresholds are breached.
        """
        # Weighted average
        weights = {
            "gpu": 0.25,
            "context": 0.20,
            "loop_safety": 0.15,
            "inference": 0.20,
            "threat_level": 0.20,
        }

        overall = (
            gpu_score * weights["gpu"]
            + context_score * weights["context"]
            + loop_safety_score * weights["loop_safety"]
            + inference_score * weights["inference"]
            + threat_level_score * weights["threat_level"]
        )

        # Apply threat penalty
        if active_threats > 0:
            threat_penalty = min(active_threats * 0.10, 0.5)
            overall *= 1.0 - threat_penalty

        # Determine status
        if overall >= self.warning_threshold:
            status = "healthy"
        elif overall >= self.critical_threshold:
            status = "warning"
        else:
            status = "critical"

        snapshot = HealthSnapshot(
            overall_score=overall,
            status=status,
            gpu_score=gpu_score,
            context_score=context_score,
            loop_safety_score=loop_safety_score,
            inference_score=inference_score,
            threat_level_score=threat_level_score,
            active_threats=active_threats,
            resolved_threats=resolved_threats,
            pending_repairs=pending_repairs,
            successful_repairs_24h=successful_repairs_24h,
            failed_repairs_24h=failed_repairs_24h,
            uptime_seconds=time.time() - self._start_time,
            metadata=metadata or {},
        )

        # Record snapshot
        self._snapshots.append(snapshot)
        if len(self._snapshots) > self.max_snapshots:
            self._snapshots = self._snapshots[-self.max_snapshots :]

        # Trigger callbacks
        if status == "warning":
            for cb in self._on_warning:
                try:
                    await cb(snapshot) if asyncio.iscoroutinefunction(cb) else cb(snapshot)
                except Exception as e:
                    log.error("[HealthMonitor] Warning callback error: %s", e)

        elif status == "critical":
            for cb in self._on_critical:
                try:
                    await cb(snapshot) if asyncio.iscoroutinefunction(cb) else cb(snapshot)
                except Exception as e:
                    log.error("[HealthMonitor] Critical callback error: %s", e)

        log.info(
            "[HealthMonitor] Health: %.3f (%s) — GPU=%.2f Context=%.2f Loop=%.2f Inference=%.2f Threat=%.2f",
            overall,
            status,
            gpu_score,
            context_score,
            loop_safety_score,
            inference_score,
            threat_level_score,
        )

        return snapshot

    def get_trend(self, window_minutes: int = 60) -> dict[str, Any]:
        """Get health trend over a time window."""
        cutoff = time.time() - (window_minutes * 60)
        recent = [s for s in self._snapshots if s.timestamp >= cutoff]

        if not recent:
            return {"trend": "unknown", "scores": []}

        scores = [s.overall_score for s in recent]
        avg = sum(scores) / len(scores)
        min_score = min(scores)
        max_score = max(scores)

        # Determine trend direction
        if len(scores) >= 2:
            first_half = scores[: len(scores) // 2]
            second_half = scores[len(scores) // 2 :]
            first_avg = sum(first_half) / len(first_half)
            second_avg = sum(second_half) / len(second_half)
            if second_avg > first_avg + 0.05:
                trend = "improving"
            elif second_avg < first_avg - 0.05:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "trend": trend,
            "average": round(avg, 3),
            "min": round(min_score, 3),
            "max": round(max_score, 3),
            "sample_count": len(scores),
            "window_minutes": window_minutes,
        }

    def get_latest(self) -> HealthSnapshot | None:
        """Get the most recent health snapshot."""
        return self._snapshots[-1] if self._snapshots else None

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent health history."""
        return [s.to_dict() for s in self._snapshots[-limit:]]


# Singleton
_monitor: HealthMonitor | None = None


def get_health_monitor(
    check_interval: float = 30.0,
    warning_threshold: float = 0.7,
    critical_threshold: float = 0.5,
) -> HealthMonitor:
    """Get or create the global health monitor."""
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor(
            check_interval=check_interval,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
        )
    return _monitor


def reset_health_monitor() -> None:
    """Reset the global health monitor (for testing)."""
    global _monitor
    _monitor = None
