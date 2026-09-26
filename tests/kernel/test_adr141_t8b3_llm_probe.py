"""T8b-3 — donor POST /api/llm/probe → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:4590.

Shape (donor-verbatim):
  POST /api/llm/probe
    -> {"llm_available": bool, "base_url": str|None, "model": str|None}

Wiring (layering rule): the donor runs a real GET /models against its
single configured backend. The kernel's registry.llm (ADR-132
FailoverLLMAdapter) already performs the real per-backend probe via
is_healthy() — which also engages the fallback when the primary is down —
so the route is a thin surface over that existing substrate (no new
client, no new probe logic).
"""

from __future__ import annotations

import pytest

import kernel.app as ka  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    with TestClient(ka.app) as c:
        yield c


def test_probe_shape(client):
    r = client.post("/api/llm/probe")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"llm_available", "base_url", "model"}
    assert isinstance(body["llm_available"], bool)
    # the kernel's primary lane (:8090 llama.cpp) is live on this host
    assert body["llm_available"] is True
    assert body["base_url"]
    assert body["model"]


def test_probe_matches_llm_status_lane(client):
    probe = client.post("/api/llm/probe").json()
    status = client.get("/api/llm/status").json()
    # same live lane, same reported values
    assert probe["base_url"] == status.get("base_url")
    assert probe["model"] == status.get("model")


def test_probe_none_registry(client, monkeypatch):
    from kernel.app import registry

    saved = registry.llm
    monkeypatch.setattr(registry, "llm", None, raising=False)
    try:
        r = client.post("/api/llm/probe")
        assert r.status_code == 200
        assert r.json() == {"llm_available": False, "base_url": None, "model": None}
    finally:
        registry.llm = saved
