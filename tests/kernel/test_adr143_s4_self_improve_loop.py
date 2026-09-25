"""ADR-143 T3 / S4 — plugin Hegelian loop (SelfImprovementLoop) tests.

Covers the donor-faithful port of ``loop_orchestrator.SelfImprovementLoop``
adapted onto the kernel's five Tektos engines:
* full cycle with all engines wired — phase order + substrate feed
* planner guidance folded into the prompt (kernel adaptation)
* executor failure → cycle failed + substrate on_session_failed
* missing engines → honest degrade (failed cycle, no raise)
* max_cycles cap
* get_loop_health shape + clear_cycles + __len__
* driver integration (set_loop + run_cycle_now)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from kernel.learning.driver import LearningDriver
from plugins.tektos.self_improve.loop import LoopCycle, SelfImprovementLoop


# ── fake DI collaborators ───────────────────────────────────────────────────


@dataclass(frozen=True)
class _Spec:
    id: str = "spec-test"
    description: str = "A test spec"
    requirements: tuple[str, ...] = ("req-1",)
    phases: tuple = ()


@dataclass(frozen=True)
class _PlannerOutput:
    spec: _Spec = field(default_factory=_Spec)


@dataclass(frozen=True)
class _Step:
    action: str = "phase_start"


@dataclass(frozen=True)
class _TestReport:
    status: str = "passed"


@dataclass(frozen=True)
class _Record:
    status: str = "completed"
    steps: tuple = (_Step(),)
    test_results: tuple = (_TestReport(),)
    artifacts: tuple = ()
    error_summary: str = ""
    total_duration_seconds: float = 1.5


class FakePlanner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_spec(self, *, session_id, prompt, context=None, **kw):
        self.calls.append({"session_id": session_id, "prompt": prompt, "context": context})
        return _PlannerOutput(), None


class FakeExecutor:
    def __init__(self, record: Any = _Record()) -> None:
        self.record = record
        self.calls = 0

    async def execute_spec(self, *, session_id, spec, **kw):
        self.calls += 1
        return self.record, None


class FakeManager:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def on_task_start(self, *, session_id, task_id, spec_id=""):
        self.events.append("start")

    async def on_error(self, *, session_id, category, description, **kw):
        self.events.append("error")
        return None, None

    async def on_task_complete(self, *, session_id, task_id, success, **kw):
        self.events.append(f"complete:{success}")


class FakeReflection:
    def __init__(self) -> None:
        self.calls = 0

    async def reflect_on_turn(self, *, session_id, turn_outcome, **kw):
        self.calls += 1
        return object(), None


class FakeSynthesis:
    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, *, session_id, spec, execution_feedback, **kw):
        self.calls += 1
        from plugins.tektos.synthesis.models import SynthesisResult

        return SynthesisResult(spec_id=spec.get("id", ""), is_actionable=True), None


class FakeExperience:
    def __init__(self, records: tuple = ()) -> None:
        self.records_in = list(records)
        self.recorded: list[dict[str, Any]] = []
        self.recall_calls = 0

    def is_persistence_bound(self) -> bool:
        return False

    async def recall(self, *, context, limit=10):
        self.recall_calls += 1
        return tuple(self.records_in[:limit])

    def recent(self, limit=10):
        return tuple(self.recorded)

    async def record(self, *, session_id, synthesis, context=None, **kw):
        self.recorded.append(synthesis)
        exp_id = f"exp-{len(self.recorded)}"
        return _FakeExperienceRecord(exp_id), None


@dataclass(frozen=True)
class _FakeExperienceRecord:
    id: str
    guidance: str = "guidance"
    summary: str = "summary"


class FakeLearning:
    """Fake kernel learning substrate (isolated tmp dirs)."""

    def __init__(self, tmp_path) -> None:
        from kernel.learning.engine import LearningEngine

        self.engine = LearningEngine(
            experience_db=str(tmp_path / "experience.jsonl"),
            meta_learning_db=str(tmp_path / "meta.json"),
            benchmark_dir=str(tmp_path / "benchmarks"),
        )
        self.completed: list[str] = []
        self.failed: list[str] = []

    def get_experience(self, top_k=10):
        return self.engine.get_experience(top_k=top_k)

    async def on_session_completed(self, session_id, **kw):
        self.completed.append(session_id)
        return await self.engine.on_session_completed(session_id, **kw)

    async def on_session_failed(self, session_id, **kw):
        self.failed.append(session_id)
        return await self.engine.on_session_failed(session_id, **kw)


def _full_loop(tmp_path) -> SelfImprovementLoop:
    return SelfImprovementLoop(
        planner=FakePlanner(),
        executor=FakeExecutor(),
        manager=FakeManager(),
        reflection=FakeReflection(),
        synthesis=FakeSynthesis(),
        experience=FakeExperience(),
        learning=FakeLearning(tmp_path),
    )


# ── tests ───────────────────────────────────────────────────────────────────


def test_full_cycle_all_phases(tmp_path):
    loop = _full_loop(tmp_path)
    cycle = loop.run("Build a calculator", cycle_id="c1")
    assert cycle.status == "complete"
    assert cycle.cycle_id == "c1"
    assert cycle.error is None
    assert cycle.duration_seconds is not None and cycle.duration_seconds >= 0

    planner, executor, manager = loop._planner, loop._executor, loop._manager
    assert planner.calls and planner.calls[0]["session_id"] == "c1"
    assert executor.calls == 1
    assert manager.events == ["start", "error", "complete:True"]
    assert loop._reflection.calls == 1
    assert loop._synthesis.calls == 1
    assert len(cycle.syntheses) == 1
    # synthesis actionable → experience recorded
    assert len(cycle.experience_stored) == 1
    # substrate fed (donor's dead write path, now wired)
    assert loop._learning.completed == ["c1"]
    assert cycle.learning_record_id == "c1"


def test_guidance_folded_into_prompt(tmp_path):
    exp = _FakeExperienceRecord("e1", guidance="prefer small steps")
    loop = SelfImprovementLoop(
        planner=FakePlanner(),
        executor=FakeExecutor(),
        experience=FakeExperience(records=(exp,)),
    )
    cycle = loop.run("Build X")
    assert cycle.status == "complete"
    prompt = loop._planner.calls[0]["prompt"]
    assert "prefer small steps" in prompt
    assert loop._experience.recall_calls == 1


def test_executor_failure_feeds_substrate_failed(tmp_path):
    failed_record = _Record(
        status="failed", error_summary="boom", test_results=()
    )
    learning = FakeLearning(tmp_path)
    loop = SelfImprovementLoop(
        planner=FakePlanner(),
        executor=FakeExecutor(record=failed_record),
        learning=learning,
    )
    cycle = loop.run("Build X", cycle_id="cf")
    # executor record is 'failed' → success=False, but phases still run
    assert cycle.execution_status == "failed"
    assert cycle.status == "complete"  # loop completed; execution did not
    assert learning.completed == ["cf"]
    assert learning.failed == []


def test_planner_missing_degrades_to_failed():
    loop = SelfImprovementLoop(executor=FakeExecutor())
    cycle = loop.run("Build X")
    assert cycle.status == "failed"
    assert "planner not wired" in (cycle.error or "")
    assert not loop._cycles[0].experience_stored


def test_executor_missing_degrades_to_failed():
    loop = SelfImprovementLoop(planner=FakePlanner())
    cycle = loop.run("Build X")
    assert cycle.status == "failed"
    assert "executor not wired" in (cycle.error or "")


def test_unexpected_engine_error_marks_failed_not_raises(tmp_path):
    class ExplodingPlanner:
        async def generate_spec(self, **kw):
            raise RuntimeError("planner exploded")

    loop = SelfImprovementLoop(planner=ExplodingPlanner(), learning=FakeLearning(tmp_path))
    cycle = loop.run("Build X", cycle_id="cx")
    assert cycle.status == "failed"
    assert "planner exploded" in (cycle.error or "")
    # honest failed-substrate feed
    assert loop._learning.failed == ["cx"]


def test_max_cycles_cap(tmp_path):
    loop = SelfImprovementLoop(max_cycles=2, **_full_engine_kwargs(tmp_path))
    loop.run("a")
    loop.run("b")
    with pytest.raises(RuntimeError, match="Maximum cycles"):
        loop.run("c")


def test_health_shape_and_clear(tmp_path):
    loop = _full_loop(tmp_path)
    loop.run("a")
    health = loop.get_loop_health()
    assert health["total_cycles"] == 1
    assert health["completed"] == 1
    assert health["success_rate"] == 1.0
    assert health["learning_substrate_wired"] is True
    assert len(health["recent_cycles"]) == 1
    assert len(loop) == 1
    loop.clear_cycles()
    assert len(loop) == 0
    assert loop.get_loop_health()["total_cycles"] == 0


def test_unwired_loop_health(tmp_path):
    loop = SelfImprovementLoop()
    health = loop.get_loop_health()
    assert health["learning_substrate_wired"] is False
    assert health["experience_health"] is None


def test_driver_integration_run_cycle_now(tmp_path):
    loop = _full_loop(tmp_path)
    driver = LearningDriver(loop=loop, enabled=True, interval=999.0)
    summary = asyncio.run(driver.run_cycle_now("Build Y"))
    assert summary["status"] == "complete"
    assert summary["id"] == "cycle-" + summary["id"].split("-", 1)[1]
    status = driver.get_status()
    assert status["orchestrator_ready"] is True
    assert status["loop_health"]["total_cycles"] == 1
    assert status["loop_cycles"] == 1
    assert len(driver._cycle_log) == 1


def test_substrate_record_persisted_to_disk(tmp_path):
    loop = _full_loop(tmp_path)
    loop.run("Build Z", cycle_id="cz")
    lines = (tmp_path / "experience.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    import json

    rec = json.loads(lines[0])
    assert rec["session_id"] == "cz"
    assert rec["success"] is True


def _full_engine_kwargs(tmp_path) -> dict[str, Any]:
    return {
        "planner": FakePlanner(),
        "executor": FakeExecutor(),
        "manager": FakeManager(),
        "reflection": FakeReflection(),
        "synthesis": FakeSynthesis(),
        "experience": FakeExperience(),
        "learning": FakeLearning(tmp_path),
    }
