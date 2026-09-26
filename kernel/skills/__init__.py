"""Tektos-Ultima-v1 — Skill System (donor `tektos/skills/` → kernel, verbatim).

ADR-108 D9 discharge (2026-09-26, post-freeze ADR): the donor's
reusable-procedure substrate — SQLite skill registry, lifecycle manager
(create/select/execute/dedup/prune/improve/maintenance), step executor —
elevated to kernel shared infrastructure per the governing layering rule
(generic machinery → kernel; coding-agent-specific policy → plugin).
None of this is Tektos threat-model policy: it is a generic
reusable-procedure store + lifecycle engine (same class as
`kernel/db_manager.py`, `kernel/metabolism.py`, `kernel/rag_retriever.py`).

Kernel seams (composition root `kernel/app.py`, substrate untouched):
- ``tool_registry``  → injected into `SkillManager` (executor fallback dispatch)
- ``memory_system``  → injected into `SkillManager` (donor resolved it via
  `import tektos.main`; ADR-007 forbids that — two-method adapter over
  `registry.tektos_memory_persistence`)
- db                 → `data/tektos_skills.db` (kernel-owned, gitignored)
"""

from .executor import ExecutionResult, SkillExecutor
from .manager import SkillManager, SkillMatch, SkillSelectionResult
from .registry import Skill, SkillRegistry

__all__ = [
    "ExecutionResult",
    "Skill",
    "SkillExecutor",
    "SkillManager",
    "SkillMatch",
    "SkillRegistry",
    "SkillSelectionResult",
]
