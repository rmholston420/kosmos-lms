"""Tektos self-improvement plugin (ADR-095 proposer + ADR-143 loop).

Two surfaces:

* :class:`SelfImprovementProposer` (ADR-095, Stage 5.6) — the older
  propose-only path gated by ApprovalPort; ``apply()`` physically
  cannot mutate the filesystem until ADR-090 ratifies.
* :class:`SelfImprovementLoop` (ADR-143 T3 / S4) — the full Hegelian
  self-improvement loop (thesis → antithesis → reflection → synthesis
  → memory), adapted onto the kernel's five Tektos engines and the
  kernel learning substrate (``kernel.learning``). This is Tektos
  coding-agent POLICY: it is injected into the kernel learning driver
  (``kernel.learning.driver.LearningDriver``) at boot from the
  composition root — the substrate never imports this package
  (ADR-007).
"""

from plugins.tektos.self_improve.loop import LoopCycle, SelfImprovementLoop
from plugins.tektos.self_improve.proposer import (
    SelfImprovementProposal,
    SelfImprovementProposer,
)

__all__ = [
    "LoopCycle",
    "SelfImprovementLoop",
    "SelfImprovementProposal",
    "SelfImprovementProposer",
]
