"""Stage 8.4 · ADR-106 D8 contract tests — FastAPI router factories.

Covers both router factories (spec-planner / decomposer) in wired and unwired
states. Uses ``fastapi.testclient`` with the router mounted at the ADR-106 D8
prefix (mirrors the ADR-105 D8 pattern).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.tektos.decomposer import TaskDecomposer
from plugins.tektos.decomposer.api import build_decomposer_router
from plugins.tektos.planner import TektosSpecPlanner
from plugins.tektos.planner.api import build_spec_planner_router


def _mk(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Spec-planner router


def test_spec_planner_router_wired_plan_returns_200_with_spec_id():
    app = FastAPI()
    app.include_router(
        build_spec_planner_router(TektosSpecPlanner()),
        prefix="/tektos/api/spec-planner",
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/spec-planner/plan",
        json={"session_id": "s1", "prompt": "build me an api with authentication"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["spec_id"].startswith("spec-")
    assert body["language_game"]  # non-empty
    assert body["architecture"]["selected"]


def test_spec_planner_router_unwired_plan_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(
        build_spec_planner_router(None), prefix="/tektos/api/spec-planner"
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/spec-planner/plan",
        json={"session_id": "s1", "prompt": "x"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-106"


def test_spec_planner_router_recent_endpoint_wired_returns_items():
    app = FastAPI()
    engine = TektosSpecPlanner()
    app.include_router(
        build_spec_planner_router(engine), prefix="/tektos/api/spec-planner"
    )
    c = _mk(app)
    c.post(
        "/tektos/api/spec-planner/plan",
        json={"session_id": "s1", "prompt": "write a function that adds two numbers"},
    )
    resp = c.get("/tektos/api/spec-planner/recent?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert len(body["items"]) == 1


def test_spec_planner_router_unwired_recent_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(
        build_spec_planner_router(None), prefix="/tektos/api/spec-planner"
    )
    c = _mk(app)
    resp = c.get("/tektos/api/spec-planner/recent")
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-106"


# ---------------------------------------------------------------------------
# Decomposer router


def test_decomposer_router_wired_decompose_returns_200_with_plan_id():
    app = FastAPI()
    app.include_router(
        build_decomposer_router(TaskDecomposer()), prefix="/tektos/api/decomposer"
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/decomposer/decompose",
        json={"session_id": "s1", "task": "write hello world"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"].startswith("plan-")
    assert body["sub_task_count"] > 0
    assert "TASK DECOMPOSITION" in body["formatted_prompt"]


def test_decomposer_router_unwired_decompose_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(
        build_decomposer_router(None), prefix="/tektos/api/decomposer"
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/decomposer/decompose",
        json={"session_id": "s1", "task": "x"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-106"


def test_decomposer_router_recent_endpoint_wired_returns_items():
    app = FastAPI()
    engine = TaskDecomposer()
    app.include_router(
        build_decomposer_router(engine), prefix="/tektos/api/decomposer"
    )
    c = _mk(app)
    c.post(
        "/tektos/api/decomposer/decompose",
        json={"session_id": "s1", "task": "write hello world"},
    )
    resp = c.get("/tektos/api/decomposer/recent?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1


def test_decomposer_router_unwired_recent_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(
        build_decomposer_router(None), prefix="/tektos/api/decomposer"
    )
    c = _mk(app)
    resp = c.get("/tektos/api/decomposer/recent")
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-106"
