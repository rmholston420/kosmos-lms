"""T8b-4 — donor GET /api/search → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:4203.

Shape (donor-verbatim):
  GET /api/search?query=...&limit=...
    -> {"sessions": [{"id": str, "title": str, "tag": str}], "events": [...]}
    error path -> {"error": str, "sessions": [], "events": []} (200)

Wiring (layering rule): sessions from the T2c session port
(registry.session.search_sessions); events from the ADR-141 T2b replay
substrate — new kernel.tektos_replay.search_events_global (cross-session
substring search over the bus, donor FTS5-fallback semantics, donor row
shape {session_id, seq, type, payload, created_at}).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import kernel.app as ka  # noqa: E402
from ports.event_envelope import EventEnvelope


class _FakeBus:
    """Minimal event bus: read_recent per event type (valkey-style rows)."""

    def __init__(self, rows_by_type: dict[str, list[tuple[str, EventEnvelope]]]):
        self._rows = rows_by_type

    async def read_recent(
        self, *, event_type: str, count: int | None = None
    ) -> list[tuple[str, EventEnvelope]]:
        rows = list(self._rows.get(event_type, []))
        if count is not None:
            rows = rows[-count:]
        return rows


class _FakeSessionPort:
    def __init__(self, sessions: list[Any]):
        self._sessions = sessions

    async def search_sessions(self, *, query: str, sort: str = "updated_at",
                              order: str = "desc") -> list[Any]:
        if not query:
            return []
        q = query.lower()
        return [
            s for s in self._sessions
            if q in (s.title or "").lower() or q in (s.tag or "").lower()
            or q in (s.id or "").lower()
        ]


def _env(payload: dict[str, Any], seq: int) -> EventEnvelope:
    return EventEnvelope(
        event_type="tektos.agent.turn.llm_completed",
        producer_plugin="tektos",
        payload=payload,
        occurred_at=datetime(2026, 9, 26, 1, 0, seq, tzinfo=timezone.utc),
    )


def test_search_sessions_and_events(client_shape):
    client, registry = client_shape
    rows = {
        "tektos.agent.turn.llm_completed": [
            ("1-1", _env({"session_id": "s1", "text": "hello world"}, 1)),
            ("1-2", _env({"session_id": "s2", "text": "goodbye"}, 2)),
        ]
    }
    from kernel.tektos_replay import REPLAY_EVENT_TYPES

    assert "tektos.agent.turn.llm_completed" in REPLAY_EVENT_TYPES
    registry.event_bus = _FakeBus(rows)
    from ports.session import LiveSession

    registry.session = _FakeSessionPort(
        [LiveSession(id="s1", model="m", cwd="/", title="World talk", tag="alpha")]
    )
    try:
        r = client.get("/api/search", params={"query": "world"})
        assert r.status_code == 200
        body = r.json()
        assert body["sessions"] == [{"id": "s1", "title": "World talk", "tag": "alpha"}]
        assert len(body["events"]) == 1
        ev = body["events"][0]
        assert set(ev) == {"session_id", "seq", "type", "payload", "created_at"}
        assert ev["session_id"] == "s1"
        assert ev["type"] == "assistant.delta"
    finally:
        registry.event_bus = None
        registry.session = None


def test_search_empty_query_returns_empty_lists(client_shape):
    client, registry = client_shape
    r = client.get("/api/search", params={"query": ""})
    assert r.status_code == 200
    assert r.json() == {"sessions": [], "events": []}


def test_search_no_match_empty(client_shape):
    client, registry = client_shape
    registry.event_bus = _FakeBus({})
    registry.session = _FakeSessionPort([])
    try:
        body = client.get("/api/search", params={"query": "zzz-none"}).json()
        assert body == {"sessions": [], "events": []}
    finally:
        registry.event_bus = None
        registry.session = None


def test_search_limit_caps_events(client_shape):
    client, registry = client_shape
    rows = {
        "tektos.agent.turn.llm_completed": [
            (f"1-{i}", _env({"session_id": f"s{i}", "text": f"hit {i}"}, i))
            for i in range(5)
        ]
    }
    registry.event_bus = _FakeBus(rows)
    registry.session = _FakeSessionPort([])
    try:
        body = client.get("/api/search", params={"query": "hit", "limit": 3}).json()
        assert len(body["events"]) == 3
        # newest first
        assert body["events"][0]["payload"]["text"] == "hit 4"
    finally:
        registry.event_bus = None
        registry.session = None


@pytest.fixture()
def client_shape():
    from fastapi.testclient import TestClient
    from kernel.app import registry

    with TestClient(ka.app) as c:
        yield c, registry
