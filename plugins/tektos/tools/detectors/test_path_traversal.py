"""Contract tests for ``PathTraversalDetector`` (Stage 4.8 · ADR-094 §D3).

Test surface (per ADR-094 Consequences §Testing):
- happy path: relative path inside NamespaceRoot → no hits
- block: ``.`` and ``..`` components
- block: absolute path outside root
- block: symlink escape
- guard: empty path → block (``empty_path`` reason)
- guard: non-filesystem ``kind`` → returns empty tuple (detector self-filters)
- guard: non-filesystem tool_name → returns empty tuple
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from plugins.tektos.tools.detectors.path_traversal import PathTraversalDetector
from ports.immune import ImmuneScanRequest


def _mk_request(
    *, tool_name: str = "file_read", path: str = "notes.txt", kind: str = "tektos.tool.filesystem"
) -> ImmuneScanRequest:
    return ImmuneScanRequest(
        payload={"tool_name": tool_name, "arguments": {"path": path}},
        kind=kind,
        source_plugin="tektos",
    )


@pytest.mark.asyncio
async def test_relative_path_inside_root_produces_no_hits(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello")
    detector = PathTraversalDetector(namespace_root=tmp_path)
    hits = await detector.evaluate(_mk_request(path="notes.txt"))
    assert hits == ()


@pytest.mark.asyncio
async def test_dotdot_component_is_blocked(tmp_path: Path) -> None:
    detector = PathTraversalDetector(namespace_root=tmp_path)
    hits = await detector.evaluate(_mk_request(path="../etc/passwd"))
    assert len(hits) == 1
    assert hits[0].severity == "block"
    assert "reason=dotdot_component" in hits[0].evidence


@pytest.mark.asyncio
async def test_absolute_escape_is_blocked(tmp_path: Path) -> None:
    detector = PathTraversalDetector(namespace_root=tmp_path)
    hits = await detector.evaluate(_mk_request(path="/etc/passwd"))
    assert len(hits) == 1
    assert hits[0].severity == "block"
    assert "reason=absolute_escape" in hits[0].evidence


@pytest.mark.asyncio
async def test_symlink_escape_is_blocked(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret")
    link = tmp_path / "leak_link"
    os.symlink(outside / "secret.txt", link)

    detector = PathTraversalDetector(namespace_root=tmp_path)
    hits = await detector.evaluate(_mk_request(path="leak_link"))
    assert len(hits) == 1
    assert hits[0].severity == "block"
    assert "reason=symlink_escape" in hits[0].evidence


@pytest.mark.asyncio
async def test_empty_path_is_blocked(tmp_path: Path) -> None:
    detector = PathTraversalDetector(namespace_root=tmp_path)
    hits = await detector.evaluate(_mk_request(path=""))
    assert len(hits) == 1
    assert hits[0].severity == "block"
    assert "reason=empty_path" in hits[0].evidence


@pytest.mark.asyncio
async def test_non_filesystem_kind_returns_empty(tmp_path: Path) -> None:
    detector = PathTraversalDetector(namespace_root=tmp_path)
    hits = await detector.evaluate(
        _mk_request(path="../etc/passwd", kind="tektos.tool.mcp")
    )
    assert hits == ()


@pytest.mark.asyncio
async def test_non_filesystem_tool_name_returns_empty(tmp_path: Path) -> None:
    detector = PathTraversalDetector(namespace_root=tmp_path)
    hits = await detector.evaluate(
        _mk_request(tool_name="shell_exec", path="../etc/passwd")
    )
    assert hits == ()


@pytest.mark.asyncio
async def test_detector_advertises_immune_contract(tmp_path: Path) -> None:
    detector = PathTraversalDetector(namespace_root=tmp_path)
    assert detector.name == "path_traversal"
    assert detector.severity_ceiling == "block"
    assert detector.namespace_root == tmp_path.resolve()
