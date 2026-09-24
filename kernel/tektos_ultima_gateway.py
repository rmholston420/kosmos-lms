"""Tektos-Ultima API gateway (Stage 9.1, ADR-109).

Pure proxy from the kosmos kernel to the standalone Tektos-Ultima API
(``TEKTOS_ULTIMA_API_URL``, default ``http://127.0.0.1:8020``).

Native kosmos pages under ``/tektos-ultima/*`` call

    /api/tektos-ultima/gateway/<upstream-path>

instead of hitting :8020 directly.  The kernel owns the upstream base
URL (single env var), normalises failures into a typed envelope, and
passes ``text/event-stream`` responses through byte-for-byte so the
SSE prompt stream (``POST /api/prompt/sse`` upstream) keeps working.

Stage 9.5 retires the iframe proxy + CSP middleware (ADR-091) once
parity is verified; the gateway stays as the kernel-side surface.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)

_UPSTREAM_ENV = "TEKTOS_ULTIMA_API_URL"
_DEFAULT_UPSTREAM = "http://127.0.0.1:8020"
_PREFIX = "/api/tektos-ultima/gateway"
_CLIENT_TIMEOUT = httpx.Timeout(connect=2.0, read=300.0, write=30.0, pool=5.0)
_HOP_HEADERS = {"host", "content-length", "accept-encoding", "connection"}


def _upstream_base() -> str:
    return os.environ.get(_UPSTREAM_ENV, _DEFAULT_UPSTREAM).rstrip("/")


def _unavailable(base: str, exc: Exception) -> JSONResponse:
    return JSONResponse(
        {
            "error": "tektos_ultima_unavailable",
            "detail": f"{type(exc).__name__}: {exc}",
            "upstream": base,
        },
        status_code=503,
    )


def build_tektos_ultima_gateway_router() -> APIRouter:
    """Gateway router — pure proxy, no registry coupling (ADR-109 D2)."""
    router = APIRouter(prefix=_PREFIX, tags=["tektos-ultima-gateway"])

    @router.get("/health")
    async def upstream_health() -> JSONResponse:
        """Upstream reachability probe. 200 when :8020 answers /health."""
        base = _upstream_base()
        try:
            async with httpx.AsyncClient(timeout=_CLIENT_TIMEOUT) as client:
                resp = await client.get(f"{base}/health")
            payload: dict[str, Any] = {
                "upstream": base,
                "reachable": True,
                "status_code": resp.status_code,
                "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None,
            }
            return JSONResponse(payload)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "upstream": base,
                    "reachable": False,
                    "error": "tektos_ultima_unavailable",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
                status_code=503,
            )

    async def _proxy(request: Request) -> Any:
        base = _upstream_base()
        url = f"{base}/{request.path_params['upstream_path']}"
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS
        }
        body = await request.body()
        params = dict(request.query_params)
        # NOTE: client is NOT in an async-with here — for SSE the
        # StreamingResponse generator owns its lifetime (see _forward),
        # which outlives this coroutine.
        client = httpx.AsyncClient(timeout=_CLIENT_TIMEOUT)
        try:
            req = client.build_request(
                request.method, url, content=body, headers=headers, params=params
            )
            resp = await client.send(req, stream=True)
        except Exception as exc:  # noqa: BLE001 — connect/resolve/DNS failure
            await client.aclose()
            logger.warning("tektos-ultima gateway: upstream unreachable: %s", exc)
            return _unavailable(base, exc)

        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("text/event-stream"):
            # Live SSE: _forward() closes response AND client when the
            # stream ends or the browser disconnects.
            return StreamingResponse(
                _forward(client, resp),
                status_code=resp.status_code,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        try:
            raw = await resp.aread()
        except Exception as exc:  # noqa: BLE001 — mid-body upstream drop
            await resp.aclose()
            await client.aclose()
            logger.warning("tektos-ultima gateway: upstream unreachable: %s", exc)
            return _unavailable(base, exc)
        await resp.aclose()
        await client.aclose()
        return Response(
            raw,
            status_code=resp.status_code,
            media_type=ctype or "application/json",
        )

    # Path parameter captures the FULL upstream path: a request to
    # /api/tektos-ultima/gateway/api/sessions proxies to {base}/api/sessions.
    # /health (registered above) wins over this catch-all for that path.
    _route = "/{upstream_path:path}"
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        router.add_api_route(_route, _proxy, methods=[method])
    return router


async def _forward(
    client: httpx.AsyncClient, resp: httpx.Response
) -> Any:
    """Yield upstream SSE bytes until the stream ends."""
    try:
        async for chunk in resp.aiter_bytes():
            yield chunk
    finally:
        await resp.aclose()
