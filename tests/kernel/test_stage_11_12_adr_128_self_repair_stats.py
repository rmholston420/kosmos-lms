"""Stage 11.12 — ADR-128 self_repair tests: /api/self_repair/status.

Kernel-native self-repair truth (replaces the ADR-109 gateway proxy to
:8020). EXTENDED by ADR-141 R7 to a dual-surface envelope:

- ``engine`` — the executing daemon (kernel.reliability, ADR-142) when
  booted; ``engine.wired: false`` is the honest test-default.
- ``proposer`` — the older propose-only ADR-095 surface (HUMAN_REQUIRED
  approval tier).
- ``strategies`` — the static 19-label catalog (vendored RepairStrategy).

``healthy`` / ``status`` now track the EXECUTING daemon, not the proposer
(After R7 the kernel executes — "not wired in kernel" no longer holds).

Tests run GPU-free: no network, no Postgres. The registry is faked per
test; the proposer is the REAL ``SelfRepairProposer`` (faked ports —
propose-only, so nothing executes); the engine is a duck-typed fake.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from kernel.app import app


class _FakePort:
    """Minimal stand-in for ApprovalGatewayPort / MemoryPort / EventBusPort.

    The SelfRepairProposer is duck-typed at runtime (uses only
    ``propose`` / memory writes / ``publish``); the port protocols are
    structural, so we cast to ``Any`` at the constructor boundary.
    """

    async def propose(self, *a: Any, **kw: Any) -> Any:
        return None

    async def publish(self, *a: Any, **kw: Any) -> Any:
        return None

    async def write_event(self, *a: Any, **kw: Any) -> None:
        return None

    async def write(self, *a: Any, **kw: Any) -> Any:
        return None


class _FakeEngine:
    """Duck-typed stand-in for kernel.reliability.SelfRepairEngine."""

    def __init__(self, running: bool = True) -> None:
        self._running = running

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "uptime_seconds": 7.5,
            "total_repairs": 1,
            "completed_repairs": 1,
            "failed_repairs": 0,
            "degraded_repairs": 0,
            "strategies_registered": 8,
            "workflows_registered": 6,
        }


def _port() -> Any:
    return cast(Any, _FakePort())


def _real_proposer():
    from plugins.tektos.self_repair import SelfRepairProposer

    return SelfRepairProposer(
        approval_gateway=_port(),
        memory=_port(),
        event_bus=_port(),
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kernel.app import registry

    monkeypatch.setattr(registry, "tektos_self_repair", None, raising=False)
    monkeypatch.setattr(registry, "self_repair", None, raising=False)
    monkeypatch.setattr(registry, "errors", {}, raising=False)
    return TestClient(app)


def _with_engine(client: TestClient, monkeypatch: pytest.MonkeyPatch, running: bool = True) -> None:
    from kernel.app import registry

    monkeypatch.setattr(registry, "self_repair", _FakeEngine(running), raising=False)


# ── Degraded state (engine + proposer both off — the test default) ────────


def test_self_repair_off_degraded(client: TestClient) -> None:
    r = client.get("/api/self_repair/status")
    assert r.status_code == 200
    o = r.json()
    # ADR-141 R7: healthy tracks the executing daemon, not the proposer.
    assert o["status"] == "degraded"
    assert o["healthy"] is False
    assert o["engine"]["wired"] is False
    assert o["proposer"]["wired"] is False
    assert o["proposer"]["confidence"] is None
    assert o["proposer"]["provenance"] is None
    # The static strategy catalog is reported even when everything is off.
    assert o["strategies"]["strategies_registered"] == 19
    assert o["strategies"]["categories"] == {
        "code": 4,
        "context": 4,
        "escalation": 1,
        "infrastructure": 5,
        "recovery": 2,
        "workload": 3,
    }
    assert o["errors"] == []


def test_self_repair_strategy_catalog_sorted_names(client: TestClient) -> None:
    o = client.get("/api/self_repair/status").json()
    names = o["strategies"]["strategy_names"]
    assert len(names) == 19
    assert names == sorted(names)  # deterministic order
    assert "restart_service" in names
    assert "escalate_to_user" in names
    assert "apply_patch" in names


# ── Engine running — healthy, even when the proposer is off ────────────────


def test_self_repair_engine_running_is_healthy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_engine(client, monkeypatch, running=True)
    o = client.get("/api/self_repair/status").json()
    assert o["status"] == "initialized"
    assert o["healthy"] is True
    assert o["engine"]["wired"] is True
    assert o["engine"]["running"] is True
    assert o["engine"]["strategies_registered"] == 8
    # Proposer still off — reported truthfully, no longer the health gate.
    assert o["proposer"]["wired"] is False
    assert o["errors"] == []


def test_self_repair_engine_stopped_degraded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_engine(client, monkeypatch, running=False)
    o = client.get("/api/self_repair/status").json()
    assert o["status"] == "degraded"
    assert o["healthy"] is False
    assert o["engine"]["wired"] is True
    assert o["engine"]["running"] is False


# ── Wired state — real proposer, faked ports ───────────────────────────────


def test_self_repair_proposer_wired_reports_tier_and_confidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kernel.app import registry

    _with_engine(client, monkeypatch, running=True)
    registry.tektos_self_repair = _real_proposer()
    try:
        o = client.get("/api/self_repair/status").json()
    finally:
        registry.tektos_self_repair = None
    assert o["healthy"] is True
    assert o["proposer"]["wired"] is True
    assert o["proposer"]["tier"] == "HUMAN_REQUIRED"
    # ADR-095 D2 locked values: default confidence 0.85, provenance string.
    assert o["proposer"]["confidence"] == 0.85
    assert o["proposer"]["provenance"] == "tektos_self_modification"
    assert o["strategies"]["strategies_registered"] == 19
    assert o["errors"] == []


def test_self_repair_wired_custom_confidence(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from kernel.app import registry

    from plugins.tektos.self_repair import SelfRepairProposer

    _with_engine(client, monkeypatch, running=True)
    registry.tektos_self_repair = SelfRepairProposer(
        approval_gateway=_port(),
        memory=_port(),
        event_bus=_port(),
        confidence=0.9,  # the ADR-090 ceiling — still legal
    )
    try:
        o = client.get("/api/self_repair/status").json()
    finally:
        registry.tektos_self_repair = None
    assert o["proposer"]["confidence"] == 0.9
    assert o["healthy"] is True


# ── Catalog consistency is self-checked ────────────────────────────────────


def test_self_repair_catalog_inconsistency_surfaces_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import kernel.app as kapp

    # Simulate a stale catalog: a label present in the enum but not mapped.
    monkeypatch.setitem(
        kapp._SELF_REPAIR_STRATEGY_CATEGORIES,
        "infrastructure",
        ("restart_service", "reload_config"),  # dropped clear_cache & friends
    )
    o = client.get("/api/self_repair/status").json()
    assert any("missing from catalog" in e for e in o["errors"])
    # The count reflects the intersection — honest, not fabricated.
    assert o["strategies"]["strategies_registered"] < 19
