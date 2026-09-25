"""Kernel learning substrate (ADR-143, T3 — self-improvement).

The shared, Tektos-agnostic *learning* substrate of Kosmos-LMS, elevated
to kernel-level infrastructure (same class as ``kernel.reliability``) per
the user's porting rule: generic functionality goes to shared
infrastructure; agent-specific *policy* stays in the owning plugin.

Split:

* **This package (substrate):** the experience ledger + meta-learning +
  benchmark store (:mod:`~kernel.learning.engine`), the queue +
  env-gated driver scaffolding (:mod:`~kernel.learning.driver`), and the
  donor-faithful data model (:mod:`~kernel.learning.models`).

* **Plugin (policy):** the Tektos Hegelian self-improvement loop
  (thesis → antithesis → synthesis → experience-replay cycle) in
  :mod:`plugins.tektos.self_improve.loop` is *injected* into the driver
  at boot by the composition root (``kernel/app.py``). The substrate
  never imports plugins (ADR-007); unwired, the driver degrades to an
  honest ``orchestrator_ready: false`` (donor semantics — the donor
  booted with ``_self_improvement_loop_orchestrator = None`` on failure
  and its ``/status`` reported exactly that).

Donor provenance: tektos-ultima-v1 ``src/tektos/self_improvement/engine.py``
(672-line ``SelfImprovementAdapter``) + ``src/tektos/agents/self_improvement/
loop_orchestrator.py`` (275-line ``SelfImprovementLoop``) + the driver/queue
scaffolding in ``main.py:1224-1288`` — ported under the ADR-141
functionality-preservation constraint. The donor's ``openhands-ext``
optional-engine hook is retained as a fail-open try/import (the donor
shipped pure-Tektos fallback when it was absent, which is the state on
Collosus).

Donor gap closed (improvement over the donor): the donor's ledger write
paths (``on_session_completed`` / ``on_session_failed``) had ZERO callers
anywhere in the donor codebase — its read routes served a ledger nothing
ever populated. Here the plugin loop's ``record_cycle_outcome`` feeds the
substrate, so completed cycles populate the ledger and the read routes
return real data.
"""

from kernel.learning.driver import (
    ENABLED_ENV,
    INTERVAL_ENV,
    LearningDriver,
    get_learning_driver,
    reset_learning_driver,
)
from kernel.learning.engine import (
    LearningEngine,
    get_learning_engine,
    reset_learning_engine,
)
from kernel.learning.models import ExperienceRecord

__all__ = [
    "ExperienceRecord",
    "LearningEngine",
    "get_learning_engine",
    "reset_learning_engine",
    "LearningDriver",
    "get_learning_driver",
    "reset_learning_driver",
    "ENABLED_ENV",
    "INTERVAL_ENV",
]
