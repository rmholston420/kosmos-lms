"""Stage 11.16 slice E — ADR-132 kernel-native model-switch.

The sessions page previously proxied ``:8020/api/sessions/{id}/model`` —
the *standalone* Tektos engine's ModelRequest handler. The kernel referent
is ``registry.session`` booted with ``KOSMOS_SESSION=tektos``
(``TektosSessionAdapter``). A *Tektos* session carries its model as first-
class lineage, so the mutation goes through the adapter's vendor layer
(``switch_model`` → ``session.updated`` event) — the generic ADR-103
SessionPort has no model setter.

These tests install a real ``TektosSessionAdapter`` with a recording
in-memory event bus and verify:

* ``POST /api/sessions/{id}/model`` → donor shape ``{ok, model, old_model}``
* the session's model is mutated (GET /api/sessions reflects it)
* a ``session.updated`` envelope with ``{"changes": {"model": …, "from": …}}``
  is published (replay-visible)
* 404 unknown session, 422 missing model, 503 offline port
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adapters.session.tektos.adapter import TektosSessionAdapter
from kernel import app as kapp


class RecordingEventBus:
    """Minimal EventBusPort stand-in that records published envelopes."""

    def __init__(self) -> None:
        self.published: list[Any] = []

    def publish(self, envelope: dict[str, Any]) -> Any:
        self.published.append(envelope)
        return None


@pytest.fixture()
def event_bus() -> RecordingEventBus:
    return RecordingEventBus()


@pytest.fixture()
def client(event_bus: RecordingEventBus, monkeypatch: pytest.MonkeyPatch):
    """Kernel app with a real TektosSessionAdapter + recording bus."""
    port = TektosSessionAdapter(event_bus=event_bus)
    monkeypatch.setattr(kapp.registry, "session", port)
    yield TestClient(kapp.app)
    # Unbind module-level vendor bindings so other tests start clean.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(port.close())
    finally:
        loop.close()


def _create(client: TestClient, model: str = "qwen3.8-27b-code") -> str:
    return client.post(
        "/api/sessions", json={"model": model, "cwd": "/tmp"}
    ).json()["id"]


# ── Happy path ─────────────────────────────────────────────────────────────


def test_switch_model_donor_shape(client: TestClient) -> None:
    sid = _create(client, model="qwen3.8-27b-code")
    r = client.post(f"/api/sessions/{sid}/model", json={"model": "granite4.1-8b-instruct"})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "ok": True,
        "model": "granite4.1-8b-instruct",
        "old_model": "qwen3.8-27b-code",
    }


def test_switch_model_mutates_session(client: TestClient) -> None:
    sid = _create(client, model="qwen3.8-27b-code")
    client.post(f"/api/sessions/{sid}/model", json={"model": "granite4.1-8b-instruct"})
    listed = client.get("/api/sessions").json()
    assert [s for s in listed if s["id"] == sid][0]["model"] == "granite4.1-8b-instruct"


def test_switch_model_publishes_session_updated(
    client: TestClient, event_bus: RecordingEventBus
) -> None:
    sid = _create(client, model="qwen3.8-27b-code")
    event_bus.published.clear()
    client.post(f"/api/sessions/{sid}/model", json={"model": "granite4.1-8b-instruct"})
    updated = [
        e for e in event_bus.published if getattr(e, "event_type", None) == "session.updated"
    ]
    assert len(updated) == 1
    changes = updated[0].payload["changes"]
    assert changes == {"model": "granite4.1-8b-instruct", "from": "qwen3.8-27b-code"}
    assert updated[0].payload["session_id"] == sid


def test_switch_model_to_same_model_is_idempotent(client: TestClient) -> None:
    sid = _create(client, model="qwen3.8-27b-code")
    r = client.post(f"/api/sessions/{sid}/model", json={"model": "qwen3.8-27b-code"})
    assert r.json() == {
        "ok": True,
        "model": "qwen3.8-27b-code",
        "old_model": "qwen3.8-27b-code",
    }


# ── Error paths ────────────────────────────────────────────────────────────


def test_switch_model_unknown_session_404(client: TestClient) -> None:
    r = client.post(
        "/api/sessions/nope-123/model", json={"model": "granite4.1-8b-instruct"}
    )
    assert r.status_code == 404


def test_switch_model_missing_model_422(client: TestClient) -> None:
    sid = _create(client)
    assert client.post(f"/api/sessions/{sid}/model", json={}).status_code == 422
    assert client.post(f"/api/sessions/{sid}/model", json={"model": ""}).status_code == 422


def test_offline_port_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kapp.registry, "session", None)
    c = TestClient(kapp.app)
    r = c.post("/api/sessions/whatever/model", json={"model": "m"})
    assert r.status_code == 503
    assert "KOSMOS_SESSION=tektos" in r.json()["detail"]


def test_non_tektos_port_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic inmemory port has no model lineage → 503, not a silent
    no-op: model-switch is a Tektos-referent capability."""
    from adapters.session.inmemory.adapter import InMemorySessionAdapter

    monkeypatch.setattr(kapp.registry, "session", InMemorySessionAdapter())
    c = TestClient(kapp.app)
    sid = c.post("/api/sessions", json={"model": "m"}).json()["id"]
    r = c.post(f"/api/sessions/{sid}/model", json={"model": "other"})
    assert r.status_code == 503
