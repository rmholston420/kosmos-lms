"""Kernel-wide CSP middleware — ``frame-ancestors 'self'`` (ADR-089).

Home: ``kernel/csp.py`` (Stage 14.1, ADR-109 exit-gate deletion).

Originally lived in ``kernel/tektos_ultima_bridge.py`` (Stage 9.5 moved
it into ``kernel/tektos_ultima_gateway.py``); with the ADR-109 gateway
module deleted, it gets its own module because it is a **kernel-wide
hardening measure**, not gateway functionality: any Kosmos page
(including the static-export shell) cannot be iframed by an external
origin.

Implemented against the raw ASGI interface (not ``BaseHTTPMiddleware``)
so streaming responses are not buffered. If a response already carries a
``Content-Security-Policy`` header, the directive is appended (not
replaced) so existing directives survive.

Mounted kernel-wide by ``kernel/app.py``:
    app.add_middleware(KosmosCSPMiddleware)
"""

from __future__ import annotations

from typing import Any

_CSP_DIRECTIVE = b"frame-ancestors 'self'"
_CSP_HEADER = b"content-security-policy"


class KosmosCSPMiddleware:
    """ASGI middleware appending ``frame-ancestors 'self'`` (ADR-089).

    Survives ADR-091 iframe retirement: moved verbatim from
    ``kernel/tektos_ultima_bridge.py`` (Stage 9.5), then out of the
    ADR-109 gateway module (Stage 14.1) — behavior byte-identical.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        wrapped_send = self._wrap_send(send)
        await self._app(scope, receive, wrapped_send)

    def _wrap_send(self, send: Any) -> Any:
        async def _send(message: Any) -> None:
            if message["type"] != "http.response.start":
                await send(message)
                return

            headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
            merged = self._merge_csp(headers)
            message = {**message, "headers": merged}
            await send(message)

        return _send

    def _merge_csp(
        self,
        headers: list[tuple[bytes, bytes]],
    ) -> list[tuple[bytes, bytes]]:
        out: list[tuple[bytes, bytes]] = []
        found = False
        for name, value in headers:
            if name.lower() == _CSP_HEADER:
                found = True
                if b"frame-ancestors" in value.lower():
                    # Upstream already set frame-ancestors; the strictest
                    # directive wins per CSP spec, so leave it alone.
                    out.append((name, value))
                else:
                    combined = value.rstrip(b"; ") + b"; " + _CSP_DIRECTIVE
                    out.append((name, combined))
            else:
                out.append((name, value))

        if not found:
            out.append((_CSP_HEADER, _CSP_DIRECTIVE))
        return out
