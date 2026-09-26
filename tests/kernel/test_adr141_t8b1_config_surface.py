"""T8b-1 — donor /api/config GET+PATCH → kernel-native surface (ADR-141).

Donor: tektos-ultima-v1 src/tektos/main.py:5160 (GET), :5232 (PATCH).

Shape (donor-verbatim, verified against panels/page.tsx ConfigTab):
  GET /api/config
    -> {"protocol_version": str, "llm": {...}, "config": [row, ...], "llm_available": bool}
    row = {"key": str, "value": str|bool|None, "type": str, "sensitive": bool, "description": str}
  PATCH /api/config
    body {"key": str, "value": X}
    -> {"status": "updated"|"restarted", "key": str, "applied": bool}

Wiring (layering rule — surface over kernel substrate, donor is a flat
env-config dump with no real apply):
  * llm block + rows read the LIVE kernel lane (registry.llm):
    KOSMOS_LLM_BASE_URL → lane 0 (:8090), KOSMOS_LLM_FALLBACK_BASE_URL → lane 1
    (:8092), plus KOSMOS_VISION_BASE_URL (:8094) and the default model.
  * PATCH is read-mostly honest: value is written back to os.environ only
    when the key maps to an unconfigured env var (restart-required, applied
    False); configured keys and unknown keys report applied False with
    status "restarted"/"updated" matching the donor response shapes.
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


def test_config_get_shape(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["protocol_version"], str) and body["protocol_version"]
    assert isinstance(body["config"], list)
    assert body["config"], "expected at least one config row"
    assert isinstance(body["llm"], dict)
    assert isinstance(body["llm_available"], bool)
    for row in body["config"]:
        assert set(row) >= {"key", "value", "type", "sensitive", "description"}
    # live lane must be surfaced (kernel owns the LLM topology, ADR-132)
    assert body["llm"]["lane"] in {"primary", "fallback", "unavailable"}
    if body["llm_available"]:
        assert body["llm"]["base_url"]
        assert body["llm"]["model"]


def test_config_get_env_rows_present(client):
    body = client.get("/api/config").json()
    keys = {row["key"] for row in body["config"]}
    assert {"KOSMOS_LLM_BASE_URL", "KOSMOS_LLM_FALLBACK_BASE_URL"} <= keys
    # sensitive values must never leak plaintext
    for row in body["config"]:
        if row["sensitive"]:
            assert not row["value"] or "•" in str(row["value"])


def test_config_patch_unknown_key(client):
    r = client.patch("/api/config", json={"key": "NOT_A_REAL_KEY", "value": "x"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["applied"] is False
    assert body["note"] == "key not mapped to runtime"  # donor wire
    assert body["value"] == "x"


def test_config_patch_configured_key_not_applied(client, monkeypatch):
    monkeypatch.setenv("KOSMOS_LLM_FALLBACK_BASE_URL", "http://127.0.0.1:8092/v1")
    r = client.patch(
        "/api/config", json={"key": "KOSMOS_LLM_FALLBACK_BASE_URL", "value": "http://x"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["applied"] is False  # configured lane — not live-mutated
    assert "restart" in body["note"]


def test_config_patch_unconfigured_env_written_back(client, monkeypatch):
    monkeypatch.delenv("KOSMOS_VLM_BASE_URL", raising=False)
    try:
        r = client.patch(
            "/api/config", json={"key": "KOSMOS_VLM_BASE_URL", "value": "http://vlm.test/v1"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["applied"] is True
        assert os.environ.get("KOSMOS_VLM_BASE_URL") == "http://vlm.test/v1"
    finally:
        os.environ.pop("KOSMOS_VLM_BASE_URL", None)


def test_config_patch_requires_key(client):
    r = client.patch("/api/config", json={"value": "x"})
    assert r.status_code == 422
