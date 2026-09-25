"""ADR-133 slice I2c — kernel /api/immune/* endpoint tests.

Boots the real kernel app with a fake immune adapter on
``registry.immune`` and a fake bus (``read_recent``) on
``registry.event_bus``. GPU-free.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kernel import app as kernel_app  # noqa: E402
from ports.event_envelope import EventEnvelope  # noqa: E402
from ports.immune import DetectorInfo  # noqa: E402


class FakeImmune:
    def __init__(self) -> None:
        self._infos = (
            DetectorInfo(
                name="prompt_injection",
                severity_ceiling="block",
                description="detects prompt injection",
            ),
            DetectorInfo(
                name="excessive_repetition",
                severity_ceiling="warn",
                description="detects repetition",
            ),
        )

    async def list_detectors(self) -> tuple:
        return self._infos

    def is_healthy(self) -> bool:
        return True


class FakeBus:
    def __init__(self) -> None:
        block = EventEnvelope(
            event_type="immune.verdict.block",
            producer_plugin="tektos_immune_adapter",
            payload={
                "source_plugin": "tektos_manager",
                "kind": "tektos.tool.invocation",
                "decision": "block",
                "reason": "injection",
                "hit_count": 1,
                "hits": [
                    {"detector": "prompt_injection", "severity": "block", "evidence": "e"}
                ],
            },
            occurred_at=datetime.fromtimestamp(100, tz=timezone.utc),
        )
        allow = EventEnvelope(
            event_type="immune.verdict.allow",
            producer_plugin="tektos_immune_adapter",
            payload={
                "source_plugin": "tektos_manager",
                "kind": "tektos.tool.invocation",
                "decision": "allow",
                "reason": "clean",
                "hit_count": 0,
                "hits": [],
            },
            occurred_at=datetime.fromtimestamp(300, tz=timezone.utc),
        )
        self.streams = {
            "immune.verdict.block": [("100-1", block)],
            "immune.verdict.allow": [("300-1", allow)],
        }

    async def read_recent(self, *, event_type, count=None):
        items = list(self.streams.get(event_type, []))
        if count is not None:
            items = items[-count:]
        return items


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(kernel_app, "registry", kernel_app.registry)
    kernel_app.registry.immune = FakeImmune()
    kernel_app.registry.event_bus = FakeBus()
    transport = ASGITransport(app=kernel_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    kernel_app.registry.immune = None
    kernel_app.registry.event_bus = None


@pytest.mark.anyio
async def test_detectors(client) -> None:
    r = await client.get("/api/immune/detectors")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert {d["name"] for d in body["detectors"]} == {
        "prompt_injection",
        "excessive_repetition",
    }


@pytest.mark.anyio
async def test_threats_active_and_resolved(client) -> None:
    r = await client.get("/api/immune/threats")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1  # only the block
    assert body["threats"][0]["detector"] == "prompt_injection"
    r2 = await client.get("/api/immune/threats", params={"resolved": "true"})
    assert r2.json()["count"] == 2  # block + allow


@pytest.mark.anyio
async def test_responses_newest_first(client) -> None:
    r = await client.get("/api/immune/responses")
    assert r.status_code == 200
    rows = r.json()["responses"]
    assert [row["decision"] for row in rows] == ["allow", "block"]


@pytest.mark.anyio
async def test_memory_summary_and_entries(client) -> None:
    r = await client.get("/api/immune/memory")
    assert r.status_code == 200
    m = r.json()
    assert m["total_threats_observed"] == 2
    assert m["active_threats"] == 1
    assert m["resolved_threats"] == 1
    assert m["uptime_hours"] >= 0.0
    r2 = await client.get("/api/immune/memory/entries")
    assert r2.status_code == 200
    assert len(r2.json()["response_history"]) == 2


@pytest.mark.anyio
async def test_detectors_503_when_immune_offline(client, monkeypatch) -> None:
    monkeypatch.setattr(kernel_app.registry, "immune", None)
    r = await client.get("/api/immune/detectors")
    assert r.status_code == 503


@pytest.mark.anyio
async def test_threats_503_when_bus_offline(client, monkeypatch) -> None:
    monkeypatch.setattr(kernel_app.registry, "event_bus", None)
    r = await client.get("/api/immune/threats")
    assert r.status_code == 503
