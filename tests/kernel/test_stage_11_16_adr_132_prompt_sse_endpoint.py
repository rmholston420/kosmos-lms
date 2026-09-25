"""Stage 11.16 slice G2c — ADR-132 prompt/sse kernel endpoint tests.

``POST /api/prompt/sse`` used to proxy :8020. The kernel referent runs
the prompt through ``registry.tektos_turn_loop`` (Stage 8.2) and maps
the bus events to OpenAI ``chat.completion.chunk`` SSE frames
(:mod:`kernel.tektos_prompt_sse`). These tests drive the HTTP endpoint
with a real ``TektosSessionAdapter``, a fan-out bus, and a scripted fake
turn loop, and verify the exact bytes the sessions page parses.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adapters.session.tektos.adapter import TektosSessionAdapter
from kernel import app as kapp


class FanOutBus:
    """EventBusPort stand-in: publish fans out to per-type subscriber queues."""

    def __init__(self) -> None:
        self._subs: dict[str, list] = defaultdict(list)

    async def publish(self, envelope) -> str:
        for q in self._subs.get(envelope.event_type, []):
            q.put_nowait(envelope)
        return "1-1"

    def subscribe(self, event_type: str, *, maxsize: int = 0):
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs[event_type].append(q)
        return q

    def unsubscribe(self, event_type: str, queue) -> None:
        subs = self._subs.get(event_type)
        if subs and queue in subs:
            subs.remove(queue)

    async def read_recent(self, *, event_type, count=None):
        return []

    async def is_healthy(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ScriptedLoop:
    """Fake TektosTurnLoop: publishes a scripted event sequence per turn."""

    def __init__(self, bus: FanOutBus, script: list[tuple[str, dict[str, Any]]]) -> None:
        self._bus = bus
        self._script = script
        self.calls: list[dict[str, Any]] = []

    async def run_turn(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        for event_type, extra in self._script:
            payload = {"source": "tektos_runtime", "agent_id": kwargs.get("agent_id", ""), **extra}

            class _Env:
                pass

            env = _Env()
            env.event_type = event_type
            env.payload = payload
            await self._bus.publish(env)
            await asyncio.sleep(0.01)


class _ClosableClient:
    """TestClient wrapper that closes the session adapter on exit."""

    def __init__(self, client: TestClient, port: TektosSessionAdapter) -> None:
        self.client = client
        self._port = port

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def close(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._port.close())
        finally:
            loop.close()


def _client(
    bus: FanOutBus, loop: ScriptedLoop, monkeypatch: pytest.MonkeyPatch
) -> _ClosableClient:
    port = TektosSessionAdapter(event_bus=bus)
    monkeypatch.setattr(kapp.registry, "session", port)
    monkeypatch.setattr(kapp.registry, "event_bus", bus)
    monkeypatch.setattr(kapp.registry, "tektos_turn_loop", loop)
    return _ClosableClient(TestClient(kapp.app), port)


def _post_sse(
    client: _ClosableClient, sid: str, prompt: str, **extra: Any
) -> tuple[list[dict], bool]:
    """POST prompt/sse, parse the SSE stream into data objects.

    Returns ``(frames, done)`` — ``done`` is True when the OpenAI
    ``[DONE]`` sentinel terminated the stream (donor parity).
    """
    with client.stream(
        "POST",
        "/api/prompt/sse",
        json={"session_id": sid, "prompt": prompt, **extra},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        frames: list[dict] = []
        done = False
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                done = True
                continue
            frames.append(json.loads(data))
    return frames, done


def _create(client: _ClosableClient) -> str:
    return client.post(
        "/api/sessions", json={"model": "qwen3.8-27b-code", "cwd": "/tmp"}
    ).json()["id"]


def test_prompt_sse_full_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FanOutBus()
    loop = ScriptedLoop(
        bus,
        [
            ("tektos.agent.turn.started", {"session_id": "SIDPLACEHOLDER"}),
            (
                "tektos.agent.turn.llm_completed",
                {"session_id": "SIDPLACEHOLDER", "text": "hello from kernel"},
            ),
            ("tektos.agent.turn.completed", {"session_id": "SIDPLACEHOLDER"}),
        ],
    )
    c = _client(bus, loop, monkeypatch)
    try:
        sid = _create(c)
        # patch the scripted events to the real session id
        loop._script = [
            (et, {**extra, "session_id": sid}) for et, extra in loop._script
        ]
        frames, done = _post_sse(c, sid, "hi there")
        assert done  # donor-parity [DONE] sentinel
        contents = [
            f["choices"][0]["delta"].get("content")
            for f in frames
            if f["choices"][0]["delta"].get("content")
        ]
        assert contents == ["hello from kernel"]
        assert frames[-1]["choices"][0]["finish_reason"] == "stop"
        assert frames[-1]["choices"][0]["delta"] == {}
        assert all(f["object"] == "chat.completion.chunk" for f in frames)
        assert all(f["model"] == "qwen3.8-27b-code" for f in frames)
        # The loop ran the turn with the right session and prompt.
        assert loop.calls[0]["session_id"] == sid
        assert loop.calls[0]["prompt"] == "hi there"
    finally:
        c.close()


def test_prompt_sse_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = FanOutBus()
    loop = ScriptedLoop(bus, [])
    c = _client(bus, loop, monkeypatch)
    try:
        # 422: missing prompt
        assert c.post("/api/prompt/sse", json={"session_id": "x"}).status_code == 422
        # 404: unknown session
        r = c.post("/api/prompt/sse", json={"session_id": "nope", "prompt": "hi"})
        assert r.status_code == 404
        # 503: turn loop offline
        monkeypatch.setattr(kapp.registry, "tektos_turn_loop", None)
        sid = _create(c)
        r = c.post("/api/prompt/sse", json={"session_id": sid, "prompt": "hi"})
        assert r.status_code == 503
        assert "turn loop offline" in r.json()["detail"]
    finally:
        c.close()


def test_prompt_sse_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = FanOutBus()
    loop = ScriptedLoop(
        bus, [("tektos.agent.turn.completed", {"session_id": "X"})]
    )
    c = _client(bus, loop, monkeypatch)
    try:
        sid = _create(c)
        loop._script = [(et, {**extra, "session_id": sid}) for et, extra in loop._script]
        frames, done = _post_sse(c, sid, "hi", model="granite4.1-8b-instruct")
        assert all(f["model"] == "granite4.1-8b-instruct" for f in frames)
    finally:
        c.close()


def test_prompt_sse_session_port_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kapp.registry, "session", None)
    c = TestClient(kapp.app)
    r = c.post("/api/prompt/sse", json={"session_id": "x", "prompt": "hi"})
    assert r.status_code == 503
