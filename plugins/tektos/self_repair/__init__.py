"""Tektos self-repair plugin (propose-only, ADR-095).

Stage 5.6 landing: propose-only self-repair path gated by ApprovalPort.
No apply path lands until ADR-090 (SelfModificationPort) ratifies.
"""

from plugins.tektos.self_repair.proposer import (
    SelfRepairProposal,
    SelfRepairProposer,
)

__all__ = ["SelfRepairProposal", "SelfRepairProposer"]
