"""ADR-134 slice H2a+H2c — kernel.tektos_hindsight mapper + endpoint tests.

GPU-free: fake ``httpx.AsyncClient`` injected by monkeypatch (the module
imports httpx at call time, so patching the class covers both the mapper
and the endpoint).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kernel import app as kernel_app  # noqa: E402


# ---------------------------------------------------------------------------
# Fake httpx
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://fake"),
                response=httpx.Response(self.status_code),
            )


class _RecallState:
    """Mutable state shared by the fake client instance (test-visible)."""

    posts: list[tuple[str, dict[str, Any]]] = []
    payload: dict[str, Any] = {
        "results": [
            {
                "id": "e1",
                "content": "tagged fact",
                "tags": ["tektos-session"],
                "created_at": "2026-09-25T01:00:00Z",
            },
            {
                "id": "e2",
                "content": "untagged fact",
                "tags": [],
                "created_at": "2026-09-25T00:59:00Z",
            },
            {
                "id": "e3",
                "content": "third",
                "tags": ["other"],
                "created_at": "2026-09-25T00:58:00Z",
            },
        ]
    }


class FakeAsyncClient:
    """Records POSTs; returns ``_RecallState.payload`` for recall."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _RecallState.posts = []

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get(self, url: str) -> _FakeResponse:
        return _FakeResponse({"status": "healthy"})

    async def post(
        self, url: str, json: dict[str, Any] | None = None
    ) -> _FakeResponse:
        _RecallState.posts.append((url, json or {}))
        return _FakeResponse(_RecallState.payload)


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.delenv("KOSMOS_HINDSIGHT_URL", raising=False)
    monkeypatch.delenv("KOSMOS_HINDSIGHT_PROFILE", raising=False)
    monkeypatch.delenv("KOSMOS_HINDSIGHT_BANK", raising=False)
    transport = ASGITransport(app=kernel_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Mapper (H2a)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_recall_uses_default_profile_bank_and_sentinel() -> None:
    from kernel.tektos_hindsight import _recall

    monkey = pytest.MonkeyPatch()
    monkey.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkey.delenv("KOSMOS_HINDSIGHT_URL", raising=False)
    try:
        results = await _recall("", limit=10)
    finally:
        monkey.undo()
    assert [r["id"] for r in results] == ["e1", "e2", "e3"]
    url, body = _RecallState.posts[-1]
    assert url == (
        "http://127.0.0.1:9178/v1/default/banks/default/memories/recall"
    )
    # empty query → donor's neutral sentinel (v1 rejects empty with 422)
    assert body == {"query": "tektos"}


@pytest.mark.anyio
async def test_experiences_tag_preferring_order() -> None:
    from kernel.tektos_hindsight import get_experiences

    monkey = pytest.MonkeyPatch()
    monkey.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        rows = await get_experiences(context="tektos-session", limit=10)
    finally:
        monkey.undo()
    # tagged item first, then the rest, truncated to limit
    assert [r["id"] for r in rows] == ["e1", "e2", "e3"]
    assert rows[0]["tags"] == ["tektos-session"]


@pytest.mark.anyio
async def test_experiences_limit_truncation() -> None:
    from kernel.tektos_hindsight import get_experiences

    monkey = pytest.MonkeyPatch()
    monkey.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        rows = await get_experiences(context="tektos-session", limit=1)
    finally:
        monkey.undo()
    assert [r["id"] for r in rows] == ["e1"]


# ---------------------------------------------------------------------------
# Endpoints (H2b)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_status_endpoint_donor_shape(client) -> None:
    r = await client.get("/api/hindsight/status")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "hindsight"
    assert body["status"] == "connected"
    assert body["healthy"] is True
    assert body["base_url"] == "http://127.0.0.1:9178"
    # donor-identity additions
    assert body["bank_id"] == "default"
    assert body["profile"] == "default"


@pytest.mark.anyio
async def test_experiences_endpoint_raw_list(client) -> None:
    r = await client.get("/api/hindsight/experiences", params={"limit": 10})
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert [row["id"] for row in rows] == ["e1", "e2", "e3"]
    url, body = _RecallState.posts[-1]
    assert body == {"query": "tektos"}


@pytest.mark.anyio
async def test_experiences_context_query_forwarded(client) -> None:
    r = await client.get(
        "/api/hindsight/experiences", params={"context": "tektos-session"}
    )
    assert r.status_code == 200
    _url, body = _RecallState.posts[-1]
    assert body == {"query": "tektos-session"}


@pytest.mark.anyio
async def test_experiences_503_when_daemon_down(client, monkeypatch) -> None:
    class DownClient(FakeAsyncClient):
        async def post(self, url: str, json: dict[str, Any] | None = None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", DownClient)
    r = await client.get("/api/hindsight/experiences")
    assert r.status_code == 503
    assert "unreachable" in r.json()["detail"]
