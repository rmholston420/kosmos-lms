"""ADR-141 T5 — tool management surface (5 routes, donor wire fidelity).

T5a: ``kernel/tool_registry.py`` — donor ``ToolRegistry`` + ``ToolDefinition``
port (substrate; DI event_bus, kernel ``EventEnvelope`` API).
T5b: ``plugins/tektos/tools/sandbox_provider.py`` — donor ``SandboxProvider``
port (7 built-in tool handlers).
T5c: ``plugins/tektos/tools/builtin_defs.py`` — the 7 donor built-in tool
definitions, registered via the composition root (``kernel/app.py`` boot).
T5d: the 5 management routes at donor paths (main.py:2843-2935):
  ``GET /api/tools/schema``, ``POST /api/tools/register`` (donor 501 stub),
  ``POST /api/tools/{name}/enable``, ``POST /api/tools/{name}/disable``,
  ``POST /api/tools/{name}/execute``.

Isolation: ADR-132 pattern — bare ``TestClient`` (no lifespan; the registry
boots in the lifespan, so these tests monkeypatch the module-level
``_tool_registry`` / ``_tool_sandbox`` globals directly) +
``monkeypatch.chdir(tmp_path)`` + an isolated tmp sandbox root so the
built-in tools never touch the real filesystem.

Wire fidelity: every assertion mirrors the donor routes — same keys, same
types, same error shapes (404 ``Unknown tool: {name}``, 501 detail text).
Registry-level donor-vs-kernel wire parity was verified live (13/13
diffs, separate tmp sandboxes, root paths normalized).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import kernel.app as ka
from kernel.tool_registry import ToolDefinition, ToolRegistry
from plugins.tektos.tools.builtin_defs import (
    register_donor_builtins,
    reset_loaded_flag,
)
from plugins.tektos.tools.sandbox_provider import SandboxProvider

BUILTIN_NAMES = [
    "bash",
    "file_read",
    "file_write",
    "file_delete",
    "directory_list",
    "directory_create",
    "search",
]


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def booted(tmp_path, monkeypatch):
    """Boot the T5 globals exactly like the lifespan does, on tmp storage.

    The lifespan boots ``_tool_sandbox = SandboxProvider()`` (fs_root from
    TEKTOS_FS_ROOT, default ``/``) + ``_tool_registry = ToolRegistry(
    event_bus)`` + ``register_donor_builtins``. Tests pin the sandbox to
    ``tmp_path`` so the built-in tools operate on isolated storage, and the
    event bus is None (registry emits best-effort; a None bus is a no-op,
    donor parity for the unwired case).
    """
    reset_loaded_flag()
    sbx = SandboxProvider(fs_root=tmp_path)
    reg = ToolRegistry(event_bus=None)
    register_donor_builtins(reg, sbx)
    monkeypatch.setattr(ka, "_tool_sandbox", sbx)
    monkeypatch.setattr(ka, "_tool_registry", reg)
    monkeypatch.chdir(tmp_path)
    return reg


@pytest.fixture
def client(booted):
    with TestClient(ka.app, raise_server_exceptions=False) as c:
        yield c


# ── T5a: kernel/tool_registry.py — substrate semantics ─────────────────


def test_registry_register_get_list_wire():
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="probe",
            description="A probe tool",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            handler=lambda p: f"echo {p['x']}",
        )
    )
    t = reg.get("probe")
    assert t is not None and t.enabled is True
    # list_tools wire (donor to_dict keys, exact set)
    entry = reg.list_tools()[0]
    assert set(entry) == {
        "name",
        "description",
        "parameters",
        "enabled",
        "timeout",
        "call_count",
        "last_call",
    }
    assert entry["name"] == "probe"
    assert entry["timeout"] == 30  # donor default
    # enabled_only filter
    t.enabled = False
    assert reg.list_tools() == []
    assert len(reg.list_tools(enabled_only=False)) == 1


def test_registry_execute_success_and_error_paths():
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="ok",
            description="d",
            parameters={},
            handler=lambda p: "done",
        )
    )
    reg.register(
        ToolDefinition(
            name="boom",
            description="d",
            parameters={},
            handler=lambda p: (_ for _ in ()).throw(RuntimeError("kaput")),
        )
    )
    assert reg.execute("ok", {}) == "done"
    # donor: error → "Error: {exc}" string (not an exception)
    assert reg.execute("boom", {}) == "Error: kaput"
    assert reg.execute("nope", {}) == "Unknown tool: nope"
    t_ok = reg.get("ok")
    assert t_ok is not None
    t_ok.enabled = False
    assert reg.execute("ok", {}) == "Tool 'ok' is disabled"


def test_registry_executed_calls_counter():
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(name="ok", description="d", parameters={}, handler=lambda p: "x")
    )
    reg.execute("ok", {})
    reg.execute("ok", {})
    entry = reg.list_tools()[0]
    assert entry["call_count"] == 2
    assert entry["last_call"] > 0


def test_registry_schema_wire():
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="t",
            description="d",
            parameters={"type": "object", "properties": {"a": {"type": "string"}}},
            handler=lambda p: "x",
        )
    )
    reg.register(
        ToolDefinition(name="off", description="d", parameters={}, enabled=False, handler=lambda p: "x")
    )
    schema = reg.to_tools_schema()
    assert len(schema) == 1  # enabled-only (donor)
    assert schema[0] == {
        "type": "function",
        "function": {"name": "t", "description": "d", "parameters": schema[0]["function"]["parameters"]},
    }


def test_registry_event_bus_capture(tmp_path):
    """Donor ``tool.*`` events, wrapped in the kernel EventEnvelope.

    The kernel ``EventBusPort`` is async (ADR-023); the registry bridges a
    sync call site via fire-and-forget ``create_task`` — so this test runs
    inside a loop and lets the scheduled publishes drain.
    """
    import asyncio

    from ports.event_envelope import EventEnvelope

    captured: list[EventEnvelope] = []

    class Bus:
        async def publish(self, env):
            captured.append(env)
            return "entry-1"

    async def run():
        reg = ToolRegistry(event_bus=Bus())
        reg.register(
            ToolDefinition(name="ok", description="d", parameters={}, handler=lambda p: "x")
        )
        reg.execute("ok", {})
        reg.unregister("ok")
        await asyncio.sleep(0)  # let the fire-and-forget tasks drain
        return reg

    reg = asyncio.run(run())
    del reg
    types = [e.event_type for e in captured]
    assert types == ["tool.registered", "tool.executed", "tool.unregistered"]
    for e in captured:
        assert e.producer_plugin == "tool-registry"
    assert captured[0].payload == {"tool_name": "ok", "enabled": True}
    assert captured[1].payload["success"] is True
    assert captured[1].payload["tool_name"] == "ok"
    assert "duration" in captured[1].payload


def test_registry_dead_bus_never_raises():
    """A raising event bus must not break a tool call (best-effort, donor-safe)."""

    class BrokenBus:
        def publish(self, env):
            raise RuntimeError("bus down")

    reg = ToolRegistry(event_bus=BrokenBus())
    reg.register(
        ToolDefinition(name="ok", description="d", parameters={}, handler=lambda p: "x")
    )
    assert reg.execute("ok", {}) == "x"


# ── T5b: plugins/tektos/tools/sandbox_provider.py — sandbox semantics ───


def test_sandbox_bash_and_file_roundtrip(tmp_path):
    sbx = SandboxProvider(fs_root=tmp_path)
    # bash
    out = sbx.execute("bash", {"command": "echo hello-t5"})
    assert out.startswith("Exit 0: success")
    assert "hello-t5" in out
    # file_write → file_read (paged header, donor verbatim)
    out = sbx.execute("file_write", {"path": "a/b.txt", "content": "l1\nl2\n"})
    assert out == "Written 6 bytes to a/b.txt"
    out = sbx.execute("file_read", {"path": "a/b.txt"})
    assert "total_lines=2" in out and "truncated=false" in out
    assert "l1" in out and "l2" in out
    # directory_create + directory_list
    out = sbx.execute("directory_create", {"path": "d1"})
    assert out == "Created directory: d1"
    assert "DIR d1/" in sbx.execute("directory_list", {"path": "."})
    # search
    assert "a/b.txt:2: l2" in sbx.execute("search", {"query": "l2", "path": "."})
    # file_delete
    out = sbx.execute("file_delete", {"path": "a/b.txt"})
    assert out == "Deleted file: a/b.txt"


def test_sandbox_escape_blocked(tmp_path):
    sbx = SandboxProvider(fs_root=tmp_path)
    assert "outside sandbox" in sbx.execute("file_read", {"path": "../../etc/passwd"})
    assert "outside sandbox" in sbx.execute("file_write", {"path": "../escape.txt"})
    # in-root traversal resolves under the root → allowed (donor startswith semantics)
    sbx.execute("file_write", {"path": "dir1/f.txt", "content": "v"})
    assert "outside sandbox" not in sbx.execute("file_read", {"path": "dir1/../dir1/f.txt"})


def test_sandbox_unknown_tool_and_empty_command(tmp_path):
    sbx = SandboxProvider(fs_root=tmp_path)
    assert sbx.execute("nope", {}) == "Unknown tool: nope"
    assert sbx.execute("bash", {}) == "Error: No command provided"


# ── T5c: builtin definitions ────────────────────────────────────────────


def test_register_donor_builtins_seven_tools_and_gate(tmp_path):
    reset_loaded_flag()
    sbx = SandboxProvider(fs_root=tmp_path)
    reg = ToolRegistry()
    register_donor_builtins(reg, sbx)
    names = [t["name"] for t in reg.list_tools()]
    assert names == BUILTIN_NAMES  # donor registration order
    # bash carries the donor's 30 s timeout; others default 30 too
    bash_def = reg.get("bash")
    assert bash_def is not None and bash_def.timeout == 30
    # gate: second call is a no-op (donor _built_in_tools_loaded)
    n0 = len(reg.list_tools())
    register_donor_builtins(reg, sbx)
    assert len(reg.list_tools()) == n0
    reset_loaded_flag()


# ── T5d: the 5 routes (donor wire) ─────────────────────────────────────


def test_route_schema(client, booted):
    r = client.get("/api/tools/schema")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"tools"}
    tools = body["tools"]
    assert len(tools) == 7
    assert all(t["type"] == "function" for t in tools)
    names = [t["function"]["name"] for t in tools]
    assert names == BUILTIN_NAMES


def test_route_schema_uninitialized(client, monkeypatch):
    monkeypatch.setattr(ka, "_tool_registry", None)
    r = client.get("/api/tools/schema")
    assert r.status_code == 200
    assert r.json() == {"error": "Tool registry not initialized"}


def test_route_register_is_501_stub(client, booted):
    r = client.post(
        "/api/tools/register",
        json={"name": "evil", "description": "x", "parameters": {}},
    )
    assert r.status_code == 501
    assert (
        r.json()["detail"]
        == "Runtime tool registration over HTTP is not implemented. "
        "Register tools in-process via ToolRegistry.register or expose "
        "them through MCP."
    )
    # and nothing was registered (donor: body referenced then refused)
    assert client.get("/api/tools/schema").json()["tools"] and (
        "evil" not in [t["function"]["name"] for t in client.get("/api/tools/schema").json()["tools"]]
    )


def test_route_disable_enable_roundtrip(client, booted):
    r = client.post("/api/tools/bash/disable")
    assert r.status_code == 200
    assert r.json() == {"status": "disabled", "name": "bash"}
    # schema drops disabled tools (donor to_tools_schema enabled-only)
    names = [t["function"]["name"] for t in client.get("/api/tools/schema").json()["tools"]]
    assert "bash" not in names
    r = client.post("/api/tools/bash/enable")
    assert r.status_code == 200
    assert r.json() == {"status": "enabled", "name": "bash"}
    names = [t["function"]["name"] for t in client.get("/api/tools/schema").json()["tools"]]
    assert "bash" in names


def test_route_enable_disable_unknown_404(client, booted):
    for route in ("/api/tools/ghost/disable", "/api/tools/ghost/enable"):
        r = client.post(route)
        assert r.status_code == 404
        assert r.json()["detail"] == "Unknown tool: ghost"


def test_route_execute_success(client, booted, tmp_path):
    r = client.post("/api/tools/file_write/execute", json={"parameters": {"path": "r.txt", "content": "v"}})
    assert r.status_code == 200
    assert r.json() == {"result": "Written 1 bytes to r.txt"}
    assert (tmp_path / "r.txt").read_text() == "v"


def test_route_execute_bash(client, booted):
    r = client.post("/api/tools/bash/execute", json={"parameters": {"command": "echo t5-live"}})
    assert r.status_code == 200
    body = r.json()
    assert "t5-live" in body["result"]


def test_route_execute_unknown_and_disabled(client, booted):
    # unknown tool → donor registry returns the string in the result field
    r = client.post("/api/tools/ghost/execute", json={"parameters": {}})
    assert r.status_code == 200
    assert r.json() == {"result": "Unknown tool: ghost"}
    # disabled tool → donor string
    client.post("/api/tools/bash/disable")
    r = client.post("/api/tools/bash/execute", json={"parameters": {"command": "echo x"}})
    assert r.json() == {"result": "Tool 'bash' is disabled"}


def test_route_execute_uninitialized(client, monkeypatch):
    monkeypatch.setattr(ka, "_tool_registry", None)
    r = client.post("/api/tools/bash/execute", json={"parameters": {"command": "echo x"}})
    assert r.status_code == 200
    assert r.json() == {"error": "Tool registry not initialized"}


# ── T5d boot wiring: the lifespan boots registry + 7 built-ins ──────────


def test_lifespan_boot_wires_seven_tools(tmp_path, monkeypatch):
    """Full-lifespan boot: _tool_registry non-None, 7 built-ins registered."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEKTOS_FS_ROOT", str(tmp_path))
    with TestClient(ka.app) as c:
        assert ka._tool_registry is not None
        names = [t["name"] for t in ka._tool_registry.list_tools()]
        assert names == BUILTIN_NAMES
        r = c.get("/api/tools/schema")
        assert r.status_code == 200
        assert len(r.json()["tools"]) == 7
