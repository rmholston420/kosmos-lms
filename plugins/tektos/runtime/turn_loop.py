"""Tektos runtime turn loop.

Stage 3.13 (ADR-092 §3) landed this module as an event-driven pre-LLM slice
composing ``ImmunePort`` + ``LoopSafetyPort`` + ``ThermalPort`` + ``EventBusPort``.

Stage 8.2 (ADR-104) grows the same class with four *optional* port
collaborators — ``SessionPort`` (D2), ``LLMPort`` (D3), ``SandboxPort`` (D4),
and ``ResourcePort`` (D5) — without disturbing any Stage 3.13 test surface.
Every new collaborator defaults to ``None``; when omitted, this module
behaves identically to the pre-8.2 skeleton.

See ADR-104 for the full behavioural contract.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

from ports.event_envelope import EventEnvelope
from ports.immune import ImmuneScanRequest, ImmuneVerdict
from ports.loop_safety import LoopSafetyState, TurnHandle, TurnSummary
from ports.resource import ResourceKind
from ports.sandbox import SandboxRequest, SandboxResult
from ports.thermal import ThermalPressure

logger = logging.getLogger(__name__)

__all__ = [
    "ToolCallSpec",
    "ToolCallOutcome",
    "TurnOutcome",
    "TurnStopReason",
    "TektosTurnLoop",
]


TurnStopReason = Literal[
    "completed",
    "immune_blocked_prompt",
    "immune_blocked_tool_call",
    "thermal_red",
    "loop_exhausted",
    "loop_repetition",
    "budget_exhausted",
    "llm_error",
    "sandbox_error",
    "resource_exhausted",
    "preflight_error",
]


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class _SessionPortLike(Protocol):
    async def start_turn(self, session_id: str, *, reason: str = "") -> Any: ...
    async def complete_turn(
        self, session_id: str, *, reason: str = ""
    ) -> Any: ...
    async def fail_turn(self, session_id: str, *, reason: str = "") -> Any: ...
    async def interrupt_turn(
        self, session_id: str, *, reason: str = ""
    ) -> Any: ...


class _LLMPortLike(Protocol):
    async def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> dict[str, Any]: ...


class _SandboxPortLike(Protocol):
    async def run(self, request: SandboxRequest) -> SandboxResult: ...


class _ResourcePortLike(Protocol):
    async def can_allocate(
        self, kind: ResourceKind, amount: Decimal | float
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ToolCallSpec:
    """Declarative tool call the runtime should attempt this turn.

    ADR-104 D4: when ``sandbox_request`` is set and a ``SandboxPort`` is bound
    on the loop, the tool is executed via ``sandbox.run(sandbox_request)``.
    When either is unset, the tool is still budget-accounted but not
    executed (Stage 3.13 semantics preserved).
    """

    name: str
    read_only: bool
    action_hash: str
    args: dict = field(default_factory=dict)
    sandbox_request: SandboxRequest | None = None


@dataclass(frozen=True, slots=True)
class ToolCallOutcome:
    """Per-tool-call outcome after immune + loop-safety gating.

    ADR-104 D4: ``sandbox_result`` is populated when the tool was executed
    via ``SandboxPort``; ``None`` otherwise.
    """

    spec: ToolCallSpec
    accepted: bool
    reason: str
    immune_decision: str
    loop_status: str
    sandbox_result: SandboxResult | None = None


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """Result of a single ``run_turn`` invocation.

    ADR-104:
    - ``llm_response`` — set when an ``LLMPort`` was bound and inference
      succeeded (D3).
    - ``resource_exhausted`` — advisory flag set when the post-turn
      ``ResourcePort.can_allocate`` check returned ``False`` (D5).
    - ``error`` — captured message when the turn stopped with a
      terminal-error reason (``llm_error`` / ``sandbox_error``).
    """

    stop_reason: TurnStopReason
    handle: TurnHandle | None
    summary: TurnSummary | None
    prompt_verdict: ImmuneVerdict | None
    thermal_pressure: ThermalPressure | None
    tool_outcomes: tuple[ToolCallOutcome, ...]
    llm_response: dict[str, Any] | None = None
    resource_exhausted: bool = False
    error: str | None = None


class TektosTurnLoop:
    """The Tektos runtime turn loop.

    Stage 3.13 base: ``ImmunePort`` + ``LoopSafetyPort`` + ``ThermalPort``
    + ``EventBusPort`` (event fan-out).

    Stage 8.2 growth (ADR-104): optional ``SessionPort`` (lifecycle
    transitions), ``LLMPort`` (single non-streaming inference),
    ``SandboxPort`` (per-tool execution), ``ResourcePort`` (post-turn
    advisory check). Every 8.2 collaborator defaults to ``None``; when
    unset the loop behaves exactly as the Stage 3.13 skeleton.
    """

    def __init__(
        self,
        *,
        immune,
        loop_safety,
        thermal,
        event_bus: _EventBusLike | None = None,
        # ADR-104 Stage 8.2 optional collaborators
        session_port: _SessionPortLike | None = None,
        llm: _LLMPortLike | None = None,
        sandbox: _SandboxPortLike | None = None,
        resource: _ResourcePortLike | None = None,
    ) -> None:
        self._immune = immune
        self._loop_safety = loop_safety
        self._thermal = thermal
        self._event_bus = event_bus
        self._session_port = session_port
        self._llm = llm
        self._sandbox = sandbox
        self._resource = resource

    async def run_turn(
        self,
        *,
        agent_id: str,
        prompt: str,
        tool_calls: list[ToolCallSpec] | None = None,
        # ADR-104 Stage 8.2 optional kwargs
        session_id: str | None = None,
        system_prompt: str | None = None,
        llm_options: dict[str, Any] | None = None,
    ) -> TurnOutcome:
        tool_calls = tool_calls or []
        llm_options = llm_options or {}

        # ADR-104 D2: open the session-lifecycle turn before any gating so
        # a blocked-by-immune outcome fails the turn on the FSM as well.
        if self._session_port is not None and session_id is not None:
            try:
                await self._session_port.start_turn(
                    session_id, reason="tektos.turn"
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "session.start_turn failed for session=%s agent=%s",
                    session_id,
                    agent_id,
                )

        # 1. Immune scan on the prompt itself.
        prompt_scan = ImmuneScanRequest(
            payload={"prompt": prompt},
            kind="tektos.agent.prompt",
            source_plugin="tektos_runtime",
        )
        try:
            prompt_verdict = await self._immune.scan(prompt_scan)
        except Exception:  # noqa: BLE001
            logger.exception(
                "immune.scan (prompt) failed for session=%s agent=%s",
                session_id,
                agent_id,
            )
            await self._session_fail(session_id, "immune_scan_error")
            return TurnOutcome(
                stop_reason="preflight_error",
                handle=None,
                summary=None,
                prompt_verdict=None,
                thermal_pressure=self._thermal.pressure(),
                tool_outcomes=(),
            )
        if prompt_verdict.decision == "block":
            await self._publish_turn_event(
                "tektos.agent.turn.blocked",
                agent_id=agent_id,
                session_id=session_id,
                extra={
                    "stage": "prompt_scan",
                    "reason": prompt_verdict.reason,
                },
            )
            await self._session_fail(session_id, "immune_blocked_prompt")
            return TurnOutcome(
                stop_reason="immune_blocked_prompt",
                handle=None,
                summary=None,
                prompt_verdict=prompt_verdict,
                thermal_pressure=self._thermal.pressure(),
                tool_outcomes=(),
            )

        # 2. Thermal pre-flight (sync hot-path).
        pressure = self._thermal.pressure()
        if pressure.level == "red":
            await self._publish_turn_event(
                "tektos.agent.turn.blocked",
                agent_id=agent_id,
                session_id=session_id,
                extra={
                    "stage": "thermal_preflight",
                    "gpu_temp_c": pressure.gpu_temp_c,
                    "level": "red",
                },
            )
            await self._session_fail(session_id, "thermal_red")
            return TurnOutcome(
                stop_reason="thermal_red",
                handle=None,
                summary=None,
                prompt_verdict=prompt_verdict,
                thermal_pressure=pressure,
                tool_outcomes=(),
            )

        # 3. Open the loop-safety turn.
        try:
            handle = await self._loop_safety.begin_turn(agent_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "loop_safety.begin_turn failed for session=%s agent=%s",
                session_id,
                agent_id,
            )
            await self._session_fail(session_id, "loop_safety_error")
            return TurnOutcome(
                stop_reason="preflight_error",
                handle=None,
                summary=None,
                prompt_verdict=prompt_verdict,
                thermal_pressure=self._thermal.pressure(),
                tool_outcomes=(),
            )
        await self._publish_turn_event(
            "tektos.agent.turn.started",
            agent_id=agent_id,
            session_id=session_id,
            handle=handle,
            extra={"tool_calls_planned": len(tool_calls)},
        )

        outcomes: list[ToolCallOutcome] = []
        stop_reason: TurnStopReason = "completed"
        llm_response: dict[str, Any] | None = None
        error_message: str | None = None
        summary: TurnSummary | None = None

        try:
            # ADR-104 D3: single non-streaming LLM inference (once per turn).
            if self._llm is not None:
                start_ns = time.perf_counter_ns()
                try:
                    llm_response = await self._llm.generate(
                        prompt=prompt,
                        system=system_prompt,
                        **llm_options,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "llm.generate failed for agent=%s session=%s",
                        agent_id,
                        session_id,
                    )
                    stop_reason = "llm_error"
                    error_message = str(exc)
                else:
                    latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
                    response_text = self._extract_response_text(llm_response)
                    await self._publish_turn_event(
                        "tektos.agent.turn.llm_completed",
                        agent_id=agent_id,
                        session_id=session_id,
                        handle=handle,
                        extra={
                            "model": (llm_response or {}).get("model"),
                            "latency_ms": int(latency_ms),
                            "response_length": len(response_text),
                            # ADR-132 slice F: carry the assistant text so the
                            # kernel-native replay endpoint can reconstruct
                            # the conversation (donor assistant.delta parity).
                            "text": response_text,
                        },
                    )

            # Per-tool gating + optional sandbox execution.
            if stop_reason == "completed":
                for spec in tool_calls:
                    # 3a. Immune scan on the tool call.
                    call_verdict = await self._immune.scan(
                        ImmuneScanRequest(
                            payload={
                                "tool_name": spec.name,
                                "tool_input": spec.args,
                            },
                            kind="tektos.agent.tool_call",
                            source_plugin="tektos_runtime",
                        )
                    )
                    if call_verdict.decision == "block":
                        outcomes.append(
                            ToolCallOutcome(
                                spec=spec,
                                accepted=False,
                                reason=f"immune blocked: {call_verdict.reason}",
                                immune_decision="block",
                                loop_status="ok",
                            )
                        )
                        stop_reason = "immune_blocked_tool_call"
                        await self._publish_turn_event(
                            "tektos.agent.turn.tool_call",
                            agent_id=agent_id,
                            session_id=session_id,
                            handle=handle,
                            extra={
                                "tool": spec.name,
                                "accepted": False,
                                "reason": "immune_block",
                            },
                        )
                        break

                    # 3b. Repetition check (advisory).
                    await self._loop_safety.check_repetition(
                        handle, spec.action_hash
                    )

                    # 3c. Record the tool call (consumes read-only budget).
                    state: LoopSafetyState = (
                        await self._loop_safety.record_tool_call(
                            handle, read_only=spec.read_only
                        )
                    )

                    # ADR-104 D4: sandbox execution when bound + requested.
                    sandbox_result: SandboxResult | None = None
                    if (
                        self._sandbox is not None
                        and spec.sandbox_request is not None
                        and state.status in ("ok", "warn")
                    ):
                        try:
                            sandbox_result = await self._sandbox.run(
                                spec.sandbox_request
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception(
                                "sandbox.run failed tool=%s agent=%s",
                                spec.name,
                                agent_id,
                            )
                            outcomes.append(
                                ToolCallOutcome(
                                    spec=spec,
                                    accepted=False,
                                    reason=f"sandbox error: {exc}",
                                    immune_decision=call_verdict.decision,
                                    loop_status=state.status,
                                )
                            )
                            stop_reason = "sandbox_error"
                            error_message = str(exc)
                            await self._publish_turn_event(
                                "tektos.agent.turn.tool_call",
                                agent_id=agent_id,
                                session_id=session_id,
                                handle=handle,
                                extra={
                                    "tool": spec.name,
                                    "accepted": False,
                                    "reason": "sandbox_error",
                                },
                            )
                            break

                    outcomes.append(
                        ToolCallOutcome(
                            spec=spec,
                            accepted=state.status in ("ok", "warn"),
                            reason=state.detail or "ok",
                            immune_decision=call_verdict.decision,
                            loop_status=state.status,
                            sandbox_result=sandbox_result,
                        )
                    )
                    await self._publish_turn_event(
                        "tektos.agent.turn.tool_call",
                        agent_id=agent_id,
                        session_id=session_id,
                        handle=handle,
                        extra={
                            "tool": spec.name,
                            "accepted": state.status in ("ok", "warn"),
                            "loop_status": state.status,
                            "budget_remaining": state.budget_remaining,
                        },
                    )

                    # ADR-104 D6: sandbox_completed fan-out.
                    if sandbox_result is not None:
                        await self._publish_turn_event(
                            "tektos.agent.turn.sandbox_completed",
                            agent_id=agent_id,
                            session_id=session_id,
                            handle=handle,
                            extra={
                                "tool": spec.name,
                                "exit_code": sandbox_result.exit_code,
                                "wall_seconds": sandbox_result.wall_seconds,
                                "killed_by": sandbox_result.killed_by,
                            },
                        )

                    if state.status == "budget_exhausted":
                        stop_reason = "budget_exhausted"
                        break
                    if state.status == "exhausted":
                        stop_reason = "loop_exhausted"
                        break
                    if state.status == "repetition":
                        stop_reason = "loop_repetition"
                        break

            summary = await self._loop_safety.end_turn(handle)
        finally:
            # Ensure end_turn ran even on unexpected exception.
            if summary is None:
                try:
                    summary = await self._loop_safety.end_turn(handle)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "loop_safety.end_turn failed during recovery for turn=%s",
                        handle.turn_id,
                    )

        # ADR-104 D5: post-turn ResourcePort advisory check (fail-open).
        resource_exhausted = False
        if self._resource is not None:
            try:
                can = await self._resource.can_allocate(
                    ResourceKind.COMPUTE, Decimal("1")
                )
                resource_exhausted = not can
            except Exception:  # noqa: BLE001
                logger.exception(
                    "resource.can_allocate failed for agent=%s", agent_id
                )

        await self._publish_turn_event(
            "tektos.agent.turn.completed",
            agent_id=agent_id,
            session_id=session_id,
            handle=handle,
            extra={
                "stop_reason": stop_reason,
                "tokens_total": summary.tokens_total if summary else 0,
                "tool_calls": summary.tool_calls if summary else 0,
                "read_only_calls": summary.read_only_calls if summary else 0,
                "terminal_status": (
                    summary.terminal_status if summary else "unknown"
                ),
            },
        )

        # ADR-104 D2: session-lifecycle transitions on branch exit.
        if stop_reason == "completed":
            await self._session_complete(session_id, stop_reason)
        else:
            await self._session_fail(session_id, stop_reason)

        return TurnOutcome(
            stop_reason=stop_reason,
            handle=handle,
            summary=summary,
            prompt_verdict=prompt_verdict,
            thermal_pressure=self._thermal.pressure(),
            tool_outcomes=tuple(outcomes),
            llm_response=llm_response,
            resource_exhausted=resource_exhausted,
            error=error_message,
        )

    # ── ADR-104 D2 external interrupt surface ───────────────────────────

    async def interrupt(self, session_id: str, *, reason: str = "external") -> None:
        """Interrupt an in-flight turn (mirrors donor ``RuntimeSDK.interrupt``).

        No-op when no ``SessionPort`` is bound.
        """
        if self._session_port is None:
            return
        try:
            await self._session_port.interrupt_turn(session_id, reason=reason)
        except Exception:  # noqa: BLE001
            logger.exception(
                "session.interrupt_turn failed for session=%s", session_id
            )

    # ── Internal ──────────────────────────────────────────────────────

    async def _session_complete(
        self, session_id: str | None, reason: str
    ) -> None:
        if self._session_port is None or session_id is None:
            return
        try:
            await self._session_port.complete_turn(session_id, reason=reason)
        except Exception:  # noqa: BLE001
            logger.exception(
                "session.complete_turn failed for session=%s reason=%s",
                session_id,
                reason,
            )

    async def _session_fail(
        self, session_id: str | None, reason: str
    ) -> None:
        if self._session_port is None or session_id is None:
            return
        try:
            await self._session_port.fail_turn(session_id, reason=reason)
        except Exception:  # noqa: BLE001
            logger.exception(
                "session.fail_turn failed for session=%s reason=%s",
                session_id,
                reason,
            )

    @staticmethod
    def _extract_response_text(response: dict[str, Any] | None) -> str:
        """Best-effort extraction of assistant text from an LLM response dict.

        Supports the two shapes commonly returned by ``LLMPort.generate``
        backends: Ollama-style ``{"response": "..."}`` and OpenAI-style
        ``{"choices": [{"message": {"content": "..."}}]}``. Returns "" on
        anything unrecognised.
        """
        if not response:
            return ""
        text = response.get("response")
        if isinstance(text, str):
            return text
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
                text = first.get("text")
                if isinstance(text, str):
                    return text
        return ""

    async def _publish_turn_event(
        self,
        event_type: str,
        *,
        agent_id: str,
        handle: TurnHandle | None = None,
        session_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            payload: dict = {
                "source": "tektos_runtime",
                "agent_id": agent_id,
            }
            if session_id is not None:
                payload["session_id"] = session_id
            if handle is not None:
                payload["turn_id"] = handle.turn_id
                payload["correlation_id"] = handle.turn_id
            if extra:
                payload.update(extra)
            envelope = EventEnvelope(
                event_type=event_type,
                producer_plugin="tektos_runtime",
                payload=payload,
            )
            await self._event_bus.publish(envelope)
        except Exception:  # noqa: BLE001 — never let bus faults break the turn
            logger.exception(
                "turn-loop publish failed for event_type=%s agent=%s",
                event_type,
                agent_id,
            )
