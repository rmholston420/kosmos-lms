"""Stage 9.1 · ADR-109 — Tektos-Ultima API gateway contract tests.

A real fake upstream (FastAPI + uvicorn on a random 127.0.0.1 port)
stands in for the standalone Tektos API on :8020.  The kernel gateway
router is mounted on a bare FastAPI app and exercised through
``TestClient`` — the same path the production kernel uses
(``kernel/app.py`` mount block).

Covers:
* ``GET /api/tektos-ultima/gateway/health`` — reachable / unavailable
* REST passthrough — body, query params, status code, media type
* SSE passthrough — ``text/event-stream`` forwarded chunk-by-chunk
* upstream-down degradation — typed 503 envelope, kernel stays up
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
import typing as t

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from kernel.tektos_ultima_gateway import (
    _UPSTREAM_ENV,
    build_tektos_ultima_gateway_router,
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_upstream() -> FastAPI:
    """Fake standalone Tektos API — the shape the gateway must proxy."""
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "system": "tektos-upstream-fake"}

    @app.get("/api/echo")
    async def echo(q: str = "") -> JSONResponse:
        return JSONResponse({"echoed": True, "q": q})

    @app.post("/api/echo")
    async def echo_post(request: Request) -> JSONResponse:
        return JSONResponse({"received": await request.json()})

    @app.get("/api/notfound")
    async def notfound() -> JSONResponse:
        return JSONResponse({"detail": "nope"}, status_code=404)

    @app.post("/api/stream")
    async def stream() -> StreamingResponse:
        async def gen() -> t.AsyncIterator[bytes]:
            for i in range(3):
                yield f"event: tick\ndata: {i}\n\n".encode()
                await asyncio.sleep(0.01)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


@pytest.fixture()
def upstream_url() -> t.Iterator[str]:
    """Run the fake upstream on a real socket; set the gateway env var."""
    port = _free_port()
    app = _build_upstream()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        pytest.fail("fake upstream did not come up")

    old = os.environ.get(_UPSTREAM_ENV)
    os.environ[_UPSTREAM_ENV] = f"http://127.0.0.1:{port}"
    yield f"http://127.0.0.1:{port}"
    if old is None:
        os.environ.pop(_UPSTREAM_ENV, None)
    else:
        os.environ[_UPSTREAM_ENV] = old
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def client() -> t.Iterator[TestClient]:
    app = FastAPI()
    app.include_router(build_tektos_ultima_gateway_router())
    with TestClient(app) as c:
        yield c


def test_gateway_health_reachable(client: TestClient, upstream_url: str) -> None:
    resp = client.get("/api/tektos-ultima/gateway/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert body["upstream"] == upstream_url
    assert body["body"]["status"] == "ok"


def test_gateway_health_unavailable(client: TestClient) -> None:
    # Point the gateway at a dead port — kernel must stay up, 503 envelope.
    old = os.environ.get(_UPSTREAM_ENV)
    os.environ[_UPSTREAM_ENV] = "http://127.0.0.1:1"
    try:
        resp = client.get("/api/tektos-ultima/gateway/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["reachable"] is False
        assert body["error"] == "tektos_ultima_unavailable"
    finally:
        if old is None:
            os.environ.pop(_UPSTREAM_ENV, None)
        else:
            os.environ[_UPSTREAM_ENV] = old


def test_rest_get_passthrough(client: TestClient, upstream_url: str) -> None:
    resp = client.get(
        "/api/tektos-ultima/gateway/api/echo", params={"q": "hello"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"echoed": True, "q": "hello"}
    assert resp.headers["content-type"].startswith("application/json")


def test_rest_post_passthrough(client: TestClient, upstream_url: str) -> None:
    resp = client.post(
        "/api/tektos-ultima/gateway/api/echo", json={"a": 1, "b": [2, 3]}
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": {"a": 1, "b": [2, 3]}}


def test_status_code_passthrough(client: TestClient, upstream_url: str) -> None:
    resp = client.get("/api/tektos-ultima/gateway/api/notfound")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "nope"}


def test_sse_passthrough(client: TestClient, upstream_url: str) -> None:
    with client.stream(
        "POST", "/api/tektos-ultima/gateway/api/stream"
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        chunks = list(resp.iter_text())
    text = "".join(chunks)
    assert "event: tick" in text
    assert "data: 0" in text and "data: 1" in text and "data: 2" in text


def test_upstream_down_proxy_returns_503_envelope(
    client: TestClient,
) -> None:
    old = os.environ.get(_UPSTREAM_ENV)
    os.environ[_UPSTREAM_ENV] = "http://127.0.0.1:1"
    try:
        resp = client.get("/api/tektos-ultima/gateway/api/echo")
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"] == "tektos_ultima_unavailable"
        assert "upstream" in body
    finally:
        if old is None:
            os.environ.pop(_UPSTREAM_ENV, None)
        else:
            os.environ[_UPSTREAM_ENV] = old
