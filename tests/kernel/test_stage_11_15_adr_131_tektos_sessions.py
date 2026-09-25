"""Stage 11.15 — ADR-131 kernel-native Tektos session lifecycle.

The sessions page previously proxied ``:8020/api/sessions*`` — the
*standalone* Tektos engine's SessionManager. The kernel referent is
``registry.session`` booted with ``KOSMOS_SESSION=tektos``
(``TektosSessionAdapter`` — the fidelity port of the donor SessionManager
behind the ADR-103 SessionPort contract). A *Tektos* session (model, cwd,
tag, fork lineage, per-session FSM history) is deliberately NOT served by
the generic inmemory adapter — that one is kernel plumbing without
model/title/root lineage.

These tests install a fresh ``InMemorySessionAdapter`` on
``registry.session`` (any SessionPort works — the endpoints speak the
port contract) and verify the donor-compatible response shapes:

* ``GET /api/sessions`` → raw array (the page's SessionInfo elements)
* ``POST /api/sessions`` → ``{id, title, model, cwd, status}``
* ``GET /api/sessions/{id}`` → donor fields + ADR-103 ``state``/``state_history``
* ``PATCH /api/sessions/{id}`` → rename (donor shape)
* ``POST .../archive|interrupt`` → ``{ok: true}``
* ``POST .../fork`` → ``{id, title, model, status, parent_title}``
* ``DELETE ...`` → ``{ok, events_deleted}``, 404 for unknown
* 503 when the port is offline (``registry.session is None``)

GPU-free, no Postgres, no env gates.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adapters.session.inmemory.adapter import InMemorySessionAdapter
from kernel import app as kapp


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Kernel app with a fresh in-memory SessionPort installed."""
    port = InMemorySessionAdapter()
    monkeypatch.setattr(kapp.registry, "session", port)
    return TestClient(kapp.app)


@pytest.fixture()
def offline_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Kernel app with the session port deliberately offline."""
    monkeypatch.setattr(kapp.registry, "session", None)
    return TestClient(kapp.app)


# ── 503 when offline ───────────────────────────────────────────────────────


def test_offline_returns_503(offline_client: TestClient) -> None:
    assert offline_client.get("/api/sessions").status_code == 503
    r = offline_client.post("/api/sessions", json={"model": "m"})
    assert r.status_code == 503
    assert "KOSMOS_SESSION=tektos" in r.json()["detail"]


# ── List ───────────────────────────────────────────────────────────────────


def test_list_empty_is_raw_array(client: TestClient) -> None:
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_list_element_schema_is_session_info(client: TestClient) -> None:
    sid = client.post(
        "/api/sessions", json={"model": "qwen3.8-27b-code", "cwd": "/tmp"}
    ).json()["id"]
    body = client.get("/api/sessions").json()
    assert isinstance(body, list) and len(body) == 1
    e = body[0]
    for key in (
        "id", "model", "cwd", "status", "title", "tag", "root_session_id",
        "created_at", "updated_at", "is_active", "is_failed", "is_archived",
    ):
        assert key in e, f"missing {key}"
    assert e["id"] == sid
    assert e["model"] == "qwen3.8-27b-code"
    assert e["status"] == "ready"
    assert e["is_active"] is True
    assert e["is_archived"] is False


# ── Create ─────────────────────────────────────────────────────────────────


def test_create_returns_donor_shape(client: TestClient) -> None:
    r = client.post(
        "/api/sessions",
        json={"model": "m1", "cwd": "/tmp", "permission_mode": "auto"},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"id", "title", "model", "cwd", "status"}
    assert body["model"] == "m1"
    assert body["cwd"] == "/tmp"
    assert body["status"] == "ready"


def test_create_requires_model(client: TestClient) -> None:
    assert client.post("/api/sessions", json={}).status_code == 422
    assert client.post("/api/sessions", json={"cwd": "/tmp"}).status_code == 422


# ── Get (donor fields + FSM audit superset) ────────────────────────────────


def test_get_includes_state_audit(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    body = client.get(f"/api/sessions/{sid}").json()
    # donor fields
    assert body["id"] == sid and body["model"] == "m1"
    # ADR-103 superset — the referent detail inmemory plumbing lacks
    assert body["state"] == "ready"
    assert body["state_history"] and body["state_history"][0]["to"] == "ready"


def test_get_unknown_404(client: TestClient) -> None:
    assert client.get("/api/sessions/nope").status_code == 404


# ── Rename (PATCH — donor shape) ───────────────────────────────────────────


def test_rename_patch(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    r = client.patch(f"/api/sessions/{sid}", json={"title": "my session"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "my session"
    assert set(body.keys()) == {"id", "title", "model", "status", "is_archived", "tag"}
    assert client.get(f"/api/sessions/{sid}").json()["title"] == "my session"


def test_rename_requires_title(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    assert client.patch(f"/api/sessions/{sid}", json={}).status_code == 422
    assert client.patch("/api/sessions/nope", json={"title": "x"}).status_code == 404


# ── Archive ────────────────────────────────────────────────────────────────


def test_archive(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/archive")
    assert r.status_code == 200 and r.json() == {"ok": True}
    live = client.get("/api/sessions").json()
    archived = client.get("/api/sessions", params={"archived": True}).json()
    assert all(s["id"] != sid for s in live)
    assert [s["id"] for s in archived] == [sid]
    assert archived[0]["is_archived"] is True


def test_archive_unknown_404(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/archive").status_code == 404


# ── Interrupt (donor no-op semantics) ──────────────────────────────────────


def test_interrupt_not_running_is_ok(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/interrupt")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_interrupt_unknown_404(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/interrupt").status_code == 404


# ── Fork ───────────────────────────────────────────────────────────────────


def test_fork_returns_donor_shape(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    client.patch(f"/api/sessions/{sid}", json={"title": "original"})
    r = client.post(f"/api/sessions/{sid}/fork", json={"model": "m2"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"id", "title", "model", "status", "parent_title"}
    assert body["parent_title"] == "original"
    # Donor wraps the vendor's "fork of <title>" prefix again — the UI
    # only reads ``id`` from this response, so assert the donor string.
    assert body["title"].startswith("Fork of fork of original")
    assert body["model"] == "m2"
    assert body["id"] != sid
    # fork lineage: child's root_session_id points at the parent
    child = client.get(f"/api/sessions/{body['id']}").json()
    assert child["root_session_id"] == sid


def test_fork_defaults_model(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/fork", json={})
    assert r.status_code == 200
    assert r.json()["model"] == "default"


def test_fork_unknown_404(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/fork", json={}).status_code == 404


# ── Delete ─────────────────────────────────────────────────────────────────


def test_delete(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"model": "m1"}).json()["id"]
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "events_deleted": 0}
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.get("/api/sessions").json() == []


def test_delete_unknown_404(client: TestClient) -> None:
    assert client.delete("/api/sessions/nope").status_code == 404


# ── Full lifecycle ordering (create → fork → archive → delete) ─────────────


def test_lifecycle_happy_path(client: TestClient) -> None:
    created = client.post("/api/sessions", json={"model": "m1"}).json()
    sid = created["id"]
    forked = client.post(f"/api/sessions/{sid}/fork", json={"model": "m1"}).json()
    assert len(client.get("/api/sessions").json()) == 2
    assert client.post(f"/api/sessions/{forked['id']}/archive").json() == {"ok": True}
    assert len(client.get("/api/sessions").json()) == 1
    assert len(client.get("/api/sessions", params={"archived": True}).json()) == 1
    assert client.delete(f"/api/sessions/{sid}").json()["ok"] is True
    assert len(client.get("/api/sessions").json()) == 0
