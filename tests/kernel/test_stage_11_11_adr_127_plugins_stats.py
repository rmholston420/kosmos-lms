"""Stage 11.11 — ADR-127 plugins tests: /api/plugins.

Kernel-native plugin truth (replaces the ADR-109 gateway proxy to :8020,
whose functional search-provider list has no kernel referent). Two
corrections the endpoint must reflect (user clarification 2026-09-25):

  1. The kernel's ``plugins/`` packages are SUBSYSTEMS, not plugins.
  2. The kernel's real plugin mechanism is the FrontendContractPort
     descriptor registry (routes/panels/design-tokens).

The functional plugin registry is a real gap — Tektos's search providers
stay on the standalone engine. Tests run GPU-free: no network, no Postgres.
The registry is faked per test; the descriptors are the REAL frozen
``PluginDescriptor``/``Route``/``Panel`` dataclasses (duck-typed endpoint).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kernel.app import app
from ports.frontend_contract import (
    Panel,
    PanelSlot,
    PluginDescriptor,
    Route,
)


class _FakeFrontendContract:
    """Duck-typed FrontendContractPort: only ``list_plugins`` is read."""

    def __init__(self, descriptors: list, raise_on_list: bool = False) -> None:
        self._descriptors = descriptors
        self._raise = raise_on_list

    async def list_plugins(self):
        if self._raise:
            raise RuntimeError("descriptor registry query failed (test)")
        return self._descriptors


def _tektos_descriptor() -> PluginDescriptor:
    return PluginDescriptor(
        name="tektos",
        state_namespace="tektos",
        version="1.0.0",
        kernel_compat="1.0",
        routes=(Route(path="/tektos", label="Tektos", icon="t", lazy_module="tektos"),),
        panels=(
            Panel(
                id="tektos-overview",
                slot=PanelSlot.ALGEDONIC,
                priority=1,
                lazy_module="tektos",
                plugin_name="tektos",
            ),
        ),
    )


def _zetesis_descriptor() -> PluginDescriptor:
    return PluginDescriptor(
        name="zetesis",
        state_namespace="zetesis",
        version="0.4.0",
        kernel_compat="1.0",
        routes=(),
        panels=(),
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kernel.app import registry

    # Isolate the frontend_contract slot (degraded = the off state).
    monkeypatch.setattr(registry, "frontend_contract", None, raising=False)
    # Neutralize the subsystem slots so wiring assertions are explicit.
    monkeypatch.setattr(registry, "phrouros", None, raising=False)
    monkeypatch.setattr(registry, "approval", None, raising=False)
    monkeypatch.setattr(registry, "zetesis", None, raising=False)
    monkeypatch.setattr(registry, "tektos", None, raising=False)
    return TestClient(app)


# ── Degraded state (frontend_contract off) ─────────────────────────────────


def test_plugins_degraded_when_no_frontend_contract(client: TestClient) -> None:
    r = client.get("/api/plugins")
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "degraded"
    assert o["healthy"] is False
    assert o["ui_plugins"]["count"] == 0
    assert o["ui_plugins"]["plugins"] == []
    # Subsystems correctly reported as NOT wired (all slots None).
    assert o["subsystems"] == {
        "phrouros": False,
        "praxis": False,
        "zetesis": False,
        "tektos": False,
    }
    # The functional gap is reported honestly, never fabricated.
    assert "pending" in o["functional"]["kernel_registry"]
    assert ":8020/api/plugins" in o["functional"]["tektos_search_providers"]
    assert o["errors"] == []


# ── Wired state (real descriptors) ─────────────────────────────────────────


def test_plugins_wired_reports_real_descriptors(client: TestClient) -> None:
    from kernel.app import registry

    registry.frontend_contract = _FakeFrontendContract(
        [_tektos_descriptor(), _zetesis_descriptor()]
    )
    try:
        r = client.get("/api/plugins")
    finally:
        registry.frontend_contract = None
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "initialized"
    assert o["healthy"] is True
    assert o["ui_plugins"]["count"] == 2
    names = [p["name"] for p in o["ui_plugins"]["plugins"]]
    assert names == ["tektos", "zetesis"]
    # Route paths + panel ids are the serialized descriptor shape.
    tektos = o["ui_plugins"]["plugins"][0]
    assert tektos["routes"] == ["/tektos"]
    assert tektos["panels"] == ["tektos-overview"]
    assert tektos["version"] == "1.0.0"
    assert tektos["kernel_compat"] == "1.0"
    # The empty-descriptor (zetesis) serializes to empty route/panel lists.
    zetesis = o["ui_plugins"]["plugins"][1]
    assert zetesis["routes"] == []
    assert zetesis["panels"] == []
    assert o["errors"] == []


# ── Subsystem wiring reflects registry slots ───────────────────────────────


def test_plugins_subsystem_wiring_tracks_slots(client: TestClient) -> None:
    from kernel.app import registry

    # Wire phrouros + tektos (praxis reads the approval slot).
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(registry, "phrouros", object(), raising=False)
        monkey.setattr(registry, "tektos", object(), raising=False)
        monkey.setattr(registry, "approval", object(), raising=False)
        r = client.get("/api/plugins")
    finally:
        monkey.undo()
    o = r.json()
    assert o["subsystems"]["phrouros"] is True
    assert o["subsystems"]["tektos"] is True
    assert o["subsystems"]["praxis"] is True  # via approval slot
    assert o["subsystems"]["zetesis"] is False  # left None


# ── Raising list_plugins degrades partially (never 500) ────────────────────


def test_plugins_raising_descriptors_degrade_partially(client: TestClient) -> None:
    from kernel.app import registry

    registry.frontend_contract = _FakeFrontendContract([], raise_on_list=True)
    try:
        r = client.get("/api/plugins")
    finally:
        registry.frontend_contract = None
    assert r.status_code == 200  # always-200, never 500
    o = r.json()
    assert o["healthy"] is True  # frontend_contract present
    assert o["status"] == "initialized"
    assert any("descriptor registry query failed" in e for e in o["errors"])
    assert o["ui_plugins"]["count"] == 0
    assert o["ui_plugins"]["plugins"] == []
