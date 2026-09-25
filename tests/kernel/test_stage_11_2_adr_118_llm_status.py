"""Stage 11.2 — ADR-118 ``/api/llm/status`` tests.

The top-bar model indicator must report the ACTIVE kernel LLM lane
(ADR-116 failover: llama.cpp :8090 primary → Ollama fallback), not the
embedder model Ollama happens to hold. These tests monkeypatch the
registry + the GPU probe so no real llama-server / nvidia-smi is touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kernel import app as kernel_app_module
from kernel.app import app


client = TestClient(app)


@dataclass
class _StubLlama:
    _base_url: str = "http://127.0.0.1:8090"
    _default_model: str = "qwen3.8-27b-code"


@dataclass
class _StubOllama:
    _base_url: str = "http://127.0.0.1:11434"
    _default_model: str = "qwen3-vl:4b"


@dataclass
class _StubFailover:
    active_backend: str = "primary"
    failover_count: int = 0
    _primary: Any = None
    _fallback: Any = None

    def __post_init__(self) -> None:
        self._primary = _StubLlama()
        self._fallback = _StubOllama()


def _patch_gpu(monkeypatch: pytest.MonkeyPatch, reading: tuple[int, int] | None) -> None:
    async def _fake() -> tuple[int, int] | None:
        return reading

    monkeypatch.setattr(kernel_app_module, "_gpu_vram_bytes", _fake)


def test_llm_status_reports_primary_llama_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "llm", _StubFailover())
    _patch_gpu(monkeypatch, (31_000_000_000, 34_359_738_368))

    r = client.get("/api/llm/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["healthy"] is True
    assert body["backend"] == "llama.cpp"
    assert body["lane"] == "primary"
    assert body["model"] == "qwen3.8-27b-code"
    assert body["base_url"] == "http://127.0.0.1:8090"
    assert body["vram_used_bytes"] == 31_000_000_000
    assert body["vram_capacity_bytes"] == 34_359_738_368
    assert ":8090" in body["detail"]


def test_llm_status_models_catalog_both_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-119: the endpoint carries the kernel-native model catalog."""
    monkeypatch.setattr(kernel_app_module.registry, "llm", _StubFailover())
    _patch_gpu(monkeypatch, None)

    body = client.get("/api/llm/status").json()
    models = {m["lane"]: m for m in body["models"]}
    assert set(models) == {"primary", "fallback"}
    assert models["primary"] == {
        "id": "qwen3.8-27b-code",
        "name": "qwen3.8-27b-code",
        "lane": "primary",
        "backend": "llama.cpp",
        "endpoint": "http://127.0.0.1:8090",
        "active": True,
        "recommended": True,
    }
    assert models["fallback"]["backend"] == "ollama"
    assert models["fallback"]["active"] is False
    assert models["fallback"]["recommended"] is False


def test_llm_status_models_catalog_active_follows_failover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "llm", _StubFailover(active_backend="fallback"))
    _patch_gpu(monkeypatch, None)

    body = client.get("/api/llm/status").json()
    models = {m["lane"]: m for m in body["models"]}
    assert models["primary"]["active"] is False
    assert models["fallback"]["active"] is True


def test_llm_status_reports_fallback_ollama_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fo = _StubFailover(active_backend="fallback")
    monkeypatch.setattr(kernel_app_module.registry, "llm", fo)
    _patch_gpu(monkeypatch, (4_000_000_000, 34_359_738_368))

    r = client.get("/api/llm/status")
    body = r.json()
    assert body["healthy"] is True
    assert body["backend"] == "ollama"
    assert body["lane"] == "fallback"
    assert body["model"] == "qwen3-vl:4b"
    assert body["base_url"] == "http://127.0.0.1:11434"


def test_llm_status_no_gpu_reading_never_fabricates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "llm", _StubFailover())
    _patch_gpu(monkeypatch, None)

    r = client.get("/api/llm/status")
    body = r.json()
    assert body["vram_used_bytes"] is None
    # capacity falls back to the known Colossus constant, never None
    assert body["vram_capacity_bytes"] == 34_359_738_368


def test_llm_status_unhealthy_when_no_llm_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "llm", None)
    monkeypatch.setattr(
        kernel_app_module.registry, "errors", {"llm": "llm_boot_failed"}
    )
    _patch_gpu(monkeypatch, None)

    r = client.get("/api/llm/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["healthy"] is False
    assert body["model"] is None
    assert body["detail"] == "llm_boot_failed"
