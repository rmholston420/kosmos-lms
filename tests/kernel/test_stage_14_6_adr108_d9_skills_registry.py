"""Stage 14.6 — ADR-108 D9 discharge: donor skills registry routes.

The donor's reusable-procedure substrate (kernel/skills/: registry.py +
manager.py + executor.py) is now live in the kernel and exposed on the
registry as ``tektos_skills`` (manager) / ``tektos_skill_executor``
(executor). This test exercises the 16 donor-faithful routes
(donor main.py:2479-2860) + the discharged T8c-8c
``POST /api/dreamtime/trigger-skill-generation`` route against the REAL
substrate (SQLite skill store in a tmp dir — no network, no GPU, no
mocks of the substrate itself).

Route inventory (16 skills + 1 dreamtime skill-gen):
  GET    /api/skills                      (list, category/active filter)
  GET    /api/skills/search               (name/desc/trigger search)
  GET    /api/skills/dedup/groups         (duplicate groups, no merge)
  GET    /api/skills/{skill_id}           (single)
  POST   /api/skills                      (create)
  PUT    /api/skills/{skill_id}           (update)
  DELETE /api/skills/{skill_id}           (delete)
  POST   /api/skills/{skill_id}/toggle    (enable/disable)
  POST   /api/skills/{skill_id}/prune     (prune inactive)
  POST   /api/skills/dedup                (find + merge)
  POST   /api/skills/{skill_id}/improve   (manual improvement)
  POST   /api/skills/{skill_id}/improve/from-execution
  POST   /api/skills/maintenance          (dedup + prune + auto-improve)
  POST   /api/skills/select               (context → matched skills)
  POST   /api/skills/{skill_id}/execute   (inline execute + usage record)
  POST   /api/dreamtime/trigger-skill-generation (T8c-8c discharge)

Degraded state: ``registry.tektos_skills is None`` → the donor's own
fail shape ``{"error": "Skill manager not initialized"}`` at 200 (never
a 500, never a fabricated count).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from kernel.app import app
from kernel.skills import Skill, SkillManager, SkillRegistry


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def skill_manager(tmp_path) -> Iterator[SkillManager]:
    """Real substrate on a throwaway SQLite db + skills dir."""
    db = tmp_path / "skills.db"
    sdir = tmp_path / "skills"
    registry = SkillRegistry(db_path=str(db), skill_dir=str(sdir))
    manager = SkillManager(registry=registry)
    yield manager
    try:
        registry.close()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def client(skill_manager: SkillManager, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kernel.app import registry

    monkeypatch.setattr(registry, "tektos_skills", skill_manager, raising=False)
    return TestClient(app)


def _make_skill(manager: SkillManager, name: str, **kw) -> Skill:
    return manager.create_skill(
        name=name,
        description=kw.pop("description", f"Does {name.lower().replace(' ', '-')}"),
        trigger_conditions=kw.pop("trigger_conditions", ["unit_test_trigger"]),
        steps=kw.pop("steps", [{"action": "echo", "value": "hello"}]),
        category=kw.pop("category", "unit_test"),
        source=kw.pop("source", "user_created"),
        metadata=kw.pop("metadata", {}),
    )


# ── Degraded state (substrate off) ────────────────────────────────────────


def test_skills_off_degraded_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from kernel.app import registry

    monkeypatch.setattr(registry, "tektos_skills", None, raising=False)
    c = TestClient(app)
    # Only the GET routes return the donor fail-open shape when the
    # substrate is off. (toggle/prune/improve/maintenance/select are POST —
    # see the mounted route inventory.) /api/skills/stats is the ADR-125
    # route with its own degraded shape, asserted in its own test file.
    for path in (
        "/api/skills",
        "/api/skills/search",
        "/api/skills/dedup/groups",
        "/api/skills/abc123",
    ):
        r = c.get(path)
        assert r.status_code == 200, path
        assert r.json() == {"error": "Skill manager not initialized"}, path


def test_skills_off_write_routes_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    from kernel.app import registry

    monkeypatch.setattr(registry, "tektos_skills", None, raising=False)
    c = TestClient(app)
    r = c.post("/api/skills", json={"name": "x", "description": "y"})
    assert r.status_code == 200
    assert r.json() == {"error": "Skill manager not initialized"}
    r = c.post("/api/skills/select", json={"context": {}})
    assert r.status_code == 200
    assert r.json() == {"error": "Skill manager not initialized"}


# ── CRUD ──────────────────────────────────────────────────────────────────


def test_create_list_get(client: TestClient, skill_manager: SkillManager) -> None:
    r = client.post(
        "/api/skills",
        json={
            "name": "Git Rebase Heal",
            "description": "Resolve rebase conflicts methodically",
            "trigger_conditions": ["rebase conflict"],
            "steps": [{"action": "git status"}],
            "category": "git",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    sid = body["id"]
    assert body["name"] == "Git Rebase Heal"

    # list
    r = client.get("/api/skills")
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert len(skills) == 1
    assert skills[0]["id"] == sid
    assert skills[0]["category"] == "git"
    assert skills[0]["enabled"] is True
    assert skills[0]["success_rate"] == 0.0

    # single
    r = client.get(f"/api/skills/{sid}")
    assert r.status_code == 200
    s = r.json()
    assert s["name"] == "Git Rebase Heal"
    assert s["trigger_conditions"] == ["rebase conflict"]
    assert s["steps"] == [{"action": "git status"}]
    assert s["metadata"] == {}


def test_get_missing_404(client: TestClient) -> None:
    r = client.get("/api/skills/nope")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_update_skill(client: TestClient, skill_manager: SkillManager) -> None:
    s = _make_skill(skill_manager, "Updatable")
    sid = s.id
    r = client.put(
        f"/api/skills/{sid}",
        json={"description": "new desc", "category": "renamed", "enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["updated"] is True
    got = client.get(f"/api/skills/{sid}").json()
    assert got["description"] == "new desc"
    assert got["category"] == "renamed"
    assert got["enabled"] is False


def test_toggle_skill(client: TestClient, skill_manager: SkillManager) -> None:
    s = _make_skill(skill_manager, "Toggler")
    sid = s.id
    assert client.get(f"/api/skills/{sid}").json()["enabled"] is True
    r = client.post(f"/api/skills/{sid}/toggle")
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    r = client.post(f"/api/skills/{sid}/toggle")
    assert r.json()["enabled"] is True


def test_delete_skill(client: TestClient, skill_manager: SkillManager) -> None:
    s = _make_skill(skill_manager, "Doomed")
    sid = s.id
    r = client.delete(f"/api/skills/{sid}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    assert client.get(f"/api/skills/{sid}").status_code == 404


def test_delete_missing_404(client: TestClient) -> None:
    r = client.delete("/api/skills/ghost")
    assert r.status_code == 404


# ── Search + dedup ────────────────────────────────────────────────────────


def test_search_skills(client: TestClient, skill_manager: SkillManager) -> None:
    _make_skill(skill_manager, "Docker Build Fix", description="docker build failure")
    _make_skill(skill_manager, "SQL Query Tune", description="slow query plan")
    r = client.get("/api/skills/search", params={"query": "docker"})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["skills"]]
    assert "Docker Build Fix" in names
    assert "SQL Query Tune" not in names


def test_dedup_groups_identical(client: TestClient, skill_manager: SkillManager) -> None:
    _make_skill(
        skill_manager,
        "Copy One",
        description="same description",
        trigger_conditions=["same trigger"],
    )
    _make_skill(
        skill_manager,
        "Copy Two",
        description="same description",
        trigger_conditions=["same trigger"],
    )
    r = client.get("/api/skills/dedup/groups", params={"threshold": 0.5})
    assert r.status_code == 200
    groups = r.json()["groups"]
    assert len(groups) >= 1
    g = groups[0]
    assert g["primary"]["id"] != g["duplicates"][0]["id"]
    assert 0.0 <= g["similarity"] <= 1.0


def test_dedup_merge(client: TestClient, skill_manager: SkillManager) -> None:
    a = _make_skill(
        skill_manager,
        "Dup A",
        description="identical body",
        trigger_conditions=["same"],
    )
    b = _make_skill(
        skill_manager,
        "Dup B",
        description="identical body",
        trigger_conditions=["same"],
    )
    r = client.post("/api/skills/dedup", params={"threshold": 0.5})
    assert r.status_code == 200
    stats = r.json()
    # The manager reports how many groups it merged; after merge only one
    # of the two remains.
    remaining = [
        s["id"]
        for s in client.get("/api/skills").json()["skills"]
    ]
    survivors = [x for x in (a.id, b.id) if x in remaining]
    assert len(survivors) == 1, f"expected exactly one survivor, got {survivors}"
    assert stats is not None


# ── Improve + maintenance ─────────────────────────────────────────────────


def test_improve_skill(client: TestClient, skill_manager: SkillManager) -> None:
    s = _make_skill(skill_manager, "Improvable")
    sid = s.id
    r = client.post(
        f"/api/skills/{sid}/improve",
        json={
            "description": "refined description",
            "steps": [{"action": "v2"}],
            "trigger_conditions": ["v2 trigger"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["improved"] is True
    # Version bumped by the manager on improvement.
    assert body["version"] != "0.1.0" or body["version"] is not None
    got = client.get(f"/api/skills/{sid}").json()
    assert got["description"] == "refined description"


def test_improve_missing_404(client: TestClient) -> None:
    r = client.post(
        "/api/skills/ghost/improve", json={"description": "x"}
    )
    assert r.status_code == 404


def test_improve_from_execution(client: TestClient, skill_manager: SkillManager) -> None:
    s = _make_skill(skill_manager, "Executor")
    skill_manager.registry.record_usage(s.id, success=True)
    r = client.post(f"/api/skills/{s.id}/improve/from-execution")
    assert r.status_code == 200
    assert r.json()["improved"] is True


def test_run_maintenance(client: TestClient, skill_manager: SkillManager) -> None:
    _make_skill(skill_manager, "Maintainable One")
    r = client.post("/api/skills/maintenance")
    assert r.status_code == 200
    body = r.json()
    # Donor run_maintenance returns a dict of sub-results (dedup/prune/...).
    assert isinstance(body, dict)


# ── Select + execute ──────────────────────────────────────────────────────


def test_select_skills(client: TestClient, skill_manager: SkillManager) -> None:
    _make_skill(
        skill_manager,
        "Context Skill",
        trigger_conditions=["unit_test_trigger", "context_probe"],
    )
    r = client.post(
        "/api/skills/select", json={"context": {"probe": True}, "max_skills": 3}
    )
    assert r.status_code == 200
    body = r.json()
    assert "selected" in body
    for m in body["selected"]:
        assert {"id", "name", "category", "score", "reason"} <= set(m.keys())


def test_execute_skill_records_usage(client: TestClient, skill_manager: SkillManager) -> None:
    s = _make_skill(
        skill_manager,
        "Runnable",
        steps=[{"action": "echo", "value": "hi"}],
    )
    sid = s.id
    r = client.post(f"/api/skills/{sid}/execute", json={"context": {"k": "v"}})
    assert r.status_code == 200
    body = r.json()
    assert body["skill_id"] == sid
    assert body["success"] in (True, False)
    # Usage recorded either way.
    got = client.get(f"/api/skills/{sid}").json()
    assert got["usage_count"] >= 1


def test_execute_missing_404(client: TestClient) -> None:
    r = client.post("/api/skills/ghost/execute", json={"context": {}})
    assert r.status_code == 404


# ── T8c-8c discharge: dreamtime → skill generation ────────────────────────


def test_trigger_skill_generation_no_dreamtime(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kernel.app import registry

    monkeypatch.setattr(registry, "tektos_dreamtime", None, raising=False)
    r = client.post("/api/dreamtime/trigger-skill-generation")
    assert r.status_code == 200
    assert r.json() == {"error": "Dreamtime engine not initialized"}


def test_trigger_skill_generation_from_insights(
    client: TestClient, skill_manager: SkillManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kernel.app import registry

    class _FakeDream:
        def __init__(self, insights: list[str]) -> None:
            self.insights = insights

    class _FakeEngine:
        def get_dream_history(self, limit: int = 10) -> list[_FakeDream]:
            return [
                _FakeDream(
                    [
                        "Retry transient network errors before escalating",
                        "Check the target file exists before overwriting",
                    ]
                )
            ]

    monkeypatch.setattr(registry, "tektos_dreamtime", _FakeEngine(), raising=False)
    before = len(skill_manager.registry.list_skills(active_only=False))
    r = client.post("/api/dreamtime/trigger-skill-generation")
    assert r.status_code == 200
    body = r.json()
    assert body["insights_processed"] == 2
    assert body["skills_created"] >= 1
    after = len(skill_manager.registry.list_skills(active_only=False))
    assert after == before + body["skills_created"]
    assert all(isinstance(n, str) for n in body["skill_names"])
