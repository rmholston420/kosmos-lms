"""T8c-2 — donor GET /api/routing/decide → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:5297.

Shape (donor wire, preserved):
  GET /api/routing/decide?task=...&category=...
    -> {task, category, recommended_model, confidence, fallback_models,
        estimated_cost}  (+ honest extra: reason)
  degrade (no router) -> same keys, confidence=0.5 (donor except-path wire)

Wiring (layering rule): donor `src/tektos/routing.py` (396 LOC, generic
multi-model routing: tiers/scoring/cost/fallback) → verbatim kernel
substrate `kernel/routing.py`; router seeded at boot from the kernel
primary-lane env (donor seeded TEKTOS_LLM_* — same profile: BALANCED,
general, is_default).

Documented divergence: the donor route ALWAYS failed (wrong `route()`
kwargs + `.get()` on a dataclass) → 0.5-confidence fallback every time.
Kernel calls `route(task_category, complexity)` correctly; complexity is
a documented length heuristic (1-5).
"""

from __future__ import annotations

from typing import Any

import pytest

import kernel.app as ka  # noqa: F401  (module import = app/registry state)
from fastapi.testclient import TestClient


@pytest.fixture()
def client_shape():
    from kernel.app import registry

    with TestClient(ka.app) as c:
        yield c, registry


def _decide(client: TestClient, task: str = "do x", category: str = "general") -> dict[str, Any]:
    r = client.get("/api/routing/decide", params={"task": task, "category": category})
    assert r.status_code == 200
    return r.json()


def test_decide_donor_wire_keys(client_shape):
    client, registry = client_shape
    body = _decide(client, task="refactor this module", category="refactoring")
    for k in ("task", "category", "recommended_model", "confidence",
              "fallback_models", "estimated_cost"):
        assert k in body, f"missing donor key {k}"
    assert body["task"] == "refactor this module"
    assert body["category"] == "refactoring"
    assert isinstance(body["fallback_models"], list)
    assert isinstance(body["estimated_cost"], float)


def test_decide_real_routing_not_always_fallback(client_shape):
    client, registry = client_shape
    # The donor ALWAYS took its except-path (broken call) and returned the
    # 0.5-confidence fallback — with NO reason field. Real routing returns
    # reason "Selected <model> for ..." — that's the discriminator.
    body = _decide(client, task="small fix", category="general")
    assert body["reason"].startswith("Selected"), (
        "route() must be called correctly — donor defect was no real "
        "decision (no reason field)"
    )
    assert body["recommended_model"]


def test_decide_unknown_category_degrades_to_misc(client_shape):
    client, registry = client_shape
    body = _decide(client, task="hello", category="not_a_real_category")
    assert body["reason"].startswith("Selected")  # real routing (MISC bucket)
    assert body["category"] == "not_a_real_category"  # echoed, donor wire


def test_decide_no_router_donor_fallback_wire(client_shape):
    client, registry = client_shape
    saved = registry.model_router
    registry.model_router = None
    try:
        body = _decide(client, task="x", category="general")
        assert body["confidence"] == 0.5
        assert body["fallback_models"] == []
        assert body["estimated_cost"] == 0.0
        assert body["recommended_model"]  # env default
    finally:
        registry.model_router = saved


def test_router_booted_at_lifespan(client_shape):
    client, registry = client_shape
    assert registry.model_router is not None
    default = registry.model_router.get_default()
    assert default is not None
    assert default.tier.value == "balanced"
    assert default.category == "general"


def test_decide_single_model_consistent_across_complexities(client_shape):
    client, registry = client_shape
    short = _decide(client, task="tiny", category="general")
    long_task = _decide(client, task="z" * 500, category="general")
    # single BALANCED model → same pick at any complexity; wire is sane.
    assert short["recommended_model"] == long_task["recommended_model"]
    assert short["confidence"] > 0 and long_task["confidence"] > 0


def test_substrate_complexity_token_estimate():
    """Substrate check: complexity → estimated_tokens = max(256, 512*n)."""
    from kernel.routing import ModelProfile, ModelRouter, ModelTier, TaskCategory

    r = ModelRouter()
    r.register_model(ModelProfile(
        name="m", api_base="http://x", model_name="m",
        tier=ModelTier.BALANCED, category="general", is_default=True,
    ))
    # max(256, complexity*512); complexity floor is 1 → 512.
    assert r.route(TaskCategory.MISC, complexity=5).estimated_tokens == 2560
    assert r.route(TaskCategory.MISC, complexity=1).estimated_tokens == 512
