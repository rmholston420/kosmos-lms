"""ADR-141 R7 / R8 — kernel-native self-repair routes (donor fidelity).

Closes the ADR-139 gateway split: the four donor endpoints
(``main.py:3055-3106`` on :8020) are now served by the kernel against
the DI-wired ``kernel.reliability`` engine daemon:

- ``GET  /api/self_repair/status`` — dual-surface envelope: ``engine``
  (the executing daemon: running/uptime/counts/effectiveness/latest_health)
  + ``proposer`` (ADR-095 propose-only) + static 19-label strategy catalog.
- ``GET  /api/self_repair/history`` — donor ``{"history": [...]}`` envelope.
- ``POST /api/self_repair/repair`` — donor ``{"record": ...}`` envelope;
  accepts both the UI ``{"note": ...}`` shape (→ manual_check at
  severity 1, note in ctx) and the donor threat_category/severity/ctx shape
  (passed through untouched).
- ``POST /api/self_repair/health`` — donor HealthSnapshot envelope; all
  scores optional, invalid payload → 400.

The registry is faked per test (a duck-typed engine recording its call
args) — no daemon thread, no GPU, no network.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from kernel.app import app, registry


class _FakeRecord:
    def __init__(self, args: tuple[str, int, dict[str, Any]]) -> None:
        self._args = args

    def to_dict(self) -> dict[str, Any]:
        category, severity, ctx = self._args
        return {
            "record_id": "rec-test",
            "threat_category": category,
            "threat_severity": str(severity),
            "description": f"fake {category}",
            "status": "completed",
            "strategy_used": "throttle_workload",
            "verification_passed": True,
            "degradation_applied": "reduced",
            "created_at": 1_750_000_000.0,
            "ctx": ctx,
        }


class _FakeSnapshot:
    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": 0.68,
            "status": "warning",
            "gpu_score": 0.4,
            "active_threats": 2,
        }


class _FakeEngine:
    """Duck-typed stand-in for kernel.reliability.SelfRepairEngine."""

    def __init__(
        self,
        *,
        running: bool = True,
        status: dict[str, Any] | None = None,
        status_exc: type[Exception] | None = None,
        records: list[dict[str, Any]] | None = None,
        repair_exc: type[Exception] | None = None,
    ) -> None:
        self._running = running
        self._status = status or {
            "running": running,
            "uptime_seconds": 42.0,
            "total_repairs": 3,
            "completed_repairs": 2,
            "failed_repairs": 1,
            "degraded_repairs": 0,
            "strategies_registered": 8,
            "workflows_registered": 6,
            "effectiveness": {"success_rate": 0.66},
            "latest_health": {"overall_score": 0.9, "status": "healthy"},
            "health_trend": [0.95, 0.9, 0.9],
        }
        self._status_exc = status_exc
        self._records = records or [
            {
                "record_id": "rec-1",
                "threat_category": "resource_exhaustion",
                "threat_severity": "3",
                "description": "fake donor-shape repair",
                "status": "completed",
                "strategy_used": "throttle_workload",
                "verification_passed": True,
                "degradation_applied": "none",
                "created_at": 1_750_000_000.0,
            }
        ]
        self.repair_exc = repair_exc
        self.repair_calls: list[tuple[str, int, dict[str, Any]]] = []

    def get_status(self) -> dict[str, Any]:
        if self._status_exc is not None:
            raise self._status_exc("boom")
        return self._status

    def get_repair_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._records[-limit:]

    async def repair_threat(
        self, category: str, severity: int, ctx: dict[str, Any]
    ) -> _FakeRecord:
        if self.repair_exc is not None:
            raise self.repair_exc("boom")
        self.repair_calls.append((category, severity, ctx))
        return _FakeRecord((category, severity, ctx))

    async def manual_health_check(self, **kw: Any) -> _FakeSnapshot:
        return _FakeSnapshot()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_engine(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(registry, "self_repair", None, raising=False)
    monkeypatch.setattr(registry, "errors", {"self_repair": None}, raising=False)


# ---------------------------------------------------------------------------
# /api/self_repair/status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_engine_wired_reports_daemon_truth(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry, "self_repair", _FakeEngine(), raising=False)
        r = client.get("/api/self_repair/status")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "initialized"
        assert body["healthy"] is True
        eng = body["engine"]
        assert eng["wired"] is True
        assert eng["running"] is True
        assert eng["uptime_seconds"] == 42.0
        assert eng["total_repairs"] == 3
        assert eng["completed_repairs"] == 2
        assert eng["strategies_registered"] == 8
        assert eng["workflows_registered"] == 6
        assert eng["effectiveness"]["success_rate"] == 0.66
        assert eng["latest_health"]["status"] == "healthy"
        assert body["strategies"]["strategies_registered"] == 19
        assert body["errors"] == []

    def test_unwired_engine_honest_degrade(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry, "errors", {"self_repair": "ctor failed"}, raising=False)
        r = client.get("/api/self_repair/status")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert body["healthy"] is False
        assert body["engine"]["wired"] is False
        assert "ctor failed" in body["engine"]["note"]

    def test_engine_error_surfaces_not_500(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            registry, "self_repair", _FakeEngine(status_exc=RuntimeError), raising=False
        )
        r = client.get("/api/self_repair/status")
        assert r.status_code == 200
        body = r.json()
        assert body["healthy"] is False
        assert any("boom" in e for e in body["errors"])


# ---------------------------------------------------------------------------
# /api/self_repair/history
# ---------------------------------------------------------------------------


class TestHistory:
    def test_unwired_honest_empty(self, client: TestClient) -> None:
        r = client.get("/api/self_repair/history")
        assert r.status_code == 200
        assert r.json() == {"error": "Self-repair engine not initialized", "history": []}

    def test_donor_envelope(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry, "self_repair", _FakeEngine(), raising=False)
        r = client.get("/api/self_repair/history")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body["history"], list)
        assert body["history"][0]["record_id"] == "rec-1"
        assert body["history"][0]["status"] == "completed"

    def test_limit_respected(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _FakeEngine()
        engine._records = [{"record_id": f"rec-{i}"} for i in range(10)]
        monkeypatch.setattr(registry, "self_repair", engine, raising=False)
        body = client.get("/api/self_repair/history?limit=3").json()
        assert len(body["history"]) == 3
        assert body["history"][-1]["record_id"] == "rec-9"


# ---------------------------------------------------------------------------
# /api/self_repair/repair
# ---------------------------------------------------------------------------


class TestRepair:
    def test_unwired_honest_error(self, client: TestClient) -> None:
        r = client.post("/api/self_repair/repair", json={})
        assert r.status_code == 200
        assert r.json() == {"error": "Self-repair engine not initialized"}

    def test_ui_note_shape_maps_to_manual_check(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _FakeEngine()
        monkeypatch.setattr(registry, "self_repair", engine, raising=False)
        r = client.post("/api/self_repair/repair", json={"note": "GPU pegged hot"})
        assert r.status_code == 200
        body = r.json()
        assert "record" in body
        category, severity, ctx = engine.repair_calls[0]
        assert category == "manual_check"
        assert severity == 1
        assert ctx["note"] == "GPU pegged hot"

    def test_donor_shape_passthrough(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _FakeEngine()
        monkeypatch.setattr(registry, "self_repair", engine, raising=False)
        r = client.post(
            "/api/self_repair/repair",
            json={
                "threat_category": "resource_exhaustion",
                "threat_severity": 3,
                "ctx": {"vram_pct": 0.9, "gpu_temp_c": 95},
            },
        )
        assert r.status_code == 200
        category, severity, ctx = engine.repair_calls[0]
        assert category == "resource_exhaustion"
        assert severity == 3
        assert ctx["vram_pct"] == 0.9

    def test_record_envelope_carries_engine_data(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry, "self_repair", _FakeEngine(), raising=False)
        r = client.post(
            "/api/self_repair/repair",
            json={"threat_category": "resource_exhaustion", "threat_severity": 3},
        )
        rec = r.json()["record"]
        assert rec["strategy_used"] == "throttle_workload"
        assert rec["status"] == "completed"
        assert rec["verification_passed"] is True

    def test_engine_failure_is_500(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            registry, "self_repair", _FakeEngine(repair_exc=RuntimeError), raising=False
        )
        r = client.post("/api/self_repair/repair", json={"note": "x"})
        assert r.status_code == 500

    def test_invalid_severity_is_400(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            registry, "self_repair", _FakeEngine(repair_exc=ValueError), raising=False
        )
        r = client.post(
            "/api/self_repair/repair",
            json={"threat_category": "x", "threat_severity": "not-a-number"},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# /api/self_repair/health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_unwired_honest_error(self, client: TestClient) -> None:
        r = client.post("/api/self_repair/health", json={})
        assert r.status_code == 200
        assert r.json() == {"error": "Self-repair engine not initialized"}

    def test_defaults_all_healthy(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry, "self_repair", _FakeEngine(), raising=False)
        r = client.post("/api/self_repair/health", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["overall_score"] == 0.68
        assert body["status"] == "warning"

    def test_scores_pass_through(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _FakeEngine()
        seen: dict[str, Any] = {}

        async def _capture(**kw: Any) -> _FakeSnapshot:
            seen.update(kw)
            return _FakeSnapshot()

        engine.manual_health_check = _capture  # type: ignore[method-assign]
        monkeypatch.setattr(registry, "self_repair", engine, raising=False)
        r = client.post(
            "/api/self_repair/health",
            json={
                "gpu_score": 0.4,
                "active_threats": 2,
                "failed_repairs_24h": 1,
            },
        )
        assert r.status_code == 200
        assert seen["gpu_score"] == 0.4
        assert seen["active_threats"] == 2
        assert seen["failed_repairs_24h"] == 1
        # Route defaults for unspecified fields:
        assert seen["context_score"] == 1.0
        assert seen["pending_repairs"] == 0

    def test_invalid_score_is_400(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        engine = _FakeEngine()

        async def _raise(**kw: Any) -> _FakeSnapshot:
            # Simulates the route's float(...) conversion failing on a
            # non-numeric score; the route maps ValueError → 400.
            raise ValueError("could not convert string to float: 'hot'")

        engine.manual_health_check = _raise  # type: ignore[method-assign]
        monkeypatch.setattr(registry, "self_repair", engine, raising=False)
        r = client.post("/api/self_repair/health", json={"gpu_score": "hot"})
        assert r.status_code == 400
