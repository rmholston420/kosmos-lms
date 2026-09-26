"""Tektos Axiom System — Context Compression Framework

Compresses all Tektos knowledge into axioms that survive context compaction.
Each axiom is self-contained, verifiable, and machine-parseable.

Usage:
    from kernel.axioms import load_axioms, axiom_get, axiom_has
    axioms = load_axioms()  # loads from filesystem
    if axiom_has(axioms, 'phase.6.10.complete'):
        log.info("GUI testing committed")

Axiom format (YAML in .axiom files):
    id: phase.6.10.complete
    category: milestone
    status: verified
    date: 2026-08-14
    test_count: 963
    coverage_pct: 77
    notes: |
        All Phase 6 hardening items complete.
        Playwright + Chromium installed.
        Git integration committed.

    prerequisites: []
    blocking: []

"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# ── Axiom Data Model ────────────────────────────────────────────────────────


@dataclass
class Axiom:
    """Single axiom — self-contained unit of Tektos knowledge."""

    id: str  # dot-separated namespace: phase.6.10.complete
    category: str  # milestone, directive, architecture, operation, constraint, lesson
    status: str  # pending, in_progress, verified, deprecated
    date: str  # ISO date
    content: str = ""  # prose summary
    notes: str = ""  # detailed notes
    metadata: dict = field(default_factory=dict)  # test_count, coverage_pct, commit_hash, etc.
    prerequisites: list[str] = field(default_factory=list)  # axiom IDs that must be true
    blocking: list[str] = field(default_factory=list)  # axiom IDs that block this one
    tags: list[str] = field(default_factory=list)  # keywords for search

    def is_active(self) -> bool:
        return self.status in ("pending", "in_progress", "verified")

    def is_complete(self) -> bool:
        return self.status == "verified"


class AxiomSystem:
    """Load, query, and persist axioms."""

    def __init__(self, axioms_dir: str | None = None):
        self.axioms_dir = Path(axioms_dir) if axioms_dir else Path(__file__).parent / "axioms"
        self._axioms: dict[str, Axiom] = {}

    def load(self) -> AxiomSystem:
        """Load all .axiom files from axioms directory."""
        if not self.axioms_dir.exists():
            log.warning(f"Axioms directory not found: {self.axioms_dir}")
            return self

        for axiom_file in sorted(self.axioms_dir.glob("**/*.axiom")):
            try:
                with open(axiom_file) as f:
                    # Load all documents in the file (yaml.dump_all creates multi-doc)
                    for doc in yaml.safe_load_all(f):
                        if doc is None:
                            continue
                        if isinstance(doc, list):
                            for item in doc:
                                self._axioms[item["id"]] = self._parse_axiom(item)
                        elif isinstance(doc, dict):
                            self._axioms[doc["id"]] = self._parse_axiom(doc)
            except Exception as e:
                log.error(f"Failed to load axiom {axiom_file}: {e}")

        return self

    def _parse_axiom(self, data: dict) -> Axiom:
        return Axiom(
            id=data["id"],
            category=data.get("category", "misc"),
            status=data.get("status", "pending"),
            date=data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            content=data.get("content", ""),
            notes=data.get("notes", ""),
            metadata=data.get("metadata", {}),
            prerequisites=data.get("prerequisites", []),
            blocking=data.get("blocking", []),
            tags=data.get("tags", []),
        )

    def get(self, axiom_id: str) -> Axiom | None:
        return self._axioms.get(axiom_id)

    def has(self, axiom_id: str) -> bool:
        return axiom_id in self._axioms

    def verify(self, axiom_id: str) -> bool:
        """Mark an axiom as verified."""
        if axiom_id in self._axioms:
            self._axioms[axiom_id].status = "verified"
            self._save()
            return True
        return False

    def set_status(self, axiom_id: str, status: str) -> bool:
        if axiom_id in self._axioms:
            self._axioms[axiom_id].status = status
            self._save()
            return True
        return False

    def add(self, axiom: Axiom) -> None:
        self._axioms[axiom.id] = axiom
        self._save()

    def create(self, id: str, category: str, content: str, **kwargs) -> Axiom:
        """Create and persist a new axiom."""
        axiom = Axiom(
            id=id,
            category=category,
            status="pending",
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            content=content,
            **kwargs,
        )
        self._axioms[id] = axiom
        self._save()
        return axiom

    def list_active(self) -> list[Axiom]:
        """List all active (non-deprecated) axioms."""
        return [a for a in self._axioms.values() if a.is_active()]

    def list_by_category(self, category: str) -> list[Axiom]:
        return [a for a in self._axioms.values() if a.category == category]

    def list_by_status(self, status: str) -> list[Axiom]:
        return [a for a in self._axioms.values() if a.status == status]

    def get_blockers(self, axiom_id: str) -> list[Axiom]:
        """Get axioms that block the given axiom (i.e., its incomplete prerequisites)."""
        axiom = self.get(axiom_id)
        if not axiom:
            return []
        blockers = [self.get(p) for p in axiom.prerequisites]
        return [b for b in blockers if b and not b.is_complete()]

    def get_dependents(self, axiom_id: str) -> list[Axiom]:
        """Get axioms that depend on the given axiom."""
        dependents = [a for a in self._axioms.values() if axiom_id in a.prerequisites]
        return dependents

    def to_markdown(self) -> str:
        """Render all axioms as Markdown — for knowledge base."""
        lines = ["# Tektos Axioms", "", "## Active Axioms", ""]

        for axiom in sorted(self._axioms.values(), key=lambda a: a.id):
            if not axiom.is_active():
                continue
            lines.append(f"### `{axiom.id}`")
            lines.append(f"- **Category**: {axiom.category}")
            lines.append(f"- **Status**: {axiom.status}")
            lines.append(f"- **Date**: {axiom.date}")
            if axiom.content:
                lines.append(f"- **Summary**: {axiom.content}")
            if axiom.metadata:
                meta = ", ".join(f"{k}={v}" for k, v in axiom.metadata.items())
                lines.append(f"- **Metadata**: {meta}")
            if axiom.notes:
                lines.append(f"- **Notes**: {axiom.notes}")
            if axiom.tags:
                lines.append(f"- **Tags**: {', '.join(axiom.tags)}")
            lines.append("")

        return "\n".join(lines)

    def _save(self) -> None:
        """Persist all axioms to .axiom files."""
        self.axioms_dir.mkdir(parents=True, exist_ok=True)

        # Group axioms by category for organization
        categories: dict[str, list[Axiom]] = {}
        for axiom in self._axioms.values():
            categories.setdefault(axiom.category, []).append(axiom)

        for category, axioms in categories.items():
            category_dir = self.axioms_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)

            # One file per category with all axioms
            file_path = category_dir / f"{category}.axiom"
            with open(file_path, "w") as f:
                yaml.dump_all(
                    [self._serialize(a) for a in axioms],
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

    def _serialize(self, axiom: Axiom) -> dict[str, Any]:
        return {
            "id": axiom.id,
            "category": axiom.category,
            "status": axiom.status,
            "date": axiom.date,
            "content": axiom.content,
            "notes": axiom.notes,
            "metadata": axiom.metadata,
            "prerequisites": axiom.prerequisites,
            "blocking": axiom.blocking,
            "tags": axiom.tags,
        }


# ── Convenience Functions ────────────────────────────────────────────────────

_axiom_system: AxiomSystem | None = None


def load_axioms(axioms_dir: str | None = None) -> AxiomSystem:
    """Load or return cached axiom system."""
    global _axiom_system
    if _axiom_system is None:
        _axiom_system = AxiomSystem(axioms_dir)
        _axiom_system.load()
    return _axiom_system


def axiom_get(axiom_id: str) -> Axiom | None:
    return load_axioms().get(axiom_id)


def axiom_has(axiom_id: str) -> bool:
    return load_axioms().has(axiom_id)


def axiom_verify(axiom_id: str) -> bool:
    return load_axioms().verify(axiom_id)


def axiom_create(id: str, category: str, content: str, **kwargs) -> Axiom:
    return load_axioms().create(id, category, content, **kwargs)
