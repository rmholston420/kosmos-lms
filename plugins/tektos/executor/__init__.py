"""plugins.tektos.executor — Tektos spec-executor + tool-router helpers (Stage 8.5 · ADR-107).

Two sibling engines land under this package (ADR-107 D1):

* ``TektosSpecExecutor`` — consumes a Stage 8.4 :class:`BuildSpec` and produces
  an :class:`ExecutionRecord` via the donor's deterministic scaffold heuristics
  (preserved verbatim per ADR-107 D2). Optional ``SandboxPort`` used for the
  pytest + ruff quality gates; when unwired, the executor falls open to a
  ``sandbox_unavailable`` status per ADR-107 D9.
* ``TektosToolRouter`` — routes a ``SubTask.tools_needed`` tuple (from the
  Stage 8.4 :class:`DecompositionPlan`) to a :class:`ToolRoute` naming the
  chosen port + argument shape. Routing only at 8.5; execution + recovery
  deferred to Stage 8.6 per ADR-107 D9.

Both engines persist through ``RelationalMemoryPort.write_narrative`` with an
in-process ring-buffer fallback (ADR-107 D3). ADR-007: only ``ports.*`` + own
subpackage imports.
"""

from __future__ import annotations

# Locked constants (ADR-107 D4) ────────────────────────────────────────────
# Every constant is duplicated on the module *and* re-exported from the
# corresponding engine.py for downstream import ergonomics; the values live
# HERE so ADR-107 D4 has a single source of truth.

TEKTOS_EXECUTOR_PROVENANCE: str = "tektos.executor"
"""Locked ``MemoryPort`` provenance (ADR-008)."""

TEKTOS_EXECUTOR_PREDICATE: str = "tektos.executor.spec_executed"
"""Locked event kind + narrative title prefix (ADR-023)."""

TEKTOS_EXECUTOR_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036 · mirrors ADR-105/ADR-106)."""

TEKTOS_TOOL_ROUTER_PROVENANCE: str = "tektos.tool_router"
"""Locked ``MemoryPort`` provenance for the routing engine (ADR-008)."""

TEKTOS_TOOL_ROUTER_PREDICATE: str = "tektos.tool_router.routed"
"""Locked event kind + narrative title prefix (ADR-023)."""

TEKTOS_TOOL_ROUTER_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence."""

from .models import (  # noqa: E402
    ExecutionArtifact,
    ExecutionRecord,
    ExecutionStep,
    ExecutionTestReport,
    ToolRoute,
)
from .engine import TektosSpecExecutor, TektosToolRouter  # noqa: E402

__all__ = [
    "TEKTOS_EXECUTOR_DEFAULT_CONFIDENCE",
    "TEKTOS_EXECUTOR_PREDICATE",
    "TEKTOS_EXECUTOR_PROVENANCE",
    "TEKTOS_TOOL_ROUTER_DEFAULT_CONFIDENCE",
    "TEKTOS_TOOL_ROUTER_PREDICATE",
    "TEKTOS_TOOL_ROUTER_PROVENANCE",
    "ExecutionArtifact",
    "ExecutionRecord",
    "ExecutionStep",
    "ExecutionTestReport",
    "TektosSpecExecutor",
    "TektosToolRouter",
    "ToolRoute",
]
