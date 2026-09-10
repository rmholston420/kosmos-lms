"""Protocol conformance test for LoopSafetyPort (ADR-080, ADR-088).

Any adapter satisfying ``LoopSafetyPort`` MUST pass this test. Fast tier —
no network. Uses a stub adapter that implements minimum viable state
tracking so we exercise the Protocol shape and port-level guards.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from ports.loop_safety import (
    LoopCaps,
    LoopSafetyPort,
    LoopSafetyState,
    TurnHandle,
    TurnSummary,
    validate_loop_caps,
)


class _StubLoopSafetyAdapter:
    """Minimal LoopSafetyPort implementation used only for protocol tests."""

    def __init__(self, caps: LoopCaps | None = None) -> None:
        self._caps = caps or LoopCaps()
        self._closed = False
        self._budget: dict[str, int] = {}
        self._tokens: dict[str, int] = {}
        self._tool_calls: dict[str, int] = {}
        self._read_only_calls: dict[str, int] = {}
        self._terminal: dict[str, str] = {}
        self._summaries: dict[str, TurnSummary] = {}

    async def begin_turn(
        self,
        agent_id: str,
        config: LoopCaps | None = None,
    ) -> TurnHandle:
        validate_loop_caps(config or self._caps)
        handle = TurnHandle(
            turn_id=f"t-{len(self._budget)}",
            agent_id=agent_id,
            started_at=datetime.now(timezone.utc),
        )
        self._budget[handle.turn_id] = (config or self._caps).read_only_budget
        self._tokens[handle.turn_id] = 0
        self._tool_calls[handle.turn_id] = 0
        self._read_only_calls[handle.turn_id] = 0
        self._terminal[handle.turn_id] = "ok"
        return handle

    async def end_turn(self, handle: TurnHandle) -> TurnSummary:
        if handle.turn_id in self._summaries:
            return self._summaries[handle.turn_id]
        summary = TurnSummary(
            turn_id=handle.turn_id,
            ended_at=datetime.now(timezone.utc),
            tokens_total=self._tokens[handle.turn_id],
            tool_calls=self._tool_calls[handle.turn_id],
            read_only_calls=self._read_only_calls[handle.turn_id],
            terminal_status=self._terminal[handle.turn_id],  # type: ignore[arg-type]
        )
        self._summaries[handle.turn_id] = summary
        return summary

    async def record_tokens(self, handle: TurnHandle, tokens: int) -> LoopSafetyState:
        self._tokens[handle.turn_id] += tokens
        return LoopSafetyState(
            status="ok",
            detail="",
            budget_remaining=self._budget[handle.turn_id],
        )

    async def record_tool_call(
        self,
        handle: TurnHandle,
        *,
        read_only: bool,
    ) -> LoopSafetyState:
        self._tool_calls[handle.turn_id] += 1
        if not read_only:
            return LoopSafetyState(
                status="ok",
                detail="non-read-only",
                budget_remaining=self._budget[handle.turn_id],
            )
        # Read-only path: consume budget.
        if self._budget[handle.turn_id] <= 0:
            self._terminal[handle.turn_id] = "budget_exhausted"
            return LoopSafetyState(
                status="budget_exhausted",
                detail="ADR-088",
                budget_remaining=0,
            )
        self._budget[handle.turn_id] -= 1
        self._read_only_calls[handle.turn_id] += 1
        return LoopSafetyState(
            status="ok",
            detail="",
            budget_remaining=self._budget[handle.turn_id],
        )

    async def check_repetition(
        self,
        handle: TurnHandle,
        action_hash: str,
    ) -> LoopSafetyState:
        return LoopSafetyState(
            status="ok",
            detail="",
            budget_remaining=self._budget[handle.turn_id],
        )

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True


def test_stub_adapter_satisfies_protocol_runtime_checkable() -> None:
    assert isinstance(_StubLoopSafetyAdapter(), LoopSafetyPort)


def test_loop_caps_defaults_match_adr_088_and_spec_25_7() -> None:
    caps = LoopCaps()
    # ADR-088 default read-only budget.
    assert caps.read_only_budget == 10
    # Spec §25.7 caps.
    assert caps.max_turns == 15
    assert caps.max_tokens_total == 65_536
    assert caps.max_wall_time_seconds == 300
    assert caps.repetition_window == 3


def test_validate_loop_caps_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        validate_loop_caps(LoopCaps(max_turns=0))
    with pytest.raises(ValueError):
        validate_loop_caps(LoopCaps(read_only_budget=-1))


def test_begin_turn_resets_read_only_budget() -> None:
    adapter = _StubLoopSafetyAdapter(LoopCaps(read_only_budget=3))

    async def _run() -> int:
        h = await adapter.begin_turn("agent-a")
        state = await adapter.record_tool_call(h, read_only=True)
        return state.budget_remaining

    assert asyncio.run(_run()) == 2


def test_read_only_budget_exhausts_on_over_use() -> None:
    adapter = _StubLoopSafetyAdapter(LoopCaps(read_only_budget=2))

    async def _run() -> tuple[str, str, str]:
        h = await adapter.begin_turn("agent-a")
        s1 = await adapter.record_tool_call(h, read_only=True)
        s2 = await adapter.record_tool_call(h, read_only=True)
        s3 = await adapter.record_tool_call(h, read_only=True)
        return s1.status, s2.status, s3.status

    s1, s2, s3 = asyncio.run(_run())
    assert s1 == "ok"
    assert s2 == "ok"
    assert s3 == "budget_exhausted"


def test_non_read_only_tool_call_does_not_consume_budget() -> None:
    adapter = _StubLoopSafetyAdapter(LoopCaps(read_only_budget=2))

    async def _run() -> int:
        h = await adapter.begin_turn("agent-a")
        # Ten non-read-only calls MUST NOT touch the read-only budget (ADR-088).
        for _ in range(10):
            await adapter.record_tool_call(h, read_only=False)
        state = await adapter.record_tool_call(h, read_only=True)
        return state.budget_remaining

    assert asyncio.run(_run()) == 1


def test_end_turn_is_idempotent() -> None:
    adapter = _StubLoopSafetyAdapter()

    async def _run() -> tuple[TurnSummary, TurnSummary]:
        h = await adapter.begin_turn("agent-a")
        s1 = await adapter.end_turn(h)
        s2 = await adapter.end_turn(h)
        return s1, s2

    s1, s2 = asyncio.run(_run())
    assert s1 == s2


def test_is_healthy_never_raises() -> None:
    adapter = _StubLoopSafetyAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False


def test_close_is_idempotent() -> None:
    adapter = _StubLoopSafetyAdapter()

    async def _run() -> None:
        await adapter.close()
        await adapter.close()

    asyncio.run(_run())
