"""Contract tests — Stage 9.2 built-in tools (bash, directory_create, search).

DoD (plan-v2 §9.3 + Stage 9 exit gate): all 7 built-in tools
invocable through the registry. These tests pin the three Stage 9.2
tools the way ``test_filesystem.py`` pins the Stage 4.8 four:

- descriptors registered with the locked tiers
- bash argv is ``["bash", "-c", <command>]`` — argv-only, never
  ``shell=True``
- directory_create / search resolve paths against the namespace root
  and are guarded by the pre-approval PathTraversalDetector
  (``../`` and absolute escapes are blocked before the approval gate)
- benign invocations flow through approval and reach the sandbox
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from adapters.sandbox.noop.adapter import NoOpSandboxAdapter
from ports.approval import ApprovalRecord, ApprovalStatus, ChangeApprovalTier
from ports.event_envelope import EventEnvelope
from plugins.tektos.tools.builtin import (
    BUILTIN_TOOL_NAMES,
    invoke_bash,
    invoke_directory_create,
    invoke_search,
    register_builtin_tools,
)
from plugins.tektos.tools.detectors.path_traversal import (
    PathTraversalDetected,
    PathTraversalDetector,
)
from plugins.tektos.tools.filesystem import FilesystemToolConfig
from plugins.tektos.tools.registry import TektosToolRegistry


class _StubGateway:
    def __init__(self) -> None:
        self.proposals: list[dict[str, Any]] = []

    async def propose(
        self,
        intention_id: str,
        delta: Mapping[str, Any],
        tier: ChangeApprovalTier,
        *,
        proposing_domain: str,
        diff_preview: Mapping[str, Any] | None = None,
    ) -> str:
        approval_id = f"appr-{len(self.proposals) + 1}"
        self.proposals.append(
            {
                "approval_id": approval_id,
                "intention_id": intention_id,
                "tier": tier,
                "delta": dict(delta),
                "diff_preview": dict(diff_preview or {}),
            }
        )
        return approval_id


class _AutoApproveResolver:
    async def get_by_id(self, approval_id: str) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=approval_id,
            intention_id="turn-1",
            proposing_domain="tektos",
            tier=ChangeApprovalTier.HUMAN_REQUIRED,
            delta={},
            status=ApprovalStatus.APPROVED,
            proposed_at=datetime.now(timezone.utc),
            reason=None,
        )

    async def resolve(self, *_args: Any, **_kwargs: Any) -> ApprovalRecord:
        raise NotImplementedError

    async def list_pending(self, **_kwargs: Any) -> tuple[ApprovalRecord, ...]:
        return ()


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return f"evt-{len(self.published)}"


class _RecordingMemory:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        source_citation: Any = None,
        pii_tier: str = "Public",
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        self.events.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "provenance": provenance,
                "confidence": confidence,
                "attributes": dict(attributes or {}),
            }
        )

        class _Id:
            id = f"mem-{len(self.events)}"

        return _Id()

    async def query_temporal(self, *_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ()


def _mk_registry(
    tmp_root: Path, *, with_detector: bool = True
) -> tuple[TektosToolRegistry, _StubGateway, _RecordingBus, _RecordingMemory]:
    gateway = _StubGateway()
    resolver = _AutoApproveResolver()
    bus = _RecordingBus()
    memory = _RecordingMemory()
    detectors: tuple[Any, ...] = ()
    if with_detector:
        detectors = (PathTraversalDetector(namespace_root=tmp_root),)
    registry = TektosToolRegistry(
        approval_gateway=gateway,
        approval_resolver=resolver,
        sandbox=NoOpSandboxAdapter(),
        event_bus=bus,
        pre_approval_detectors=detectors,
        memory=memory,
        detector_scan_source="tektos",
        approval_timeout_seconds=2,
    )
    return registry, gateway, bus, memory


# ── Registration + tiers ────────────────────────────────────────────────


def test_register_builtin_tools_registers_all_three(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)
    assert {d.name for d in registry.list_tools()} == BUILTIN_TOOL_NAMES


def test_builtin_tiers_are_locked(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)
    tiers = {d.name: d.approval_tier for d in registry.list_tools()}
    assert tiers["bash"] is ChangeApprovalTier.HUMAN_REQUIRED
    assert tiers["directory_create"] is ChangeApprovalTier.HUMAN_REQUIRED
    assert tiers["search"] is ChangeApprovalTier.AUTONOMOUS


def test_builtin_descriptors_are_network_none(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)
    for descriptor in registry.list_tools():
        assert descriptor.network == "none", descriptor.name


def test_register_builtin_tools_rejects_duplicate(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)
    with pytest.raises(ValueError):
        register_builtin_tools(registry)


# ── bash semantics ──────────────────────────────────────────────────────


def test_bash_argv_is_bash_dash_c_not_shell_true(tmp_path: Path) -> None:
    registry, gateway, bus, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)
    sandbox = registry._sandbox
    assert isinstance(sandbox, NoOpSandboxAdapter)

    result = asyncio.run(
        invoke_bash(registry, command="echo hello", intention_id="int-bash-1")
    )
    assert result.exit_code == 0
    # The last approval proposal carries the full argument map.
    last_delta = gateway.proposals[-1]["delta"]
    assert last_delta["arguments"]["argv"] == ["bash", "-c", "echo hello"]
    # Registry completed envelope published.
    assert any(e.event_type == "tektos.tool.completed" for e in bus.published)


def test_bash_rejects_missing_command(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)
    with pytest.raises(ValueError):
        asyncio.run(registry.invoke("bash", {}, intention_id="int-bash-2"))


# ── directory_create semantics ──────────────────────────────────────────


def test_directory_create_resolves_and_uses_mkdir_p(tmp_path: Path) -> None:
    registry, gateway, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)

    config = FilesystemToolConfig(namespace_root=tmp_path)
    asyncio.run(
        invoke_directory_create(
            registry, path="build/obj", intention_id="int-mkdir-1", config=config
        )
    )
    delta = gateway.proposals[-1]["delta"]
    argv = delta["arguments"]["argv"]
    assert argv[:2] == ["mkdir", "-p"]
    resolved = Path(argv[2])
    assert resolved.is_absolute()
    assert tmp_path.resolve() in resolved.parents or resolved == tmp_path.resolve()


def test_directory_create_blocks_dotdot_escape(tmp_path: Path) -> None:
    registry, _, bus, memory = _mk_registry(tmp_path)
    register_builtin_tools(registry)

    config = FilesystemToolConfig(namespace_root=tmp_path)
    with pytest.raises(PathTraversalDetected) as exc:
        asyncio.run(
            invoke_directory_create(
                registry,
                path="../escape",
                intention_id="int-mkdir-2",
                config=config,
            )
        )
    assert exc.value.detector_reason == "dotdot_component"
    # ADR-079 rule 1+2: immune verdict published AND written to memory.
    assert any(e.event_type == "immune.verdict.block" for e in bus.published)
    assert any(ev["provenance"] == "immune_verdict" for ev in memory.events)


def test_directory_create_blocks_absolute_escape(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)

    config = FilesystemToolConfig(namespace_root=tmp_path)
    with pytest.raises(PathTraversalDetected) as exc:
        asyncio.run(
            invoke_directory_create(
                registry,
                path="/etc/cron.d",
                intention_id="int-mkdir-3",
                config=config,
            )
        )
    assert exc.value.detector_reason == "absolute_escape"


# ── search semantics ────────────────────────────────────────────────────


def test_search_resolves_path_and_uses_ripgrep_argv(tmp_path: Path) -> None:
    registry, gateway, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)

    config = FilesystemToolConfig(namespace_root=tmp_path)
    asyncio.run(
        invoke_search(
            registry,
            query="def foo",
            intention_id="int-search-1",
            config=config,
            path="src",
        )
    )
    delta = gateway.proposals[-1]["delta"]
    argv = delta["arguments"]["argv"]
    assert argv[0] == "rg"
    assert argv[-2] == "def foo"
    resolved = Path(argv[-1])
    assert resolved.is_absolute()
    assert tmp_path.resolve() in resolved.parents


def test_search_is_autonomous_and_unapproved_polling_skipped(tmp_path: Path) -> None:
    """AUTONOMOUS tier: invoke completes without resolver polling and
    publishes invoked+completed (no approved/denied envelope)."""
    registry, gateway, bus, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)

    config = FilesystemToolConfig(namespace_root=tmp_path)
    result = asyncio.run(
        invoke_search(
            registry,
            query="bar",
            intention_id="int-search-2",
            config=config,
        )
    )
    assert result.exit_code == 0
    types = [e.event_type for e in bus.published]
    assert "tektos.tool.invoked" in types
    assert "tektos.tool.completed" in types
    assert "tektos.tool.denied" not in types


def test_search_blocks_dotdot_escape(tmp_path: Path) -> None:
    registry, _, _, _ = _mk_registry(tmp_path)
    register_builtin_tools(registry)

    config = FilesystemToolConfig(namespace_root=tmp_path)
    with pytest.raises(PathTraversalDetected) as exc:
        asyncio.run(
            invoke_search(
                registry,
                query=".*",
                intention_id="int-search-3",
                config=config,
                path="../../..",
            )
        )
    assert exc.value.detector_reason == "dotdot_component"


# ── Stage 9 exit gate DoD: all 7 built-in tools invocable ───────────────


def test_seven_builtin_tools_all_invocable(tmp_path: Path) -> None:
    """Exit gate: 4 Stage 4.8 filesystem tools + 3 Stage 9.2 built-ins
    registered on ONE registry, every tool invoked to completion."""
    from plugins.tektos.tools.filesystem import register_filesystem_tools

    registry, gateway, bus, _ = _mk_registry(tmp_path)
    config = FilesystemToolConfig(namespace_root=tmp_path)
    register_filesystem_tools(registry, config=config)
    register_builtin_tools(registry)

    names = {d.name for d in registry.list_tools()}
    assert names == {
        # Stage 4.8 (ADR-094 §D3)
        "file_read",
        "file_list",
        "file_write",
        "file_delete",
        # Stage 9.2
        "bash",
        "directory_create",
        "search",
    }

    (tmp_path / "probe.txt").write_text("hello stage 9\n")

    # AUTONOMOUS tools — complete without resolver polling.
    assert asyncio.run(
        registry.invoke("file_read", {"path": "probe.txt", "argv": ["cat", str(tmp_path / "probe.txt")]}, intention_id="gate-1")
    ).exit_code == 0
    assert asyncio.run(
        registry.invoke("file_list", {"path": ".", "argv": ["ls", "-la", str(tmp_path)]}, intention_id="gate-2")
    ).exit_code == 0
    assert asyncio.run(
        invoke_search(registry, query="hello", intention_id="gate-3", config=config)
    ).exit_code == 0

    # Gated tools — auto-approving resolver stands in for the human.
    assert asyncio.run(
        invoke_bash(registry, command="echo gate", intention_id="gate-4")
    ).exit_code == 0
    assert asyncio.run(
        invoke_directory_create(registry, path="out", intention_id="gate-5", config=config)
    ).exit_code == 0
    assert asyncio.run(
        registry.invoke("file_write", {"path": "g.txt", "content": "x", "argv": ["tee", str(tmp_path / "g.txt")], "stdin": "x"}, intention_id="gate-6")
    ).exit_code == 0
    assert asyncio.run(
        registry.invoke("file_delete", {"path": "g.txt", "argv": ["rm", "-rf", str(tmp_path / "g.txt")]}, intention_id="gate-7")
    ).exit_code == 0

    # Every invocation published the completion envelope.
    completed = [
        e for e in bus.published if e.event_type == "tektos.tool.completed"
    ]
    assert len(completed) == 7
    assert all(e.payload.get("provenance") == "tektos_tool" for e in completed)
