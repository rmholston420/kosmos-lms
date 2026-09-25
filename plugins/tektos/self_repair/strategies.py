"""Self-Repair Strategies — ADR-141 R3 (full donor port).

Donor: ``tektos.self_repair.strategies`` (tektos-ultima-v1, 723 lines).
Ported verbatim under the ADR-141 functionality-preservation constraint
("Kosmos-LMS Tektos must not lose any of the functionality of
Tektos-Ultima"): the 8 built-in strategies, the ``RepairEffector``
injection interface, the ``RepairStrategyRegistry`` and the
``TEKTOS_SELF_REPAIR_REQUIRE_REAL`` strict mode all carry over unchanged.

Kosmos deltas (documented, not behavioral):
  1. Imports resolve against the kernel reliability substrate's data
     model (``kernel.reliability.models`` — ADR-142 re-home of the
     vendored donor data primitives) instead of the donor package's
     relative ``.models``.
  2. Docstring provenance header (this file).

Simulation semantics are UNCHANGED from the donor: built-in strategies
mutate ``ctx`` recovery flags (no syscalls) and the registry stamps the
result ``[simulated]`` via ``_mark_simulated``. The donor itself ships
with no ``RepairEffector`` implementation wired (``set_effector`` is
never called in the donor main.py) — so the donor's live behavior is
exactly this simulation mode, which is what "full donor execution
semantics" ratifies.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from kernel.reliability.models import (
    RepairResult,
    RepairStrategy,
)

log = logging.getLogger(__name__)


def _require_real() -> bool:
    """Return True when the strict env-var forbids simulated repairs."""
    return os.getenv("TEKTOS_SELF_REPAIR_REQUIRE_REAL", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class RepairEffector:
    """Interface for real side-effect-carrying repair actions.

    Concrete implementations should perform real syscalls: throttle the
    GPU with ``nvidia-smi -pl``, restart a systemd unit, page the on-call
    channel, or delegate to a container runtime. Injected by callers via
    :meth:`RepairStrategyRegistry.set_effector`.
    """

    async def throttle_gpu(self, target_watts: int) -> None:
        raise NotImplementedError

    async def restart_service(self, name: str) -> None:
        raise NotImplementedError

    async def free_vram(self) -> None:
        raise NotImplementedError

    async def switch_to_fallback_model(self) -> None:
        raise NotImplementedError


class BaseRepairStrategy:
    """Base class for repair strategies.

    Each strategy implements:
        - can_handle(category, severity) → bool (should I handle this?)
        - diagnose(ctx) → str (what's wrong?)
        - repair(ctx) → RepairResult (fix it)
        - verify(ctx) → bool (did it work?)
    """

    name: str = "base"
    supported_categories: list[str] = []
    min_severity: int = 0  # 0=LOW, 1=MEDIUM, 2=HIGH, 3=CRITICAL
    #: When True (default), repair() only *simulates* the fix by mutating
    #: ctx. Override to False on subclasses backed by real syscalls.
    simulation: bool = True

    def _mark_simulated(self, result: RepairResult) -> RepairResult:
        """Emit a warning and stamp the result as simulated.

        If ``TEKTOS_SELF_REPAIR_REQUIRE_REAL`` is set, raise instead.
        """
        if _require_real():
            raise NotImplementedError(
                f"Self-repair strategy {self.name!r} is simulation-only "
                f"but TEKTOS_SELF_REPAIR_REQUIRE_REAL is set. Wire a real "
                f"RepairEffector before enabling strict mode."
            )
        log.warning(
            "[self_repair] %s executed SIMULATED repair \u2014 no real syscall "
            "was made. Injected recovery flags into ctx only.",
            self.name,
        )
        extra = " [simulated]"
        if result.verification_details and extra not in result.verification_details:
            result.verification_details = f"{result.verification_details}{extra}"
        elif not result.verification_details:
            result.verification_details = "simulated"
        return result

    async def can_handle(self, category: str, severity: int) -> bool:
        return category in self.supported_categories and severity >= self.min_severity

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        return "No diagnosis available"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        return RepairResult(
            success=False,
            strategy=RepairStrategy.RESTART_SERVICE,
            actions_taken=[],
            verification_passed=False,
            error="Not implemented",
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        return False, "Verification not implemented"


class ResourceExhaustionRepair(BaseRepairStrategy):
    """Repair strategy for GPU temperature and VRAM exhaustion.

    Handles:
        - GPU temperature above warning/critical thresholds
        - VRAM usage above warning/critical thresholds
        - Token burn rate issues
    """

    name = "resource_exhaustion"
    supported_categories = ["resource_exhaustion", "vram_oom", "token_burn"]
    min_severity = 1  # MEDIUM and above

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        temp = ctx.get("gpu_temperature", 0)
        vram_pct = ctx.get("vram_pct", 0)
        parts = []
        if temp > 0:
            if temp >= 88:
                parts.append(f"GPU temperature CRITICAL at {temp:.1f}°C")
            elif temp >= 80:
                parts.append(f"GPU temperature HIGH at {temp:.1f}°C")
            elif temp >= 70:
                parts.append(f"GPU temperature WARNING at {temp:.1f}°C")
        if vram_pct > 0:
            if vram_pct >= 0.95:
                parts.append(f"VRAM critically full at {vram_pct:.0%}")
            elif vram_pct >= 0.85:
                parts.append(f"VRAM high at {vram_pct:.0%}")
        return "; ".join(parts) if parts else "Resource exhaustion detected"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []
        temp = ctx.get("gpu_temperature", 0)
        vram_pct = ctx.get("vram_pct", 0)

        # Step 1: Throttle workload if temperature is high
        if temp >= 70:
            actions.append(f"Throttling workload (temp={temp:.1f}°C)")
            ctx["context_reduction"] = True
            ctx["throttle_active"] = True
            # Simulate temperature reduction from throttling
            ctx["gpu_temperature"] = max(45.0, temp - 20.0)

        # Step 2: Free VRAM if critically full
        if vram_pct >= 0.85:
            actions.append("Freeing VRAM — reducing context window")
            ctx["vram_free"] = True
            ctx["context_reduction"] = True
            # Simulate VRAM reduction
            ctx["vram_pct"] = max(0.50, vram_pct - 0.20)

        # Step 3: Switch to smaller model if still critical
        if temp >= 80 or vram_pct >= 0.95:
            actions.append("Switching to fallback model (CPU)")
            ctx["switch_to_fallback"] = True
            # Simulate temperature drop from model switch
            ctx["gpu_temperature"] = max(45.0, ctx["gpu_temperature"] - 15.0)
            ctx["vram_pct"] = max(0.40, ctx["vram_pct"] - 0.15)

        success = ctx["gpu_temperature"] < 70 and ctx.get("vram_pct", 0.0) < 0.85
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.THROTTLE_WORKLOAD,
            actions_taken=actions,
            verification_passed=success,
            verification_details=f"Post-repair: temp={ctx['gpu_temperature']:.1f}°C, vram={ctx['vram_pct']:.0%}",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        temp = ctx.get("gpu_temperature", 0)
        vram_pct = ctx.get("vram_pct", 0)
        if temp < 70 and vram_pct < 0.85:
            return True, "Resources within safe thresholds"
        return False, f"Still elevated: temp={temp:.1f}°C, vram={vram_pct:.0%}"


class ContextOverflowRepair(BaseRepairStrategy):
    """Repair strategy for context collapse and overflow.

    Handles:
        - Context at >90% capacity
        - Unbounded message accumulation
        - Constraint loss from context bloat
    """

    name = "context_overflow"
    supported_categories = ["context_collapse", "context_overflow"]
    min_severity = 1

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        tokens = ctx.get("context_tokens", 0)
        max_tokens = ctx.get("context_max_tokens", 128000)
        if max_tokens > 0:
            pct = tokens / max_tokens
            return f"Context at {pct:.0%} capacity ({tokens}/{max_tokens} tokens)"
        return "Context overflow detected"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []
        tokens = ctx.get("context_tokens", 0)
        max_tokens = ctx.get("context_max_tokens", 128000)

        if max_tokens > 0:
            pct = tokens / max_tokens
            if pct >= 0.95:
                actions.append(
                    "Emergency context compression — keeping only system prompt + last 10 messages"
                )
                ctx["compress_aggressive"] = True
                ctx["keep_last_n"] = 10
            elif pct >= 0.85:
                actions.append("Context compression — keeping system prompt + last 20 messages")
                ctx["compress_aggressive"] = False
                ctx["keep_last_n"] = 20
            else:
                actions.append("Light context cleanup — removing low-priority constraints")
                ctx["compress_aggressive"] = False
                ctx["keep_last_n"] = 30

        success = True  # Compression always succeeds
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.COMPRESS_CONTEXT,
            actions_taken=actions,
            verification_passed=True,
            verification_details=f"Compressed to last {ctx.get('keep_last_n', 20)} messages",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        tokens = ctx.get("context_tokens", 0)
        max_tokens = ctx.get("context_max_tokens", 128000)
        if max_tokens > 0:
            pct = tokens / max_tokens
            if pct < 0.80:
                return True, f"Context reduced to {pct:.0%} capacity"
        return False, f"Context still at {tokens / max_tokens:.0%} capacity"


class LoopDetectionRepair(BaseRepairStrategy):
    """Repair strategy for agent loops and repetitive behavior.

    Handles:
        - Repeated tool calls
        - Repetitive patterns
        - Stuck execution
    """

    name = "loop_detection"
    supported_categories = ["loop_detected", "repetition"]
    min_severity = 1

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        loop_count = ctx.get("loop_count", 0)
        repetition_count = ctx.get("repetition_count", 0)
        parts = []
        if loop_count > 0:
            parts.append(f"{loop_count} repeated tool calls detected")
        if repetition_count > 0:
            parts.append(f"{repetition_count} repetitive patterns detected")
        return "; ".join(parts) if parts else "Loop/repetition detected"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        actions.append("Resetting agent strategy — forcing new approach")
        ctx["strategy_reset"] = True
        ctx["force_new_approach"] = True

        # If still looping, escalate to user
        if ctx.get("loop_count", 0) >= 10:
            actions.append("Escalating to user — agent stuck in loop")
            ctx["escalate_to_user"] = True

        success = True  # Strategy reset always succeeds
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.RESET_STRATEGY,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Strategy reset applied",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        if ctx.get("strategy_reset"):
            return True, "Strategy reset applied — monitoring for new patterns"
        return False, "No strategy reset applied"


class PromptInjectionRepair(BaseRepairStrategy):
    """Repair strategy for prompt injection attempts.

    Handles:
        - System prompt override attempts
        - Role-play injection
        - Identity override
        - Data exfiltration
    """

    name = "prompt_injection"
    supported_categories = ["prompt_injection", "secret_exposure"]
    min_severity = 1

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        matches = ctx.get("injection_matches", [])
        if matches:
            return f"Prompt injection patterns: {'; '.join(matches)}"
        return "Prompt injection detected"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        actions.append("Quarantining session — isolating from further input")
        ctx["quarantine"] = True

        actions.append("Resetting system prompt to baseline")
        ctx["reset_system_prompt"] = True

        actions.append("Alerting admin")
        ctx["alert_admin"] = True

        elapsed = time.time() - start

        return RepairResult(
            success=True,
            strategy=RepairStrategy.ESCALATE_TO_USER,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Session quarantined, system prompt reset",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        if ctx.get("quarantine") and ctx.get("reset_system_prompt"):
            return True, "Session quarantined and prompt reset"
        return False, "Quarantine not applied"


class InfrastructureFailureRepair(BaseRepairStrategy):
    """Repair strategy for infrastructure failures.

    Handles:
        - Model unavailable
        - Embedder unavailable
        - Service crashes
    """

    name = "infrastructure_failure"
    supported_categories = ["infrastructure_failure", "model_unavailable", "embedder_unavailable"]
    min_severity = 1

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        model = ctx.get("model", "unknown")
        embedder = ctx.get("embedder", "unknown")
        parts = []
        if not ctx.get("model_available", True):
            parts.append(f"Model '{model}' unavailable")
        if not ctx.get("embedder_available", True):
            parts.append(f"Embedder '{embedder}' unavailable")
        return "; ".join(parts) if parts else "Infrastructure failure detected"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        # Try to restart the service
        if not ctx.get("model_available", True):
            actions.append("Attempting to restart model service on port 8090")
            ctx["restart_model_service"] = True

        if not ctx.get("embedder_available", True):
            actions.append("Attempting to restart embedder service on port 8091")
            ctx["restart_embedder_service"] = True

        # If restart fails, switch to fallback
        if not ctx.get("model_available", True):
            actions.append("Switching to fallback model on port 8092")
            ctx["switch_to_fallback"] = True

        success = bool(
            ctx.get("model_available", True) or ctx.get("switch_to_fallback")
        )
        elapsed = time.time() - start

        return RepairResult(
            success=success,
            strategy=RepairStrategy.RESTART_SERVICE,
            actions_taken=actions,
            verification_passed=success,
            verification_details="Service restart attempted" if success else "Fallback activated",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        if ctx.get("model_available", True):
            return True, "Model service available"
        if ctx.get("switch_to_fallback"):
            return True, "Fallback model active"
        return False, "Model service still unavailable"


class PerformanceDegradationRepair(BaseRepairStrategy):
    """Repair strategy for performance degradation.

    Handles:
        - High error rates
        - Decreasing throughput
        - Increasing wall time per task
    """

    name = "performance_degradation"
    supported_categories = ["performance_degradation", "throughput_drop"]
    min_severity = 1

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        error_count = ctx.get("error_count", 0)
        parts = []
        if error_count > 0:
            parts.append(f"{error_count} errors detected")
        if ctx.get("throughput_drop", 0) > 0:
            parts.append(f"Throughput dropped {ctx['throughput_drop']:.0%}")
        return "; ".join(parts) if parts else "Performance degradation detected"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        actions.append("Clearing internal caches")
        ctx["clear_caches"] = True

        actions.append("Resetting error counters")
        ctx["reset_error_counters"] = True

        # If error rate is very high, suggest rollback
        if ctx.get("error_count", 0) >= 10:
            actions.append("Suggesting rollback to last known good state")
            ctx["suggest_rollback"] = True

        elapsed = time.time() - start

        return RepairResult(
            success=True,
            strategy=RepairStrategy.CLEAR_CACHE,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Caches cleared, counters reset",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        if ctx.get("clear_caches") and ctx.get("reset_error_counters"):
            return True, "Caches cleared and counters reset"
        return False, "Repair not applied"


class SelfDegradationRepair(BaseRepairStrategy):
    """Repair strategy for self-modification that degrades performance.

    Handles:
        - Self-modification causing performance drop
        - Bad axiom changes
        - Corrupted memory entries
    """

    name = "self_degradation"
    supported_categories = ["self_degradation"]
    min_severity = 2  # HIGH and above — self-degradation is serious

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        degradation = ctx.get("performance_degradation", 0)
        return f"Self-modification caused {degradation:.0%} performance degradation"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        actions.append("Rolling back last self-modification")
        ctx["rollback_self_modification"] = True

        actions.append("Running self-tests to verify system integrity")
        ctx["run_self_tests"] = True

        elapsed = time.time() - start

        return RepairResult(
            success=True,
            strategy=RepairStrategy.ROLLBACK_CODE,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Self-modification rolled back",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        if ctx.get("rollback_self_modification"):
            return True, "Self-modification rolled back — awaiting self-test results"
        return False, "Rollback not applied"


class GuardrailViolationRepair(BaseRepairStrategy):
    """Repair strategy for guardrail violations.

    Handles:
        - Axiom violations
        - Safety boundary breaches
        - Policy violations
    """

    name = "guardrail_violation"
    supported_categories = ["guardrail_violation"]
    min_severity = 2

    async def diagnose(self, ctx: dict[str, Any]) -> str:
        violation = ctx.get("violation_type", "unknown")
        return f"Guardrail violation: {violation}"

    async def repair(self, ctx: dict[str, Any]) -> RepairResult:
        start = time.time()
        actions = []

        actions.append("Halting current operation")
        ctx["halt_operation"] = True

        actions.append("Resetting to last valid state")
        ctx["reset_to_valid_state"] = True

        actions.append("Notifying admin of violation")
        ctx["notify_admin"] = True

        elapsed = time.time() - start

        return RepairResult(
            success=True,
            strategy=RepairStrategy.ESCALATE_TO_USER,
            actions_taken=actions,
            verification_passed=True,
            verification_details="Operation halted, admin notified",
            time_seconds=elapsed,
        )

    async def verify(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        if ctx.get("halt_operation") and ctx.get("reset_to_valid_state"):
            return True, "Operation halted and state reset"
        return False, "Repair not applied"


class RepairStrategyRegistry:
    """Registry of repair strategies, organized by threat category.

    Manages strategy registration, lookup, and execution.
    """

    def __init__(self):
        self._strategies: list[BaseRepairStrategy] = []
        self._effector: RepairEffector | None = None
        self._register_builtin_strategies()

    def set_effector(self, effector: RepairEffector | None) -> None:
        """Inject a real :class:`RepairEffector`.

        When set, subclasses can invoke ``self._registry._effector`` (via
        the registry singleton) to carry out real side-effects. If not
        set, all built-in strategies remain in simulation mode.
        """
        self._effector = effector

    def _register_builtin_strategies(self) -> None:
        """Register all built-in repair strategies."""
        self.register(ResourceExhaustionRepair())
        self.register(ContextOverflowRepair())
        self.register(LoopDetectionRepair())
        self.register(PromptInjectionRepair())
        self.register(InfrastructureFailureRepair())
        self.register(PerformanceDegradationRepair())
        self.register(SelfDegradationRepair())
        self.register(GuardrailViolationRepair())

    def register(self, strategy: BaseRepairStrategy) -> None:
        """Register a strategy."""
        self._strategies.append(strategy)
        log.info(
            "[RepairStrategyRegistry] Registered strategy: %s (%s)",
            strategy.name,
            strategy.supported_categories,
        )

    def unregister(self, name: str) -> None:
        """Unregister a strategy by name."""
        self._strategies = [s for s in self._strategies if s.name != name]
        log.info("[RepairStrategyRegistry] Unregistered strategy: %s", name)

    async def get_strategy(self, category: str, severity: int) -> BaseRepairStrategy | None:
        """Find the best strategy for a given threat category and severity."""
        candidates = []
        for strategy in self._strategies:
            if await strategy.can_handle(category, severity):
                candidates.append(strategy)

        if not candidates:
            return None

        # Return the first matching strategy (most specific first)
        return candidates[0]

    async def repair(
        self,
        threat_category: str,
        threat_severity: int,
        ctx: dict[str, Any],
    ) -> RepairResult:
        """Execute the best repair strategy for a threat."""
        strategy = await self.get_strategy(threat_category, threat_severity)
        if not strategy:
            return RepairResult(
                success=False,
                strategy=RepairStrategy.ESCALATE_TO_USER,
                actions_taken=[],
                verification_passed=False,
                error=f"No repair strategy found for category={threat_category}, severity={threat_severity}",
            )

        log.info(
            "[RepairStrategyRegistry] Using strategy '%s' for %s (severity=%s)",
            strategy.name,
            threat_category,
            threat_severity,
        )

        # Diagnose
        diagnosis = await strategy.diagnose(ctx)
        ctx["diagnosis"] = diagnosis
        log.info("[RepairStrategyRegistry] Diagnosis: %s", diagnosis)

        # Repair — wrap in simulation guard
        result = await strategy.repair(ctx)
        if getattr(strategy, "simulation", False):
            result = strategy._mark_simulated(result)
        result.actions_taken = [diagnosis] + result.actions_taken

        return result

    def list_strategies(self) -> list[dict[str, Any]]:
        """List all registered strategies."""
        return [
            {
                "name": s.name,
                "supported_categories": s.supported_categories,
                "min_severity": s.min_severity,
            }
            for s in self._strategies
        ]


# Singleton
_registry: RepairStrategyRegistry | None = None


def get_strategy_registry() -> RepairStrategyRegistry:
    """Get or create the global strategy registry."""
    global _registry
    if _registry is None:
        _registry = RepairStrategyRegistry()
    return _registry


def reset_strategy_registry() -> None:
    """Reset the global strategy registry (for testing)."""
    global _registry
    _registry = None


__all__ = [
    "BaseRepairStrategy",
    "ContextOverflowRepair",
    "GuardrailViolationRepair",
    "InfrastructureFailureRepair",
    "LoopDetectionRepair",
    "PerformanceDegradationRepair",
    "PromptInjectionRepair",
    "RepairEffector",
    "RepairStrategyRegistry",
    "ResourceExhaustionRepair",
    "SelfDegradationRepair",
    "get_strategy_registry",
    "reset_strategy_registry",
]
