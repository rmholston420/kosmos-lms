"""plugins.tektos.planner.pipeline — the donor ``Planner`` orchestrator
(ADR-141 T4).

Verbatim port of ``tektos-ultima/src/tektos/agents/planner/orchestrator.py``
(152 LOC, pure heuristic — no LLM calls). Composes the five leaf stages
already ported at Stage 8.4 (ADR-106) into the donor's exact pipeline:

1. Language Game Classifier → identify the domain
2. Disambiguator → catch ambiguous terms across domains
3. Translator → convert NL → Proper Technical English
4. Template Selector → choose architecture template
5. Spec Generator → produce structured build spec

The kernel's ``TektosSpecPlanner`` (spec_planner.py) is a *different*
surface — async, session-bound, persisting via ``write_narrative``,
fail-open. This class is the donor's synchronous, stateless pipeline,
ported for wire fidelity of ``POST /api/planner/plan`` (donor
``main.py:3195``) which returns ``PlannerOutput.model_dump()`` verbatim.

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

from typing import Any

from .disambiguator import (
    find_ambiguities,
    find_vague_terms,
    generate_clarifying_questions,
    resolve_ambiguities,
)
from .language_game import classify_language_game, get_language_game_description
from .spec_generator import generate_spec
from .spec_models import AmbiguityResolution, PlannerOutput
from .template_selector import choose_best_template
from .translator import add_spec_context, translate_to_technical_english


class Planner:
    """The Planner/Thinker (S4) orchestrator.

    Processes natural language through the full pipeline:
    Language Game → Disambiguator → Translator → Template Selector →
    Spec Generator.

    Attributes:
        context_budget: Maximum context budget in tokens (default: 128000).
        max_clarifying_questions: Maximum number of questions to ask per prompt.
    """

    def __init__(
        self,
        context_budget: int = 128000,
        max_clarifying_questions: int = 3,
    ) -> None:
        self.context_budget = context_budget
        self.max_clarifying_questions = max_clarifying_questions

    def plan(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
        user_preference: str | None = None,
        synthesis_guidance: str = "",
    ) -> PlannerOutput:
        """Run the full planning pipeline on a natural language prompt.

        Verbatim port of donor ``Planner.plan`` — same stage order, same
        filters, same ``PlannerOutput`` construction.

        Args:
            prompt: The user's natural language prompt.
            context: Optional context dict (language_game, tech_stack,
                constraints, previous_conversation, ...).
            user_preference: Optional user preference for architecture template.
            synthesis_guidance: Lessons from prior execution cycles.

        Returns:
            PlannerOutput containing the structured spec and metadata.
        """
        # Step 1: Classify language game
        language_game = classify_language_game(prompt)

        # Step 2: Find ambiguities
        ambiguities = find_ambiguities(prompt, language_game)
        vague_terms = find_vague_terms(prompt)
        all_ambiguities = ambiguities + vague_terms

        # Step 3: Resolve ambiguities
        resolved, resolutions = resolve_ambiguities(
            all_ambiguities,
            user_input=context.get("previous_conversation") if context else None,
        )

        # Step 4: Generate clarifying questions (for unresolved critical ambiguities)
        unresolved_critical = [
            amb
            for amb, res in zip(resolved, resolutions)
            if res == AmbiguityResolution.ASK_USER and amb.criticality == "critical"
        ]
        clarifying_questions = generate_clarifying_questions(tuple(unresolved_critical))

        # Limit clarifying questions
        clarifying_questions = clarifying_questions[: self.max_clarifying_questions]

        # Step 5: Translate to Proper Technical English
        context_for_translation = context or {}
        context_for_translation["language_game"] = get_language_game_description(
            language_game
        )
        translated = translate_to_technical_english(prompt)
        translated = add_spec_context(translated, context_for_translation)

        # Step 6: Select architecture template
        requirements = tuple(self._extract_requirements(translated))
        architecture = choose_best_template(
            requirements,
            user_preference=user_preference,
        )

        # Step 7: Generate build spec
        spec = generate_spec(
            original_prompt=prompt,
            translated_prompt=translated,
            language_game=language_game,
            architecture=architecture,
            requirements=requirements,
            constraints=context.get("constraints") if context else None,
            tech_stack=context.get("tech_stack") if context else None,
            test_strategy=(
                context.get("test_strategy", "spec-driven") if context else "spec-driven"
            ),
            notes=context.get("notes") if context else None,
            context_budget_warning=(
                f"Spec uses {len(translated)} chars. Context budget: {self.context_budget}."
                if len(translated) > self.context_budget * 0.8
                else None
            ),
            synthesis_guidance=synthesis_guidance,
        )

        return PlannerOutput(
            spec=spec,
            synthesis_guidance=synthesis_guidance,
            language_game_detected=language_game,
            ambiguities_found=all_ambiguities,
            ambiguities_resolved=list(zip(resolved, resolutions)),
            clarifying_questions_asked=clarifying_questions,
            templates_presented=[architecture.selected],
            context_budget_used=len(translated),
            context_budget_total=self.context_budget,
        )

    def _extract_requirements(self, text: str) -> list[str]:
        """Extract requirements from translated text.

        Verbatim port of donor ``Planner._extract_requirements`` — split on
        newlines, drop empty lines. The Spec Generator does more
        sophisticated extraction if needed.
        """
        lines = text.split("\n")
        return [line.strip() for line in lines if line.strip()]


__all__ = ["Planner"]
