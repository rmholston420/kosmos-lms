"""ADR-141 T4 — planner surface (4 routes, donor wire fidelity).

T4a: ``GET /api/planner/templates``, ``GET /api/planner/language-games``,
``POST /api/planner/plan`` — the donor's ``Planner`` pipeline (pure
heuristic, no LLM) ported to ``plugins/tektos/planner/pipeline.py``.
T4b: ``GET /api/planner/status`` — the donor's runtime
``PlannerOrchestrator`` (plan-lifecycle tracker) elevated to
``kernel/plan_tracker.py``.

Isolation: ADR-132 pattern — the four routes are self-contained (no
adapter boots, no lifespan), so the tests use a bare ``TestClient``
without lifespan and ``monkeypatch.chdir(tmp_path)``. The
process-wide ``_plan_tracker`` singleton is monkeypatched per test so
tests never share plan state.

Wire fidelity: every assertion mirrors the donor (main.py:3174/3182/3195/
4650) — same keys, same types, same defaults. Donor-vs-kernel diffs were
verified live during T4a/T4b (donor ``model_dump()`` == kernel
serializer for the same prompt).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import kernel.app as ka
from kernel.plan_tracker import Plan, PlanStep, PlanTracker
from plugins.tektos.planner.pipeline import Planner
from plugins.tektos.planner.spec_models import (
    BuildSpec,
    LanguageGame,
    PlannerOutput,
)
from plugins.tektos.planner.template_selector import TEMPLATES

PROMPT = "Build a small REST API with docker for a todo app, please make it quick and simple"


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Bare TestClient (no lifespan) + isolated plan tracker + tmp cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ka, "_plan_tracker", PlanTracker())
    with TestClient(ka.app, raise_server_exceptions=False) as c:
        yield c


# ── T4b: kernel/plan_tracker.py — donor-faithful tracker ────────────────


def test_plan_tracker_create_and_get():
    """create_plan: plan_N ids, step_N ids, default steps, created_at."""
    t = PlanTracker()
    pid = t.create_plan("build a todo api")
    assert pid == "plan_1"
    plan = t.get_plan(pid)
    assert isinstance(plan, Plan)
    assert plan.description == "build a todo api"
    assert plan.status == "draft"
    assert plan.steps == [PlanStep(step_id="step_1", description="build a todo api")]
    assert plan.created_at  # __post_init__ stamps it (donor parity)


def test_plan_tracker_explicit_steps_and_stats():
    """Explicit steps + get_plan_stats wire (donor /status payload)."""
    t = PlanTracker()
    assert t.get_plan_stats() == {
        "total_plans": 0,
        "active": 0,
        "completed": 0,
        "failed": 0,
        "active_plan_id": None,
    }
    t.create_plan("a")
    p1 = t.get_plan("plan_1")
    assert p1 is not None
    p1.status = "active"
    t.create_plan("b", steps=["s1", "s2"])
    p2 = t.get_plan("plan_2")
    assert p2 is not None
    p2.status = "completed"
    stats = t.get_plan_stats()
    assert stats == {
        "total_plans": 2,
        "active": 1,
        "completed": 1,
        "failed": 0,
        "active_plan_id": None,
    }
    assert [s.step_id for s in p2.steps] == ["step_1", "step_2"]
    assert t.get_plan("nope") is None
    assert t.get_active_plan() is None


# ── T4a: the pipeline (plugin port) ─────────────────────────────────────


def test_pipeline_plan_returns_planner_output():
    """plan() runs all five stages and returns the donor-shape output."""
    out = Planner(context_budget=128000, max_clarifying_questions=3).plan(prompt=PROMPT)
    assert isinstance(out, PlannerOutput)
    assert isinstance(out.spec, BuildSpec)
    assert out.language_game_detected == LanguageGame.SOFTWARE_ENGINEERING
    assert out.context_budget_total == 128000
    assert out.context_budget_used == len(out.spec.translated_prompt)
    assert out.spec.language_game == out.language_game_detected
    assert isinstance(out.spec.phases, tuple) and len(out.spec.phases) >= 1
    assert isinstance(out.spec.requirements, tuple) and len(out.spec.requirements) >= 1
    assert out.spec.architecture.selected in {t.name for t in TEMPLATES}
    # donor semantics: ambiguities are the disambiguator + vague-term union;
    # resolved is list(zip(resolved, resolutions)) — a LIST of tuples (donor
    # orchestrator.py:140, same as the kernel port)
    assert isinstance(out.ambiguities_found, tuple)
    assert isinstance(out.ambiguities_resolved, list)
    assert len(out.ambiguities_resolved) == len(out.ambiguities_found)


def test_pipeline_custom_budget_and_max_questions():
    """constructor params flow through (donor Planner.__init__)."""
    p = Planner(context_budget=100, max_clarifying_questions=1)
    # prompt longer than 80% of budget → donor budget warning fires
    long_prompt = ("Build a small REST API with docker for a todo app that also "
                   "handles auth and pagination and rate limiting ") * 5
    out = p.plan(prompt=long_prompt)
    assert out.context_budget_total == 100
    assert len(out.clarifying_questions_asked) <= 1
    # donor semantics: warning when translated prompt > 80% of budget
    assert out.spec.context_budget_warning is not None
    assert "100" in out.spec.context_budget_warning


def test_pipeline_clarifying_questions_capped():
    """clarifying_questions is capped at max_clarifying_questions (donor)."""
    p = Planner(context_budget=128000, max_clarifying_questions=2)
    out = p.plan(prompt="Make it fast and scalable, whatever works best")
    assert len(out.clarifying_questions_asked) <= 2


# ── T4a: serializer — donor model_dump() wire shape ─────────────────────


def test_serializer_wire_shape():
    """_planner_output_to_wire: dataclasses→dicts, tuples→lists, enums→values."""
    out = Planner().plan(prompt=PROMPT)
    wire = ka._planner_output_to_wire(out)
    # top-level keys == donor PlannerOutput fields (model_dump parity)
    assert set(wire.keys()) == {
        "spec",
        "synthesis_guidance",
        "language_game_detected",
        "ambiguities_found",
        "ambiguities_resolved",
        "clarifying_questions_asked",
        "templates_presented",
        "context_budget_used",
        "context_budget_total",
    }
    # enum → value (donor pydantic model_dump() behavior)
    assert wire["language_game_detected"] == "software_engineering"
    # tuple → list
    assert isinstance(wire["spec"]["phases"], list)
    assert isinstance(wire["spec"]["requirements"], list)
    # spec fields == donor BuildSpec fields
    assert set(wire["spec"].keys()) == {
        "id",
        "version",
        "original_prompt",
        "translated_prompt",
        "description",
        "language_game",
        "architecture",
        "requirements",
        "phases",
        "constraints",
        "test_strategy",
        "tech_stack",
        "synthesis_guidance",
        "context_budget_warning",
        "created_at",
        "notes",
        "metadata",
    }
    # phase wire shape
    phase = wire["spec"]["phases"][0]
    assert set(phase.keys()) == {
        "id",
        "description",
        "deliverables",
        "acceptance_criteria",
        "estimated_effort",
    }
    # no live objects leak out — JSON-serializable end to end
    json.dumps(wire)


# ── T4a: HTTP routes ────────────────────────────────────────────────────


def test_get_planner_templates(client):
    """donor main.py:3174 — {"templates": [t.model_dump() for t in TEMPLATES]}."""
    r = client.get("/api/planner/templates")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"templates"}
    assert len(body["templates"]) == len(TEMPLATES)
    for t in body["templates"]:
        assert set(t.keys()) == {
            "name",
            "description",
            "pros",
            "cons",
            "use_cases",
            "recommended_for",
        }
        assert isinstance(t["pros"], list)


def test_get_planner_language_games(client):
    """donor main.py:3182 — name/description per LanguageGame member."""
    r = client.get("/api/planner/language-games")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"language_games"}
    assert len(body["language_games"]) == len(LanguageGame)
    names = [g["name"] for g in body["language_games"]]
    assert names == [g.value for g in LanguageGame]
    assert body["language_games"][0]["description"] == (
        names[0].replace("_", " ").title()
    )


def test_post_planner_plan(client):
    """donor main.py:3195 — PlannerOutput.model_dump() wire verbatim."""
    r = client.post("/api/planner/plan", json={"prompt": PROMPT})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "spec",
        "synthesis_guidance",
        "language_game_detected",
        "ambiguities_found",
        "ambiguities_resolved",
        "clarifying_questions_asked",
        "templates_presented",
        "context_budget_used",
        "context_budget_total",
    }
    assert body["context_budget_total"] == 128000  # donor default
    assert body["spec"]["original_prompt"] == PROMPT
    assert isinstance(body["spec"]["phases"], list)
    assert isinstance(body["spec"]["requirements"], list)
    assert body["spec"]["architecture"]["selected"] == "vertical_slice"
    assert body["language_game_detected"] == "software_engineering"


def test_post_planner_plan_empty_prompt_400(client):
    """donor main.py:3200 — 400 when prompt missing/empty."""
    assert client.post("/api/planner/plan", json={}).status_code == 400
    assert client.post("/api/planner/plan", json={"prompt": ""}).status_code == 400


def test_post_planner_plan_with_context_and_preference(client):
    """donor main.py:3205-3215 — context/user_preference/synthesis_guidance."""
    r = client.post(
        "/api/planner/plan",
        json={
            "prompt": "Build a small REST API",
            "context": {"tech_stack": ["python"], "constraints": ["no new deps"]},
            "user_preference": "vertical_slice",
            "synthesis_guidance": "prefer small phases",
            "context_budget": 4000,
            "max_clarifying_questions": 1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["context_budget_total"] == 4000
    assert body["synthesis_guidance"] == "prefer small phases"
    assert body["spec"]["synthesis_guidance"] == "prefer small phases"
    assert body["spec"]["tech_stack"] == ["python"]
    assert body["spec"]["constraints"] == ["no new deps"]
    assert len(body["clarifying_questions_asked"]) <= 1


# ── T4b: /api/planner/status ────────────────────────────────────────────


def test_planner_status_wire(client):
    """donor main.py:4650 — {"status": "initialized", "stats": get_plan_stats()}."""
    r = client.get("/api/planner/status")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "status": "initialized",
        "stats": {
            "total_plans": 0,
            "active": 0,
            "completed": 0,
            "failed": 0,
            "active_plan_id": None,
        },
    }


def test_planner_status_reflects_tracker(client):
    """plans created on the singleton appear in /status stats."""
    ka._plan_tracker.create_plan("smoke plan", steps=["s1", "s2"])
    p1 = ka._plan_tracker.get_plan("plan_1")
    assert p1 is not None
    p1.status = "active"
    r = client.get("/api/planner/status")
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["total_plans"] == 1
    assert stats["active"] == 1
