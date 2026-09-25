"""Self-Repair Engine — ADR-141 R5 (full donor port).

Donor: ``tektos.self_repair.engine`` (tektos-ultima-v1, 466 lines).
Ported verbatim under the ADR-141 functionality-preservation constraint —
the user-mandated "FULL donor execution semantics (no approval gate)":

* The engine boots at kernel start (donor ``main.py:980-984`` did the same)
  and runs the background monitoring loop — ``check_health`` on an
  interval → snapshot → threshold → repair trigger.
* ``repair_threat`` executes the full lifecycle (diagnose → repair →
  verify → learn) directly — no approval gate, matching the donor.
* The donor never called ``set_effector`` — the built-in strategies and
  workflows are *simulated* (ctx mutation + ``[simulated]`` marker) with a
  loud warning, hard-failing only under ``TEKTOS_SELF_REPAIR_REQUIRE_REAL``.
  That donor behavior is preserved exactly.

Only the intra-package imports change (siblings + vendored models,
ADR-141 R2/R3/R4). Everything else is verbatim.

Architecture (donor docstring, preserved):
    ┌─────────────────────────────────────────────────────────────┐
    │                    SelfRepairEngine                        │
    │  HealthMonitor ─▶ RepairStrategyRegistry ─▶ HealingWorkflows│
    │         │                    │                            │
    │         ▼                    ▼                            ▼
    │  EffectivenessTracker ◀─ RepairRecord ─▶ Immune Memory    │
    │                                                             │
    │  VSM Mapping:                                               │
    │    S3 (Control): Repair orchestrator, escalation            │
    │    S4 (Intelligence): Adaptive strategies, learning         │
    │    S5 (Identity): Repair must never degrade core identity   │
    └─────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any

from .effectiveness import (
    get_effectiveness_tracker,
    reset_effectiveness_tracker,
)
from .health_monitor import get_health_monitor, reset_health_monitor
from .models import (
    DegradationLevel,
    DegradationPlan,
    HealthSnapshot,
    RepairRecord,
    RepairResult,
    RepairStatus,
    RepairStrategy,
)

log = logging.getLogger(__name__)


class _EscalateOnlyRegistry:
    """Fallback strategy surface when no agent policy is injected (ADR-142).

    The substrate must not import the Tektos plugin (ADR-007), so the
    built-in 8-strategy / 6-workflow threat model is *injected* at boot
    by the composition root. When it is not wired, this fallback keeps the
    full lifecycle running but degrades to honest escalation — the strategy
    phase returns ``ESCALATE_TO_USER`` and ``list_strategies()`` is empty,
    so ``get_status()`` reports ``strategies_registered=0`` (the same
    "unwired" convention as ADR-141 T1). No fabricated repairs.
    """

    async def repair(self, category: str, severity: int, ctx: dict[str, Any]):
        return RepairResult(
            success=False,
            strategy=RepairStrategy.ESCALATE_TO_USER,
            actions_taken=[],
            verification_passed=False,
            error=f"No repair policy wired for category={category} (ADR-142)",
        )

    def list_strategies(self) -> list[dict[str, Any]]:
        return []


class SelfRepairEngine:
    """Main orchestrator for Tektos's self-repair system.

    Coordinates the full repair lifecycle:
        1. Health monitoring (continuous)
        2. Threat detection (via immune system integration)
        3. Diagnosis (root cause analysis)
        4. Repair execution (strategy + workflow)
        5. Verification (did it work?)
        6. Learning (effectiveness tracking + immune memory)

    The engine runs a background monitoring loop that automatically
    triggers repairs when health drops below thresholds.
    """

    def __init__(
        self,
        check_interval: float = 30.0,
        warning_threshold: float = 0.7,
        critical_threshold: float = 0.5,
        max_repair_attempts: int = 3,
        max_repair_time_seconds: float = 120.0,
        enable_workflows: bool = True,
        enable_effectiveness_tracking: bool = True,
        enable_health_monitoring: bool = True,
        strategies: Any = None,
        workflows: Any = None,
    ):
        self.check_interval = check_interval
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.max_repair_attempts = max_repair_attempts
        self.max_repair_time_seconds = max_repair_time_seconds
        self.enable_workflows = enable_workflows
        self.enable_effectiveness_tracking = enable_effectiveness_tracking
        self.enable_health_monitoring = enable_health_monitoring

        # Core components. ``strategies`` / ``workflows`` are agent-POLICY
        # surfaces injected by the composition root (ADR-142: substrate must
        # not import plugins — ADR-007). Unwired → honest degrade.
        self.strategies = strategies if strategies is not None else _EscalateOnlyRegistry()
        self.workflows = workflows if (workflows is not None and enable_workflows) else None
        self.effectiveness = get_effectiveness_tracker() if enable_effectiveness_tracking else None
        self.health_monitor = (
            get_health_monitor(
                check_interval=check_interval,
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
            )
            if enable_health_monitoring
            else None
        )

        # State
        self._running = False
        self._task: asyncio.Task | None = None
        self._repair_history: list[RepairRecord] = []
        self._start_time = time.time()

        # Callbacks
        self._on_repair_complete: list[Any] = []
        self._on_repair_failed: list[Any] = []
        self._on_degradation: list[Any] = []

    def on_repair_complete(self, callback: Any) -> None:
        """Register a callback for completed repairs."""
        self._on_repair_complete.append(callback)

    def on_repair_failed(self, callback: Any) -> None:
        """Register a callback for failed repairs."""
        self._on_repair_failed.append(callback)

    def on_degradation(self, callback: Any) -> None:
        """Register a callback for graceful degradation."""
        self._on_degradation.append(callback)

    async def start(self) -> None:
        """Start the self-repair engine."""
        self._running = True

        # Start health monitoring
        if self.health_monitor:
            await self.health_monitor.start()

        # Start background monitoring loop
        self._task = asyncio.create_task(self._monitoring_loop())
        log.info(
            "[SelfRepairEngine] Started (interval=%.1fs, workflows=%s)",
            self.check_interval,
            self.enable_workflows,
        )

    async def stop(self) -> None:
        """Stop the self-repair engine."""
        self._running = False

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        if self.health_monitor:
            await self.health_monitor.stop()

        log.info("[SelfRepairEngine] Stopped")

    async def _monitoring_loop(self) -> None:
        """Background monitoring loop.

        Periodically checks health and triggers repairs when needed.
        """
        while self._running:
            try:
                # Skip health check if monitor is disabled
                if self.health_monitor:
                    await self.health_monitor.check_health()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("[SelfRepairEngine] Monitoring loop error: %s", e)
                await asyncio.sleep(self.check_interval)

    async def repair_threat(
        self,
        threat_category: str,
        threat_severity: int,
        ctx: dict[str, Any],
    ) -> RepairRecord:
        """Execute the full repair lifecycle for a threat.

        This is the main entry point for triggering repairs.
        It runs: diagnose → repair → verify → learn

        Args:
            threat_category: Category of the threat (e.g., "resource_exhaustion")
            threat_severity: Severity level (0=LOW, 1=MEDIUM, 2=HIGH, 3=CRITICAL)
            ctx: Context dict with system state (GPU temp, VRAM, etc.)

        Returns:
            RepairRecord with full details of the repair attempt
        """
        record_id = f"repair_{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        record = RepairRecord(
            record_id=record_id,
            threat_category=threat_category,
            threat_severity=str(threat_severity),
            description=f"Repair initiated for {threat_category} (severity={threat_severity})",
            status=RepairStatus.PENDING,
        )

        log.info(
            "[SelfRepairEngine] Starting repair: %s (severity=%s)", threat_category, threat_severity
        )

        # Phase 1: Diagnosis
        record.status = RepairStatus.DIAGNOSING
        diag_start = time.time()

        # Try workflow first (if enabled)
        workflow_result = None
        if self.workflows:
            workflow_result = await self.workflows.run(threat_category, threat_severity, ctx)

        # Then try strategy
        strategy_result = await self.strategies.repair(threat_category, threat_severity, ctx)

        diag_elapsed = time.time() - diag_start
        record.time_to_diagnose_seconds = diag_elapsed
        record.diagnosis = ctx.get("diagnosis", "No diagnosis available")

        # Phase 2: Repair
        record.status = RepairStatus.REPAIRING
        repair_start = time.time()

        # Use workflow result if available, otherwise strategy result
        repair_result = workflow_result or strategy_result

        # If workflow failed, try strategy as fallback
        if repair_result and not repair_result.success and self.strategies:
            log.info("[SelfRepairEngine] Workflow failed, trying strategy fallback")
            repair_result = await self.strategies.repair(threat_category, threat_severity, ctx)

        # If still failed, apply degradation
        if repair_result and not repair_result.success:
            degradation = await self._apply_degradation(threat_category, threat_severity, ctx)
            record.degradation_applied = degradation.level
            record.repair_actions.append(f"Applied degradation: {degradation.level.value}")

            for cb in self._on_degradation:
                try:
                    await cb(degradation) if asyncio.iscoroutinefunction(cb) else cb(degradation)
                except Exception as e:
                    log.error("[SelfRepairEngine] Degradation callback error: %s", e)

        repair_elapsed = time.time() - repair_start
        record.time_to_repair_seconds = repair_elapsed
        record.strategy_used = repair_result.strategy if repair_result else None
        record.repair_actions = repair_result.actions_taken if repair_result else []

        # Phase 3: Verification
        record.status = RepairStatus.VERIFYING
        verify_start = time.time()

        if repair_result:
            # Try to verify using the strategy instance if available
            verify_passed = repair_result.verification_passed
            verify_details = repair_result.verification_details
            record.verification_passed = verify_passed
            record.verification_details = verify_details
        else:
            record.verification_passed = False
            record.verification_details = "No repair executed"

        verify_elapsed = time.time() - verify_start
        record.time_to_verify_seconds = verify_elapsed

        # Phase 4: Finalize
        record.total_time_seconds = time.time() - start_time
        record.completed_at = record.completed_at or time.time()

        if record.verification_passed:
            record.status = RepairStatus.COMPLETED
            log.info(
                "[SelfRepairEngine] Repair completed: %s (%.1fs)",
                record_id,
                record.total_time_seconds,
            )

            # Record effectiveness
            if self.effectiveness:
                self.effectiveness.record_success(record)

            for cb in self._on_repair_complete:
                try:
                    await cb(record) if asyncio.iscoroutinefunction(cb) else cb(record)
                except Exception as e:
                    log.error("[SelfRepairEngine] Complete callback error: %s", e)

        elif record.degradation_applied != DegradationLevel.NONE:
            record.status = RepairStatus.DEGRADED
            log.warning(
                "[SelfRepairEngine] Repair degraded: %s → %s",
                record_id,
                record.degradation_applied.value,
            )

            if self.effectiveness:
                self.effectiveness.record_degradation(record)

        else:
            record.status = RepairStatus.FAILED
            record.error = repair_result.error if repair_result else "No repair result"
            log.error("[SelfRepairEngine] Repair failed: %s — %s", record_id, record.error)

            if self.effectiveness:
                self.effectiveness.record_failure(record)

            for cb in self._on_repair_failed:
                try:
                    await cb(record) if asyncio.iscoroutinefunction(cb) else cb(record)
                except Exception as e:
                    log.error("[SelfRepairEngine] Failed callback error: %s", e)

        # Store record
        self._repair_history.append(record)

        return record

    async def _apply_degradation(
        self,
        category: str,
        severity: int,
        ctx: dict[str, Any],
    ) -> DegradationPlan:
        """Apply graceful degradation when full repair fails.

        Determines the appropriate degradation level based on severity
        and applies the minimum viable configuration.
        """
        if severity >= 3:  # CRITICAL
            level = DegradationLevel.EMERGENCY
            disabled = ["self_improvement", "skill_generation", "long_running_tasks"]
            fallback = ["fallback_model", "minimal_context"]
            message = "EMERGENCY: System degraded to bare minimum. Admin notification sent."
        elif severity >= 2:  # HIGH
            level = DegradationLevel.MINIMAL
            disabled = ["self_improvement", "skill_generation"]
            fallback = ["fallback_model"]
            message = "System degraded to minimal mode. Some features disabled."
        else:  # MEDIUM
            level = DegradationLevel.REDUCED
            disabled = ["long_running_tasks"]
            fallback = []
            message = "System operating in reduced mode."

        plan = DegradationPlan(
            level=level,
            disabled_features=disabled,
            fallback_services=fallback,
            notification_message=message,
            estimated_recovery_time_seconds=300.0,
        )

        log.warning("[SelfRepairEngine] Applied degradation: %s", level.value)
        return plan

    async def manual_health_check(
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
    ) -> HealthSnapshot:
        """Perform a manual health check and return a snapshot.

        This is used by the immune system to feed health data
        into the self-repair engine.
        """
        if self.health_monitor:
            return await self.health_monitor.check_health(
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
            )
        return HealthSnapshot()

    def get_repair_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent repair history."""
        return [r.to_dict() for r in self._repair_history[-limit:]]

    def get_status(self) -> dict[str, Any]:
        """Get current status of the self-repair engine."""
        uptime = time.time() - self._start_time
        status = {
            "running": self._running,
            "uptime_seconds": round(uptime, 1),
            "total_repairs": len(self._repair_history),
            "completed_repairs": sum(
                1 for r in self._repair_history if r.status == RepairStatus.COMPLETED
            ),
            "failed_repairs": sum(
                1 for r in self._repair_history if r.status == RepairStatus.FAILED
            ),
            "degraded_repairs": sum(
                1 for r in self._repair_history if r.status == RepairStatus.DEGRADED
            ),
            "strategies_registered": len(self.strategies.list_strategies()),
            "workflows_registered": len(self.workflows.list_workflows()) if self.workflows else 0,
        }

        if self.effectiveness:
            status["effectiveness"] = self.effectiveness.get_stats()

        if self.health_monitor:
            latest = self.health_monitor.get_latest()
            if latest:
                status["latest_health"] = latest.to_dict()
                status["health_trend"] = self.health_monitor.get_trend()

        return status

    def to_memory_entry(self) -> dict[str, Any]:
        """Convert to memory entry for self-improvement loop."""
        return {
            "self_repair_status": self.get_status(),
            "effectiveness": self.effectiveness.to_memory_entry() if self.effectiveness else {},
        }


# Singleton
_engine: SelfRepairEngine | None = None


def get_self_repair_engine(**kwargs: Any) -> SelfRepairEngine:
    """Get or create the global self-repair engine."""
    global _engine
    if _engine is None:
        _engine = SelfRepairEngine(**kwargs)
    return _engine


def reset_self_repair_engine() -> None:
    """Reset the global self-repair engine (for testing).

    Substrate-only reset (ADR-142): the engine + substrate singletons.
    The Tektos *plugin's* strategy-registry / healing-workflow singletons
    are plugin state — tests that wire them (and may import the plugin)
    reset them via ``plugins.tektos.self_repair.strategies.reset_strategy_registry``
    and ``plugins.tektos.self_repair.workflows.reset_healing_workflows``.
    The substrate must not import the plugin (ADR-007).
    """
    global _engine
    _engine = None
    reset_effectiveness_tracker()
    reset_health_monitor()
