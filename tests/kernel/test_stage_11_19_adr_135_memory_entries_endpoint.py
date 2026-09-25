"""ADR-135 slices M2+M3 — kernel-native GET /api/memory endpoint tests.

GPU-free: fake registry.memory with a scripted recent_memory_events() +
real kernel app via ASGITransport (the ADR-132/133/134 endpoint pattern).

Every test restores registry.memory (the fixture's finally).

Covers:
- 200 envelope: entries[] rows with donor-relevant keys (id/kind/
  content/score/written_at/provenance/subject), count, limit, backend,
  timestamp
- newest-first sort (rows fed out of order come back written_at DESC)
- limit clamp (0 → 1, 500 → 100)
- 503 when registry.memory is None
- 500 with detail when recent_memory_events raises
- coexistence: /api/memory/stats still serves the ADR-123 shape
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import kernel.app as kernel_app
from kernel.app import app


class FakeMemoryAdapter:
    """Scripted stand-in for DozerDbMemoryAdapter (read surface only)."""

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        healthy: bool = True,
        raise_on_list: bool = False,
    ) -> None:
        self._rows = rows if rows is not None else []
        self._healthy = healthy
        self._raise = raise_on_list

    async def recent_memory_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._raise:
            raise RuntimeError("graph backend closed")
        return [dict(r) for r in self._rows[:limit]]

    def is_healthy(self) -> bool:
        return self._healthy


def _row(
    rid: str,
    predicate: str,
    obj: str,
    *,
    written_at: str,
    provenance: str = "test",
    confidence: float = 0.8,
    subject: str = "subj",
) -> dict[str, Any]:
    return {
        "id": rid,
        "predicate": predicate,
        "object": obj,
        "written_at": written_at,
        "provenance": provenance,
        "confidence": confidence,
        "subject": subject,
        "pii_tier": "Public",
    }


@pytest_asyncio.fixture
async def patched_registry():
    original = kernel_app.registry.memory
    kernel_app.registry.memory = FakeMemoryAdapter()
    try:
        yield kernel_app.registry.memory
    finally:
        kernel_app.registry.memory = original


@pytest_asyncio.fixture
async def memory_client():
    """ASGI client; tests set kernel_app.registry.memory freely, the
    fixture restores the original on teardown."""
    original = kernel_app.registry.memory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
        finally:
            kernel_app.registry.memory = original


@pytest.mark.anyio
async def test_entries_envelope_and_sort(memory_client: AsyncClient) -> None:
    rows = [
        _row("e-old", "P_OLD", "oldest", written_at="2026-01-01T00:00:00+00:00"),
        _row("e-mid", "P_MID", "middle", written_at="2026-01-02T00:00:00+00:00"),
        _row("e-new", "P_NEW", "newest", written_at="2026-01-03T00:00:00+00:00"),
    ]
    kernel_app.registry.memory = FakeMemoryAdapter(rows)

    r = await memory_client.get("/api/memory")

    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["limit"] == 50
    assert body["backend"] == "dozerdb"
    datetime.fromisoformat(body["timestamp"])
    entries = body["entries"]
    assert [e["id"] for e in entries] == ["e-new", "e-mid", "e-old"]
    first = entries[0]
    assert first["kind"] == "P_NEW"
    assert first["content"] == "newest"
    assert first["score"] == 0.8
    assert first["provenance"] == "test"
    assert first["subject"] == "subj"
    assert first["written_at"] == "2026-01-03T00:00:00+00:00"


@pytest.mark.anyio
async def test_entries_limit_clamp(memory_client: AsyncClient) -> None:
    rows = [
        _row(f"e{i}", f"P{i}", f"o{i}", written_at=f"2026-01-{i+1:02d}T00:00:00+00:00")
        for i in range(6)
    ]
    kernel_app.registry.memory = FakeMemoryAdapter(rows)

    r_big = await memory_client.get("/api/memory", params={"limit": 500})
    r_zero = await memory_client.get("/api/memory", params={"limit": 0})

    assert r_big.status_code == 200
    assert r_big.json()["limit"] == 100
    assert r_zero.status_code == 200
    assert r_zero.json()["limit"] == 1
    assert r_zero.json()["count"] == 1


@pytest.mark.anyio
async def test_entries_empty_corpus(memory_client: AsyncClient) -> None:
    kernel_app.registry.memory = FakeMemoryAdapter([])

    r = await memory_client.get("/api/memory")

    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == []
    assert body["count"] == 0


@pytest.mark.anyio
async def test_entries_503_when_memory_lane_offline(memory_client: AsyncClient) -> None:
    kernel_app.registry.memory = None

    r = await memory_client.get("/api/memory")

    assert r.status_code == 503
    assert "memory lane offline" in r.json()["detail"]


@pytest.mark.anyio
async def test_entries_500_with_detail_when_read_raises(memory_client: AsyncClient) -> None:
    kernel_app.registry.memory = FakeMemoryAdapter(raise_on_list=True)

    r = await memory_client.get("/api/memory")

    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "RuntimeError" in detail
    assert "graph backend closed" in detail


@pytest.mark.anyio
async def test_stats_endpoint_unchanged(memory_client: AsyncClient) -> None:
    """ADR-123 /api/memory/stats must still serve its own shape."""

    class StatsAdapter(FakeMemoryAdapter):
        async def stats(self) -> dict[str, Any]:
            return {
                "healthy": True,
                "memory_events": 3,
                "entities": 7,
                "quarantined": 0,
                "errors": [],
            }

    kernel_app.registry.memory = StatsAdapter([
        _row("e1", "P", "o", written_at="2026-01-01T00:00:00+00:00"),
    ])

    r = await memory_client.get("/api/memory/stats")

    assert r.status_code == 200
    body = r.json()
    assert body["memory_events"] == 3
    assert body["entities"] == 7
    assert body["quarantined"] == 0
    assert body["healthy"] is True
