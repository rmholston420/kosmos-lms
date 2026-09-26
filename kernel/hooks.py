"""
Tektos-Ultima-v1 — Hook System

Lightweight event-driven hook system for policy, audit, approval,
self-improvement triggers, and resource monitoring.

Architecture:
    @hook.register("session.completed")
    async def on_session_completed(ctx: HookContext) -> HookResult:
        await self_improvement.record_experience(ctx)
        return HookResult(continue=True)

Hook categories:
    - tool.before / tool.after — audit, approval, rate-limiting
    - session.* — self-improvement triggers, resource checks
    - prompt.before — context injection, spec validation
    - memory.write — provenance validation (Agent Memory Guard)
    - resource.warning — thermal/VRAM alerts

Kernel substrate (ADR-141 T8c-4) — verbatim port of the donor
``tektos-ultima-v1/src/tektos/runtime/hooks.py`` (325 LOC, self-contained:
stdlib-only). Consumed by ``registry.hook_manager`` (booted with the
kernel ``thermal_watchdog`` as the resource monitor — the donor passed its
own thermal monitor; the thermal built-in hook degrades identically on
both sides because neither monitor exposes ``check_thermal_limit``) and by
the donor-faithful ``GET /api/hooks`` + ``POST /api/hooks/fire`` routes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ── Types ──────────────────────────────────────────────────────────────────


class HookPriority(int, Enum):
    """Execution priority for hooks (lower = earlier)."""

    CRITICAL = 0  # Must run before anything else
    HIGH = 10
    NORMAL = 50  # Default
    LOW = 90


class HookResultCode(str, Enum):
    CONTINUE = "continue"
    ABORT = "abort"
    REJECT = "reject"
    WAIT = "wait"


@dataclass
class HookResult:
    outcome: HookResultCode = HookResultCode.CONTINUE
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    blocking: bool = False


@dataclass
class HookContext:
    """Shared context passed to all hooks for a given event."""

    event_type: str
    session_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    model: str | None = None
    task_description: str | None = None
    outcome: str | None = None
    wall_time: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_session_id(self) -> str:
        return self.session_id or "unknown"


# ── Hook Protocol ──────────────────────────────────────────────────────────


class HookFn(Protocol):
    async def __call__(self, ctx: HookContext) -> HookResult: ...


# ── Hook Registry ──────────────────────────────────────────────────────────


class HookRegistry:
    """
    Registry of event-driven hooks with priority ordering.

    Usage:
        registry = HookRegistry()

        @registry.register("tool.before")
        async def audit(ctx: HookContext) -> HookResult:
            logger.info("Tool call: %s", ctx.tool_name)
            return HookResult(continue=True)

        # Execute hooks for an event
        results = await registry.fire("tool.before", ctx)
        if any(r.outcome == HookResultCode.ABORT for r in results):
            logger.warning("Hook blocked tool execution")
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[int, HookFn]]] = {}

    def register(
        self,
        event_type: str,
        priority: HookPriority = HookPriority.NORMAL,
    ) -> Callable[[HookFn], HookFn]:
        """Decorator to register a hook function for an event type."""

        def decorator(fn: HookFn) -> HookFn:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append((priority, fn))
            return fn

        return decorator

    async def fire(
        self,
        event_type: str,
        ctx: HookContext,
        *,
        stop_on_abort: bool = True,
    ) -> list[HookResult]:
        """
        Fire all hooks for an event type, sorted by priority.

        If stop_on_abort=True, returns immediately on first ABORT/REJECT.
        """
        handlers = sorted(
            self._handlers.get(event_type, []),
            key=lambda x: x[0],
        )

        results: list[HookResult] = []
        for _, fn in handlers:
            try:
                result = await fn(ctx)
                results.append(result)
                logger.debug(
                    "Hook %s.%s → %s: %s",
                    event_type,
                    fn.__name__,
                    result.outcome.value,
                    result.message,
                )
                if stop_on_abort and result.outcome in (
                    HookResultCode.ABORT,
                    HookResultCode.REJECT,
                ):
                    break
            except Exception:
                logger.exception("Hook %s failed: %s", event_type, fn.__name__)
                results.append(
                    HookResult(
                        outcome=HookResultCode.ABORT,
                        message=f"Hook {fn.__name__} raised exception",
                        blocking=True,
                    )
                )

        return results

    def unregister(self, event_type: str, fn: HookFn) -> None:
        if event_type in self._handlers:
            self._handlers[event_type] = [
                (p, f) for p, f in self._handlers[event_type] if f is not fn
            ]
            if not self._handlers[event_type]:
                del self._handlers[event_type]

    def list_hooks(self) -> dict[str, list[str]]:
        """Return {event_type: [fn_name, ...]} for all registered hooks."""
        return {et: [fn.__name__ for _, fn in handlers] for et, handlers in self._handlers.items()}


# ── Built-in Hooks ─────────────────────────────────────────────────────────


class BuiltinHooks:
    """
    Standard hooks that ship with Tektos.

    These can be overridden by registering custom hooks for the same event.
    Custom hooks registered with lower priority (higher number) run after
    builtins.
    """

    def __init__(self, registry: HookRegistry, resource_monitor=None) -> None:
        self._registry = registry
        self._resource_monitor = resource_monitor

        self._register_defaults()

    def _register_defaults(self) -> None:
        @self._registry.register("tool.before")
        async def _audit_log_tool(ctx: HookContext) -> HookResult:
            """Log every tool call to audit trail."""
            logger.info(
                "[AUDIT] tool=%s session=%s",
                ctx.tool_name,
                ctx.get_session_id(),
            )
            return HookResult()

        @self._registry.register("tool.after")
        async def _audit_log_tool_result(ctx: HookContext) -> HookResult:
            """Log tool call completion."""
            logger.info(
                "[AUDIT] tool=%s completed session=%s",
                ctx.tool_name,
                ctx.get_session_id(),
            )
            return HookResult()

        @self._registry.register("session.created")
        async def _init_session_audit(ctx: HookContext) -> HookResult:
            logger.info("[AUDIT] session=%s created", ctx.get_session_id())
            return HookResult()

        @self._registry.register("prompt.before")
        async def _validate_prompt(ctx: HookContext) -> HookResult:
            """Validate prompt input before sending to LLM."""
            prompt = ctx.metadata.get("prompt_text", "")
            if len(prompt) < 1:
                return HookResult(
                    outcome=HookResultCode.ABORT,
                    message="Empty prompt rejected",
                    blocking=True,
                )
            return HookResult()

        # Only register the thermal guard when the injected resource monitor
        # actually exposes ``check_thermal_limit``. Earlier the hook called
        # the method unconditionally, which raised AttributeError on every
        # tool.before fire and produced ``Hook tool.before failed:
        # _check_thermal_limit`` in the log for every tool call. The fire
        # loop is non-blocking so tools still ran, but the noise misled the
        # model into thinking its own tools were being sandboxed.
        if self._resource_monitor and hasattr(
            self._resource_monitor, "check_thermal_limit"
        ):

            @self._registry.register("tool.before")
            async def _check_thermal_limit(ctx: HookContext) -> HookResult:
                """Block inference if GPU is above operational ceiling.

                Fail-open on telemetry errors: a diagnostic failure inside
                the resource monitor must never deny the user's tool call.
                """
                try:
                    ok = self._resource_monitor.check_thermal_limit()
                except Exception:
                    logger.debug(
                        "check_thermal_limit raised; treating as pass",
                        exc_info=True,
                    )
                    return HookResult()
                if not ok:
                    return HookResult(
                        outcome=HookResultCode.ABORT,
                        message="GPU thermal limit reached — inference blocked",
                        blocking=True,
                        data={"reason": "thermal_limit"},
                    )
                return HookResult()

            @self._registry.register("session.failed")
            async def _log_thermal_alert(ctx: HookContext) -> HookResult:
                if ctx.metadata.get("thermal"):
                    logger.warning(
                        "[THERMAL] session=%s failed due to thermal limit",
                        ctx.get_session_id(),
                    )
                return HookResult()


# ── Hook Manager (convenience) ─────────────────────────────────────────────


class HookManager:
    """
    High-level manager for hook lifecycle.

    Usage:
        manager = HookManager(resource_monitor)
        manager.fire("session.completed", session_id="abc", ...)
        manager.fire("tool.before", tool_name="terminal", ...)
    """

    def __init__(self, resource_monitor=None) -> None:
        self.registry = HookRegistry()
        self._builtins = BuiltinHooks(self.registry, resource_monitor)

    def register(
        self,
        event_type: str,
        priority: HookPriority = HookPriority.NORMAL,
    ) -> Callable[[HookFn], HookFn]:
        return self.registry.register(event_type, priority)

    async def fire(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        stop_on_abort: bool = True,
        **kwargs: Any,
    ) -> list[HookResult]:
        ctx = HookContext(
            event_type=event_type,
            session_id=session_id,
            **{k: v for k, v in kwargs.items() if k in HookContext.__dataclass_fields__},
        )
        return await self.registry.fire(event_type, ctx, stop_on_abort=stop_on_abort)

    def list_hooks(self) -> dict[str, list[str]]:
        return self.registry.list_hooks()
