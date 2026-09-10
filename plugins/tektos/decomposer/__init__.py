"""plugins.tektos.decomposer — Tektos task decomposer (Stage 8.4 · ADR-106).

Kosmos-native rewrite of ``tektos-ultima/src/tektos/runtime/task_decomposer.py``
per ADR-106 D2. Rule-based analytic core preserved verbatim (five branch
predicates ``_is_build_task`` / ``_is_code_generation_task`` /
``_is_regex_or_pattern_task`` / ``_is_download_build_task`` / generic +
per-branch ``SubTask`` sequences). The donor's in-memory ``_plans`` dict is
replaced by persistence through ``RelationalMemoryPort.write_narrative`` with
an in-process ring-buffer fallback (ADR-106 D3).

ADR-007: only ``ports.*`` + own subpackage imports.
"""

from __future__ import annotations

TEKTOS_DECOMPOSER_PROVENANCE: str = "tektos.decomposer"
"""Locked provenance."""

TEKTOS_DECOMPOSER_PREDICATE: str = "tektos.decomposer.plan_generated"
"""Locked event kind + narrative title prefix."""

TEKTOS_DECOMPOSER_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036, mirrors ADR-105 / ADR-106)."""

from .models import DecompositionPlan, SubTask  # noqa: E402
from .engine import TaskDecomposer  # noqa: E402

__all__ = [
    "TEKTOS_DECOMPOSER_DEFAULT_CONFIDENCE",
    "TEKTOS_DECOMPOSER_PREDICATE",
    "TEKTOS_DECOMPOSER_PROVENANCE",
    "DecompositionPlan",
    "SubTask",
    "TaskDecomposer",
]
