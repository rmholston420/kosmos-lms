"""ADR-141 Stage 13.9 — repo map substrate port + route.

Donor `tektos/runtime/repo_map_generator.py` (135 LOC, 100% stdlib, zero
`tektos.*` imports) → `kernel/repo_map_generator.py` byte-verbatim
(generic repository-structure substrate → kernel per governing layering
rule). `registry.tektos_repo_map` booted at the composition root with
the Kosmos repo root as `project_root` (donor main.py:1493 mapped the
donor's own repo root — kernel-honest equivalent: map the repo the
substrate lives in); the real `os.walk` scan is scheduled on the running
loop fire-and-forget, exactly as the donor boot did.

Donor route main.py:4617: `not_initialized` when gate-off. The route is
a live status probe — during the async scan `get_stats()` reports the
partial (zero) counts, matching the donor; the route test waits for the
walk to complete, like a probe after boot settles.
"""

from __future__ import annotations

import time

import kernel.app as ka
from fastapi.testclient import TestClient
import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(ka.app) as tc:
        yield tc


def test_repo_map_status_initialized(client):
    """GET /api/repoMap/status → 200, donor initialized envelope; wait
    for the async boot scan (create_task at lifespan) to finish."""
    gen = ka.registry.tektos_repo_map
    assert gen is not None  # booted in lifespan

    deadline = time.monotonic() + 30  # the real os.walk over the repo
    while time.monotonic() < deadline and gen.get_stats()["total_entries"] == 0:
        time.sleep(0.2)

    r = client.get("/api/repoMap/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "initialized"
    stats = body["stats"]
    for key in ("project_root", "total_entries", "files", "directories"):
        assert key in stats, key
    assert stats["total_entries"] > 0
    assert stats["files"] > 0
    assert stats["directories"] > 0
    assert stats["project_root"] == str(gen._project_root)
    # donor accounting: every surviving dir + every .py/.ts/.js file is
    # exactly one entry
    assert stats["files"] + stats["directories"] == stats["total_entries"]


def test_repo_map_status_gate_off(client, monkeypatch):
    """Gate-off (slot None) → donor-verbatim not_initialized at 200."""
    monkeypatch.setattr(ka.registry, "tektos_repo_map", None)
    r = client.get("/api/repoMap/status")
    assert r.status_code == 200
    assert r.json() == {"status": "not_initialized"}


# ── Substrate unit tests (pure logic, temp-tree scan) ────────────────────


def test_build_map_scan_and_exclusions(tmp_path):
    """Donor build_map (repo_map_generator.py:48-105): walks the tree,
    prunes hidden + common non-source dirs, keeps only .py/.ts/.js,
    records import lines per file."""
    from kernel.repo_map_generator import RepoMapGenerator

    root = tmp_path
    (root / "src").mkdir()
    (root / "node_modules").mkdir()
    (root / ".git").mkdir()
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "a.py").write_text("import os\nfrom pathlib import Path\nprint('hi')\n")
    (root / "src" / "b.ts").write_text("import fs from 'fs';\n")
    (root / "src" / "ignored.md").write_text("no imports here\nimport fake\n")
    (root / "node_modules" / "junk.py").write_text("import os\n")
    (root / "src" / "__pycache__" / "c.py").write_text("import os\n")

    gen = RepoMapGenerator(project_root=str(root))
    count = gen.build_map()

    stats = gen.get_stats()
    # pruned dirs (node_modules/.git/__pycache__) are removed from
    # dirs[:] before the walk descends → only `src` survives
    assert stats["files"] == 2  # a.py + b.ts (md / pruned dirs excluded)
    assert stats["directories"] == 1  # only src
    assert stats["total_entries"] == 3
    assert count == 3

    entry = gen.get_entry("src/a.py")
    assert entry is not None
    assert entry.type == "file"
    assert entry.imports == ["import os", "from pathlib import Path"]
    assert gen.get_entry("src/ignored.md") is None  # .md not indexed
    dir_entry = gen.get_entry("src")
    assert dir_entry is not None
    assert dir_entry.type == "directory"


def test_build_map_idempotent_rebuild(tmp_path):
    """Donor: build_map() clears + recounts — a fresh walk sees the
    current tree (rebuild after adding a file counts both)."""
    from kernel.repo_map_generator import RepoMapGenerator

    root = tmp_path
    (root / "x.py").write_text("import os\n")
    gen = RepoMapGenerator(project_root=str(root))
    first = gen.build_map()
    (root / "y.py").write_text("import sys\n")
    second = gen.build_map()
    assert first == 1
    assert second == 2  # fresh walk sees both files
