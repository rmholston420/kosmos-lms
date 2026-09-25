"""Kernel learning engine (ADR-143, T3 — self-improvement substrate).

Donor-faithful port of tektos-ultima-v1's ``SelfImprovementAdapter``
(``src/tektos/self_improvement/engine.py``, 672 lines) into the kernel
learning substrate. This is the generic *learning machinery* — the
experience ledger, meta-learning store, benchmark store, and their read
API — elevated to shared infrastructure per the user's porting rule.

What this engine does (donor semantics, preserved):
* **Ledger** — append-only JSONL of :class:`ExperienceRecord`
  (``~/.tektos/experience.jsonl`` by default) + dual-persist to Hindsight.
* **Meta-learning** — per-model / per-task-type quality + improvement
  counters (``~/.tektos/meta_learning.json``).
* **Benchmark store** — one JSON file per session (``~/.tektos/benchmarks/``).
* **Read API** — ``get_experience`` / ``query_experience`` /
  ``get_learning_metrics`` / ``get_report``.
* **Write API** — ``on_session_completed`` / ``on_session_failed`` (the
  cybernetic feedback loop: evaluate → reflect → skill → meta-learn →
  benchmark → record).

DI seams (the substrate never imports plugins, ADR-007):
* ``hindsight_retainer`` — duck-typed ``.retain(content, *, context, tags)``
  (the donor's ``HindsightClient`` shape). ``None`` → JSONL-only.
* ``tick_emitter`` — async ``emitter(session_id, event_type, payload)``
  (the donor's ``ws_event_emitter`` shape). ``None`` → no ticks.
* ``skill_creator`` — duck-typed ``.create_skill_from_reflection(...)``
  returning skill objects with a ``.name``. ``None`` → no skill creation.

The openhands-ext optional engine is retained as a fail-open try/import,
exactly as the donor: when present it supplies ``evaluate_task`` and
``run_reflection``; when absent (the Collosus state) the engine falls back
to its pure-Tektos heuristic evaluation and empty reflection.

Donor gap closed (see package docstring): the loop layer (S4,
``plugins/tektos/self_improve/loop.py``) calls ``on_session_completed`` per
cycle, so the ledger is actually populated — in the donor these write paths
had zero callers.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from kernel.learning.models import ExperienceRecord

logger = logging.getLogger(__name__)

# A "tick emitter" is an async callable: (session_id, event_type, payload).
TickEmitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]
# A "hindsight retainer" is duck-typed with a sync .retain(content, *, context, tags).
HindsightRetainer = Any
# A "skill creator" is duck-typed with .create_skill_from_reflection(...) -> [obj.name].
SkillCreator = Any


@dataclass
class _OhEngine:
    """Holds the optional openhands-ext engine, or ``None`` when absent."""

    evaluate: Optional[Callable[..., dict[str, Any]]] = None
    reflect: Optional[Callable[..., dict[str, Any]]] = None


class LearningEngine:
    """Kernel learning substrate (donor ``SelfImprovementAdapter``).

    The generic experience → evaluation → meta-learning → benchmark loop,
    with a file-based ledger + Hindsight dual-persist. Tektos-agnostic: the
    Tektos *policy* (the Hegelian cycle) drives this engine; the engine
    itself only knows how to record and report learning.
    """

    def __init__(
        self,
        experience_db: str | None = None,
        meta_learning_db: str | None = None,
        benchmark_dir: str | None = None,
        skill_dir: str | None = None,
        tick_emitter: TickEmitter | None = None,
        hindsight_retainer: HindsightRetainer | None = None,
        skill_creator: SkillCreator | None = None,
    ) -> None:
        self.experience_db = Path(
            experience_db or str(Path.home() / ".tektos/experience.jsonl")
        )
        self.meta_learning_db = Path(
            meta_learning_db or str(Path.home() / ".tektos/meta_learning.json")
        )
        self.benchmark_dir = Path(
            benchmark_dir or str(Path.home() / ".tektos/benchmarks")
        )
        self.skill_dir = Path(skill_dir or str(Path.home() / ".hermes/skills/"))

        self._tick_emitter = tick_emitter
        self._hindsight_retainer = hindsight_retainer
        self._skill_creator = skill_creator

        # Ensure parent dirs exist (donor-faithful).
        for p in [self.experience_db, self.meta_learning_db, self.benchmark_dir]:
            p.parent.mkdir(parents=True, exist_ok=True)

        # Optional openhands-ext engine — fail-open, exactly as the donor.
        self._oh_engine = self._try_load_oh_engine()

    # ── Optional openhands-ext hook (donor-faithful) ──────────────────────

    def _try_load_oh_engine(self) -> _OhEngine:
        try:
            from openhands_ext.self_improvement.engine import (  # type: ignore
                SelfImprovementEngine,
            )
        except ImportError:
            logger.info(
                "openhands-ext not available — using pure-Tektos learning fallback"
            )
            return _OhEngine()

        try:
            oh = SelfImprovementEngine(
                experience_db=str(self.experience_db),
                meta_learning_db=str(self.meta_learning_db),
                benchmark_results=str(self.benchmark_dir),
                skill_dir=str(self.skill_dir),
            )
            logger.info("LearningEngine: openhands-ext engine loaded")
            return _OhEngine(evaluate=oh.evaluate_task, reflect=oh.run_reflection)
        except Exception:  # noqa: BLE001 — degrade open, donor-faithful
            logger.exception("LearningEngine: openhands-ext init failed; pure fallback")
            return _OhEngine()

    # ── Session Completion Handler ───────────────────────────────────────

    async def on_session_completed(
        self,
        session_id: str,
        task: str,
        spec: str,
        model_used: str,
        success: bool,
        tests_passed: int,
        tests_total: int,
        wall_time_seconds: float,
        output_files: list[str] | None = None,
        **extra: Any,
    ) -> ExperienceRecord:
        """Main entry point for the cybernetic feedback loop (donor-faithful)."""
        logger.info(
            "[LEARNING] session=%s success=%s model=%s",
            session_id,
            success,
            model_used,
        )

        await self._emit_tick(
            session_id,
            "evaluation.started",
            data={"task": task, "model": model_used},
        )

        evaluation = self._evaluate(
            session_id,
            task,
            spec,
            output_files or [],
            tests_passed,
            tests_total,
        )

        await self._emit_tick(
            session_id,
            "evaluation.complete",
            data={
                "score": evaluation["overall_score"],
                "violations": evaluation.get("spec_violations", []),
            },
        )

        reflection = self._reflect(
            task=task,
            spec=spec,
            success=success,
            tests_passed=tests_passed,
            tests_total=tests_total,
            model_used=model_used,
            spec_violations=evaluation.get("spec_violations", []),
            code_issues=evaluation.get("code_issues", []),
            wall_time_seconds=wall_time_seconds,
        )

        created_skill_names: list[str] = []
        if self._skill_creator is not None:
            try:
                new_skills = self._skill_creator.create_skill_from_reflection(
                    lessons=reflection.get("generalizable_lessons", []),
                    what_worked=reflection.get("what_worked", []),
                    what_failed=reflection.get("what_failed", []),
                    what_to_avoid=reflection.get("what_to_avoid", []),
                    recommendations=evaluation.get("recommendations", []),
                )
                created_skill_names = [getattr(s, "name", str(s)) for s in new_skills]
                logger.info(
                    "[LEARNING] Created %d skills from session %s",
                    len(created_skill_names),
                    session_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("[LEARNING] Skill creation failed")

        await self._record_meta_learning(
            model_used,
            task,
            success,
            evaluation["overall_score"],
        )

        await self._record_benchmark(
            session_id,
            model_used,
            success,
            tests_passed,
            tests_total,
            wall_time_seconds,
        )

        record = ExperienceRecord(
            session_id=session_id,
            task=task,
            model_used=model_used,
            success=success,
            tests_passed=tests_passed,
            tests_total=tests_total,
            wall_time_seconds=wall_time_seconds,
            evaluation_score=evaluation["overall_score"],
            spec_violations=evaluation.get("spec_violations", []),
            code_issues=evaluation.get("code_issues", []),
            lessons=reflection.get("generalizable_lessons", []),
            what_worked=reflection.get("what_worked", []),
            what_failed=reflection.get("what_failed", []),
            what_to_avoid=reflection.get("what_to_avoid", []),
            recommendations=evaluation.get("recommendations", []),
            created_skills=created_skill_names,
            meta_data=evaluation,
        )

        self._save_experience(record)

        await self._emit_tick(
            session_id,
            "reflection.complete",
            data={
                "lessons": record.lessons,
                "skills_created": record.created_skills,
            },
        )

        logger.info(
            "[LEARNING] session=%s recorded score=%.2f lessons=%d",
            session_id,
            record.evaluation_score,
            len(record.lessons),
        )

        return record

    async def on_session_failed(
        self,
        session_id: str,
        task: str,
        spec: str,
        model_used: str,
        error: str,
        wall_time_seconds: float,
    ) -> ExperienceRecord:
        """Handle failed sessions — trigger auto-evaluation and reflection (donor)."""
        logger.warning("[LEARNING] session=%s failed: %s", session_id, error)

        await self._emit_tick(
            session_id,
            "failure.detected",
            data={"error": error, "model": model_used},
        )

        evaluation = {
            "overall_score": 0.0,
            "spec_violations": [],
            "code_issues": [f"Session failed: {error}"],
            "recommendations": ["Analyze failure root cause and adjust approach"],
        }

        await self._record_meta_learning(model_used, task, False, 0.0)

        record = ExperienceRecord(
            session_id=session_id,
            task=task,
            model_used=model_used,
            success=False,
            tests_passed=0,
            tests_total=0,
            wall_time_seconds=wall_time_seconds,
            evaluation_score=0.0,
            code_issues=evaluation["code_issues"],
            what_failed=[error],
            recommendations=evaluation["recommendations"],
        )

        self._save_experience(record)

        await self._emit_tick(
            session_id,
            "failure.recorded",
            data={"lessons": record.lessons},
        )

        return record

    # ── Experience Buffer ────────────────────────────────────────────────

    def _save_experience(self, record: ExperienceRecord) -> None:
        """Append to JSONL + dual-persist to Hindsight (donor-faithful)."""
        with open(self.experience_db, "a") as f:
            f.write(record.to_json() + "\n")
        self._save_to_hindsight(record)

    def _save_to_hindsight(self, record: ExperienceRecord) -> None:
        """Dual-persist to Hindsight for cross-session semantic memory."""
        if self._hindsight_retainer is None:
            return
        try:
            parts = [
                f"Session {record.session_id}: {record.task}",
                f"Model: {record.model_used}",
                f"Result: {'SUCCESS' if record.success else 'FAILED'}",
                f"Tests: {record.tests_passed}/{record.tests_total}",
                f"Score: {record.evaluation_score:.2f}",
                f"Time: {record.wall_time_seconds:.0f}s",
            ]
            if record.lessons:
                parts.append(f"Lessons: {'; '.join(record.lessons[:3])}")
            if record.what_worked:
                parts.append(f"What worked: {'; '.join(record.what_worked[:3])}")
            if record.what_failed:
                parts.append(f"What failed: {'; '.join(record.what_failed[:3])}")
            if record.what_to_avoid:
                parts.append(f"Avoid: {'; '.join(record.what_to_avoid[:3])}")
            if record.recommendations:
                parts.append(f"Recommendations: {'; '.join(record.recommendations[:3])}")
            content = "\n".join(parts)

            self._hindsight_retainer.retain(
                content=content,
                context=f"self-improvement:{record.model_used}:{record.task[:50]}",
                tags=[
                    "tektos",
                    "self-improvement",
                    "experience",
                    "success" if record.success else "failure",
                    record.model_used,
                ],
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to persist experience to Hindsight: %s", e)

    def get_experience(self, top_k: int = 10) -> list[ExperienceRecord]:
        """Load recent experience records (donor-faithful)."""
        if not self.experience_db.exists():
            return []
        records: list[ExperienceRecord] = []
        with open(self.experience_db) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                with contextlib.suppress(json.JSONDecodeError, KeyError):
                    records.append(ExperienceRecord.from_dict(json.loads(line)))
        return records[:top_k]

    def query_experience(
        self,
        task_keywords: list[str] | None = None,
        success_only: bool = False,
        failed_only: bool = False,
        top_k: int = 5,
    ) -> list[ExperienceRecord]:
        """Query experiences by keywords and success/failure (donor-faithful)."""
        records = self.get_experience(top_k=top_k * 2)
        filtered = []
        for r in records:
            if success_only and not r.success:
                continue
            if failed_only and r.success:
                continue
            if task_keywords:
                task_lower = r.task.lower()
                if not any(kw.lower() in task_lower for kw in task_keywords):
                    continue
            filtered.append(r)
        return filtered[:top_k]

    # ── Pure-Tektos Evaluation (fallback) ────────────────────────────────

    def _evaluate(
        self,
        session_id: str,
        task: str,
        spec: str,
        output_files: list[str],
        tests_passed: int,
        tests_total: int,
    ) -> dict[str, Any]:
        """Self-evaluation: score, spec compliance, code quality (donor)."""
        if self._oh_engine.evaluate is not None:
            try:
                return self._oh_engine.evaluate(
                    task=task,
                    spec=spec,
                    output_files=output_files,
                    tests_passed=tests_passed,
                    tests_total=tests_total,
                )
            except Exception:  # noqa: BLE001
                logger.exception("[LEARNING] OpenHands evaluation failed")

        # Pure-Tektos fallback — heuristic scoring (donor-faithful).
        test_score = tests_passed / tests_total if tests_total > 0 else 0.0
        spec_score = 1.0 if not spec else 0.0  # Simplified
        code_score = 1.0  # No files to check
        overall = test_score * 0.5 + spec_score * 0.3 + code_score * 0.2

        return {
            "overall_score": overall,
            "test_pass_rate": test_score,
            "spec_violations": [],
            "code_issues": [],
            "recommendations": ["Use openhands-ext-v1 for full evaluation"],
        }

    def _reflect(
        self,
        *,
        task: str,
        spec: str,
        success: bool,
        tests_passed: int,
        tests_total: int,
        model_used: str,
        spec_violations: list[str],
        code_issues: list[str],
        wall_time_seconds: float,
    ) -> dict[str, Any]:
        """Reflection via openhands-ext when available; empty otherwise (donor)."""
        if self._oh_engine.reflect is None:
            return {}
        try:
            return self._oh_engine.reflect(
                task=task,
                spec=spec,
                success=success,
                tests_passed=tests_passed,
                tests_total=tests_total,
                model_used=model_used,
                spec_violations=spec_violations,
                code_issues=code_issues,
                wall_time_seconds=wall_time_seconds,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[LEARNING] Reflection failed")
            return {}

    # ── Meta-Learning (pure Tektos) ──────────────────────────────────────

    async def _record_meta_learning(
        self,
        model: str,
        task_type: str,
        success: bool,
        quality_score: float,
    ) -> None:
        """Record model performance for meta-learning (donor-faithful)."""
        meta: dict[str, Any] = {
            "version": "1.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "prompt_patterns": {},
            "model_performance": {},
            "failure_modes": {},
            "learning_metrics": {
                "total_tasks": 0,
                "total_improvements": 0,
                "improvement_history": [],
            },
        }

        if self.meta_learning_db.exists():
            with contextlib.suppress(json.JSONDecodeError):
                meta = json.loads(self.meta_learning_db.read_text())

        if model not in meta["model_performance"]:
            meta["model_performance"][model] = {"task_types": {}, "overall_quality": 0.0}

        if task_type not in meta["model_performance"][model]["task_types"]:
            meta["model_performance"][model]["task_types"][task_type] = {
                "tasks": 0,
                "successes": 0,
                "total_quality": 0.0,
            }

        type_data = meta["model_performance"][model]["task_types"][task_type]
        type_data["tasks"] += 1
        if success:
            type_data["successes"] += 1
        type_data["total_quality"] += quality_score

        model_data = meta["model_performance"][model]
        total_tasks = sum(t["tasks"] for t in model_data["task_types"].values())
        total_quality = sum(t["total_quality"] for t in model_data["task_types"].values())
        model_data["overall_quality"] = (
            total_quality / total_tasks if total_tasks > 0 else 0.0
        )

        meta["learning_metrics"]["total_tasks"] += 1
        if quality_score > 0.5:
            meta["learning_metrics"]["total_improvements"] += 1
            meta["learning_metrics"]["improvement_history"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "task_type": task_type,
                    "improvement": quality_score - 0.5,
                }
            )

        self.meta_learning_db.write_text(json.dumps(meta, indent=2))

    async def _record_benchmark(
        self,
        session_id: str,
        model: str,
        success: bool,
        tests_passed: int,
        tests_total: int,
        wall_time_seconds: float,
    ) -> None:
        """Save benchmark result to JSON file (donor-faithful)."""
        self.benchmark_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "session_id": session_id,
            "model": model,
            "success": success,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
            "wall_time_seconds": wall_time_seconds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        result_file = self.benchmark_dir / f"{session_id}.json"
        result_file.write_text(json.dumps(result, indent=2))

    # ── Tick Emitter ─────────────────────────────────────────────────────

    async def _emit_tick(
        self,
        session_id: str,
        tick_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a self_improvement.tick (donor shape, via injected emitter)."""
        if self._tick_emitter is None:
            return
        try:
            payload = {"tick": tick_type, **data} if data else {"tick": tick_type}
            await self._tick_emitter(session_id, "self_improvement.tick", payload)
        except Exception:  # noqa: BLE001 — degrade open
            logger.exception("[LEARNING] tick emit failed")

    # ── Public Read API ──────────────────────────────────────────────────

    def get_learning_metrics(self) -> dict[str, Any]:
        """Get current learning metrics (donor-faithful)."""
        if not self.meta_learning_db.exists():
            return {
                "total_tasks": 0,
                "total_improvements": 0,
                "learning_velocity": 0.0,
                "model_rankings": [],
                "best_model_for_coding": None,
            }

        try:
            meta = json.loads(self.meta_learning_db.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {
                "total_tasks": 0,
                "total_improvements": 0,
                "learning_velocity": 0.0,
            }

        metrics = meta.get("learning_metrics", {})
        total = metrics.get("total_tasks", 0)
        improvements = metrics.get("total_improvements", 0)

        model_perf = meta.get("model_performance", {})
        rankings = []
        for model, data in model_perf.items():
            for task_type, tdata in data.get("task_types", {}).items():
                avg_quality = (
                    tdata["total_quality"] / tdata["tasks"] if tdata["tasks"] > 0 else 0
                )
                rankings.append(
                    {
                        "model": model,
                        "task_type": task_type,
                        "tasks": tdata["tasks"],
                        "successes": tdata["successes"],
                        "avg_quality": round(avg_quality, 3),
                    }
                )
        rankings.sort(key=lambda x: x["avg_quality"], reverse=True)

        return {
            "total_tasks": total,
            "total_improvements": improvements,
            "learning_velocity": round(improvements / total, 3) if total > 0 else 0.0,
            "model_rankings": rankings[:10],
            "best_model_for_coding": (rankings[0]["model"] if rankings else None),
        }

    def get_report(self) -> str:
        """Generate self-improvement report (donor-faithful)."""
        metrics = self.get_learning_metrics()
        lines = [
            "# SELF-IMPROVEMENT REPORT",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Learning Metrics",
            f"- Total Tasks: {metrics['total_tasks']}",
            f"- Total Improvements: {metrics['total_improvements']}",
            f"- Learning Velocity: {metrics['learning_velocity']:.2f} improvements/task",
            "",
            "## Model Performance",
        ]
        for r in metrics.get("model_rankings", [])[:5]:
            lines.append(
                f"- {r['model']}: avg_quality={r['avg_quality']:.2f}, "
                f"tasks={r['tasks']}, successes={r['successes']}"
            )
        lines.append("")
        lines.append("## Recommendations")
        if metrics.get("best_model_for_coding"):
            lines.append(f"- Use {metrics['best_model_for_coding']} for coding tasks")
        if metrics.get("learning_velocity", 0.0) < 0.1:
            lines.append(
                "- Learning velocity is low — consider more diverse task types"
            )
        return "\n".join(lines)


# ── Module-level singleton (mirrors kernel.reliability) ─────────────────────

_engine: LearningEngine | None = None


def get_learning_engine(**kwargs: Any) -> LearningEngine:
    """Get or create the global learning engine (composition-root seam)."""
    global _engine
    if _engine is None:
        _engine = LearningEngine(**kwargs)
    return _engine


def reset_learning_engine() -> None:
    """Reset the global learning engine (for testing)."""
    global _engine
    _engine = None


__all__ = [
    "LearningEngine",
    "ExperienceRecord",
    "get_learning_engine",
    "reset_learning_engine",
]
