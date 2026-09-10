"""Tektos self-improvement plugin (propose-only, ADR-095).

Stage 5.6 landing: propose-only self-improvement path gated by ApprovalPort.
No apply path lands until ADR-090 (SelfModificationPort) ratifies.
"""

from plugins.tektos.self_improve.proposer import (
    SelfImprovementProposal,
    SelfImprovementProposer,
)

__all__ = ["SelfImprovementProposal", "SelfImprovementProposer"]
