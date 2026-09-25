"""ADR-141 T1 — orchestrator donor-fidelity status/agents routes.

Donor ``GET /api/multi-agent-orchestrator/{status,agents}`` on :8020 (the
last of the panel AgentsTab's two gateway calls) ported onto the
ADR-114-mounted ``build_orchestrator_router``. Contract:

- ``/status`` — donor shape ``{status, hierarchical_agent,
  long_running_agent, coding_executor}``; honest-degrade: ``status``
  reports ``"unwired"`` (not the donor's unconditional ``"initialized"``)
  when no engine family is wired — a status endpoint reports reality.
- ``/agents`` — donor shape: list of ``{id, name, role, status,
  active_tasks}``; only WIRED agents listed; display strings preserved
  verbatim; ``active_tasks`` reads defensive ``_active_tasks`` /
  ``_active_sessions`` (kernel engines don't expose them → 0, never a
  fabricated count).
- The ``coding`` referent is the ADR-107 spec-executor
  (``registry.tektos_executor``) — tested here with a bare sentinel.
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


def _app_with(*, bundle, hierarchical, long_running, coding) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_orchestrator_router(
            bundle,
            hierarchical=hierarchical,
            long_running=long_running,
            coding=coding,
        ),
        prefix=PREFIX,
    )
    return app


@pytest.fixture()
def unwired_client() -> TestClient:
    return TestClient(
        _app_with(bundle=None, hierarchical=None, long_running=None, coding=None)
    )


@pytest.fixture()
def full_client() -> TestClient:
    bundle = OrchestratorBundle(
        orchestrator=TektosOrchestrator(),
        wired_sandbox=False,
        wired_memory=False,
        wired_event_bus=False,
    )
    # Coding referent: a bare sentinel object stands in for the ADR-107
    # TektosSpecExecutor — the routes only check identity + getattr.
    class _CodingRef:
        _active_sessions: list = []

    return TestClient(
        _app_with(
            bundle=bundle,
            hierarchical=TektosHierarchicalAgent(),
            long_running=TektosLongRunningAgent(),
            coding=_CodingRef(),
        )
    )


class TestStatus:
    def test_unwired_reports_unwired(self, unwired_client: TestClient) -> None:
        r = unwired_client.get(f"{PREFIX}/status")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "unwired"
        assert body["hierarchical_agent"] is False
        assert body["long_running_agent"] is False
        assert body["coding_executor"] is False

    def test_wired_reports_initialized(self, full_client: TestClient) -> None:
        r = full_client.get(f"{PREFIX}/status")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "initialized"
        assert body["hierarchical_agent"] is True
        assert body["long_running_agent"] is True
        assert body["coding_executor"] is True

    def test_partial_wiring_reports_bonuses_truthfully(self) -> None:
        bundle = OrchestratorBundle(
            orchestrator=TektosOrchestrator(),
            wired_sandbox=False,
            wired_memory=False,
            wired_event_bus=False,
        )
        client = TestClient(
            _app_with(
                bundle=bundle,
                hierarchical=None,
                long_running=None,
                coding=object(),
            )
        )
        body = client.get(f"{PREFIX}/status").json()
        assert body["status"] == "initialized"
        assert body["coding_executor"] is True
        assert body["hierarchical_agent"] is False
        assert body["long_running_agent"] is False


class TestAgents:
    def test_unwired_lists_nothing(self, unwired_client: TestClient) -> None:
        r = unwired_client.get(f"{PREFIX}/agents")
        assert r.status_code == 200
        assert r.json() == []

    def test_wired_lists_all_three_donor_agents(self, full_client: TestClient) -> None:
        r = full_client.get(f"{PREFIX}/agents")
        assert r.status_code == 200
        agents = r.json()
        assert len(agents) == 3
        by_id = {a["id"]: a for a in agents}
        # Donor display strings preserved verbatim.
        assert by_id["hierarchical"]["name"] == "Hierarchical Planner"
        assert by_id["hierarchical"]["role"] == "planner"
        assert by_id["long_running"]["name"] == "Long-Running Executor"
        assert by_id["long_running"]["role"] == "executor"
        assert by_id["coding"]["name"] == "Coding Agent"
        assert by_id["coding"]["role"] == "executor"
        for a in agents:
            assert a["status"] == "ready"
            assert a["active_tasks"] == 0  # kernel engines don't track → 0

    def test_active_tasks_reads_bookkeeping_when_present(self) -> None:
        class _Hier:
            _active_tasks: list = ["t1", "t2", "t3"]

        class _LR:
            _active_tasks: list = ["t1"]

        class _Coding:
            _active_sessions: list = ["s1"]

        client = TestClient(
            _app_with(
                bundle=None,
                hierarchical=_Hier(),
                long_running=_LR(),
                coding=_Coding(),
            )
        )
        by_id = {a["id"]: a for a in client.get(f"{PREFIX}/agents").json()}
        assert by_id["hierarchical"]["active_tasks"] == 3
        assert by_id["long_running"]["active_tasks"] == 1
        assert by_id["coding"]["active_tasks"] == 1

    def test_none_bookkeeping_degrades_to_zero_not_error(self) -> None:
        class _Hier:
            _active_tasks: None = None

        client = TestClient(
            _app_with(
                bundle=None,
                hierarchical=_Hier(),
                long_running=None,
                coding=None,
            )
        )
        agents = client.get(f"{PREFIX}/agents").json()
        assert len(agents) == 1
        assert agents[0]["active_tasks"] == 0
