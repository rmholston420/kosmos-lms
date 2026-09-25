"""Stage 11.16 slice F2c — ADR-132 kernel-native replay endpoint.

``GET /api/sessions/{id}/replay`` used to proxy ``:8020`` (the standalone
engine's event store). The kernel referent: the session's lifecycle events
live on the event bus (Valkey in prod), and the turn loop publishes
``tektos.agent.turn.*`` to the same bus. The endpoint reads the known
Tektos event types off the bus, filters to the session, and maps to the
donor chat-event shape (kernel/tektos_replay.py).

These tests install a real ``TektosSessionAdapter`` plus a recording bus
that also supports ``read_recent`` (the slice E recording bus only
records), so the endpoint's full path — port gate, 404, bus read, mapper —
is exercised end to end.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adapters.session.tektos.adapter import TektosSessionAdapter
from kernel import app as kapp
from ports.event_envelope import EventEnvelope


class RecordingReplayBus:
    """Records publishes AND supports read_recent (per-type streams).

    Entry ids are a global monotonically increasing ms-seq counter in
    publish order — Valkey's XADD id semantics.
    """

    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []
        self._streams: dict[str, list[tuple[str, EventEnvelope]]] = defaultdict(list)
        self._next_ms = 1_700_000_000_000  # 13 digits, like a real 2026 timestamp

    def publish(self, envelope: EventEnvelope) -> str:
        self._next_ms += 1
        entry_id = f"{self._next_ms}-1"
        self.published.append(envelope)
        self._streams[envelope.event_type].append((entry_id, envelope))
        return entry_id

    async def read_recent(
        self, *, event_type: str, count: int | None = None
    ) -> list[tuple[str, EventEnvelope]]:
        items = self._streams.get(event_type, [])
        if count is not None:
            items = items[-count:]
        return list(items)


@pytest.fixture()
def bus() -> RecordingReplayBus:
    return RecordingReplayBus()


@pytest.fixture()
def client(bus: RecordingReplayBus, monkeypatch: pytest.MonkeyPatch):
    """Kernel app with a real TektosSessionAdapter + recording/replay bus."""
    port = TektosSessionAdapter(event_bus=bus)
    monkeypatch.setattr(kapp.registry, "session", port)
    monkeypatch.setattr(kapp.registry, "event_bus", bus)
    yield TestClient(kapp.app)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(port.close())
    finally:
        loop.close()


def _create(client: TestClient, model: str = "qwen3.8-27b-code") -> str:
    return client.post(
        "/api/sessions", json={"model": model, "cwd": "/tmp"}
    ).json()["id"]


def _publish_turn(bus: RecordingReplayBus, sid: str) -> None:
    """Simulate one turn the way the turn loop publishes it."""
    from datetime import datetime, timezone

    def env(et: str, **payload: Any) -> EventEnvelope:
        return EventEnvelope(
            event_type=et,
            producer_plugin="tektos_runtime",
            payload={"session_id": sid, "source": "tektos_runtime", **payload},
            occurred_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
        )

    bus.publish(env("tektos.agent.turn.started", agent_id="a", tool_calls_planned=1))
    bus.publish(
        env(
            "tektos.agent.turn.llm_completed",
            model="m",
            latency_ms=10,
            response_length=5,
            text="hi back",
        )
    )
    bus.publish(env("tektos.agent.turn.tool_call", tool="read_file", accepted=True))
    bus.publish(
        env(
            "tektos.agent.turn.sandbox_completed",
            tool="read_file",
            exit_code=0,
            wall_seconds=0.1,
        )
    )
    bus.publish(env("tektos.agent.turn.completed", stop_reason="completed"))


# ── Happy path ─────────────────────────────────────────────────────────────


def test_replay_lifecycle_after_create(client: TestClient) -> None:
    """A freshly created session replays its lifecycle events, donor shape.

    The vendor's create_session transitions CREATED → READY but only
    publishes ``session.created``; ``session.ready`` is WS-only (the
    kernel has no WS), so the replay is exactly one row.
    """
    sid = _create(client)
    r = client.get(f"/api/sessions/{sid}/replay")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    types = [row["type"] for row in rows]
    assert types == ["session.created"]
    for row in rows:
        assert set(row) == {"seq", "type", "payload", "protocol_version", "created_at"}
    assert [row["seq"] for row in rows] == [1]
    assert rows[0]["payload"]["model"] == "qwen3.8-27b-code"


def test_replay_full_turn_maps_to_chat_events(
    client: TestClient, bus: RecordingReplayBus
) -> None:
    sid = _create(client)
    _publish_turn(bus, sid)
    rows = client.get(f"/api/sessions/{sid}/replay").json()
    types = [row["type"] for row in rows]
    assert types == [
        "session.created",
        "assistant.delta",
        "tool.started",
        "tool.completed",
        "assistant.completed",
    ]
    # The LLM text is the chat seed.
    assert rows[1]["payload"]["text"] == "hi back"
    # turn.started and sandbox diagnostics are folded into donor types.
    assert rows[2]["payload"]["tool_name"] == "read_file"
    assert rows[3]["payload"]["status"] == "done"
    assert rows[4]["payload"]["stop_reason"] == "completed"
    # Ordering: lifecycle before the turn, seq strictly ascending.
    assert [row["seq"] for row in rows] == list(range(1, len(rows) + 1))


def test_replay_model_switch_visible(client: TestClient) -> None:
    """Slice E's session.updated shows up in replay as a passthrough row."""
    sid = _create(client)
    client.post(f"/api/sessions/{sid}/model", json={"model": "granite4.1-8b-instruct"})
    rows = client.get(f"/api/sessions/{sid}/replay").json()
    updated = [row for row in rows if row["type"] == "session.updated"]
    assert len(updated) == 1
    assert updated[0]["payload"]["changes"] == {
        "model": "granite4.1-8b-instruct",
        "from": "qwen3.8-27b-code",
    }


def test_replay_excludes_other_sessions(client: TestClient, bus: RecordingReplayBus) -> None:
    sid_a = _create(client)
    sid_b = _create(client)
    _publish_turn(bus, sid_b)
    rows_a = client.get(f"/api/sessions/{sid_a}/replay").json()
    assert all(row["payload"].get("session_id") != sid_b for row in rows_a)
    types_a = [row["type"] for row in rows_a]
    assert types_a == ["session.created"]
    rows_b = client.get(f"/api/sessions/{sid_b}/replay").json()
    assert "assistant.delta" in [row["type"] for row in rows_b]


# ── Error paths ────────────────────────────────────────────────────────────


def test_replay_unknown_session_404(client: TestClient) -> None:
    assert client.get("/api/sessions/nope-123/replay").status_code == 404


def test_replay_port_offline_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kapp.registry, "session", None)
    c = TestClient(kapp.app)
    assert c.get("/api/sessions/whatever/replay").status_code == 503


def test_replay_bus_offline_503(
    monkeypatch: pytest.MonkeyPatch, bus: RecordingReplayBus
) -> None:
    port = TektosSessionAdapter(event_bus=bus)
    monkeypatch.setattr(kapp.registry, "session", port)
    monkeypatch.setattr(kapp.registry, "event_bus", None)
    c = TestClient(kapp.app)
    sid = c.post("/api/sessions", json={"model": "m", "cwd": "/tmp"}).json()["id"]
    r = c.get(f"/api/sessions/{sid}/replay")
    assert r.status_code == 503
    assert "event bus offline" in r.json()["detail"]
