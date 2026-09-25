"""SelfRepairProposer — Stage 5.6 propose-only self-repair.

Per ADR-095 D2 + ADR-090 §Interim behaviour, this proposer:

1. Builds a ``SelfRepairProposal`` dataclass from a ``RepairRecord``
   (donor vocabulary) and the proposed strategy label.
2. Routes it through ``ApprovalGatewayPort.propose`` with tier
   ``HUMAN_REQUIRED`` (ADR-095 D3).
3. Writes a ``MemoryPort`` triple with
   ``provenance="tektos_self_modification"`` and ``confidence=0.85``
   (satisfies ADR-090 interim rule 3 + spec §25.4 ``≤ 0.9`` invariant).
4. Publishes ``tektos.self_modification.proposed`` on the event bus
   (namespace reserved by ADR-086).
5. Exposes ``apply()`` that raises ``NotImplementedError`` referencing
   ADR-090 — physically cannot execute any RepairStrategy
   (belt-and-suspenders on top of the approval-gate deny path per
   ADR-095 D2).
6. Exposes ``record_denial()`` for the denial-close memory triple
   (ADR-095 D4).

The proposer uses the donor ``RepairRecord`` / ``RepairStrategy`` /
``RepairStatus`` vocabulary vendored under
``adapters/tektos/vendor/self_repair_models_donor.py`` so future
post-ratification landing of the SelfRepairEngine can consume the same
proposal shape without renaming.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, NoReturn

from kernel.reliability.models import (
    RepairRecord,
    RepairStrategy,
)
from ports.approval import (
    ApprovalGatewayPort,
    ChangeApprovalTier,
)
from ports.event_bus import EventBusPort
from ports.event_envelope import EventEnvelope
from ports.memory import MemoryPort

SELF_MODIFICATION_PROVENANCE = "tektos_self_modification"
"""Provenance string locked by spec §25.4 + ADR-090 interim rule 3."""

SELF_MODIFICATION_CONFIDENCE_CEILING = 0.9
"""Ceiling from spec §25.4 + ADR-090 interim rule 3."""

DEFAULT_SELF_MODIFICATION_CONFIDENCE = 0.85
"""Default confidence — 0.05 headroom below the ceiling per ADR-095."""

SELF_REPAIR_PROPOSED_EVENT = "tektos.self_modification.proposed"
"""Event type reserved by ADR-086."""

SELF_REPAIR_PROPOSED_PREDICATE = "tektos.self_modification.proposed"
"""Predicate for the propose-time memory triple."""

SELF_REPAIR_DENIED_PREDICATE = "tektos.self_modification.denied"
"""Predicate for the denial-close memory triple (ADR-095 D4)."""

PROPOSING_DOMAIN = "tektos"
"""Fixed proposing_domain for every self-modification proposal (ADR-007)."""


@dataclass(frozen=True, slots=True)
class SelfRepairProposal:
    """One self-repair proposal.

    Frozen: proposals are immutable audit artefacts. Any revision produces
    a fresh proposal with a new ``proposal_id``.
    """

    proposal_id: str
    repair_record: RepairRecord
    strategy: RepairStrategy
    target_path: str
    patch: str
    reason: str
    proposed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def as_delta(self) -> dict[str, Any]:
        """Serialize into the ``delta`` payload for ``ApprovalGatewayPort.propose``."""
        return {
            "proposal_id": self.proposal_id,
            "repair_record": self.repair_record.to_dict(),
            "strategy": self.strategy.value,
            "target_path": self.target_path,
            "patch": self.patch,
            "reason": self.reason,
            "proposed_at": self.proposed_at.isoformat(),
        }


class SelfRepairProposer:
    """Propose-only self-repair path (ADR-095 D2)."""

    provenance: str = SELF_MODIFICATION_PROVENANCE
    """Class-level constant — cannot be overridden per proposer instance."""

    def __init__(
        self,
        *,
        approval_gateway: ApprovalGatewayPort,
        memory: MemoryPort,
        event_bus: EventBusPort,
        confidence: float = DEFAULT_SELF_MODIFICATION_CONFIDENCE,
    ) -> None:
        if confidence > SELF_MODIFICATION_CONFIDENCE_CEILING:
            raise ValueError(
                "SelfRepairProposer confidence must be "
                f"<= {SELF_MODIFICATION_CONFIDENCE_CEILING} "
                "(ADR-090 interim rule 3; spec §25.4)."
            )
        if confidence < 0.0:
            raise ValueError(
                "SelfRepairProposer confidence must be >= 0.0 (ADR-027)."
            )
        self._approval_gateway = approval_gateway
        self._memory = memory
        self._event_bus = event_bus
        self._confidence = float(confidence)

    async def propose(
        self,
        *,
        repair_record: RepairRecord,
        strategy: RepairStrategy,
        target_path: str,
        patch: str,
        reason: str,
    ) -> str:
        """Build a proposal, route through approval + memory + event bus.

        Returns the opaque ``approval_id``. Callers await resolution via
        :class:`ApprovalResolverPort` on a later turn.

        Raises:
            ValueError: any input field is empty or the strategy is not a
                :class:`RepairStrategy` member.
        """
        for name, value in (
            ("target_path", target_path),
            ("patch", patch),
            ("reason", reason),
        ):
            if not value or not value.strip():
                raise ValueError(
                    f"SelfRepairProposer.propose {name!r} must be non-empty."
                )
        if not isinstance(strategy, RepairStrategy):
            raise ValueError(
                "SelfRepairProposer.propose 'strategy' must be a "
                "RepairStrategy member (vendored donor vocabulary)."
            )

        proposal = SelfRepairProposal(
            proposal_id=str(uuid.uuid4()),
            repair_record=repair_record,
            strategy=strategy,
            target_path=target_path,
            patch=patch,
            reason=reason,
        )

        intention_id = f"tektos.self_repair.{proposal.proposal_id}"
        delta = proposal.as_delta()

        approval_id = await self._approval_gateway.propose(
            intention_id=intention_id,
            delta=delta,
            tier=ChangeApprovalTier.HUMAN_REQUIRED,
            proposing_domain=PROPOSING_DOMAIN,
            diff_preview={
                "action": "self_repair.propose",
                "strategy": strategy.value,
                "target_path": target_path,
                "reason": reason,
                "threat_category": repair_record.threat_category,
                "threat_severity": repair_record.threat_severity,
            },
        )

        await self._memory.write_event(
            subject=proposal.proposal_id,
            predicate=SELF_REPAIR_PROPOSED_PREDICATE,
            object=target_path,
            provenance=self.provenance,
            confidence=self._confidence,
            attributes={
                "approval_id": approval_id,
                "intention_id": intention_id,
                "strategy": strategy.value,
                "threat_category": repair_record.threat_category,
                "threat_severity": repair_record.threat_severity,
                "record_id": repair_record.record_id,
                "reason": reason,
                "kind": "self_repair",
            },
        )

        await self._event_bus.publish(
            EventEnvelope(
                event_type=SELF_REPAIR_PROPOSED_EVENT,
                producer_plugin=PROPOSING_DOMAIN,
                payload={
                    "proposal_id": proposal.proposal_id,
                    "approval_id": approval_id,
                    "intention_id": intention_id,
                    "target_path": target_path,
                    "strategy": strategy.value,
                    "record_id": repair_record.record_id,
                    "kind": "self_repair",
                    "provenance": self.provenance,
                    "confidence": self._confidence,
                },
            )
        )

        return approval_id

    async def record_denial(
        self,
        *,
        proposal_id: str,
        approval_id: str,
        target_path: str,
        reason: str,
    ) -> None:
        """Close the audit loop on a denial (ADR-095 D4)."""
        await self._memory.write_event(
            subject=proposal_id,
            predicate=SELF_REPAIR_DENIED_PREDICATE,
            object=target_path,
            provenance=self.provenance,
            confidence=self._confidence,
            attributes={
                "approval_id": approval_id,
                "denial_reason": reason,
                "kind": "self_repair",
            },
        )

    async def apply(self, approval_id: str) -> NoReturn:
        """Never returns — physically cannot apply (ADR-090 not ratified).

        Belt-and-suspenders on top of the approval-gate deny path: even if
        a caller bypasses the gate, this method cannot execute any
        RepairStrategy because it has no implementation.
        """
        raise NotImplementedError(
            "SelfRepairProposer.apply is unavailable until ADR-090 "
            "(SelfModificationPort) ratifies. Stage 5.6 is propose-only "
            "per ADR-095 D2 + ADR-090 interim rule 4. "
            f"(approval_id={approval_id!r})"
        )


__all__ = [
    "DEFAULT_SELF_MODIFICATION_CONFIDENCE",
    "PROPOSING_DOMAIN",
    "SELF_MODIFICATION_CONFIDENCE_CEILING",
    "SELF_MODIFICATION_PROVENANCE",
    "SELF_REPAIR_DENIED_PREDICATE",
    "SELF_REPAIR_PROPOSED_EVENT",
    "SELF_REPAIR_PROPOSED_PREDICATE",
    "SelfRepairProposal",
    "SelfRepairProposer",
]
