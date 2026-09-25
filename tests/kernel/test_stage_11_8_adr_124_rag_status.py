"""Stage 11.8 — ADR-124 RAG tests: LlamaEmbeddingsAdapter + /api/rag/status.

Kernel-native RAG pipeline status (replaces the ADR-109 gateway proxy to
:8020). The embedder is the llama.cpp qwen3-embedding-0.6b on :8091
(CPU-only by design — keeps the RTX 5090's 32 GB for the 27B lane on
:8090). Vector store is Qdrant (:6333); the endpoint reports REAL
collection/point counts, never fabricated :8020-style counters.

Endpoint tests fake the registry adapters and point KOSMOS_QDRANT_URL at
a closed port (probe must degrade, never raise, never fabricate). The
llama adapter tests hit the LIVE :8091 embedder (user directive: live
tests over mocks) and skip cleanly if it is not running.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from kernel import app as kernel_app_module
from kernel.app import app

client = TestClient(app)

LIVE_EMBEDDER_URL = os.environ.get(
    "KOSMOS_EMBEDDER_BASE_URL", "http://127.0.0.1:8091"
)
LIVE_EMBEDDER_MODEL = os.environ.get(
    "KOSMOS_EMBEDDER_MODEL", "qwen3-embedding-0.6b"
)


# ── LlamaEmbeddingsAdapter ────────────────────────────────────────────────


def _live_embedder_available() -> bool:
    import httpx

    try:
        r = httpx.get(f"{LIVE_EMBEDDER_URL}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


live_embedder = pytest.mark.skipif(
    not _live_embedder_available(),
    reason="llama.cpp embedder :8091 not running",
)


@live_embedder
def test_llama_adapter_live_health_dims_embed() -> None:
    import asyncio

    from adapters.embeddings.llama.adapter import LlamaEmbeddingsAdapter

    a = LlamaEmbeddingsAdapter()
    try:
        assert a.is_healthy() is True
        assert a.model == LIVE_EMBEDDER_MODEL
        assert a.base_url == LIVE_EMBEDDER_URL
        dims = asyncio.run(a.dimensions())
        assert dims == 1024
        v = asyncio.run(a.embed(texts=["RAG pipeline test"]))
        assert len(v) == 1
        assert len(v[0]) == 1024
    finally:
        asyncio.run(a.close())


@live_embedder
def test_llama_adapter_live_batch_embed() -> None:
    import asyncio

    from adapters.embeddings.llama.adapter import LlamaEmbeddingsAdapter

    a = LlamaEmbeddingsAdapter()
    try:
        vecs = asyncio.run(a.embed(texts=["alpha", "beta", "gamma"]))
        assert len(vecs) == 3
        assert all(len(v) == 1024 for v in vecs)
    finally:
        asyncio.run(a.close())


def test_llama_adapter_env_override() -> None:
    from adapters.embeddings.llama.adapter import LlamaEmbeddingsAdapter

    a = LlamaEmbeddingsAdapter(
        base_url="http://127.0.0.1:9999", default_model="custom-model"
    )
    try:
        assert a.base_url == "http://127.0.0.1:9999"
        assert a.model == "custom-model"
        # No :9999 listener → healthy False, never raises (ADR-023 rule 5).
        assert a.is_healthy() is False
    finally:
        asyncio_run_close(a)


def asyncio_run_close(a) -> None:
    import asyncio

    try:
        asyncio.run(a.close())
    except Exception:
        pass


# ── GET /api/rag/status ───────────────────────────────────────────────────


class _FakeEmbedder:
    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    @property
    def model(self) -> str:
        return "qwen3-embedding-0.6b"

    @property
    def base_url(self) -> str:
        return "http://127.0.0.1:8091"

    def is_healthy(self) -> bool:
        return self._healthy


class _FakeVector:
    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    def is_healthy(self) -> bool:
        return self._healthy


@pytest.fixture
def qdrant_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    # Point the REST probe at a closed port: the probe must degrade
    # (healthy=False, counters None) — never raise, never fabricate.
    monkeypatch.setenv("KOSMOS_QDRANT_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("KOSMOS_QDRANT_API_KEY", raising=False)


def _body() -> dict:
    r = client.get("/api/rag/status")
    assert r.status_code == 200, r.text
    return r.json()


def test_rag_status_envelope_shape(
    monkeypatch: pytest.MonkeyPatch, qdrant_offline
) -> None:
    monkeypatch.setattr(
        kernel_app_module.registry, "embeddings", _FakeEmbedder()
    )
    monkeypatch.setattr(
        kernel_app_module.registry, "vector", _FakeVector()
    )
    body = _body()
    assert body["status"] == "initialized"
    assert body["embedder"] == {
        "available": True,
        "healthy": True,
        "model": "qwen3-embedding-0.6b",
        "base_url": "http://127.0.0.1:8091",
    }
    assert body["vector"]["available"] is True
    # Qdrant offline → counters None (honest), healthy False.
    assert body["stats"]["indexed_count"] is None
    assert body["stats"]["collections"] is None
    assert body["healthy"] is False
    assert any("qdrant" in e for e in body["errors"])
    assert "timestamp" in body


def test_rag_status_embedder_unhealthy(
    monkeypatch: pytest.MonkeyPatch, qdrant_offline
) -> None:
    monkeypatch.setattr(
        kernel_app_module.registry, "embeddings", _FakeEmbedder(healthy=False)
    )
    monkeypatch.setattr(
        kernel_app_module.registry, "vector", _FakeVector()
    )
    body = _body()
    assert body["healthy"] is False
    assert "embedder unhealthy" in body["errors"]


def test_rag_status_missing_adapters_degraded(
    monkeypatch: pytest.MonkeyPatch, qdrant_offline
) -> None:
    monkeypatch.setattr(kernel_app_module.registry, "embeddings", None)
    monkeypatch.setattr(kernel_app_module.registry, "vector", None)
    body = _body()
    assert body["status"] == "degraded"
    assert body["stats"]["has_embedder"] is False
    assert body["stats"]["has_retriever"] is False
    assert body["healthy"] is False


def test_rag_status_vector_is_healthy_raising_never_500(
    monkeypatch: pytest.MonkeyPatch, qdrant_offline
) -> None:
    class _BoomVector:
        def is_healthy(self) -> bool:
            raise RuntimeError("vector probe exploded")

    monkeypatch.setattr(
        kernel_app_module.registry, "embeddings", _FakeEmbedder()
    )
    monkeypatch.setattr(
        kernel_app_module.registry, "vector", _BoomVector()
    )
    r = client.get("/api/rag/status")
    assert r.status_code == 200
    body = r.json()
    assert body["healthy"] is False
    assert any("vector is_healthy" in e for e in body["errors"])


def test_rag_qdrant_probe_real_counts(
    monkeypatch: pytest.MonkeyPatch, qdrant_offline
) -> None:
    """Stub the REST layer: verify the probe reads /healthz → /collections
    → per-collection points_count and sums them honestly."""
    import httpx

    calls: list[str] = []

    class _FakeResp:
        def __init__(self, status: int, payload: dict) -> None:
            self.status_code = status
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    async def fake_get(self, url: str, **_kw):
        calls.append(url)
        if url.endswith("/healthz"):
            return _FakeResp(200, {})
        if url.endswith("/collections"):
            return _FakeResp(
                200,
                {
                    "result": {
                        "collections": [
                            {"name": "rigpa_gnosis"},
                            {"name": "kosmos-memory-default"},
                        ]
                    }
                },
            )
        if url.endswith("/collections/rigpa_gnosis"):
            return _FakeResp(200, {"result": {"points_count": 64}})
        if url.endswith("/collections/kosmos-memory-default"):
            return _FakeResp(200, {"result": {"points_count": 4}})
        return _FakeResp(404, {})

    monkeypatch.setattr(
        kernel_app_module.registry, "embeddings", _FakeEmbedder()
    )
    monkeypatch.setattr(
        kernel_app_module.registry, "vector", _FakeVector()
    )
    # Point the probe back at the stubbed URL; monkeypatch restores
    # httpx.AsyncClient.get automatically at test end.
    monkeypatch.setenv("KOSMOS_QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    body = _body()

    assert any("healthz" in c for c in calls)
    assert body["stats"]["indexed_count"] == 68
    assert body["stats"]["collections"] == 2
    assert body["healthy"] is True
    assert body["errors"] == []
