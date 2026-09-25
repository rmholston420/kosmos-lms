"""Kernel reliability substrate (ADR-142, 2026-09-25).

The shared, Tektos-agnostic self-healing substrate of Kosmos-LMS,
elevated to kernel-level infrastructure (same class as
``kernel.tektos_immune`` / ``kernel.tektos_thermal_watchdog`` /
``kernel.tektos_telemetry``) per the user's porting rule: generic
functionality goes to shared infrastructure; agent-specific
*policy* stays in the owning plugin.

Split:

* **This package (substrate):** the repair lifecycle engine
  (:mod:`~kernel.reliability.engine`), the health monitor
  (:mod:`~kernel.reliability.health_monitor`), the repair
  effectiveness tracker (:mod:`~kernel.reliability.effectiveness`),
  and the donor-fidelity data models
  (:mod:`~kernel.reliability.models`).

* **Plugin (policy):** the Tektos threat model — the 8 concrete
  repair strategies + 6 healing workflows in
  :mod:`plugins.tektos.self_repair` — is *injected* into the
  substrate at boot by the composition root (``kernel/app.py``).
  The substrate never imports plugins (ADR-007); it only depends on
  the injected registry/workflow surfaces.

Donor provenance: tektos-ultima-v1 ``src/tektos/self_repair/``
(7 modules, 2,465 lines) — ported verbatim under the ADR-141
functionality-preservation constraint; only the intra-package import
paths and the DI seams differ.
"""

from kernel.reliability.effectiveness import (
    RepairEffectivenessTracker,
    get_effectiveness_tracker,
    reset_effectiveness_tracker,
)
from kernel.reliability.engine import (
    SelfRepairEngine,
    get_self_repair_engine,
    reset_self_repair_engine,
)
from kernel.reliability.health_monitor import (
    HealthMonitor,
    get_health_monitor,
    reset_health_monitor,
)
from kernel.reliability.models import (
    DegradationLevel,
    DegradationPlan,
    HealthSnapshot,
    RepairRecord,
    RepairResult,
    RepairStatus,
    RepairStrategy,
)

__all__ = [
    "DegradationLevel",
    "DegradationPlan",
    "HealthMonitor",
    "HealthSnapshot",
    "RepairEffectivenessTracker",
    "RepairRecord",
    "RepairResult",
    "RepairStatus",
    "RepairStrategy",
    "SelfRepairEngine",
    "get_effectiveness_tracker",
    "get_health_monitor",
    "get_self_repair_engine",
    "reset_effectiveness_tracker",
    "reset_health_monitor",
    "reset_self_repair_engine",
]
