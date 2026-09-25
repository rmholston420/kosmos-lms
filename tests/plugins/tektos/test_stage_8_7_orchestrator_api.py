"""Stage 8.7 — Tektos Orchestrator router contract (ADR-114 D8).

Contract tests over :func:`plugins.tektos.orchestrator.api.build_orchestrator_router`
mounted onto a bare FastAPI app via TestClient under the mount-time prefix
``/tektos/api/orchestrator`` (the engine family does NOT inline-mount in
``kernel/app.py`` — ADR-106/107/108 precedent).

Scenarios:
- Degrade: every route returns 503 (ADR-101) when the corresponding engine
  is ``None``.
- Happy path: task lifecycle round-trips; hierarchical plan executes with the
  deterministic template fallback (no LLMPort wired); long-running status
  reflects lifecycle.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from plugins.tektos.orchestrator.api import build_orchestrator_router
from plugins.tektos.orchestrator.engine import (
    OrchestratorBundle,
    TektosOrchestrator,
)
from plugins.tektos.orchestrator.hierarchical import TektosHierarchicalAgent
from plugins.tektos.orchestrator.long_running import TektosLongRunningAgent

PREFIX = "/tektos/api/orchestrator"


def _app_with(
    *,
    bundle: OrchestratorBundle | None,
    hierarchical: TektosHierarchicalAgent | None,
    long_running: TektosLongRunningAgent | None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_orchestrator_router(
            bundle,
            hierarchical=hierarchical,
            long_running=long_running,
        ),
        prefix=PREFIX,
    )
    return app


@pytest.fixture()
def degrade_client() -> TestClient:
    return TestClient(_app_with(bundle=None, hierarchical=None, long_running=None))


@pytest.fixture()
def live_client() -> TestClient:
    bundle = OrchestratorBundle(
        orchestrator=TektosOrchestrator(),
        wired_sandbox=False,
        wired_memory=False,
        wired_event_bus=False,
    )
    return TestClient(
        _app_with(
            bundle=bundle,
            hierarchical=TektosHierarchicalAgent(),
            long_running=TektosLongRunningAgent(),
        )
    )


# ---------------------------------------------------------------------------
# Degrade (ADR-101 / ADR-114 D8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/tasks", "post", {"description": "x"}),
        ("/stats", "get", None),
        ("/recent", "get", None),
        ("/hierarchical/tasks", "post", {"role": "coder", "description": "x"}),
        ("/hierarchical/plan", "post", {"task_ids": ["t1"]}),
        ("/hierarchical/recent", "get", None),
        ("/long-running/status", "get", None),
        ("/long-running/heartbeat", "post", None),
        ("/long-running/checkpoint", "post", {"session_id": "", "next_action": ""}),
    ],
)
def test_routes_503_when_engine_unwired(
    degrade_client: TestClient, path: str, method: str, body: dict | None
) -> None:
    if method == "get":
        resp = degrade_client.get(PREFIX + path)
    else:
        resp = degrade_client.post(PREFIX + path, json=body)
    assert resp.status_code == 503, f"{path} -> {resp.status_code}"
    detail = resp.json()["detail"]
    assert detail["adr"] == "ADR-114"
    assert "ADR-114" in detail["detail"]


# ---------------------------------------------------------------------------
# Happy path — orchestrator
# ---------------------------------------------------------------------------


def test_task_lifecycle_roundtrip(live_client: TestClient) -> None:
    resp = live_client.post(
        # "write" matches file_agent's write_file capability (donor keyword
        # matching is verbatim — see engine.assign_task).
        PREFIX + "/tasks", json={"description": "write a feature module"}
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    assert resp.json()["status"] == "pending"

    # Assign to a default worker agent: description contains "write_file"'s
    # "write" keyword, which matches file_agent's capability (donor
    # keyword matching is verbatim — see engine.assign_task).
    resp = live_client.post(
        f"{PREFIX}/tasks/{task_id}/assign",
        json={"task_id": task_id, "agent_id": "file_agent"},
    )
    assert resp.status_code == 200
    assert resp.json()["assigned"] is True

    resp = live_client.post(f"{PREFIX}/tasks/{task_id}/execute")
    assert resp.status_code == 200

    resp = live_client.get(PREFIX + "/stats")
    assert resp.status_code == 200
    assert "recent_batches" in resp.json()


def test_execute_unassigned_task_reports_failure(live_client: TestClient) -> None:
    resp = live_client.post(
        PREFIX + "/tasks", json={"description": "orphan task"}
    )
    task_id = resp.json()["task_id"]
    resp = live_client.post(f"{PREFIX}/tasks/{task_id}/execute")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "not assigned" in resp.json()["error"]


def test_execute_unknown_task_reports_not_found(live_client: TestClient) -> None:
    resp = live_client.post(f"{PREFIX}/tasks/nope/execute")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "not found" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Hierarchical — deterministic template fallback (no LLMPort wired)
# ---------------------------------------------------------------------------


def test_hierarchical_plan_deterministic_fallback(live_client: TestClient) -> None:
    resp = live_client.post(
        PREFIX + "/hierarchical/tasks",
        json={"role": "architect", "description": "build a rocket"},
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    resp = live_client.post(
        PREFIX + "/hierarchical/plan", json={"task_ids": [task_id]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 0
    result = body["results"][0]
    assert result["success"] is True
    assert "Architecture design for: build a rocket" in result["output"]


def test_hierarchical_unknown_role_422(live_client: TestClient) -> None:
    resp = live_client.post(
        PREFIX + "/hierarchical/tasks",
        json={"role": "warp_drive", "description": "x"},
    )
    assert resp.status_code == 422


def test_hierarchical_plan_unknown_task_404(live_client: TestClient) -> None:
    resp = live_client.post(
        PREFIX + "/hierarchical/plan", json={"task_ids": ["ghost"]}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Long-running
# ---------------------------------------------------------------------------


def test_long_running_status_shape(live_client: TestClient) -> None:
    resp = live_client.get(PREFIX + "/long-running/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert body["state"] in (
        "idle",
        "running",
        "paused",
        "checkpointed",
        "completed",
    )
    assert body["wired_memory"] is False
    assert "progress_percent" in body


def test_long_running_heartbeat_unwired_is_noop(live_client: TestClient) -> None:
    resp = live_client.post(PREFIX + "/long-running/heartbeat")
    assert resp.status_code == 200
    assert resp.json()["wired_memory"] is False


def test_long_running_checkpoint_unwired(live_client: TestClient) -> None:
    resp = live_client.post(
        PREFIX + "/long-running/checkpoint",
        json={"session_id": "", "next_action": "continue"},
    )
    assert resp.status_code == 200
