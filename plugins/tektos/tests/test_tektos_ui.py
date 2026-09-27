"""Tektos UI HTMX dashboard tests (Stage 3.11, ADR-045).

Two tiers:

* Fast unit tier — runs by default under ``make stage1-gate``. Uses
  FastAPI ``TestClient`` (no port binding) with in-process fake
  collaborators. Covers every route contract from Q1e=A, the three
  Q5=A MemoryPort writes, the Q_res_2=B ``resolved_by="tektos_ui"``
  audit stamp, the vendored-htmx SHA-256 identity, the ADR-007 AST
  guard, the ADR-041 STATUS AMENDMENT (Route added \u2192 COMPLIANT),
  and the DoD literal end-to-end flow.
* Interactive tier — env-gated (``KOSMOS_STAGE_311_INTERACTIVE=1``).
  Boots real uvicorn against ``127.0.0.1:8765`` for manual browser
  verification on Colossus. No asserts.
"""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from adapters.approval_resolver.praxis import PraxisApprovalResolverAdapter
from ports.approval import (
    ApprovalRecord,
    ApprovalResolverPort,
    ApprovalStatus,
    ChangeApprovalTier,
)
from ports.memory import MemoryEventId, MemoryPort, validate_zero_trust_write
from plugins.tektos.plugin import build_tektos_descriptor
from plugins.tektos.ui import (
    DiffRender,
    ExecutionResult,
    ExecutorPort,
    NopExecutor,
    TEKTOS_UI_HEALTHZ_PATH,
    TEKTOS_UI_HTMX_JS_PATH,
    TEKTOS_UI_HTMX_JS_TEMPLATE_HREF,
    TEKTOS_UI_HTMX_SHA256,
    TEKTOS_UI_HTMX_UPSTREAM_COMMIT,
    TEKTOS_UI_HTMX_UPSTREAM_LICENSE,
    TEKTOS_UI_HTMX_VERSION,
    TEKTOS_UI_INDEX_PATH,
    TEKTOS_UI_PLAN_APPROVED_PREDICATE,
    TEKTOS_UI_PLAN_APPROVE_PATH,
    TEKTOS_UI_PLAN_DETAIL_PATH,
    TEKTOS_UI_PLAN_DIFF_PATH,
    TEKTOS_UI_PLAN_DIFF_RENDERED_PREDICATE,
    TEKTOS_UI_PLAN_EXECUTED_PREDICATE,
    TEKTOS_UI_PLAN_EXECUTE_PATH,
    TEKTOS_UI_PROPOSING_DOMAIN,
    TEKTOS_UI_PROVENANCE,
    TEKTOS_UI_RESOLVED_BY,
    TEKTOS_UI_SUCCESS_CONFIDENCE,
    build_tektos_ui_app,
    compute_diff_sha256,
    confidence_for_ui_event,
    render_unified_diff,
)


# ── Fakes ────────────────────────────────────────────────────────────────


class _FakeResolver:
    """In-memory :class:`ApprovalResolverPort` implementation."""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def seed(self, record: ApprovalRecord) -> None:
        self._records[record.approval_id] = record

    async def resolve(
        self,
        approval_id: str,
        approved: bool,
        *,
        reason: str | None = None,
        modifications: Any = None,
        resolved_by: str = "user",
    ) -> ApprovalRecord:
        current = self._records[approval_id]
        if approved:
            new_status = (
                ApprovalStatus.MODIFIED if modifications else ApprovalStatus.APPROVED
            )
        else:
            if not reason:
                raise ValueError("reject requires reason")
            new_status = ApprovalStatus.REJECTED
        updated = ApprovalRecord(
            approval_id=current.approval_id,
            intention_id=current.intention_id,
            proposing_domain=current.proposing_domain,
            tier=current.tier,
            delta=current.delta,
            status=new_status,
            proposed_at=current.proposed_at,
            resolved_at=datetime.now(timezone.utc),
            resolved_by=resolved_by,
            reason=reason,
            modifications=dict(modifications) if modifications else {},
            diff_preview=current.diff_preview,
        )
        self._records[approval_id] = updated
        return updated

    async def get_by_id(self, approval_id: str) -> ApprovalRecord:
        return self._records[approval_id]

    async def list_pending(
        self,
        *,
        proposing_domain: str | None = None,
    ) -> tuple[ApprovalRecord, ...]:
        pending = [
            r for r in self._records.values() if r.status is ApprovalStatus.PENDING
        ]
        if proposing_domain is not None:
            pending = [r for r in pending if r.proposing_domain == proposing_domain]
        return tuple(pending)


class _FakeMemory:
    """Recording :class:`ports.memory.MemoryPort` fake."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        self._counter = 0

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
        self._counter += 1
        event_id = f"mem-{self._counter}"
        self.writes.append(
            {
                "id": event_id,
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "provenance": provenance,
                "confidence": confidence,
                "source_citation": source_citation,
                "pii_tier": pii_tier,
                "attributes": dict(attributes) if attributes else {},
            }
        )
        return event_id

    async def query_temporal(self, *args: Any, **kwargs: Any) -> Any:
        return ()


def _pending(
    *,
    approval_id: str = "apex-1",
    change_id: str = "add-dark-mode",
    proposing_domain: str = TEKTOS_UI_PROPOSING_DOMAIN,
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=approval_id,
        intention_id=f"tektos.plan.{change_id}",
        proposing_domain=proposing_domain,
        tier=ChangeApprovalTier.HUMAN_REVIEW,
        delta={"summary": "swap theme"},
        status=ApprovalStatus.PENDING,
        proposed_at=datetime.now(timezone.utc),
    )


def _client(*, resolver: _FakeResolver, memory: _FakeMemory) -> TestClient:
    app = build_tektos_ui_app(
        approval_resolver=resolver,
        memory=memory,
        executor=NopExecutor(),
    )
    return TestClient(app)


# ── Port/Protocol conformance ───────────────────────────────────────────


def test_fake_resolver_implements_approval_resolver_port() -> None:
    """``ApprovalResolverPort`` is runtime-checkable (ADR-045)."""
    assert isinstance(_FakeResolver(), ApprovalResolverPort)


def test_nop_executor_implements_executor_port() -> None:
    assert isinstance(NopExecutor(), ExecutorPort)


def test_confidence_for_ui_event_bounds() -> None:
    assert confidence_for_ui_event(success=True) == TEKTOS_UI_SUCCESS_CONFIDENCE
    assert confidence_for_ui_event(success=False) == 0.0


def test_confidence_for_ui_event_rejects_non_bool() -> None:
    with pytest.raises(TypeError):
        confidence_for_ui_event(success=1)  # type: ignore[arg-type]


# ── Diff helpers ────────────────────────────────────────────────────────


def test_render_unified_diff_deterministic() -> None:
    d1 = render_unified_diff(before="a\n", after="b\n")
    d2 = render_unified_diff(before="a\n", after="b\n")
    assert d1 == d2
    assert compute_diff_sha256(d1) == compute_diff_sha256(d2)


def test_render_unified_diff_empty_when_identical() -> None:
    assert render_unified_diff(before="x\n", after="x\n") == ""


@pytest.mark.asyncio
async def test_nop_executor_returns_stable_snapshot() -> None:
    r1 = await NopExecutor().execute(approval_id="a", change_id="c")
    r2 = await NopExecutor().execute(approval_id="a", change_id="c")
    assert isinstance(r1, ExecutionResult)
    assert r1.approval_id == "a"
    assert r1.change_id == "c"
    assert r1.diff_sha256 == r2.diff_sha256


@pytest.mark.asyncio
async def test_nop_executor_rejects_empty_args() -> None:
    with pytest.raises(ValueError):
        await NopExecutor().execute(approval_id="", change_id="c")
    with pytest.raises(ValueError):
        await NopExecutor().execute(approval_id="a", change_id="")


# ── PraxisApprovalResolverAdapter ───────────────────────────────────────


@pytest.mark.asyncio
async def test_praxis_adapter_filters_by_proposing_domain() -> None:
    """Q_res_1=B: adapter applies port-level ``proposing_domain`` filter."""

    class _EngineStub:
        def __init__(self, records: tuple[ApprovalRecord, ...]) -> None:
            self._records = records

        async def list_pending(self) -> tuple[ApprovalRecord, ...]:
            return self._records

        async def resolve(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def get_by_id(self, approval_id: str) -> Any:
            raise NotImplementedError

    tektos_a = _pending(approval_id="t-1", proposing_domain="tektos")
    tektos_b = _pending(approval_id="t-2", proposing_domain="tektos")
    other = _pending(approval_id="o-1", proposing_domain="forge_oh")
    adapter = PraxisApprovalResolverAdapter(_EngineStub((tektos_a, tektos_b, other)))
    all_pending = await adapter.list_pending()
    assert len(all_pending) == 3
    only_tektos = await adapter.list_pending(proposing_domain="tektos")
    assert {r.approval_id for r in only_tektos} == {"t-1", "t-2"}
    only_forge = await adapter.list_pending(proposing_domain="forge_oh")
    assert {r.approval_id for r in only_forge} == {"o-1"}


# ── Route contract ──────────────────────────────────────────────────────


def test_index_returns_dashboard_shell_with_htmx_script_tag() -> None:
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.get(TEKTOS_UI_INDEX_PATH)
    assert response.status_code == 200
    assert TEKTOS_UI_HTMX_JS_TEMPLATE_HREF in response.text
    assert "apex-1" in response.text
    assert "add-dark-mode" in response.text


def test_index_shows_only_tektos_proposed_approvals() -> None:
    """Q_res_1=B: server passes ``proposing_domain="tektos"``."""
    resolver = _FakeResolver()
    resolver.seed(_pending(approval_id="tektos-1", proposing_domain="tektos"))
    resolver.seed(_pending(approval_id="other-1", proposing_domain="forge_oh"))
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.get(TEKTOS_UI_INDEX_PATH)
    assert "tektos-1" in response.text
    assert "other-1" not in response.text


def test_plan_detail_route_renders_fragment() -> None:
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.get(TEKTOS_UI_PLAN_DETAIL_PATH.format(approval_id="apex-1"))
    assert response.status_code == 200
    assert "apex-1" in response.text
    assert "add-dark-mode" in response.text


def test_plan_detail_404_on_unknown_id() -> None:
    resolver = _FakeResolver()
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.get(TEKTOS_UI_PLAN_DETAIL_PATH.format(approval_id="nope"))
    assert response.status_code == 404


def test_healthz_returns_ok() -> None:
    resolver = _FakeResolver()
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.get(TEKTOS_UI_HEALTHZ_PATH)
    assert response.status_code == 200
    assert response.text == "ok"


def test_htmx_route_serves_vendored_bytes() -> None:
    """Q1b=A + Q1f=A: vendored htmx served via route, not static dir."""
    resolver = _FakeResolver()
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.get(TEKTOS_UI_HTMX_JS_PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    digest = hashlib.sha256(response.content).hexdigest()
    assert digest == TEKTOS_UI_HTMX_SHA256
    assert response.headers["cache-control"].startswith("public")


def test_vendored_htmx_file_matches_policy_sha256() -> None:
    """Vendored bytes on disk match the locked ADR-045 hash."""
    here = Path(__file__).resolve().parent.parent / "ui" / "htmx.min.js"
    digest = hashlib.sha256(here.read_bytes()).hexdigest()
    assert digest == TEKTOS_UI_HTMX_SHA256
    assert TEKTOS_UI_HTMX_VERSION == "2.0.4"
    assert TEKTOS_UI_HTMX_UPSTREAM_COMMIT == (
        "b82cf843e47e575dd8c2ad8fee547d8e2c3bb87f"
    )
    assert TEKTOS_UI_HTMX_UPSTREAM_LICENSE == "0BSD"


# ── MemoryPort event contract (Q5=A) ────────────────────────────────────


def test_approve_writes_plan_approved_memory_event() -> None:
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.post(TEKTOS_UI_PLAN_APPROVE_PATH.format(approval_id="apex-1"))
    assert response.status_code == 200
    assert len(memory.writes) == 1
    w = memory.writes[0]
    assert w["predicate"] == TEKTOS_UI_PLAN_APPROVED_PREDICATE
    assert w["provenance"] == TEKTOS_UI_PROVENANCE
    assert w["confidence"] == TEKTOS_UI_SUCCESS_CONFIDENCE
    assert w["subject"] == "add-dark-mode::apex-1"
    attrs = w["attributes"]
    assert attrs["approval_id"] == "apex-1"
    assert attrs["change_id"] == "add-dark-mode"
    assert attrs["resolved_by"] == TEKTOS_UI_RESOLVED_BY == "tektos_ui"
    assert attrs["resolved_at"].endswith("Z")


def test_approve_stamps_resolved_by_tektos_ui_on_record() -> None:
    """Q_res_2=B: UI approvals set ``resolved_by="tektos_ui"``."""
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        client.post(TEKTOS_UI_PLAN_APPROVE_PATH.format(approval_id="apex-1"))
    updated = resolver._records["apex-1"]
    assert updated.status is ApprovalStatus.APPROVED
    assert updated.resolved_by == TEKTOS_UI_RESOLVED_BY == "tektos_ui"


def test_execute_writes_plan_executed_memory_event() -> None:
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.post(TEKTOS_UI_PLAN_EXECUTE_PATH.format(approval_id="apex-1"))
    assert response.status_code == 200
    assert len(memory.writes) == 1
    w = memory.writes[0]
    assert w["predicate"] == TEKTOS_UI_PLAN_EXECUTED_PREDICATE
    assert w["provenance"] == TEKTOS_UI_PROVENANCE
    assert w["confidence"] == TEKTOS_UI_SUCCESS_CONFIDENCE
    attrs = w["attributes"]
    assert attrs["approval_id"] == "apex-1"
    assert attrs["change_id"] == "add-dark-mode"
    assert len(attrs["diff_sha256"]) == 64  # sha256 hex
    assert attrs["executed_at"].endswith("Z")


def test_diff_writes_plan_diff_rendered_memory_event() -> None:
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        response = client.get(TEKTOS_UI_PLAN_DIFF_PATH.format(approval_id="apex-1"))
    assert response.status_code == 200
    assert len(memory.writes) == 1
    w = memory.writes[0]
    assert w["predicate"] == TEKTOS_UI_PLAN_DIFF_RENDERED_PREDICATE
    assert w["provenance"] == TEKTOS_UI_PROVENANCE
    attrs = w["attributes"]
    assert attrs["approval_id"] == "apex-1"
    assert attrs["change_id"] == "add-dark-mode"
    assert len(attrs["diff_sha256"]) == 64
    assert attrs["rendered_at"].endswith("Z")


def test_execute_and_diff_produce_matching_diff_sha256() -> None:
    """Q5=A: Execute and Diff legs correlate by ``diff_sha256``."""
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        client.post(TEKTOS_UI_PLAN_EXECUTE_PATH.format(approval_id="apex-1"))
        client.get(TEKTOS_UI_PLAN_DIFF_PATH.format(approval_id="apex-1"))
    assert (
        memory.writes[0]["attributes"]["diff_sha256"]
        == memory.writes[1]["attributes"]["diff_sha256"]
    )


# ── ADR-041 STATUS AMENDMENT (Route added → COMPLIANT) ──────────────────


def test_tektos_descriptor_now_carries_ui_route_adr_045() -> None:
    """ADR-045: Stage 3.11 adds one Route so parity flips to COMPLIANT.

    Stage 14.11 (GUI surfacing) adds a second Route (/tektos-ultima), so the
    descriptor now carries 2 routes — the ADR-045 route stays routes[0]."""
    d = build_tektos_descriptor()
    assert len(d.routes) == 2
    assert d.routes[0].path == "/tektos"
    assert d.routes[0].label == "Tektos"
    assert d.routes[0].lazy_module == "tektos/pages/DashboardPage"
    assert d.routes[1].path == "/tektos-ultima"
    assert d.routes[1].label == "Tektos-Ultima"


# ── ADR-007 AST guard ───────────────────────────────────────────────────


_UI_PKG_DIR = Path(__file__).resolve().parent.parent / "ui"


def test_tektos_ui_imports_no_other_plugins_adr_007() -> None:
    """ADR-007: no plugin may import another plugin's package directly.

    Statically walk every ``.py`` file under ``plugins/tektos/ui/`` and
    reject any ``import plugins.<other>`` that is not ``plugins.tektos``
    itself.
    """
    offenders: list[tuple[str, str]] = []
    for py_path in _UI_PKG_DIR.rglob("*.py"):
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    if mod.startswith("plugins.") and not mod.startswith(
                        "plugins.tektos"
                    ):
                        offenders.append((str(py_path), mod))
                continue
            else:
                continue
            if mod.startswith("plugins.") and not mod.startswith("plugins.tektos"):
                offenders.append((str(py_path), mod))
    assert offenders == [], f"ADR-007 violation(s): {offenders}"


# ── DoD literal end-to-end (Q10=A) ──────────────────────────────────────


def test_plan_approve_execute_diff_flow_visible_in_kernel_dashboard_build_sequence_3_11_dod() -> None:
    """Stage 3.11 DoD literal (ADR-045 §Q10=A).

    "Plan \u2192 Approve \u2192 Execute \u2192 Diff flow visible in
    kernel dashboard."

    Renaming this test requires an ADR-045 amendment.
    """
    resolver = _FakeResolver()
    resolver.seed(_pending())
    memory = _FakeMemory()
    with _client(resolver=resolver, memory=memory) as client:
        # Plan leg: dashboard shows the pending Tektos plan.
        index = client.get(TEKTOS_UI_INDEX_PATH)
        assert index.status_code == 200
        assert "apex-1" in index.text
        assert "add-dark-mode" in index.text
        assert TEKTOS_UI_HTMX_JS_TEMPLATE_HREF in index.text
        # Approve leg.
        approve = client.post(
            TEKTOS_UI_PLAN_APPROVE_PATH.format(approval_id="apex-1")
        )
        assert approve.status_code == 200
        # Execute leg.
        execute = client.post(
            TEKTOS_UI_PLAN_EXECUTE_PATH.format(approval_id="apex-1")
        )
        assert execute.status_code == 200
        # Diff leg.
        diff = client.get(TEKTOS_UI_PLAN_DIFF_PATH.format(approval_id="apex-1"))
        assert diff.status_code == 200
        assert "sha256" in diff.text
    predicates = [w["predicate"] for w in memory.writes]
    assert predicates == [
        TEKTOS_UI_PLAN_APPROVED_PREDICATE,
        TEKTOS_UI_PLAN_EXECUTED_PREDICATE,
        TEKTOS_UI_PLAN_DIFF_RENDERED_PREDICATE,
    ]
    for w in memory.writes:
        assert w["provenance"] == TEKTOS_UI_PROVENANCE
        assert w["confidence"] == TEKTOS_UI_SUCCESS_CONFIDENCE
    # Execute + Diff share a diff_sha256.
    assert (
        memory.writes[1]["attributes"]["diff_sha256"]
        == memory.writes[2]["attributes"]["diff_sha256"]
    )
    # Record final status.
    final = resolver._records["apex-1"]
    assert final.status is ApprovalStatus.APPROVED
    assert final.resolved_by == TEKTOS_UI_RESOLVED_BY == "tektos_ui"


# ── Env-gated interactive tier (Q7=B) ───────────────────────────────────


_INTERACTIVE_ENV_VAR = "KOSMOS_STAGE_311_INTERACTIVE"


@pytest.mark.skipif(
    os.environ.get(_INTERACTIVE_ENV_VAR) != "1",
    reason=(
        "Interactive tier is Colossus-only. "
        f"Set {_INTERACTIVE_ENV_VAR}=1 to run."
    ),
)
def test_interactive_tier_uvicorn_boots_on_127_0_0_1_8765() -> None:
    """Boot real uvicorn against ``127.0.0.1:8765`` and hit ``/healthz``.

    The runner script ``scripts/tektos_ui.py`` owns the real wiring;
    this test only asserts the port binds and ``/healthz`` responds.
    """
    proc = subprocess.Popen(
        [sys.executable, "scripts/tektos_ui.py"],
        cwd=Path(__file__).resolve().parents[3],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 15.0
        last_exc: Exception | None = None
        while time.time() < deadline:
            try:
                r = httpx.get("http://127.0.0.1:8765/healthz", timeout=1.0)
                if r.status_code == 200 and r.text == "ok":
                    break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.25)
        else:  # pragma: no cover - only reached on interactive fail
            raise AssertionError(
                f"tektos_ui.py did not respond on 127.0.0.1:8765 "
                f"within 15s (last error: {last_exc})"
            )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
