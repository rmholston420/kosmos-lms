"""plugins.tektos.runtime.turn_loop — TektosTurnLoop.

Minimal event-driven vertical slice for Stage 3.13 (ADR-092 §3).

Composes the three Stage 3.13 adapters through their ports:

    ImmunePort  → prompt + tool-call gating
    LoopSafetyPort → turn budget + ADR-088 read-only interlock
    ThermalPort → hot-path pressure check (refuses red-level turns)
    EventBusPort → tektos.agent.turn.* envelopes

Deliberately excludes: LLM inference, planner, sandbox, tool executor,
approval flows, MCP, RAG, memory search, self-modification. Those land
Stage 4.7 and later.

Usage:

    loop = TektosTurnLoop(
        immune=immune_adapter,
        loop_safety=loop_safety_adapter,
        thermal=thermal_adapter,
        event_bus=event_bus,
    )
    outcome = await loop.run_turn(
        agent_id="tektos-runtime-1",
        prompt="describe the repo",
        tool_calls=[
            ToolCallSpec(name="read_file", read_only=True, action_hash="read:README"),
        ],
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ports.event_envelope import EventEnvelope
from ports.immune import ImmuneScanRequest, ImmuneVerdict
from ports.loop_safety import LoopSafetyState, TurnHandle, TurnSummary
from ports.thermal import ThermalPressure

logger = logging.getLogger(__name__)

__all__ = ["ToolCallSpec", "ToolCallOutcome", "TurnOutcome", "TektosTurnLoop"]


TurnStopReason = Literal[
    "completed",
    "immune_blocked_prompt",
    "immune_blocked_tool_call",
    "thermal_red",
    "loop_exhausted",
    "loop_repetition",
    "budget_exhausted",
]


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


@dataclass(frozen=True, slots=True)
class ToolCallSpec:
    """Declarative tool call the runtime should attempt this turn."""

    name: str
    read_only: bool
    action_hash: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCallOutcome:
    """Per-tool-call outcome after immune + loop-safety gating."""

    spec: ToolCallSpec
    accepted: bool
    reason: str
    immune_decision: str
    loop_status: str


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """Result of a single ``run_turn`` invocation."""

    stop_reason: TurnStopReason
    handle: TurnHandle | None
    summary: TurnSummary | None
    prompt_verdict: ImmuneVerdict | None
    thermal_pressure: ThermalPressure | None
    tool_outcomes: tuple[ToolCallOutcome, ...]


class TektosTurnLoop:
    """The minimal Stage 3.13 turn loop — no LLM, no sandbox.

    Composes ``ImmunePort`` + ``LoopSafetyPort`` + ``ThermalPort``
    through their formal port Protocols. Emits ``tektos.agent.turn.*``
    envelopes on the injected ``EventBusPort`` so downstream plugins can
    observe every turn boundary and tool-call attempt.
    """

    def __init__(
        self,
        *,
        immune,
        loop_safety,
        thermal,
        event_bus: _EventBusLike | None = None,
    ) -> None:
        self._immune = immune
        self._loop_safety = loop_safety
        self._thermal = thermal
        self._event_bus = event_bus

    async def run_turn(
        self,
        *,
        agent_id: str,
        prompt: str,
        tool_calls: list[ToolCallSpec] | None = None,
    ) -> TurnOutcome:
        tool_calls = tool_calls or []

        # 1. Immune scan on the prompt itself.
        prompt_scan = ImmuneScanRequest(
            payload={"prompt": prompt},
            kind="tektos.agent.prompt",
            source_plugin="tektos_runtime",
        )
        prompt_verdict = await self._immune.scan(prompt_scan)
        if prompt_verdict.decision == "block":
            await self._publish_turn_event(
                "tektos.agent.turn.blocked",
                agent_id=agent_id,
                extra={
                    "stage": "prompt_scan",
                    "reason": prompt_verdict.reason,
                },
            )
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
                extra={
                    "stage": "thermal_preflight",
                    "gpu_temp_c": pressure.gpu_temp_c,
                    "level": "red",
                },
            )
            return TurnOutcome(
                stop_reason="thermal_red",
                handle=None,
                summary=None,
                prompt_verdict=prompt_verdict,
                thermal_pressure=pressure,
                tool_outcomes=(),
            )

        # 3. Open the loop-safety turn.
        handle = await self._loop_safety.begin_turn(agent_id)
        await self._publish_turn_event(
            "tektos.agent.turn.started",
            agent_id=agent_id,
            handle=handle,
            extra={"tool_calls_planned": len(tool_calls)},
        )

        outcomes: list[ToolCallOutcome] = []
        stop_reason: TurnStopReason = "completed"

        try:
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
                        handle=handle,
                        extra={
                            "tool": spec.name,
                            "accepted": False,
                            "reason": "immune_block",
                        },
                    )
                    break

                # 3b. Repetition check (advisory — does not itself run the tool).
                await self._loop_safety.check_repetition(handle, spec.action_hash)

                # 3c. Record the tool call (consumes read-only budget if applicable).
                state: LoopSafetyState = await self._loop_safety.record_tool_call(
                    handle, read_only=spec.read_only
                )

                outcomes.append(
                    ToolCallOutcome(
                        spec=spec,
                        accepted=state.status in ("ok", "warn"),
                        reason=state.detail or "ok",
                        immune_decision=call_verdict.decision,
                        loop_status=state.status,
                    )
                )
                await self._publish_turn_event(
                    "tektos.agent.turn.tool_call",
                    agent_id=agent_id,
                    handle=handle,
                    extra={
                        "tool": spec.name,
                        "accepted": state.status in ("ok", "warn"),
                        "loop_status": state.status,
                        "budget_remaining": state.budget_remaining,
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
            # If end_turn was not reached (exception in body), still close.
            if "summary" not in dir():
                summary = await self._loop_safety.end_turn(handle)  # noqa: F841

        await self._publish_turn_event(
            "tektos.agent.turn.completed",
            agent_id=agent_id,
            handle=handle,
            extra={
                "stop_reason": stop_reason,
                "tokens_total": summary.tokens_total,
                "tool_calls": summary.tool_calls,
                "read_only_calls": summary.read_only_calls,
                "terminal_status": summary.terminal_status,
            },
        )

        return TurnOutcome(
            stop_reason=stop_reason,
            handle=handle,
            summary=summary,
            prompt_verdict=prompt_verdict,
            thermal_pressure=self._thermal.pressure(),
            tool_outcomes=tuple(outcomes),
        )

    # ── Internal ──────────────────────────────────────────────────────

    async def _publish_turn_event(
        self,
        event_type: str,
        *,
        agent_id: str,
        handle: TurnHandle | None = None,
        extra: dict | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            payload: dict = {
                "source": "tektos_runtime",
                "agent_id": agent_id,
            }
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
