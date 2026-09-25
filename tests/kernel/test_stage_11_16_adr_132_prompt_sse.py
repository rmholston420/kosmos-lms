"""Stage 11.16 slice G2a — ADR-132 prompt/sse SSE module tests.

Exercises :mod:`kernel.tektos_prompt_sse` end to end with a fake bus
(in-process fan-out, no Valkey) and a fake turn loop: the generator
subscribes to the turn/session stream types, runs the turn as a task,
maps the session's events to OpenAI ``chat.completion.chunk`` frames in
the donor wire format, and closes on the terminal turn event.

Live tests (user rule): the frame mapping is verified against the exact
bytes the sessions page parses — ``data:`` lines, ``choices[0].delta.content``,
``finish_reason`` — plus the donor's tool_call delta shape.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import pytest

from kernel.tektos_prompt_sse import map_envelope, sse_frame, stream_prompt_sse
from ports.event_envelope import EventEnvelope


class FanOutBus:
    """EventBusPort stand-in: publish fans out to per-type subscriber queues."""

    def __init__(self) -> None:
        self._subs: dict[str, list] = defaultdict(list)
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        for q in self._subs.get(envelope.event_type, []):
            q.put_nowait(envelope)
        return f"1-{len(self.published)}"

    def subscribe(self, event_type: str, *, maxsize: int = 0):
        q: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=maxsize)
        self._subs[event_type].append(q)
        return q

    def unsubscribe(self, event_type: str, queue) -> None:
        subs = self._subs.get(event_type)
        if subs and queue in subs:
            subs.remove(queue)

    # EventBusPort surface (unused by the SSE module, present for conformance)
    async def read_recent(self, *, event_type, count=None):
        return []

    async def is_healthy(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakeTurnLoop:
    """Publishes a scripted event sequence like the real turn loop would."""

    def __init__(self, bus: FanOutBus, script: list[tuple[str, dict[str, Any]]]) -> None:
        self._bus = bus
        self._script = script
        self.started: list[dict[str, Any]] = []

    async def run_turn(self, **kwargs: Any) -> Any:
        self.started.append(kwargs)
        for event_type, extra in self._script:
            payload: dict[str, Any] = {
                "source": "tektos_runtime",
                "agent_id": kwargs.get("agent_id", ""),
                **extra,
            }
            env = EventEnvelope(
                event_type=event_type,
                producer_plugin="tektos_runtime",
                payload=payload,
                occurred_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
            )
            await self._bus.publish(env)
            await asyncio.sleep(0.01)  # let the generator drain between events
        return None


def _env(event_type: str, **payload: Any) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer_plugin="tektos_runtime",
        payload=payload,
        occurred_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
    )


def _parse_frames(raw: list[str]) -> list[tuple[str, dict]]:
    """Split raw SSE text into (event_name, data_obj) — the UI's protocol.

    ``data: [DONE]`` (the OpenAI stream sentinel, donor parity) is not
    JSON; the UI skips it, so this parser does too. Use
    :func:`_has_done` to assert the sentinel separately.
    """
    out: list[tuple[str, dict]] = []
    for frame in raw:
        event = ""
        for line in frame.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            if line.startswith("data: "):
                data = line[6:].strip()
                if data == "[DONE]":
                    continue
                out.append((event, json.loads(data)))
    return out


def _has_done(raw: list[str]) -> bool:
    """True if the OpenAI ``[DONE]`` sentinel terminated the stream."""
    return any(
        "data: [DONE]" in frame for frame in raw
    )


SID = "abcdef01-2345-6789-abcd-ef0123456789"


async def _collect(frames: Any) -> list[str]:
    out = []
    async for frame in frames:
        out.append(frame)
    return out


# ── Wire format ────────────────────────────────────────────────────────────


def test_sse_frame_format() -> None:
    frame = sse_frame({"id": "x"}, event="hermes.tool.progress")
    assert frame == 'event: hermes.tool.progress\ndata: {"id": "x"}\n\n'
    frame = sse_frame({"id": "x"})
    assert frame == 'data: {"id": "x"}\n\n'


def test_llm_completed_maps_to_content_chunk() -> None:
    env = _env(
        "tektos.agent.turn.llm_completed",
        session_id=SID,
        model="m",
        response_length=2,
        text="hi",
    )
    frame, terminal = map_envelope(
        env, session_id=SID, completion_id="chatcmpl-abcdef01", created=1, model="m"
    )
    assert not terminal
    assert frame is not None
    parsed = json.loads(frame.splitlines()[0][6:])
    assert parsed["object"] == "chat.completion.chunk"
    assert parsed["id"] == "chatcmpl-abcdef01"
    choice = parsed["choices"][0]
    assert choice["delta"]["content"] == "hi"
    assert choice["finish_reason"] is None


def test_turn_completed_maps_to_finish_chunk() -> None:
    env = _env(
        "tektos.agent.turn.completed", session_id=SID, stop_reason="tool_limit"
    )
    frame, terminal = map_envelope(
        env, session_id=SID, completion_id="c", created=1, model="m"
    )
    assert terminal
    assert frame is not None
    parsed = json.loads(frame.splitlines()[0][6:])
    assert parsed["choices"][0]["finish_reason"] == "tool_limit"
    assert parsed["choices"][0]["delta"] == {}


def test_turn_failed_maps_to_error_chunk() -> None:
    env = _env(
        "tektos.agent.turn.failed", session_id=SID, reason="llm_timeout"
    )
    frame, terminal = map_envelope(
        env, session_id=SID, completion_id="c", created=1, model="m"
    )
    assert terminal
    assert frame is not None
    parsed = json.loads(frame.splitlines()[0][6:])
    assert parsed["choices"][0]["finish_reason"] == "error"
    assert parsed["error"]["type"] == "agent_error"
    assert "llm_timeout" in parsed["error"]["message"]


def test_tool_call_maps_to_tool_delta() -> None:
    env = _env(
        "tektos.agent.turn.tool_call", session_id=SID, tool="read_file"
    )
    frame, terminal = map_envelope(
        env, session_id=SID, completion_id="c", created=1, model="m"
    )
    assert not terminal
    assert frame is not None
    parsed = json.loads(frame.splitlines()[0][6:])
    tool = parsed["choices"][0]["delta"]["tool_calls"][0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "read_file"


def test_other_session_events_ignored() -> None:
    env = _env(
        "tektos.agent.turn.llm_completed",
        session_id="other-session",
        text="not for us",
    )
    frame, terminal = map_envelope(
        env, session_id=SID, completion_id="c", created=1, model="m"
    )
    assert frame is None
    assert not terminal


def test_noise_events_map_to_no_frame() -> None:
    for event_type in (
        "tektos.agent.turn.started",
        "tektos.agent.turn.tool_call.rejected",
        "tektos.agent.turn.sandbox_completed",
        "tektos.agent.turn.interrupted",
        "session.updated",
    ):
        env = _env(event_type, session_id=SID)
        frame, terminal = map_envelope(
            env, session_id=SID, completion_id="c", created=1, model="m"
        )
        assert frame is None and not terminal, event_type


# ── Generator end to end ───────────────────────────────────────────────────


async def _full_turn_scenario() -> None:
    bus = FanOutBus()
    loop = FakeTurnLoop(
        bus,
        [
            ("tektos.agent.turn.started", {"session_id": SID}),
            (
                "tektos.agent.turn.llm_completed",
                {"session_id": SID, "model": "m", "text": "hello world"},
            ),
            ("tektos.agent.turn.tool_call", {"session_id": SID, "tool": "grep"}),
            (
                "tektos.agent.turn.llm_completed",
                {"session_id": SID, "model": "m", "text": "done."},
            ),
            ("tektos.agent.turn.completed", {"session_id": SID, "stop_reason": "completed"}),
        ],
    )
    raw = await _collect(
        stream_prompt_sse(
            bus=bus, loop=loop, session_id=SID, prompt="say hi", model="m"
        )
    )
    frames = _parse_frames(raw)
    assert _has_done(raw)  # donor-parity [DONE] sentinel
    assert all(event == "" for event, _ in frames)  # no custom event names
    contents = [
        d["choices"][0]["delta"].get("content")
        for _, d in frames
        if d["choices"][0]["delta"].get("content") is not None
    ]
    assert contents == ["hello world", "done."]
    # The turn's tool activity appears as a tool_call delta.
    tool_deltas = [
        d
        for _, d in frames
        if "tool_calls" in d["choices"][0]["delta"]
    ]
    assert len(tool_deltas) == 1
    assert tool_deltas[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "grep"
    # Terminal frame carries the stop reason.
    last = frames[-1][1]
    assert last["choices"][0]["finish_reason"] == "completed"
    assert last["choices"][0]["delta"] == {}
    # The loop received the session and prompt.
    assert loop.started[0]["session_id"] == SID
    assert loop.started[0]["prompt"] == "say hi"


def test_full_turn_scenario() -> None:
    asyncio.run(_full_turn_scenario())


async def _blocked_scenario() -> None:
    """An immune-blocked turn still produces a terminal error frame."""
    bus = FanOutBus()
    loop = FakeTurnLoop(
        bus,
        [
            (
                "tektos.agent.turn.blocked",
                {"session_id": SID, "stage": "prompt_scan", "reason": "prompt blocked"},
            ),
        ],
    )
    raw = await _collect(
        stream_prompt_sse(
            bus=bus, loop=loop, session_id=SID, prompt="bad prompt", model="m"
        )
    )
    frames = _parse_frames(raw)
    assert len(frames) == 1
    last = frames[0][1]
    assert last["choices"][0]["finish_reason"] == "error"
    assert "prompt blocked" in last["error"]["message"]


def test_blocked_scenario() -> None:
    asyncio.run(_blocked_scenario())


async def _session_failed_scenario() -> None:
    """A session.failed lifecycle event terminates the stream."""
    bus = FanOutBus()
    loop = FakeTurnLoop(
        bus,
        [
            (
                "tektos.agent.turn.llm_completed",
                {"session_id": SID, "text": "partial"},
            ),
            ("session.failed", {"session_id": SID, "error": "sandbox died"}),
        ],
    )
    raw = await _collect(
        stream_prompt_sse(
            bus=bus, loop=loop, session_id=SID, prompt="x", model="m"
        )
    )
    frames = _parse_frames(raw)
    assert frames[0][1]["choices"][0]["delta"]["content"] == "partial"
    last = frames[-1][1]
    assert last["choices"][0]["finish_reason"] == "error"
    assert "sandbox died" in last["error"]["message"]


def test_session_failed_scenario() -> None:
    asyncio.run(_session_failed_scenario())


async def _cleanup_scenario() -> None:
    """Subscriptions are removed after the stream ends."""
    bus = FanOutBus()
    loop = FakeTurnLoop(
        bus, [("tektos.agent.turn.completed", {"session_id": SID})]
    )
    await _collect(
        stream_prompt_sse(
            bus=bus, loop=loop, session_id=SID, prompt="x", model="m"
        )
    )
    assert all(not subs for subs in bus._subs.values())


def test_cleanup_scenario() -> None:
    asyncio.run(_cleanup_scenario())


async def _other_sessions_no_crosstalk() -> None:
    """Concurrent other-session traffic on the same bus is filtered out."""
    bus = FanOutBus()

    async def other_traffic() -> None:
        for i in range(3):
            await bus.publish(
                _env(
                    "tektos.agent.turn.llm_completed",
                    session_id="other",
                    text=f"other-{i}",
                )
            )
            await asyncio.sleep(0.005)

    loop = FakeTurnLoop(
        bus,
        [
            (
                "tektos.agent.turn.llm_completed",
                {"session_id": SID, "text": "mine"},
            ),
            ("tektos.agent.turn.completed", {"session_id": SID, "stop_reason": "completed"}),
        ],
    )
    other_task = asyncio.create_task(other_traffic())
    raw = await _collect(
        stream_prompt_sse(
            bus=bus, loop=loop, session_id=SID, prompt="x", model="m"
        )
    )
    other_task.cancel()
    contents = [
        d["choices"][0]["delta"].get("content")
        for _, d in _parse_frames(raw)
        if d["choices"][0]["delta"].get("content") is not None
    ]
    assert contents == ["mine"]


def test_other_sessions_no_crosstalk() -> None:
    asyncio.run(_other_sessions_no_crosstalk())
