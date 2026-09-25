"""Stage 11.14 — ADR-130 kernel-native /api/directory_list.

The panels Knowledge tab previously proxied ``:8020/api/directory_list`` —
the *standalone* engine's repo-root listing. The kernel endpoint lists the
kernel's own workspace root (cwd), depth 1-2, truncated at 500 entries,
with a traversal guard (paths must stay inside the workspace root).
Element schema matches :8020 plus ``is_dir`` (which the standalone engine
omitted — the tab's Type column rendered "file" for every directory).

GPU-free, no Postgres.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kernel import app as kapp


@pytest.fixture()
def client() -> TestClient:
    return TestClient(kapp.app)


# ── Shape + content (against the real kernel repo cwd) ─────────────────────


def test_lists_workspace_root_depth_1(client: TestClient) -> None:
    r = client.get("/api/directory_list")
    assert r.status_code == 200
    body = r.json()
    assert body["depth"] == 1
    assert body["count"] == len(body["entries"]) > 0
    assert body["truncated"] is False
    assert body["errors"] == []
    # element schema: :8020-compatible + is_dir
    for e in body["entries"]:
        for key in ("name", "path", "parent", "type", "is_dir", "size", "mtime", "depth"):
            assert key in e
        assert e["type"] in ("dir", "file")
        assert e["is_dir"] == (e["type"] == "dir")
        if e["is_dir"]:
            assert e["size"] is None
        else:
            assert isinstance(e["size"], int)
    # the kernel repo markers must be visible at depth 1
    names = {x["name"] for x in body["entries"]}
    assert "kernel" in names
    assert "BUILD_LOG.md" in names


def test_depth_2_and_subpath(client: TestClient) -> None:
    r = client.get("/api/directory_list", params={"depth": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["depth"] == 2
    assert any(e["depth"] == 2 for e in body["entries"])

    sub = client.get("/api/directory_list", params={"path": "docs/adrs"})
    assert sub.status_code == 200
    body2 = sub.json()
    assert body2["path"].endswith("docs/adrs")
    assert body2["count"] == len(body2["entries"])
    assert all(e["parent"] == body2["path"] for e in body2["entries"])


def test_depth_clamped(client: TestClient) -> None:
    assert client.get("/api/directory_list", params={"depth": 9}).json()["depth"] == 2
    assert client.get("/api/directory_list", params={"depth": 0}).json()["depth"] == 1


# ── Traversal guard ────────────────────────────────────────────────────────


def test_traversal_guard_rejects_outside_paths(client: TestClient) -> None:
    assert client.get("/api/directory_list", params={"path": "/etc"}).status_code == 400
    assert client.get("/api/directory_list", params={"path": "../../etc"}).status_code == 400


# ── Isolated-cwd cases (tmp workspace) ─────────────────────────────────────


def _client_with_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
    return TestClient(kapp.app)


def test_missing_dir_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client_with_cwd(tmp_path, monkeypatch)
    assert c.get("/api/directory_list", params={"path": "nope"}).status_code == 404


def test_empty_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client_with_cwd(tmp_path, monkeypatch)
    body = c.get("/api/directory_list").json()
    assert body["count"] == 0
    assert body["entries"] == []
    assert body["truncated"] is False


def test_truncation_at_max_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(kapp._DIRECTORY_MAX_ENTRIES + 100):
        (tmp_path / f"file_{i:03d}.txt").write_text("x")
    c = _client_with_cwd(tmp_path, monkeypatch)
    body = c.get("/api/directory_list").json()
    assert body["truncated"] is True
    assert body["count"] == kapp._DIRECTORY_MAX_ENTRIES
    assert len(body["entries"]) == kapp._DIRECTORY_MAX_ENTRIES


def test_size_and_type_correct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world!")
    c = _client_with_cwd(tmp_path, monkeypatch)
    body = c.get("/api/directory_list", params={"depth": 2}).json()
    by_name = {e["name"]: e for e in body["entries"] if e["parent"] == str(tmp_path)}
    assert by_name["a.txt"]["size"] == 5
    assert by_name["a.txt"]["is_dir"] is False
    assert by_name["sub"]["is_dir"] is True
    assert by_name["sub"]["size"] is None
    # depth-2 child visible under sub/
    b = [e for e in body["entries"] if e["name"] == "b.txt"]
    assert b and b[0]["size"] == 6 and b[0]["depth"] == 2
