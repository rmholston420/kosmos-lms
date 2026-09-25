# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/self_improvement/engine.py (ExperienceRecord only)
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole copyright).
#
# Kosmos modifications (ADR-095, Stage 5.6 — ORIGINAL):
# 1. Vendored ONLY the ExperienceRecord dataclass (pure data + serializers).
#    The SelfImprovementAdapter, LoopOrchestrator, and cybernetic feedback
#    loop were NOT ported in Stage 5.6 — they carry apply paths that trigger
#    meta-learning against live infrastructure (violates ADR-090 rule 4).
# 2. Retained to_dict/to_json/from_dict serializers unchanged (pure data).
# 3. Restated module docstring to reference ADR-095 interim scope.
#
# ADR-143 (T3, 2026-09-25) — THIS REVISION:
# The model MOVED to the kernel learning substrate
# (kernel/learning/models.py). Per the user's layering rule, the *data* shape
# of the shared learning ledger is shared-infrastructure, not vendor surface —
# so it now lives in the kernel. The interim "not ported" scope of ADR-095 is
# superseded: the substrate (ledger + meta-learning + benchmark store +
# driver) is ported to kernel/learning/, and the Hegelian loop (Tektos policy)
# to plugins/tektos/self_improve/loop.py, wired via the composition root.
# This file is now a thin re-export shim so the Stage 5.6 proposer keeps its
# import path unchanged.
"""Vendored donor primitives for Tektos self-improvement (re-export shim).

The model now lives in :mod:`kernel.learning.models` (ADR-143).
"""

from kernel.learning.models import ExperienceRecord

__all__ = ["ExperienceRecord"]
