"""Contract tests for SelfRepairProposer (Stage 5.6 · ADR-095).

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
- Strategy-type guard: propose rejects non-RepairStrategy values.
- Deny path end-to-end: ApprovalResolverPort returns REJECTED → proposer's
  record_denial closes the audit loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest

from kernel.reliability.models import (
    RepairRecord,
    RepairStatus,
    RepairStrategy,
)
from plugins.tektos.self_repair.proposer import (
    DEFAULT_SELF_MODIFICATION_CONFIDENCE,
    SELF_MODIFICATION_PROVENANCE,
    SELF_REPAIR_DENIED_PREDICATE,
    SELF_REPAIR_PROPOSED_EVENT,
    SELF_REPAIR_PROPOSED_PREDICATE,
    SelfRepairProposer,
)
from ports.approval import ApprovalRecord, ApprovalStatus, ChangeApprovalTier
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


class _DenyingResolver:
    """Test double: resolves every approval with REJECTED."""

    async def resolve(
        self,
        approval_id: str,
        approved: bool,
        *,
        reason: str | None = None,
        modifications: Mapping[str, Any] | None = None,
        resolved_by: str = "user",
    ) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=approval_id,
            intention_id="tektos.self_repair.stub",
            proposing_domain="tektos",
            tier=ChangeApprovalTier.HUMAN_REQUIRED,
            delta={},
            status=ApprovalStatus.REJECTED,
            proposed_at=datetime.now(timezone.utc),
            reason=reason,
        )


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


def _mk_repair_record() -> RepairRecord:
    return RepairRecord(
        record_id="rec-1",
        threat_category="context_overflow",
        threat_severity="high",
        description="context window at 97% capacity",
        status=RepairStatus.DIAGNOSING,
    )


def _mk_proposer() -> tuple[SelfRepairProposer, _StubGateway, _RecordingMemory, _RecordingBus]:
    gw = _StubGateway()
    mem = _RecordingMemory()
    bus = _RecordingBus()
    proposer = SelfRepairProposer(
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
            repair_record=_mk_repair_record(),
            strategy=RepairStrategy.COMPRESS_CONTEXT,
            target_path="plugins/tektos/agent.py",
            patch="- old\n+ new",
            reason="context overflow guard",
        )
    )

    assert isinstance(approval_id, str) and approval_id
    # ApprovalGatewayPort called with HUMAN_REQUIRED + tektos domain.
    assert len(gw.calls) == 1
    call = gw.calls[0]
    assert call["approval_id"] == approval_id
    assert call["tier"] is ChangeApprovalTier.HUMAN_REQUIRED
    assert call["proposing_domain"] == "tektos"
    assert call["intention_id"].startswith("tektos.self_repair.")
    assert call["delta"]["strategy"] == "compress_context"
    assert call["diff_preview"]["strategy"] == "compress_context"
    assert call["diff_preview"]["threat_category"] == "context_overflow"
    # MemoryPort written with locked provenance + 0.85 confidence.
    assert len(mem.events) == 1
    evt = mem.events[0]
    assert evt["provenance"] == SELF_MODIFICATION_PROVENANCE
    assert evt["confidence"] == DEFAULT_SELF_MODIFICATION_CONFIDENCE
    assert evt["predicate"] == SELF_REPAIR_PROPOSED_PREDICATE
    assert evt["attributes"]["strategy"] == "compress_context"
    assert evt["attributes"]["kind"] == "self_repair"
    # EventBusPort published with reserved event_type + tektos producer.
    assert len(bus.published) == 1
    env = bus.published[0]
    assert env.event_type == SELF_REPAIR_PROPOSED_EVENT
    assert env.producer_plugin == "tektos"
    assert env.payload["strategy"] == "compress_context"
    assert env.payload["kind"] == "self_repair"


# ── apply() blocked ────────────────────────────────────────────────────


def test_apply_raises_not_implemented_referencing_adr_090() -> None:
    proposer, _gw, _mem, _bus = _mk_proposer()
    with pytest.raises(NotImplementedError) as exc:
        asyncio.run(proposer.apply("appr-42"))
    assert "ADR-090" in str(exc.value)
    assert "appr-42" in str(exc.value)


# ── Deny path (end-to-end round-trip per ADR-090 interim rule 5) ───────


def test_deny_path_end_to_end_writes_denial_triple() -> None:
    """ADR-090 interim rule 5: no ApprovalPort verdict → no apply.

    Round-trips a proposal through propose → REJECTED resolution →
    record_denial, asserting apply() is never called and the audit trail
    carries both the propose event and the denial event.
    """
    proposer, _gw, mem, _bus = _mk_proposer()
    resolver = _DenyingResolver()

    approval_id = asyncio.run(
        proposer.propose(
            repair_record=_mk_repair_record(),
            strategy=RepairStrategy.COMPRESS_CONTEXT,
            target_path="plugins/tektos/agent.py",
            patch="- old\n+ new",
            reason="context overflow guard",
        )
    )
    proposal_id = mem.events[0]["subject"]

    record = asyncio.run(
        resolver.resolve(
            approval_id=approval_id,
            approved=False,
            reason="user rejected self-mod",
        )
    )
    assert record.status is ApprovalStatus.REJECTED

    # Simulate the caller's post-denial hook.
    asyncio.run(
        proposer.record_denial(
            proposal_id=proposal_id,
            approval_id=approval_id,
            target_path="plugins/tektos/agent.py",
            reason=record.reason or "",
        )
    )

    # Two memory writes: propose + denial. No apply-side write.
    assert len(mem.events) == 2
    proposed, denied = mem.events
    assert proposed["predicate"] == SELF_REPAIR_PROPOSED_PREDICATE
    assert denied["predicate"] == SELF_REPAIR_DENIED_PREDICATE
    assert denied["provenance"] == SELF_MODIFICATION_PROVENANCE
    assert denied["confidence"] == DEFAULT_SELF_MODIFICATION_CONFIDENCE
    assert denied["attributes"]["denial_reason"] == "user rejected self-mod"


# ── Confidence invariant ──────────────────────────────────────────────


def test_confidence_above_ceiling_rejected_at_ctor() -> None:
    with pytest.raises(ValueError, match="ADR-090"):
        SelfRepairProposer(
            approval_gateway=_StubGateway(),  # type: ignore[arg-type]
            memory=_RecordingMemory(),  # type: ignore[arg-type]
            event_bus=_RecordingBus(),  # type: ignore[arg-type]
            confidence=0.95,
        )


def test_confidence_below_zero_rejected_at_ctor() -> None:
    with pytest.raises(ValueError, match="ADR-027"):
        SelfRepairProposer(
            approval_gateway=_StubGateway(),  # type: ignore[arg-type]
            memory=_RecordingMemory(),  # type: ignore[arg-type]
            event_bus=_RecordingBus(),  # type: ignore[arg-type]
            confidence=-0.1,
        )


# ── Provenance lock ───────────────────────────────────────────────────


def test_provenance_is_class_level_constant_not_ctor_arg() -> None:
    with pytest.raises(TypeError):
        SelfRepairProposer(
            approval_gateway=_StubGateway(),  # type: ignore[arg-type]
            memory=_RecordingMemory(),  # type: ignore[arg-type]
            event_bus=_RecordingBus(),  # type: ignore[arg-type]
            provenance="something_else",  # type: ignore[call-arg]
        )
    assert SelfRepairProposer.provenance == SELF_MODIFICATION_PROVENANCE


# ── Strategy-type guard ───────────────────────────────────────────────


def test_propose_rejects_non_repair_strategy() -> None:
    proposer, _gw, _mem, _bus = _mk_proposer()
    with pytest.raises(ValueError, match="RepairStrategy"):
        asyncio.run(
            proposer.propose(
                repair_record=_mk_repair_record(),
                strategy="apply_patch",  # type: ignore[arg-type]
                target_path="plugins/tektos/agent.py",
                patch="patch",
                reason="reason",
            )
        )
