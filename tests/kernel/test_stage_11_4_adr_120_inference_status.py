"""Stage 11.4 — ADR-120 ``/api/inference/status`` tests.

Kernel-native probe of the ACTIVE LLM lane (replaces the ADR-109 gateway
proxy to :8020). Envelope mirrors the old standalone shape:
{status, model, base_url, health, llm_available}. Fake httpx — no real
llama-server / Ollama is touched.
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
    _primary: Any = None
    _fallback: Any = None

    def __post_init__(self) -> None:
        self._primary = _StubLlama()
        self._fallback = _StubOllama()


class _FakeResp:
    def __init__(self, ok: bool = True, status_code: int = 200) -> None:
        self.ok = ok
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError("HTTPError")


class _FakeClient:
    _response = _FakeResp()
    _last_url: str | None = None

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *a: Any) -> None:
        pass

    async def get(self, url: str, *a: Any, **k: Any) -> _FakeResp:
        _FakeClient._last_url = url
        return _FakeClient._response


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch, ok: bool = True) -> None:
    import httpx

    _FakeClient._response = _FakeResp(ok=ok)
    _FakeClient._last_url = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


def test_inference_status_probes_primary_llama_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "llm", _StubFailover())
    _install_fake_httpx(monkeypatch, ok=True)

    r = client.get("/api/inference/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "status": "active",
        "model": "qwen3.8-27b-code",
        "base_url": "http://127.0.0.1:8090",
        "health": "ok",
        "llm_available": True,
    }
    # llama.cpp lane is probed via OpenAI /v1/models — not Ollama /api/ps
    assert _FakeClient._last_url == "http://127.0.0.1:8090/v1/models"


def test_inference_status_fallback_lane_probes_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kernel_app_module.registry,
        "llm",
        _StubFailover(active_backend="fallback"),
    )
    _install_fake_httpx(monkeypatch, ok=True)

    body = client.get("/api/inference/status").json()
    assert body["model"] == "qwen3-vl:4b"
    assert body["base_url"] == "http://127.0.0.1:11434"
    assert body["status"] == "active"
    assert _FakeClient._last_url == "http://127.0.0.1:11434/api/version"


def test_inference_status_degraded_when_lane_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "llm", _StubFailover())
    _install_fake_httpx(monkeypatch, ok=False)

    body = client.get("/api/inference/status").json()
    assert body["status"] == "degraded"
    assert body["health"] == "error"
    assert body["llm_available"] is False
    # model/base_url still reported — the card shows *which* lane is down
    assert body["model"] == "qwen3.8-27b-code"
    assert body["base_url"] == "http://127.0.0.1:8090"


def test_inference_status_degraded_when_no_llm_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "llm", None)
    _install_fake_httpx(monkeypatch)

    r = client.get("/api/inference/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "degraded"
    assert body["llm_available"] is False
    assert body["model"] is None
