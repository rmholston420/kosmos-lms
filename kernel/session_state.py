"""Session state persistence for LAST_KNOWN_STATE.md (ADR-141 T2).

Kernel-native port of the donor ``tektos-ultima/src/tektos/runtime/
session_state.py`` (356 LOC): ``SessionState`` (structured resume anchor)
+ ``SessionStateManager`` (markdown file I/O: load/save/snapshot).

**Donor-fidelity:** ``SessionState`` is verbatim — same fields, same
``to_markdown``/``from_markdown``/``to_dict``/``from_dict`` wire shapes
(the ``/api/state/{session_id}`` route returns ``{session_id, state:
to_dict(), markdown: to_markdown()}`` exactly as the donor did on :8020).

**One documented donor fix** (``SessionStateManager``): the donor keyed
ALL sessions at one shared file — ``workspace/LAST_KNOWN_STATE.md`` with
``workspace`` defaulting to the hard-coded ``/home/rmholston``. That
breaks the donor's own 404 semantics (a session with no saved state would
read *another* session's file) and cross-contaminates state between
sessions. The kernel manager keys the file per session under
``<workspace>/tektos_state/<session_id>.md``. ``workspace`` defaults to
``os.getcwd()`` (the kernel workspace root, same convention as
``/api/directory_list``) and is overridable per manager for tests.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Subdirectory (relative to the workspace root) holding per-session
#: LAST_KNOWN_STATE files.
STATE_SUBDIR = "tektos_state"


@dataclass
class SessionState:
    """Structured state for a Tektos session.

    This is the single source of truth for resuming work after
    a session ends or context is lost.
    """

    session_id: str
    project: str
    timestamp: str

    # Objective and progress
    objective: str = ""
    progress: str = ""
    completion_pct: float = 0.0

    # Current state
    current_file: str = ""
    current_command: str = ""
    running_processes: list[str] = field(default_factory=list)
    api_endpoints: dict[str, str] = field(default_factory=dict)

    # Decisions and context
    key_decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # Next steps
    next_steps: list[str] = field(default_factory=list)
    exact_commands: list[str] = field(default_factory=list)

    # Blockers
    blockers: list[str] = field(default_factory=list)

    # Task list
    todo_items: list[dict[str, Any]] = field(default_factory=list)

    # Environment
    environment: dict[str, str] = field(default_factory=dict)

    # Memory context
    memory_context: str = ""

    # Files referenced
    referenced_files: list[str] = field(default_factory=list)

    # Metadata
    version: int = 1

    def to_markdown(self) -> str:
        """Convert to LAST_KNOWN_STATE.md format."""
        lines = [
            "# LAST_KNOWN_STATE.md",
            "",
            f"**Session:** {self.session_id}",
            f"**Project:** {self.project}",
            f"**Timestamp:** {self.timestamp}",
            f"**Version:** {self.version}",
            "",
            "## Objective",
            "",
            f"{self.objective}",
            "",
            f"**Progress:** {self.progress}",
        ]

        if self.completion_pct:
            lines.append(f"**Completion:** {self.completion_pct}%")

        lines.append("")

        # Current State
        lines.append("## Current State")
        lines.append("")
        if self.current_file:
            lines.append(f"- **Current File:** `{self.current_file}`")
        if self.current_command:
            lines.append(f"- **Current Command:** `{self.current_command}`")
        if self.running_processes:
            lines.append(f"- **Running:** {', '.join(self.running_processes)}")
        if self.api_endpoints:
            lines.append("- **APIs:**")
            for endpoint, status in self.api_endpoints.items():
                lines.append(f"  - `{endpoint}`: {status}")
        lines.append("")

        # Key Decisions
        if self.key_decisions:
            lines.append("## Key Decisions")
            lines.append("")
            for i, decision in enumerate(self.key_decisions, 1):
                lines.append(f"{i}. {decision}")
            lines.append("")

        # Constraints
        if self.constraints:
            lines.append("## Constraints")
            lines.append("")
            for constraint in self.constraints:
                lines.append(f"- {constraint}")
            lines.append("")

        # Next Steps
        if self.next_steps:
            lines.append("## Next Steps")
            lines.append("")
            for i, step in enumerate(self.next_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        # Exact Commands
        if self.exact_commands:
            lines.append("## Exact Commands")
            lines.append("")
            for cmd in self.exact_commands:
                lines.append("```bash")
                lines.append(f"{cmd}")
                lines.append("```")
            lines.append("")

        # Task List
        if self.todo_items:
            lines.append("## Task List")
            lines.append("")
            for item in self.todo_items:
                status = "✓" if item.get("status") == "completed" else "○"
                content = item.get("content", "")
                lines.append(f"- [{status}] {content}")
            lines.append("")

        # Blockers
        if self.blockers:
            lines.append("## Blockers")
            lines.append("")
            for blocker in self.blockers:
                lines.append(f"- 🚫 {blocker}")
            lines.append("")

        # Notes
        if self.notes:
            lines.append("## Notes")
            lines.append("")
            for note in self.notes:
                lines.append(f"- {note}")
            lines.append("")

        # Memory Context
        if self.memory_context:
            lines.append("## Memory Context")
            lines.append("")
            lines.append(self.memory_context)
            lines.append("")

        # Referenced Files
        if self.referenced_files:
            lines.append("## Referenced Files")
            lines.append("")
            for f in self.referenced_files:
                lines.append(f"- `{f}`")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, md: str, session_id: str, project: str) -> SessionState:
        """Parse LAST_KNOWN_STATE.md (simplified reconstruction)."""
        state = cls(
            session_id=session_id,
            project=project,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Extract objective (everything between ## Objective and next ## header or **Progress:)
        if "## Objective" in md:
            obj_section = md.split("## Objective")[1]
            # Stop at the next ## header or at **Progress: line
            for delimiter in ["\n## ", "**Progress:**"]:
                if delimiter in obj_section:
                    obj_section = obj_section.split(delimiter)[0]
            state.objective = obj_section.strip()

        # Extract progress
        if "**Progress:**" in md:
            prog_section = md.split("**Progress:**")[1]
            prog_line = prog_section.split("\n")[0]
            state.progress = prog_line.split("**")[0].strip()

        # Extract completion
        if "**Completion:**" in md:
            comp_section = md.split("**Completion:**")[1]
            comp_line = comp_section.split("\n")[0]
            with contextlib.suppress(ValueError):
                state.completion_pct = float(comp_line.split("%")[0].strip())

        # Extract current file
        if "- **Current File:**" in md:
            state.current_file = md.split("- **Current File:**")[1].split("`")[1]

        # Extract next steps (numbered list like "1. Finish integration")
        if "## Next Steps" in md:
            steps_section = md.split("## Next Steps")[1]
            # Stop at next ## header
            if "\n## " in steps_section:
                steps_section = steps_section.split("\n## ")[0]
            for line in steps_section.strip().split("\n"):
                line = line.strip()
                # Match "1. step" or "- step" format
                if line and (line[0].isdigit() and ". " in line or line.startswith("- ")):
                    # Remove number prefix
                    content = line.split(". ", 1)[-1] if ". " in line else line[2:]
                    state.next_steps.append(content.strip())

        # Extract key decisions (numbered list like "1. Use LAST_KNOWN_STATE.md as anchor doc")
        if "## Key Decisions" in md:
            decisions_section = md.split("## Key Decisions")[1]
            if "\n## " in decisions_section:
                decisions_section = decisions_section.split("\n## ")[0]
            for line in decisions_section.strip().split("\n"):
                line = line.strip()
                if line and (line[0].isdigit() and ". " in line):
                    content = line.split(". ", 1)[-1]
                    state.key_decisions.append(content.strip())

        # Extract blockers (prefixed with 🚫)
        if "## Blockers" in md:
            blockers_section = md.split("## Blockers")[1]
            if "\n## " in blockers_section:
                blockers_section = blockers_section.split("\n## ")[0]
            for line in blockers_section.strip().split("\n"):
                line = line.strip()
                if line and ("\U0001F6AB " in line or line.startswith("- ")):
                    content = line.replace("\U0001F6AB ", "").replace("- ", "").strip()
                    if content:
                        state.blockers.append(content)

        # Extract task list
        if "## Task List" in md:
            tasks_section = md.split("## Task List")[1].split("## ")[0]
            for line in tasks_section.strip().split("\n"):
                if line.strip().startswith("- ["):
                    content = line.split("] ")[1] if "] " in line else ""
                    is_done = "[✓]" in line
                    state.todo_items.append(
                        {"content": content, "status": "completed" if is_done else "pending"}
                    )

        return state

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Reconstruct from dict."""
        return cls(**data)


class SessionStateManager:
    """Manages LAST_KNOWN_STATE.md persistence and retrieval.

    Handles:
    - Saving state to the per-session file
    - Loading state (default when no file exists — donor semantics)
    - Incremental updates during work
    - Full snapshots at session boundaries (version bump)

    Kernel deviation (documented in the module docstring): the file is
    per-session (``<workspace>/tektos_state/<session_id>.md``) rather than
    one shared file for every session.
    """

    def __init__(
        self,
        session_id: str,
        project: str,
        workspace: str | None = None,
    ):
        self.session_id = session_id
        self.project = project
        self.workspace = Path(workspace or os.getcwd())
        self.state_file = self.workspace / STATE_SUBDIR / f"{session_id}.md"

    def load_state(self) -> SessionState:
        """Load last known state from file or create default."""
        if self.state_file.exists():
            md = self.state_file.read_text()
            return SessionState.from_markdown(md, self.session_id, self.project)

        return self._create_default()

    def has_state(self) -> bool:
        """True when a saved state file exists for this session."""
        return self.state_file.exists()

    def save_state(self, state: SessionState) -> None:
        """Save state to the per-session file."""
        md = state.to_markdown()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(md)

    def update_state(self, **kwargs) -> SessionState:
        """Incrementally update state fields."""
        state = self.load_state()

        for key, value in kwargs.items():
            if hasattr(state, key):
                current = getattr(state, key)
                if isinstance(current, list) and isinstance(value, list):
                    current.extend(value)
                else:
                    setattr(state, key, value)

        state.timestamp = datetime.now(timezone.utc).isoformat()
        self.save_state(state)
        return state

    def save_full_snapshot(self, state: SessionState) -> None:
        """Save a full state snapshot with version bump."""
        state.version += 1
        state.timestamp = datetime.now(timezone.utc).isoformat()
        self.save_state(state)

    def _create_default(self) -> SessionState:
        """Create a default state for a new session."""
        return SessionState(
            session_id=self.session_id,
            project=self.project,
            timestamp=datetime.now(timezone.utc).isoformat(),
            objective="Initialize session",
            progress="Starting work",
            next_steps=[
                "Review LAST_KNOWN_STATE.md from previous session",
                "Load project context and current state",
                "Continue from last completed task",
            ],
        )


def create_default_session_state(session_id: str, project: str) -> SessionState:
    """Create a default state for a new Tektos session."""
    return SessionStateManager(
        session_id=session_id,
        project=project,
    )._create_default()
