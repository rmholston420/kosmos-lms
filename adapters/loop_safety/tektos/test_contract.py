"""Contract test for TektosLoopSafetyAdapter (ADR-080, ADR-088, ADR-092).

Two tiers:
1. Protocol conformance — the adapter satisfies ``LoopSafetyPort`` at
   runtime (``isinstance`` check against ``runtime_checkable`` Protocol).
2. Adapter-specific behavioural tests — ADR-088 read-only budget
   interlock, terminal-state event + memory writes, per-turn isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from adapters.loop_safety.tektos.adapter import TektosLoopSafetyAdapter
from ports.event_envelope import EventEnvelope
from ports.loop_safety import LoopCaps, LoopSafetyPort


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return envelope.event_id


@dataclass
class _MemoryCall:
    subject: str
    predicate: str
    object: str
    provenance: str
    confidence: float
    attributes: dict


class _RecordingMemory:
    def __init__(self) -> None:
        self.writes: list[_MemoryCall] = []

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict | None = None,
    ) -> str:
        self.writes.append(
            _MemoryCall(
                subject=subject,
                predicate=predicate,
                object=object,
                provenance=provenance,
                confidence=confidence,
                attributes=attributes or {},
            )
        )
        return f"mem-{len(self.writes)}"


# ── Protocol conformance ─────────────────────────────────────────────────


def test_adapter_satisfies_loop_safety_port_protocol() -> None:
    adapter = TektosLoopSafetyAdapter()
    assert isinstance(adapter, LoopSafetyPort)


# ── ADR-088 read-only budget interlock ───────────────────────────────────


@pytest.mark.asyncio
async def test_read_only_budget_exhausts_after_configured_calls() -> None:
    bus = _RecordingBus()
    memory = _RecordingMemory()
    adapter = TektosLoopSafetyAdapter(
        default_caps=LoopCaps(read_only_budget=3),
        event_bus=bus,
        memory=memory,
    )
    handle = await adapter.begin_turn(agent_id="tektos-t1")

    # First 2 read-only calls succeed with decreasing budget.
    state1 = await adapter.record_tool_call(handle, read_only=True)
    assert state1.status == "ok"
    assert state1.budget_remaining == 2

    state2 = await adapter.record_tool_call(handle, read_only=True)
    assert state2.status == "ok"
    assert state2.budget_remaining == 1

    # 3rd call brings budget to 0 → status flips to budget_exhausted.
    state3 = await adapter.record_tool_call(handle, read_only=True)
    assert state3.status == "budget_exhausted"
    assert state3.budget_remaining == 0

    # ADR-080 rule 1: state transition publishes on EventBusPort.
    kinds = [env.event_type for env in bus.published]
    assert "loop_safety.read_only_budget_exhausted" in kinds

    # ADR-080 rule 2: terminal state writes MemoryPort with provenance=loop_safety, conf=1.0.
    terminal_mem = [w for w in memory.writes if w.provenance == "loop_safety"]
    assert len(terminal_mem) == 1
    assert terminal_mem[0].confidence == 1.0
    assert terminal_mem[0].object == "budget_exhausted"

    summary = await adapter.end_turn(handle)
    assert summary.terminal_status == "budget_exhausted"
    assert summary.read_only_calls == 3


@pytest.mark.asyncio
async def test_non_read_only_calls_do_not_consume_budget() -> None:
    adapter = TektosLoopSafetyAdapter(
        default_caps=LoopCaps(read_only_budget=2),
    )
    handle = await adapter.begin_turn(agent_id="tektos-t2")
    for _ in range(5):
        state = await adapter.record_tool_call(handle, read_only=False)
        assert state.budget_remaining == 2  # never decrements
    assert state.status == "ok"


@pytest.mark.asyncio
async def test_budget_resets_across_turns() -> None:
    adapter = TektosLoopSafetyAdapter(
        default_caps=LoopCaps(read_only_budget=1),
    )
    h1 = await adapter.begin_turn(agent_id="tektos-t3")
    state1 = await adapter.record_tool_call(h1, read_only=True)
    assert state1.status == "budget_exhausted"

    h2 = await adapter.begin_turn(agent_id="tektos-t3")
    # New turn resets the budget per ADR-088.
    state2 = await adapter.record_tool_call(h2, read_only=True)
    assert state2.status == "budget_exhausted"
    # But this was a NEW turn — first call.
    summary = await adapter.end_turn(h2)
    assert summary.read_only_calls == 1


@pytest.mark.asyncio
async def test_end_turn_is_idempotent() -> None:
    adapter = TektosLoopSafetyAdapter()
    handle = await adapter.begin_turn(agent_id="tektos-t4")
    s1 = await adapter.end_turn(handle)
    s2 = await adapter.end_turn(handle)
    assert s1 is s2 or (s1.turn_id == s2.turn_id and s1.ended_at == s2.ended_at)


@pytest.mark.asyncio
async def test_repetition_terminates_turn_and_publishes() -> None:
    bus = _RecordingBus()
    memory = _RecordingMemory()
    adapter = TektosLoopSafetyAdapter(
        default_caps=LoopCaps(repetition_window=3),
        event_bus=bus,
        memory=memory,
    )
    handle = await adapter.begin_turn(agent_id="tektos-t5")
    await adapter.check_repetition(handle, "same-action")
    await adapter.check_repetition(handle, "same-action")
    final = await adapter.check_repetition(handle, "same-action")
    assert final.status == "repetition"
    assert any(env.event_type == "loop_safety.repetition" for env in bus.published)
    assert any(w.object == "repetition" for w in memory.writes)


@pytest.mark.asyncio
async def test_close_is_idempotent_and_flips_health() -> None:
    adapter = TektosLoopSafetyAdapter()
    assert adapter.is_healthy() is True
    await adapter.close()
    await adapter.close()  # idempotent
    assert adapter.is_healthy() is False
    with pytest.raises(RuntimeError):
        await adapter.begin_turn(agent_id="tektos-t6")
