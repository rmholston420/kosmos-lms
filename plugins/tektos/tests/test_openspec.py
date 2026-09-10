"""Stage 3.6 OpenSpec parser + plan producer contract tests (ADR-040).

Coverage:

* Policy locked constants (ADR-040).
* Completeness-confidence formula bounds.
* Fence-mask semantics.
* Requirement / scenario extraction fence + metadata awareness.
* Task parser fence-block filtering.
* Directory walk + required-artifact enforcement.
* Full DoD literal — ``produce_plan`` on the committed
  ``add-dark-mode`` fixture writes queryable per-artifact + plan events.
* ADR-007 no-cross-plugin-import guard (AST verified).
* ADR-008 zero-trust write guard passthrough.
* ADR-023 envelope-first — no new port surface added.

Every test uses the pure-stdlib ``_FakeMemoryPort`` double defined below;
zero third-party imports required to execute this test module.
"""

from __future__ import annotations

import ast
import inspect
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

from plugins.tektos import openspec as tektos_openspec
from plugins.tektos.openspec import (
    Artifact,
    ArtifactKind,
    DeltaKind,
    Plan,
    PlanProductionResult,
    produce_plan,
)
from plugins.tektos.openspec.parser import (
    ArtifactNotFoundError,
    InvalidChangeDirectoryError,
    compute_fence_mask,
    iter_top_level_sections,
    parse_artifact,
    parse_delta_spec,
    parse_tasks,
    walk_change_directory,
)
from plugins.tektos.openspec.policy import (
    OPENSPEC_ARTIFACT_PREDICATE,
    OPENSPEC_FULL_ARTIFACT_SET,
    OPENSPEC_MIN_CONFIDENCE,
    OPENSPEC_PLAN_PREDICATE,
    OPENSPEC_PROVENANCE,
    OPENSPEC_REQUIRED_ARTIFACTS,
    OPENSPEC_UPSTREAM_COMMIT,
    OPENSPEC_UPSTREAM_LICENSE,
    compute_completeness_confidence,
)

FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "openspec" / "add-dark-mode"
).resolve()


# ── FakeMemoryPort (mirrors test_repomap.py pattern) ───────────────────────


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
            id=f"openspec-{self._next_seq}",
            written_at=datetime.now(timezone.utc),
        )

    async def query_temporal(
        self,
        cypher_or_query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        self.queries.append(
            {"query": cypher_or_query, "as_of": as_of, "limit": limit}
        )
        hits: list[MemoryHit] = []
        for i, w in enumerate(self.writes):
            if (
                cypher_or_query in w["predicate"]
                or cypher_or_query in w["subject"]
            ):
                hits.append(
                    MemoryHit(
                        id=f"openspec-{i + 1}",
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
        # ADR-085 / ADR-099 added search_hybrid to MemoryPort. Openspec tests
        # must not depend on hybrid retrieval — raise on any misuse.
        raise NotImplementedError

    def is_healthy(self) -> bool:
        return True

    async def close(self) -> None:
        return None


# ── Protocol conformance ───────────────────────────────────────────────────


def test_fake_memory_port_conforms_to_memoryport_protocol() -> None:
    assert isinstance(_FakeMemoryPort(), MemoryPort)


# ── Policy locked constants (ADR-040) ──────────────────────────────────────


def test_openspec_provenance_locked_to_openspec_parser() -> None:
    assert OPENSPEC_PROVENANCE == "openspec-parser"


def test_openspec_artifact_predicate_locked() -> None:
    assert OPENSPEC_ARTIFACT_PREDICATE == "tektos.openspec.artifact.parsed"


def test_openspec_plan_predicate_locked() -> None:
    assert OPENSPEC_PLAN_PREDICATE == "tektos.openspec.plan.produced"


def test_openspec_upstream_commit_locked() -> None:
    # Frozen upstream Fission-AI/OpenSpec HEAD 2026-07-30.
    assert OPENSPEC_UPSTREAM_COMMIT == "2b3d368539132be6311e55db58899abbf5306b81"


def test_openspec_upstream_license_is_permissive() -> None:
    assert OPENSPEC_UPSTREAM_LICENSE == "MIT"


def test_openspec_min_confidence_is_positive_and_below_one() -> None:
    assert 0.0 < OPENSPEC_MIN_CONFIDENCE < 1.0


def test_openspec_full_artifact_set_locked() -> None:
    assert OPENSPEC_FULL_ARTIFACT_SET == frozenset(
        {"proposal.md", "design.md", "tasks.md"}
    )


def test_openspec_required_artifacts_locked_to_proposal_only() -> None:
    assert OPENSPEC_REQUIRED_ARTIFACTS == frozenset({"proposal.md"})


# ── compute_completeness_confidence ────────────────────────────────────────


def test_completeness_confidence_full_matches_one() -> None:
    assert compute_completeness_confidence(
        non_empty_sections=4, total_sections=4
    ) == 1.0


def test_completeness_confidence_zero_falls_back_to_min() -> None:
    v = compute_completeness_confidence(
        non_empty_sections=0, total_sections=4
    )
    assert v == OPENSPEC_MIN_CONFIDENCE


def test_completeness_confidence_zero_total_treated_as_one() -> None:
    v = compute_completeness_confidence(
        non_empty_sections=0, total_sections=0
    )
    assert v == OPENSPEC_MIN_CONFIDENCE


def test_completeness_confidence_negative_raises() -> None:
    with pytest.raises(ValueError):
        compute_completeness_confidence(
            non_empty_sections=-1, total_sections=1
        )


def test_completeness_confidence_never_exceeds_one() -> None:
    # Even if non_empty > total (impossible in practice), clamp at 1.0.
    v = compute_completeness_confidence(
        non_empty_sections=99, total_sections=1
    )
    assert v == 1.0


# ── Fence mask ─────────────────────────────────────────────────────────────


def test_fence_mask_marks_content_and_delimiters() -> None:
    text = "before\n```\ninside\n```\nafter"
    mask = compute_fence_mask(text.splitlines())
    assert mask == [False, True, True, True, False]


def test_fence_mask_tilde_fence_supported() -> None:
    text = "before\n~~~\ninside\n~~~\nafter"
    mask = compute_fence_mask(text.splitlines())
    assert mask == [False, True, True, True, False]


def test_fence_mask_unterminated_stays_inside() -> None:
    text = "before\n```\ninside forever"
    mask = compute_fence_mask(text.splitlines())
    assert mask == [False, True, True]


# ── Section iteration ──────────────────────────────────────────────────────


def test_iter_top_level_sections_ignores_fenced_headers() -> None:
    text = (
        "## Real one\n"
        "body\n"
        "```\n"
        "## Fenced one\n"
        "```\n"
        "## Real two\n"
        "body2\n"
    )
    lines = text.splitlines()
    mask = compute_fence_mask(lines)
    sections = iter_top_level_sections(lines, mask)
    heads = [h for (h, _s, _e) in sections]
    assert heads == ["Real one", "Real two"]


# ── Artifact parsing ───────────────────────────────────────────────────────


def test_parse_proposal_artifact_from_fixture() -> None:
    art = parse_artifact(
        FIXTURE_ROOT / "proposal.md",
        ArtifactKind.PROPOSAL,
        base_dir=FIXTURE_ROOT,
    )
    assert art.kind is ArtifactKind.PROPOSAL
    assert art.relative_path == "proposal.md"
    assert art.byte_count > 0
    # Real fixture has: Intent, Scope, Approach, Out of scope.
    assert set(art.section_headers) >= {"Intent", "Scope", "Approach"}
    assert art.non_empty_section_count == len(art.section_headers)
    assert art.completeness_confidence == 1.0


def test_parse_artifact_missing_raises() -> None:
    with pytest.raises(ArtifactNotFoundError):
        parse_artifact(
            FIXTURE_ROOT / "does-not-exist.md",
            ArtifactKind.PROPOSAL,
            base_dir=FIXTURE_ROOT,
        )


# ── Delta spec parsing ─────────────────────────────────────────────────────


def test_parse_delta_spec_extracts_added_modified_removed() -> None:
    ds = parse_delta_spec(
        FIXTURE_ROOT / "specs" / "ui" / "spec.md", base_dir=FIXTURE_ROOT
    )
    assert ds.domain == "ui"
    assert ds.artifact.relative_path == "specs/ui/spec.md"
    # ADDED: two requirements.
    assert len(ds.added) == 2
    assert ds.added[0].heading.startswith("Theme toggle")
    assert ds.added[0].has_normative_keyword is True
    assert ds.added[0].scenario_count == 2
    # System-preference-fallback requirement has metadata lines that must be
    # skipped and 1 scenario.
    assert ds.added[1].scenario_count == 1
    assert ds.added[1].has_normative_keyword is True
    # MODIFIED: one requirement, one scenario.
    assert len(ds.modified) == 1
    assert ds.modified[0].scenario_count == 1
    assert ds.modified[0].has_normative_keyword is True
    # REMOVED: one requirement, zero scenarios (removed reqs have no body
    # scenarios in this fixture).
    assert len(ds.removed) == 1


# ── Task parsing ───────────────────────────────────────────────────────────


def test_parse_tasks_ignores_fenced_checkbox_and_counts_done() -> None:
    items = parse_tasks(FIXTURE_ROOT / "tasks.md")
    # Real fixture: 2 done + 5 undone in the checklist + 2 in validation
    # section = 9 total; the fenced example line MUST NOT count.
    assert len(items) == 9
    done = [t for t in items if t.done]
    assert len(done) == 2
    fenced_texts = [t.text for t in items if "MUST NOT count" in t.text]
    assert fenced_texts == []


def test_parse_tasks_missing_file_returns_empty() -> None:
    result = parse_tasks(FIXTURE_ROOT / "nonexistent.md")
    assert result == ()


# ── Directory walk ─────────────────────────────────────────────────────────


def test_walk_change_directory_discovers_all_artifacts() -> None:
    found = walk_change_directory(FIXTURE_ROOT)
    assert "proposal.md" in found
    assert "design.md" in found
    assert "tasks.md" in found
    assert "specs/ui/spec.md" in found
    assert len(found) == 4


def test_walk_change_directory_missing_dir_raises() -> None:
    with pytest.raises(InvalidChangeDirectoryError):
        walk_change_directory(FIXTURE_ROOT / "not-a-real-change")


def test_walk_change_directory_missing_proposal_raises(tmp_path: Path) -> None:
    (tmp_path / "tasks.md").write_text("- [ ] hi\n")
    with pytest.raises(InvalidChangeDirectoryError):
        walk_change_directory(tmp_path)


# ── DoD literal: produce_plan on fixture ───────────────────────────────────


@pytest.mark.asyncio
async def test_produce_plan_on_add_dark_mode_fixture_writes_queryable_events_build_sequence_3_6_dod() -> None:
    """Stage 3.6 DoD literal.

    "Tektos accepts an OpenSpec doc and produces a plan."

    Invokes ``produce_plan`` on the committed ``add-dark-mode`` fixture,
    asserts:

    * Every artifact write carries locked provenance + valid confidence.
    * Exactly one plan.produced event is written.
    * The MemoryPort ``query_temporal`` surface is queryable by both the
      artifact predicate and the plan predicate.
    * All frozen upstream metadata (commit SHA, license) flows through
      to every write's attributes.
    """
    mem = _FakeMemoryPort()

    result = await produce_plan(FIXTURE_ROOT, mem)

    assert isinstance(result, PlanProductionResult)
    plan = result.plan
    assert isinstance(plan, Plan)
    assert plan.change_id == "add-dark-mode"
    # 4 artifacts: proposal + design + tasks + one delta spec.
    assert plan.artifact_count == 4
    # Per-artifact writes + 1 plan write.
    assert len(mem.writes) == 5
    plan_writes = [
        w for w in mem.writes if w["predicate"] == OPENSPEC_PLAN_PREDICATE
    ]
    assert len(plan_writes) == 1
    artifact_writes = [
        w for w in mem.writes if w["predicate"] == OPENSPEC_ARTIFACT_PREDICATE
    ]
    assert len(artifact_writes) == 4
    # Every write locked provenance + non-zero confidence + upstream meta.
    for w in mem.writes:
        assert w["provenance"] == OPENSPEC_PROVENANCE
        assert w["confidence"] > 0.0
        assert w["confidence"] <= 1.0
        assert w["attributes"]["upstream_commit"] == OPENSPEC_UPSTREAM_COMMIT
        assert w["attributes"]["upstream_license"] == OPENSPEC_UPSTREAM_LICENSE
    # Plan event body reflects real fixture content.
    (pw,) = plan_writes
    assert pw["subject"] == "add-dark-mode"
    assert pw["attributes"]["delta_added"] == 2
    assert pw["attributes"]["delta_modified"] == 1
    assert pw["attributes"]["delta_removed"] == 1
    # Task counts from tasks.md (2 done / 9 total per fixture).
    assert pw["attributes"]["task_count"] == 9
    assert pw["attributes"]["done_task_count"] == 2

    # ---- query_temporal round-trip ----
    plan_hits = await mem.query_temporal(OPENSPEC_PLAN_PREDICATE, limit=10)
    assert len(plan_hits) == 1
    assert plan_hits[0].payload["subject"] == "add-dark-mode"
    artifact_hits = await mem.query_temporal(
        OPENSPEC_ARTIFACT_PREDICATE, limit=10
    )
    assert len(artifact_hits) == 4
    # Per-artifact event ids returned to caller.
    assert set(result.per_artifact_event_ids.keys()) == {
        "proposal.md",
        "design.md",
        "tasks.md",
        "specs/ui/spec.md",
    }


@pytest.mark.asyncio
async def test_produce_plan_with_only_required_proposal(tmp_path: Path) -> None:
    """Minimal-artifact case: only ``proposal.md`` — plan still produces."""
    (tmp_path / "proposal.md").write_text(
        "# Proposal: tiny\n\n## Intent\nSomething.\n"
    )
    mem = _FakeMemoryPort()
    result = await produce_plan(tmp_path, mem)
    assert result.plan.artifact_count == 1
    assert result.plan.design is None
    assert result.plan.tasks_artifact is None
    assert result.plan.tasks == ()
    assert result.plan.delta_specs == ()
    plan_writes = [
        w for w in mem.writes if w["predicate"] == OPENSPEC_PLAN_PREDICATE
    ]
    assert len(plan_writes) == 1
    assert plan_writes[0]["attributes"]["task_count"] == 0


# ── ADR-007: no cross-plugin imports ───────────────────────────────────────


def test_openspec_subsystem_imports_no_other_plugins_adr_007() -> None:
    """AST-verify: no ``import plugins.<other>`` or
    ``from plugins.<other>`` anywhere in
    :mod:`plugins.tektos.openspec`."""
    pkg_root = Path(inspect.getfile(tektos_openspec)).parent
    offenders: list[str] = []
    for py in sorted(pkg_root.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("plugins.") and not node.module.startswith(
                    "plugins.tektos"
                ):
                    offenders.append(f"{py.name}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(
                        "plugins."
                    ) and not alias.name.startswith("plugins.tektos"):
                        offenders.append(f"{py.name}: import {alias.name}")
    assert offenders == [], (
        f"ADR-007 violation — Tektos OpenSpec imports another plugin: "
        f"{offenders}"
    )


# ── ADR-008: zero-trust write guard passthrough ────────────────────────────


@pytest.mark.asyncio
async def test_produce_plan_never_bypasses_memory_port_zero_trust_guard(
    tmp_path: Path,
) -> None:
    """A stub port that always raises MUST propagate — never swallowed."""
    (tmp_path / "proposal.md").write_text(
        "# Proposal: tiny\n\n## Intent\nSomething.\n"
    )

    @dataclass(slots=True)
    class _AlwaysRejectingMemoryPort:
        async def write_event(
            self, *args: Any, **kwargs: Any
        ) -> MemoryEventId:
            raise ValueError("provenance rejected by test")

        async def query_temporal(
            self, *args: Any, **kwargs: Any
        ) -> list[MemoryHit]:
            return []

        async def link_entities(self, *args: Any, **kwargs: Any) -> None:
            raise NotImplementedError

        async def quarantine_write(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def is_healthy(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    with pytest.raises(ValueError, match="provenance rejected by test"):
        await produce_plan(tmp_path, _AlwaysRejectingMemoryPort())
