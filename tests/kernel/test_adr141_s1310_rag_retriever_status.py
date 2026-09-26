"""ADR-141 Stage 13.10 — RAG retriever substrate port + route.

Donor `tektos/runtime/rag_retriever.py` (858 LOC, 100% stdlib +
aiosqlite, zero `tektos.*` imports) → `kernel/rag_retriever.py`
byte-verbatim (generic vector-index substrate → kernel per the
governing layering rule). The donor's `EmbedderClient` seam
(`embed_batch(texts)→.embeddings`, `embed(query)→.embeddings[0]`) is
bridged to the kernel-owned embeddings lane (ADR-124 D1,
`LlamaEmbeddingsAdapter.embed_meta`) by a tiny `_EmbedderBridge` in the
composition root — substrate untouched (ADR-007). `start()` (opens the
SQLite index) is scheduled fire-and-forget on the running loop, as in
the donor's boot (main.py:1464-1470).

Donor route main.py:4661: `initialized` + db_path + initialized flag /
`not_initialized` gate-off at 200.

The retrieval unit test exercises the REAL keyword-fallback path with
no embedder at all (donor: `embedder_client=None` → keyword retrieve) —
pure SQLite + Python, no mocks, no live :8091 required.
"""

from __future__ import annotations

import asyncio
import time

import kernel.app as ka
from fastapi.testclient import TestClient
import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(ka.app) as tc:
        yield tc


def test_rag_retriever_status_initialized(client):
    """GET /api/ragRetriever/status → 200, donor initialized envelope;
    wait for the async start() (SQLite open) to finish first."""
    ret = ka.registry.tektos_rag_retriever
    assert ret is not None  # booted in lifespan (embeddings lane up)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not ret._initialized:
        time.sleep(0.2)

    r = client.get("/api/ragRetriever/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "initialized"
    assert body["initialized"] is True
    assert body["db_path"] == ret._db_path
    assert "tektos_rag.db" in body["db_path"]


def test_rag_retriever_status_gate_off(client, monkeypatch):
    """Gate-off (slot None) → donor-verbatim not_initialized at 200."""
    monkeypatch.setattr(ka.registry, "tektos_rag_retriever", None)
    r = client.get("/api/ragRetriever/status")
    assert r.status_code == 200
    assert r.json() == {"status": "not_initialized"}


# ── Substrate unit tests: real keyword retrieve, no embedder, tmp tree ──


def test_index_and_keyword_retrieve_no_embedder(tmp_path):
    """Donor keyword-fallback path (embedder_client=None): index a temp
    codebase, retrieve by keyword, expect the right file ranked first.
    Real SQLite + real chunking — no mocks."""
    from kernel.rag_retriever import RAGRetriever

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "def authenticate_user(token, session):\n"
        "    # verify the JWT and load the session claims\n"
        "    session.claims = decode_token(token)\n"
        "    return session\n"
    )
    (tmp_path / "src" / "net.py").write_text(
        "def open_http_connection(host, port):\n"
        "    return socket.create_connection((host, port))\n"
    )

    async def run():
        ret = RAGRetriever(
            embedder_client=None,
            project_root=str(tmp_path),
            db_path=str(tmp_path / "rag_test.db"),
        )
        await ret.start()
        n = await ret.index_codebase()
        results = await ret.retrieve("authenticate user token session", top_k=3)
        await ret.stop()
        return n, results

    n, results = asyncio.run(run())
    assert n >= 2  # both files produced at least one chunk
    assert len(results) >= 1
    top = results[0]
    # the auth file must rank first for an auth query
    assert "auth" in top.source_id
    assert top.score >= 0
