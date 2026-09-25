"""Stage 11.7 — ADR-123 ``/api/memory/stats`` tests.

Kernel-native memory corpus stats (replaces the ADR-109 gateway proxy to
:8020). Reads the LIVE ``registry.memory`` (DozerDbMemoryAdapter). Counts
are real Cypher on DozerDB / label-filter on the in-memory backend.

No Neo4j, no real graph — a fake graph whose ``query_cypher`` records the
``label:<Label>`` shape the adapter asks for and returns N stub nodes, so
we verify the adapter's count logic AND the endpoint's envelope without
touching the DB. A raising graph verifies the never-fabricate rule.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from kernel import app as kernel_app_module
from kernel.app import app

client = TestClient(app)


class _FakeGraph:
    """Mimics the method ``stats()`` calls: count_nodes(label) -> int."""

    def __init__(
        self,
        counts: dict[str, int] | None = None,
        *,
        raise_on: str | None = None,
        healthy: bool = True,
    ) -> None:
        self._counts = counts or {}
        self._raise_on = raise_on
        self._healthy = healthy
        self.seen: list[str] = []

    def is_healthy(self) -> bool:
        return self._healthy

    async def count_nodes(self, label: str) -> int:
        self.seen.append(label)
        if self._raise_on and label == self._raise_on:
            raise RuntimeError(f"boom: {label}")
        return self._counts.get(label, 0)


class _FakeAdapter:
    """Structurally the two methods the endpoint reads: stats + is_healthy."""

    def __init__(self, graph: _FakeGraph, *, healthy: bool = True) -> None:
        self._graph = graph
        self._healthy = healthy

    def is_healthy(self) -> bool:
        return self._healthy

    async def stats(self) -> dict[str, Any]:
        # Re-implements the adapter's count loop over the fake graph so we
        # test the ENDPOINT's envelope handling independently of the
        # adapter (the adapter's own count logic is tested separately).
        out: dict[str, Any] = {
            "healthy": self._healthy,
            "memory_events": None,
            "entities": None,
            "quarantined": None,
            "errors": [],
        }
        for prop, label in (
            ("memory_events", "MemoryEvent"),
            ("entities", "Entity"),
            ("quarantined", "Quarantined"),
        ):
            try:
                out[prop] = await self._graph.count_nodes(label)
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"{label}: {type(exc).__name__}")
        return out


def test_memory_stats_reports_real_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _FakeGraph(
        {"MemoryEvent": 7692, "Entity": 12345, "Quarantined": 0}
    )
    monkeypatch.setattr(
        kernel_app_module.registry, "memory", _FakeAdapter(graph)
    )
    r = client.get("/api/memory/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["healthy"] is True
    assert body["backend"] == "dozerdb"
    assert body["memory_events"] == 7692
    assert body["entities"] == 12345
    assert body["quarantined"] == 0
    assert body["errors"] == []
    assert "timestamp" in body
    # The adapter asked for exactly the three labels, in order.
    assert graph.seen == ["MemoryEvent", "Entity", "Quarantined"]


def test_memory_stats_none_adapter_reports_none_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # registry.memory is None → backend "none", all counts None, degraded.
    monkeypatch.setattr(kernel_app_module.registry, "memory", None)
    r = client.get("/api/memory/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["healthy"] is False
    assert body["backend"] == "none"
    assert body["memory_events"] is None
    assert body["entities"] is None
    assert body["quarantined"] is None


def test_memory_stats_unhealthy_adapter_is_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _FakeGraph({"MemoryEvent": 5}, healthy=False)
    monkeypatch.setattr(
        kernel_app_module.registry, "memory", _FakeAdapter(graph, healthy=False)
    )
    body = client.get("/api/memory/stats").json()
    assert body["healthy"] is False
    assert "unhealthy" in body["backend"]
    # counts still real (the graph works even if the adapter flags itself)
    assert body["memory_events"] == 5


def test_memory_stats_count_failure_never_fabricates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A label that raises must leave its count None + record the error —
    # the card shows "count unavailable", not a fake zero.
    graph = _FakeGraph({"MemoryEvent": 100, "Entity": 50}, raise_on="Quarantined")
    monkeypatch.setattr(
        kernel_app_module.registry, "memory", _FakeAdapter(graph)
    )
    body = client.get("/api/memory/stats").json()
    assert body["memory_events"] == 100
    assert body["entities"] == 50
    assert body["quarantined"] is None
    assert any("Quarantined" in e for e in body["errors"])
    # healthy is still True (the adapter itself is fine — one bad count).
    assert body["healthy"] is True


def test_memory_stats_adapter_stats_raising_is_500_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If adapter.stats() itself blows up (not just a count), the endpoint
    # degrades to a 200 with the error surfaced — never a 500.
    class _BoomAdapter:
        def is_healthy(self) -> bool:
            return True

        async def stats(self) -> dict[str, Any]:
            raise RuntimeError("adapter exploded")

    monkeypatch.setattr(kernel_app_module.registry, "memory", _BoomAdapter())
    r = client.get("/api/memory/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["healthy"] is False
    assert body["memory_events"] is None
    assert any("stats()" in e for e in body["errors"])


# ── real adapter, no Neo4j ────────────────────────────────────────────────
# The endpoint tests above use a fake adapter. This one exercises the REAL
# DozerDbMemoryAdapter.stats() against the in-memory graph backend — the
# count loop, label shapes, and the per-label degrade rule are all real
# production code here (no Neo4j needed: the backend filters by label).


class _RaisingGraph:
    def is_healthy(self) -> bool:
        return True

    async def count_nodes(self, label: str) -> int:
        raise RuntimeError("graph down")


def test_real_adapter_stats_counts_and_degrades() -> None:
    import asyncio

    from adapters.memory.dozerdb.adapter import (
        DozerDbMemoryAdapter,
        InMemoryGraphBackend,
        InMemoryTemporalIndex,
        NoOpAmgPolicy,
    )

    graph = InMemoryGraphBackend()
    adapter = DozerDbMemoryAdapter(
        graph=graph,
        amg=NoOpAmgPolicy(),
        temporal=InMemoryTemporalIndex(),
    )
    # Write 2 real events through the adapter → 2 MemoryEvent + 4 Entity
    # nodes (subject + object per event).
    for i in range(2):
        asyncio.run(
            adapter.write_event(
                subject=f"subj_{i}",
                predicate="knows",
                object=f"obj_{i}",
                provenance="test",
                confidence=0.9,
            )
        )

    s = asyncio.run(adapter.stats())
    assert s["healthy"] is True
    assert s["memory_events"] == 2
    assert s["entities"] == 4
    assert s["quarantined"] == 0
    assert s["errors"] == []

    # A downed graph: every count is None + errors recorded; never raises.
    adapter2 = DozerDbMemoryAdapter(
        graph=_RaisingGraph(),  # type: ignore[arg-type] — stats() only calls query_cypher + is_healthy
        amg=NoOpAmgPolicy(),
        temporal=InMemoryTemporalIndex(),
    )
    s2 = asyncio.run(adapter2.stats())
    assert s2["memory_events"] is None
    assert s2["entities"] is None
    assert s2["quarantined"] is None
    assert len(s2["errors"]) == 3

