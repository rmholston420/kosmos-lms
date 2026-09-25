"""plugins.tektos.orchestrator — Tektos multi-agent orchestration (Stage 8.7 · ADR-114).

Sixth Tektos engine subpackage under ``plugins/tektos/`` (after reflection,
synthesis, experience, planner, executor, manager), landing three sibling
engines per ADR-114 D1:

* ``TektosOrchestrator`` — multi-agent task orchestration (donor
  ``runtime/multi_agent_orchestrator.py`` rewritten per ADR-114 D2):
  lifecycle + keyword capability matching + reconcile preserved verbatim;
  real-tool dispatch rerouted from ``subprocess.run(shell=True)`` to
  ``SandboxPort.run`` (R1); ``execute_parallel`` is a true
  ``asyncio.gather`` under a semaphore; failed tasks consult
  ``plugins.tektos.manager.classify_recovery`` (ADR-107 D9 discharge).
* ``TektosHierarchicalAgent`` — six-role hierarchical execution (donor
  ``runtime/hierarchical_agent.py`` rewritten per ADR-114 D2): role
  handlers call ``LLMPort.chat`` when bound; donor template strings are
  the verbatim deterministic unwired fallback.
* ``TektosLongRunningAgent`` — checkpoint/resume + heartbeats (donor
  ``runtime/long_running_agent.py`` rewritten per ADR-114 D2): persistence
  through ``RelationalMemoryPort.record_event`` (R3); ring-buffer
  fallback (ADR-101).

ADR-007: this module imports only from ``ports.*`` and its own subpackage
(plus the same-repo ``plugins.tektos.manager`` classifier at call time,
per ADR-114 D6 — module-level import only, no boot-order coupling).
"""

from __future__ import annotations

# Locked constants (ADR-114 D4) ────────────────────────────────────────────
# Single source of truth. Every write / publish / record call reads HERE.

TEKTOS_ORCHESTRATOR_PROVENANCE: str = "tektos.orchestrator"
"""Locked ``MemoryPort``/``RelationalMemoryPort`` provenance (ADR-008)."""

TEKTOS_ORCHESTRATOR_PREDICATE: str = "tektos.orchestrator.task_completed"
"""Locked event kind + narrative title prefix (ADR-023)."""

TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE: float = 0.75
"""Pre-Reflexion default confidence (ADR-036 · mirrors ADR-105/106/107/108)."""

# Locked ancillary event kinds (ADR-114 D7) — envelope-first per ADR-023.
TEKTOS_ORCHESTRATOR_EVENT_BATCH: str = "tektos.orchestrator.batch_completed"
TEKTOS_ORCHESTRATOR_EVENT_ROLE: str = "tektos.hierarchical.role_completed"

# Locked record kinds for the long-running engine (ADR-114 D3).
TEKTOS_LONG_RUNNING_CHECKPOINT_KIND: str = "tektos.long_running.checkpoint"
TEKTOS_LONG_RUNNING_HEARTBEAT_KIND: str = "tektos.long_running.heartbeat"


from .models import (  # noqa: E402
    AgentCheckpoint,
    AgentProgress,
    AgentResult,
    AgentRole,
    AgentTask,
    HierRole,
    LongRunningState,
    OrchestrationResult,
    Subagent,
    Task,
    TaskStatus,
)
from .engine import OrchestratorBundle, TektosOrchestrator  # noqa: E402
from .hierarchical import TektosHierarchicalAgent  # noqa: E402
from .long_running import TektosLongRunningAgent  # noqa: E402

__all__ = [
    "AgentCheckpoint",
    "AgentProgress",
    "AgentResult",
    "AgentRole",
    "AgentTask",
    "HierRole",
    "LongRunningState",
    "OrchestrationResult",
    "Subagent",
    "Task",
    "TaskStatus",
    "TEKTOS_LONG_RUNNING_CHECKPOINT_KIND",
    "TEKTOS_LONG_RUNNING_HEARTBEAT_KIND",
    "TEKTOS_ORCHESTRATOR_DEFAULT_CONFIDENCE",
    "TEKTOS_ORCHESTRATOR_EVENT_BATCH",
    "TEKTOS_ORCHESTRATOR_EVENT_ROLE",
    "TEKTOS_ORCHESTRATOR_PREDICATE",
    "TEKTOS_ORCHESTRATOR_PROVENANCE",
    "OrchestratorBundle",
    "TektosHierarchicalAgent",
    "TektosLongRunningAgent",
    "TektosOrchestrator",
]
