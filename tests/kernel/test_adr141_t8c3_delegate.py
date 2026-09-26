"""T8c-3 — donor POST /api/delegate → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:4065.

Shape (donor wire, preserved):
  POST /api/delegate  {session_id, goal, context?, timeout?}
    -> {subagent_id, status: "started", goal}

Kernel referent: the donor spawns a FRESH sub-session via
``session_manager.create_session`` and awaits ``runtime_sdk.submit_prompt``
(the request's session_id/timeout are accepted but unused — that donor
quirk is preserved). Kernel: ``registry.session.create_session`` +
``await registry.tektos_turn_loop.run_turn`` (ADR-104 turn loop is the
kernel referent for the donor's submit_prompt). Subagent prompt is the
donor's verbatim GOAL/CONTEXT/WORKFLOW template.
"""

from __future__ import annotations

import asyncio
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


class RecordingLoop:
    """Fake TektosTurnLoop: records run_turn kwargs, no bus traffic needed."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_turn(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch):
    bus = FanOutBus()
    loop = RecordingLoop()
    port = TektosSessionAdapter(event_bus=bus)
    monkeypatch.setattr(kapp.registry, "session", port)
    monkeypatch.setattr(kapp.registry, "event_bus", bus)
    monkeypatch.setattr(kapp.registry, "tektos_turn_loop", loop)
    client = TestClient(kapp.app)
    yield client, port, loop
    loop2 = asyncio.new_event_loop()
    try:
        loop2.run_until_complete(port.close())
    finally:
        loop2.close()


def test_delegate_donor_wire_shape(harness):
    client, port, loop = harness
    r = client.post("/api/delegate", json={"goal": "refactor the parser"})
    assert r.status_code == 200
    body = r.json()
    for k in ("subagent_id", "status", "goal"):
        assert k in body, f"missing donor key {k}"
    assert body["status"] == "started"
    assert body["goal"] == "refactor the parser"
    # a FRESH sub-session was created and is retrievable
    sub = asyncio.new_event_loop().run_until_complete(
        port.get_session(body["subagent_id"])
    )
    assert sub is not None


def test_delegate_prompt_is_donor_template(harness):
    client, port, loop = harness
    r = client.post(
        "/api/delegate",
        json={"goal": "ship the report", "context": "Q3 numbers in data/"},
    )
    assert r.status_code == 200
    assert len(loop.calls) == 1
    call = loop.calls[0]
    prompt = call["prompt"]
    # donor verbatim template markers
    assert "You are a subagent working on a specific subtask." in prompt
    assert "GOAL: ship the report" in prompt
    assert "CONTEXT: Q3 numbers in data/" in prompt
    assert "WORKFLOW:" in prompt
    assert "1. Analyze the goal and plan your approach" in prompt
    assert "5. Return a concise summary of what you accomplished" in prompt
    assert "Do not deviate from the task" in prompt
    assert call["system_prompt"] == (
        "You are a specialized subagent. Complete your assigned task "
        "efficiently."
    )
    # run_turn is bound to the fresh sub-session, not the request's
    assert call["session_id"] == r.json()["subagent_id"]


def test_delegate_context_default(harness):
    client, port, loop = harness
    r = client.post("/api/delegate", json={"goal": "x"})
    assert r.status_code == 200
    assert "CONTEXT: No additional context provided." in loop.calls[0]["prompt"]


def test_delegate_requires_goal(harness):
    client, port, loop = harness
    assert client.post("/api/delegate", json={}).status_code == 422
    assert client.post("/api/delegate", json={"goal": ""}).status_code == 422
    assert loop.calls == []


def test_delegate_loop_offline_503(harness, monkeypatch: pytest.MonkeyPatch):
    client, port, loop = harness
    monkeypatch.setattr(kapp.registry, "tektos_turn_loop", None)
    r = client.post("/api/delegate", json={"goal": "x"})
    assert r.status_code == 503
