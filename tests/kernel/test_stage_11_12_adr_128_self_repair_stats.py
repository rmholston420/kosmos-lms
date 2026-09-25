"""Stage 11.12 — ADR-128 self_repair tests: /api/self_repair/status.

Kernel-native self-repair truth (replaces the ADR-109 gateway proxy to
:8020, whose *executing* repair daemon — uptime/completed_repairs/
effectiveness — has no kernel referent). The kernel's surface is the
propose-only ``SelfRepairProposer`` (Stage 5.6, ADR-095 D2) + the static
vendored ``RepairStrategy`` catalog.

Tests run GPU-free: no network, no Postgres. The registry is faked per
test; the proposer is the REAL ``SelfRepairProposer`` (faked ports —
propose-only, so nothing executes).
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

    async def write_event(self, *a: Any, **kw: Any) -> Any:
        return None

    async def write(self, *a: Any, **kw: Any) -> Any:
        return None


def _port() -> Any:
    return cast(Any, _FakePort())


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kernel.app import registry

    monkeypatch.setattr(registry, "tektos_self_repair", None, raising=False)
    return TestClient(app)


def _real_proposer():
    """Real SelfRepairProposer with faked ports — propose-only, safe."""
    from plugins.tektos.self_repair import SelfRepairProposer

    return SelfRepairProposer(
        approval_gateway=_port(),
        memory=_port(),
        event_bus=_port(),
    )


# ── Degraded state (proposer off — the default) ───────────────────────────


def test_self_repair_off_degraded(client: TestClient) -> None:
    r = client.get("/api/self_repair/status")
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "degraded"
    assert o["healthy"] is False
    assert o["proposer"]["wired"] is False
    assert o["proposer"]["confidence"] is None
    assert o["proposer"]["provenance"] is None
    # The static strategy catalog is reported even when the proposer is off.
    assert o["strategies"]["strategies_registered"] == 19
    assert o["strategies"]["categories"] == {
        "code": 4,
        "context": 4,
        "escalation": 1,
        "infrastructure": 5,
        "recovery": 2,
        "workload": 3,
    }
    assert o["execution"].startswith("not wired in kernel")
    assert ":8020/api/self_repair/status" in o["execution"]
    assert o["errors"] == []


def test_self_repair_strategy_catalog_sorted_names(client: TestClient) -> None:
    o = client.get("/api/self_repair/status").json()
    names = o["strategies"]["strategy_names"]
    assert len(names) == 19
    assert names == sorted(names)  # deterministic order
    assert "restart_service" in names
    assert "escalate_to_user" in names
    assert "apply_patch" in names


# ── Wired state — real proposer, faked ports ───────────────────────────────


def test_self_repair_wired(client: TestClient) -> None:
    from kernel.app import registry

    registry.tektos_self_repair = _real_proposer()
    try:
        r = client.get("/api/self_repair/status")
    finally:
        registry.tektos_self_repair = None
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "initialized"
    assert o["healthy"] is True
    assert o["proposer"]["wired"] is True
    assert o["proposer"]["tier"] == "HUMAN_REQUIRED"
    # ADR-095 D2 locked values: default confidence 0.85, provenance string.
    assert o["proposer"]["confidence"] == 0.85
    assert o["proposer"]["provenance"] == "tektos_self_modification"
    assert o["strategies"]["strategies_registered"] == 19
    assert o["errors"] == []


def test_self_repair_wired_custom_confidence(client: TestClient) -> None:
    from kernel.app import registry

    from plugins.tektos.self_repair import SelfRepairProposer

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
