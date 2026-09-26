"""Stage 11.9 — ADR-125 skills tests: /api/skills/stats.

Kernel-native Tektos skill-candidate status (replaces the ADR-109 gateway
proxy to :8020, whose 24-skill manager has no kernel referent). The kernel's
real skills-adjacent surface is the Tektos Manager archetype tracker
(ADR-108): recurring task patterns flagged as skill candidates at
threshold. The full donor skill registry stays deferred (ADR-108 D9) —
the endpoint must report that honestly, never fabricate a count.

Tests run GPU-free: no network, no Postgres. The registry is faked per
test; the tracker is the REAL ``ArchetypeTracker`` (plugin-internal, but
importable — serialization must work against the actual frozen dataclasses).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kernel.app import app
from plugins.tektos.manager.archetype_tracker import ArchetypeTracker


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kernel.app import registry

    # Isolate: no manager by default (the ADR-108 off state) AND no donor
    # skill registry (Stage 14.6: the substrate boots by default now, so
    # the degraded-shape tests must explicitly turn it off — the endpoint
    # then falls back to the "deferred (ADR-108 D9)" note).
    monkeypatch.setattr(registry, "tektos_manager", None, raising=False)
    monkeypatch.setattr(registry, "tektos_skills", None, raising=False)
    return TestClient(app)


def _fake_manager(tracker: object):
    """Duck-typed TektosManager stand-in exposing ``.archetypes``."""

    class _M:
        archetypes = tracker

    return _M()


# ── Degraded state (manager off — the default) ────────────────────────────


def test_skills_manager_off_degraded(client: TestClient) -> None:
    r = client.get("/api/skills/stats")
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "degraded"
    assert o["healthy"] is False
    assert o["skills"]["wired"] is False
    assert o["skills"]["archetypes"] == 0
    assert o["skills"]["at_threshold"] == 0
    assert o["skills"]["threshold"] is None
    assert o["skills"]["total_events"] is None
    # Honest: the deferred-registry note is present, no fabricated counts.
    # Stage 14.6: registry is a dict now (donor substrate live) — off-state
    # keeps the "deferred (ADR-108 D9)" note inside it.
    assert isinstance(o["skills"]["registry"], dict)
    assert o["skills"]["registry"]["wired"] is False
    assert "ADR-108 D9" in o["skills"]["registry"]["note"]
    assert o["errors"] == []


# ── Wired state (manager on) — real tracker data ──────────────────────────


def test_skills_manager_wired_empty_tracker(client: TestClient) -> None:
    from kernel.app import registry

    registry.tektos_manager = _fake_manager(ArchetypeTracker(threshold=3))
    try:
        r = client.get("/api/skills/stats")
    finally:
        registry.tektos_manager = None
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "initialized"
    assert o["healthy"] is True
    assert o["skills"]["wired"] is True
    assert o["skills"]["archetypes"] == 0
    assert o["skills"]["at_threshold"] == 0
    assert o["skills"]["threshold"] == 3
    assert o["skills"]["total_events"] == 0
    assert o["errors"] == []


def test_skills_archetype_at_threshold(client: TestClient) -> None:
    from kernel.app import registry

    tracker = ArchetypeTracker(threshold=3)
    for _ in range(3):
        tracker.record_event(
            "error_handling", "repeated timeout on retry", severity="warning"
        )
    tracker.record_event(
        "file_operations", "one-off write", severity="info"
    )
    registry.tektos_manager = _fake_manager(tracker)
    try:
        o = client.get("/api/skills/stats").json()
    finally:
        registry.tektos_manager = None

    assert o["healthy"] is True
    assert o["skills"]["archetypes"] == 2
    assert o["skills"]["at_threshold"] == 1
    assert o["skills"]["total_events"] == 4
    assert o["skills"]["threshold"] == 3

    # Sorted by occurrence_count desc: error_handling (3) first.
    top = o["skills"]["archetype_list"][0]
    assert top["category"] == "error_handling"
    assert top["occurrence_count"] == 3
    assert top["at_threshold"] is True
    assert top["permanent_structure_id"] is None  # ADR-108 D9: none created
    assert top["first_seen"] is not None
    assert top["last_seen"] is not None

    second = o["skills"]["archetype_list"][1]
    assert second["category"] == "file_operations"
    assert second["occurrence_count"] == 1
    assert second["at_threshold"] is False


def test_skills_archetype_with_structure_not_at_threshold(client: TestClient) -> None:
    from kernel.app import registry

    tracker = ArchetypeTracker(threshold=2)
    for _ in range(2):
        tracker.record_event("git", "repeated merge conflict", severity="warning")
    # A permanent structure exists → no longer a candidate (donor invariant).
    tracker.mark_structure_created("git", "skill:git-merge-heal")
    registry.tektos_manager = _fake_manager(tracker)
    try:
        o = client.get("/api/skills/stats").json()
    finally:
        registry.tektos_manager = None

    assert o["skills"]["at_threshold"] == 0
    top = o["skills"]["archetype_list"][0]
    assert top["at_threshold"] is False
    assert top["permanent_structure_id"] == "skill:git-merge-heal"


# ── Failure paths ──────────────────────────────────────────────────────────


def test_skills_manager_without_tracker_degrades(client: TestClient) -> None:
    from kernel.app import registry

    class _Bare:  # manager handle with no archetype tracker
        pass

    registry.tektos_manager = _Bare()
    try:
        o = client.get("/api/skills/stats").json()
    finally:
        registry.tektos_manager = None
    assert o["healthy"] is True  # manager wired; the tracker gap is an error, not a 500
    assert o["skills"]["wired"] is True
    assert any("tracker" in e for e in o["errors"])


def test_skills_tracker_raising_degrades(client: TestClient) -> None:
    from kernel.app import registry

    class _BoomTracker:
        threshold = 3
        events = []

        def get_active_archetypes(self):
            raise RuntimeError("simulated tracker failure")

    registry.tektos_manager = _fake_manager(_BoomTracker())
    try:
        r = client.get("/api/skills/stats")
    finally:
        registry.tektos_manager = None
    assert r.status_code == 200  # never 500
    o = r.json()
    assert any("simulated tracker failure" in e for e in o["errors"])
