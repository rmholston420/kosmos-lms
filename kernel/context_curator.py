"""ContextCurator — manages context window lifecycle and compaction decisions.

Provides:
- Context window monitoring (token budget tracking)
- Automatic compaction triggers based on usage
- Context summarization coordination with ContextCompactor
- Persistent context preservation across sessions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ContextSnapshot:
    """A point-in-time snapshot of context state."""

    timestamp: str = ""
    total_tokens: int = 0
    used_tokens: int = 0
    budget_remaining: int = 0
    compaction_needed: bool = False
    active_tiers: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class ContextCurator:
    """Manages context window lifecycle and compaction decisions.

    This module coordinates with ContextCompactor to decide when and how
    to compress context, and with EmbedderClient for semantic preservation.
    """

    def __init__(
        self,
        max_tokens: int = 262144,
        compaction_threshold: float = 0.75,
    ) -> None:
        """Initialize the context curator.

        Args:
            max_tokens: Maximum token budget for context.
            compaction_threshold: Fraction of budget at which to trigger compaction.
        """
        self.max_tokens = max_tokens
        self.compaction_threshold = compaction_threshold
        self._current_tokens = 0
        self._snapshots: list[ContextSnapshot] = []
        self._compaction_count = 0

    def record_usage(self, tokens: int) -> None:
        """Record token usage for the current context window."""
        self._current_tokens = tokens

    def get_snapshot(self) -> ContextSnapshot:
        """Get current context snapshot."""
        budget_remaining = max(0, self.max_tokens - self._current_tokens)
        compaction_needed = self._current_tokens > (self.max_tokens * self.compaction_threshold)

        snapshot = ContextSnapshot(
            total_tokens=self.max_tokens,
            used_tokens=self._current_tokens,
            budget_remaining=budget_remaining,
            compaction_needed=compaction_needed,
            active_tiers=4 if compaction_needed else 0,
            metadata={
                "compaction_count": self._compaction_count,
                "threshold": self.compaction_threshold,
            },
        )
        self._snapshots.append(snapshot)
        return snapshot

    def should_compact(self) -> bool:
        """Check if context compaction is needed."""
        return self._current_tokens > (self.max_tokens * self.compaction_threshold)

    def get_compaction_stats(self) -> dict[str, Any]:
        """Get statistics about context compaction."""
        return {
            "max_tokens": self.max_tokens,
            "current_tokens": self._current_tokens,
            "budget_remaining": max(0, self.max_tokens - self._current_tokens),
            "compaction_threshold": self.compaction_threshold,
            "should_compact": self.should_compact(),
            "total_compactions": self._compaction_count,
            "snapshots_tracked": len(self._snapshots),
        }

    async def start(self) -> None:
        """Initialize the context curator."""
        logger.info(
            "Context curator initialized (max=%d, threshold=%.0f%%)",
            self.max_tokens,
            self.compaction_threshold * 100,
        )

    async def stop(self) -> None:
        """Clean up the context curator."""
        logger.info("Context curator stopped")
