"""T8b-2 — donor /api/keys → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:5328.

Shape (donor-verbatim, verified against panels/page.tsx ConfigTab):
  GET /api/keys
    -> {"keys": [{"name": str, "key": str, "value": str, "configured": bool}]}

Wiring (layering rule): the donor listed its own TEKTOS_* secret env vars;
the kernel lists the KOSMOS_* secret set it actually reads (LLM/VLM lane
API keys, Qdrant API key, DozerDB password) plus the shared DATABASE_URL /
OPENAI_API_KEY the donor surfaced. Values are never returned in plaintext —
configured → "••••••••", absent → "not configured".
"""

from __future__ import annotations

import os

import pytest

import kernel.app as ka  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    with TestClient(ka.app) as c:
        yield c


def test_keys_shape_and_masking(client, monkeypatch):
    monkeypatch.setenv("KOSMOS_QDRANT_API_KEY", "secret-should-never-leak")
    monkeypatch.delenv("KOSMOS_DOZERDB_PASSWORD", raising=False)
    r = client.get("/api/keys")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["keys"], list) and body["keys"]
    for row in body["keys"]:
        assert set(row) >= {"name", "key", "value", "configured"}
        assert isinstance(row["configured"], bool)
        # masking: plaintext must never appear in the response
        assert "secret-should-never-leak" not in r.text
    qdrant = next(k for k in body["keys"] if k["key"] == "KOSMOS_QDRANT_API_KEY")
    assert qdrant["configured"] is True
    assert qdrant["value"] == "••••••••"
    assert qdrant["name"] == "Qdrant Api Key"
    dozer = next(k for k in body["keys"] if k["key"] == "KOSMOS_DOZERDB_PASSWORD")
    assert dozer["configured"] is False
    assert dozer["value"] == "not configured"
