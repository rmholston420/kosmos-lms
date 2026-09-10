"""Stage 8.3 · ADR-105 D8 contract tests — FastAPI router factories.

Covers all three router factories (reflection / synthesis / experience)
in both wired and unwired states. Uses ``fastapi.testclient`` with the
router mounted at the ADR-105 D8 prefix.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.tektos.experience import ExperienceReplay
from plugins.tektos.experience.api import build_experience_router
from plugins.tektos.reflection import ReflectionEngine
from plugins.tektos.reflection.api import build_reflection_router
from plugins.tektos.synthesis import SynthesisEngine
from plugins.tektos.synthesis.api import build_synthesis_router


def _mk(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Reflection router


def test_reflection_router_wired_reflect_returns_200_with_insight():
    app = FastAPI()
    app.include_router(
        build_reflection_router(ReflectionEngine()), prefix="/tektos/api/reflection"
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/reflection/reflect",
        json={"session_id": "s1", "turn_outcome": {"stop_reason": "ok"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["insight"]["insight_type"] in {
        "clean_completion",
        "failure_pattern",
        "resource_pressure",
        "tool_gating_pattern",
    }


def test_reflection_router_unwired_reflect_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(build_reflection_router(None), prefix="/tektos/api/reflection")
    c = _mk(app)
    resp = c.post(
        "/tektos/api/reflection/reflect",
        json={"session_id": "s1", "turn_outcome": {}},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["adr"] == "ADR-105"


def test_reflection_router_recent_endpoint_wired_returns_list():
    app = FastAPI()
    app.include_router(
        build_reflection_router(ReflectionEngine()), prefix="/tektos/api/reflection"
    )
    c = _mk(app)
    resp = c.get("/tektos/api/reflection/recent?limit=5")
    assert resp.status_code == 200
    assert "insights" in resp.json()


# ---------------------------------------------------------------------------
# Synthesis router


def test_synthesis_router_wired_synthesize_returns_200():
    app = FastAPI()
    app.include_router(
        build_synthesis_router(SynthesisEngine()), prefix="/tektos/api/synthesis"
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/synthesis/synthesize",
        json={
            "session_id": "s1",
            "spec": {"id": "sp1", "description": "x"},
            "execution_feedback": {"stop_reason": "ok", "tool_outcomes": [{"accepted": True}]},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["spec_id"] == "sp1"


def test_synthesis_router_unwired_synthesize_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(build_synthesis_router(None), prefix="/tektos/api/synthesis")
    c = _mk(app)
    resp = c.post(
        "/tektos/api/synthesis/synthesize",
        json={"session_id": "s1", "spec": {}, "execution_feedback": {}},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-105"


def test_synthesis_router_recent_endpoint_wired_returns_list():
    app = FastAPI()
    app.include_router(
        build_synthesis_router(SynthesisEngine()), prefix="/tektos/api/synthesis"
    )
    c = _mk(app)
    resp = c.get("/tektos/api/synthesis/recent?limit=5")
    assert resp.status_code == 200
    assert "results" in resp.json()


# ---------------------------------------------------------------------------
# Experience router


def test_experience_router_wired_record_returns_200():
    app = FastAPI()
    app.include_router(
        build_experience_router(ExperienceReplay()), prefix="/tektos/api/experience"
    )
    c = _mk(app)
    resp = c.post(
        "/tektos/api/experience/record",
        json={
            "session_id": "s1",
            "synthesis": {"spec_id": "sp1", "synthesis": "y", "context": "coding"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["record"]["cycle_id"] == "sp1"


def test_experience_router_wired_recent_returns_records_by_context():
    app = FastAPI()
    engine = ExperienceReplay()
    app.include_router(
        build_experience_router(engine), prefix="/tektos/api/experience"
    )
    c = _mk(app)
    c.post(
        "/tektos/api/experience/record",
        json={
            "session_id": "s1",
            "synthesis": {"spec_id": "sp1", "synthesis": "y", "context": "coding"},
        },
    )
    resp = c.get("/tektos/api/experience/recent?context=coding&limit=5")
    assert resp.status_code == 200
    assert len(resp.json()["records"]) == 1


def test_experience_router_unwired_record_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(build_experience_router(None), prefix="/tektos/api/experience")
    c = _mk(app)
    resp = c.post(
        "/tektos/api/experience/record",
        json={"session_id": "s1", "synthesis": {}},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-105"


def test_experience_router_unwired_recent_returns_503_with_adr_marker():
    app = FastAPI()
    app.include_router(build_experience_router(None), prefix="/tektos/api/experience")
    c = _mk(app)
    resp = c.get("/tektos/api/experience/recent?context=coding&limit=5")
    assert resp.status_code == 503
    assert resp.json()["detail"]["adr"] == "ADR-105"
