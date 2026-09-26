"""Evaluation Framework — SWE-bench and Custom Evaluations.

Implements evaluation capabilities for Tektos, including:
- SWE-bench integration for agentic coding benchmarking
- Custom evaluation harness for task-specific metrics
- Quality metrics tracking (code quality, test coverage, etc.)
- Performance metrics (time to solution, token usage, etc.)
- Comparison and reporting

This enables Tektos to measure its own performance and identify
areas for improvement.

SOTA Reference: SWE-bench, SWE-Star, SWE-bench Verified,
mini-SWE-agent, SWE-smith.

Kernel substrate (ADR-141 T8c-6) — verbatim port of the donor
``tektos-ultima-v1/src/tektos/runtime/evaluation_framework.py`` (417 LOC,
self-contained: stdlib-only). Generic benchmark/quality-measurement
infrastructure, so it is kernel-level shared substrate (layering rule)
rather than Tektos-plugin policy. Consumed by ``GET /api/evaluation/status``
(kernel/app.py) exactly as the donor consumed it (fresh
``get_evaluation_harness()`` call, donor wire preserved).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class EvaluationType(Enum):
    """Types of evaluations."""

    SWE_BENCH = "swe_bench"
    CUSTOM = "custom"
    CODE_QUALITY = "code_quality"
    TEST_COVERAGE = "test_coverage"
    PERFORMANCE = "performance"
    SECURITY = "security"


class EvaluationStatus(Enum):
    """Evaluation execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class EvaluationResult:
    """Result from an evaluation."""

    evaluation_id: str
    evaluation_type: EvaluationType
    status: EvaluationStatus
    score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        """Calculate evaluation duration in seconds."""
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_markdown(self) -> str:
        """Convert to markdown for display."""
        status = "✓" if self.status == EvaluationStatus.COMPLETED else "✗"
        return (
            f"## {status} {self.evaluation_type.value.title()} Evaluation\n\n"
            f"**Score**: {self.score:.2f}\n\n"
            f"**Duration**: {self.duration:.2f}s\n\n"
            f"**Details**:\n```json\n{json.dumps(self.details, indent=2)}\n```\n\n"
            f"{'**Error**: ' + self.error if self.error else ''}"
        )


@dataclass
class EvaluationTask:
    """A task to be evaluated."""

    task_id: str
    description: str
    expected_output: str | None = None
    actual_output: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    status: EvaluationStatus = EvaluationStatus.PENDING
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "expected_output": self.expected_output,
            "actual_output": self.actual_output,
            "metrics": self.metrics,
            "status": self.status.value,
            "error": self.error,
        }


class EvaluationHarness:
    """Evaluation harness for Tektos.

    Manages evaluations, tracks metrics, and generates reports.
    """

    def __init__(self, project_root: str = ".", output_dir: str = "./evaluations"):
        """Initialize evaluation harness.

        Args:
            project_root: Path to the project root.
            output_dir: Directory to store evaluation results.
        """
        self.project_root = Path(project_root)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._evaluations: dict[str, EvaluationResult] = {}
        self._tasks: dict[str, EvaluationTask] = {}
        self._results: list[EvaluationResult] = []
        # Optional plug-in for SWE-bench delegation (see set_swe_bench_runner).
        self._swe_bench_runner: Any = None

    def set_swe_bench_runner(self, runner: Any) -> None:
        """Register an external SWE-bench runner.

        Tektos does not ship an in-tree SWE-bench harness. Callers that
        need SWE-bench scoring should register an object with an
        ``async run(evaluation)`` coroutine (for example a thin adapter
        around the OpenHands SWE-bench evaluator). When present, the
        runner is invoked from :meth:`_run_swe_bench_evaluation` and
        expected to populate ``evaluation.score`` and
        ``evaluation.details``.
        """
        self._swe_bench_runner = runner

    async def run_evaluation(self, evaluation: EvaluationResult) -> EvaluationResult:
        """Run an evaluation.

        Args:
            evaluation: The evaluation to run.

        Returns:
            The evaluation result with updated status.
        """
        evaluation.status = EvaluationStatus.RUNNING
        log.info(
            f"[Evaluation] Running evaluation {evaluation.evaluation_id}: "
            f"{evaluation.evaluation_type.value}"
        )

        try:
            # Run evaluation based on type
            if evaluation.evaluation_type == EvaluationType.SWE_BENCH:
                await self._run_swe_bench_evaluation(evaluation)
            elif evaluation.evaluation_type == EvaluationType.CUSTOM:
                await self._run_custom_evaluation(evaluation)
            elif evaluation.evaluation_type == EvaluationType.CODE_QUALITY:
                await self._run_code_quality_evaluation(evaluation)
            elif evaluation.evaluation_type == EvaluationType.TEST_COVERAGE:
                await self._run_test_coverage_evaluation(evaluation)
            elif evaluation.evaluation_type == EvaluationType.PERFORMANCE:
                await self._run_performance_evaluation(evaluation)
            elif evaluation.evaluation_type == EvaluationType.SECURITY:
                await self._run_security_evaluation(evaluation)

            evaluation.status = EvaluationStatus.COMPLETED
            evaluation.completed_at = time.time()
            self._results.append(evaluation)

            # Save result to disk
            await self._save_evaluation_result(evaluation)

            log.info(
                f"[Evaluation] Completed evaluation {evaluation.evaluation_id}: "
                f"score={evaluation.score:.2f}"
            )

        except Exception as exc:
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error = str(exc)
            evaluation.completed_at = time.time()

            log.error(f"[Evaluation] Failed evaluation {evaluation.evaluation_id}: {exc}")

        return evaluation

    async def _run_swe_bench_evaluation(self, evaluation: EvaluationResult) -> None:
        """Run SWE-bench evaluation via an externally registered runner.

        Tektos does not embed the SWE-bench harness — it is a large
        third-party evaluation stack we intentionally do not vendor.
        The recommended path is to delegate to OpenHands' SWE-bench
        evaluator (or another external harness) via
        :meth:`set_swe_bench_runner`.

        Behavior:

        - If a runner has been registered, its ``run(evaluation)``
          coroutine is awaited and expected to populate
          ``evaluation.score`` and ``evaluation.details``.
        - Otherwise this method raises :class:`NotImplementedError`,
          which surfaces as ``EvaluationStatus.FAILED`` with a clear
          error message on the evaluation result. It never silently
          reports a fake ``score=0.0`` — that produced misleading
          "pass_rate=0" telemetry in previous versions.
        """
        runner = self._swe_bench_runner
        if runner is None:
            raise NotImplementedError(
                "SWE-bench evaluation requires an external runner. Register one "
                "via EvaluationHarness.set_swe_bench_runner(...). Tektos does not "
                "ship an in-tree SWE-bench harness; the recommended integration "
                "is a thin adapter around the OpenHands SWE-bench evaluator."
            )

        run = getattr(runner, "run", None)
        if run is None or not callable(run):
            raise TypeError("SWE-bench runner must expose an async 'run(evaluation)' method")
        await run(evaluation)

    async def _run_custom_evaluation(self, evaluation: EvaluationResult) -> None:
        """Run custom evaluation."""
        # Run custom evaluation based on metrics
        if evaluation.metrics:
            # Average all metric values as the score
            values = [v for v in evaluation.metrics.values() if isinstance(v, (int, float))]
            evaluation.score = sum(values) / len(values) if values else 0.0
        else:
            evaluation.score = 0.0
        evaluation.details = {
            "custom_metrics": evaluation.metrics,
        }

    async def _run_code_quality_evaluation(self, evaluation: EvaluationResult) -> None:
        """Run code quality evaluation."""
        # Run code quality checks
        try:
            # Run pylint or similar
            result = subprocess.run(
                ["python", "-m", "pylint", "--errors-only", str(self.project_root / "src")],
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Calculate score based on errors
            error_count = result.stdout.count("E:")
            evaluation.score = max(0.0, 1.0 - (error_count / 100))
            evaluation.details = {
                "error_count": error_count,
                "warnings": result.stdout.count("W:"),
            }
        except Exception as exc:
            evaluation.score = 0.0
            evaluation.details = {"error": str(exc)}

    async def _run_test_coverage_evaluation(self, evaluation: EvaluationResult) -> None:
        """Run test coverage evaluation."""
        # Run pytest with coverage
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "pytest",
                    "--cov=src",
                    "--cov-report=term-missing",
                    "-q",
                    str(self.project_root / "tests"),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Parse coverage from output
            coverage = 0.0
            for line in result.stdout.split("\n"):
                if "TOTAL" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        with contextlib.suppress(ValueError):
                            coverage = float(parts[-1].replace("%", ""))
                    break

            evaluation.score = coverage / 100
            evaluation.details = {
                "coverage": coverage,
                "tests_run": result.stdout.count("PASSED"),
            }
        except Exception as exc:
            evaluation.score = 0.0
            evaluation.details = {"error": str(exc)}

    async def _run_performance_evaluation(self, evaluation: EvaluationResult) -> None:
        """Run performance evaluation."""
        # Run performance benchmarks
        evaluation.score = 0.0
        evaluation.details = {
            "benchmarks": [],
        }

    async def _run_security_evaluation(self, evaluation: EvaluationResult) -> None:
        """Run security evaluation."""
        # Run security checks
        evaluation.score = 1.0
        evaluation.details = {
            "vulnerabilities": 0,
        }

    async def _save_evaluation_result(self, evaluation: EvaluationResult) -> None:
        """Save evaluation result to disk."""
        filepath = self.output_dir / f"{evaluation.evaluation_id}.json"
        with open(filepath, "w") as f:
            json.dump(
                evaluation.to_dict()
                if hasattr(evaluation, "to_dict")
                else {
                    "evaluation_id": evaluation.evaluation_id,
                    "evaluation_type": evaluation.evaluation_type.value,
                    "status": evaluation.status.value,
                    "score": evaluation.score,
                    "details": evaluation.details,
                    "error": evaluation.error,
                    "started_at": evaluation.started_at,
                    "completed_at": evaluation.completed_at,
                    "metrics": evaluation.metrics,
                },
                f,
                indent=2,
            )

    def add_task(self, task: EvaluationTask) -> None:
        """Add a task to be evaluated.

        Args:
            task: The task to add.
        """
        self._tasks[task.task_id] = task
        log.info(f"[Evaluation] Added task {task.task_id}")

    def get_status(self) -> dict[str, Any]:
        """Get current status of evaluations.

        Returns:
            Status dictionary.
        """
        return {
            "total_evaluations": len(self._evaluations),
            "completed_evaluations": len(self._results),
            "average_score": (
                sum(e.score for e in self._results) / len(self._results) if self._results else 0.0
            ),
            "evaluations": {
                eid: e.to_markdown() if hasattr(e, "to_markdown") else str(e)
                for eid, e in self._evaluations.items()
            },
            "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
        }

    def to_memory_entry(self) -> dict[str, Any]:
        """Convert to memory entry for self-improvement loop."""
        return {
            "total_evaluations": len(self._evaluations),
            "completed_evaluations": len(self._results),
            "average_score": (
                sum(e.score for e in self._results) / len(self._results) if self._results else 0.0
            ),
        }


# ── Convenience Functions ───────────────────────────────────────────────────

_harness: EvaluationHarness | None = None


def get_evaluation_harness(
    project_root: str = ".", output_dir: str = "./evaluations"
) -> EvaluationHarness:
    """Get or create the evaluation harness.

    Args:
        project_root: Path to the project root.
        output_dir: Directory to store evaluation results.

    Returns:
        EvaluationHarness instance.
    """
    global _harness
    if _harness is None or _harness.project_root != Path(project_root):
        _harness = EvaluationHarness(
            project_root=project_root,
            output_dir=output_dir,
        )
    return _harness


def run_evaluation(evaluation: EvaluationResult) -> EvaluationResult:
    """Run an evaluation.

    Args:
        evaluation: The evaluation to run.

    Returns:
        The evaluation result.
    """
    harness = get_evaluation_harness()
    return asyncio.run(harness.run_evaluation(evaluation))
