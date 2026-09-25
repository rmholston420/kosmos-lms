"""Stage 11.16 slice D — ADR-132 kernel-native models picker.

The sessions page previously proxied ``:8020/api/models`` — the *standalone*
Tektos engine, which builds its picker from ``TEKTOS_LLM_*`` env (four
llama-server lanes: primary coder / fallback coder / embedder / vision).

The kernel-native endpoint builds the list from the **kernel's own** ADR-116
adapter env — the exact vars the adapters read at boot:

* ``KOSMOS_LLAMA_SWAP_*``   → primary coder lane (llama.cpp, GPU)
* ``KOSMOS_OLLAMA_*``       → fallback + vision lane (Ollama)
* ``KOSMOS_EMBEDDER_*``     → embedder lane (llama.cpp, CPU-only)

So the UI never advertises a model the kernel cannot actually reach, and
the list is three lanes, not the donor's four (the kernel has no separate
vision lane — the Ollama fallback *is* the vision model).

These tests monkeypatch the env and assert the picker reflects the kernel
config (not a hardcoded donor list).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kernel import app as kapp


@pytest.fixture()
def client() -> TestClient:
    return TestClient(kapp.app)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "KOSMOS_LLAMA_SWAP_BASE_URL",
        "KOSMOS_LLAMA_SWAP_DEFAULT_MODEL",
        "KOSMOS_OLLAMA_BASE_URL",
        "KOSMOS_OLLAMA_DEFAULT_MODEL",
        "KOSMOS_EMBEDDER_BASE_URL",
        "KOSMOS_EMBEDDER_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_models_returns_three_lanes(client: TestClient) -> None:
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # Kernel is three lanes, not the donor's four (no separate vision lane).
    assert len(body) == 3


def test_models_roles_and_recommended(client: TestClient) -> None:
    body = client.get("/api/models").json()
    roles = [m["role"] for m in body]
    assert roles == ["coder", "fallback", "embedder"]
    rec = [m for m in body if m.get("recommended")]
    assert len(rec) == 1
    assert rec[0]["role"] == "coder"


def test_models_element_shape(client: TestClient) -> None:
    for m in client.get("/api/models").json():
        for key in ("id", "name", "role", "description", "endpoint", "capabilities"):
            assert key in m
    assert all(isinstance(m["capabilities"], list) for m in client.get("/api/models").json())


def test_models_defaults_when_env_unset(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    body = client.get("/api/models").json()
    by_role = {m["role"]: m for m in body}
    # Sidecar / Ollama / CPU-embedder defaults mirror the adapter modules.
    assert by_role["coder"]["endpoint"] == "http://127.0.0.1:8080"
    assert by_role["coder"]["id"] == "qwen3:14b-q8_0"
    assert by_role["fallback"]["endpoint"] == "http://127.0.0.1:11434"
    assert by_role["fallback"]["id"] == "llama3.1:latest"
    assert by_role["embedder"]["endpoint"] == "http://127.0.0.1:8091"
    assert by_role["embedder"]["id"] == "qwen3-embedding-0.6b"


def test_models_reflects_kernel_env(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("KOSMOS_LLAMA_SWAP_BASE_URL", "http://127.0.0.1:8090")
    monkeypatch.setenv("KOSMOS_LLAMA_SWAP_DEFAULT_MODEL", "qwen3.8-27b-code")
    monkeypatch.setenv("KOSMOS_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("KOSMOS_OLLAMA_DEFAULT_MODEL", "qwen3-vl:4b")
    monkeypatch.setenv("KOSMOS_EMBEDDER_BASE_URL", "http://127.0.0.1:8091")
    monkeypatch.setenv("KOSMOS_EMBEDDER_MODEL", "qwen3-embedding-0.6b")

    body = client.get("/api/models").json()
    by_role = {m["role"]: m for m in body}
    assert by_role["coder"]["id"] == "qwen3.8-27b-code"
    assert by_role["coder"]["endpoint"] == "http://127.0.0.1:8090"
    assert by_role["fallback"]["id"] == "qwen3-vl:4b"
    assert by_role["fallback"]["endpoint"] == "http://127.0.0.1:11434"
    assert by_role["embedder"]["id"] == "qwen3-embedding-0.6b"


def test_models_strips_trailing_slash(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("KOSMOS_LLAMA_SWAP_BASE_URL", "http://127.0.0.1:8090/")
    monkeypatch.setenv("KOSMOS_OLLAMA_BASE_URL", "http://127.0.0.1:11434/")
    body = client.get("/api/models").json()
    by_role = {m["role"]: m for m in body}
    assert by_role["coder"]["endpoint"] == "http://127.0.0.1:8090"
    assert by_role["fallback"]["endpoint"] == "http://127.0.0.1:11434"


def test_models_vision_capability_on_fallback(client: TestClient) -> None:
    body = client.get("/api/models").json()
    by_role = {m["role"]: m for m in body}
    # The kernel has no separate vision lane; vision lives on the fallback.
    assert "vision" in by_role["fallback"]["capabilities"]
    assert "vision" not in by_role["coder"]["capabilities"]
    assert "embeddings" in by_role["embedder"]["capabilities"]
