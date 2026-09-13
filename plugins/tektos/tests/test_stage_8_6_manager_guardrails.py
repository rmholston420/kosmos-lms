"""Stage 8.6 · ADR-108 tests — guardrails vocabulary (verbatim donor port)."""

from __future__ import annotations

from plugins.tektos.manager import GUARDRAIL_RULES, Guardrail, GuardrailLevel


def test_guardrail_enum_has_all_13_members():
    # Donor parity: 10 v1 + 3 v2 = 13 members total.
    assert len(list(Guardrail)) == 13


def test_guardrail_level_has_three_tiers():
    assert {lvl.value for lvl in GuardrailLevel} == {"hard", "medium", "soft"}


def test_guardrail_rules_cover_ten_of_thirteen_members():
    # Donor ``GUARDRAIL_RULES`` intentionally omits ALGORITHMIC_FAIRNESS,
    # PRIVACY_BY_DESIGN, BACKUP_BEFORE_MODIFY — preserved verbatim.
    assert len(GUARDRAIL_RULES) == 10


def test_guardrail_rules_all_have_required_keys():
    for guardrail, meta in GUARDRAIL_RULES.items():
        assert "description" in meta, f"{guardrail} missing description"
        assert "level" in meta, f"{guardrail} missing level"
        assert "enforcement" in meta, f"{guardrail} missing enforcement"
        assert isinstance(meta["level"], GuardrailLevel)


def test_hard_guardrails_include_secrets_and_llm_compute():
    hard = {
        g for g, meta in GUARDRAIL_RULES.items() if meta["level"] == GuardrailLevel.HARD
    }
    assert Guardrail.NO_HARD_CODED_SECRETS in hard
    assert Guardrail.LLM_MUST_NOT_COMPUTE in hard
    assert Guardrail.SANDBOX_ISOLATION in hard
    assert Guardrail.REDACTION_POLICY in hard
    assert Guardrail.TEST_BEFORE_MERGE in hard
    assert Guardrail.RE_DIRECTION_OVER_PUNISHMENT in hard
    assert Guardrail.SELF_IMPROVEMENT_NON_DEGRADING in hard


def test_guardrail_string_values_are_stable_donor_slugs():
    # Locked slug parity — kernel/API contracts depend on these strings.
    assert Guardrail.NO_HARD_CODED_SECRETS.value == "no_hardcoded_secrets"
    assert Guardrail.LLM_MUST_NOT_COMPUTE.value == "llm_must_not_compute"
    assert Guardrail.SANDBOX_ISOLATION.value == "sandbox_isolation"
    assert Guardrail.REDACTION_POLICY.value == "redaction_policy"
    assert (
        Guardrail.RE_DIRECTION_OVER_PUNISHMENT.value == "re_direction_over_punishment"
    )
    assert (
        Guardrail.SELF_IMPROVEMENT_NON_DEGRADING.value
        == "self_improvement_non_degrading"
    )
