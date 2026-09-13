"""plugins.tektos.manager.guardrails — non-negotiable manager constraints.

Preserved verbatim from ``tektos-ultima/src/tektos/agents/manager/guardrails.py``
per ADR-108 D2. This is policy vocabulary — NOT detection code. The manager
delegates guardrail scanning to :class:`ports.immune.ImmunePort` (ADR-079);
donor's inline regex from ``_check_guardrails`` is kept only as a fallback
keyword scan when ``ImmunePort`` is unbound (see :mod:`.engine` per ADR-108
R3 + D9).

Guardrails are NOT suggestions. They are the system's immune system.
"""

from __future__ import annotations

from enum import Enum


class GuardrailLevel(str, Enum):
    """Guardrail enforcement levels."""

    HARD = "hard"  # Never bypassed — system integrity
    MEDIUM = "medium"  # Bypassable by user with explicit confirmation
    SOFT = "soft"  # Warning only — agent can override


class Guardrail(str, Enum):
    """Defined guardrails for the system.

    Every guardrail is non-negotiable. The Manager enforces them. The
    Coding Agent (S1) must not violate them. The Planner (S4) must not
    produce specs that violate them.
    """

    LLM_MUST_NOT_COMPUTE = "llm_must_not_compute"
    """LLMs are translators only (NL → logic). Computation belongs to tools."""

    VENDOR_BEFORE_BUILD = "vendor_before_build"
    """Reuse existing code before building custom. Tracked via PORTING-LEDGER."""

    NO_HARD_CODED_SECRETS = "no_hardcoded_secrets"
    """Never embed credentials, API keys, tokens, or connection strings."""

    CONTEXT_BUDGET_ADHERENCE = "context_budget_adherence"
    """Specs must not exceed context budget (default 128K tokens)."""

    TEST_BEFORE_MERGE = "test_before_merge"
    """All code changes must pass tests before integration."""

    SANDBOX_ISOLATION = "sandbox_isolation"
    """Agent tasks run in isolated sandboxes. No cross-session file access."""

    REDACTION_POLICY = "redaction_policy"
    """All sensitive data must be redacted from logs, outputs, and Trail."""

    ALGORITHMIC_FAIRNESS = "algorithmic_fairness"
    """No biased or discriminatory patterns in agent behavior."""

    PRIVACY_BY_DESIGN = "privacy_by_design"
    """User data is private by default. No data shared without explicit consent."""

    BACKUP_BEFORE_MODIFY = "backup_before_modify"
    """Always backup before modifying critical files or configs."""

    # New guardrails for v2.0
    RE_DIRECTION_OVER_PUNISHMENT = "re_direction_over_punishment"
    """Manager feedback uses re-direction, not rejection or punishment."""

    WHOLE_SYSTEM_BEFORE_PART = "whole_system_before_part"
    """Always understand the whole before modifying a part."""

    SELF_IMPROVEMENT_NON_DEGRADING = "self_improvement_non_degrading"
    """Self-modifications must not degrade performance (Gödel Agent principle)."""


# Guardrail metadata (donor ``GUARDRAIL_RULES`` — preserved verbatim, per
# ADR-108 D2). Members without an entry (ALGORITHMIC_FAIRNESS, PRIVACY_BY_DESIGN,
# BACKUP_BEFORE_MODIFY) mirror donor behaviour.
GUARDRAIL_RULES: dict[Guardrail, dict[str, str | GuardrailLevel]] = {
    Guardrail.LLM_MUST_NOT_COMPUTE: {
        "description": "An LLM must never perform computation — the LLM is a translator only (NL → logic). "
        "LLM calls are expensive, slow, and nondeterministic. Tools are deterministic, "
        "fast, free, and precise.",
        "level": GuardrailLevel.HARD,
        "enforcement": "Manager checks every LLM call. If a tool could handle it, "
        "the Manager redirects the LLM to the tool.",
    },
    Guardrail.VENDOR_BEFORE_BUILD: {
        "description": "Reuse well-designed existing tools and frameworks before writing "
        "custom translation logic.",
        "level": GuardrailLevel.MEDIUM,
        "enforcement": "PORTING-LEDGER.md tracks vendor-before-build decisions. "
        "Manager checks if a similar tool exists before allowing custom code.",
    },
    Guardrail.NO_HARD_CODED_SECRETS: {
        "description": "Never embed credentials, API keys, tokens, or connection strings "
        "in source code, configs, or logs.",
        "level": GuardrailLevel.HARD,
        "enforcement": "Static analysis via regex checks all new code for secret patterns. "
        "Manager rejects any commit with embedded secrets.",
    },
    Guardrail.CONTEXT_BUDGET_ADHERENCE: {
        "description": "Specs and prompts must not exceed the context budget (default 128K tokens). "
        "The Planner must produce terse, unambiguous specs.",
        "level": GuardrailLevel.SOFT,
        "enforcement": "Planner tracks context budget. Warning if >80% used. "
        "Hard limit at 100% triggers truncation.",
    },
    Guardrail.TEST_BEFORE_MERGE: {
        "description": "All code changes must pass tests before integration. "
        "Tests that never fail are invalid.",
        "level": GuardrailLevel.HARD,
        "enforcement": "CI/CD pipeline enforces test gate. Manager checks test "
        "results before allowing merge.",
    },
    Guardrail.SANDBOX_ISOLATION: {
        "description": "Agent tasks run in isolated sandboxes. No cross-session "
        "file access or data leakage.",
        "level": GuardrailLevel.HARD,
        "enforcement": "Sandbox provider enforces filesystem, network, and memory "
        "isolation per task.",
    },
    Guardrail.REDACTION_POLICY: {
        "description": "All sensitive data must be redacted from logs, outputs, and Trail.",
        "level": GuardrailLevel.HARD,
        "enforcement": "Output filter runs on all manager and agent outputs. "
        "Patterns: API keys, tokens, passwords, connection strings.",
    },
    Guardrail.RE_DIRECTION_OVER_PUNISHMENT: {
        "description": "Manager feedback uses re-direction (guidance), not rejection "
        "or punishment. Punishment creates defensive behavior and resentment.",
        "level": GuardrailLevel.HARD,
        "enforcement": "Manager feedback language follows: 'Here's what happened. "
        "Here's what should happen. Here's why. Try this.'",
    },
    Guardrail.WHOLE_SYSTEM_BEFORE_PART: {
        "description": "Always understand the whole system before modifying a part. "
        "Changes must be evaluated for systemic impact.",
        "level": GuardrailLevel.MEDIUM,
        "enforcement": "Manager requires systemic impact assessment before "
        "allowing architectural changes.",
    },
    Guardrail.SELF_IMPROVEMENT_NON_DEGRADING: {
        "description": "Self-modifications must not degrade performance. "
        "Every change must pass empirical tests (Gödel Agent principle).",
        "level": GuardrailLevel.HARD,
        "enforcement": "Manager compares metrics before and after any "
        "self-modification. If degraded, rollback automatically.",
    },
}


__all__ = ["GUARDRAIL_RULES", "Guardrail", "GuardrailLevel"]
