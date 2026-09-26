"""ADR-141 Stage 13.8 — context curator substrate port + route.

Donor `tektos/runtime/context_curator.py` (110 LOC, 100% stdlib, zero
`tektos.*` imports) → `kernel/context_curator.py` byte-verbatim (generic
context-window lifecycle substrate → kernel per governing layering rule).
`registry.tektos_context_curator` booted at the composition root with
donor boot values (main.py:1434: 256k budget, 0.75 threshold); donor's
log-only `await start()` scheduled on the running loop (no state change).
Donor route main.py:4639: `not_initialized` when gate-off.
"""

from __future__ import annotations

import kernel.app as ka
from fastapi.testclient import TestClient
import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(ka.app) as tc:
        yield tc


def test_context_curator_status_initialized(client):
    """GET /api/contextCurator/status → 200, donor initialized envelope."""
    r = client.get("/api/contextCurator/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "initialized"
    stats = body["stats"]
    for key in (
        "max_tokens",
        "current_tokens",
        "budget_remaining",
        "compaction_threshold",
        "should_compact",
        "total_compactions",
        "snapshots_tracked",
    ):
        assert key in stats, key
    assert stats["max_tokens"] == 262144  # donor main.py:1434 boot value
    assert stats["compaction_threshold"] == 0.75
    assert stats["should_compact"] is False
    assert stats["budget_remaining"] == 262144


def test_context_curator_status_gate_off(client, monkeypatch):
    """Gate-off (slot None) → donor-verbatim not_initialized at 200."""
    monkeypatch.setattr(ka.registry, "tektos_context_curator", None)
    r = client.get("/api/contextCurator/status")
    assert r.status_code == 200
    assert r.json() == {"status": "not_initialized"}


# ── Substrate unit tests (pure logic) ────────────────────────────────────


def test_compaction_threshold_bands_verbatim():
    """Donor compaction bands (context_curator.py:61-98): should_compact
    flips strictly above max*threshold; budget_remaining floors at 0."""
    from kernel.context_curator import ContextCurator

    cur = ContextCurator(max_tokens=1000, compaction_threshold=0.75)
    cur.record_usage(750)  # exactly at threshold → NOT compact (donor: >)
    assert cur.should_compact() is False

    cur.record_usage(751)  # strictly above → compact
    assert cur.should_compact() is True
    snap = cur.get_snapshot()
    assert snap.compaction_needed is True
    assert snap.active_tiers == 4  # donor: 4 tiers when compaction needed

    cur.record_usage(5000)  # over budget → budget_remaining floors at 0
    stats = cur.get_compaction_stats()
    assert stats["budget_remaining"] == 0
    assert stats["current_tokens"] == 5000
    assert stats["snapshots_tracked"] >= 1
