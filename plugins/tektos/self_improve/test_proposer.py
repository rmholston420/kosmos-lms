"""Contract tests for SelfImprovementProposer (Stage 5.6 · ADR-095).

Covers:
- Happy-path propose: returns approval_id, ApprovalGatewayPort called with
  HUMAN_REQUIRED tier + proposing_domain='tektos', MemoryPort written with
  provenance='tektos_self_modification' + confidence=0.85, EventBusPort
  published with event_type='tektos.self_modification.proposed'.
- apply() raises NotImplementedError referencing ADR-090.
- Deny path: record_denial writes second MemoryPort triple with
  predicate='tektos.self_modification.denied'.
- Confidence-invariant: construction with confidence > 0.9 raises ValueError.
- Provenance-lock: provenance is a class-level constant, not a ctor arg.
- Empty-input guard: propose with empty target_path/patch/reason raises
  ValueError.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from adapters.tektos.vendor.self_improve_models_donor import ExperienceRecord
from plugins.tektos.self_improve.proposer import (
    DEFAULT_SELF_MODIFICATION_CONFIDENCE,
    SELF_IMPROVEMENT_DENIED_PREDICATE,
    SELF_IMPROVEMENT_PROPOSED_EVENT,
    SELF_IMPROVEMENT_PROPOSED_PREDICATE,
    SELF_MODIFICATION_PROVENANCE,
    SelfImprovementProposer,
)
from ports.approval import ChangeApprovalTier
from ports.event_envelope import EventEnvelope


class _StubGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def propose(
        self,
        intention_id: str,
        delta: Mapping[str, Any],
        tier: ChangeApprovalTier,
        *,
        proposing_domain: str,
        diff_preview: Mapping[str, Any] | None = None,
    ) -> str:
        approval_id = f"appr-{len(self.calls) + 1}"
        self.calls.append(
            {
                "approval_id": approval_id,
                "intention_id": intention_id,
                "delta": dict(delta),
                "tier": tier,
                "proposing_domain": proposing_domain,
                "diff_preview": dict(diff_preview or {}),
            }
        )
        return approval_id


class _RecordingMemory:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        source_citation: Any = None,
        pii_tier: str = "Public",
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        self.events.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "provenance": provenance,
                "confidence": confidence,
                "attributes": dict(attributes or {}),
            }
        )

        class _Id:
            id = f"mem-{len(self.events)}"

        return _Id()


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return f"evt-{len(self.published)}"


def _mk_experience() -> ExperienceRecord:
    return ExperienceRecord(
        session_id="sess-1",
        task="refactor tests",
        model_used="glm-4.6",
        success=True,
        tests_passed=42,
        tests_total=42,
        wall_time_seconds=180.0,
        evaluation_score=0.95,
        lessons=["prefer async fixtures"],
    )


def _mk_proposer() -> tuple[SelfImprovementProposer, _StubGateway, _RecordingMemory, _RecordingBus]:
    gw = _StubGateway()
    mem = _RecordingMemory()
    bus = _RecordingBus()
    proposer = SelfImprovementProposer(
        approval_gateway=gw,  # type: ignore[arg-type]
        memory=mem,  # type: ignore[arg-type]
        event_bus=bus,  # type: ignore[arg-type]
    )
    return proposer, gw, mem, bus


# ── Happy-path ─────────────────────────────────────────────────────────


def test_propose_returns_approval_id_and_routes_all_three_ports() -> None:
    proposer, gw, mem, bus = _mk_proposer()

    approval_id = asyncio.run(
        proposer.propose(
            experience=_mk_experience(),
            target_path="plugins/tektos/agent.py",
            patch="- old\n+ new",
            reason="lesson learned: async fixtures",
        )
    )

    assert isinstance(approval_id, str) and approval_id
    # ApprovalGatewayPort called with HUMAN_REQUIRED + tektos domain.
    assert len(gw.calls) == 1
    call = gw.calls[0]
    assert call["approval_id"] == approval_id
    assert call["tier"] is ChangeApprovalTier.HUMAN_REQUIRED
    assert call["proposing_domain"] == "tektos"
    assert call["intention_id"].startswith("tektos.self_improve.")
    assert call["delta"]["target_path"] == "plugins/tektos/agent.py"
    assert call["diff_preview"]["action"] == "self_improvement.propose"
    # MemoryPort written with locked provenance + 0.85 confidence.
    assert len(mem.events) == 1
    evt = mem.events[0]
    assert evt["provenance"] == SELF_MODIFICATION_PROVENANCE
    assert evt["confidence"] == DEFAULT_SELF_MODIFICATION_CONFIDENCE
    assert evt["predicate"] == SELF_IMPROVEMENT_PROPOSED_PREDICATE
    assert evt["object"] == "plugins/tektos/agent.py"
    assert evt["attributes"]["approval_id"] == approval_id
    assert evt["attributes"]["kind"] == "self_improvement"
    # EventBusPort published with reserved event_type + tektos producer.
    assert len(bus.published) == 1
    env = bus.published[0]
    assert env.event_type == SELF_IMPROVEMENT_PROPOSED_EVENT
    assert env.producer_plugin == "tektos"
    assert env.payload["approval_id"] == approval_id
    assert env.payload["provenance"] == SELF_MODIFICATION_PROVENANCE
    assert env.payload["confidence"] == DEFAULT_SELF_MODIFICATION_CONFIDENCE


# ── apply() blocked ────────────────────────────────────────────────────


def test_apply_raises_not_implemented_referencing_adr_090() -> None:
    proposer, _gw, _mem, _bus = _mk_proposer()
    with pytest.raises(NotImplementedError) as exc:
        asyncio.run(proposer.apply("appr-1"))
    assert "ADR-090" in str(exc.value)
    assert "appr-1" in str(exc.value)


# ── Deny path ──────────────────────────────────────────────────────────


def test_record_denial_writes_denial_triple() -> None:
    proposer, _gw, mem, _bus = _mk_proposer()
    asyncio.run(
        proposer.record_denial(
            proposal_id="prop-1",
            approval_id="appr-1",
            target_path="plugins/tektos/agent.py",
            reason="user rejected self-mod",
        )
    )
    assert len(mem.events) == 1
    evt = mem.events[0]
    assert evt["predicate"] == SELF_IMPROVEMENT_DENIED_PREDICATE
    assert evt["provenance"] == SELF_MODIFICATION_PROVENANCE
    assert evt["confidence"] == DEFAULT_SELF_MODIFICATION_CONFIDENCE
    assert evt["attributes"]["denial_reason"] == "user rejected self-mod"


# ── Confidence invariant ──────────────────────────────────────────────


def test_confidence_above_ceiling_rejected_at_ctor() -> None:
    with pytest.raises(ValueError, match="ADR-090"):
        SelfImprovementProposer(
            approval_gateway=_StubGateway(),  # type: ignore[arg-type]
            memory=_RecordingMemory(),  # type: ignore[arg-type]
            event_bus=_RecordingBus(),  # type: ignore[arg-type]
            confidence=0.95,
        )


# ── Provenance lock ───────────────────────────────────────────────────


def test_provenance_is_class_level_constant_not_ctor_arg() -> None:
    # Attempting to pass provenance kwarg raises TypeError (no such kwarg).
    with pytest.raises(TypeError):
        SelfImprovementProposer(
            approval_gateway=_StubGateway(),  # type: ignore[arg-type]
            memory=_RecordingMemory(),  # type: ignore[arg-type]
            event_bus=_RecordingBus(),  # type: ignore[arg-type]
            provenance="something_else",  # type: ignore[call-arg]
        )
    # And the class attribute is locked.
    assert SelfImprovementProposer.provenance == SELF_MODIFICATION_PROVENANCE


# ── Input guard ────────────────────────────────────────────────────────


def test_propose_rejects_empty_target_path() -> None:
    proposer, _gw, _mem, _bus = _mk_proposer()
    with pytest.raises(ValueError, match="target_path"):
        asyncio.run(
            proposer.propose(
                experience=_mk_experience(),
                target_path="   ",
                patch="patch",
                reason="reason",
            )
        )
