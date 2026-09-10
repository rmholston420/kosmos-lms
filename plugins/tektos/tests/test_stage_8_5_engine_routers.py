"""Stage 8.5 · ADR-107 D8 contract tests — FastAPI router factories.

Covers both executor + tool-router factories in wired and unwired states.
Uses ``fastapi.testclient`` with the router mounted at the ADR-107 D8 prefix
(mirrors the Stage 8.3/8.4 pattern).
"""

from __future__ import annotations

import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.tektos.executor import TektosSpecExecutor, TektosToolRouter
from plugins.tektos.executor.api import (
    build_spec_executor_router,
    build_tool_router_router,
)


def _mk(app: FastAPI) -> TestClient:
    return TestClient(app)


def _mk_spec_payload() -> dict:
    return {
        "session_id": "s1",
        "spec": {
            "id": "spec-1",
            "description": "hello world",
            "phases": [
                {
                    "id": "phase-1",
                    "description": "build",
                    "deliverables": ["greeter function", "greeter tests"],
                }
            ],
            "tech_stack": ["python"],
        },
    }


# ── Spec-executor router ───────────────────────────────────────────────────


def test_spec_executor_router_wired_execute_returns_200_with_execution_id() -> None:
    app = FastAPI()
    engine = TektosSpecExecutor(workspace=tempfile.mkdtemp(prefix="tektos-r-"))
    app.include_router(
        build_spec_executor_router(engine), prefix="/tektos/api/executor"
    )
    c = _mk(app)
    resp = c.post("/tektos/api/executor/execute", json=_mk_spec_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_id"].startswith("exec-")
    assert body["spec_id"] == "spec-1"
    assert body["artifact_count"] == 2
    # Sandbox unwired → status collapses per ADR-107 D9.
    assert body["status"] == "sandbox_unavailable"


def test_spec_executor_router_unwired_execute_returns_503_with_adr_marker() -> None:
    app = FastAPI()
    app.include_router(
        build_spec_executor_router(None), prefix="/tektos/api/executor"
    )
    c = _mk(app)
    resp = c.post("/tektos/api/executor/execute", json=_mk_spec_payload())
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-107"


def test_spec_executor_router_recent_endpoint_wired_returns_items() -> None:
    app = FastAPI()
    engine = TektosSpecExecutor(workspace=tempfile.mkdtemp(prefix="tektos-r-"))
    app.include_router(
        build_spec_executor_router(engine), prefix="/tektos/api/executor"
    )
    c = _mk(app)
    c.post("/tektos/api/executor/execute", json=_mk_spec_payload())
    resp = c.get("/tektos/api/executor/recent?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["spec_id"] == "spec-1"


def test_spec_executor_router_unwired_recent_returns_503_with_adr_marker() -> None:
    app = FastAPI()
    app.include_router(
        build_spec_executor_router(None), prefix="/tektos/api/executor"
    )
    c = _mk(app)
    resp = c.get("/tektos/api/executor/recent")
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-107"


# ── Tool-router router ─────────────────────────────────────────────────────


def test_tool_router_router_wired_route_returns_200_with_route_id() -> None:
    app = FastAPI()
    app.include_router(
        build_tool_router_router(TektosToolRouter()),
        prefix="/tektos/api/tool-router",
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/tool-router/route",
        json={
            "session_id": "s1",
            "tools_needed": ["bash", "made_up_tool"],
            "task_description": "run a shell command",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["route_id"].startswith("route-")
    assert body["primary_tool"] == "bash"
    assert "bash" in body["matched_tools"]
    assert "made_up_tool" in body["unrouted_tools"]


def test_tool_router_router_unwired_route_returns_503_with_adr_marker() -> None:
    app = FastAPI()
    app.include_router(
        build_tool_router_router(None), prefix="/tektos/api/tool-router"
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/tool-router/route",
        json={"session_id": "s1", "task_description": "x"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-107"


def test_tool_router_router_recent_endpoint_wired_returns_items() -> None:
    app = FastAPI()
    engine = TektosToolRouter()
    app.include_router(
        build_tool_router_router(engine), prefix="/tektos/api/tool-router"
    )
    c = _mk(app)
    c.post(
        "/tektos/api/tool-router/route",
        json={"session_id": "s1", "task_description": "search files"},
    )
    resp = c.get("/tektos/api/tool-router/recent?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["primary_tool"] == "search_files"


def test_tool_router_router_unwired_recent_returns_503_with_adr_marker() -> None:
    app = FastAPI()
    app.include_router(
        build_tool_router_router(None), prefix="/tektos/api/tool-router"
    )
    c = _mk(app)
    resp = c.get("/tektos/api/tool-router/recent")
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-107"
