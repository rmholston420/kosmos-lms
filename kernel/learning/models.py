"""Tektos self-improvement data models (donor-faithful).

Moved from ``adapters/tektos/vendor/self_improve_models_donor.py`` to the
kernel learning substrate (ADR-143, T3). The model is pure data +
serializers — no behavior — so it is vendor-faithful byte-for-byte.

Donor provenance: tektos-ultima-v1 ``src/tektos/self_improvement/engine.py``
(``ExperienceRecord``, upstream commit 2b45cac, vendored Stage 5.6 /
ADR-095).

ADR-143 layering: the *data* model of the self-improvement ledger is
shared-infrastructure shape (the ledger, its metrics and report consume
it), so it lives in the kernel. The vendor file now re-exports this
class so the Stage 5.6 proposer keeps its import path unchanged.
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
    self-improvement loop. The Stage 5.6 proposer serializes this into
    the approval delta; ADR-143 (T3) wires it into the kernel learning
    substrate's JSONL ledger.
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
    def from_dict(cls, data: dict[str, Any]) -> "ExperienceRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


__all__ = ["ExperienceRecord"]
