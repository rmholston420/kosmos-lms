# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/self_improvement/engine.py (ExperienceRecord only)
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole copyright).
#
# Kosmos modifications (ADR-095):
# 1. Vendored ONLY the ExperienceRecord dataclass (pure data + serializers).
#    The SelfImprovementAdapter, LoopOrchestrator, and cybernetic feedback
#    loop are NOT ported in Stage 5.6 — they carry apply paths that trigger
#    meta-learning against live infrastructure (violates ADR-090 rule 4).
# 2. Retained to_dict/to_json/from_dict serializers unchanged (pure data).
# 3. Restated module docstring to reference ADR-095 interim scope.
"""Vendored donor primitives for Tektos self-improvement (data model only).

Ported into kosmos-lms with intentional scope reduction per ADR-095. The
donor's SelfImprovementAdapter (openhands-ext feedback loop wiring) and
LoopOrchestrator (session-lifecycle hook path) are NOT ported in Stage 5.6
because they auto-trigger self-modification on session completion and
persist experience against live meta-learning databases — both violate
ADR-090 interim rule 4.

Only ExperienceRecord lands in Stage 5.6. It is used by the
SelfImprovementProposer to serialize the "lessons learned" payload of a
proposal, and will feed the Hindsight bridge at Stage 7.4 without a
separate vendoring step.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ExperienceRecord:
    """Tektos-native experience record (subset of openhands-ext TaskRecord).

    Represents one session's outcome as a candidate lesson for the
    self-improvement loop. In Stage 5.6 the proposer serializes this into
    the approval delta but no meta-learning executes against it — that
    path unlocks post-ADR-090.
    """

    session_id: str
    task: str
    model_used: str
    success: bool
    tests_passed: int
    tests_total: int
    wall_time_seconds: float
    evaluation_score: float = 0.0
    spec_violations: list[str] = field(default_factory=list)
    code_issues: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    what_to_avoid: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    created_skills: list[str] = field(default_factory=list)
    meta_data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperienceRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


__all__ = ["ExperienceRecord"]
