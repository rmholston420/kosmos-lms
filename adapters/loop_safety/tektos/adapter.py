"""adapters.loop_safety.tektos — TektosLoopSafetyAdapter.

Reference implementation of ``ports.loop_safety.LoopSafetyPort`` wrapping
the vendored donor ``LoopSafetyMonitor`` (ADR-092) and adding the
ADR-088 read-only budget interlock the donor lacks.

Composition:

* One ``LoopSafetyMonitor`` instance per open ``TurnHandle``. Instances
  are held in a dict keyed by ``turn_id``; ``end_turn`` finalises the
  entry and freezes a ``TurnSummary``.
* A separate read-only budget counter per turn (ADR-088). Budget resets
  at ``begin_turn`` and does not carry across turns.
* Every state transition publishes ``loop_safety.<status>`` on the
  injected ``EventBusPort`` (ADR-080 rule 1). Terminal states
  additionally write a ``MemoryPort`` event with
  ``provenance="loop_safety"``, ``confidence=1.0`` (ADR-080 rule 2).

The event-bus + memory ports are injected at construction; both are
optional so unit tests can exercise the adapter without a bus. Missing
dependencies are logged, not fatal — the adapter degrades to
enforcement-only mode.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ports.event_envelope import EventEnvelope
from ports.loop_safety import (
    LoopCaps,
    LoopSafetyState,
    LoopSafetyStatus,
    TurnHandle,
    TurnSummary,
    validate_loop_caps,
)

from .vendor.loop_safety_donor import (
    LoopSafetyConfig,
    LoopSafetyMonitor,
    LoopState,
    StopReason,
)

logger = logging.getLogger(__name__)

__all__ = ["TektosLoopSafetyAdapter"]


# ── Port dependency Protocols (structural) ───────────────────────────────


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class _MemoryLike(Protocol):
    async def write_event(  # pragma: no cover — Protocol for typing only
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict | None = None,
    ) -> str: ...


# ── Per-turn state record ────────────────────────────────────────────────


@dataclass(slots=True)
class _TurnState:
    handle: TurnHandle
    monitor: LoopSafetyMonitor
    caps: LoopCaps
    turn_num: int
    tokens_total: int
    tool_calls: int
    read_only_calls: int
    read_only_budget_remaining: int
    action_window: deque[str]
    terminal_status: LoopSafetyStatus
    frozen_summary: TurnSummary | None


# ── Donor stop reason → port status mapping ──────────────────────────────

_STOP_REASON_TO_STATUS: dict[StopReason, LoopSafetyStatus] = {
    StopReason.MAX_TURNS: "exhausted",
    StopReason.MAX_TOKENS: "exhausted",
    StopReason.MAX_WALL_TIME: "exhausted",
    StopReason.REPETITION: "repetition",
    StopReason.CIRCUIT_BREAKER: "exhausted",
}


class TektosLoopSafetyAdapter:
    """LoopSafetyPort adapter wrapping the vendored ``LoopSafetyMonitor``.

    Wraps donor per-turn; owns the ADR-088 read-only budget interlock.
    """

    def __init__(
        self,
        *,
        default_caps: LoopCaps | None = None,
        event_bus: _EventBusLike | None = None,
        memory: _MemoryLike | None = None,
    ) -> None:
        caps = default_caps or LoopCaps()
        validate_loop_caps(caps)
        self._default_caps = caps
        self._event_bus = event_bus
        self._memory = memory
        self._turns: dict[str, _TurnState] = {}
        self._closed = False

    # ── Turn lifecycle ────────────────────────────────────────────────

    async def begin_turn(
        self,
        agent_id: str,
        config: LoopCaps | None = None,
    ) -> TurnHandle:
        if self._closed:
            raise RuntimeError("TektosLoopSafetyAdapter is closed.")
        caps = config or self._default_caps
        validate_loop_caps(caps)
        turn_id = f"tls-{uuid.uuid4().hex[:12]}"
        handle = TurnHandle(
            turn_id=turn_id,
            agent_id=agent_id,
            started_at=datetime.now(timezone.utc),
        )
        monitor_cfg = LoopSafetyConfig(
            max_turns=caps.max_turns,
            max_tokens_total=caps.max_tokens_total,
            max_wall_time_seconds=float(caps.max_wall_time_seconds),
            repetition_window=caps.repetition_window,
        )
        self._turns[turn_id] = _TurnState(
            handle=handle,
            monitor=LoopSafetyMonitor(config=monitor_cfg),
            caps=caps,
            turn_num=0,
            tokens_total=0,
            tool_calls=0,
            read_only_calls=0,
            read_only_budget_remaining=caps.read_only_budget,
            action_window=deque(maxlen=max(caps.repetition_window * 2, 4)),
            terminal_status="ok",
            frozen_summary=None,
        )
        await self._publish("ok", handle, detail="turn opened")
        return handle

    async def end_turn(self, handle: TurnHandle) -> TurnSummary:
        state = self._turns.get(handle.turn_id)
        if state is None:
            raise KeyError(f"unknown turn_id {handle.turn_id!r}")
        if state.frozen_summary is not None:
            return state.frozen_summary
        summary = TurnSummary(
            turn_id=handle.turn_id,
            ended_at=datetime.now(timezone.utc),
            tokens_total=state.tokens_total,
            tool_calls=state.tool_calls,
            read_only_calls=state.read_only_calls,
            terminal_status=state.terminal_status,
        )
        state.frozen_summary = summary
        return summary

    # ── Recording ─────────────────────────────────────────────────────

    async def record_tokens(
        self,
        handle: TurnHandle,
        tokens: int,
    ) -> LoopSafetyState:
        state = self._require_open_turn(handle)
        if tokens < 0:
            raise ValueError("tokens must be >= 0")
        state.tokens_total += tokens
        return await self._advance_turn(state, tokens_used=tokens, tool_calls=[])

    async def record_tool_call(
        self,
        handle: TurnHandle,
        *,
        read_only: bool,
    ) -> LoopSafetyState:
        state = self._require_open_turn(handle)
        state.tool_calls += 1
        if read_only:
            state.read_only_calls += 1
            # ADR-088 interlock — decrement before any hard-limit check
            state.read_only_budget_remaining = max(
                state.read_only_budget_remaining - 1, 0
            )
            if state.read_only_budget_remaining == 0:
                state.terminal_status = "budget_exhausted"
                envelope_kind = "loop_safety.read_only_budget_exhausted"
                await self._publish(
                    "budget_exhausted",
                    handle,
                    detail="read-only budget consumed (ADR-088)",
                    envelope_kind=envelope_kind,
                )
                await self._record_terminal_memory(
                    handle, status="budget_exhausted"
                )
                return LoopSafetyState(
                    status="budget_exhausted",
                    detail="read-only budget consumed",
                    budget_remaining=0,
                )
        return await self._advance_turn(state, tokens_used=0, tool_calls=[])

    async def check_repetition(
        self,
        handle: TurnHandle,
        action_hash: str,
    ) -> LoopSafetyState:
        state = self._require_open_turn(handle)
        state.action_window.append(action_hash)
        window = list(state.action_window)[-state.caps.repetition_window :]
        # A repetition is when the last N entries are identical.
        if (
            len(window) >= state.caps.repetition_window
            and len(set(window)) == 1
        ):
            state.terminal_status = "repetition"
            await self._publish(
                "repetition",
                handle,
                detail=f"action {action_hash!r} repeated {state.caps.repetition_window}x",
            )
            await self._record_terminal_memory(handle, status="repetition")
            return LoopSafetyState(
                status="repetition",
                detail=f"repeated {action_hash!r}",
                budget_remaining=state.read_only_budget_remaining,
            )
        return LoopSafetyState(
            status="ok",
            detail="",
            budget_remaining=state.read_only_budget_remaining,
        )

    # ── Health & lifecycle ────────────────────────────────────────────

    def is_healthy(self) -> bool:
        try:
            return not self._closed
        except Exception:  # noqa: BLE001 — sync + non-throwing per ADR-023 rule 5
            return False

    async def close(self) -> None:
        self._closed = True
        self._turns.clear()

    # ── Internal helpers ──────────────────────────────────────────────

    def _require_open_turn(self, handle: TurnHandle) -> _TurnState:
        state = self._turns.get(handle.turn_id)
        if state is None:
            raise KeyError(f"unknown turn_id {handle.turn_id!r}")
        if state.frozen_summary is not None:
            raise RuntimeError(
                f"turn {handle.turn_id!r} already ended — cannot record further"
            )
        return state

    async def _advance_turn(
        self,
        state: _TurnState,
        *,
        tokens_used: int,
        tool_calls: list[str],
    ) -> LoopSafetyState:
        state.turn_num += 1
        report = state.monitor.check_turn(
            turn_num=state.turn_num,
            tokens_used=tokens_used,
            tool_calls=tool_calls,
        )
        if report.state == LoopState.STOPPED:
            reason = report.stop_reason or StopReason.CIRCUIT_BREAKER
            status = _STOP_REASON_TO_STATUS[reason]
            state.terminal_status = status
            await self._publish(
                status,
                state.handle,
                detail=f"donor monitor stopped: {reason.value}",
            )
            await self._record_terminal_memory(state.handle, status=status)
            return LoopSafetyState(
                status=status,
                detail=reason.value,
                budget_remaining=state.read_only_budget_remaining,
            )
        if report.state == LoopState.WARNING:
            await self._publish("warn", state.handle, detail="donor monitor warning")
            return LoopSafetyState(
                status="warn",
                detail="approaching cap",
                budget_remaining=state.read_only_budget_remaining,
            )
        return LoopSafetyState(
            status="ok",
            detail="",
            budget_remaining=state.read_only_budget_remaining,
        )

    async def _publish(
        self,
        status: LoopSafetyStatus,
        handle: TurnHandle,
        *,
        detail: str,
        envelope_kind: str | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        kind = envelope_kind or f"loop_safety.{status}"
        try:
            envelope = EventEnvelope(
                event_type=kind,
                producer_plugin="tektos_loop_safety_adapter",
                payload={
                    "turn_id": handle.turn_id,
                    "agent_id": handle.agent_id,
                    "status": status,
                    "detail": detail,
                    "source": "tektos_loop_safety",
                    "correlation_id": handle.turn_id,
                },
            )
            await self._event_bus.publish(envelope)
        except Exception:  # noqa: BLE001 — never let bus faults escape enforcement path
            logger.exception(
                "loop_safety publish failed for turn %s (status=%s)",
                handle.turn_id,
                status,
            )

    async def _record_terminal_memory(
        self,
        handle: TurnHandle,
        *,
        status: LoopSafetyStatus,
    ) -> None:
        if self._memory is None:
            return
        try:
            await self._memory.write_event(
                subject=f"turn:{handle.turn_id}",
                predicate="terminated_with",
                object=status,
                provenance="loop_safety",
                confidence=1.0,
                attributes={
                    "agent_id": handle.agent_id,
                    "turn_id": handle.turn_id,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "loop_safety terminal memory write failed for turn %s",
                handle.turn_id,
            )
