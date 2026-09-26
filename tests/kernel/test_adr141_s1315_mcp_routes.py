"""ADR-141 Stage 13.15 — mcp ×2: donor MCPClient → kernel substrate.

Donor ``tektos/tools/registry.py:319-543``'s ``MCPClient`` (~225 LOC, pure
generic substrate — connects to an external MCP server over HTTP
``tools/list`` via stdlib urllib, imports discovered tools into a
``ToolRegistry`` with per-tool ``tools/call`` handler closures) →
``kernel/mcp_client.py`` byte-verbatim (generic protocol client → kernel
per the governing layering rule; the only differences are the
``ToolDefinition`` import and the module logger name). Donor routes
``main.py:2930-2954`` wire-verbatim:

  GET  /api/mcp/status  → {connected, url, imported_count} / {connected: false, url: null}
  POST /api/mcp/connect → connect() result:
       ok:    {status: "ok", url, tools_imported, tool_names}
       error: {status: "error", url, error, tools_imported: 0}

Boot (main.py:287-303): ``MCPClient(registry=_tool_registry)`` + best-effort
``connect()`` to ``KOSMOS_MCP_SERVER_URL`` (donor ``TEKTOS_MCP_SERVER_URL``,
default ``http://127.0.0.1:3001/mcp``) / ``KOSMOS_MCP_TRANSPORT`` (default
``http``); connection failure non-fatal.

These tests run the REAL substrate against a REAL local MCP server (stdlib
http.server in a thread — no mocks): the kernel's ``_connect_http`` POSTs a
real ``tools/list`` request, imports the advertised tool into the kernel
ToolRegistry, and the imported tool's real ``tools/call`` round-trip is
executed through ``/api/tools/{name}/execute``.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Must be set BEFORE kernel.app import. Pointed at a DEAD port on purpose:
# the boot's best-effort connect must fail non-fatally (donor parity —
# connection refused → warning, client stays disconnected). A live target
# here would leak into other test modules' lifespan boots (session-wide
# env) and import extra tools into the shared registry. The live fake
# server below is reached only via explicit POST /api/mcp/connect.
_FAKE_PORT = 13901
os.environ["KOSMOS_MCP_SERVER_URL"] = "http://127.0.0.1:1"
os.environ["KOSMOS_MCP_TRANSPORT"] = "http"

import kernel.app as ka
from fastapi.testclient import TestClient


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 — stdlib API
        if self.path != "/mcp":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode())
        method = body.get("method")
        if method == "tools/list":
            payload = {
                "result": {
                    "tools": [
                        {
                            "name": "mcp_echo",
                            "description": "Fake MCP tool (test)",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"msg": {"type": "string"}},
                            },
                        }
                    ]
                }
            }
        elif method == "tools/call":
            args = body.get("params", {}).get("arguments", {})
            payload = {"result": {"echo": args.get("msg", "")}}
        else:
            payload = {"result": {}}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # silence
        pass


_server = ThreadingHTTPServer(("127.0.0.1", _FAKE_PORT), _Handler)
_thread = threading.Thread(target=_server.serve_forever, daemon=True)
_thread.start()


def _tc() -> TestClient:
    return TestClient(ka.app)


def test_mcp_status_wire_shape():
    """GET /api/mcp/status — donor main.py:2930-2939 wire-verbatim.

    Boot connect targets a dead port (module env, non-fatal failure —
    donor parity), so a fresh lifespan reports {connected: false, url:
    null}. After an explicit live connect: {connected, url,
    imported_count}.
    """
    with _tc() as client:
        r = client.get("/api/mcp/status")
        assert r.status_code == 200
        body = r.json()
        # Boot connect failed (dead port, non-fatal): disconnected state.
        assert body["connected"] is False
        assert body["url"] is None

        # Explicit live connect → connected wire with real URL + import count.
        c = client.post(
            "/api/mcp/connect", json={"url": f"http://127.0.0.1:{_FAKE_PORT}"}
        ).json()
        assert c["status"] == "ok"
        s = client.get("/api/mcp/status").json()
        assert s["connected"] is True
        assert s["url"] == f"http://127.0.0.1:{_FAKE_PORT}"
        assert s["imported_count"] == 1

    # Uninitialized-state wire (donor: client is None → {connected: false, url: null}).
    # Call the real route handler directly (no TestClient — a second lifespan
    # would re-boot the client; the handler reads the module global directly).
    import asyncio

    saved = ka._mcp_client
    ka._mcp_client = None
    try:
        assert asyncio.run(ka.get_mcp_status()) == {"connected": False, "url": None}
    finally:
        ka._mcp_client = saved


def test_mcp_connect_success_and_tool_import():
    """POST /api/mcp/connect — donor main.py:2948-2954 wire-verbatim.

    Real HTTP round-trip against the fake MCP server: tools/list returns
    mcp_echo → imported into the kernel ToolRegistry → status reflects it.
    """
    with _tc() as client:
        r = client.post(
            "/api/mcp/connect",
            json={"url": f"http://127.0.0.1:{_FAKE_PORT}", "transport": "http"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["url"] == f"http://127.0.0.1:{_FAKE_PORT}"
        assert body["tools_imported"] == 1
        assert body["tool_names"] == ["mcp_echo"]

        # The imported tool is live in the kernel registry.
        assert ka._tool_registry is not None
        assert ka._tool_registry.get("mcp_echo") is not None

        # /api/mcp/status now reports connected + the import count.
        s = client.get("/api/mcp/status").json()
        assert s["connected"] is True
        assert s["imported_count"] == 1


def test_imported_mcp_tool_executes_round_trip():
    """The imported MCP tool's real tools/call round-trip, end to end.

    /api/tools/mcp_echo/execute → kernel ToolRegistry.execute → the
    donor-verbatim handler closure → POST tools/call to the fake server →
    its result string returned in the donor {result: ...} envelope.
    """
    with _tc() as client:
        # Make sure the tool is imported (idempotent re-connect).
        client.post("/api/mcp/connect", json={"url": f"http://127.0.0.1:{_FAKE_PORT}"})
        r = client.post(
            "/api/tools/mcp_echo/execute", json={"parameters": {"msg": "hello-mcp"}}
        )
        assert r.status_code == 200
        body = r.json()
        # Donor envelope: {"result": <str>}; the handler returns str(result dict).
        assert body["result"].startswith("{'echo':")
        assert "hello-mcp" in body["result"]


def test_mcp_connect_error_wire():
    """POST /api/mcp/connect to a dead URL — donor error wire verbatim.

    {status: "error", url, error, tools_imported: 0} and status flips to
    disconnected (connect() nulls _server_url on failure — donor:33-34).
    """
    dead = "http://127.0.0.1:1"  # port 1 — refused, no network
    with _tc() as client:
        r = client.post(
            "/api/mcp/connect", json={"url": dead, "transport": "http"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "error"
        assert body["url"] == dead
        assert "error" in body and body["error"]
        assert body["tools_imported"] == 0

        s = client.get("/api/mcp/status").json()
        assert s["connected"] is False
        assert s["url"] is None


def teardown_module() -> None:
    # Restore the shared module-global registry to its boot state (7 built-ins):
    # the tests import mcp_echo via live connect, which would otherwise leak
    # into other test modules running later in the same pytest process (the
    # T5 tools-surface test asserts exactly the 7 built-ins).
    reg = getattr(ka, "_tool_registry", None)
    if reg is not None:
        reg.unregister("mcp_echo")
    _server.shutdown()
