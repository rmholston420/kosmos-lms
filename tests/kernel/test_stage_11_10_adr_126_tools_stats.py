"""Stage 11.10 — ADR-126 tools tests: /api/tools.

Kernel-native Tektos tools status (replaces the ADR-109 gateway proxy to
:8020, whose executable TektosToolRegistry list has no kernel referent).
The kernel's real tools surface is the Tektos Tool Router (ADR-107,
routing-only) + the static capability table. Execution stays on the
standalone engine — the endpoint must report that honestly.

Tests run GPU-free: no network, no Postgres. The registry is faked per
test; the router is the REAL ``TektosToolRouter`` (routing-only, so it
works without relational_memory).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from kernel.app import app
from plugins.tektos.executor.engine import TektosToolRouter


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kernel.app import registry

    # Isolate: no router by default (the ADR-107 off state).
    monkeypatch.setattr(registry, "tektos_tool_router", None, raising=False)
    return TestClient(app)


# ── Degraded state (router off — the default) ─────────────────────────────


def test_tools_router_off_degraded(client: TestClient) -> None:
    r = client.get("/api/tools")
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "degraded"
    assert o["healthy"] is False
    assert o["tools"]["wired"] is False
    # The static capability table is reported even when the router is off.
    assert o["tools"]["known_tools"] == 13
    assert o["tools"]["categories"] == {
        "terminal": 3,
        "file_operations": 5,
        "search": 1,
        "web": 3,
        "delegation": 1,
    }
    assert o["tools"]["routes_buffered"] is None
    assert o["tools"]["recent_routes"] == []
    assert "standalone Tektos registry" in o["tools"]["execution"]
    assert o["errors"] == []


def test_tools_capability_table_has_known_names(client: TestClient) -> None:
    o = client.get("/api/tools").json()
    names = o["tools"]["known_tool_names"]
    assert "bash" in names
    assert "file_read" in names
    assert "web_search" in names
    assert "delegate_task" in names
    assert names == sorted(names)  # deterministic order


# ── Wired state (router on) — real router, real routes ────────────────────


def test_tools_router_wired_empty(client: TestClient) -> None:
    from kernel.app import registry

    registry.tektos_tool_router = TektosToolRouter()
    try:
        r = client.get("/api/tools")
    finally:
        registry.tektos_tool_router = None
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "initialized"
    assert o["healthy"] is True
    assert o["tools"]["wired"] is True
    assert o["tools"]["routes_buffered"] == 0
    assert o["tools"]["recent_routes"] == []
    assert o["errors"] == []


def test_tools_router_wired_with_routes(client: TestClient) -> None:
    from kernel.app import registry

    router = TektosToolRouter()
    # Drive two real routes through the router (no persistence needed).
    r1, _ = asyncio.run(
        router.route(session_id="s1", task_description="run a shell command")
    )
    r2, _ = asyncio.run(
        router.route_for_tools(
            session_id="s1",
            tools_needed=("file_read", "unknown_tool"),
            task_description="read the file",
        )
    )
    assert r1.primary_tool == "bash"
    assert r2.unrouted_tools == ("unknown_tool",)

    registry.tektos_tool_router = router
    try:
        r = client.get("/api/tools")
    finally:
        registry.tektos_tool_router = None
    o = r.json()
    assert o["healthy"] is True
    assert o["tools"]["routes_buffered"] == 2
    recent = o["tools"]["recent_routes"]
    assert len(recent) == 2
    # Newer route last (deque order).
    assert recent[-1]["primary_tool"] == "file_read"
    assert recent[-1]["unrouted_tools"] == ["unknown_tool"]
    assert recent[0]["primary_tool"] == "bash"
    assert recent[0]["category"] == "terminal"
    for route in recent:
        assert route["id"] is not None
        assert route["created_at"] is not None


def test_tools_router_raising_degrades_partially(client: TestClient) -> None:
    from kernel.app import registry

    class _BoomRouter:
        def list_recent(self, limit: int = 10) -> tuple:
            raise RuntimeError("boom")

    registry.tektos_tool_router = _BoomRouter()
    try:
        r = client.get("/api/tools")
    finally:
        registry.tektos_tool_router = None
    assert r.status_code == 200  # always-200, never 500
    o = r.json()
    assert o["healthy"] is True  # router present
    assert o["tools"]["wired"] is True
    assert any("router query failed" in e for e in o["errors"])
    assert o["tools"]["recent_routes"] == []
    assert o["tools"]["routes_buffered"] is None
