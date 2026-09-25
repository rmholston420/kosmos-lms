"""Self-Healing Workflows — ADR-141 R4 (full donor port).

Donor: ``tektos.self_repair.workflows`` (tektos-ultima-v1, 470 lines).
Ported verbatim under the ADR-141 functionality-preservation constraint:
the engine consults :func:`get_healing_workflows` first (complex multi-step
playbooks before single-shot strategies). Built-in workflows are
*simulated* by default — they mutate the passed-in ``ctx`` dict and carry
the ``[simulated]`` marker, same donor semantics. Only the import target
changes (vendored models, ADR-141 R2).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from kernel.reliability.models import (
    RepairResult,
    RepairStrategy,
)

log = logging.getLogger(__name__)


class HealingWorkflow:
    """A multi-step repair workflow.

    Workflows handle complex scenarios that require coordinated
    multi-step repair actions. Like the strategies (ADR-141 R3),
    built-in workflows are *simulated* by default — they only mutate the
    passed-in ``ctx`` dict. See ``TEKTOS_SELF_REPAIR_REQUIRE_REAL``.
    """

    name: str = "base"
    triggers: list[str] = []  # Threat categories that trigger this workflow
    min_severity: int = 1
    simulation: bool = True

    async def can_run(self, category: str, severity: int) -> bool:
        return category in self.triggers and severity >= self.min_severity

    async def run(self, ctx: dict[str, Any]) -> RepairResult:
        """Execute the full workflow."""
        raise NotImplementedError


class GPUThermalCrisisWorkflow(HealingWorkflow):
    """Workflow for GPU thermal crisis.

    Multi-step response to GPU temperature emergencies:
        1. Immediate: Throttle all AI workloads
        2. Short-term: Reduce context window, switch to smaller model
        3. Long-term: Maximize fan speed, alert admin
        4. Fallback: If still critical, halt all inference
    """

    name = "gpu_thermal_crisis"
    triggers = ["resource_exhaustion"]
    min_severity = 2  # HIGH and above

    async def can_run(self, category: str, severity: int) -> bool:
        return category in self.triggers and severity >= self.min_severity

    async def run(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []
        temp = ctx.get("gpu_temperature", 0)

        # Step 1: Immediate throttle
        actions.append("Step 1: Throttling all AI workloads")
        ctx["throttle_all"] = True
        ctx["gpu_temperature"] = max(45.0, temp - 25.0)

        # Step 2: Reduce context window
        if temp >= 80:
            actions.append("Step 2: Reducing context window to minimum")
            ctx["context_reduction"] = True
            ctx["min_context"] = True
            ctx["gpu_temperature"] = max(45.0, ctx["gpu_temperature"] - 10.0)

        # Step 3: Switch to smaller model
        if temp >= 80:
            actions.append("Step 3: Switching to smaller/faster model")
            ctx["switch_to_fallback"] = True
            ctx["gpu_temperature"] = max(45.0, ctx["gpu_temperature"] - 15.0)

        # Step 4: Alert admin
        actions.append("Step 4: Alerting admin of thermal crisis")
        ctx["alert_admin"] = True
        ctx["thermal_crisis"] = True

        # Verify
        success = ctx["gpu_temperature"] < 70
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.THROTTLE_WORKLOAD,
            actions_taken=actions,
            verification_passed=success,
            verification_details=f"Post-workflow: temp={temp:.1f}°C",
            time_seconds=elapsed,
        )


class ContextCollapseWorkflow(HealingWorkflow):
    """Workflow for context collapse.

    Multi-step response to context overflow:
        1. Emergency: Compress to last N messages
        2. Cleanup: Remove low-priority constraints
        3. Reset: If still full, reset session
        4. Fallback: If still failing, degrade gracefully
    """

    name = "context_collapse"
    triggers = ["context_collapse", "context_overflow"]
    min_severity = 1

    async def run(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []
        tokens = ctx.get("context_tokens", 0)
        max_tokens = ctx.get("context_max_tokens", 128000)

        if max_tokens > 0:
            pct = tokens / max_tokens

            # Step 1: Emergency compression
            if pct >= 0.95:
                actions.append("Step 1: Emergency compression — last 5 messages only")
                ctx["keep_last_n"] = 5
                ctx["compress_aggressive"] = True
            elif pct >= 0.85:
                actions.append("Step 1: Compression — last 15 messages")
                ctx["keep_last_n"] = 15
                ctx["compress_aggressive"] = False

            # Step 2: Remove low-priority constraints
            actions.append("Step 2: Removing low-priority constraints")
            ctx["remove_low_priority"] = True

            # Step 3: If still full, reset session
            if pct >= 0.95:
                actions.append("Step 3: Resetting session to clean state")
                ctx["reset_session"] = True

        success = True
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.COMPRESS_CONTEXT,
            actions_taken=actions,
            verification_passed=True,
            verification_details=f"Context compressed, last {ctx.get('keep_last_n', 15)} messages kept",
            time_seconds=elapsed,
        )


class LoopRecoveryWorkflow(HealingWorkflow):
    """Workflow for agent loop recovery.

    Multi-step response to agent loops:
        1. Immediate: Reset strategy
        2. Analysis: Identify what's causing the loop
        3. Intervention: Force new approach
        4. Escalation: If still looping, notify user
    """

    name = "loop_recovery"
    triggers = ["loop_detected", "repetition"]
    min_severity = 1

    async def run(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []
        loop_count = ctx.get("loop_count", 0)

        # Step 1: Reset strategy
        actions.append("Step 1: Resetting agent strategy")
        ctx["strategy_reset"] = True

        # Step 2: Force new approach
        actions.append("Step 2: Forcing completely new approach")
        ctx["force_new_approach"] = True
        ctx["new_strategy_id"] = f"strategy_{int(time.time())}"

        # Step 3: If still looping, escalate
        if loop_count >= 10:
            actions.append("Step 3: Escalating to user — agent stuck")
            ctx["escalate_to_user"] = True

        success = True
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.RESET_STRATEGY,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Loop recovery workflow applied",
            time_seconds=elapsed,
        )


class InfrastructureRecoveryWorkflow(HealingWorkflow):
    """Workflow for infrastructure failure recovery.

    Multi-step response to service failures:
        1. Detect which service failed
        2. Attempt restart
        3. If restart fails, switch to fallback
        4. If no fallback, degrade gracefully
    """

    name = "infrastructure_recovery"
    triggers = ["infrastructure_failure", "model_unavailable", "embedder_unavailable"]
    min_severity = 1

    async def run(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        # Step 1: Attempt restart
        if not ctx.get("model_available", True):
            actions.append("Step 1: Attempting model service restart")
            ctx["restart_model_service"] = True

        if not ctx.get("embedder_available", True):
            actions.append("Step 1: Attempting embedder service restart")
            ctx["restart_embedder_service"] = True

        # Step 2: Switch to fallback if restart fails
        if not ctx.get("model_available", True):
            actions.append("Step 2: Switching to fallback model")
            ctx["switch_to_fallback"] = True

        # Step 3: If no fallback, degrade
        if not ctx.get("model_available", True) and not ctx.get("switch_to_fallback"):
            actions.append("Step 3: No fallback available — degrading to minimal mode")
            ctx["degrade_to_minimal"] = True

        success = bool(ctx.get("model_available", True)) or bool(ctx.get("switch_to_fallback"))
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.RESTART_SERVICE,
            actions_taken=actions,
            verification_passed=bool(success),
            verification_details="Infrastructure recovery attempted",
            time_seconds=elapsed,
        )


class SelfDegradationRecoveryWorkflow(HealingWorkflow):
    """Workflow for self-degradation recovery.

    Multi-step response to self-modification failures:
        1. Rollback last modification
        2. Run self-tests
        3. If tests pass, log the bad modification
        4. If tests fail, escalate to user
    """

    name = "self_degradation_recovery"
    triggers = ["self_degradation"]
    min_severity = 2

    async def run(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        # Step 1: Rollback
        actions.append("Step 1: Rolling back last self-modification")
        ctx["rollback_self_modification"] = True

        # Step 2: Run self-tests
        actions.append("Step 2: Running self-tests")
        ctx["run_self_tests"] = True

        # Step 3: Log bad modification
        actions.append("Step 3: Logging bad modification for immune memory")
        ctx["log_bad_modification"] = True

        success = True
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.ROLLBACK_CODE,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Self-degradation recovery workflow applied",
            time_seconds=elapsed,
        )


class PromptInjectionResponseWorkflow(HealingWorkflow):
    """Workflow for prompt injection response.

    Multi-step response to injection attempts:
        1. Quarantine session
        2. Reset system prompt
        3. Log injection pattern
        4. Alert admin
    """

    name = "prompt_injection_response"
    triggers = ["prompt_injection", "secret_exposure"]
    min_severity = 1

    async def run(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        # Step 1: Quarantine
        actions.append("Step 1: Quarantining session")
        ctx["quarantine"] = True

        # Step 2: Reset prompt
        actions.append("Step 2: Resetting system prompt to baseline")
        ctx["reset_system_prompt"] = True

        # Step 3: Log pattern
        actions.append("Step 3: Logging injection pattern for immune memory")
        ctx["log_injection_pattern"] = True

        # Step 4: Alert
        actions.append("Step 4: Alerting admin")
        ctx["alert_admin"] = True

        elapsed = time.time() - start

        return RepairResult(
            success=True,
            strategy=RepairStrategy.ESCALATE_TO_USER,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Prompt injection response workflow applied",
            time_seconds=elapsed,
        )


class RepairWorkflows:
    """Registry of healing workflows.

    Manages workflow registration, lookup, and execution.
    """

    def __init__(self):
        self._workflows: list[HealingWorkflow] = []
        self._register_builtin_workflows()

    def _register_builtin_workflows(self) -> None:
        """Register all built-in healing workflows."""
        self.register(GPUThermalCrisisWorkflow())
        self.register(ContextCollapseWorkflow())
        self.register(LoopRecoveryWorkflow())
        self.register(InfrastructureRecoveryWorkflow())
        self.register(SelfDegradationRecoveryWorkflow())
        self.register(PromptInjectionResponseWorkflow())

    def register(self, workflow: HealingWorkflow) -> None:
        """Register a healing workflow."""
        self._workflows.append(workflow)
        log.info("[RepairWorkflows] Registered workflow: %s", workflow.name)

    def unregister(self, name: str) -> None:
        """Unregister a workflow by name."""
        self._workflows = [w for w in self._workflows if w.name != name]
        log.info("[RepairWorkflows] Unregistered workflow: %s", name)

    async def get_workflow(self, category: str, severity: int) -> HealingWorkflow | None:
        """Find the best workflow for a given threat category and severity."""
        for workflow in self._workflows:
            if await workflow.can_run(category, severity):
                return workflow
        return None

    async def run(
        self,
        category: str,
        severity: int,
        ctx: dict[str, Any],
    ) -> RepairResult:
        """Execute the best workflow for a threat."""
        workflow = await self.get_workflow(category, severity)
        if not workflow:
            return RepairResult(
                success=False,
                strategy=RepairStrategy.ESCALATE_TO_USER,
                actions_taken=[],
                verification_passed=False,
                error=f"No workflow found for category={category}, severity={severity}",
            )

        log.info(
            "[RepairWorkflows] Running workflow '%s' for %s (severity=%s)",
            workflow.name,
            category,
            severity,
        )

        result = await workflow.run(ctx)
        if getattr(workflow, "simulation", False):
            # Same guard as strategies.RepairStrategyRegistry.repair —
            # loud warning by default, hard failure under
            # TEKTOS_SELF_REPAIR_REQUIRE_REAL.
            import os as _os

            if _os.getenv("TEKTOS_SELF_REPAIR_REQUIRE_REAL", "").lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                raise NotImplementedError(
                    f"Healing workflow {workflow.name!r} is simulation-only "
                    f"but TEKTOS_SELF_REPAIR_REQUIRE_REAL is set."
                )
            log.warning(
                "[self_repair] workflow %s executed SIMULATED repair — no "
                "real syscall was made. ctx mutation only.",
                workflow.name,
            )
            marker = " [simulated]"
            if result.verification_details and marker not in result.verification_details:
                result.verification_details = f"{result.verification_details}{marker}"
            elif not result.verification_details:
                result.verification_details = "simulated"
        return result

    def list_workflows(self) -> list[dict[str, Any]]:
        """List all registered workflows."""
        return [
            {
                "name": w.name,
                "triggers": w.triggers,
                "min_severity": w.min_severity,
            }
            for w in self._workflows
        ]


# Singleton
_workflows: RepairWorkflows | None = None


def get_healing_workflows() -> RepairWorkflows:
    """Get or create the global healing workflows registry."""
    global _workflows
    if _workflows is None:
        _workflows = RepairWorkflows()
    return _workflows


def reset_healing_workflows() -> None:
    """Reset the global healing workflows registry (for testing)."""
    global _workflows
    _workflows = None
