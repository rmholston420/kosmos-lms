"""Stage 14.12 exposure fix — /api/tektos/data-services base index route.

The UI's card grid composes ``base + endpoint`` per store and never fetches
the bare base path, but the 2026-09-26 audit flagged the 404 on it as a dead
ref. The new ``GET /api/tektos/data-services`` index returns one summary
entry per store; each probe degrades independently (never a 500).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"

import kernel.app as ka  # noqa: E402

EXPECTED_SERVICES = {"neo4j", "postgres", "redis", "hindsight", "qdrant"}


def test_data_services_base_index_shape():
    with TestClient(ka.app) as tc:
        r = tc.get("/api/tektos/data-services")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"services", "healthy", "total"}
    assert set(body["services"].keys()) == EXPECTED_SERVICES
    assert body["total"] == 5
    for name, entry in body["services"].items():
        assert isinstance(entry["healthy"], bool), name
        assert isinstance(entry["status"], str) and entry["status"], name
        assert entry["endpoint"] == f"/api/tektos/data-services/{name}/status", name
    assert body["healthy"] == sum(
        1 for e in body["services"].values() if e["healthy"]
    )


def test_data_services_per_store_routes_still_live():
    """The index must not shadow the per-store status endpoints."""
    with TestClient(ka.app) as tc:
        for name in sorted(EXPECTED_SERVICES):
            r = tc.get(f"/api/tektos/data-services/{name}/status")
            assert r.status_code == 200, name
            assert r.json().get("service") == name, name
