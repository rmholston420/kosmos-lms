# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/self_repair/models.py
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole copyright).
#
# Kosmos modifications (ADR-095):
# 1. Vendored ONLY the pure-data primitives (RepairStatus, RepairStrategy,
#    DegradationLevel enums + RepairRecord dataclass). No orchestration classes.
# 2. Dropped RepairResult, HealthSnapshot, DegradationPlan (all coupled to
#    the SelfRepairEngine orchestrator which is intentionally NOT ported —
#    see ADR-095 D1).
# 3. Retained to_dict/from_dict serializers unchanged (pure data).
# 4. Restated docstrings to reference ADR-095 interim scope.
"""Vendored donor primitives for Tektos self-repair (data model only).

Ported into kosmos-lms with intentional scope reduction per ADR-095: the
engine, strategy registry, workflows, health monitor, and effectiveness
tracker from the donor package are NOT ported in Stage 5.6 because they
carry apply paths (APPLY_PATCH, RESTART_SERVICE, CLEAR_CACHE, FREE_VRAM,
etc.) that violate ADR-090 interim rule 4 ("no filesystem mutation until
ADR-090 ratifies").

Only these pure-data primitives land in Stage 5.6. They exist so:
- The Stage-5.6 SelfRepairProposer can build proposal deltas using the
  stable donor enum vocabulary (avoids naming discontinuity when the
  engine eventually lands post-ADR-090).
- Future Stage 7.4 (Hindsight migration) can consume RepairRecord.to_dict()
  serializations without a separate vendoring step.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RepairStatus(str, Enum):
    """Lifecycle states of a repair attempt."""

    PENDING = "pending"
    DIAGNOSING = "diagnosing"
    REPAIRING = "repairing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


class RepairStrategy(str, Enum):
    """Types of repair strategies available.

    NOTE: In Stage 5.6 these are string labels only — no strategy is
    executed. The SelfRepairProposer emits a proposal carrying one of
    these labels; execution is deferred to post-ADR-090.
    """

    # Infrastructure repairs
    RESTART_SERVICE = "restart_service"
    RELOAD_CONFIG = "reload_config"
    CLEAR_CACHE = "clear_cache"
    SWITCH_MODEL = "switch_model"
    SWITCH_PORT = "switch_port"

    # Context repairs
    COMPRESS_CONTEXT = "compress_context"
    TRUNCATE_MESSAGES = "truncate_messages"
    RESET_SESSION = "reset_session"

    # Resource repairs
    THROTTLE_WORKLOAD = "throttle_workload"
    FREE_VRAM = "free_vram"
    REDUCE_CONTEXT = "reduce_context"

    # Behavioral repairs
    RESET_STRATEGY = "reset_strategy"
    CHANGE_APPROACH = "change_approach"
    ESCALATE_TO_USER = "escalate_to_user"

    # Self-modification repairs
    APPLY_PATCH = "apply_patch"
    ROLLBACK_CODE = "rollback_code"
    UPDATE_PROMPT = "update_prompt"

    # Recovery repairs
    RECOVER_SESSION = "recover_session"
    RESTORE_STATE = "restore_state"


class DegradationLevel(str, Enum):
    """Levels of graceful degradation."""

    NONE = "none"
    REDUCED = "reduced"
    MINIMAL = "minimal"
    EMERGENCY = "emergency"


@dataclass
class RepairRecord:
    """Complete record of a repair attempt.

    Vendored verbatim from donor; used in Stage 5.6 to build the proposal
    payload but never populated with post-apply verification data (no apply
    runs until ADR-090 ratifies).
    """

    record_id: str
    threat_category: str
    threat_severity: str
    description: str
    status: RepairStatus = RepairStatus.PENDING
    strategy_used: RepairStrategy | None = None
    diagnosis: str = ""
    repair_actions: list[str] = field(default_factory=list)
    verification_passed: bool = False
    verification_details: str = ""
    time_to_diagnose_seconds: float = 0.0
    time_to_repair_seconds: float = 0.0
    time_to_verify_seconds: float = 0.0
    total_time_seconds: float = 0.0
    error: str | None = None
    rollback_applied: bool = False
    degradation_applied: DegradationLevel = DegradationLevel.NONE
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "threat_category": self.threat_category,
            "threat_severity": self.threat_severity,
            "description": self.description,
            "status": self.status.value,
            "strategy_used": self.strategy_used.value if self.strategy_used else None,
            "diagnosis": self.diagnosis,
            "repair_actions": self.repair_actions,
            "verification_passed": self.verification_passed,
            "verification_details": self.verification_details,
            "time_to_diagnose_seconds": round(self.time_to_diagnose_seconds, 2),
            "time_to_repair_seconds": round(self.time_to_repair_seconds, 2),
            "time_to_verify_seconds": round(self.time_to_verify_seconds, 2),
            "total_time_seconds": round(self.total_time_seconds, 2),
            "error": self.error,
            "rollback_applied": self.rollback_applied,
            "degradation_applied": self.degradation_applied.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepairRecord:
        return cls(
            record_id=data["record_id"],
            threat_category=data["threat_category"],
            threat_severity=data["threat_severity"],
            description=data["description"],
            status=RepairStatus(data.get("status", "pending")),
            strategy_used=(
                RepairStrategy(data["strategy_used"])
                if data.get("strategy_used")
                else None
            ),
            diagnosis=data.get("diagnosis", ""),
            repair_actions=data.get("repair_actions", []),
            verification_passed=data.get("verification_passed", False),
            verification_details=data.get("verification_details", ""),
            time_to_diagnose_seconds=data.get("time_to_diagnose_seconds", 0.0),
            time_to_repair_seconds=data.get("time_to_repair_seconds", 0.0),
            time_to_verify_seconds=data.get("time_to_verify_seconds", 0.0),
            total_time_seconds=data.get("total_time_seconds", 0.0),
            error=data.get("error"),
            rollback_applied=data.get("rollback_applied", False),
            degradation_applied=DegradationLevel(data.get("degradation_applied", "none")),
            created_at=data.get("created_at", time.time()),
            completed_at=data.get("completed_at", 0.0),
            metadata=data.get("metadata", {}),
        )


__all__ = [
    "DegradationLevel",
    "RepairRecord",
    "RepairStatus",
    "RepairStrategy",
]
