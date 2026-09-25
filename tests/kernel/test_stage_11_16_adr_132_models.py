"""Stage 11.16 slice D — ADR-132 kernel-native models picker.

The sessions page previously proxied ``:8020/api/models`` — the *standalone*
Tektos engine, which builds its picker from ``TEKTOS_LLM_*`` env (four
llama-server lanes: primary coder / fallback coder / embedder / vision).

The kernel-native endpoint builds the list from the **kernel's own** ADR-116
/ ADR-132 adapter env — the exact vars the adapters read at boot:

* ``KOSMOS_LLAMA_SWAP_*``   → primary coder lane (llama.cpp, GPU :8090)
* ``KOSMOS_LLM_FALLBACK_*`` → CPU fallback lane (llama.cpp :8092, used only
  when the GPU primary is down)
* ``KOSMOS_EMBEDDER_*``     → embedder lane (llama.cpp, CPU-only :8091)
* ``KOSMOS_VISION_*``       → dedicated vision lane (llama.cpp Qwen3-VL :8094)

So the UI never advertises a model the kernel cannot actually reach, and the
list mirrors the donor's four lanes from the kernel's own config.

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
        "KOSMOS_LLM_FALLBACK_BASE_URL",
        "KOSMOS_LLM_FALLBACK_MODEL",
        "KOSMOS_EMBEDDER_BASE_URL",
        "KOSMOS_EMBEDDER_MODEL",
        "KOSMOS_VISION_BASE_URL",
        "KOSMOS_VISION_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_models_returns_four_lanes(client: TestClient) -> None:
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # Kernel mirrors the donor's four lanes from its own config.
    assert len(body) == 4


def test_models_roles_and_recommended(client: TestClient) -> None:
    body = client.get("/api/models").json()
    roles = [m["role"] for m in body]
    assert roles == ["coder", "fallback", "embedder", "vision"]
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
    # Sidecar / CPU-fallback / CPU-embedder / vision defaults mirror the
    # Collosus deployment (the module defaults are sidecar-only).
    assert by_role["coder"]["endpoint"] == "http://127.0.0.1:8080"
    assert by_role["coder"]["id"] == "qwen3:14b-q8_0"
    assert by_role["fallback"]["endpoint"] == "http://127.0.0.1:8092"
    assert by_role["fallback"]["id"] == "granite4.1-8b-instruct"
    assert by_role["embedder"]["endpoint"] == "http://127.0.0.1:8091"
    assert by_role["embedder"]["id"] == "qwen3-embedding-0.6b"
    assert by_role["vision"]["endpoint"] == "http://127.0.0.1:8094"
    assert by_role["vision"]["id"] == "qwen3-vl-4b"


def test_models_reflects_kernel_env(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("KOSMOS_LLAMA_SWAP_BASE_URL", "http://127.0.0.1:8090")
    monkeypatch.setenv("KOSMOS_LLAMA_SWAP_DEFAULT_MODEL", "qwen3.8-27b-code")
    monkeypatch.setenv("KOSMOS_LLM_FALLBACK_BASE_URL", "http://127.0.0.1:8092")
    monkeypatch.setenv("KOSMOS_LLM_FALLBACK_MODEL", "granite4.1-8b-instruct")
    monkeypatch.setenv("KOSMOS_EMBEDDER_BASE_URL", "http://127.0.0.1:8091")
    monkeypatch.setenv("KOSMOS_EMBEDDER_MODEL", "qwen3-embedding-0.6b")
    monkeypatch.setenv("KOSMOS_VISION_BASE_URL", "http://127.0.0.1:8094")
    monkeypatch.setenv("KOSMOS_VISION_MODEL", "qwen3-vl-4b")

    body = client.get("/api/models").json()
    by_role = {m["role"]: m for m in body}
    assert by_role["coder"]["id"] == "qwen3.8-27b-code"
    assert by_role["coder"]["endpoint"] == "http://127.0.0.1:8090"
    # Fallback reads KOSMOS_LLM_FALLBACK_* — NOT the Ollama lane.
    assert by_role["fallback"]["id"] == "granite4.1-8b-instruct"
    assert by_role["fallback"]["endpoint"] == "http://127.0.0.1:8092"
    assert by_role["embedder"]["id"] == "qwen3-embedding-0.6b"
    assert by_role["vision"]["id"] == "qwen3-vl-4b"
    assert by_role["vision"]["endpoint"] == "http://127.0.0.1:8094"


def test_models_strips_trailing_slash(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("KOSMOS_LLAMA_SWAP_BASE_URL", "http://127.0.0.1:8090/")
    monkeypatch.setenv("KOSMOS_LLM_FALLBACK_BASE_URL", "http://127.0.0.1:8092/")
    monkeypatch.setenv("KOSMOS_VISION_BASE_URL", "http://127.0.0.1:8094/")
    body = client.get("/api/models").json()
    by_role = {m["role"]: m for m in body}
    assert by_role["coder"]["endpoint"] == "http://127.0.0.1:8090"
    assert by_role["fallback"]["endpoint"] == "http://127.0.0.1:8092"
    assert by_role["vision"]["endpoint"] == "http://127.0.0.1:8094"


def test_models_vision_capability_on_vision_lane(client: TestClient) -> None:
    body = client.get("/api/models").json()
    by_role = {m["role"]: m for m in body}
    # The kernel has a dedicated vision lane (llama.cpp :8094); vision is
    # NOT on the Ollama fallback coder.
    assert "vision" in by_role["vision"]["capabilities"]
    assert "vision" not in by_role["fallback"]["capabilities"]
    assert "vision" not in by_role["coder"]["capabilities"]
    assert "embeddings" in by_role["embedder"]["capabilities"]
