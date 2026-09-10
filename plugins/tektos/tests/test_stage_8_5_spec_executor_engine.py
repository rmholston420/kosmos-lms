"""Stage 8.5 · ADR-107 contract tests — ``TektosSpecExecutor`` engine."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from plugins.tektos.executor import (
    TEKTOS_EXECUTOR_DEFAULT_CONFIDENCE,
    TEKTOS_EXECUTOR_PREDICATE,
    TEKTOS_EXECUTOR_PROVENANCE,
    ExecutionRecord,
    TektosSpecExecutor,
)
from plugins.tektos.executor.engine import (
    _classify_artifact,
    _generate_config_scaffold,
    _generate_python_module,
    _generate_scaffold,
    _generate_test_scaffold,
    _infer_extension,
    _sanitize_filename,
)
from ports.event_envelope import EventEnvelope


# ── Test doubles ───────────────────────────────────────────────────────────


class _Phase:
    def __init__(self, pid: str, description: str, deliverables: tuple[str, ...]) -> None:
        self.id = pid
        self.description = description
        self.deliverables = deliverables


class _Spec:
    def __init__(
        self,
        sid: str = "spec-1",
        description: str = "hello world app",
        phases: tuple[_Phase, ...] = (),
        tech_stack: tuple[str, ...] = ("python",),
    ) -> None:
        self.id = sid
        self.description = description
        self.phases = phases
        self.tech_stack = tech_stack


def _one_phase_spec() -> _Spec:
    return _Spec(
        phases=(
            _Phase(
                "phase-1",
                "Build the greeter",
                ("greeter function", "greeter tests"),
            ),
        ),
    )


class _StubRMem:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write_narrative(self, **kwargs: Any) -> str:  # noqa: ANN401
        self.writes.append(kwargs)
        return f"nar-{len(self.writes)}"


class _StubRMemRaise:
    async def write_narrative(self, **kwargs: Any) -> str:  # noqa: ANN401
        raise RuntimeError("kaboom")


class _StubBus:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> str:
        self.published.append(envelope)
        return "evt-1"


class _HealthySandbox:
    """Fake sandbox that reports healthy and returns exit_code=0."""

    def is_healthy(self) -> bool:
        return True

    async def run(self, request: Any) -> Any:  # noqa: ANN401
        class _R:
            exit_code = 0
            stdout = "ok"
            stderr = ""

        return _R()


class _RaisingSandbox:
    def is_healthy(self) -> bool:
        raise RuntimeError("sandbox is broken")

    async def run(self, request: Any) -> Any:  # noqa: ANN401
        raise AssertionError("should not be reached when unhealthy")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mk_executor(**kwargs: Any) -> TektosSpecExecutor:
    kwargs.setdefault("workspace", tempfile.mkdtemp(prefix="tektos-exec-"))
    return TektosSpecExecutor(**kwargs)


# ── Construction / properties ──────────────────────────────────────────────


def test_constructor_defaults_are_all_unwired() -> None:
    exe = _mk_executor()
    assert exe.is_persistence_bound is False
    assert exe.is_sandbox_bound is False


def test_is_persistence_bound_true_when_relational_memory_provided() -> None:
    exe = _mk_executor(relational_memory=_StubRMem())
    assert exe.is_persistence_bound is True


def test_is_sandbox_bound_true_when_sandbox_healthy() -> None:
    exe = _mk_executor(sandbox=_HealthySandbox())
    assert exe.is_sandbox_bound is True


def test_is_sandbox_bound_false_when_sandbox_is_healthy_raises() -> None:
    exe = _mk_executor(sandbox=_RaisingSandbox())
    assert exe.is_sandbox_bound is False


# ── execute_spec: fully-unwired path ───────────────────────────────────────


def test_execute_spec_unwired_returns_sandbox_unavailable_status() -> None:
    exe = _mk_executor()
    record, nid = _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    assert nid is None
    assert record.status == "sandbox_unavailable"
    # Artifacts still produced despite missing sandbox.
    assert len(record.artifacts) == 2


def test_execute_spec_unwired_populates_ring_buffer() -> None:
    exe = _mk_executor()
    record, _ = _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    recent = exe.list_recent(limit=5)
    assert len(recent) == 1
    assert recent[0].id == record.id


def test_execute_spec_ring_buffer_respects_max_records_cap() -> None:
    exe = _mk_executor(max_records=2)
    for _ in range(4):
        _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    assert len(exe.list_recent(limit=10)) == 2


# ── execute_spec: wired persistence + bus ──────────────────────────────────


def test_execute_spec_wired_persists_via_write_narrative_with_locked_provenance() -> None:
    rmem = _StubRMem()
    exe = _mk_executor(relational_memory=rmem)
    record, nid = _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    assert nid == "nar-1"
    w = rmem.writes[0]
    assert w["provenance"] == TEKTOS_EXECUTOR_PROVENANCE
    assert w["agent_id"] == TEKTOS_EXECUTOR_PROVENANCE
    assert w["title"].startswith(f"{TEKTOS_EXECUTOR_PREDICATE}:")
    assert 0.0 < w["confidence"] <= 1.0
    assert w["confidence"] == pytest.approx(TEKTOS_EXECUTOR_DEFAULT_CONFIDENCE)
    body = json.loads(w["body"])
    assert body["id"] == record.id
    assert body["spec_id"] == record.spec_id


def test_execute_spec_custom_agent_and_confidence_override_defaults() -> None:
    rmem = _StubRMem()
    exe = _mk_executor(relational_memory=rmem)
    _run(
        exe.execute_spec(
            session_id="s1",
            spec=_one_phase_spec(),
            agent_id="custom-agent",
            confidence=0.42,
        )
    )
    w = rmem.writes[0]
    assert w["agent_id"] == "custom-agent"
    assert w["confidence"] == pytest.approx(0.42)


def test_execute_spec_publishes_event_envelope_with_locked_predicate() -> None:
    bus = _StubBus()
    exe = _mk_executor(relational_memory=_StubRMem(), event_bus=bus)
    record, _ = _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    env = bus.published[0]
    assert env.event_type == TEKTOS_EXECUTOR_PREDICATE
    assert env.producer_plugin == TEKTOS_EXECUTOR_PROVENANCE
    assert env.payload["execution_id"] == record.id
    assert env.payload["spec_id"] == record.spec_id
    assert env.payload["status"] == record.status
    assert env.payload["artifact_count"] == len(record.artifacts)


def test_write_narrative_failure_kept_in_memory_buffer_fail_open() -> None:
    exe = _mk_executor(relational_memory=_StubRMemRaise())
    record, nid = _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    assert nid is None
    assert exe.list_recent(limit=1)[0].id == record.id


# ── Sandbox path ───────────────────────────────────────────────────────────


def test_execute_spec_with_healthy_sandbox_reaches_completed_status() -> None:
    sb = _HealthySandbox()
    exe = _mk_executor(sandbox=sb)
    record, _ = _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    assert record.status == "completed"
    # phase-tests + lint should have populated at least one test report.
    assert len(record.test_results) == 1
    assert record.test_results[0].status == "passed"


# ── Dataclass immutability ─────────────────────────────────────────────────


def test_execution_record_is_frozen_dataclass() -> None:
    exe = _mk_executor()
    record, _ = _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    assert isinstance(record, ExecutionRecord)
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        record.status = "failed"  # type: ignore[misc]


# ── Ring buffer contract ───────────────────────────────────────────────────


def test_list_recent_zero_or_negative_returns_empty_tuple() -> None:
    exe = _mk_executor()
    _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    assert exe.list_recent(limit=0) == ()
    assert exe.list_recent(limit=-1) == ()


# ── Donor helper coverage ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "deliverable,tech_stack,expected",
    [
        ("python parser", (), "py"),
        ("react component", (), "js"),
        ("typescript type", (), "ts"),
        ("html page", (), "html"),
        ("stylesheet css", (), "css"),
        ("config file", (), "yaml"),
        ("unit test", (), "test.py"),
        ("mystery blob", (), "py"),  # default
    ],
)
def test_infer_extension_covers_donor_branches(
    deliverable: str, tech_stack: tuple[str, ...], expected: str
) -> None:
    assert _infer_extension(deliverable, tech_stack) == expected


def test_sanitize_filename_collapses_repeats_and_truncates() -> None:
    result = _sanitize_filename("  Hello,  WORLD!!! " * 10)
    assert result == result.lower()
    assert "__" not in result
    assert len(result) <= 50


def test_classify_artifact_matches_donor_branch_dispatch() -> None:
    assert _classify_artifact("greeter tests") == "test_code"
    assert _classify_artifact("app config") == "config"
    assert _classify_artifact("api documentation") == "documentation"
    assert _classify_artifact("greeter docs") == "documentation"
    assert _classify_artifact("greeter function") == "source_code"


def test_generate_scaffold_dispatches_to_test_config_docs_and_default() -> None:
    spec = _Spec()
    phase = _Phase("p1", "d", ())
    assert "def test_" in _generate_scaffold("greeter tests", spec, phase)
    assert "Configuration" in _generate_scaffold("app config", spec, phase)
    docs_out = _generate_scaffold("documentation", spec, phase)
    assert spec.description in docs_out
    assert "TODO" in docs_out and "class " not in docs_out
    default = _generate_scaffold("greeter function", spec, phase)
    assert "class " in default and "def execute" in default


def test_generate_python_module_uses_class_and_spec_metadata() -> None:
    spec = _Spec()
    module = _generate_python_module("greeter function", spec, _Phase("p1", "d", ()))
    assert "class " in module
    assert spec.description in module
    assert spec.id in module


def test_generate_test_scaffold_emits_two_test_functions() -> None:
    spec = _Spec()
    scaffold = _generate_test_scaffold("greeter function", spec)
    assert "def test_greeter_function" in scaffold
    assert "def test_greeter_function_edge_cases" in scaffold


def test_generate_config_scaffold_references_spec_metadata() -> None:
    spec = _Spec()
    cfg = _generate_config_scaffold(spec)
    assert spec.description in cfg
    assert spec.id in cfg


# ── Artifact classification wired end-to-end ──────────────────────────────


def test_execute_spec_classifies_artifact_types_per_deliverable() -> None:
    spec = _Spec(
        phases=(
            _Phase(
                "phase-1",
                "mixed",
                ("greeter function", "greeter tests", "app config", "api documentation"),
            ),
        ),
    )
    exe = _mk_executor()
    record, _ = _run(exe.execute_spec(session_id="s1", spec=spec))
    types = {a.artifact_type for a in record.artifacts}
    assert {"source_code", "test_code", "config", "documentation"} <= types


def test_execute_spec_top_level_failure_when_phases_attribute_missing() -> None:
    class _BadSpec:
        id = "spec-bad"
        description = "no phases attr"
        tech_stack = ()

        @property
        def phases(self) -> tuple:  # noqa: ANN201
            raise RuntimeError("boom")

    exe = _mk_executor()
    record, _ = _run(exe.execute_spec(session_id="s1", spec=_BadSpec()))
    assert record.status == "failed"
    assert "execute_spec failure" in record.error_summary


def test_execute_spec_writes_artifacts_to_workspace_directory() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="tektos-exec-out-"))
    exe = _mk_executor(workspace=tmp)
    _run(exe.execute_spec(session_id="s1", spec=_one_phase_spec()))
    files = list(tmp.iterdir())
    assert len(files) >= 2
