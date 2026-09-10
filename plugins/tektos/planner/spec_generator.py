"""plugins.tektos.planner.spec_generator — build spec generator.

Rewritten from donor ``tektos-ultima/src/tektos/agents/planner/spec_generator.py``
per ADR-106 D2. Rule-based extraction (``_extract_requirements``,
``_extract_constraints``, ``_default_phases``) preserved verbatim; synthesis-guidance
weaving preserved verbatim.

Adjusted to build the frozen slotted ``BuildSpec`` dataclass from
``plugins.tektos.planner.spec_models``. Phase inputs may still arrive as dicts
(caller convenience); we normalise to ``SpecPhase`` before construction.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from plugins.tektos.planner.spec_models import (
    ArchitectureChoice,
    BuildSpec,
    LanguageGame,
    SpecPhase,
)


def generate_spec(
    original_prompt: str,
    translated_prompt: str,
    language_game: LanguageGame,
    architecture: ArchitectureChoice,
    requirements: Sequence[str] | None = None,
    constraints: Sequence[str] | None = None,
    tech_stack: Sequence[str] | None = None,
    test_strategy: str = "spec-driven",
    phases: Sequence[Mapping[str, Any]] | None = None,
    notes: Sequence[str] | None = None,
    context_budget_warning: str | None = None,
    description: str | None = None,
    synthesis_guidance: str = "",
) -> BuildSpec:
    """Generate a structured ``BuildSpec`` from pipeline output.

    Verbatim port of donor ``generate_spec`` behaviour — same defaulting,
    same requirement extraction, same synthesis-guidance weaving.
    """
    if not description:
        description = translated_prompt.split("\n")[0].strip()
        if len(description) > 200:
            description = description[:197] + "..."

    req_list: list[str] = list(requirements) if requirements else _extract_requirements(
        translated_prompt
    )
    con_list: list[str] = list(constraints) if constraints else _extract_constraints(
        translated_prompt
    )
    ph_list: list[Mapping[str, Any]] = list(phases) if phases else _default_phases(req_list)

    spec_phases: list[SpecPhase] = []
    for i, phase_data in enumerate(ph_list, 1):
        spec_phases.append(
            SpecPhase(
                id=str(phase_data.get("id", f"phase-{i}")),
                description=str(phase_data.get("description", "")),
                deliverables=tuple(phase_data.get("deliverables") or ()),
                acceptance_criteria=tuple(phase_data.get("acceptance_criteria") or ()),
                estimated_effort=str(phase_data.get("estimated_effort", "unknown")),
            )
        )

    spec_notes = list(notes) if notes else []
    if synthesis_guidance:
        spec_notes.append(
            f"[SELF-IMPROVEMENT GUIDANCE — Past execution lessons]\n{synthesis_guidance}"
        )
        for raw in synthesis_guidance.split("\n"):
            line = raw.strip()
            if not line or line.startswith("["):
                continue
            if line.startswith("Context:") or line.startswith("Tags:"):
                continue
            actionable = line
            for prefix in ("⚑ HIGH:", "⚠ URGENT:", "⚑ HIGH", "⚠ URGENT", "⚑ ", "⚠ ", "- "):
                if actionable.startswith(prefix):
                    actionable = actionable[len(prefix):].strip()
                    break
            if actionable and actionable not in req_list:
                req_list.append(actionable)

    return BuildSpec(
        original_prompt=original_prompt,
        translated_prompt=translated_prompt,
        language_game=language_game,
        description=description,
        requirements=tuple(req_list),
        constraints=tuple(con_list),
        tech_stack=tuple(tech_stack or ()),
        test_strategy=test_strategy,
        architecture=architecture,
        phases=tuple(spec_phases),
        context_budget_warning=context_budget_warning,
        notes=tuple(spec_notes),
        synthesis_guidance=synthesis_guidance,
    )


def _extract_requirements(text: str) -> list[str]:
    """Extract requirements from a translated prompt — verbatim from donor."""
    requirements: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            requirements.append(line.lstrip("0123456789. "))
        elif " with " in line:
            parts = line.split(" with ")
            if len(parts) > 1:
                requirements.append(parts[-1].strip())
        elif " that " in line:
            parts = line.split(" that ")
            if len(parts) > 1:
                requirements.append(parts[-1].strip())

    if not requirements and text.strip():
        requirements = [text.strip()]

    return requirements


def _extract_constraints(text: str) -> list[str]:
    """Extract constraints from a translated prompt — verbatim from donor."""
    constraints: list[str] = []
    text_lower = text.lower()

    for pattern in ("must not", "must", "only", "no ", "never"):
        if pattern in text_lower:
            idx = text_lower.index(pattern)
            end = min(idx + 100, len(text))
            constraint = text[idx:end].strip().rstrip(".")
            constraints.append(constraint)

    return constraints


def _default_phases(requirements: list[str]) -> list[dict[str, Any]]:
    """Generate default phased deliverables — verbatim from donor."""
    if not requirements:
        return [
            {
                "id": "phase-1",
                "description": "Minimal viable implementation",
                "deliverables": [],
                "estimated_effort": "S",
            },
        ]

    mvp_count = min(3, len(requirements))
    mvp_reqs = requirements[:mvp_count]
    improvement_reqs = requirements[mvp_count:] if mvp_count < len(requirements) else []
    polish_needed = len(requirements) > 2

    phases: list[dict[str, Any]] = [
        {
            "id": "phase-1",
            "description": "Minimal viable implementation",
            "deliverables": mvp_reqs,
            "acceptance_criteria": [
                f"Each of the {mvp_count} requirements is implemented and tested",
                "All acceptance criteria are met",
            ],
            "estimated_effort": "S" if mvp_count <= 2 else "M",
        },
    ]

    if improvement_reqs:
        phases.append(
            {
                "id": "phase-2",
                "description": "Features that improve the slice",
                "deliverables": improvement_reqs,
                "acceptance_criteria": [
                    f"Each of the {len(improvement_reqs)} improvement requirements is implemented and tested",
                ],
                "estimated_effort": "M" if len(improvement_reqs) <= 3 else "L",
            }
        )

    if polish_needed:
        phases.append(
            {
                "id": "phase-3",
                "description": "Polish and robustness",
                "deliverables": ["Error handling", "Input validation", "Documentation"],
                "acceptance_criteria": [
                    "All error paths are handled",
                    "Input validation is comprehensive",
                    "Documentation covers all public APIs",
                ],
                "estimated_effort": "S",
            }
        )

    return phases


__all__ = ["generate_spec"]
