"""Stage 11.16 slice F2b — replay mapper unit tests.

The mapper (kernel/tektos_replay.py) turns kernel event-bus envelopes into
the donor ``:8020`` replay shape the sessions page folds:
``[{seq, type, payload, protocol_version, created_at}]``.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import pytest

from kernel.tektos_replay import get_replay
from ports.event_envelope import EventEnvelope


def _run(bus: Any, session_id: str, count: int | None = None) -> list[dict[str, Any]]:
    """Sync shim for the async mapper (no running loop in these tests)."""
    return asyncio.run(get_replay(bus, session_id, count=count))


class FakeBus:
    """Publish/replay event bus with Valkey-like global entry ids.

    ``publish()`` assigns a monotonically increasing ms-seq id in publish
    order — exactly what Valkey's XADD ids do — so the mapper's
    lexicographic entry-id sort is exercised against real ordering, not
    against the mapper's own stream iteration order.
    """

    def __init__(self) -> None:
        self._streams: dict[str, list[tuple[str, EventEnvelope]]] = defaultdict(list)
        self._next_ms = 1000

    def publish(self, event_type: str, envelope: EventEnvelope) -> str:
        self._next_ms += 1000
        entry_id = f"{self._next_ms}-1"
        self._streams[event_type].append((entry_id, envelope))
        return entry_id

    async def read_recent(
        self, *, event_type: str, count: int | None = None
    ) -> list[tuple[str, EventEnvelope]]:
        items = self._streams.get(event_type, [])
        if count is not None:
            items = items[-count:]
        return list(items)


def _env(event_type: str, session_id: str, **payload: Any) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer_plugin="test",
        payload={"session_id": session_id, **payload},
        occurred_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
    )


def _one_turn(bus: FakeBus, session_id: str = "s-1") -> None:
    """Publish a realistic one-turn history in chronological order."""
    bus.publish("session.created", _env("session.created", session_id, model="m"))
    bus.publish(
        "tektos.agent.turn.started",
        _env("tektos.agent.turn.started", session_id, agent_id="a"),
    )
    bus.publish(
        "tektos.agent.turn.llm_completed",
        _env(
            "tektos.agent.turn.llm_completed",
            session_id,
            model="m",
            latency_ms=42,
            response_length=11,
            text="hello back",
        ),
    )
    bus.publish(
        "tektos.agent.turn.tool_call",
        _env("tektos.agent.turn.tool_call", session_id, tool="read_file", accepted=True),
    )
    bus.publish(
        "tektos.agent.turn.sandbox_completed",
        _env(
            "tektos.agent.turn.sandbox_completed",
            session_id,
            tool="read_file",
            exit_code=0,
            wall_seconds=0.5,
        ),
    )
    bus.publish(
        "tektos.agent.turn.completed",
        _env("tektos.agent.turn.completed", session_id, stop_reason="completed"),
    )


def test_replay_full_turn_donor_shape() -> None:
    bus = FakeBus()
    _one_turn(bus)
    rows = _run(bus, "s-1")
    types = [r["type"] for r in rows]
    assert types == [
        "session.created",
        "assistant.delta",
        "tool.started",
        "tool.completed",
        "assistant.completed",
    ]
    # seq is 1..N, ascending, regardless of bus retention.
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
    # Donor envelope keys present on every row.
    for r in rows:
        assert set(r) == {"seq", "type", "payload", "protocol_version", "created_at"}
    # The LLM text lands as assistant.delta — the UI's chat seed.
    delta = rows[1]
    assert delta["payload"]["text"] == "hello back"
    # tool.started carries the UI's tool_name key.
    assert rows[2]["payload"]["tool_name"] == "read_file"
    # sandbox ok maps to a "done" completion with diagnostic output.
    assert rows[3]["payload"]["status"] == "done"
    assert "exit_code=0" in rows[3]["payload"]["output"]
    assert rows[4]["payload"]["stop_reason"] == "completed"


def test_replay_filters_to_session() -> None:
    bus = FakeBus()
    _one_turn(bus, "s-1")
    # A foreign session publishes on the same streams, interleaved in time.
    bus.publish("session.created", _env("session.created", "s-2", model="m"))
    bus.publish(
        "tektos.agent.turn.llm_completed",
        _env("tektos.agent.turn.llm_completed", "s-2", text="other"),
    )
    bus.publish(
        "tektos.agent.turn.completed",
        _env("tektos.agent.turn.completed", "s-2", stop_reason="completed"),
    )
    rows = _run(bus, "s-1")
    assert len(rows) == 5  # turn.started is skipped (UI ignores it)
    # s-2's own replay only sees its own events.
    rows2 = _run(bus, "s-2")
    assert [r["type"] for r in rows2] == [
        "session.created",
        "assistant.delta",
        "assistant.completed",
    ]
    assert rows2[1]["payload"]["text"] == "other"


def test_replay_skips_turn_blocked() -> None:
    """turn.blocked → skipped; the vendor manager's session.failed carries it."""
    bus = FakeBus()
    bus.publish(
        "tektos.agent.turn.blocked",
        _env("tektos.agent.turn.blocked", "s-1", stage="thermal_preflight", level="red"),
    )
    bus.publish("session.failed", _env("session.failed", "s-1", error="thermal_red"))
    rows = _run(bus, "s-1")
    assert [r["type"] for r in rows] == ["session.failed"]


def test_replay_rejected_tool_maps_to_completed() -> None:
    bus = FakeBus()
    bus.publish(
        "tektos.agent.turn.tool_call",
        _env(
            "tektos.agent.turn.tool_call",
            "s-1",
            tool="exec",
            accepted=False,
            reason="immune_block",
        ),
    )
    rows = _run(bus, "s-1")
    assert len(rows) == 1
    assert rows[0]["type"] == "tool.completed"
    assert rows[0]["payload"]["status"] == "immune_block"


def test_replay_empty_session_returns_empty_list() -> None:
    bus = FakeBus()
    _one_turn(bus)
    assert _run(bus, "nope") == []


def test_replay_bad_stream_does_not_kill_replay() -> None:
    """One failing stream is skipped; the rest still come back."""

    class FlakyBus(FakeBus):
        async def read_recent(self, *, event_type, count=None):
            if event_type == "tektos.agent.turn.tool_call":
                raise RuntimeError("valkey down")
            return await super().read_recent(event_type=event_type, count=count)

    bus = FlakyBus()
    bus.publish(
        "tektos.agent.turn.llm_completed",
        _env("tektos.agent.turn.llm_completed", "s-1", text="still here"),
    )
    bus.publish(
        "tektos.agent.turn.tool_call",
        _env("tektos.agent.turn.tool_call", "s-1", tool="x", accepted=True),
    )
    rows = _run(bus, "s-1")
    assert [r["type"] for r in rows] == ["assistant.delta"]


@pytest.mark.parametrize("count", [None, 1000])
def test_replay_count_passthrough(count: int | None) -> None:
    bus = FakeBus()
    _one_turn(bus)
    rows = _run(bus, "s-1", count=count)
    assert len(rows) == 5  # turn.started is skipped (UI ignores it)
