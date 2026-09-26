"""Tektos-Ultima-v1 — Skill Manager

Orchestrates skill creation, selection, and execution.

Responsibilities:
  1. Create skills from reflection output or user input
  2. Match skills to current context via trigger conditions
  3. Execute matched skills in priority order
  4. Track usage and effectiveness
  5. Archive/delete ineffective skills
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .registry import Skill, SkillRegistry

log = logging.getLogger("tektos.skill_manager")


# ── Skill Selection ─────────────────────────────────────────────────────────


class SkillMatch:
    """A skill matched to the current context."""

    def __init__(self, skill: Skill, score: float, reason: str = "") -> None:
        self.skill = skill
        self.score = score
        self.reason = reason


class SkillSelectionResult:
    """Result of skill selection for a given context."""

    def __init__(self) -> None:
        self.matches: list[SkillMatch] = []
        self.executed: list[Skill] = []
        self.failed: list[Skill] = []

    @property
    def has_matches(self) -> bool:
        return len(self.matches) > 0

    @property
    def has_executed(self) -> bool:
        return len(self.executed) > 0


# ── Skill Manager ───────────────────────────────────────────────────────────


class SkillManager:
    """Orchestrates the full skill lifecycle.

    Attributes:
        registry: The skill registry for persistence.
        skill_dir: Directory where SKILL.md files are stored.
        max_active_skills: Maximum number of active skills (default 100).
        min_success_rate: Minimum success rate to keep a skill active (default 0.3).
    """

    def __init__(
        self,
        registry: SkillRegistry,
        skill_dir: str | Path | None = None,
        max_active_skills: int = 100,
        min_success_rate: float = 0.3,
        tool_registry: Any = None,
        memory_system: Any = None,
    ) -> None:
        self.registry = registry
        self.skill_dir = Path(skill_dir or str(Path.home() / ".tektos/skills/"))
        self.skill_dir.mkdir(parents=True, exist_ok=True)
        self.max_active_skills = max_active_skills
        self.min_success_rate = min_success_rate
        #: Optional ToolRegistry used as the fallback dispatch target for
        #: unknown skill-step actions in :meth:`_execute_inline`. Injected
        #: from ``main.lifespan()``; None-safe for tests.
        self._tool_registry: Any = tool_registry
        #: Optional memory system (donor: ``tektos.main.memory_system``) used
        #: by the ``apply_lesson`` / ``apply_recommendation`` / pattern steps
        #: in :meth:`_execute_inline`. Donor resolved it via
        #: ``import tektos.main``; the kernel (ADR-007) injects it instead —
        #: the composition root wires ``registry.tektos_memory_persistence``
        #: through a two-method adapter (``add_procedural_memory`` /
        #: ``add_working_memory``); None-safe (no-op when unwired).
        self._memory_system: Any = memory_system

    def set_tool_registry(self, tool_registry: Any) -> None:
        """Inject a ToolRegistry post-construction (used from lifespan)."""
        self._tool_registry = tool_registry

    def set_memory_system(self, memory_system: Any) -> None:
        """Inject a memory system post-construction (composition root)."""
        self._memory_system = memory_system

    # ── Creation ─────────────────────────────────────────────────────────

    def create_skill(
        self,
        name: str,
        description: str,
        trigger_conditions: list[str],
        steps: list[dict[str, Any]],
        category: str = "",
        source: str = "agent_discovered",
        metadata: dict[str, Any] | None = None,
    ) -> Skill:
        """Create a new skill.

        Args:
            name: Unique skill name.
            description: What the skill does.
            trigger_conditions: Conditions that should trigger this skill.
            steps: Ordered list of steps to execute.
            category: Skill category for organization.
            source: Origin of the skill.
            metadata: Additional metadata.

        Returns:
            The created Skill.

        Raises:
            ValueError: If a skill with this name already exists.
        """
        existing = self.registry.get_by_name(name)
        if existing is not None:
            log.warning("Skill %s already exists — updating instead", name)
            existing.description = description
            existing.trigger_conditions = trigger_conditions
            existing.steps = steps
            existing.category = category or existing.category
            existing.metadata = metadata or existing.metadata
            return self.registry.update(existing)

        skill = Skill(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            trigger_conditions=trigger_conditions,
            steps=steps,
            category=category,
            source=source,
            metadata=metadata or {},
        )
        return self.registry.create(skill)

    def create_skill_from_reflection(
        self,
        lessons: list[str],
        what_worked: list[str],
        what_failed: list[str],
        what_to_avoid: list[str],
        recommendations: list[str],
        category: str = "self_improvement",
    ) -> list[Skill]:
        """Create skills from self-improvement reflection output.

        This is the public API called by SelfImprovementAdapter.
        Delegates to the internal _create_from_reflection method.
        """
        return self._create_from_reflection(
            lessons=lessons,
            what_worked=what_worked,
            what_failed=what_failed,
            what_to_avoid=what_to_avoid,
            recommendations=recommendations,
            category=category,
        )

    def _create_from_reflection(
        self,
        lessons: list[str],
        what_worked: list[str],
        what_failed: list[str],
        what_to_avoid: list[str],
        recommendations: list[str],
        category: str = "self_improvement",
    ) -> list[Skill]:
        """Create skills from self-improvement reflection output.

        Analyzes lessons and recommendations to identify reusable patterns,
        then creates skills for the most valuable ones.

        Args:
            lessons: Generalizable lessons from reflection.
            what_worked: Things that worked well.
            what_failed: Things that failed.
            what_to_avoid: Things to avoid in the future.
            recommendations: Recommendations for improvement.
            category: Category for created skills.

        Returns:
            List of created skills.
        """
        created: list[Skill] = []

        # Convert lessons to skills
        for lesson in lessons:
            skill = self._lesson_to_skill(lesson, category, source="self_improvement")
            if skill:
                created.append(skill)

        # Convert recommendations to skills
        for rec in recommendations:
            skill = self._recommendation_to_skill(rec, category, source="self_improvement")
            if skill:
                created.append(skill)

        # Convert "what worked" patterns to skills
        for worked in what_worked:
            skill = self._pattern_to_skill(
                worked, "success_pattern", category, source="self_improvement"
            )
            if skill:
                created.append(skill)

        # Convert "what to avoid" to warning skills
        for avoid in what_to_avoid:
            skill = self._pattern_to_skill(
                avoid, "anti_pattern", category, source="self_improvement"
            )
            if skill:
                created.append(skill)

        log.info("Created %d skills from reflection", len(created))
        return created

    def _lesson_to_skill(
        self,
        lesson: str,
        category: str,
        source: str = "agent_discovered",
    ) -> Skill | None:
        """Convert a lesson into a skill and persist it."""
        # Extract a concise name from the lesson
        name = self._extract_skill_name(lesson)
        if not name:
            return None

        # Check if a skill with this name already exists
        existing = self.registry.get_by_name(name)
        if existing:
            return None

        skill = Skill(
            id=str(uuid.uuid4()),
            name=name,
            description=lesson,
            trigger_conditions=[f"lesson: {name}"],
            steps=[
                {
                    "action": "apply_lesson",
                    "description": lesson,
                }
            ],
            category=category,
            source=source,
        )
        return self.registry.create(skill)

    def _recommendation_to_skill(
        self,
        rec: str,
        category: str,
        source: str = "agent_discovered",
    ) -> Skill | None:
        """Convert a recommendation into a skill and persist it."""
        name = self._extract_skill_name(rec)
        if not name:
            return None

        existing = self.registry.get_by_name(name)
        if existing:
            return None

        skill = Skill(
            id=str(uuid.uuid4()),
            name=name,
            description=rec,
            trigger_conditions=[f"recommendation: {name}"],
            steps=[
                {
                    "action": "apply_recommendation",
                    "description": rec,
                }
            ],
            category=category,
            source=source,
        )
        return self.registry.create(skill)

    def _pattern_to_skill(
        self,
        pattern: str,
        pattern_type: str,
        category: str,
        source: str = "agent_discovered",
    ) -> Skill | None:
        """Convert a pattern (success or anti-pattern) into a skill and persist it."""
        name = self._extract_skill_name(pattern)
        if not name:
            return None

        existing = self.registry.get_by_name(name)
        if existing:
            return None

        skill = Skill(
            id=str(uuid.uuid4()),
            name=f"{pattern_type}_{name}",
            description=f"{pattern_type}: {pattern}",
            trigger_conditions=[f"{pattern_type}: {name}"],
            steps=[
                {
                    "action": f"apply_{pattern_type}",
                    "description": pattern,
                }
            ],
            category=category,
            source=source,
        )
        return self.registry.create(skill)

    def _extract_skill_name(self, text: str) -> str | None:
        """Extract a concise skill name from a lesson/recommendation text."""
        # Take first 50 chars, remove special chars, make slug
        import re

        name = text[:50].strip()
        name = re.sub(r"[^a-zA-Z0-9\s]", "", name)
        name = re.sub(r"\s+", "_", name).lower()
        name = name[:40]  # Max 40 chars
        if not name:
            return None
        return name

    # ── Selection ────────────────────────────────────────────────────────

    def select_skills(
        self,
        context: dict[str, Any],
        max_skills: int = 5,
    ) -> SkillSelectionResult:
        """Select skills that match the current context.

        Args:
            context: Current session context (task, tools, errors, etc.).
            max_skills: Maximum number of skills to return.

        Returns:
            SkillSelectionResult with matched skills.
        """
        result = SkillSelectionResult()

        # Get all active skills
        all_skills = self.registry.list_skills(active_only=True)

        # Score each skill against the context
        for skill in all_skills:
            score = self._score_skill_against_context(skill, context)
            if score > 0:
                result.matches.append(SkillMatch(skill=skill, score=score))

        # Sort by score descending
        result.matches.sort(key=lambda m: m.score, reverse=True)

        # Take top N
        result.matches = result.matches[:max_skills]

        log.info(
            "Selected %d skills for context (from %d total)", len(result.matches), len(all_skills)
        )
        return result

    def _score_skill_against_context(
        self,
        skill: Skill,
        context: dict[str, Any],
    ) -> float:
        """Score a skill against the current context.

        Scoring factors:
        - Trigger condition matches (highest weight)
        - Category relevance
        - Success rate (prefer reliable skills)
        - Usage count (prefer proven skills)
        """
        score = 0.0

        # Build context text for matching
        context_text = json.dumps(context).lower()

        # Check trigger conditions
        for trigger in skill.trigger_conditions:
            trigger_lower = trigger.lower()
            if trigger_lower in context_text:
                score += 10.0  # High weight for trigger match

        # Category relevance
        task_type = context.get("task_type", "")
        if task_type and task_type.lower() in skill.category.lower():
            score += 5.0

        # Success rate bonus
        if skill.success_rate > 0.5:
            score += skill.success_rate * 3.0

        # Usage count bonus (diminishing returns)
        if skill.usage_count > 0:
            score += min(skill.usage_count * 0.5, 5.0)

        return score

    # ── Execution ────────────────────────────────────────────────────────

    async def execute_selected(
        self,
        context: dict[str, Any],
        executor: Any = None,
    ) -> SkillSelectionResult:
        """Select and execute matching skills.

        Args:
            context: Current session context.
            executor: SkillExecutor instance. If None, uses inline execution.

        Returns:
            SkillSelectionResult with execution results.
        """
        result = self.select_skills(context)

        for match in result.matches:
            skill = match.skill
            try:
                if executor:
                    await executor.execute(skill, context)
                else:
                    await self._execute_inline(skill, context)
                result.executed.append(skill)
                self.registry.record_usage(skill.id, success=True)
                log.info("Executed skill: %s (score=%.1f)", skill.name, match.score)
            except Exception as e:
                result.failed.append(skill)
                self.registry.record_usage(skill.id, success=False)
                log.warning("Failed to execute skill %s: %s", skill.name, e)

        return result

    async def _execute_inline(
        self,
        skill: Skill,
        context: dict[str, Any],
    ) -> None:
        """Execute a skill's steps inline (without a dedicated executor).

        This is the fallback execution path for simple skills.
        For complex skills, use a SkillExecutor.
        """
        for step in skill.steps:
            action = step.get("action", step.get("type", "noop"))
            description = step.get("description", "")

            log.info("[SKILL:%s] Executing step: %s — %s", skill.name, action, description)

            # For now, log the step. Real execution would dispatch to tools.
            if action == "apply_lesson":
                # Store lesson in procedural memory
                self._store_in_procedural_memory(description, skill)
            elif action == "apply_recommendation":
                # Store recommendation in working memory for immediate use
                self._store_in_working_memory(description, skill)
            elif action == "apply_success_pattern":
                # Store pattern for future reference
                self._store_in_procedural_memory(description, skill)
            elif action == "apply_anti_pattern":
                # Store warning in working memory
                self._store_in_working_memory(f"AVOID: {description}", skill)
            else:
                # Unknown action — try the injected ToolRegistry as a
                # fallback dispatch target before giving up. Skill steps
                # can therefore call arbitrary registered tools (bash,
                # file_write, ...) by naming the action after the tool.
                dispatched = False
                tr = self._tool_registry
                if tr is not None:
                    dispatch = getattr(tr, "dispatch", None) or getattr(
                        tr, "execute", None
                    )
                    if callable(dispatch):
                        try:
                            tool_input = step.get("input") or step.get("args") or {}
                            dispatch(action, tool_input)
                            dispatched = True
                            log.info(
                                "[SKILL:%s] Dispatched unknown action '%s' to ToolRegistry",
                                skill.name,
                                action,
                            )
                        except Exception as exc:
                            log.warning(
                                "[SKILL:%s] ToolRegistry dispatch failed for '%s': %s",
                                skill.name,
                                action,
                                exc,
                            )
                if not dispatched:
                    log.debug("[SKILL:%s] Unknown action: %s", skill.name, action)

    def _store_in_procedural_memory(self, content: str, skill: Skill) -> None:
        """Store content in procedural memory via the memory system."""
        try:
            # Donor resolved this lazily via ``import tektos.main``;
            # the kernel injects it (ADR-007 — substrate never imports
            # the app or plugins). No-op when the seam is unwired.
            ms = self._memory_system
            if ms:
                ms.add_procedural_memory(
                    content=f"[Skill:{skill.name}] {content}",
                    metadata={"skill_id": skill.id, "skill_name": skill.name},
                )
        except Exception as e:
            log.warning("Failed to store in procedural memory: %s", e)

    def _store_in_working_memory(self, content: str, skill: Skill) -> None:
        """Store content in working memory via the memory system."""
        try:
            ms = self._memory_system
            if ms:
                ms.add_working_memory(
                    content=f"[Skill:{skill.name}] {content}",
                    metadata={"skill_id": skill.id, "skill_name": skill.name},
                )
        except Exception as e:
            log.warning("Failed to store in working memory: %s", e)

    # ── Maintenance ──────────────────────────────────────────────────────

    def prune_inactive_skills(self) -> int:
        """Archive skills that have fallen below the success rate threshold.

        Returns:
            Number of skills archived.
        """
        all_skills = self.registry.list_skills(active_only=False)
        archived = 0

        for skill in all_skills:
            if not skill.is_active:
                continue
            if skill.total_runs >= 5 and skill.success_rate < self.min_success_rate:
                skill.is_active = False
                self.registry.update(skill)
                archived += 1
                log.info(
                    "Archived low-performing skill: %s (success_rate=%.1f, runs=%d)",
                    skill.name,
                    skill.success_rate,
                    skill.total_runs,
                )

        # Enforce max active skills
        active = self.registry.list_skills(active_only=True)
        if len(active) > self.max_active_skills:
            # Sort by success_rate then usage_count, deactivate the worst
            active.sort(key=lambda s: (s.success_rate, s.usage_count))
            to_deactivate = active[: len(active) - self.max_active_skills]
            for skill in to_deactivate:
                skill.is_active = False
                self.registry.update(skill)
                archived += 1

        if archived > 0:
            log.info("Pruned %d inactive/low-performing skills", archived)
        return archived

    def get_stats(self) -> dict[str, Any]:
        """Get skill system statistics."""
        all_skills = self.registry.list_skills(active_only=False)
        active = self.registry.list_skills(active_only=True)
        top = self.registry.get_top_skills(limit=5)

        return {
            "total_skills": len(all_skills),
            "active_skills": len(active),
            "top_skills": [
                {
                    "name": s.name,
                    "category": s.category,
                    "usage_count": s.usage_count,
                    "success_rate": round(s.success_rate, 3),
                }
                for s in top
            ],
            "categories": list(set(s.category for s in all_skills if s.category)),
        }

    # ── Deduplication ────────────────────────────────────────────────────

    def find_duplicate_groups(
        self,
        similarity_threshold: float = 0.6,
    ) -> list[dict[str, Any]]:
        """Find groups of semantically similar skills.

        Args:
            similarity_threshold: Minimum similarity (0.0-1.0) to consider duplicates.

        Returns:
            List of duplicate groups with primary, duplicates, and similarity score.
        """
        return self.registry.find_duplicates(
            similarity_threshold=similarity_threshold,
            active_only=True,
        )

    def deduplicate(
        self,
        similarity_threshold: float = 0.6,
    ) -> dict[str, int]:
        """Find and merge duplicate skills.

        Args:
            similarity_threshold: Minimum similarity to consider merging.

        Returns:
            Dict with counts: merged, deleted, kept.
        """
        groups = self.registry.find_duplicates(
            similarity_threshold=similarity_threshold,
            active_only=True,
        )
        if not groups:
            log.info("No duplicate skills found")
            return {"merged": 0, "deleted": 0, "kept": 0}

        stats = self.registry.merge_duplicates(groups)
        log.info(
            "Deduplicated: merged=%d, deleted=%d, kept=%d",
            stats["merged"],
            stats["deleted"],
            stats["kept"],
        )
        return stats

    # ── Improvement ──────────────────────────────────────────────────────

    def improve_skill(
        self,
        skill_id: str,
        new_description: str | None = None,
        new_steps: list[dict[str, Any]] | None = None,
        new_triggers: list[str] | None = None,
        improvement_note: str = "",
        metadata_updates: dict[str, Any] | None = None,
    ) -> Skill | None:
        """Improve a skill by updating its description, steps, or triggers.

        Args:
            skill_id: The skill to improve.
            new_description: Updated description.
            new_steps: Updated steps list.
            new_triggers: Updated trigger conditions.
            improvement_note: Why this improvement was made.
            metadata_updates: Additional metadata to merge.

        Returns:
            The improved skill, or None if not found.
        """
        return self.registry.improve_skill(
            skill_id=skill_id,
            new_description=new_description,
            new_steps=new_steps,
            new_triggers=new_triggers,
            improvement_note=improvement_note,
            metadata_updates=metadata_updates,
        )

    def improve_from_execution(
        self,
        skill_id: str,
        execution_result: dict[str, Any],
    ) -> Skill | None:
        """Improve a skill based on its execution result.

        Analyzes execution output to:
        - Add successful patterns to metadata
        - Record failure patterns for review
        - Track improvement history with version bumping

        Args:
            skill_id: The skill that was executed.
            execution_result: Result from SkillExecutor.execute().

        Returns:
            The improved skill, or None if not found.
        """
        return self.registry.improve_from_execution(skill_id, execution_result)

    def improve_from_reflection(
        self,
        skill_id: str,
        lessons: list[str],
        what_worked: list[str],
        what_failed: list[str],
        what_to_avoid: list[str],
    ) -> Skill | None:
        """Improve an existing skill based on reflection output.

        Uses reflection insights to:
        - Enrich the skill's description with lessons learned
        - Add successful patterns as new steps
        - Remove or flag failed patterns
        - Update trigger conditions based on what actually triggered success

        Args:
            skill_id: The skill to improve.
            lessons: Generalizable lessons from reflection.
            what_worked: Things that worked well.
            what_failed: Things that failed.
            what_to_avoid: Things to avoid in the future.

        Returns:
            The improved skill, or None if not found.
        """
        skill = self.registry.get_by_id(skill_id)
        if skill is None:
            return None

        improvements = []

        # Enrich description with lessons
        if lessons:
            skill.description = f"{skill.description}\n\nLessons: {'; '.join(lessons[:3])}"
            improvements.append(f"Added {len(lessons)} lesson(s) to description")

        # Add successful patterns as new steps
        if what_worked:
            for worked in what_worked:
                # Check if this pattern already exists in steps
                existing = [
                    s for s in skill.steps if worked.lower() in s.get("description", "").lower()
                ]
                if not existing:
                    skill.steps.append(
                        {
                            "action": "apply_success_pattern",
                            "description": worked,
                        }
                    )
                    improvements.append(f"Added success pattern: {worked[:50]}")

        # Flag failed patterns for review
        if what_failed:
            skill.metadata.setdefault("lessons_learned", [])
            for failed in what_failed:
                skill.metadata["lessons_learned"].append(
                    {
                        "lesson": failed,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            improvements.append(f"Recorded {len(what_failed)} failure lesson(s)")

        # Update trigger conditions based on what worked
        if what_worked and skill.trigger_conditions:
            # Add more specific triggers based on successful patterns
            for worked in what_worked[:2]:
                trigger = f"pattern: {worked[:30]}"
                if trigger not in skill.trigger_conditions:
                    skill.trigger_conditions.append(trigger)
            improvements.append("Refined trigger conditions")

        # Update improvement history
        if "improvement_history" not in skill.metadata:
            skill.metadata["improvement_history"] = []
        skill.metadata["improvement_history"].append(
            {
                "improved_at": datetime.now(timezone.utc).isoformat(),
                "note": f"Improved from reflection: {len(improvements)} changes",
                "version_before": skill.version,
                "changes": improvements,
            }
        )

        skill.version = self.registry._bump_version(skill.version)
        skill.updated_at = datetime.now(timezone.utc).isoformat()

        return self.registry.update(skill)

    def run_maintenance(self) -> dict[str, Any]:
        """Run full skill maintenance: dedup, prune, and improve.

        This is the main maintenance entry point, called periodically
        or after significant skill accumulation.

        Returns:
            Dict with maintenance results.
        """
        results = {
            "dedup": {},
            "prune": {},
            "improvements": 0,
        }

        # 1. Deduplicate
        results["dedup"] = self.deduplicate(similarity_threshold=0.6)

        # 2. Prune inactive/low-performing skills
        results["prune"]["archived"] = self.prune_inactive_skills()

        # 3. Improve skills that have execution data but no improvements yet
        all_skills = self.registry.list_skills(active_only=True)
        for skill in all_skills:
            # Check if skill has failure patterns but no improvement history
            has_failures = skill.metadata.get("failure_patterns")
            has_improvements = skill.metadata.get("improvement_history")
            if has_failures and not has_improvements:
                # Auto-improve based on failure patterns
                failures = has_failures[:3]  # Limit to recent failures
                self.improve_skill(
                    skill_id=skill.id,
                    improvement_note=f"Auto-improved from {len(failures)} failure(s)",
                    metadata_updates={"auto_improved": True},
                )
                results["improvements"] += 1

        log.info(
            "Skill maintenance complete: dedup=%s, prune=%s, improvements=%d",
            results["dedup"],
            results["prune"],
            results["improvements"],
        )
        return results
