"""Tektos Hegelian self-improvement loop (ADR-143 T3 / S4).

Donor-faithful port of tektos-ultima-v1
``src/tektos/agents/self_improvement/loop_orchestrator.py``
(``SelfImprovementLoop``), adapted onto the Kosmos kernel's five Tektos
engines instead of the donor's monolithic ``MemorySystem``:

    thesis      → spec_planner.generate_spec   (TektosSpecPlanner)
    antithesis  → executor.execute_spec        (TektosSpecExecutor)
    regulation  → manager.on_task_*            (TektosManager)
    reflection  → reflection.reflect_on_turn   (ReflectionEngine)
    synthesis   → synthesis.synthesize         (SynthesisEngine)
    memory      → experience.record            (ExperienceReplay)

KOSMOS IMPROVEMENT over the donor (the dead write path the donor never
wired): every completed cycle ALSO feeds the kernel learning substrate
(``kernel.learning.LearningEngine.on_session_completed`` /
``on_session_failed``) — the donor's ``SelfImprovementAdapter``
write path had ZERO callers, so its experience ledger never grew from
the loop. Here the loop is the substrate's producer.

DI seams (ADR-007: the plugin owns the policy, the kernel owns the
substrate; the composition root injects both at boot): every engine is
optional. A missing engine degrades that phase honestly (logged, phase
skipped) — the cycle still completes the phases whose engines are
wired. The learning substrate is optional too; when unwired the loop
still runs (memory-only mode) but the substrate ledger does not grow.

Donor semantics preserved:
* the cycle state machine (planning → executing → reflecting →
  synthesizing → complete / failed) and the ``LoopCycle`` shape
  (``cycle_id`` / ``status`` / ``syntheses`` / ``experience_stored`` /
  ``duration_seconds`` / ``error``) — the driver's
  ``_summarize_cycle`` consumes exactly this shape;
* ``max_cycles`` cap (donor raises ``RuntimeError`` when exceeded);
* guidance from prior experiences is folded into the planner context
  (the kernel planner has no ``synthesis_guidance`` parameter — the
  adaptation documented in ADR-143 D5);
* the loop never raises out of ``run`` — a phase failure marks the
  cycle ``failed`` with the error string (donor's try/except).

The kernel engines are async while the driver drives ``run`` via
``asyncio.to_thread`` (sync, donor-faithful), so :meth:`run` is a sync
facade that owns its own event loop via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Context tag used when recalling prior experiences for guidance
# (donor used "software_engineering" as the default context).
_CONTEXT = "software_engineering"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LoopCycle:
    """A single iteration of the self-improvement loop.

    Donor ``LoopCycle`` pydantic model, frozen-slotted per Kosmos
    convention. The driver's ``_summarize_cycle`` reads ``cycle_id``,
    ``status``, ``prompt``, ``syntheses``, ``experience_stored``,
    ``duration_seconds`` and ``error`` — all preserved verbatim.
    """

    cycle_id: str
    timestamp_start: str
    prompt: str
    timestamp_end: str | None = None
    status: str = "pending"  # planning|executing|reflecting|synthesizing|complete|failed
    spec: Any | None = None
    execution_status: str | None = None
    manager_feedback: dict[str, Any] | None = None
    syntheses: list[Any] = field(default_factory=list)
    experience_stored: list[str] = field(default_factory=list)
    learning_record_id: str | None = None
    error: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.timestamp_end and self.timestamp_start:
            start = datetime.fromisoformat(self.timestamp_start)
            end = datetime.fromisoformat(self.timestamp_end)
            return (end - start).total_seconds()
        return None


class SelfImprovementLoop:
    """Orchestrates the full Hegelian self-improvement loop.

    Donor parity + kernel adaptation:

    * ``planner``    — ``TektosSpecPlanner`` (``generate_spec``).
    * ``executor``   — ``TektosSpecExecutor`` (``execute_spec``).
    * ``manager``    — ``TektosManager`` (``on_task_start`` /
      ``on_error`` / ``on_task_complete``).
    * ``reflection`` — ``ReflectionEngine`` (``reflect_on_turn``).
    * ``synthesis``  — ``SynthesisEngine`` (``synthesize``).
    * ``experience`` — ``ExperienceReplay`` (``recall`` / ``record``).
    * ``learning``   — kernel ``LearningEngine`` (substrate;
      ``get_experience`` / ``on_session_completed`` /
      ``on_session_failed``). KOSMOS IMPROVEMENT: the donor loop never
      fed its own substrate; here it is the substrate's producer.

    Usage:
        loop = SelfImprovementLoop(
            planner=registry.tektos_spec_planner,
            executor=registry.tektos_executor,
            ...
            learning=get_learning_engine(),
        )
        cycle = loop.run("Create a calculator module")
    """

    def __init__(
        self,
        *,
        planner: Any | None = None,
        executor: Any | None = None,
        manager: Any | None = None,
        reflection: Any | None = None,
        synthesis: Any | None = None,
        experience: Any | None = None,
        learning: Any | None = None,
        max_cycles: int = 10,
        experience_recall_limit: int = 3,
        model_used: str = "tektos-loop",
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._manager = manager
        self._reflection = reflection
        self._synthesis = synthesis
        self._experience = experience
        self._learning = learning
        self._cycles: list[LoopCycle] = []
        self._max_cycles = max_cycles
        self._experience_recall_limit = experience_recall_limit
        self._model_used = model_used

    # ── public API (driver contract: sync run / health / clear / len) ────

    def run(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
        cycle_id: str | None = None,
    ) -> LoopCycle:
        """Execute one full loop cycle (sync facade; donor ``run``).

        Donor signature was ``run(prompt, synthesis_guidance, cycle_id,
        context)`` — the ``synthesis_guidance`` parameter is gone in the
        kernel adaptation: guidance is always recalled from the
        experience replay (or the learning substrate as fallback) and
        folded into the planner context.

        Never raises; phase failures mark the cycle ``failed``.
        """
        if len(self._cycles) >= self._max_cycles:
            raise RuntimeError(
                f"Maximum cycles ({self._max_cycles}) reached. "
                "Clear cycles or increase max_cycles."
            )
        return asyncio.run(self._run_async(prompt, context=context, cycle_id=cycle_id))

    def get_loop_health(self) -> dict[str, Any]:
        """Donor ``get_loop_health`` — loop + experience health."""
        completed = [c for c in self._cycles if c.status == "complete"]
        failed = [c for c in self._cycles if c.status == "failed"]
        total_syntheses = sum(len(c.syntheses) for c in self._cycles)
        total_experiences = sum(len(c.experience_stored) for c in self._cycles)

        experience_health: Any = None
        recent = None
        if self._experience is not None:
            try:
                recent = self._experience.recent(limit=5)
            except Exception:  # noqa: BLE001
                logger.exception("self_improve.loop: experience.recent failed")
            experience_health = {
                "records_in_buffer": len(recent) if recent is not None else None,
                "persistence_bound": bool(
                    getattr(self._experience, "is_persistence_bound", lambda: False)()
                ),
            }

        return {
            "total_cycles": len(self._cycles),
            "completed": len(completed),
            "failed": len(failed),
            "success_rate": len(completed) / max(len(self._cycles), 1),
            "total_syntheses": total_syntheses,
            "total_experiences_stored": total_experiences,
            "learning_substrate_wired": self._learning is not None,
            "experience_health": experience_health,
            "recent_cycles": [
                {
                    "id": c.cycle_id,
                    "status": c.status,
                    "syntheses": len(c.syntheses),
                    "experiences": len(c.experience_stored),
                    "error": c.error,
                }
                for c in self._cycles[-5:]
            ],
        }

    def clear_cycles(self) -> None:
        """Clear cycle history. Engines (experience/substrate) stay intact."""
        self._cycles.clear()

    def __len__(self) -> int:
        return len(self._cycles)

    # ── guidance (donor: experience.get_planner_guidance) ────────────────

    async def _guidance(self) -> str:
        """Build planner guidance from prior experiences (donor parity).

        Preference order: ExperienceReplay recall → learning-substrate
        recent records → empty. Kernel adaptation (ADR-143 D5): the
        kernel planner has no ``synthesis_guidance`` parameter, so the
        guidance string is folded into the ``context`` dict that
        ``generate_spec`` forwards to ``add_spec_context``.
        """
        if self._experience is not None:
            try:
                records = await self._experience.recall(
                    context=_CONTEXT,
                    limit=self._experience_recall_limit,
                )
                if records:
                    return "\n".join(
                        f"- {r.guidance or r.summary}" for r in records
                    )
            except Exception:  # noqa: BLE001
                logger.exception("self_improve.loop: experience.recall failed")
        if self._learning is not None:
            try:
                records = self._learning.get_experience(top_k=self._experience_recall_limit)
                if records:
                    return "\n".join(
                        f"- {lesson}" for r in records for lesson in (r.lessons or ())
                    )
            except Exception:  # noqa: BLE001
                logger.exception("self_improve.loop: learning.get_experience failed")
        return ""

    # ── cycle state machine (donor run() PHASE 1-4) ──────────────────────

    async def _run_async(
        self,
        prompt: str,
        context: dict[str, Any] | None,
        cycle_id: str | None,
    ) -> LoopCycle:
        cid = cycle_id or f"cycle-{uuid.uuid4().hex[:8]}"
        start_ts = _now_iso()
        cycle = LoopCycle(cycle_id=cid, timestamp_start=start_ts, prompt=prompt)
        spec: Any = None
        try:
            # PHASE 1 — Planning (thesis)
            cycle.status = "planning"
            spec = await self._plan(prompt, context, cycle)

            # PHASE 2 — Execution (antithesis)
            cycle.status = "executing"
            record = await self._execute(cid, spec)
            if record is None:
                raise RuntimeError("executor not wired (no execution record)")
            cycle.execution_status = str(getattr(record, "status", ""))

            # PHASE 3 — Regulation (manager feedback)
            cycle.status = "reflecting"
            success = cycle.execution_status == "completed"
            await self._regulate(cid, spec, record, success, cycle)

            # PHASE 4 — Reflection + Synthesis (memory)
            cycle.status = "synthesizing"
            await self._synthesize_phase(cid, spec, record, cycle)

            # PHASE 5 — KOSMOS IMPROVEMENT: feed the learning substrate
            # (the donor's dead write path; see module docstring).
            await self._feed_substrate(cid, spec, record, success, cycle)

            cycle.status = "complete"
        except Exception as exc:  # noqa: BLE001 — donor parity: never raises
            cycle.status = "failed"
            cycle.error = str(exc)[:500]
            # Honest substrate feed even on failure — regardless of whether
            # a spec was produced (a planner crash still leaves a failed
            # session the substrate should learn from).
            await self._feed_substrate_failed(cid, spec, cycle)

        cycle.timestamp_end = _now_iso()
        self._cycles.append(cycle)
        return cycle

    async def _plan(
        self, prompt: str, context: dict[str, Any] | None, cycle: LoopCycle
    ) -> Any:
        """PHASE 1 — planner with guidance folded into context."""
        if self._planner is None:
            raise RuntimeError("planner not wired")
        merged = dict(context or {})
        guidance = await self._guidance()
        if guidance:
            merged["synthesis_guidance"] = guidance
            # add_spec_context only renders known keys; carry the guidance
            # in the prompt itself so it survives the translation stage.
            merged["prompt"] = (
                f"{prompt}\n\nPrior-cycle guidance:\n{guidance}"
            )
        planner_output, _narrative = await self._planner.generate_spec(
            session_id=cycle.cycle_id,
            prompt=merged.get("prompt") or prompt,
            context=merged,
        )
        spec = getattr(planner_output, "spec", planner_output)
        cycle.spec = spec
        return spec

    async def _execute(self, cycle_id: str, spec: Any) -> Any:
        """PHASE 2 — executor (fail-open inside the engine)."""
        if self._executor is None:
            return None
        record, _narrative = await self._executor.execute_spec(
            session_id=cycle_id, spec=spec
        )
        return record

    async def _regulate(
        self,
        cycle_id: str,
        spec: Any,
        record: Any,
        success: bool,
        cycle: LoopCycle,
    ) -> None:
        """PHASE 3 — manager hooks (donor on_task_start/complete + on_error)."""
        if self._manager is None:
            return
        task_id = f"task-{cycle_id}"
        try:
            await self._manager.on_task_start(
                session_id=cycle_id,
                task_id=task_id,
                spec_id=str(getattr(spec, "id", "")),
            )
            for step in tuple(getattr(record, "steps", ()) or ()):
                feedback, _nid = await self._manager.on_error(
                    session_id=cycle_id,
                    category="test_result",
                    description=f"Phase {getattr(step, 'action', '')} completed",
                )
                if feedback is not None:
                    cycle.manager_feedback = asdict(feedback)
            await self._manager.on_task_complete(
                session_id=cycle_id,
                task_id=task_id,
                success=success,
                tokens_used=0,
                tools_used=0,
                elapsed_seconds=getattr(record, "total_duration_seconds", 0.0) or 0.0,
            )
        except Exception:  # noqa: BLE001
            logger.exception("self_improve.loop: manager regulation failed")

    async def _synthesize_phase(
        self, cycle_id: str, spec: Any, record: Any, cycle: LoopCycle
    ) -> None:
        """PHASE 4 — reflection → synthesis → experience memory."""
        feedback = {
            "what_happened": (
                f"Execution finished with status="
                f"{getattr(record, 'status', 'unknown')}"
                + (
                    f" (error: {getattr(record, 'error_summary', '')})"
                    if getattr(record, "error_summary", "")
                    else ""
                )
            ),
            "tests_passed": sum(
                1
                for t in tuple(getattr(record, "test_results", ()) or ())
                if str(getattr(t, "status", "")) == "passed"
            ),
            "tests_total": len(tuple(getattr(record, "test_results", ()) or ())),
        }
        spec_dict = {
            "id": str(getattr(spec, "id", "")),
            "description": str(getattr(spec, "description", "")),
            "expected_outcome": " ".join(
                getattr(spec, "requirements", ()) or ()
            ),
        }

        # Reflection (donor: run_reflection → synthesis consumed the session)
        if self._reflection is not None:
            try:
                await self._reflection.reflect_on_turn(
                    session_id=cycle_id,
                    turn_outcome=feedback,
                    focus=f"Execution: {spec_dict['description']}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("self_improve.loop: reflection failed")

        # Synthesis (thesis + antithesis)
        result: Any = None
        if self._synthesis is not None:
            try:
                result, _nid = await self._synthesis.synthesize(
                    session_id=cycle_id,
                    spec=spec_dict,
                    execution_feedback=feedback,
                )
                cycle.syntheses.append(result)
            except Exception:  # noqa: BLE001
                logger.exception("self_improve.loop: synthesis failed")

        # Experience memory (donor: store_from_synthesis for actionable)
        if self._experience is not None and result is not None:
            try:
                if getattr(result, "is_actionable", True):
                    exp, _nid = await self._experience.record(
                        session_id=cycle_id,
                        synthesis=asdict(result),
                        context=_CONTEXT,
                    )
                    cycle.experience_stored.append(str(getattr(exp, "id", "")))
            except Exception:  # noqa: BLE001
                logger.exception("self_improve.loop: experience.record failed")

    async def _feed_substrate(
        self,
        cycle_id: str,
        spec: Any,
        record: Any,
        success: bool,
        cycle: LoopCycle,
    ) -> None:
        """PHASE 5 — kernel learning substrate (donor's dead write path)."""
        if self._learning is None:
            return
        tests = tuple(getattr(record, "test_results", ()) or ())
        passed = sum(1 for t in tests if str(getattr(t, "status", "")) == "passed")
        artifacts = tuple(getattr(record, "artifacts", ()) or ())
        try:
            lr = await self._learning.on_session_completed(
                session_id=cycle_id,
                task=str(getattr(spec, "description", "") or cycle_id),
                spec=str(getattr(spec, "id", "")),
                model_used=self._model_used,
                success=success,
                tests_passed=passed,
                tests_total=len(tests),
                wall_time_seconds=getattr(record, "total_duration_seconds", 0.0) or 0.0,
                output_files=[str(getattr(a, "path", "")) for a in artifacts],
            )
            cycle.learning_record_id = str(getattr(lr, "session_id", ""))
        except Exception:  # noqa: BLE001
            logger.exception("self_improve.loop: substrate feed (completed) failed")

    async def _feed_substrate_failed(
        self, cycle_id: str, spec: Any, cycle: LoopCycle
    ) -> None:
        """Feed the substrate on a failed cycle (honest record)."""
        if self._learning is None:
            return
        try:
            lr = await self._learning.on_session_failed(
                session_id=cycle_id,
                task=str(getattr(spec, "description", "") or cycle_id),
                spec=str(getattr(spec, "id", "")),
                model_used=self._model_used,
                error=str(cycle.error)[:300],
                wall_time_seconds=cycle.duration_seconds or 0.0,
            )
            cycle.learning_record_id = str(getattr(lr, "session_id", ""))
        except Exception:  # noqa: BLE001
            logger.exception("self_improve.loop: substrate feed (failed) failed")


__all__ = ["SelfImprovementLoop", "LoopCycle"]
