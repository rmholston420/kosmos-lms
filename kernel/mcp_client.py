"""kernel.mcp_client — the Model Context Protocol client (ADR-141 Stage 13.15).

Byte-verbatim port of ``tektos-ultima/src/tektos/tools/registry.py``'s
``MCPClient`` (donor lines 319-543, ~225 LOC). The class is a pure generic
substrate: it connects to an external MCP server (HTTP ``tools/list`` via
stdlib ``urllib``; SSE via lazy ``aiohttp``) and imports discovered tools
into a ``ToolRegistry`` through a per-tool ``tools/call`` handler closure.
No Tektos-specific policy lives in it, so per the porting layering rule
it elevates to kernel — the exact counterpart of the
``kernel/tool_registry.py`` (T5a) substrate it plugs into (identical
``ToolDefinition`` constructor + ``ToolRegistry.register`` interface).

Differences from the donor (documented, wire-preserving):

- **``ToolDefinition`` import.** The donor imported its own class from
  ``tektos.tools.registry``; here it is imported from
  ``kernel.tool_registry`` (the T5a byte-faithful port) — same
  constructor signature, so ``_import_tool`` is untouched.
- **``log`` name.** ``tektos.tools.registry`` → ``kosmos.mcp`` (module
  logger, same as every other kernel substrate).
- **SSE ``clientInfo`` name.** Kept ``"tektos"`` VERBATIM — it is the
  protocol handshake string the server sees (wire parity), not an
  import.
- **Lazy third-party imports.** ``aiohttp`` (SSE only) and the stdlib
  json/urllib imports stay function-local exactly as in the donor —
  HTTP transport needs zero extra deps; SSE degrades to the donor's
  "requires aiohttp" error when the package is absent.

Wire shapes preserved verbatim:

- ``connect(url, transport)`` → ``{status, url, tools_imported,
  tool_names}`` / ``{status:"error", url, error, tools_imported}``
- ``/api/mcp/status`` reads ``_server_url`` / ``_imported_count``
- ``/api/mcp/connect`` POST → ``connect(...)`` result
"""

from __future__ import annotations

import logging
import time
from typing import Any

from kernel.tool_registry import ToolDefinition

log = logging.getLogger("kosmos.mcp")


class MCPClient:
    """Model Context Protocol client for dynamic tool discovery.

    Connects to an MCP server (HTTP or SSE) and imports discovered tools
    into the ToolRegistry.
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._server_url: str | None = None
        self._imported_count: int = 0

    def connect(self, server_url: str, transport: str = "http") -> dict[str, Any]:
        """Connect to an MCP server and import its tools.

        Args:
            server_url: MCP server URL (e.g., http://localhost:3001/mcp)
            transport: Transport type ('http' or 'sse')

        Returns:
            Dict with connection status and tool count
        """
        self._server_url = server_url
        self._imported_count = 0

        try:
            if transport == "sse":
                return self._connect_sse(server_url)
            else:
                return self._connect_http(server_url)
        except Exception as exc:
            log.error(f"MCP connection failed: {exc}")
            self._server_url = None
            return {
                "status": "error",
                "url": server_url,
                "error": str(exc),
                "tools_imported": 0,
            }

    def _connect_http(self, url: str) -> dict[str, Any]:
        """Connect via HTTP POST to MCP server's list_tools endpoint."""
        import json as _json
        import urllib.request

        payload = _json.dumps({"method": "tools/list", "params": {}, "id": 1}).encode()
        req = urllib.request.Request(
            f"{url}/mcp",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())

        tools = data.get("result", {}).get("tools", [])
        for tool_def in tools:
            self._import_tool(tool_def)

        return {
            "status": "ok",
            "url": url,
            "tools_imported": self._imported_count,
            "tool_names": [t["name"] for t in tools],
        }

    def _connect_sse(self, url: str) -> dict[str, Any]:
        """Connect via SSE to MCP server.

        Follows the MCP SSE transport spec:
        1. GET the SSE endpoint (e.g. http://host:port/sse) — returns a stream
        2. Parse the stream for the "endpoint" message (JSON-RPC base URL)
        3. POST jsonrpc "initialize" to the endpoint
        4. POST jsonrpc "tools/list" to the endpoint
        5. Import discovered tools into the registry
        """
        import asyncio
        import json as _json

        try:
            import aiohttp
        except ImportError:
            log.warning("aiohttp not installed — SSE transport unavailable")
            return {
                "status": "error",
                "url": url,
                "tools_imported": 0,
                "note": "SSE transport requires aiohttp: pip install aiohttp",
            }

        async def _do_connect():
            async with aiohttp.ClientSession() as session:
                # Step 1: GET the SSE endpoint to receive the stream
                sse_base_url = url.rstrip("/")
                if not sse_base_url.endswith("/sse"):
                    sse_base_url = f"{sse_base_url}/sse"

                async with session.get(
                    sse_base_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    # Read SSE lines looking for the "endpoint" message
                    endpoint_url = None
                    async for line in resp.content:
                        text = line.decode("utf-8", errors="replace").strip()
                        if not text:
                            continue
                        if text.startswith("data: "):
                            data_payload = text[6:].strip()
                            try:
                                msg = _json.loads(data_payload)
                                if "endpoint" in msg:
                                    endpoint_url = msg["endpoint"]
                                    break
                            except _json.JSONDecodeError:
                                continue

                # Fallback: if no endpoint found, derive it from the SSE URL
                if not endpoint_url:
                    # SSE URL is like http://host:port/sse → endpoint is http://host:port/mcp
                    base = sse_base_url.rsplit("/sse", 1)[0]
                    endpoint_url = f"{base}/mcp"
                    log.info(
                        "SSE endpoint not found in stream; using derived URL: %s", endpoint_url
                    )

                # Step 2: Send MCP initialize request
                init_payload = _json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "tektos", "version": "0.1.0"},
                        },
                        "id": 1,
                    }
                ).encode()

                async with session.post(
                    endpoint_url,
                    data=init_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    init_response = _json.loads(await resp.text())
                    log.info("MCP initialize response: %s", init_response.get("result", {}))

                # Step 3: Call tools/list to discover tools
                list_payload = _json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "tools/list",
                        "params": {},
                        "id": 2,
                    }
                ).encode()

                async with session.post(
                    endpoint_url,
                    data=list_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = _json.loads(await resp.text())

                tools = data.get("result", {}).get("tools", [])
                for tool_def in tools:
                    self._import_tool(tool_def)

                return {
                    "status": "ok",
                    "url": url,
                    "tools_imported": self._imported_count,
                    "tool_names": [t["name"] for t in tools],
                }

        return asyncio.run(_do_connect())

    def _import_tool(self, tool_def: dict[str, Any]) -> None:
        """Import an MCP tool definition into the registry."""
        name = tool_def.get("name", "")
        if not name:
            return

        schema = tool_def.get("inputSchema", {})
        server_url = self._server_url or ""
        tool_name = name

        def handler(params):
            """Sync wrapper for MCP tool call."""
            try:
                import json as _json
                import urllib.request

                payload = _json.dumps(
                    {
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": params},
                        "id": int(time.time() * 1000),
                    }
                ).encode()
                req = urllib.request.Request(
                    f"{server_url}/mcp",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = _json.loads(resp.read().decode())
                return str(result.get("result", {}))
            except Exception as exc:
                return f"MCP error: {exc}"

        self.registry.register(
            ToolDefinition(
                name=name,
                description=tool_def.get("description", ""),
                parameters=schema if isinstance(schema, dict) else {},
                handler=handler,
                enabled=True,
                timeout=30,
            )
        )
        self._imported_count += 1
        log.info(f"Imported MCP tool: {name}")

    def disconnect(self) -> None:
        """Disconnect from MCP server."""
        self._server_url = None
        log.info("MCP client disconnected")
