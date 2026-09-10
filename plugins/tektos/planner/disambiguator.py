"""plugins.tektos.planner.disambiguator — identifies ambiguous terms.

Rewritten from donor
``tektos-ultima/src/tektos/agents/planner/disambiguator.py`` per ADR-106 D2.
Rule-based analytic core preserved verbatim (``_AMBIGUITY_DICTIONARY`` +
``_VAGUE_TERMS`` maps identical; criticality-heuristic identical). The only
change is imports from ``plugins.tektos.planner.spec_models`` and the return
type moves from ``list`` to ``tuple`` at the outer boundary (immutability
matches frozen dataclass surface).

"Meaning is use" — Wittgenstein. The Disambiguator finds the context, then
determines meaning.
"""

from __future__ import annotations

from plugins.tektos.planner.spec_models import (
    Ambiguity,
    AmbiguityResolution,
    ClarifyingQuestion,
    LanguageGame,
)

# Domain-specific ambiguity dictionary — verbatim from donor.
_AMBIGUITY_DICTIONARY: dict[str, dict[LanguageGame, str]] = {
    "function": {
        LanguageGame.SOFTWARE_ENGINEERING: "A named block of code that performs a specific task",
        LanguageGame.SYSTEMS_ARCHITECTURE: "The role or purpose of a system component within a larger architecture",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A natural law or principle; the way things work by nature (dharma as function)",
        LanguageGame.GENERAL: "A purpose or role",
    },
    "model": {
        LanguageGame.SOFTWARE_ENGINEERING: "A trained neural network that processes data",
        LanguageGame.SYSTEMS_ARCHITECTURE: "A mathematical or conceptual representation of a system",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A conceptual construct; all models are provisional (not ultimate truth)",
        LanguageGame.GENERAL: "A representation or pattern",
    },
    "test": {
        LanguageGame.SOFTWARE_ENGINEERING: "Automated verification that code behaves correctly",
        LanguageGame.SYSTEMS_ARCHITECTURE: "A stress condition applied to evaluate system behavior",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A practical experiment in understanding (direct experience, not theory)",
        LanguageGame.GENERAL: "An attempt to determine quality or correctness",
    },
    "agent": {
        LanguageGame.SOFTWARE_ENGINEERING: "A program that acts autonomously to achieve goals",
        LanguageGame.SYSTEMS_ARCHITECTURE: "An entity within a system that performs operations (S1 agent)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A being with free will and moral agency (karma-driven)",
        LanguageGame.GENERAL: "A person or entity that acts",
    },
    "process": {
        LanguageGame.SOFTWARE_ENGINEERING: "An OS-level execution unit (thread, container, process)",
        LanguageGame.SYSTEMS_ARCHITECTURE: "A workflow or transformation sequence (PRINST: what the system does)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A sequence of causal events (dependent origination)",
        LanguageGame.GENERAL: "A series of actions",
    },
    "event": {
        LanguageGame.SOFTWARE_ENGINEERING: "A discrete occurrence in a system (API call, database write)",
        LanguageGame.SYSTEMS_ARCHITECTURE: "A recorded fact in the Trail (S2 event stream)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A moment of arising in the flow of phenomena (dharmas)",
        LanguageGame.GENERAL: "Something that happens",
    },
    "pattern": {
        LanguageGame.SOFTWARE_ENGINEERING: "A reusable solution to a common problem in code (design pattern)",
        LanguageGame.SYSTEMS_ARCHITECTURE: "A recurring structural or behavioral arrangement in a system (archetype)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A repeating form in nature that reveals underlying unity (sacred geometry)",
        LanguageGame.GENERAL: "A regular or repeated arrangement",
    },
    "structure": {
        LanguageGame.SOFTWARE_ENGINEERING: "The organization of code, classes, and modules",
        LanguageGame.SYSTEMS_ARCHITECTURE: "The arrangement of components within a system (PRINST: Structure third)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "The arrangement of phenomena; all structures are empty of inherent existence",
        LanguageGame.GENERAL: "The arrangement of parts into a whole",
    },
    "system": {
        LanguageGame.SOFTWARE_ENGINEERING: "A software system or application",
        LanguageGame.SYSTEMS_ARCHITECTURE: "A cybernetic unit within a larger organization (VSM S1-S5)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "The interconnected web of phenomena (dependent origination)",
        LanguageGame.GENERAL: "A group of interacting parts",
    },
    "state": {
        LanguageGame.SOFTWARE_ENGINEERING: "The condition of a program at a specific moment (variables, memory)",
        LanguageGame.SYSTEMS_ARCHITECTURE: "The current configuration of a system (homeostatic setpoint or deviation)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "A transient condition in the flow of phenomena (impermanent)",
        LanguageGame.GENERAL: "The condition of something at a specific time",
    },
    "control": {
        LanguageGame.SOFTWARE_ENGINEERING: "Management of program flow or system resources",
        LanguageGame.SYSTEMS_ARCHITECTURE: "VSM S3: regulatory feedback that maintains homeostasis (variety regulation)",
        LanguageGame.BUDDHIST_PHILOSOPHY: "Mindfulness and ethical restraint (sila as the foundation of samadhi)",
        LanguageGame.GENERAL: "The power to influence or direct behavior",
    },
    "intelligence": {
        LanguageGame.SOFTWARE_ENGINEERING: "Pattern recognition in machine learning models",
        LanguageGame.SYSTEMS_ARCHITECTURE: "VSM S4: horizon scanning and environmental adaptation",
        LanguageGame.BUDDHIST_PHILOSOPHY: "Prajna: insight into the true nature of reality (not mere knowledge)",
        LanguageGame.GENERAL: "The ability to acquire and apply knowledge",
    },
}

# Ambiguous terms that are always vague regardless of domain — verbatim from donor.
_VAGUE_TERMS: dict[str, str] = {
    "fast": "low-latency (specify: <100ms, <1s, or real-time)",
    "slow": "high-latency (specify: >1s, >5s, or real-time is NOT acceptable)",
    "good": "meets acceptance criteria (specify: test pass rate, performance, security)",
    "bad": "fails acceptance criteria (specify: test failure, performance degradation, security issue)",
    "big": "large-scale (specify: number of records, data volume in GB/TB, users)",
    "small": "minimal/viable (specify: MVP scope, number of features, timebox)",
    "simple": "straightforward implementation (specify: number of components, lines of code)",
    "complex": "requires careful design (specify: number of dependencies, concurrency, state)",
    "secure": "meets security standards (specify: authentication, authorization, encryption)",
    "reliable": "meets uptime/accuracy standards (specify: SLA, error rate)",
    "scalable": "handles increased load (specify: users, requests, data volume)",
    "efficient": "optimal resource usage (specify: CPU, memory, bandwidth, time)",
    "clean": "well-structured code (specify: linting rules, test coverage, documentation)",
}

_CRITICAL_SYSTEMS_TERMS = ("system", "control", "intelligence", "state")


def find_ambiguities(text: str, language_game: LanguageGame) -> tuple[Ambiguity, ...]:
    """Find ambiguous terms in text based on the detected language game.

    Verbatim port of donor ``find_ambiguities`` — same iteration order, same
    criticality heuristic (critical only when the term is one of the four
    architecture terms and the game is SYSTEMS_ARCHITECTURE).
    """
    ambiguities: list[Ambiguity] = []
    text_lower = text.lower()

    for term, domain_meanings in _AMBIGUITY_DICTIONARY.items():
        if term not in text_lower:
            continue
        primary_meaning = domain_meanings.get(
            language_game, domain_meanings[LanguageGame.GENERAL]
        )
        other_meanings = [
            meaning for g, meaning in domain_meanings.items() if g != language_game
        ]
        if len(other_meanings) == 0:
            continue
        all_meanings = tuple([primary_meaning, *other_meanings])
        criticality = "moderate"
        if (
            language_game == LanguageGame.SYSTEMS_ARCHITECTURE
            and term in _CRITICAL_SYSTEMS_TERMS
        ):
            criticality = "critical"
        ambiguities.append(
            Ambiguity(
                term=term,
                possible_meanings=all_meanings,
                criticality=criticality,  # type: ignore[arg-type]
                domain=language_game,
            )
        )

    return tuple(ambiguities)


def find_vague_terms(text: str) -> tuple[Ambiguity, ...]:
    """Find vague, unquantified terms in text.

    Verbatim port of donor ``find_vague_terms`` — iterates the ``_VAGUE_TERMS``
    dict in insertion order.
    """
    ambiguities: list[Ambiguity] = []
    text_lower = text.lower()

    for term, clarification in _VAGUE_TERMS.items():
        if term in text_lower:
            ambiguities.append(
                Ambiguity(
                    term=term,
                    possible_meanings=(clarification,),
                    criticality="moderate",
                )
            )

    return tuple(ambiguities)


def resolve_ambiguities(
    ambiguities: tuple[Ambiguity, ...],
    user_input: str | None = None,
) -> tuple[tuple[Ambiguity, ...], tuple[AmbiguityResolution, ...]]:
    """Resolve ambiguities by asking the user or making optimal choices.

    Verbatim port of donor ``resolve_ambiguities`` — critical ambiguities always
    ASK_USER; moderate/minor with context → OPTIMAL_CHOICE; otherwise ASK_USER.
    """
    resolved: list[Ambiguity] = []
    resolutions: list[AmbiguityResolution] = []

    for ambiguity in ambiguities:
        if ambiguity.criticality == "critical":
            resolved.append(ambiguity)
            resolutions.append(AmbiguityResolution.ASK_USER)
        elif user_input and ambiguity.domain:
            resolved.append(ambiguity)
            resolutions.append(AmbiguityResolution.OPTIMAL_CHOICE)
        else:
            resolved.append(ambiguity)
            resolutions.append(AmbiguityResolution.ASK_USER)

    return tuple(resolved), tuple(resolutions)


def generate_clarifying_questions(
    ambiguities: tuple[Ambiguity, ...],
) -> tuple[ClarifyingQuestion, ...]:
    """Generate clarifying questions for critical ambiguities."""
    questions: list[ClarifyingQuestion] = []

    for amb in ambiguities:
        if amb.criticality != "critical":
            continue
        question = ClarifyingQuestion(
            question=f"What does '{amb.term}' mean in your context?",
            options=amb.possible_meanings,
            default=amb.possible_meanings[0] if amb.possible_meanings else "Unknown",
            reason=f"The term '{amb.term}' has multiple meanings across domains.",
        )
        questions.append(question)

    return tuple(questions)


__all__ = [
    "find_ambiguities",
    "find_vague_terms",
    "generate_clarifying_questions",
    "resolve_ambiguities",
]
