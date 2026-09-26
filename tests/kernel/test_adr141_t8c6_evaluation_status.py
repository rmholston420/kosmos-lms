"""T8c-6 — donor GET /api/evaluation/status → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:4484.

Substrate: donor runtime/evaluation_framework.py (417 LOC, self-contained,
stdlib-only) verbatim port → kernel/evaluation_framework.py. Generic
benchmark/quality-measurement infrastructure → kernel-level substrate
(layering rule), consumed by the route exactly as the donor consumed it
(fresh ``get_evaluation_harness()`` call per request, module-level
singleton inside the framework — donor semantics preserved).

Wire preserved:
  {status: "initialized", total_evaluations, completed_evaluations,
   average_score}
  {status: "error", error: str} at 200 on failure (donor shape — error
  dict in the body, never an HTTP error)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kernel import app as kapp


@pytest.fixture()
def client() -> TestClient:
    return TestClient(kapp.app)


def test_evaluation_status_donor_wire_shape(client):
    r = client.get("/api/evaluation/status")
    assert r.status_code == 200
    body = r.json()
    for k in ("status", "total_evaluations", "completed_evaluations", "average_score"):
        assert k in body, f"missing donor key {k}"
    assert body["status"] == "initialized"
    assert body["total_evaluations"] == 0
    assert body["completed_evaluations"] == 0
    assert body["average_score"] == 0.0


def test_evaluation_status_reflects_harness_state(client, monkeypatch: pytest.MonkeyPatch):
    # the route must read the SAME framework singleton the donor did —
    # state added to the harness must surface in the wire
    import kernel.evaluation_framework as ev
    from kernel.evaluation_framework import EvaluationResult, EvaluationStatus, EvaluationType

    h = ev._harness
    if h is None:
        h = ev.get_evaluation_harness()
        ev._harness = h
    res = EvaluationResult(
        evaluation_id="t8c6-probe",
        evaluation_type=EvaluationType.CODE_QUALITY,
        status=EvaluationStatus.COMPLETED,
        score=0.9,
        metrics={},
    )
    h._results.append(res)
    try:
        body = client.get("/api/evaluation/status").json()
        assert body["completed_evaluations"] == 1
        assert body["average_score"] == pytest.approx(0.9)
    finally:
        h._results.pop()


def test_evaluation_status_error_at_200(client, monkeypatch: pytest.MonkeyPatch):
    # donor degrade: exception → {status: error, error: str} at HTTP 200
    import kernel.evaluation_framework as ev

    def boom(**kw):
        raise RuntimeError("harness down")

    monkeypatch.setattr(ev, "get_evaluation_harness", boom)
    r = client.get("/api/evaluation/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "harness down" in body["error"]
