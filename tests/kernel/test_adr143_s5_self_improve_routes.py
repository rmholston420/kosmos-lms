"""ADR-143 T3 / S5b — kernel-native self-improvement routes (live TestClient).

Donor wire-shape fidelity for the five ``/api/self_improvement/*`` routes
that replace the :8020 gateway proxy (tektos-ultima-v1 main.py:3144-3166,
4555-4588). These are READ-route tests: the ledger + meta-learning stores
are seeded with donor wire shapes (``ExperienceRecord.to_json`` / the
donor ``meta_learning.json`` layout) so the routes' serialization is the
thing under test. The WRITE path (``on_session_completed`` evaluate →
reflect → meta-learn → benchmark → ledger) is covered separately by the
S2 engine suite (16/16) and is NOT re-exercised here (it would drag live
Hindsight/Valkey network calls into a fast route test).

One module-scoped lifespan boot (in-memory memory backend) serves all
tests — no per-test re-boot.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from kernel import app as ka  # noqa: E402
from kernel.learning.models import ExperienceRecord  # noqa: E402

MODEL = "qwen3.8-27b-code"


@pytest.fixture(scope="module")
def tc():
    """One lifespan boot for the whole module (the registry is stable)."""
    ka.registry.errors.clear()
    client = TestClient(ka.app)
    with client:
        yield client


def _seed_engine(tmp_path: Path, session_ids) -> None:
    """Point the booted engine at ``tmp_path`` stores with donor wire shapes."""
    engine = ka.registry.tektos_learning
    assert engine is not None, "learning substrate not booted"
    engine.experience_db = tmp_path / "experience.jsonl"
    engine.meta_learning_db = tmp_path / "meta_learning.json"
    engine.benchmark_dir = tmp_path / "benchmarks"
    engine.benchmark_dir.mkdir(parents=True, exist_ok=True)

    # Donor ExperienceRecord wire, oldest→newest (the donor get_experience
    # returns records[:top_k] in file order — oldest first).
    lines = []
    for i, sid in enumerate(session_ids):
        rec = ExperienceRecord(
            session_id=sid,
            task=f"build task {i}",
            model_used=MODEL,
            success=(i % 2 == 0),
            tests_passed=4 if i % 2 == 0 else 0,
            tests_total=4,
            wall_time_seconds=12.5,
            evaluation_score=0.7,
        )
        lines.append(rec.to_json())
    engine.experience_db.write_text("\n".join(lines) + "\n")

    # Donor meta_learning.json wire (get_learning_metrics reads this).
    meta = {
        "learning_metrics": {
            "total_tasks": len(session_ids),
            "total_improvements": 1,
        },
        "model_performance": {
            MODEL: {
                "task_types": {
                    "coding": {
                        "tasks": len(session_ids),
                        "successes": 1,
                        "total_quality": 0.7 * len(session_ids),
                    }
                }
            }
        },
    }
    engine.meta_learning_db.write_text(json.dumps(meta))


# ---------------------------------------------------------------------------
# Wiring (S5a regression guard)
# ---------------------------------------------------------------------------


def test_substrate_and_driver_booted(tc):
    reg = ka.registry
    assert reg.tektos_learning is not None, "learning substrate missing"
    assert reg.tektos_self_improve is not None, "learning driver missing"
    assert "self_improvement" not in reg.errors


def test_driver_default_off_queue_only(tc):
    driver = ka.registry.tektos_self_improve
    assert driver.enabled is False  # env gate default off
    assert driver.running is False  # no background task
    assert driver.loop_ready is True  # loop injected at boot (S5a)


# ---------------------------------------------------------------------------
# /status — donor field set (main.py:4575-4588)
# ---------------------------------------------------------------------------


def test_status_donor_fields(tc):
    r = tc.get("/api/self_improvement/status")
    assert r.status_code == 200
    body = r.json()
    for field in ("enabled", "orchestrator_ready", "pending", "interval_seconds"):
        assert field in body, f"missing donor field {field}"
    assert body["enabled"] is False  # gate default off
    assert body["orchestrator_ready"] is True  # loop wired
    assert body["pending"] == 0
    assert body["interval_seconds"] == 1800.0
    # kernel enrichment (superset of the donor shape)
    assert body["queue_length"] == 0
    assert "recent_cycles" in body
    assert "loop_health" in body


# ---------------------------------------------------------------------------
# /enqueue — donor wire (main.py:4555-4573)
# ---------------------------------------------------------------------------


def test_enqueue_requires_prompt(tc):
    r = tc.post("/api/self_improvement/enqueue", json={"prompt": "  "})
    assert r.status_code == 200
    body = r.json()
    assert body["queued"] is False
    assert body["error"] == "prompt is required"


def test_enqueue_queues_and_status_reflects_depth(tc):
    driver = ka.registry.tektos_self_improve
    driver._queue.clear()  # noqa: SLF001 — isolate between tests
    try:
        b1 = tc.post(
            "/api/self_improvement/enqueue", json={"prompt": "cycle A"}
        ).json()
        assert b1["queued"] is True
        assert b1["pending"] == 1
        b2 = tc.post(
            "/api/self_improvement/enqueue", json={"prompt": "cycle B"}
        ).json()
        assert b2["pending"] == 2
        s = tc.get("/api/self_improvement/status").json()
        assert s["pending"] == 2  # donor field mirrors queue depth
        assert s["queue_length"] == 2
    finally:
        driver._queue.clear()  # noqa: SLF001


class _FakeCycle:
    cycle_id = "fake-cycle"
    status = "completed"
    syntheses: list = []
    experience_stored: list = []
    duration_seconds = 0.01
    error = None


class _FakeLoop:
    """Stands in for the Hegelian loop so run_now doesn't hit the real LLM."""

    def run(self, prompt: str):
        return _FakeCycle()

    def get_loop_health(self):
        return {"cycles": 0}

    def __len__(self):
        return 0


def test_enqueue_run_now_returns_cycle_summary(tc):
    """run_now=true executes one cycle and returns its summary (kernel add)."""
    driver = ka.registry.tektos_self_improve
    original = driver._loop
    driver._queue.clear()  # noqa: SLF001
    try:
        driver.set_loop(_FakeLoop())
        body = tc.post(
            "/api/self_improvement/enqueue",
            json={"prompt": "run me", "run_now": True},
        ).json()
    finally:
        driver.set_loop(original)
        driver._queue.clear()  # noqa: SLF001
    assert body["queued"] is True
    assert "cycle" in body
    summary = body["cycle"]
    assert summary["status"] == "completed"
    assert summary["id"] == "fake-cycle"


# ---------------------------------------------------------------------------
# /metrics, /report, /experiences — donor read API wire
# ---------------------------------------------------------------------------


def test_metrics_wire(tc, tmp_path):
    _seed_engine(tmp_path, ["m-0", "m-1"])
    m = tc.get("/api/self_improvement/metrics").json()
    # UI reads exactly these (donor get_learning_metrics keys)
    for field in (
        "total_tasks",
        "total_improvements",
        "learning_velocity",
        "model_rankings",
        "best_model_for_coding",
    ):
        assert field in m, f"missing metrics field {field}"
    assert m["total_tasks"] == 2
    assert isinstance(m["model_rankings"], list)
    assert m["best_model_for_coding"] == MODEL


def test_report_wire(tc, tmp_path):
    _seed_engine(tmp_path, ["r-0"])
    body = tc.get("/api/self_improvement/report").json()
    assert "report" in body
    assert isinstance(body["report"], str)
    assert "SELF-IMPROVEMENT REPORT" in body["report"]


def test_experiences_wire(tc, tmp_path):
    _seed_engine(tmp_path, ["e-0", "e-1", "e-2"])
    body = tc.get("/api/self_improvement/experiences?top_k=10").json()
    assert "experiences" in body
    exps = body["experiences"]
    assert len(exps) == 3
    first = exps[0]
    # donor ExperienceRecord.to_dict() (asdict) wire — exact keys
    for field in ("session_id", "task", "model_used", "success", "created_at"):
        assert field in first, f"experience missing donor field {field}"
    # donor get_experience returns file order (oldest first)
    assert first["session_id"] == "e-0"
    assert first["task"] == "build task 0"
    assert first["model_used"] == MODEL
    # engine reads the same ledger back (real parse, not the raw file)
    rec = ka.registry.tektos_learning.get_experience(top_k=3)[0]
    assert rec.session_id == "e-0"
    assert isinstance(rec.evaluation_score, float)
