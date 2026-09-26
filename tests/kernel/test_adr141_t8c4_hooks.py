"""T8c-4 — donor hooks ×2 → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:5101 (GET /api/hooks),
:5117 (POST /api/hooks/fire). Substrate: donor runtime/hooks.py (325 LOC,
self-contained) — verbatim port to kernel/hooks.py, booted as
``registry.hook_manager`` (kernel/app.py, after model_router; resource
monitor = kernel thermal watchdog, which lacks check_thermal_limit so the
thermal guard is NOT registered — the donor's own hasattr guard degrades
gracefully; a monitor that exposes it does get the guard, see
test_hooks_fire_thermal_guard_when_referent_exposes_limit).

Wire preserved:
  GET  /api/hooks        -> {hooks: [{event_type, handlers[]}]};
                            {error: str} at 200 when system off (donor shape)
  POST /api/hooks/fire   {event_type, ...} -> {event_type, results:
                            [{outcome, message, blocking, data}]}
                            422 missing event_type; 503 system off
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from kernel import app as kapp
from kernel.hooks import HookManager


class FakeMonitor:
    """Resource-monitor stand-in exposing check_thermal_limit (the donor's
    guard registers only when the referent has it)."""

    def __init__(self, allow: bool) -> None:
        self._allow = allow

    def check_thermal_limit(self) -> bool:
        return self._allow


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch):
    hm = HookManager()
    monkeypatch.setattr(kapp.registry, "hook_manager", hm)
    client = TestClient(kapp.app)
    yield client, hm


def test_hooks_list_donor_wire_shape(harness):
    client, _ = harness
    r = client.get("/api/hooks")
    assert r.status_code == 200
    body = r.json()
    assert "hooks" in body
    events = {h["event_type"]: h["handlers"] for h in body["hooks"]}
    # 4 builtins; no resource_monitor → thermal guard not registered
    assert set(events) == {
        "tool.before",
        "tool.after",
        "session.created",
        "prompt.before",
    }
    assert "_audit_log_tool" in events["tool.before"]
    assert "_validate_prompt" in events["prompt.before"]


def test_hooks_list_manager_none_error_at_200(harness, monkeypatch: pytest.MonkeyPatch):
    client, _ = harness
    monkeypatch.setattr(kapp.registry, "hook_manager", None)
    r = client.get("/api/hooks")
    # Donor shape: error dict in the body, HTTP 200 (not an HTTP error)
    assert r.status_code == 200
    assert r.json() == {"error": "Hook system not initialized"}


def test_hooks_fire_donor_wire_shape(harness):
    client, _ = harness
    r = client.post(
        "/api/hooks/fire",
        json={
            "event_type": "tool.before",
            "session_id": "s1",
            "tool_name": "shell",
            "tool_input": {"cmd": "ls"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "tool.before"
    assert len(body["results"]) == 1
    res = body["results"][0]
    for k in ("outcome", "message", "blocking", "data"):
        assert k in res
    assert res["outcome"] == "continue"
    assert res["blocking"] is False


def test_hooks_fire_thermal_guard_when_referent_exposes_limit(
    harness, monkeypatch: pytest.MonkeyPatch
):
    client, _ = harness
    hm = HookManager(resource_monitor=FakeMonitor(allow=False))
    monkeypatch.setattr(kapp.registry, "hook_manager", hm)
    r = client.post(
        "/api/hooks/fire",
        json={"event_type": "tool.before", "session_id": "s1", "tool_name": "shell"},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    aborts = [x for x in results if x["outcome"] == "abort"]
    assert len(aborts) == 1
    assert aborts[0]["blocking"] is True
    assert aborts[0]["data"] == {"reason": "thermal_limit"}


def test_hooks_fire_empty_prompt_aborts(harness):
    client, _ = harness
    r = client.post(
        "/api/hooks/fire",
        json={"event_type": "prompt.before", "session_id": "s1", "metadata": {"prompt_text": ""}},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert any(
        x["outcome"] == "abort"
        and x["blocking"]
        and x["message"] == "Empty prompt rejected"
        for x in results
    )


def test_hooks_fire_requires_event_type(harness):
    client, _ = harness
    assert client.post("/api/hooks/fire", json={}).status_code == 422
    assert client.post("/api/hooks/fire", json={"event_type": ""}).status_code == 422


def test_hooks_fire_manager_none_503(harness, monkeypatch: pytest.MonkeyPatch):
    client, _ = harness
    monkeypatch.setattr(kapp.registry, "hook_manager", None)
    assert (
        client.post("/api/hooks/fire", json={"event_type": "tool.before"}).status_code
        == 503
    )


def test_hooks_fire_unknown_event_empty_results(harness):
    client, _ = harness
    r = client.post("/api/hooks/fire", json={"event_type": "no.such.event"})
    assert r.status_code == 200
    assert r.json() == {"event_type": "no.such.event", "results": []}
