"""Multi-model routing for Tektos.

Kernel substrate (ADR-141 T8c-2a) — verbatim port of the donor
``tektos-ultima-v1/src/tektos/routing.py`` (396 LOC, self-contained:
stdlib-only, yaml lazy-imported). Layering rule: the donor threat model
here is generic multi-model routing (tiers, scoring, cost tracking,
fallback chains) — shared infrastructure, so it lives in the kernel, not
``plugins/tektos/``. The donor's thin HTTP surface
(``GET /api/routing/decide``, main.py:5297) is wired by the kernel app
(T8c-2b).

Provides intelligent model selection based on task type, complexity,
and cost. Supports fallback chains, weighted voting, and cost tracking.

Architecture:
- ModelProfile: defines capabilities of each LLM
- RoutingPolicy: rules for selecting models
- Router: selects and chains models for a given task
- CostTracker: tracks token usage and costs across models

Design:
- Lightweight routing decision layer
- No LLM coupling — just config + heuristics
- Supports llama.cpp, vLLM, and any OpenAI-compatible API
- Integrates with repograph for task complexity estimation
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────


class TaskCategory(enum.Enum):
    """Categories of tasks Tektos performs."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    ARCHITECTURE = "architecture"
    RESEARCH = "research"
    PLANNING = "planning"
    REFACTORING = "refactoring"
    SEARCH = "search"
    MISC = "misc"


class ModelTier(enum.Enum):
    """Model tiers by capability and cost."""

    FAST = "fast"  # Quick tasks, low complexity
    BALANCED = "balanced"  # General purpose
    POWER = "power"  # Complex tasks, high accuracy
    EXPERT = "expert"  # Expert-level analysis


@dataclass
class ModelProfile:
    """Profile of an available LLM."""

    name: str
    api_base: str
    model_name: str
    tier: ModelTier
    category: str  # coder, planner, general, embedding
    context_window: int = 131072
    max_tokens: int = 8192
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    features: list[str] = field(default_factory=list)  # ["tools", "vision", "json"]
    preferred_categories: list[TaskCategory] = field(default_factory=list)
    is_default: bool = False


@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    selected_model: str
    tier: ModelTier
    category: str
    confidence: float  # 0.0-1.0
    reason: str
    fallback_model: str | None = None
    estimated_tokens: int = 0
    cost_estimate: float = 0.0


@dataclass
class CostRecord:
    """A single cost record."""

    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    timestamp: str
    task: str


# ── Cost Tracker ────────────────────────────────────────────────────────────


class CostTracker:
    """Track costs across models and sessions."""

    def __init__(self, max_records: int = 1000):
        self.records: list[CostRecord] = []
        self.max_records = max_records

    def record(
        self, model: str, input_tokens: int, output_tokens: int, cost: float, task: str
    ) -> CostRecord:
        record = CostRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            task=task,
        )
        self.records.append(record)
        # Trim oldest if exceeded
        while len(self.records) > self.max_records:
            self.records.pop(0)
        return record

    def total_cost(self) -> float:
        return sum(r.cost for r in self.records)

    def cost_by_model(self) -> dict[str, float]:
        costs: dict[str, float] = {}
        for r in self.records:
            costs[r.model] = costs.get(r.model, 0) + r.cost
        return costs

    def cost_by_task(self) -> dict[str, float]:
        costs: dict[str, float] = {}
        for r in self.records:
            costs[r.task] = costs.get(r.task, 0) + r.cost
        return costs

    def recent(self, count: int = 10) -> list[CostRecord]:
        return self.records[-count:]


# ── Router ──────────────────────────────────────────────────────────────────


class ModelRouter:
    """Route tasks to appropriate models."""

    def __init__(self):
        self.models: dict[str, ModelProfile] = {}
        self._default: ModelProfile | None = None
        self.cost_tracker = CostTracker()
        self._fallback_chain: list[str] = []

    def register_model(self, profile: ModelProfile) -> None:
        """Register a model profile."""
        self.models[profile.name] = profile
        if profile.is_default:
            self._default = profile
        log.info(f"Registered model: {profile.name} ({profile.model_name}) [{profile.tier.value}]")

    def get_model(self, name: str) -> ModelProfile | None:
        return self.models.get(name)

    def get_default(self) -> ModelProfile | None:
        return self._default

    def list_models(self) -> list[ModelProfile]:
        return list(self.models.values())

    def route(
        self,
        task_category: TaskCategory,
        complexity: int = 1,  # 1-5 scale
        prefer_tier: ModelTier | None = None,
        force_model: str | None = None,
    ) -> RoutingDecision:
        """Route a task to the best available model.

        Args:
            task_category: Category of the task.
            complexity: Task complexity (1=simple, 5=complex).
            prefer_tier: Override model tier preference.
            force_model: Force use of a specific model.
        """
        if force_model and force_model in self.models:
            model = self.models[force_model]
            return RoutingDecision(
                selected_model=model.name,
                tier=model.tier,
                category=model.category,
                confidence=0.9,
                reason=f"Forced model: {model.name}",
                fallback_model=self._get_fallback(model.name),
            )

        # Determine target tier based on complexity
        if prefer_tier:
            target_tier = prefer_tier
        elif complexity <= 2:
            target_tier = ModelTier.FAST
        elif complexity <= 3:
            target_tier = ModelTier.BALANCED
        else:
            target_tier = ModelTier.POWER

        # Find best matching model
        candidates = self._find_candidates(task_category, target_tier)

        if not candidates:
            # Fallback to any available model
            candidates = self._find_candidates(task_category, ModelTier.BALANCED)
            if not candidates:
                candidates = list(self.models.values())

        if not candidates:
            return RoutingDecision(
                selected_model="unknown",
                tier=ModelTier.BALANCED,
                category="unknown",
                confidence=0.0,
                reason="No models available",
            )

        # Score candidates
        best = max(candidates, key=lambda m: self._score(m, task_category, target_tier))

        return RoutingDecision(
            selected_model=best.name,
            tier=best.tier,
            category=best.category,
            confidence=self._score(best, task_category, target_tier),
            reason=f"Selected {best.name} for {task_category.value} (tier={target_tier.value})",
            fallback_model=self._get_fallback(best.name),
            estimated_tokens=max(256, complexity * 512),
            cost_estimate=self._estimate_cost(best, complexity),
        )

    def _find_candidates(self, category: TaskCategory, tier: ModelTier) -> list[ModelProfile]:
        """Find models that match category and tier."""
        return [
            m
            for m in self.models.values()
            if m.tier == tier
            and (
                not m.preferred_categories
                or category in m.preferred_categories
                or m.category == category.value
            )
        ]

    def _score(self, model: ModelProfile, category: TaskCategory, tier: ModelTier) -> float:
        """Score a model for a given task (0.0-1.0)."""
        score = 0.5  # Base score for tier match

        # Bonus for preferred categories
        if category in model.preferred_categories:
            score += 0.3
        if model.category == category.value:
            score += 0.1

        # Bonus for matching tier
        if model.tier == tier:
            score += 0.1

        return min(1.0, score)

    def _get_fallback(self, model_name: str) -> str | None:
        """Get fallback model name.

        Prefer same tier, then more capable tiers (higher tier).
        """
        model = self.models.get(model_name)
        if not model:
            return None

        # Try same tier first
        candidates = [
            m for m in self.models.values() if m.tier == model.tier and m.name != model_name
        ]
        if candidates:
            return candidates[0].name

        # Then try more capable tiers
        tier_order = [ModelTier.FAST, ModelTier.BALANCED, ModelTier.POWER, ModelTier.EXPERT]
        current_idx = tier_order.index(model.tier)
        for higher_tier in tier_order[current_idx + 1 :]:
            candidates = [
                m for m in self.models.values() if m.tier == higher_tier and m.name != model_name
            ]
            if candidates:
                return candidates[0].name

        return None

    def _estimate_cost(self, model: ModelProfile, complexity: int) -> float:
        """Estimate cost for a task."""
        tokens = max(256, complexity * 512)
        return (tokens / 1_000_000) * (model.cost_per_1m_input + model.cost_per_1m_output)

    def add_fallback_chain(self, model_names: list[str]) -> None:
        """Set explicit fallback chain."""
        self._fallback_chain = model_names

    def get_fallback_chain(self, model_name: str) -> list[str]:
        """Get fallback chain for a model."""
        if model_name in self.models:
            return [n for n in self._fallback_chain if n != model_name and n in self.models]
        return []

    def set_default(self, model_name: str) -> bool:
        """Set the default model."""
        if model_name in self.models:
            self._default = self.models[model_name]
            self.models[model_name].is_default = True
            return True
        return False

    def get_stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        total = len(self.cost_tracker.records)
        return {
            "total_models": len(self.models),
            "total_tasks_routed": total,
            "total_cost": self.cost_tracker.total_cost(),
            "cost_by_model": self.cost_tracker.cost_by_model(),
            "models": {
                name: {
                    "tier": m.tier.value,
                    "category": m.category,
                    "default": m.is_default,
                }
                for name, m in self.models.items()
            },
        }


# ── Config Builder ─────────────────────────────────────────────────────────


def build_default_config(base_url: str, model_name: str) -> dict[str, Any]:
    """Build default routing config from environment."""
    return {
        "models": [
            {
                "name": "default",
                "api_base": base_url,
                "model_name": model_name,
                "tier": "balanced",
                "category": "general",
                "is_default": True,
                "context_window": 131072,
                "max_tokens": 8192,
            }
        ],
        "policies": {
            "auto_fallback": True,
            "cost_tracking": True,
        },
    }


def load_config(config_path: str) -> ModelRouter:
    """Load routing config from YAML file."""
    import yaml

    router = ModelRouter()

    with open(config_path) as f:
        data = yaml.safe_load(f)

    for model_data in data.get("models", []):
        profile = ModelProfile(
            name=model_data["name"],
            api_base=model_data["api_base"],
            model_name=model_data["model_name"],
            tier=ModelTier(model_data.get("tier", "balanced")),
            category=model_data.get("category", "general"),
            context_window=model_data.get("context_window", 131072),
            max_tokens=model_data.get("max_tokens", 8192),
            cost_per_1m_input=model_data.get("cost_per_1m_input", 0.0),
            cost_per_1m_output=model_data.get("cost_per_1m_output", 0.0),
            features=model_data.get("features", []),
            preferred_categories=[
                TaskCategory(c) for c in model_data.get("preferred_categories", [])
            ],
            is_default=model_data.get("is_default", False),
        )
        router.register_model(profile)

    return router
