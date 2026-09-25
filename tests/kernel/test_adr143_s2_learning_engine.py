"""ADR-143 T3 / S2 — kernel learning substrate (LearningEngine) tests.

Covers the donor-faithful port of ``SelfImprovementAdapter``:
* read API against a seeded JSONL ledger (donor wire shapes)
* write paths (``on_session_completed`` / ``on_session_failed``) — the
  donor's dead write paths, now live
* meta-learning + benchmark persistence
* DI degrade: None retainer/emitter/skill_creator → no side effects
* dual-persist: retainer called with donor tag/context shapes
* evaluation fallback heuristic (openhands-ext absent)
* singleton seam
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kernel.learning import (  # noqa: E402
    ExperienceRecord,
    LearningEngine,
    get_learning_engine,
    reset_learning_engine,
)


# ── fixtures ───────────────────────────────────────────────────────────────


class FakeRetainer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retain(self, content: str, *, context: str | None = None, tags=None):
        self.calls.append({"content": content, "context": context, "tags": tags})
        return {"ok": True}


class FakeSkillCreator:
    def __init__(self) -> None:
        self.calls = 0

    def create_skill_from_reflection(self, **kwargs: Any) -> list:
        self.calls += 1

        class _Skill:
            name = "test-skill"

        return [_Skill()]


class RecordingEmitter:
    def __init__(self) -> None:
        self.ticks: list[tuple[str, str, dict[str, Any]]] = []

    async def __call__(self, session_id, event_type, payload):
        self.ticks.append((session_id, event_type, payload))


@pytest.fixture
def paths(tmp_path: Path):
    return {
        "experience_db": str(tmp_path / "experience.jsonl"),
        "meta_learning_db": str(tmp_path / "meta_learning.json"),
        "benchmark_dir": str(tmp_path / "benchmarks"),
    }


@pytest.fixture
def engine(paths, tmp_path) -> LearningEngine:
    return LearningEngine(
        experience_db=paths["experience_db"],
        meta_learning_db=paths["meta_learning_db"],
        benchmark_dir=paths["benchmark_dir"],
        skill_dir=str(tmp_path / "skills"),
    )


# ── read API ───────────────────────────────────────────────────────────────


def test_get_experience_empty_when_no_ledger(engine):
    assert engine.get_experience() == []


def test_get_experience_returns_recent_records(engine, paths):
    records = [
        ExperienceRecord(
            session_id=f"s{i}",
            task=f"task {i}",
            model_used="m",
            success=(i % 2 == 0),
            tests_passed=i,
            tests_total=i + 1,
            wall_time_seconds=float(i),
        )
        for i in range(12)
    ]
    with open(paths["experience_db"], "w") as f:
        for r in records:
            f.write(r.to_json() + "\n")

    got = engine.get_experience(top_k=10)
    assert len(got) == 10
    assert got[0].session_id == "s0"
    assert got[9].session_id == "s9"
    assert all(isinstance(r, ExperienceRecord) for r in got)


def test_get_experience_skips_malformed_lines(engine, paths):
    with open(paths["experience_db"], "w") as f:
        f.write("not json\n")
        f.write(json.dumps({"session_id": "ok", "task": "t", "model_used": "m",
                            "success": True, "tests_passed": 1, "tests_total": 1,
                            "wall_time_seconds": 1.0}) + "\n")
    got = engine.get_experience()
    assert len(got) == 1
    assert got[0].session_id == "ok"


def test_query_experience_filters(engine, paths):
    for i, (task, ok) in enumerate([
        ("fix auth bug", True),
        ("fix network bug", False),
        ("refactor parser", True),
    ]):
        with open(paths["experience_db"], "a") as f:
            f.write(ExperienceRecord(
                session_id=f"s{i}", task=task, model_used="m", success=ok,
                tests_passed=1, tests_total=1, wall_time_seconds=1.0,
            ).to_json() + "\n")

    assert [r.task for r in engine.query_experience(task_keywords=["auth"])] == ["fix auth bug"]
    assert [r.task for r in engine.query_experience(success_only=True)] == [
        "fix auth bug", "refactor parser"
    ]
    assert [r.task for r in engine.query_experience(failed_only=True)] == ["fix network bug"]


# ── write paths (the donor's dead paths, now live) ─────────────────────────


async def test_on_session_completed_records_ledger_meta_benchmark(
    engine, paths
):
    rec = await engine.on_session_completed(
        session_id="sess-1",
        task="implement feature X",
        spec="do X correctly",
        model_used="qwen3.8-27b",
        success=True,
        tests_passed=8,
        tests_total=10,
        wall_time_seconds=120.0,
    )
    assert rec.session_id == "sess-1"
    assert rec.success is True
    # heuristic score: 0.8*0.5 + 0.0(spec given)*0.3 + 1.0*0.2 = 0.6
    assert rec.evaluation_score == pytest.approx(0.6)

    # ledger appended
    lines = open(paths["experience_db"]).read().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["session_id"] == "sess-1"

    # meta-learning updated
    meta = json.loads(open(paths["meta_learning_db"]).read())
    assert meta["learning_metrics"]["total_tasks"] == 1
    assert meta["learning_metrics"]["total_improvements"] == 1  # 0.6 > 0.5
    mp = meta["model_performance"]["qwen3.8-27b"]["task_types"]["implement feature X"]
    assert mp["tasks"] == 1 and mp["successes"] == 1

    # benchmark written
    bench = json.loads((Path(paths["benchmark_dir"]) / "sess-1.json").read_text())
    assert bench["success"] is True and bench["tests_passed"] == 8


async def test_on_session_completed_no_spec_scores_highest(engine):
    rec = await engine.on_session_completed(
        session_id="s", task="t", spec="", model_used="m", success=True,
        tests_passed=3, tests_total=3, wall_time_seconds=1.0,
    )
    # 1.0*0.5 + 1.0*0.3 + 1.0*0.2 = 1.0
    assert rec.evaluation_score == pytest.approx(1.0)


async def test_on_session_failed_records_failure(engine, paths):
    rec = await engine.on_session_failed(
        session_id="bad-1", task="t", spec="s", model_used="m",
        error="boom", wall_time_seconds=5.0,
    )
    assert rec.success is False
    assert rec.evaluation_score == 0.0
    assert rec.what_failed == ["boom"]
    assert any("boom" in c for c in rec.code_issues)

    meta = json.loads(open(paths["meta_learning_db"]).read())
    assert meta["learning_metrics"]["total_improvements"] == 0
    # donor-faithful: on_session_failed does NOT write a benchmark file
    assert not (Path(paths["benchmark_dir"]) / "bad-1.json").exists()


# ── DI seams: dual-persist, ticks, skills ──────────────────────────────────


async def test_hindsight_dual_persist_donor_shape(tmp_path, paths):
    ret = FakeRetainer()
    eng = LearningEngine(
        experience_db=paths["experience_db"],
        meta_learning_db=paths["meta_learning_db"],
        benchmark_dir=paths["benchmark_dir"],
        hindsight_retainer=ret,
    )
    await eng.on_session_completed(
        session_id="h-1", task="hindsight task", spec="", model_used="modelA",
        success=True, tests_passed=5, tests_total=5, wall_time_seconds=10.0,
    )
    assert len(ret.calls) == 1
    call = ret.calls[0]
    assert call["context"] == "self-improvement:modelA:hindsight task"
    assert call["tags"][:4] == ["tektos", "self-improvement", "experience", "success"]
    assert call["tags"][4] == "modelA"
    assert "h-1" in call["content"] and "SUCCESS" in call["content"]


async def test_no_retainer_degrades_to_jsonl_only(engine, paths):
    rec = await engine.on_session_completed(
        session_id="j-1", task="t", spec="", model_used="m", success=True,
        tests_passed=1, tests_total=1, wall_time_seconds=1.0,
    )
    assert rec.session_id == "j-1"
    assert "j-1" in open(paths["experience_db"]).read()


async def test_ticks_emit_donor_shape(tmp_path, paths):
    em = RecordingEmitter()
    eng = LearningEngine(
        experience_db=paths["experience_db"],
        meta_learning_db=paths["meta_learning_db"],
        benchmark_dir=paths["benchmark_dir"],
        tick_emitter=em,
    )
    await eng.on_session_completed(
        session_id="t-1", task="t", spec="", model_used="m", success=True,
        tests_passed=1, tests_total=1, wall_time_seconds=1.0,
    )
    types = [p["tick"] for (_, _, p) in em.ticks]
    assert types == ["evaluation.started", "evaluation.complete", "reflection.complete"]
    assert all(e == "self_improvement.tick" for (_, e, _) in em.ticks)
    assert all(s == "t-1" for (s, _, _) in em.ticks)


async def test_failed_session_ticks(tmp_path, paths):
    em = RecordingEmitter()
    eng = LearningEngine(
        experience_db=paths["experience_db"],
        meta_learning_db=paths["meta_learning_db"],
        benchmark_dir=paths["benchmark_dir"],
        tick_emitter=em,
    )
    await eng.on_session_failed(
        session_id="f-1", task="t", spec="s", model_used="m",
        error="err", wall_time_seconds=1.0,
    )
    types = [p["tick"] for (_, _, p) in em.ticks]
    assert types == ["failure.detected", "failure.recorded"]


async def test_skill_creator_invoked(tmp_path, paths):
    creator = FakeSkillCreator()
    eng = LearningEngine(
        experience_db=paths["experience_db"],
        meta_learning_db=paths["meta_learning_db"],
        benchmark_dir=paths["benchmark_dir"],
        skill_creator=creator,
    )
    rec = await eng.on_session_completed(
        session_id="sk-1", task="t", spec="", model_used="m", success=True,
        tests_passed=2, tests_total=2, wall_time_seconds=1.0,
    )
    assert creator.calls == 1
    assert rec.created_skills == ["test-skill"]


async def test_retainer_exception_degrades_open(tmp_path, paths):
    class BrokenRetainer:
        def retain(self, **kw):
            raise RuntimeError("hindsight down")

    eng = LearningEngine(
        experience_db=paths["experience_db"],
        meta_learning_db=paths["meta_learning_db"],
        benchmark_dir=paths["benchmark_dir"],
        hindsight_retainer=BrokenRetainer(),
    )
    rec = await eng.on_session_completed(
        session_id="r-1", task="t", spec="", model_used="m", success=True,
        tests_passed=1, tests_total=1, wall_time_seconds=1.0,
    )
    assert rec.session_id == "r-1"
    assert "r-1" in open(paths["experience_db"]).read()


# ── metrics + report ───────────────────────────────────────────────────────


def test_metrics_empty_state(engine):
    m = engine.get_learning_metrics()
    assert m == {
        "total_tasks": 0,
        "total_improvements": 0,
        "learning_velocity": 0.0,
        "model_rankings": [],
        "best_model_for_coding": None,
    }


def test_metrics_rankings_and_report(engine, paths):
    with open(paths["meta_learning_db"], "w") as f:
        json.dump(
            {
                "version": "1.0",
                "model_performance": {
                    "modelA": {
                        "overall_quality": 0.9,
                        "task_types": {
                            "bugfix": {"tasks": 10, "successes": 9, "total_quality": 9.0},
                        },
                    },
                    "modelB": {
                        "overall_quality": 0.4,
                        "task_types": {
                            "feature": {"tasks": 5, "successes": 2, "total_quality": 2.0},
                        },
                    },
                },
                "learning_metrics": {
                    "total_tasks": 15,
                    "total_improvements": 6,
                    "improvement_history": [],
                },
            },
            f,
        )
    m = engine.get_learning_metrics()
    assert m["total_tasks"] == 15
    assert m["learning_velocity"] == pytest.approx(0.4)
    assert m["best_model_for_coding"] == "modelA"
    assert m["model_rankings"][0]["model"] == "modelA"
    assert m["model_rankings"][0]["avg_quality"] == pytest.approx(0.9)

    report = engine.get_report()
    assert "# SELF-IMPROVEMENT REPORT" in report
    assert "modelA" in report and "modelB" in report
    assert "- Use modelA for coding tasks" in report


# ── singleton ──────────────────────────────────────────────────────────────


def test_singleton_seam(tmp_path):
    reset_learning_engine()
    try:
        a = get_learning_engine(experience_db=str(tmp_path / "x.jsonl"))
        b = get_learning_engine()
        assert a is b
        reset_learning_engine()
        c = get_learning_engine(experience_db=str(tmp_path / "y.jsonl"))
        assert c is not a
        assert c.experience_db.name == "y.jsonl"
    finally:
        reset_learning_engine()
