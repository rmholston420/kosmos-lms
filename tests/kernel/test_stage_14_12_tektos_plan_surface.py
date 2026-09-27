"""Stage 14.12 — Tektos plan surface tests (ADR-067 D4 discharge).

Live integration tests over the kernel-native Plan → Approve → Execute →
Diff routes consumed by ``ui/app/tektos/detail/page.tsx``:

  * ``GET  /api/approvals/{id}``          — detail leg (native, ADR-062)
  * ``POST /api/approvals/{id}/approve``  — approve leg (native, ADR-062)
  * ``POST /api/tektos/plan/{id}/execute`` — execute leg (new, port of the
    /tektos-ui sub-app Execute leg)
  * ``GET  /api/tektos/plan/{id}/diff``    — diff leg (new, port of the
    /tektos-ui sub-app Diff leg)

Mirrors the seeding pattern of
``tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py`` (propose a
HUMAN_REVIEW record through the live APEX engine).

Requires Valkey up (event_bus + notification chain).
"""

from __future__ import annotations

from functools import partial
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from kernel import app as kernel_app_module
from kernel.app import app
from ports.approval import ChangeApprovalTier


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def approval_engine(client: TestClient):
    ap = kernel_app_module.registry.approval
    if ap is None:
        pytest.skip("approval subsystem not booted")
    return ap._engine


def _propose_pending(client: TestClient, engine, *, intention_id: str) -> str:
    call = partial(
        engine.propose,
        intention_id,
        {"kind": "test.plan", "payload": {"n": 1}},
        ChangeApprovalTier.HUMAN_REVIEW,
        proposing_domain="tektos",
        diff_preview={"summary": "test-plan"},
    )
    return client.portal.call(call)


# ---------------------------------------------------------------------------
# Detail + Approve (native legs)
# ---------------------------------------------------------------------------


def test_detail_returns_record(client: TestClient, approval_engine: Any):
    approval_id = _propose_pending(client, approval_engine, intention_id="plan-detail-1")
    resp = client.get(f"/api/approvals/{approval_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["approval_id"] == approval_id
    assert body["status"] == "PENDING"
    assert body["proposing_domain"] == "tektos"


def test_approve_then_execute_returns_result(client: TestClient, approval_engine: Any):
    approval_id = _propose_pending(client, approval_engine, intention_id="plan-exec-1")
    approve = client.post(
        f"/api/approvals/{approval_id}/approve",
        json={"reason": None, "modifications": {}, "resolved_by": "kosmos_ui"},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "APPROVED"

    resp = client.post(f"/api/tektos/plan/{approval_id}/execute", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["approval_id"] == approval_id
    # intention "plan-exec-1" has no "tektos.plan." prefix → raw id is change_id
    assert body["change_id"] == "plan-exec-1"
    assert body["before"].strip().endswith("before")
    assert body["after"].strip().endswith("after")
    assert len(body["diff_sha256"]) == 64


# ---------------------------------------------------------------------------
# Diff leg
# ---------------------------------------------------------------------------


def test_diff_returns_unified_diff(client: TestClient, approval_engine: Any):
    approval_id = _propose_pending(client, approval_engine, intention_id="plan-diff-1")
    resp = client.get(f"/api/tektos/plan/{approval_id}/diff")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["approval_id"] == approval_id
    assert body["change_id"] == "plan-diff-1"
    # deterministic NopExecutor snapshot → fixed before/after pair
    assert "tektos:plan:before" in body["body"]
    assert "tektos:plan:after" in body["body"]
    assert body["body"].lstrip().startswith("---")
    assert len(body["diff_sha256"]) == 64


# ---------------------------------------------------------------------------
# Change-id prefix stripping (tektos.plan.<change_id> intentions)
# ---------------------------------------------------------------------------


def test_execute_strips_tektos_plan_prefix(client: TestClient, approval_engine: Any):
    approval_id = _propose_pending(
        client, approval_engine, intention_id="tektos.plan.chg-99"
    )
    resp = client.post(f"/api/tektos/plan/{approval_id}/execute", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["change_id"] == "chg-99"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_execute_unknown_id_returns_404(client: TestClient):
    resp = client.post("/api/tektos/plan/does-not-exist/execute", json={})
    assert resp.status_code == 404


def test_diff_unknown_id_returns_404(client: TestClient):
    resp = client.get("/api/tektos/plan/does-not-exist/diff")
    assert resp.status_code == 404


def test_detail_unknown_id_returns_404(client: TestClient):
    resp = client.get("/api/approvals/does-not-exist")
    assert resp.status_code == 404
