"""Stage 11.6 — ADR-122 ``/api/immune/health`` tests.

Kernel-native immune health (replaces the ADR-109 gateway proxy to
:8020). Reads the LIVE ``registry.immune`` detector registry. The kernel
port is a scan-on-request detector registry (no persistent threat ledger,
no per-component scoring), so the envelope mirrors the old :8020 keys the
card already parses (overall/status/active_threats/uptime_seconds) and
adds a ``detectors`` array. No GPU, no real adapter — a stub with the two
methods the endpoint calls (``is_healthy`` + ``list_detectors``).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from kernel import app as kernel_app_module
from kernel.app import app

client = TestClient(app)


class _Info:
    def __init__(self, name: str, ceiling: str, desc: str = "") -> None:
        self.name = name
        self.severity_ceiling = ceiling
        self.description = desc


class _StubImmune:
    """Structurally satisfies the two methods the endpoint reads."""

    _healthy: bool = True
    _detectors: tuple[_Info, ...] = ()
    _raise: bool = False

    def is_healthy(self) -> bool:
        return self._healthy

    async def list_detectors(self) -> tuple[_Info, ...]:
        if self._raise:
            raise RuntimeError("detector registry unavailable")
        return self._detectors


def _stub(
    *,
    healthy: bool = True,
    detectors: tuple[_Info, ...] = (),
    raise_list: bool = False,
) -> _StubImmune:
    s = _StubImmune()
    s._healthy = healthy
    s._detectors = detectors
    s._raise = raise_list
    return s


def test_immune_health_healthy_reports_detector_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kernel_app_module.registry,
        "immune",
        _stub(
            detectors=(
                _Info("prompt_injection", "block", "Stops injection"),
                _Info("loop_detection", "warn"),
            )
        ),
    )
    r = client.get("/api/immune/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "healthy"
    assert body["overall"] == 1.0
    assert body["active_threats"] == 0
    assert body["detail"] == "2 detectors registered"
    assert [d["name"] for d in body["detectors"]] == [
        "prompt_injection",
        "loop_detection",
    ]
    assert body["detectors"][0]["severity_ceiling"] == "block"
    # envelope keys the card's parseCard already reads are present
    assert body["uptime_seconds"] >= 0
    assert "timestamp" in body


def test_immune_health_none_registry_reports_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # KOSMOS_IMMUNE=off → registry.immune is None. Always 200, never 500.
    monkeypatch.setattr(kernel_app_module.registry, "immune", None)
    r = client.get("/api/immune/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "degraded"
    assert body["overall"] == 0.0
    assert body["detectors"] == []
    assert "offline" in body["detail"].lower()


def test_immune_health_unhealthy_adapter_reports_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kernel_app_module.registry, "immune", _stub(healthy=False)
    )
    body = client.get("/api/immune/health").json()
    assert body["status"] == "degraded"
    assert body["overall"] == 0.0
    assert body["detectors"] == []


def test_immune_health_list_detectors_raising_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # list_detectors raising must not 500 — degrade to empty registry.
    monkeypatch.setattr(
        kernel_app_module.registry, "immune", _stub(raise_list=True)
    )
    r = client.get("/api/immune/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "healthy"
    assert body["detectors"] == []
    assert body["detail"] == "0 detectors registered"


def test_immune_health_severity_ceiling_string_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # severity_ceiling is a Literal[str] in the port — must pass through
    # as-is, not be mangled by an enum-value lookup.
    monkeypatch.setattr(
        kernel_app_module.registry,
        "immune",
        _stub(detectors=(_Info("context_collapse", "block"),)),
    )
    body = client.get("/api/immune/health").json()
    assert body["detectors"][0]["severity_ceiling"] == "block"
