"""Kosmos-native ``TektosSpecPlanner`` (Stage 8.4 · ADR-106).

Composes five pipeline stages — language-game classification, disambiguation,
translation to Proper Technical English, architecture-template selection, and
spec generation — into one ``PlannerOutput``. Persists via
``RelationalMemoryPort.write_narrative`` and publishes
``tektos.planner.spec_generated`` on the event bus. Mirrors the pattern
established by ``ExperienceReplay`` (ADR-105): frozen dataclasses, fail-open
port calls, and a ring-buffer fallback when persistence is unbound.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

from ports.event_envelope import EventEnvelope

from . import (
    TEKTOS_SPEC_PLANNER_DEFAULT_CONFIDENCE,
    TEKTOS_SPEC_PLANNER_PREDICATE,
    TEKTOS_SPEC_PLANNER_PROVENANCE,
)
from .disambiguator import (
    find_ambiguities,
    find_vague_terms,
    generate_clarifying_questions,
    resolve_ambiguities,
)
from .language_game import classify_language_game
from .spec_generator import generate_spec
from .spec_models import (
    ArchitectureChoice,
    BuildSpec,
    LanguageGame,
    PlannerOutput,
)
from .template_selector import choose_best_template
from .translator import add_spec_context, translate_to_technical_english

log = logging.getLogger(__name__)


@runtime_checkable
class _RelationalMemoryLike(Protocol):
    async def write_narrative(
        self,
        *,
        session_id: str,
        agent_id: str | None,
        title: str,
        body: str,
        tags: tuple[str, ...],
        embedding: tuple[float, ...] | None,
        confidence: float,
        provenance: str,
    ) -> str: ...


@runtime_checkable
class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


def _spec_to_body(spec: BuildSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "version": spec.version,
        "created_at": spec.created_at,
        "original_prompt": spec.original_prompt,
        "translated_prompt": spec.translated_prompt,
        "language_game": spec.language_game.value,
        "description": spec.description,
        "requirements": list(spec.requirements),
        "constraints": list(spec.constraints),
        "tech_stack": list(spec.tech_stack),
        "test_strategy": spec.test_strategy,
        "architecture": {
            "selected": spec.architecture.selected,
            "reason": spec.architecture.reason,
            "is_user_choice": spec.architecture.is_user_choice,
        },
        "phases": [
            {
                "id": phase.id,
                "description": phase.description,
                "deliverables": list(phase.deliverables),
                "acceptance_criteria": list(phase.acceptance_criteria),
                "estimated_effort": phase.estimated_effort,
            }
            for phase in spec.phases
        ],
        "context_budget_warning": spec.context_budget_warning,
        "notes": list(spec.notes),
        "synthesis_guidance": spec.synthesis_guidance,
    }


class TektosSpecPlanner:
    """Kosmos Tektos spec-planner engine (ADR-106 D1)."""

    def __init__(
        self,
        *,
        relational_memory: _RelationalMemoryLike | None = None,
        event_bus: _EventBusLike | None = None,
        max_records: int = 100,
    ) -> None:
        self._relational_memory = relational_memory
        self._event_bus = event_bus
        self._buffer: deque[PlannerOutput] = deque(maxlen=max_records)

    @property
    def is_persistence_bound(self) -> bool:
        return self._relational_memory is not None

    # --- generation path ------------------------------------------------

    async def generate_spec(
        self,
        *,
        session_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
        user_preference: str | None = None,
        confidence: float | None = None,
    ) -> tuple[PlannerOutput, str | None]:
        """Run the full five-stage planning pipeline.

        Never raises (fail-open). Returns ``(planner_output, narrative_id)`` —
        ``narrative_id`` is ``None`` when persistence is unbound or the port
        call fails.
        """
        # Stage 1 — language-game detection.
        try:
            language_game = classify_language_game(prompt)
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.planner: classify_language_game failed; defaulting to GENERAL"
            )
            language_game = LanguageGame.GENERAL

        # Stage 2 — disambiguation.
        resolved: tuple = ()
        resolutions: tuple = ()
        clarifying_questions: tuple = ()
        try:
            domain_ambiguities = find_ambiguities(prompt, language_game)
            vague_ambiguities = find_vague_terms(prompt)
            all_ambiguities = tuple(domain_ambiguities) + tuple(vague_ambiguities)
            resolved, resolutions = resolve_ambiguities(
                all_ambiguities, user_input=prompt if context else None
            )
            clarifying_questions = generate_clarifying_questions(resolved)
        except Exception:  # noqa: BLE001
            log.exception("tektos.planner: disambiguation failed; continuing with empty set")

        # Stage 3 — translation.
        try:
            translated = translate_to_technical_english(prompt)
            translated = add_spec_context(translated, context)
        except Exception:  # noqa: BLE001
            log.exception("tektos.planner: translation failed; using original prompt")
            translated = prompt

        # Stage 4 — architecture template selection.
        requirements_tuple = tuple(line for line in prompt.split("\n") if line.strip())
        try:
            architecture = choose_best_template(
                requirements_tuple, user_preference=user_preference
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "tektos.planner: choose_best_template failed; defaulting to vertical_slice"
            )
            architecture = ArchitectureChoice(
                selected="vertical_slice",
                reason="Default fallback (template selection error)",
                is_user_choice=False,
            )

        # Stage 5 — spec generation.
        try:
            spec = generate_spec(
                original_prompt=prompt,
                translated_prompt=translated,
                language_game=language_game,
                architecture=architecture,
            )
        except Exception:  # noqa: BLE001
            log.exception("tektos.planner: generate_spec failed; producing minimal spec")
            spec = BuildSpec(
                original_prompt=prompt,
                translated_prompt=translated,
                description=prompt[:200],
                requirements=(),
                architecture=architecture,
                phases=(),
                language_game=language_game,
                notes=("Degraded spec — Stage 5 generation failed",),
            )

        # Zip resolved ambiguities + resolutions into PlannerOutput shape.
        ambiguities_resolved_pairs = tuple(
            (amb, res) for amb, res in zip(resolved, resolutions)
        )

        output = PlannerOutput(
            spec=spec,
            language_game_detected=language_game,
            ambiguities_found=tuple(resolved),
            ambiguities_resolved=ambiguities_resolved_pairs,
            clarifying_questions_asked=tuple(clarifying_questions),
        )
        self._buffer.append(output)

        eff_conf = (
            float(confidence)
            if confidence is not None
            else TEKTOS_SPEC_PLANNER_DEFAULT_CONFIDENCE
        )

        narrative_id: str | None = None
        if self._relational_memory is not None:
            try:
                narrative_id = await self._relational_memory.write_narrative(
                    session_id=session_id,
                    agent_id=TEKTOS_SPEC_PLANNER_PROVENANCE,
                    title=f"{TEKTOS_SPEC_PLANNER_PREDICATE}:{spec.id}",
                    body=json.dumps(
                        {
                            "spec_id": spec.id,
                            "spec": _spec_to_body(spec),
                            "resolutions": [r.value for _, r in ambiguities_resolved_pairs],
                        },
                        default=str,
                    ),
                    tags=(
                        TEKTOS_SPEC_PLANNER_PROVENANCE,
                        language_game.value,
                        session_id,
                    ),
                    embedding=None,
                    confidence=eff_conf,
                    provenance=TEKTOS_SPEC_PLANNER_PROVENANCE,
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.planner: write_narrative failed; kept in memory-only "
                    "buffer (ADR-106 D9 fail-open)"
                )
                narrative_id = None

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    EventEnvelope(
                        event_type=TEKTOS_SPEC_PLANNER_PREDICATE,
                        producer_plugin=TEKTOS_SPEC_PLANNER_PROVENANCE,
                        payload={
                            "session_id": session_id,
                            "spec_id": spec.id,
                            "language_game": language_game.value,
                            "narrative_id": narrative_id,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "tektos.planner: EventBus publish failed; continuing (fail-open)"
                )

        return output, narrative_id

    def list_recent(self, limit: int = 10) -> tuple[PlannerOutput, ...]:
        """Return most-recent buffered planner outputs."""
        if limit <= 0:
            return ()
        return tuple(list(self._buffer)[-limit:])


__all__ = ["TektosSpecPlanner"]
