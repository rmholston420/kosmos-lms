"""SelfImprovementProposer — Stage 5.6 propose-only self-improvement.

Per ADR-095 D2 + ADR-090 §Interim behaviour, this proposer:

1. Builds a ``SelfImprovementProposal`` dataclass from an ``ExperienceRecord``
   and a target patch.
2. Routes it through ``ApprovalGatewayPort.propose`` with tier
   ``HUMAN_REQUIRED`` (ADR-095 D3).
3. Writes a ``MemoryPort`` triple with
   ``provenance="tektos_self_modification"`` and ``confidence=0.85``
   (satisfies ADR-090 interim rule 3 + spec §25.4 ``≤ 0.9`` invariant).
4. Publishes ``tektos.self_modification.proposed`` on the event bus
   (namespace reserved by ADR-086).
5. Exposes ``apply()`` that raises ``NotImplementedError`` referencing
   ADR-090 — physically cannot mutate the filesystem (belt-and-suspenders
   on top of the approval-gate deny path per ADR-095 D2).
6. Exposes ``record_denial()`` that writes a second ``MemoryPort`` triple
   with ``predicate="tektos.self_modification.denied"`` so denials are as
   observable as proposals (ADR-095 D4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, NoReturn

from adapters.tektos.vendor.self_improve_models_donor import ExperienceRecord
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

SELF_IMPROVEMENT_PROPOSED_EVENT = "tektos.self_modification.proposed"
"""Event type reserved by ADR-086."""

SELF_IMPROVEMENT_DENIED_PREDICATE = "tektos.self_modification.denied"
"""Predicate for the denial-close memory triple (ADR-095 D4)."""

SELF_IMPROVEMENT_PROPOSED_PREDICATE = "tektos.self_modification.proposed"
"""Predicate for the propose-time memory triple."""

PROPOSING_DOMAIN = "tektos"
"""Fixed proposing_domain for every self-modification proposal (ADR-007)."""


@dataclass(frozen=True, slots=True)
class SelfImprovementProposal:
    """One self-improvement proposal.

    Frozen: proposals are immutable audit artefacts. Any revision produces
    a fresh proposal with a new ``proposal_id``.
    """

    proposal_id: str
    experience: ExperienceRecord
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
            "experience": self.experience.to_dict(),
            "target_path": self.target_path,
            "patch": self.patch,
            "reason": self.reason,
            "proposed_at": self.proposed_at.isoformat(),
        }


class SelfImprovementProposer:
    """Propose-only self-improvement path (ADR-095 D2)."""

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
                "SelfImprovementProposer confidence must be "
                f"<= {SELF_MODIFICATION_CONFIDENCE_CEILING} "
                "(ADR-090 interim rule 3; spec §25.4)."
            )
        if confidence < 0.0:
            raise ValueError(
                "SelfImprovementProposer confidence must be >= 0.0 (ADR-027)."
            )
        self._approval_gateway = approval_gateway
        self._memory = memory
        self._event_bus = event_bus
        self._confidence = float(confidence)

    async def propose(
        self,
        *,
        experience: ExperienceRecord,
        target_path: str,
        patch: str,
        reason: str,
    ) -> str:
        """Build a proposal, route through approval + memory + event bus.

        Returns the opaque ``approval_id`` from
        :meth:`ApprovalGatewayPort.propose`. Callers await resolution via
        :class:`ApprovalResolverPort` on a later turn.

        Raises:
            ValueError: any input field is empty.
        """
        for name, value in (
            ("target_path", target_path),
            ("patch", patch),
            ("reason", reason),
        ):
            if not value or not value.strip():
                raise ValueError(
                    f"SelfImprovementProposer.propose {name!r} must be non-empty."
                )

        proposal = SelfImprovementProposal(
            proposal_id=str(uuid.uuid4()),
            experience=experience,
            target_path=target_path,
            patch=patch,
            reason=reason,
        )

        intention_id = f"tektos.self_improve.{proposal.proposal_id}"
        delta = proposal.as_delta()

        approval_id = await self._approval_gateway.propose(
            intention_id=intention_id,
            delta=delta,
            tier=ChangeApprovalTier.HUMAN_REQUIRED,
            proposing_domain=PROPOSING_DOMAIN,
            diff_preview={
                "action": "self_improvement.propose",
                "target_path": target_path,
                "reason": reason,
                "session_id": experience.session_id,
            },
        )

        await self._memory.write_event(
            subject=proposal.proposal_id,
            predicate=SELF_IMPROVEMENT_PROPOSED_PREDICATE,
            object=target_path,
            provenance=self.provenance,
            confidence=self._confidence,
            attributes={
                "approval_id": approval_id,
                "intention_id": intention_id,
                "session_id": experience.session_id,
                "task": experience.task,
                "reason": reason,
                "kind": "self_improvement",
            },
        )

        await self._event_bus.publish(
            EventEnvelope(
                event_type=SELF_IMPROVEMENT_PROPOSED_EVENT,
                producer_plugin=PROPOSING_DOMAIN,
                payload={
                    "proposal_id": proposal.proposal_id,
                    "approval_id": approval_id,
                    "intention_id": intention_id,
                    "target_path": target_path,
                    "session_id": experience.session_id,
                    "kind": "self_improvement",
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
        """Close the audit loop on a denial (ADR-095 D4).

        Called after :class:`ApprovalResolverPort` resolves the proposal
        with ``approved=False``. Writes a second ``MemoryPort`` triple so
        the denial is as observable as the proposal.
        """
        await self._memory.write_event(
            subject=proposal_id,
            predicate=SELF_IMPROVEMENT_DENIED_PREDICATE,
            object=target_path,
            provenance=self.provenance,
            confidence=self._confidence,
            attributes={
                "approval_id": approval_id,
                "denial_reason": reason,
                "kind": "self_improvement",
            },
        )

    async def apply(self, approval_id: str) -> NoReturn:
        """Never returns — physically cannot apply (ADR-090 not ratified).

        Belt-and-suspenders on top of the approval-gate deny path: even if
        a caller bypasses the gate, this method cannot mutate the
        filesystem because it has no implementation.
        """
        raise NotImplementedError(
            "SelfImprovementProposer.apply is unavailable until ADR-090 "
            "(SelfModificationPort) ratifies. Stage 5.6 is propose-only "
            "per ADR-095 D2 + ADR-090 interim rule 4. "
            f"(approval_id={approval_id!r})"
        )


__all__ = [
    "DEFAULT_SELF_MODIFICATION_CONFIDENCE",
    "PROPOSING_DOMAIN",
    "SELF_IMPROVEMENT_DENIED_PREDICATE",
    "SELF_IMPROVEMENT_PROPOSED_EVENT",
    "SELF_IMPROVEMENT_PROPOSED_PREDICATE",
    "SELF_MODIFICATION_CONFIDENCE_CEILING",
    "SELF_MODIFICATION_PROVENANCE",
    "SelfImprovementProposal",
    "SelfImprovementProposer",
]
