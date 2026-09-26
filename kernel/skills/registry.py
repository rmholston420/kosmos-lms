"""Tektos-Ultima-v1 — Skill Registry

SQLite-backed CRUD for the skill_registry table.
Handles skill creation, lookup, update, and deletion.

Schema (from migration v3):
    skill_registry (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        category TEXT,
        description TEXT,
        trigger_conditions TEXT DEFAULT '[]',
        steps TEXT DEFAULT '[]',
        source TEXT DEFAULT 'agent_discovered',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        version TEXT DEFAULT '0.1.0',
        is_active INTEGER DEFAULT 1,
        metadata TEXT DEFAULT '{}'
    )
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("tektos.skill_registry")


# ── Skill Data Model ────────────────────────────────────────────────────────


@dataclass
class Skill:
    """A Tektos skill — a reusable procedure with triggers and steps."""

    id: str
    name: str
    category: str = ""
    description: str = ""
    trigger_conditions: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    source: str = "agent_discovered"  # agent_discovered | user_created | self_improvement
    created_at: str = ""
    updated_at: str = ""
    version: str = "0.1.0"
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    usage_count: int = 0
    last_used: str = ""
    success_rate: float = 0.0
    total_runs: int = 0
    successful_runs: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["is_active"] = 1 if self.is_active else 0
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        data = dict(data)
        data["is_active"] = bool(data.get("is_active", True))
        # Parse JSON string fields
        tc = data.get("trigger_conditions")
        if isinstance(tc, str):
            try:
                data["trigger_conditions"] = json.loads(tc)
            except (json.JSONDecodeError, TypeError):
                data["trigger_conditions"] = []
        else:
            data.setdefault("trigger_conditions", [])
        steps = data.get("steps")
        if isinstance(steps, str):
            try:
                data["steps"] = json.loads(steps)
            except (json.JSONDecodeError, TypeError):
                data["steps"] = []
        else:
            data.setdefault("steps", [])
        meta = data.get("metadata")
        if isinstance(meta, str):
            try:
                data["metadata"] = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                data["metadata"] = {}
        else:
            data.setdefault("metadata", {})
        data.setdefault("source", "agent_discovered")
        data.setdefault("usage_count", 0)
        data.setdefault("last_used", "")
        data.setdefault("success_rate", 0.0)
        data.setdefault("total_runs", 0)
        data.setdefault("successful_runs", 0)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_skill_md(self) -> str:
        """Serialize skill to SKILL.md format for file storage."""
        lines = [
            f"# {self.name}",
            "",
            "## Description",
            self.description or "",
            "",
            "## Category",
            self.category or "general",
            "",
            "## Trigger Conditions",
        ]
        for tc in self.trigger_conditions:
            lines.append(f"- {tc}")
        lines.append("")
        lines.append("## Steps")
        for i, step in enumerate(self.steps, 1):
            action = step.get("action", step.get("type", "unknown"))
            target = step.get("target", step.get("tool", ""))
            args = step.get("args", step.get("parameters", {}))
            desc = step.get("description", "")
            lines.append(f"{i}. **{action}** {target}: {desc}")
            if args:
                lines.append(f"   - Parameters: {json.dumps(args, indent=4)}")
        lines.append("")
        lines.append("## Metadata")
        lines.append(f"- Source: {self.source}")
        lines.append(f"- Version: {self.version}")
        lines.append(f"- Created: {self.created_at}")
        lines.append(f"- Usage: {self.usage_count} times ({self.success_rate:.0%} success)")
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def from_skill_md(cls, content: str, name: str, category: str = "") -> Skill:
        """Parse a SKILL.md file into a Skill object."""
        skill = cls(id=str(uuid.uuid4()), name=name, category=category)

        sections = content.split("## ")
        for section in sections:
            if section.startswith("Description"):
                parts = section.split("\n", 1)
                if len(parts) > 1:
                    skill.description = parts[1].strip()
            elif section.startswith("Trigger Conditions"):
                for line in section.split("\n"):
                    line = line.strip()
                    if line.startswith("- "):
                        skill.trigger_conditions.append(line[2:].strip())
            elif section.startswith("Steps"):
                # Steps are parsed as numbered lines
                for line in section.split("\n"):
                    line = line.strip()
                    if line and line[0].isdigit() and ". " in line:
                        skill.steps.append(
                            {
                                "description": line.split(". ", 1)[1] if ". " in line else line,
                            }
                        )
            elif section.startswith("Metadata"):
                for line in section.split("\n"):
                    line = line.strip()
                    if line.startswith("- Source: "):
                        skill.source = line.split(": ", 1)[1].strip()
                    elif line.startswith("- Version: "):
                        skill.version = line.split(": ", 1)[1].strip()

        return skill


# ── Skill Registry ──────────────────────────────────────────────────────────


class SkillRegistry:
    """SQLite-backed skill registry.

    Provides CRUD operations for skills stored in the skill_registry table.
    Also manages SKILL.md file storage in the configured skill directory.
    """

    def __init__(self, db_path: str | Path, skill_dir: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.skill_dir = Path(skill_dir or str(Path.home() / ".tektos/skills/"))
        self.skill_dir.mkdir(parents=True, exist_ok=True)
        self._conn: Any | None = None
        self._init_db()

    def _get_conn(self) -> Any:
        """Get a SQLite connection.

        ``check_same_thread=False``: the kernel serves requests from an
        anyio worker thread (donor served same-thread, so it never needed
        this; the kernel does — TestClient + uvicorn workers both differ
        from the boot thread). Every public method is a short
        single-statement transaction; the SQLite layer serializes writers,
        so the shared connection is safe under the kernel's request
        concurrency. (Stage 14.6 seam — donor-verbatim body, one flag.)
        """
        import sqlite3

        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path), timeout=30.0, check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        """Ensure skill_registry table exists."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_registry (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                category TEXT,
                description TEXT,
                trigger_conditions TEXT DEFAULT '[]',
                steps TEXT DEFAULT '[]',
                source TEXT DEFAULT 'agent_discovered',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version TEXT DEFAULT '0.1.0',
                is_active INTEGER DEFAULT 1,
                metadata TEXT DEFAULT '{}',
                usage_count INTEGER DEFAULT 0,
                last_used TEXT DEFAULT '',
                success_rate REAL DEFAULT 0.0,
                total_runs INTEGER DEFAULT 0,
                successful_runs INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_registry_name ON skill_registry(name)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_registry_category ON skill_registry(category)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_registry_active ON skill_registry(is_active)"
        )
        conn.commit()

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create(self, skill: Skill) -> Skill:
        """Create a new skill. Returns the created skill."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        skill.updated_at = now
        skill.to_dict()
        conn.execute(
            """INSERT OR REPLACE INTO skill_registry
               (id, name, category, description, trigger_conditions, steps,
                source, created_at, updated_at, version, is_active, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                skill.id,
                skill.name,
                skill.category,
                skill.description,
                json.dumps(skill.trigger_conditions),
                json.dumps(skill.steps),
                skill.source,
                skill.created_at,
                skill.updated_at,
                skill.version,
                1 if skill.is_active else 0,
                json.dumps(skill.metadata),
            ),
        )
        conn.commit()
        # Write SKILL.md file
        self._write_skill_file(skill)
        log.info("Created skill: %s (id=%s)", skill.name, skill.id)
        return skill

    def get_by_id(self, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM skill_registry WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            return None
        return Skill.from_dict(dict(row))

    def get_by_name(self, name: str) -> Skill | None:
        """Get a skill by name."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM skill_registry WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return Skill.from_dict(dict(row))

    def update(self, skill: Skill) -> Skill:
        """Update an existing skill."""
        skill.updated_at = datetime.now(timezone.utc).isoformat()
        skill.to_dict()
        conn = self._get_conn()
        conn.execute(
            """UPDATE skill_registry SET
                name = ?, category = ?, description = ?,
                trigger_conditions = ?, steps = ?,
                updated_at = ?, version = ?, is_active = ?, metadata = ?
               WHERE id = ?""",
            (
                skill.name,
                skill.category,
                skill.description,
                json.dumps(skill.trigger_conditions),
                json.dumps(skill.steps),
                skill.updated_at,
                skill.version,
                1 if skill.is_active else 0,
                json.dumps(skill.metadata),
                skill.id,
            ),
        )
        conn.commit()
        self._write_skill_file(skill)
        log.info("Updated skill: %s", skill.name)
        return skill

    def delete(self, skill_id: str) -> bool:
        """Delete a skill. Returns True if deleted."""
        conn = self._get_conn()
        skill = self.get_by_id(skill_id)
        if skill is None:
            return False
        conn.execute("DELETE FROM skill_registry WHERE id = ?", (skill_id,))
        conn.commit()
        # Remove SKILL.md file
        self._delete_skill_file(skill)
        log.info("Deleted skill: %s", skill.name)
        return True

    def list_skills(
        self,
        active_only: bool = True,
        category: str | None = None,
        source: str | None = None,
    ) -> list[Skill]:
        """List skills with optional filters."""
        conn = self._get_conn()
        query = "SELECT * FROM skill_registry WHERE 1=1"
        params: list[Any] = []
        if active_only:
            query += " AND is_active = 1"
        if category:
            query += " AND category = ?"
            params.append(category)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY updated_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [Skill.from_dict(dict(r)) for r in rows]

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[Skill]:
        """Search skills by name, description, or trigger conditions."""
        conn = self._get_conn()
        pattern = f"%{query}%"
        rows = conn.execute(
            """SELECT * FROM skill_registry
               WHERE name LIKE ? OR description LIKE ? OR trigger_conditions LIKE ?
               ORDER BY updated_at DESC LIMIT ?""",
            (pattern, pattern, pattern, limit),
        ).fetchall()
        return [Skill.from_dict(dict(r)) for r in rows]

    # ── Usage Tracking ───────────────────────────────────────────────────

    def record_usage(self, skill_id: str, success: bool) -> None:
        """Record a skill execution result."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE skill_registry SET
                usage_count = usage_count + 1,
                last_used = ?,
                total_runs = total_runs + 1,
                successful_runs = successful_runs + ?
               WHERE id = ?""",
            (now, 1 if success else 0, skill_id),
        )
        conn.commit()
        # Recalculate success rate
        skill = self.get_by_id(skill_id)
        if skill and skill.total_runs > 0:
            skill.success_rate = skill.successful_runs / skill.total_runs
            skill.updated_at = now
            conn.execute(
                "UPDATE skill_registry SET updated_at = ?, success_rate = ? WHERE id = ?",
                (now, skill.success_rate, skill_id),
            )
            conn.commit()

    def get_top_skills(self, limit: int = 10) -> list[Skill]:
        """Get the most-used skills."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM skill_registry
               WHERE is_active = 1 AND usage_count > 0
               ORDER BY usage_count DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [Skill.from_dict(dict(r)) for r in rows]

    # ── Deduplication ────────────────────────────────────────────────────

    def find_duplicates(
        self,
        similarity_threshold: float = 0.6,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Find groups of semantically similar skills.

        Uses a heuristic similarity score based on:
        - Shared trigger conditions (exact match)
        - Shared step descriptions (substring overlap)
        - Shared category
        - Description similarity (word overlap)

        Returns a list of duplicate groups, each containing:
        - primary: the best skill to keep (highest usage + success)
        - duplicates: skills to merge into the primary
        - similarity: average similarity score
        """
        skills = self.list_skills(active_only=active_only)
        groups: list[dict[str, Any]] = []
        merged_ids: set[str] = set()

        for i, skill_a in enumerate(skills):
            if skill_a.id in merged_ids:
                continue
            group: dict[str, Any] = {
                "primary": skill_a,
                "duplicates": [],
                "similarities": [],
            }

            for j, skill_b in enumerate(skills):
                if i == j or skill_b.id in merged_ids:
                    continue
                sim = self._compute_similarity(skill_a, skill_b)
                if sim >= similarity_threshold:
                    group["duplicates"].append(skill_b)
                    group["similarities"].append(sim)

            if group["duplicates"]:
                # Pick the best skill as primary (highest usage, then highest success)
                all_in_group = [skill_a] + group["duplicates"]
                all_in_group.sort(key=lambda s: (s.usage_count, s.success_rate), reverse=True)
                group["primary"] = all_in_group[0]
                group["duplicates"] = [s for s in all_in_group[1:]]
                group["similarity"] = sum(group["similarities"]) / len(group["similarities"])
                groups.append(group)
                for dup in group["duplicates"]:
                    merged_ids.add(dup.id)

        return groups

    def _compute_similarity(self, a: Skill, b: Skill) -> float:
        """Compute semantic similarity between two skills (0.0 to 1.0)."""
        score = 0.0
        factors = 0

        # 1. Shared trigger conditions (weight: 0.35)
        triggers_a = set(a.trigger_conditions)
        triggers_b = set(b.trigger_conditions)
        if triggers_a or triggers_b:
            overlap = len(triggers_a & triggers_b)
            union = len(triggers_a | triggers_b)
            score += 0.35 * (overlap / union if union > 0 else 0)
            factors += 1

        # 2. Shared category (weight: 0.15)
        if a.category and b.category:
            score += 0.15 if a.category == b.category else 0.0
            factors += 1

        # 3. Description word overlap (weight: 0.25)
        words_a = set(a.description.lower().split())
        words_b = set(b.description.lower().split())
        if words_a or words_b:
            overlap = len(words_a & words_b)
            union = len(words_a | words_b)
            score += 0.25 * (overlap / union if union > 0 else 0)
            factors += 1

        # 4. Step overlap (weight: 0.25)
        steps_a = [s.get("description", s.get("action", "")) for s in a.steps]
        steps_b = [s.get("description", s.get("action", "")) for s in b.steps]
        if steps_a or steps_b:
            step_overlap = 0
            for sa in steps_a:
                for sb in steps_b:
                    sa_lower = sa.lower()
                    sb_lower = sb.lower()
                    if sa_lower in sb_lower or sb_lower in sa_lower:
                        step_overlap += 1
                        break
            max_steps = max(len(steps_a), len(steps_b))
            score += 0.25 * (step_overlap / max_steps if max_steps > 0 else 0)
            factors += 1

        return score

    def merge_duplicates(
        self,
        groups: list[dict[str, Any]],
        keep_primary: bool = True,
    ) -> dict[str, int]:
        """Merge duplicate skills into their primary.

        Merges:
        - Trigger conditions (union)
        - Steps (deduplicated, primary's steps first)
        - Description (primary's description, enriched with duplicates)
        - Usage stats (summed)
        - Success stats (recalculated)

        Args:
            groups: Output from find_duplicates()
            keep_primary: If True, keep the primary skill and delete duplicates.
                         If False, create a new merged skill and delete all originals.

        Returns:
            Dict with counts: merged, deleted, kept
        """
        stats = {"merged": 0, "deleted": 0, "kept": 0}

        for group in groups:
            primary = group["primary"]
            duplicates = group["duplicates"]
            if not duplicates:
                continue

            # Merge trigger conditions (union)
            merged_triggers = set(primary.trigger_conditions)
            for dup in duplicates:
                merged_triggers.update(dup.trigger_conditions)

            # Merge steps (deduplicated, primary first)
            merged_steps = list(primary.steps)
            step_keys = {json.dumps(s, sort_keys=True) for s in primary.steps}
            for dup in duplicates:
                for step in dup.steps:
                    key = json.dumps(step, sort_keys=True)
                    if key not in step_keys:
                        merged_steps.append(step)
                        step_keys.add(key)

            # Enrich description with insights from duplicates
            dup_descriptions = [d.description for d in duplicates if d.description]
            enriched_desc = primary.description
            if dup_descriptions:
                enriched_desc = (
                    f"{primary.description}\n\nMerged from: {'; '.join(dup_descriptions[:3])}"
                )

            # Merge usage stats
            total_usage = primary.usage_count
            total_runs = primary.total_runs
            total_success = primary.successful_runs
            for dup in duplicates:
                total_usage += dup.usage_count
                total_runs += dup.total_runs
                total_success += dup.successful_runs

            success_rate = total_success / total_runs if total_runs > 0 else 0.0

            # Update primary
            primary.trigger_conditions = sorted(merged_triggers)
            primary.steps = merged_steps
            primary.description = enriched_desc
            primary.usage_count = total_usage
            primary.total_runs = total_runs
            primary.successful_runs = total_success
            primary.success_rate = success_rate
            primary.updated_at = datetime.now(timezone.utc).isoformat()

            # Add merge metadata
            merged_from = [d.name for d in duplicates]
            primary.metadata["merged_from"] = merged_from
            primary.metadata["merged_at"] = primary.updated_at
            primary.metadata["merge_count"] = len(duplicates)
            primary.version = self._bump_version(primary.version)

            self.update(primary)
            stats["merged"] += 1

            # Delete duplicates
            for dup in duplicates:
                self.delete(dup.id)
                stats["deleted"] += 1

            stats["kept"] += 1

        return stats

    def _bump_version(self, version: str) -> str:
        """Bump semantic version (major.minor.patch)."""
        parts = version.split(".")
        if len(parts) == 3:
            try:
                major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                patch += 1
                return f"{major}.{minor}.{patch}"
            except ValueError:
                pass
        return version

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
        skill = self.get_by_id(skill_id)
        if skill is None:
            return None

        if new_description is not None:
            skill.description = new_description
        if new_steps is not None:
            skill.steps = new_steps
        if new_triggers is not None:
            skill.trigger_conditions = new_triggers

        # Track improvement history
        if "improvement_history" not in skill.metadata:
            skill.metadata["improvement_history"] = []
        skill.metadata["improvement_history"].append(
            {
                "improved_at": datetime.now(timezone.utc).isoformat(),
                "note": improvement_note,
                "version_before": skill.version,
            }
        )

        if metadata_updates:
            skill.metadata.update(metadata_updates)

        skill.version = self._bump_version(skill.version)
        skill.updated_at = datetime.now(timezone.utc).isoformat()

        return self.update(skill)

    def improve_from_execution(
        self,
        skill_id: str,
        execution_result: dict[str, Any],
    ) -> Skill | None:
        """Improve a skill based on its execution result.

        Analyzes execution output to:
        - Add successful patterns to steps
        - Remove or fix failed steps
        - Refine trigger conditions based on what actually triggered it
        - Update description with learned insights

        Args:
            skill_id: The skill that was executed.
            execution_result: Result from SkillExecutor.execute().

        Returns:
            The improved skill, or None if not found.
        """
        skill = self.get_by_id(skill_id)
        if skill is None:
            return None

        success = execution_result.get("success", False)
        step_results = execution_result.get("step_results", [])
        output = execution_result.get("output", "")
        error = execution_result.get("error", "")

        improvements = []

        if success:
            # Extract successful patterns from output
            if output:
                improvements.append(f"Successful execution produced: {output[:200]}")

            # Add successful step patterns to the skill
            for sr in step_results:
                if sr.get("success") and sr.get("output"):
                    skill.metadata.setdefault("successful_patterns", [])
                    skill.metadata["successful_patterns"].append(
                        {
                            "step": sr.get("action", ""),
                            "output_summary": sr["output"][:100],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )

        if error:
            # Record failure patterns
            skill.metadata.setdefault("failure_patterns", [])
            skill.metadata["failure_patterns"].append(
                {
                    "error": error[:200],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            # If a specific step failed, mark it for review
            for sr in step_results:
                if not sr.get("success"):
                    skill.metadata.setdefault("steps_needing_review", [])
                    if sr.get("action") not in skill.metadata["steps_needing_review"]:
                        skill.metadata["steps_needing_review"].append(sr.get("action", ""))

        # Update improvement history
        if "improvement_history" not in skill.metadata:
            skill.metadata["improvement_history"] = []
        skill.metadata["improvement_history"].append(
            {
                "improved_at": datetime.now(timezone.utc).isoformat(),
                "note": f"Auto-improved from execution: {'success' if success else 'failure'}",
                "version_before": skill.version,
                "success": success,
            }
        )

        skill.version = self._bump_version(skill.version)
        skill.updated_at = datetime.now(timezone.utc).isoformat()

        return self.update(skill)

    # ── File Storage ─────────────────────────────────────────────────────

    def _write_skill_file(self, skill: Skill) -> None:
        """Write a skill to a SKILL.md file."""
        path = self.skill_dir / f"{skill.name}.md"
        path.write_text(skill.to_skill_md())

    def _delete_skill_file(self, skill: Skill) -> None:
        """Remove a skill's SKILL.md file."""
        path = self.skill_dir / f"{skill.name}.md"
        if path.exists():
            path.unlink()

    def _load_skill_file(self, skill: Skill) -> str | None:
        """Load a skill's SKILL.md file content."""
        path = self.skill_dir / f"{skill.name}.md"
        if path.exists():
            return path.read_text()
        return None

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
