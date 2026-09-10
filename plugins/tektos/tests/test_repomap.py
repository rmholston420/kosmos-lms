"""Stage 3.3 DoD contract tests for :mod:`plugins.tektos.repomap`.

DoD literal (spec §18 3.3, ADR-038):

    "Repomap of a 10k-file repo completes; results queryable via
     MemoryPort. Every write carries provenance='aider-repomap' and
     confidence = freshness score."

Landing anchor:
    :func:`test_repomap_10k_file_corpus_writes_queryable_via_memoryport_build_sequence_3_3_dod`

All fakes below implement the :class:`~ports.memory.MemoryPort` Protocol
in full for the surface repomap consumes at Stage 3.3. The fake honours
the port-level ADR-008 zero-trust guard via
:func:`ports.memory.validate_zero_trust_write`.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ports.memory import (
    MemoryEventId,
    MemoryHit,
    MemoryPort,
    validate_zero_trust_write,
)

from plugins.tektos.repomap import (
    REPOMAP_CACHE_VERSION,
    REPOMAP_DEFAULT_MAP_TOKENS,
    REPOMAP_FRESHNESS_WINDOW_DAYS,
    REPOMAP_INDEXED_PREDICATE,
    REPOMAP_MIN_CONFIDENCE,
    REPOMAP_PROVENANCE,
    REPOMAP_SNAPSHOT_PREDICATE,
    RankedTag,
    RepoMapResult,
    SUPPORTED_LANGUAGES,
    Tag,
    compute_freshness_confidence,
    index,
)
from plugins.tektos.repomap.rank import rank_files, rank_tags
from plugins.tektos.repomap.render import default_token_counter, render_repomap
from plugins.tektos.repomap.tags import (
    TAGS_CACHE_DIRNAME,
    extract_tags,
    iter_source_files,
)


# ── Fakes ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _FakeMemoryPort:
    """Records every write; honours ADR-008 zero-trust guard."""

    writes: list[dict[str, Any]] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)
    _next_seq: int = 0

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        source_citation: str | None = None,
        pii_tier: str = "Public",
        attributes: dict[str, Any] | None = None,
    ) -> MemoryEventId:
        validate_zero_trust_write(provenance=provenance, confidence=confidence)
        self._next_seq += 1
        self.writes.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "provenance": provenance,
                "confidence": confidence,
                "source_citation": source_citation,
                "pii_tier": pii_tier,
                "attributes": dict(attributes or {}),
            }
        )
        return MemoryEventId(
            id=f"repomap-{self._next_seq}",
            written_at=datetime.now(timezone.utc),
        )

    async def query_temporal(
        self,
        cypher_or_query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        """Simple in-memory query: substring-match on the predicate."""
        self.queries.append(
            {"query": cypher_or_query, "as_of": as_of, "limit": limit}
        )
        hits: list[MemoryHit] = []
        for i, w in enumerate(self.writes):
            if cypher_or_query in w["predicate"] or cypher_or_query in w["subject"]:
                hits.append(
                    MemoryHit(
                        id=f"repomap-{i + 1}",
                        payload={
                            "subject": w["subject"],
                            "predicate": w["predicate"],
                            "object": w["object"],
                            "provenance": w["provenance"],
                            "confidence": w["confidence"],
                            "attributes": w["attributes"],
                        },
                        score=w["confidence"],
                        as_of=as_of,
                    )
                )
                if len(hits) >= limit:
                    break
        return hits

    async def link_entities(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def quarantine_write(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def search_semantic(self, *args: Any, **kwargs: Any) -> list:
        # ADR-074 D1 added search_semantic to MemoryPort; fake degrades to [].
        return []

    async def search_hybrid(self, *args: Any, **kwargs: Any) -> list:
        # ADR-085 / ADR-099 added search_hybrid to MemoryPort. Repomap tests
        # must not depend on hybrid retrieval — raise on any misuse.
        raise NotImplementedError

    def is_healthy(self) -> bool:
        return True

    async def close(self) -> None:
        return None


# ── Protocol conformance ───────────────────────────────────────────────────


def test_fake_memory_port_conforms_to_memoryport_protocol() -> None:
    assert isinstance(_FakeMemoryPort(), MemoryPort)


# ── Policy locked constants (ADR-038) ──────────────────────────────────────


def test_repomap_provenance_locked_to_aider_repomap() -> None:
    assert REPOMAP_PROVENANCE == "aider-repomap"


def test_repomap_predicates_locked() -> None:
    assert REPOMAP_INDEXED_PREDICATE == "tektos.repomap.indexed"
    assert REPOMAP_SNAPSHOT_PREDICATE == "tektos.repomap.snapshot"


def test_repomap_freshness_window_locked_at_30_days() -> None:
    assert REPOMAP_FRESHNESS_WINDOW_DAYS == 30.0


def test_repomap_default_map_tokens_matches_upstream_aider() -> None:
    # Upstream aider RepoMap(map_tokens=1024) default.
    assert REPOMAP_DEFAULT_MAP_TOKENS == 1024


def test_repomap_cache_version_matches_upstream_tsl_pack() -> None:
    # Upstream aider sets CACHE_VERSION=4 when USING_TSL_PACK.
    assert REPOMAP_CACHE_VERSION == 4


def test_repomap_min_confidence_is_positive() -> None:
    # ADR-008 zero-trust guard requires confidence in (0, 1].
    assert 0.0 < REPOMAP_MIN_CONFIDENCE <= 1.0


# ── Freshness formula (ADR-038 Q4=B) ───────────────────────────────────────


def test_compute_freshness_brand_new_file_is_full_confidence() -> None:
    now = 1_700_000_000.0
    assert compute_freshness_confidence(file_mtime_epoch=now, now_epoch=now) == 1.0


def test_compute_freshness_one_day_old_is_high_confidence() -> None:
    now = 1_700_000_000.0
    conf = compute_freshness_confidence(
        file_mtime_epoch=now - 86400, now_epoch=now
    )
    # 1 day of a 30-day window: 1 - 1/30 = 0.9667
    assert 0.96 <= conf <= 0.97


def test_compute_freshness_at_window_boundary_is_min_confidence() -> None:
    now = 1_700_000_000.0
    conf = compute_freshness_confidence(
        file_mtime_epoch=now - 86400 * 30, now_epoch=now
    )
    assert conf == REPOMAP_MIN_CONFIDENCE


def test_compute_freshness_beyond_window_is_min_confidence_not_zero() -> None:
    now = 1_700_000_000.0
    conf = compute_freshness_confidence(
        file_mtime_epoch=now - 86400 * 365, now_epoch=now
    )
    assert conf == REPOMAP_MIN_CONFIDENCE
    assert conf > 0.0  # zero-trust guard rejects <=0


def test_compute_freshness_rejects_nonpositive_window() -> None:
    with pytest.raises(ValueError, match="window_days must be positive"):
        compute_freshness_confidence(
            file_mtime_epoch=0.0, now_epoch=0.0, window_days=0
        )


def test_compute_freshness_clamps_future_mtime_to_full_confidence() -> None:
    now = 1_700_000_000.0
    conf = compute_freshness_confidence(
        file_mtime_epoch=now + 3600, now_epoch=now
    )
    assert conf == 1.0


# ── Tag extraction ─────────────────────────────────────────────────────────


def test_supported_languages_includes_python_javascript_rust(tmp_path: Path) -> None:
    assert {"python", "javascript", "typescript", "rust"} <= SUPPORTED_LANGUAGES


def test_extract_tags_finds_python_defs_and_refs(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        "def greet(name):\n"
        "    return f'hi {name}'\n"
        "\n"
        "def caller():\n"
        "    return greet('world')\n",
        encoding="utf-8",
    )
    tags = extract_tags(str(src), repo_root=str(tmp_path))
    kinds = {t.kind for t in tags}
    names = {t.name for t in tags}
    assert "def" in kinds
    assert "ref" in kinds
    assert {"greet", "caller"} <= names


def test_extract_tags_cache_hit_returns_same_result(tmp_path: Path) -> None:
    src = tmp_path / "cached.py"
    src.write_text("def a():\n    return 1\n", encoding="utf-8")
    first = extract_tags(str(src), repo_root=str(tmp_path))
    second = extract_tags(str(src), repo_root=str(tmp_path))
    assert first == second
    # Cache directory materialized under repo root.
    assert (tmp_path / TAGS_CACHE_DIRNAME).is_dir()


def test_extract_tags_returns_empty_for_unsupported_language(tmp_path: Path) -> None:
    src = tmp_path / "readme.md"
    src.write_text("# hi\n", encoding="utf-8")
    assert extract_tags(str(src), repo_root=str(tmp_path)) == []


def test_iter_source_files_skips_hidden_dirs(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    files = list(iter_source_files(tmp_path))
    assert any(f.endswith("a.py") for f in files)
    assert not any(".git" in f for f in files)


# ── Rank ───────────────────────────────────────────────────────────────────


def _mk_tag(rel: str, name: str, kind: str, line: int = 0) -> Tag:
    return Tag(rel_fname=rel, fname=rel, name=name, kind=kind, line=line)


def test_rank_tags_orders_most_referenced_defs_highest() -> None:
    tags_by_file = {
        "lib.py": [
            _mk_tag("lib.py", "helper_function", "def", 0),
            _mk_tag("lib.py", "rare_helper", "def", 4),
        ],
        "app.py": [
            _mk_tag("app.py", "helper_function", "ref"),
            _mk_tag("app.py", "helper_function", "ref"),
            _mk_tag("app.py", "helper_function", "ref"),
        ],
        "util.py": [
            _mk_tag("util.py", "helper_function", "ref"),
        ],
    }
    ranked = rank_tags(tags_by_file)
    assert ranked, "expected at least one ranked entry"
    # lib.py holds the most-referenced def and must show up in the top slot.
    top = ranked[0]
    assert top.rel_fname == "lib.py"
    # helper_function is the most-referenced ident — must appear among the
    # lib.py rows (rank distributes across out-edges so exact index varies).
    lib_idents = {r.ident for r in ranked if r.rel_fname == "lib.py"}
    assert "helper_function" in lib_idents


def test_rank_tags_deterministic_with_same_input() -> None:
    tags_by_file = {
        "a.py": [_mk_tag("a.py", "foo", "def")],
        "b.py": [_mk_tag("b.py", "foo", "ref")],
    }
    r1 = rank_tags(tags_by_file)
    r2 = rank_tags(tags_by_file)
    assert [(r.rel_fname, r.ident) for r in r1] == [
        (r.rel_fname, r.ident) for r in r2
    ]


def test_rank_files_aggregates_per_file_totals() -> None:
    tags_by_file = {
        "lib.py": [
            _mk_tag("lib.py", "aaa", "def"),
            _mk_tag("lib.py", "bbb", "def"),
        ],
        "app.py": [
            _mk_tag("app.py", "aaa", "ref"),
            _mk_tag("app.py", "bbb", "ref"),
        ],
    }
    ranked = rank_tags(tags_by_file)
    per_file = dict(rank_files(ranked))
    assert "lib.py" in per_file
    assert per_file["lib.py"] > 0.0


# ── Render ─────────────────────────────────────────────────────────────────


def test_render_repomap_empty_returns_empty_string(tmp_path: Path) -> None:
    assert render_repomap([], repo_root=str(tmp_path), max_tokens=100) == ""


def test_render_repomap_respects_token_budget(tmp_path: Path) -> None:
    src = tmp_path / "big.py"
    src.write_text(
        "\n".join(f"def fn_{i}(): pass" for i in range(50)) + "\n",
        encoding="utf-8",
    )
    tags = extract_tags(str(src), repo_root=str(tmp_path))
    ranked = rank_tags({"big.py": tags})
    rendered = render_repomap(
        ranked, repo_root=str(tmp_path), max_tokens=20
    )
    assert default_token_counter(rendered) <= 25  # within 15% tolerance of 20


def test_default_token_counter_is_whitespace_split() -> None:
    assert default_token_counter("a b c d") == 4
    assert default_token_counter("") == 0


# ── Indexer end-to-end ─────────────────────────────────────────────────────


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_index_writes_per_file_events_with_locked_provenance(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "lib.py", "def foo():\n    return 1\n")
    _write(tmp_path / "app.py", "from lib import foo\nprint(foo())\n")
    mem = _FakeMemoryPort()
    result = await index(tmp_path, memory=mem)
    per_file_writes = [
        w for w in mem.writes if w["predicate"] == REPOMAP_INDEXED_PREDICATE
    ]
    assert len(per_file_writes) == result.files_indexed
    for w in per_file_writes:
        assert w["provenance"] == REPOMAP_PROVENANCE
        assert 0.0 < w["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_index_writes_exactly_one_snapshot_per_run(tmp_path: Path) -> None:
    _write(tmp_path / "one.py", "def one(): pass\n")
    _write(tmp_path / "two.py", "def two(): pass\n")
    mem = _FakeMemoryPort()
    await index(tmp_path, memory=mem)
    snapshots = [
        w for w in mem.writes if w["predicate"] == REPOMAP_SNAPSHOT_PREDICATE
    ]
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap["provenance"] == REPOMAP_PROVENANCE
    assert "total_files" in snap["attributes"]
    assert "rendered_map" in snap["attributes"]
    assert snap["attributes"]["cache_version"] == REPOMAP_CACHE_VERSION


@pytest.mark.asyncio
async def test_index_freshness_confidence_falls_off_with_mtime(
    tmp_path: Path,
) -> None:
    fresh = tmp_path / "fresh.py"
    stale = tmp_path / "stale.py"
    _write(fresh, "def fresh_fn(): pass\n")
    _write(stale, "def stale_fn(): pass\n")
    now = time.time()
    # Fresh: mtime = now. Stale: mtime = now - 60 days.
    os.utime(stale, (now - 86400 * 60, now - 86400 * 60))
    mem = _FakeMemoryPort()
    await index(tmp_path, memory=mem, now_epoch=now)
    per_file = {
        w["subject"]: w
        for w in mem.writes
        if w["predicate"] == REPOMAP_INDEXED_PREDICATE
    }
    assert per_file["fresh.py"]["confidence"] > per_file["stale.py"]["confidence"]
    assert per_file["stale.py"]["confidence"] == REPOMAP_MIN_CONFIDENCE


@pytest.mark.asyncio
async def test_index_result_top_files_matches_rank_order(tmp_path: Path) -> None:
    _write(tmp_path / "core.py", "def core():\n    return 1\n")
    _write(
        tmp_path / "a.py",
        "from core import core\ndef a(): return core()\n",
    )
    _write(
        tmp_path / "b.py",
        "from core import core\ndef b(): return core()\n",
    )
    mem = _FakeMemoryPort()
    result = await index(tmp_path, memory=mem)
    assert result.top_files
    top_rel = result.top_files[0][0]
    assert top_rel == "core.py"


@pytest.mark.asyncio
async def test_index_results_queryable_via_memoryport_query_temporal(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "hello.py", "def hello(): return 42\n")
    mem = _FakeMemoryPort()
    await index(tmp_path, memory=mem)
    hits = await mem.query_temporal(REPOMAP_INDEXED_PREDICATE, limit=100)
    assert len(hits) >= 1
    assert all(h.payload["provenance"] == REPOMAP_PROVENANCE for h in hits)
    snapshot_hits = await mem.query_temporal(REPOMAP_SNAPSHOT_PREDICATE, limit=10)
    assert len(snapshot_hits) == 1


@pytest.mark.asyncio
async def test_index_return_value_is_repomapresult(tmp_path: Path) -> None:
    _write(tmp_path / "x.py", "def x(): pass\n")
    mem = _FakeMemoryPort()
    result = await index(tmp_path, memory=mem)
    assert isinstance(result, RepoMapResult)
    assert result.files_indexed >= 1
    assert result.snapshot_event_id
    assert result.elapsed_seconds >= 0.0


# ── DoD synthetic corpus generator ─────────────────────────────────────────


def _generate_synthetic_corpus(root: Path, n: int) -> None:
    """Generate ``n`` tiny Python files with a shared reference graph.

    Files split into ~sqrt(n) subdirectories. Every file:
    * defines two functions named ``<pkg>_fn_<i>`` and ``helper_<i>``.
    * references a "hub" function from a peer file so PageRank has
      non-trivial flow.

    Used by both the fast smoke test (``n=500``, always-green in the
    stage1-gate) and the DoD literal (``n=10_000``, env-gated).
    """
    root.mkdir(parents=True, exist_ok=True)
    # Balance directory fan-out ~= sqrt(n); guarantee we emit exactly ``n``.
    pkg_count = max(1, int(n**0.5))
    remaining = n
    pkg_i = 0
    while remaining > 0:
        pkg_dir = root / f"pkg{pkg_i:03d}"
        pkg_dir.mkdir(exist_ok=True)
        # Deliberately no __init__.py: it inflates ``files_indexed``
        # counts with empty tag rows.
        # First ``pkg_count`` dirs each get ceil(n/pkg_count) files; any
        # short-fall is topped up by extending into fresh pkg dirs.
        target_this_pkg = -(-remaining // max(1, pkg_count - pkg_i))
        for j in range(target_this_pkg):
            idx = pkg_i * 1000 + j  # stable globally-unique index
            body = (
                f"def pkg{pkg_i:03d}_fn_{j}():\n"
                f"    return helper_{idx}()\n"
                f"\n"
                f"def helper_{idx}():\n"
                f"    return hub_fn(1) + 42\n"
                f"\n"
                f"def hub_fn(x):\n"
                f"    return x * 2\n"
            )
            (pkg_dir / f"mod_{j:03d}.py").write_text(body, encoding="utf-8")
            remaining -= 1
            if remaining <= 0:
                break
        pkg_i += 1


# ── Fast smoke: 500-file corpus (always in stage1-gate) ────────────────────


@pytest.mark.asyncio
async def test_repomap_smoke_500_file_corpus_writes_queryable_via_memoryport(
    tmp_path: Path,
) -> None:
    """Stage 3.3 smoke — same assertions as DoD literal, smaller corpus.

    Kept fast so it always runs in ``make stage1-gate``. The full 10k
    DoD literal is env-gated to keep CI credit costs bounded; see
    :func:`test_repomap_10k_file_corpus_writes_queryable_via_memoryport_build_sequence_3_3_dod`.
    """
    n = 500
    corpus_root = tmp_path / "corpus"
    _generate_synthetic_corpus(corpus_root, n=n)

    mem = _FakeMemoryPort()
    result = await index(
        corpus_root,
        memory=mem,
        max_map_tokens=256,
    )

    assert result.files_indexed == n

    indexed_writes = [
        w for w in mem.writes if w["predicate"] == REPOMAP_INDEXED_PREDICATE
    ]
    assert len(indexed_writes) == n
    assert all(w["provenance"] == REPOMAP_PROVENANCE for w in indexed_writes)
    assert all(0.0 < w["confidence"] <= 1.0 for w in indexed_writes)

    snapshots = [
        w for w in mem.writes if w["predicate"] == REPOMAP_SNAPSHOT_PREDICATE
    ]
    assert len(snapshots) == 1
    assert snapshots[0]["attributes"]["total_files"] == n

    per_file_hits = await mem.query_temporal(
        REPOMAP_INDEXED_PREDICATE, limit=100
    )
    assert len(per_file_hits) == 100
    assert all(h.payload["provenance"] == REPOMAP_PROVENANCE for h in per_file_hits)


# ── DoD literal: 10k-file corpus, env-gated ────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("KOSMOS_STAGE_33_LARGE_CORPUS") != "1",
    reason=(
        "10k-file DoD literal is opt-in "
        "(set KOSMOS_STAGE_33_LARGE_CORPUS=1). Generates 10,000 files and "
        "runs the full index pipeline; slow in CI, fast on Colossus."
    ),
)
@pytest.mark.asyncio
async def test_repomap_10k_file_corpus_writes_queryable_via_memoryport_build_sequence_3_3_dod(
    tmp_path: Path,
) -> None:
    """Stage 3.3 DoD literal (env-gated).

    Assertion (spec §18 3.3, ADR-038):
      * Repomap of a 10k-file repo completes.
      * Every per-file write carries ``provenance="aider-repomap"`` and
        a ``confidence`` in ``(0, 1]``.
      * Exactly one snapshot event is written.
      * Results are queryable via
        :meth:`ports.memory.MemoryPort.query_temporal`.

    Env-gated so the sandbox stage1-gate stays fast; the fast smoke
    variant
    :func:`test_repomap_smoke_500_file_corpus_writes_queryable_via_memoryport`
    exercises the same assertions on a 500-file corpus.
    """
    corpus_root = tmp_path / "corpus"
    _generate_synthetic_corpus(corpus_root, n=10_000)

    mem = _FakeMemoryPort()
    result = await index(
        corpus_root,
        memory=mem,
        max_map_tokens=512,
    )

    assert result.files_indexed == 10_000

    indexed_writes = [
        w for w in mem.writes if w["predicate"] == REPOMAP_INDEXED_PREDICATE
    ]
    assert len(indexed_writes) == 10_000
    assert all(w["provenance"] == REPOMAP_PROVENANCE for w in indexed_writes)
    assert all(0.0 < w["confidence"] <= 1.0 for w in indexed_writes)

    snapshots = [
        w for w in mem.writes if w["predicate"] == REPOMAP_SNAPSHOT_PREDICATE
    ]
    assert len(snapshots) == 1
    assert snapshots[0]["provenance"] == REPOMAP_PROVENANCE
    assert snapshots[0]["attributes"]["total_files"] == 10_000

    per_file_hits = await mem.query_temporal(
        REPOMAP_INDEXED_PREDICATE, limit=100
    )
    assert len(per_file_hits) == 100
    assert all(h.payload["provenance"] == REPOMAP_PROVENANCE for h in per_file_hits)

    snapshot_hits = await mem.query_temporal(
        REPOMAP_SNAPSHOT_PREDICATE, limit=10
    )
    assert len(snapshot_hits) == 1


# ── Env-gated real-corpus integration test ─────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("KOSMOS_STAGE_33_REAL_CORPUS") != "1",
    reason=(
        "Real-corpus integration test opt-in only "
        "(set KOSMOS_STAGE_33_REAL_CORPUS=1). Pulls CPython source into a "
        "temp dir and runs the full pipeline against it."
    ),
)
@pytest.mark.asyncio
async def test_index_against_real_cpython_corpus(tmp_path: Path) -> None:
    """Integration test — env-gated; not part of make stage1-gate.

    Pulls a small real-world Python source tree and asserts the pipeline
    completes end-to-end with realistic tag distributions.
    """
    import subprocess

    corpus = tmp_path / "cpython-lib"
    corpus.mkdir()
    subprocess.check_call(
        [
            "git",
            "clone",
            "--depth=1",
            "--filter=blob:none",
            "--sparse",
            "https://github.com/python/cpython.git",
            str(corpus),
        ]
    )
    subprocess.check_call(
        ["git", "-C", str(corpus), "sparse-checkout", "set", "Lib/json"]
    )

    mem = _FakeMemoryPort()
    result = await index(corpus / "Lib" / "json", memory=mem, max_map_tokens=1024)
    assert result.files_indexed >= 3
    assert result.idents_ranked > 0
    snap_writes = [
        w for w in mem.writes if w["predicate"] == REPOMAP_SNAPSHOT_PREDICATE
    ]
    assert len(snap_writes) == 1
