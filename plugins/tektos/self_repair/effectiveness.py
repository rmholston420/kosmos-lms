"""Repair Effectiveness Tracker — ADR-141 R4 (full donor port).

Donor: ``tektos.self_repair.effectiveness`` (tektos-ultima-v1, 233 lines).
Ported verbatim under the ADR-141 functionality-preservation constraint:
the engine records every repair outcome here (success/failure/rollback/
degradation), computes per-category + per-strategy stats, and the UI
self-repair tab's effectiveness numbers come from ``get_stats()``. The only
change vs the donor is the import target for :class:`RepairRecord`
(vendored, ADR-141 R2).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from adapters.tektos.vendor.self_repair_models_donor import RepairRecord

log = logging.getLogger(__name__)


class RepairEffectivenessTracker:
    """Tracks repair effectiveness across all repair attempts.

    Maintains statistics on:
        - Success/failure rates by category
        - Average time-to-repair
        - Strategy effectiveness
        - Degradation frequency
        - Rollback frequency
    """

    def __init__(self, window_hours: int = 24):
        self.window_seconds = window_hours * 3600
        self._records: list[RepairRecord] = []

        # Statistics
        self._by_category: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failed": 0, "rolled_back": 0, "degraded": 0, "total": 0}
        )
        self._by_strategy: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failed": 0, "total": 0}
        )
        self._total_time: dict[str, float] = defaultdict(float)
        self._total_count: dict[str, int] = defaultdict(int)

    def _is_in_window(self, record: RepairRecord) -> bool:
        """Check if a record is within the tracking window."""
        return (time.time() - record.created_at) < self.window_seconds

    def record_success(self, record: RepairRecord) -> None:
        """Record a successful repair."""
        self._records.append(record)
        cat = record.threat_category
        self._by_category[cat]["success"] += 1
        self._by_category[cat]["total"] += 1

        if record.strategy_used:
            strat = record.strategy_used.value
            self._by_strategy[strat]["success"] += 1
            self._by_strategy[strat]["total"] += 1

        self._total_time[cat] += record.total_time_seconds
        self._total_count[cat] += 1

        log.info(
            "[RepairEffectiveness] Success: %s (%s) in %.1fs",
            record.threat_category,
            record.strategy_used,
            record.total_time_seconds,
        )

    def record_failure(self, record: RepairRecord) -> None:
        """Record a failed repair."""
        self._records.append(record)
        cat = record.threat_category
        self._by_category[cat]["failed"] += 1
        self._by_category[cat]["total"] += 1

        if record.strategy_used:
            strat = record.strategy_used.value
            self._by_strategy[strat]["failed"] += 1
            self._by_strategy[strat]["total"] += 1

        self._total_time[cat] += record.total_time_seconds
        self._total_count[cat] += 1

        log.warning(
            "[RepairEffectiveness] Failed: %s (%s): %s",
            record.threat_category,
            record.strategy_used,
            record.error,
        )

    def record_rollback(self, record: RepairRecord) -> None:
        """Record a rolled-back repair."""
        self._records.append(record)
        cat = record.threat_category
        self._by_category[cat]["rolled_back"] += 1
        self._by_category[cat]["total"] += 1

        log.warning("[RepairEffectiveness] Rolled back: %s", record.threat_category)

    def record_degradation(self, record: RepairRecord) -> None:
        """Record a degraded repair (graceful degradation applied)."""
        self._records.append(record)
        cat = record.threat_category
        self._by_category[cat]["degraded"] += 1
        self._by_category[cat]["total"] += 1

        log.info(
            "[RepairEffectiveness] Degraded: %s → %s",
            record.threat_category,
            record.degradation_applied.value,
        )

    def get_success_rate(self, category: str | None = None) -> float:
        """Get overall or per-category success rate."""
        if category:
            stats = self._by_category.get(category, {"total": 0, "success": 0})
        else:
            stats = {"total": 0, "success": 0}
            for cat_stats in self._by_category.values():
                stats["total"] += cat_stats["total"]
                stats["success"] += cat_stats["success"]

        if stats["total"] == 0:
            return 1.0  # No data yet, assume healthy
        return stats["success"] / stats["total"]

    def get_average_time(self, category: str | None = None) -> float:
        """Get average time-to-repair in seconds."""
        if category:
            count = self._total_count.get(category, 0)
            total = self._total_time.get(category, 0.0)
        else:
            count = sum(self._total_count.values())
            total = sum(self._total_time.values())

        if count == 0:
            return 0.0
        return total / count

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive repair effectiveness statistics."""
        total_success = sum(s["success"] for s in self._by_category.values())
        total_failed = sum(s["failed"] for s in self._by_category.values())
        total_rolled_back = sum(s["rolled_back"] for s in self._by_category.values())
        total_degraded = sum(s["degraded"] for s in self._by_category.values())
        total = sum(s["total"] for s in self._by_category.values())

        return {
            "total_repairs": total,
            "successful": total_success,
            "failed": total_failed,
            "rolled_back": total_rolled_back,
            "degraded": total_degraded,
            "overall_success_rate": round(total_success / max(1, total), 3),
            "by_category": dict(self._by_category),
            "by_strategy": dict(self._by_strategy),
            "average_time_seconds": round(self.get_average_time(), 2),
            "window_hours": self.window_seconds / 3600,
        }

    def get_recommendations(self) -> list[str]:
        """Get repair improvement recommendations based on stats."""
        recommendations = []

        # Check for categories with low success rates
        for cat, stats in self._by_category.items():
            if stats["total"] >= 3:
                rate = stats["success"] / stats["total"]
                if rate < 0.5:
                    recommendations.append(
                        f"Category '{cat}' has low success rate ({rate:.0%}). "
                        f"Review and improve repair strategies."
                    )

        # Check for high rollback rates
        for cat, stats in self._by_category.items():
            if stats["total"] >= 3 and stats["rolled_back"] / stats["total"] > 0.3:
                recommendations.append(
                    f"Category '{cat}' has high rollback rate. "
                    f"Repair strategies may be causing secondary issues."
                )

        # Check for slow repairs
        avg_time = self.get_average_time()
        if avg_time > 60:
            recommendations.append(
                f"Average repair time is {avg_time:.0f}s. Consider optimizing repair strategies."
            )

        return recommendations

    def to_memory_entry(self) -> dict[str, Any]:
        """Convert to memory entry for self-improvement loop."""
        stats = self.get_stats()
        return {
            "repair_effectiveness": stats,
            "recommendations": self.get_recommendations(),
        }


# Singleton
_tracker: RepairEffectivenessTracker | None = None


def get_effectiveness_tracker(window_hours: int = 24) -> RepairEffectivenessTracker:
    """Get or create the global effectiveness tracker."""
    global _tracker
    if _tracker is None:
        _tracker = RepairEffectivenessTracker(window_hours=window_hours)
    return _tracker


def reset_effectiveness_tracker() -> None:
    """Reset the global effectiveness tracker (for testing)."""
    global _tracker
    _tracker = None
