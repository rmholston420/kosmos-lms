"""Tektos self-repair plugin.

ADR-142 (2026-09-25) layering: the self-healing SUBSTRATE (engine
daemon, health monitor, effectiveness tracker, data models) lives in
the kernel at :mod:`kernel.reliability` — shared infrastructure, the
same class as ``kernel.tektos_immune`` / ``tektos_thermal_watchdog``.
This package holds the Tektos coding-agent POLICY injected into the
substrate at boot (composition root, ``kernel.app``):

* :mod:`plugins.tektos.self_repair.strategies` — the 8 concrete repair
  strategies (the Tektos threat model: what to do about each failure
  class) + :class:`RepairStrategyRegistry`.
* :mod:`plugins.tektos.self_repair.workflows` — the 6 multi-step
  healing workflows + :class:`RepairWorkflows`.
* :class:`SelfRepairProposer` (ADR-095, propose-only) — the older
  ApprovalPort-gated path; the full engine supersedes its role but the
  proposer stays for the propose-only flow.

The substrate never imports this package (ADR-007); the wiring crosses
plugin→kernel only at the composition root.
"""

from plugins.tektos.self_repair.proposer import (
    SelfRepairProposal,
    SelfRepairProposer,
)

__all__ = ["SelfRepairProposal", "SelfRepairProposer"]
