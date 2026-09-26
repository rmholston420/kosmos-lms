"""RepoMapGenerator — generates and maintains repository structure maps.

Provides:
- Repository structure scanning
- Dependency graph generation
- File import analysis
- Repository map serialization
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RepoMapEntry:
    """An entry in the repository map."""

    path: str
    type: str  # "file", "directory"
    size: int = 0
    imports: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


class RepoMapGenerator:
    """Generates and maintains repository structure maps.

    This module scans the repository to build a map of files, directories,
    and their dependencies (imports).
    """

    def __init__(self, project_root: str = ".") -> None:
        """Initialize the repo map generator.

        Args:
            project_root: Root directory of the project to scan.
        """
        self._project_root = project_root
        self._entries: dict[str, RepoMapEntry] = {}
        self._file_count = 0
        self._dir_count = 0

    def build_map(self) -> int:
        """Build the repository map by scanning the project root.

        Returns:
            Number of entries added to the map.
        """
        import os

        self._entries.clear()
        self._file_count = 0
        self._dir_count = 0

        for root, dirs, files in os.walk(self._project_root):
            # Skip hidden and common non-source dirs
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d
                not in (
                    "__pycache__",
                    "node_modules",
                    ".git",
                    "venv",
                    ".venv",
                    "data",
                    "dist",
                    "build",
                )
            ]

            for d in dirs:
                rel = os.path.relpath(os.path.join(root, d), self._project_root)
                self._entries[rel] = RepoMapEntry(path=rel, type="directory")
                self._dir_count += 1

            for f in files:
                if not (f.endswith(".py") or f.endswith(".ts") or f.endswith(".js")):
                    continue
                full_path = os.path.join(root, f)
                rel = os.path.relpath(full_path, self._project_root)

                imports = []
                try:
                    with open(full_path, errors="ignore") as fh:
                        for line in fh:
                            line = line.strip()
                            if line.startswith("import ") or line.startswith("from "):
                                imports.append(line)
                except OSError:
                    pass

                self._entries[rel] = RepoMapEntry(
                    path=rel,
                    type="file",
                    size=os.path.getsize(full_path) if os.path.exists(full_path) else 0,
                    imports=imports,
                )
                self._file_count += 1

        return len(self._entries)

    def get_entry(self, path: str) -> RepoMapEntry | None:
        """Get a map entry by path."""
        return self._entries.get(path)

    def get_stats(self) -> dict[str, Any]:
        """Get repository map statistics."""
        return {
            "project_root": self._project_root,
            "total_entries": len(self._entries),
            "files": self._file_count,
            "directories": self._dir_count,
        }

    async def start(self) -> None:
        """Initialize the repo map generator."""
        count = self.build_map()
        logger.info(
            "Repo map generator initialized: %d entries (%d files, %d dirs)",
            count,
            self._file_count,
            self._dir_count,
        )

    async def stop(self) -> None:
        """Clean up the repo map generator."""
        logger.info("Repo map generator stopped")
