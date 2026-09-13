"""Stage 8.6 · ADR-108 contract tests — :class:`TektosManager` engine."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from plugins.tektos.manager import (
    TEKTOS_MANAGER_DEFAULT_CONFIDENCE,
    TEKTOS_MANAGER_EVENT_ARCHETYPE,
    TEKTOS_MANAGER_EVENT_GUARDRAIL,
    TEKTOS_MANAGER_PREDICATE,
    TEKTOS_MANAGER_PROVENANCE,
    ArchetypeTracker,
    Guardrail,
    ManagerFeedback,
    ManagerHealthReport,
    TektosManager,
)
from plugins.tektos.manager.engine import (
    _check_threshold,
    _fallback_guardrail_scan,
    classify_recovery,
)


# ── Test doubles ───────────────────────────────────────────────────────────


class _StubRMem:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write_narrative(self, **kwargs: Any) -> str:  # noqa: ANN401
        self.writes.append(kwargs)
        return f"nar-{len(self.writes)}"


class _StubRMemRaise:
    async def write_narrative(self, **kwargs: Any) -> str:  # noqa: ANN401
        raise RuntimeError("kaboom")


class _StubBus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, envelope: Any) -> str:  # noqa: ANN401
        self.published.append(envelope)
        return f"env-{len(self.published)}"


class _StubBusRaise:
    async def publish(self, envelope: Any) -> str:  # noqa: ANN401
        raise RuntimeError("bus down")


class _Verdict:
    def __init__(
        self, decision: str, hits: tuple[Any, ...] = (), reason: str = ""
    ) -> None:
        self.decision = decision
        self.detector_hits = hits
        self.reason = reason


class _Hit:
    def __init__(self, name: str) -> None:
        self.detector_name = name
        self.severity = "warning"
        self.evidence = {}


class _StubImmune:
    def __init__(self, verdict: _Verdict, healthy: bool = True) -> None:
        self._verdict = verdict
        self._healthy = healthy
        self.calls: list[Any] = []

    def is_healthy(self) -> bool:
        return self._healthy

    async def scan(self, request: Any) -> _Verdict:  # noqa: ANN401
        self.calls.append(request)
        return self._verdict


class _StubImmuneRaise:
    def is_healthy(self) -> bool:
        return True

    async def scan(self, request: Any) -> _Verdict:  # noqa: ANN401
        raise RuntimeError("immune down")


class _StubObs:
    def __init__(self) -> None:
        self.scores: list[tuple[str, float, dict[str, Any] | None]] = []

    def score(
        self, name: str, value: float, *, attributes: dict[str, Any] | None = None
    ) -> None:
        self.scores.append((name, value, attributes))


class _StubObsRaise:
    def score(
        self, name: str, value: float, *, attributes: dict[str, Any] | None = None
    ) -> None:
        raise RuntimeError("obs down")


# ── Pure-function tests ────────────────────────────────────────────────────


def test_check_threshold_lower_is_better_branches():
    # error_rate is direction="below": bigger is worse.
    assert _check_threshold("error_rate", 0.01) is None
    assert _check_threshold("error_rate", 0.05) == "warning"
    assert _check_threshold("error_rate", 0.09) == "warning"
    assert _check_threshold("error_rate", 0.10) == "critical"
    assert _check_threshold("error_rate", 0.50) == "critical"


def test_check_threshold_higher_is_better_branches():
    # tool_success_ratio is direction="above": smaller is worse.
    assert _check_threshold("tool_success_ratio", 1.0) is None
    assert _check_threshold("tool_success_ratio", 0.80) == "warning"
    assert _check_threshold("tool_success_ratio", 0.65) == "warning"
    assert _check_threshold("tool_success_ratio", 0.60) == "critical"
    assert _check_threshold("tool_success_ratio", 0.10) == "critical"


def test_check_threshold_unknown_metric_returns_none():
    assert _check_threshold("does_not_exist", 999.0) is None


def test_classify_recovery_covers_all_buckets():
    assert classify_recovery("timeout") == "retry"
    assert classify_recovery("network_error") == "retry"
    assert classify_recovery("rate_limit_hit") == "retry"
    assert classify_recovery("tool_not_installed") == "alternative_tool"
    assert classify_recovery("resource_not_found") == "alternative_tool"
    assert classify_recovery("unsupported_op") == "alternative_tool"
    assert classify_recovery("auth_failure") == "escalate"
    assert classify_recovery("permission_denied") == "escalate"
    assert classify_recovery("random_junk") == "skip"


def test_classify_recovery_escalate_wins_over_retry():
    # 'credential' matches escalate keyword; must not be classified as retry.
    assert classify_recovery("credential_timeout") == "escalate"


def test_fallback_guardrail_scan_hits_secrets():
    hit = _fallback_guardrail_scan("llm_hallucination", "leaked api_key in log")
    assert hit is not None
    assert hit[0] == Guardrail.NO_HARD_CODED_SECRETS


def test_fallback_guardrail_scan_hits_compute():
    hit = _fallback_guardrail_scan("llm_output", "did arithmetic inside completion")
    assert hit is not None
    assert hit[0] == Guardrail.LLM_MUST_NOT_COMPUTE


def test_fallback_guardrail_scan_clean():
    assert _fallback_guardrail_scan("timeout", "generic timeout") is None


# ── Locked constants ───────────────────────────────────────────────────────


def test_locked_constants_are_fixed():
    assert TEKTOS_MANAGER_PROVENANCE == "tektos.manager"
    assert TEKTOS_MANAGER_PREDICATE == "tektos.manager.feedback_generated"
    assert TEKTOS_MANAGER_EVENT_ARCHETYPE == "tektos.manager.archetype_recognized"
    assert TEKTOS_MANAGER_EVENT_GUARDRAIL == "tektos.manager.guardrail_triggered"
    assert TEKTOS_MANAGER_DEFAULT_CONFIDENCE == 0.75


# ── Lifecycle hooks — unbound (fail-open) ──────────────────────────────────


def test_on_task_start_transitions_to_active_and_scores_latency():
    obs = _StubObs()
    m = TektosManager(observability=obs)
    asyncio.run(m.on_task_start(session_id="s1", task_id="t1", spec_id="spec-1"))
    assert m.state == "active"
    assert obs.scores == [
        (
            "plugin.tektos.manager.latency",
            0.0,
            {"session_id": "s1", "task_id": "t1", "spec_id": "spec-1"},
        )
    ]


def test_on_task_complete_success_scores_full_metric_set():
    obs = _StubObs()
    m = TektosManager(observability=obs)
    asyncio.run(
        m.on_task_complete(
            session_id="s1",
            task_id="t1",
            success=True,
            tokens_used=100,
            tools_used=4,
            elapsed_seconds=2.5,
        )
    )
    assert m.state == "idle"
    names = [s[0] for s in obs.scores]
    assert "plugin.tektos.manager.latency" in names
    assert "plugin.tektos.manager.error_rate" in names
    assert "plugin.tektos.manager.token_efficiency" in names
    assert "plugin.tektos.manager.tool_success_ratio" in names


def test_on_task_complete_failure_records_error_and_zero_tool_success():
    obs = _StubObs()
    m = TektosManager(observability=obs)
    asyncio.run(
        m.on_task_complete(
            session_id="s1",
            task_id="t1",
            success=False,
        )
    )
    error_score = next(
        s for s in obs.scores if s[0] == "plugin.tektos.manager.error_rate"
    )
    tool_score = next(
        s for s in obs.scores if s[0] == "plugin.tektos.manager.tool_success_ratio"
    )
    assert error_score[1] == 1.0
    assert tool_score[1] == 0.0


def test_on_task_complete_success_token_efficiency_avoids_divide_by_zero():
    obs = _StubObs()
    m = TektosManager(observability=obs)
    asyncio.run(
        m.on_task_complete(
            session_id="s1", task_id="t1", success=True, tokens_used=50, tools_used=0
        )
    )
    te = next(
        s for s in obs.scores if s[0] == "plugin.tektos.manager.token_efficiency"
    )
    assert te[1] == 50.0  # 50 / max(1, 0)


# ── Error hook — archetype path ────────────────────────────────────────────


def test_on_error_records_event_and_scores_archetype_frequency():
    obs = _StubObs()
    m = TektosManager(observability=obs, archetype_threshold=99)
    asyncio.run(
        m.on_error(session_id="s1", category="llm_malformed_json", description="bad")
    )
    freq_scores = [
        s for s in obs.scores if s[0] == "plugin.tektos.manager.archetype_frequency"
    ]
    assert freq_scores
    assert freq_scores[-1][1] == 1.0


def test_on_error_below_threshold_returns_none_feedback():
    rmem = _StubRMem()
    m = TektosManager(relational_memory=rmem, archetype_threshold=5)
    feedback, nid = asyncio.run(
        m.on_error(session_id="s1", category="rare_error", description="thing")
    )
    assert feedback is None
    assert nid is None
    assert rmem.writes == []


def test_on_error_hits_threshold_emits_archetype_feedback_and_persists():
    rmem = _StubRMem()
    bus = _StubBus()
    m = TektosManager(
        relational_memory=rmem, event_bus=bus, archetype_threshold=3
    )
    for _ in range(3):
        feedback, nid = asyncio.run(
            m.on_error(
                session_id="s1",
                category="llm_malformed_json",
                description="parser fail",
            )
        )
    assert feedback is not None
    assert feedback.type == "archetype_recognized"
    assert feedback.category == "llm_malformed_json"
    assert nid == "nar-1"
    assert len(rmem.writes) == 1
    write = rmem.writes[0]
    assert write["provenance"] == TEKTOS_MANAGER_PROVENANCE
    assert write["agent_id"] == TEKTOS_MANAGER_PROVENANCE
    assert write["title"].startswith(TEKTOS_MANAGER_PREDICATE)
    body = json.loads(write["body"])
    assert body["type"] == "archetype_recognized"
    # Two envelopes: feedback_generated + archetype_recognized
    assert len(bus.published) == 2
    assert bus.published[0].event_type == TEKTOS_MANAGER_PREDICATE
    assert bus.published[1].event_type == TEKTOS_MANAGER_EVENT_ARCHETYPE
    assert bus.published[1].payload["occurrence_count"] == 3


def test_on_error_hits_threshold_confidence_override():
    rmem = _StubRMem()
    m = TektosManager(relational_memory=rmem, archetype_threshold=1)
    asyncio.run(
        m.on_error(
            session_id="s1",
            category="x",
            description="y",
            confidence=0.99,
        )
    )
    assert rmem.writes[0]["confidence"] == 0.99


def test_on_error_default_confidence_used_when_none_passed():
    rmem = _StubRMem()
    m = TektosManager(relational_memory=rmem, archetype_threshold=1)
    asyncio.run(m.on_error(session_id="s1", category="x", description="y"))
    assert rmem.writes[0]["confidence"] == TEKTOS_MANAGER_DEFAULT_CONFIDENCE


# ── Error hook — guardrail path (Immune bound) ─────────────────────────────


def test_on_error_guardrail_via_immune_block_verdict():
    rmem = _StubRMem()
    bus = _StubBus()
    immune = _StubImmune(
        _Verdict(
            "block",
            hits=(_Hit("secret_scanner"),),
            reason="detected api_key in payload",
        )
    )
    m = TektosManager(
        relational_memory=rmem,
        event_bus=bus,
        immune=immune,
        archetype_threshold=99,  # keep archetype path silent
    )
    feedback, nid = asyncio.run(
        m.on_error(
            session_id="s1",
            category="log_leak",
            description="value logged",
        )
    )
    assert feedback is not None
    assert feedback.type == "guardrail_triggered"
    assert feedback.severity == "critical"
    assert nid == "nar-1"
    assert immune.calls, "ImmunePort.scan should have been invoked"
    assert any(
        env.event_type == TEKTOS_MANAGER_EVENT_GUARDRAIL for env in bus.published
    )
    guardrail_env = next(
        env for env in bus.published if env.event_type == TEKTOS_MANAGER_EVENT_GUARDRAIL
    )
    assert guardrail_env.payload["guardrail_source"] == "immune"
    assert guardrail_env.payload["detector_hits"] == ("secret_scanner",)


def test_on_error_guardrail_immune_allow_returns_none():
    immune = _StubImmune(_Verdict("allow"))
    m = TektosManager(immune=immune, archetype_threshold=99)
    feedback, nid = asyncio.run(
        m.on_error(session_id="s1", category="clean", description="clean")
    )
    assert feedback is None
    assert nid is None


def test_on_error_guardrail_immune_raise_falls_back_to_keyword_scan():
    rmem = _StubRMem()
    m = TektosManager(
        relational_memory=rmem,
        immune=_StubImmuneRaise(),
        archetype_threshold=99,
    )
    feedback, _ = asyncio.run(
        m.on_error(
            session_id="s1", category="log", description="leaked api_key here"
        )
    )
    assert feedback is not None
    assert feedback.type == "guardrail_triggered"


def test_on_error_guardrail_fallback_keyword_scan_when_immune_unbound():
    rmem = _StubRMem()
    m = TektosManager(relational_memory=rmem, archetype_threshold=99)
    feedback, _ = asyncio.run(
        m.on_error(
            session_id="s1",
            category="secrets_log",
            description="password appeared in output",
        )
    )
    assert feedback is not None
    assert feedback.type == "guardrail_triggered"


# ── Fail-open: port failures never break the hook ──────────────────────────


def test_on_error_persistence_failure_still_returns_feedback():
    m = TektosManager(relational_memory=_StubRMemRaise(), archetype_threshold=1)
    feedback, nid = asyncio.run(
        m.on_error(session_id="s1", category="x", description="y")
    )
    assert feedback is not None
    assert nid is None


def test_on_error_bus_failure_still_returns_feedback():
    rmem = _StubRMem()
    m = TektosManager(
        relational_memory=rmem, event_bus=_StubBusRaise(), archetype_threshold=1
    )
    feedback, nid = asyncio.run(
        m.on_error(session_id="s1", category="x", description="y")
    )
    assert feedback is not None
    assert nid == "nar-1"


def test_observability_failure_never_raises():
    m = TektosManager(observability=_StubObsRaise())
    # None of these should raise.
    asyncio.run(m.on_task_start(session_id="s", task_id="t"))
    asyncio.run(
        m.on_task_complete(session_id="s", task_id="t", success=True, tools_used=1)
    )


# ── Spiral update hook ─────────────────────────────────────────────────────


def test_on_spiral_update_expanding_emits_warning():
    rmem = _StubRMem()
    bus = _StubBus()
    m = TektosManager(relational_memory=rmem, event_bus=bus)
    feedback, nid = asyncio.run(
        m.on_spiral_update(
            session_id="s", new_radius=1.5, description="bigger context"
        )
    )
    assert feedback is not None
    assert feedback.type == "spiral_warning"
    assert feedback.severity == "warning"
    assert m.spiral_radius == 1.5
    assert nid == "nar-1"


def test_on_spiral_update_converging_returns_none():
    m = TektosManager()
    feedback, nid = asyncio.run(
        m.on_spiral_update(
            session_id="s", new_radius=0.5, description="reduced scope"
        )
    )
    assert feedback is None
    assert nid is None
    assert m.spiral_radius == 0.5


# ── Rhythm hook ────────────────────────────────────────────────────────────


def test_on_rhythm_event_is_synchronous_and_returns_feedback():
    m = TektosManager()
    feedback = m.on_rhythm_event(
        session_id="s", rhythm_name="daily", description="daily rollup"
    )
    assert isinstance(feedback, ManagerFeedback)
    assert feedback.type == "rhythm_triggered"
    assert feedback.severity == "info"
    assert feedback.category == "rhythm.daily"


# ── Health report + recent buffer ──────────────────────────────────────────


def test_get_health_report_reflects_state_radius_and_archetypes():
    m = TektosManager(archetype_threshold=3)
    for _ in range(2):
        asyncio.run(m.on_error(session_id="s", category="cat_a", description="d"))
    for _ in range(1):
        asyncio.run(m.on_error(session_id="s", category="cat_b", description="d"))
    report = m.get_health_report()
    assert isinstance(report, ManagerHealthReport)
    assert report.state == "idle"
    assert report.spiral_radius == 1.0
    cats = {c: n for (c, n, _t) in report.active_archetypes}
    assert cats == {"cat_a": 2, "cat_b": 1}


def test_list_recent_returns_last_n_in_insertion_order():
    m = TektosManager(archetype_threshold=1, max_records=100)
    for i in range(5):
        asyncio.run(
            m.on_error(session_id="s", category=f"cat_{i}", description="d")
        )
    items = m.list_recent(limit=3)
    assert len(items) == 3
    assert items[-1].category == "cat_4"


def test_list_recent_negative_limit_returns_empty():
    m = TektosManager(archetype_threshold=1)
    asyncio.run(m.on_error(session_id="s", category="x", description="d"))
    assert m.list_recent(limit=0) == ()
    assert m.list_recent(limit=-5) == ()


def test_max_records_bounds_the_ring_buffer():
    m = TektosManager(archetype_threshold=1, max_records=3)
    for i in range(10):
        asyncio.run(
            m.on_error(session_id="s", category=f"cat_{i}", description="d")
        )
    assert len(m.list_recent(limit=100)) == 3


def test_classify_recovery_passthrough():
    m = TektosManager()
    assert m.classify_recovery("timeout") == "retry"
    assert m.classify_recovery("permission_denied") == "escalate"


def test_check_metric_threshold_passthrough():
    m = TektosManager()
    assert m.check_metric_threshold("error_rate", 0.15) == "critical"
    assert m.check_metric_threshold("error_rate", 0.01) is None


def test_persistence_bound_flag_reflects_relational_memory():
    assert not TektosManager().is_persistence_bound
    assert TektosManager(relational_memory=_StubRMem()).is_persistence_bound


def test_immune_bound_flag_tolerates_is_healthy_raising():
    class _Boom:
        def is_healthy(self) -> bool:
            raise RuntimeError("nope")

        async def scan(self, request: Any) -> Any:  # noqa: ANN401
            return _Verdict("allow")

    assert not TektosManager(immune=_Boom()).is_immune_bound
