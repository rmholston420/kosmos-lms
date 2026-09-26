"""ADR-141 T7 — embedder surface routes (donor paths, donor shapes).

Donor referents (tektos-ultima-v1 main.py:4448/4464):
  GET  /api/embedder/status  → {"status": "initialized", "model": ...,
                                "base_url": ...} | {"status":
                                "not_initialized"}
  POST /api/embedder/embed   → {"model", "dimensions", "usage",
                                "embedding_preview"} | {"error": ...}
                                (empty text, uninit, or backend failure —
                                all at 200, donor shape)

Per the layering rule (governing, 2026-09-25) these are NOT a second
EmbedderClient port: the routes are a thin Tektos surface over the
kernel-owned ``registry.embeddings`` (LlamaEmbeddingsAdapter, ADR-124 D1 —
same :8091, same qwen3-embedding-0.6b). The donor's ``usage`` field comes
from the adapter's ``embed_meta()`` (added for T7; the ADR-073 batch
contract ``embed`` deliberately discards it).

The embed tests hit the REAL llama-server embedder on :8091 (live, no
mocks). The degraded/error shapes are exercised by swapping the registry
slot or pointing a fresh adapter at a dead port (restored in each test).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import kernel.app as ka  # noqa: E402


@pytest.fixture(scope="module")
def tc():
    """Real lifespan boot — registry.embeddings boots ungated (ADR-124 D1)."""
    client = TestClient(ka.app)
    with client:
        yield client


def _emb(tc: TestClient):
    emb = ka.registry.embeddings
    assert emb is not None, (
        "embeddings adapter not booted — "
        f"boot error: {ka.registry.errors.get('embeddings')!r}"
    )
    return emb


def test_status_initialized_shape(tc: TestClient) -> None:
    emb = _emb(tc)
    r = tc.get("/api/embedder/status")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "status": "initialized",
        "model": emb._default_model,
        "base_url": emb._base_url,
    }
    # Kernel default lane (ADR-124 D1) — same :8091 / model as the donor.
    assert body["model"] == "qwen3-embedding-0.6b"
    assert body["base_url"] == "http://127.0.0.1:8091"


def test_status_degraded_when_slot_none(tc: TestClient) -> None:
    original = ka.registry.embeddings
    ka.registry.embeddings = None
    try:
        r = tc.get("/api/embedder/status")
        assert r.status_code == 200
        assert r.json() == {"status": "not_initialized"}
    finally:
        ka.registry.embeddings = original


def test_embed_roundtrip_live(tc: TestClient) -> None:
    """Live against the real :8091 llama-server embedder."""
    r = tc.post("/api/embedder/embed", json={"text": "hello kosmos"})
    assert r.status_code == 200
    body = r.json()
    assert "error" not in body
    # Donor shape: model, dimensions, usage, embedding_preview.
    assert set(body) == {"model", "dimensions", "usage", "embedding_preview"}
    assert body["model"] == "qwen3-embedding-0.6b"
    assert body["dimensions"] == 1024
    # llama-server usage block (verified live on :8091).
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["total_tokens"] == body["usage"]["prompt_tokens"]
    # Preview: first 8 dims, real floats (not fabricated).
    assert len(body["embedding_preview"]) == 8
    assert all(isinstance(v, float) for v in body["embedding_preview"])


def test_embed_empty_text_error_at_200(tc: TestClient) -> None:
    r = tc.post("/api/embedder/embed", json={"text": "   "})
    assert r.status_code == 200
    assert r.json() == {"error": "text is required"}


def test_embed_degraded_when_slot_none(tc: TestClient) -> None:
    original = ka.registry.embeddings
    ka.registry.embeddings = None
    try:
        r = tc.post("/api/embedder/embed", json={"text": "hello"})
        assert r.status_code == 200
        assert r.json() == {"error": "embedder not initialized"}
    finally:
        ka.registry.embeddings = original


def test_embed_backend_failure_error_at_200(tc: TestClient) -> None:
    """Adapter pointed at a dead port → donor error shape at 200."""
    from adapters.embeddings.llama.adapter import LlamaEmbeddingsAdapter

    original = ka.registry.embeddings
    dead = LlamaEmbeddingsAdapter(base_url="http://127.0.0.1:9")
    ka.registry.embeddings = dead
    try:
        r = tc.post("/api/embedder/embed", json={"text": "hello"})
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"error"}
        assert body["error"]
    finally:
        ka.registry.embeddings = original
        # The httpx client was used on the TestClient's loop; close it
        # there via the client's blocking portal (cross-loop close invalid).
        assert tc.portal is not None
        tc.portal.call(dead.close)


def test_embed_and_embed_meta_agree(tc: TestClient) -> None:
    """T7's embed_meta() and the ADR-073 embed() share one round-trip:
    same vectors, embed_meta additionally carries usage. A fresh adapter
    instance (own httpx client) is driven on one new event loop — live
    against :8091, no mocks."""
    import asyncio

    from adapters.embeddings.llama.adapter import LlamaEmbeddingsAdapter

    emb = LlamaEmbeddingsAdapter()
    texts = ["vector parity check"]

    async def _run():
        m = await emb.embed_meta(texts=texts)
        v = await emb.embed(texts=texts)
        await emb.close()
        return m, v

    m, v = asyncio.new_event_loop().run_until_complete(_run())
    assert [list(x) for x in m.embeddings] == v
    assert m.usage["prompt_tokens"] > 0
    assert m.model == emb._default_model
