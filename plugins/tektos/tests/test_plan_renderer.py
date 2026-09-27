"""Stage 3.7 Tektos plan renderer + plugin bootstrap contract tests (ADR-041).

Coverage:

* Policy locked constants (ADR-041 §Q1=B, Q3=A APPROVALS_QUEUE, Q4=A
  HUMAN_REVIEW, Q6=A predicate).
* Confidence clamping bounds + non-finite rejection.
* Delta aggregation across every ``specs/<domain>/spec.md``.
* ``project_plan_to_card`` pure-function correctness + input validation.
* ``render_and_gate_plan_card`` order-of-operations: propose → project →
  MemoryPort write.
* Fail-closed HUMAN_REVIEW tier is passed to ApprovalGatewayPort.
* MemoryPort write-event zero-trust guard passthrough.
* TektosPlugin descriptor shape (name, panel slot, priority, lazy_module).
* TektosPlugin start/stop idempotency + FrontendContractPort registration.
* ADR-007 AST guard — renderer + plugin import only ``ports.*`` and own
  plugin subpackages.
* End-to-end DoD literal on the Stage 3.6 ``add-dark-mode`` fixture.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ports.approval import ApprovalGatewayPort, ChangeApprovalTier
from ports.frontend_contract import (
    FrontendContractPort,
    Panel,
    PanelSlot,
    PluginDescriptor,
    PluginRegistration,
    Route,
    UiParityStatus,
)
from plugins.tektos.ui.policy import (
    TEKTOS_UI_ROUTE_ICON,
    TEKTOS_UI_ROUTE_LABEL,
    TEKTOS_UI_ROUTE_LAZY_MODULE,
    TEKTOS_UI_ROUTE_PATH,
)
from ports.memory import (
    MemoryEventId,
    MemoryHit,
    MemoryPort,
    validate_zero_trust_write,
)

from plugins.tektos import renderer as tektos_renderer
from plugins.tektos.openspec import Plan, produce_plan
from plugins.tektos.openspec.models import Artifact, ArtifactKind
from plugins.tektos.plugin import (
    TEKTOS_KERNEL_COMPAT,
    TEKTOS_PLAN_APPROVAL_LAZY_MODULE,
    TEKTOS_PLAN_APPROVAL_PANEL_ID,
    TEKTOS_PLAN_APPROVAL_PANEL_PRIORITY,
    TEKTOS_PLUGIN_NAME,
    TEKTOS_STATE_NAMESPACE,
    TEKTOS_VERSION,
    TektosPlugin,
    build_tektos_descriptor,
)
from plugins.tektos.renderer.models import PlanCard
from plugins.tektos.renderer.policy import (
    TEKTOS_PLAN_APPROVAL_TIER,
    TEKTOS_PLAN_CARD_MIN_CONFIDENCE,
    TEKTOS_PLAN_CARD_PREDICATE,
    TEKTOS_PLAN_PROPOSING_DOMAIN,
    TEKTOS_PLAN_RENDERER_PROVENANCE,
    clamp_card_confidence,
)
from plugins.tektos.renderer.project import (
    project_plan_to_card,
    render_and_gate_plan_card,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeMemoryPort:
    """MemoryPort test double.

    Records every :meth:`write_event` call verbatim and enforces the
    port-level zero-trust guard on every write (matches the Stage 3.6
    openspec test fake).
    """

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
        validate_zero_trust_write(
            provenance=provenance,
            confidence=confidence,
        )
        self._counter += 1
        record = {
            "subject": subject,
            "predicate": predicate,
            "object": object,
            "provenance": provenance,
            "confidence": confidence,
            "source_citation": source_citation,
            "pii_tier": pii_tier,
            "attributes": dict(attributes or {}),
        }
        self.writes.append(record)
        return MemoryEventId(
            id=f"mem-{self._counter}",
            written_at=datetime.now(timezone.utc),
        )

    async def query_temporal(
        self,
        cypher_or_query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        return []

    async def link_entities(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict[str, Any] | None = None,
    ) -> MemoryEventId:
        return MemoryEventId(
            id="mem-link", written_at=datetime.now(timezone.utc)
        )


class _FakeApprovalGatewayPort:
    """ApprovalGatewayPort test double.

    Records every :meth:`propose` call and returns a synthetic
    ``approval_id``.
    """

    def __init__(self, next_id: str = "apex-1") -> None:
        self.calls: list[dict[str, Any]] = []
        self._next_id = next_id

    async def propose(
        self,
        intention_id: str,
        delta,
        tier: ChangeApprovalTier,
        *,
        proposing_domain: str,
        diff_preview=None,
    ) -> str:
        self.calls.append(
            {
                "intention_id": intention_id,
                "delta": dict(delta),
                "tier": tier,
                "proposing_domain": proposing_domain,
                "diff_preview": dict(diff_preview or {}),
            }
        )
        return self._next_id


class _RejectingMemoryPort:
    """MemoryPort double that always rejects writes at the zero-trust guard.

    Used to assert ``render_and_gate_plan_card`` never bypasses the port
    layer (ADR-008).
    """

    async def write_event(self, *args, **kwargs) -> MemoryEventId:
        raise ValueError("rejecting memory port: zero-trust write refused")

    async def query_temporal(self, *args, **kwargs) -> list[MemoryHit]:
        return []

    async def link_entities(self, *args, **kwargs) -> MemoryEventId:
        return MemoryEventId(
            id="mem-link", written_at=datetime.now(timezone.utc)
        )


class _FakeFrontendContract:
    """FrontendContractPort test double.

    Records descriptors and returns synthetic
    :class:`PluginRegistration` objects. ``unregister_plugin`` returns
    True when a matching name was registered.
    """

    def __init__(
        self,
        ui_parity_status: UiParityStatus | None = None,
    ) -> None:
        self.registrations: list[PluginDescriptor] = []
        self.unregistered: list[str] = []
        self._ui_parity_override = ui_parity_status

    @staticmethod
    def _derive_parity(descriptor: PluginDescriptor) -> UiParityStatus:
        """Mirror ``adapters/frontend_contract/kernel/adapter.py::_derive_parity``.

        ADR-031: parity is COMPLIANT only when the descriptor carries
        both routes and panels.
        """
        if descriptor.routes and descriptor.panels:
            return UiParityStatus.COMPLIANT
        return UiParityStatus.IN_PROGRESS

    async def register_plugin(
        self, descriptor: PluginDescriptor
    ) -> PluginRegistration:
        self.registrations.append(descriptor)
        parity = (
            self._ui_parity_override
            if self._ui_parity_override is not None
            else self._derive_parity(descriptor)
        )
        return PluginRegistration(
            descriptor=descriptor,
            registered_at=datetime.now(timezone.utc),
            ui_parity_status=parity,
        )

    async def unregister_plugin(self, name: str) -> bool:
        was_registered = any(d.name == name for d in self.registrations)
        if was_registered:
            self.unregistered.append(name)
        return was_registered


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


ADD_DARK_MODE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "openspec" / "add-dark-mode"
).resolve()


def _make_artifact(
    kind: ArtifactKind,
    relative_path: str,
    completeness: float,
) -> Artifact:
    return Artifact(
        kind=kind,
        relative_path=relative_path,
        byte_count=0,
        section_headers=(),
        non_empty_section_count=0,
        completeness_confidence=completeness,
    )


def _synthetic_plan(
    *,
    change_id: str = "synthetic-change",
    rendered_summary: str = "synthetic",
    task_count: int = 3,
    done_task_count: int = 1,
    delta_added: int = 2,
    delta_modified: int = 1,
    delta_removed: int = 0,
    mean_completeness: float = 0.75,
) -> Plan:
    """Minimal synthetic ``Plan`` for pure-function tests."""
    proposal = _make_artifact(
        ArtifactKind.PROPOSAL, "proposal.md", mean_completeness
    )
    # Fabricate delta_specs to satisfy the delta counts.
    from plugins.tektos.openspec.models import DeltaSpec, Requirement

    def _req(heading: str) -> Requirement:
        return Requirement(
            heading=heading,
            body_lines=(),
            scenario_count=0,
            has_normative_keyword=False,
        )

    added = tuple(_req(f"a{i}") for i in range(delta_added))
    modified = tuple(_req(f"m{i}") for i in range(delta_modified))
    removed = tuple(_req(f"r{i}") for i in range(delta_removed))
    delta_specs: tuple[DeltaSpec, ...] = ()
    if added or modified or removed:
        delta_specs = (
            DeltaSpec(
                domain="ui",
                artifact=_make_artifact(
                    ArtifactKind.DELTA_SPEC,
                    "specs/ui/spec.md",
                    mean_completeness,
                ),
                added=added,
                modified=modified,
                removed=removed,
            ),
        )

    # Fabricate tasks.
    from plugins.tektos.openspec.models import TaskItem

    tasks = tuple(
        TaskItem(text=f"task-{i}", done=(i < done_task_count))
        for i in range(task_count)
    )

    return Plan(
        change_id=change_id,
        change_dir="/tmp/synthetic",
        proposal=proposal,
        design=None,
        tasks_artifact=None,
        tasks=tasks,
        delta_specs=delta_specs,
        artifact_count=1 + len(delta_specs),
        mean_completeness=mean_completeness,
        rendered_summary=rendered_summary,
    )


# ---------------------------------------------------------------------------
# ADR-041 Q1=B locked constants + Q3/Q4/Q6
# ---------------------------------------------------------------------------


def test_locked_constants_match_adr_041_q3_q4_q6() -> None:
    assert TEKTOS_PLAN_RENDERER_PROVENANCE == "tektos_plan_renderer"
    assert TEKTOS_PLAN_CARD_PREDICATE == "tektos.plan.card_rendered"
    assert TEKTOS_PLAN_PROPOSING_DOMAIN == "tektos"
    assert TEKTOS_PLAN_APPROVAL_TIER is ChangeApprovalTier.HUMAN_REVIEW
    assert TEKTOS_PLAN_CARD_MIN_CONFIDENCE == 0.05


def test_public_surface_matches_adr_041_q2_no_new_port() -> None:
    """ADR-041 Q2=A: no new port surface. The renderer must expose
    only PlanCard + two functions + locked constants."""
    exported = set(tektos_renderer.__all__)
    assert "PlanCard" in exported
    assert "project_plan_to_card" in exported
    assert "render_and_gate_plan_card" in exported
    # Locked policy re-exports:
    assert "TEKTOS_PLAN_APPROVAL_TIER" in exported
    assert "TEKTOS_PLAN_CARD_PREDICATE" in exported


# ---------------------------------------------------------------------------
# clamp_card_confidence
# ---------------------------------------------------------------------------


def test_clamp_card_confidence_clamps_below_min() -> None:
    assert clamp_card_confidence(-1.0) == TEKTOS_PLAN_CARD_MIN_CONFIDENCE
    assert clamp_card_confidence(0.0) == TEKTOS_PLAN_CARD_MIN_CONFIDENCE
    assert clamp_card_confidence(0.049) == TEKTOS_PLAN_CARD_MIN_CONFIDENCE


def test_clamp_card_confidence_clamps_above_one() -> None:
    assert clamp_card_confidence(1.0) == 1.0
    assert clamp_card_confidence(1.5) == 1.0
    assert clamp_card_confidence(1e6) == 1.0


def test_clamp_card_confidence_passthrough_in_range() -> None:
    assert clamp_card_confidence(0.5) == 0.5
    assert clamp_card_confidence(0.75) == 0.75


def test_clamp_card_confidence_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        clamp_card_confidence(float("nan"))
    with pytest.raises(ValueError):
        clamp_card_confidence(float("inf"))
    with pytest.raises(ValueError):
        clamp_card_confidence(float("-inf"))


def test_clamp_card_confidence_rejects_non_numeric() -> None:
    with pytest.raises(TypeError):
        clamp_card_confidence("0.5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# project_plan_to_card
# ---------------------------------------------------------------------------


def test_project_plan_to_card_aggregates_deltas_from_all_specs() -> None:
    """When multiple delta_specs contribute added/modified/removed, the
    card sums across all of them."""
    from plugins.tektos.openspec.models import DeltaSpec, Requirement

    def _req(heading: str) -> Requirement:
        return Requirement(
            heading=heading,
            body_lines=(),
            scenario_count=0,
            has_normative_keyword=False,
        )

    plan = _synthetic_plan(
        delta_added=1, delta_modified=1, delta_removed=1
    )
    # Add a second delta_spec directly (bypass helper's single-spec shortcut).
    proposal_artifact = plan.proposal
    from dataclasses import replace as _replace

    second_spec = DeltaSpec(
        domain="auth",
        artifact=_make_artifact(
            ArtifactKind.DELTA_SPEC, "specs/auth/spec.md", 0.5
        ),
        added=(_req("x"), _req("y")),  # +2 added
        modified=(),
        removed=(_req("z"),),  # +1 removed
    )
    plan = _replace(
        plan,
        delta_specs=plan.delta_specs + (second_spec,),
    )

    card = project_plan_to_card(
        plan,
        panel_id="tektos.plan_approvals",
        approval_id="apex-1",
        tier=ChangeApprovalTier.HUMAN_REVIEW,
    )
    assert card.delta_added == 1 + 2
    assert card.delta_modified == 1 + 0
    assert card.delta_removed == 1 + 1


def test_project_plan_to_card_confidence_is_clamped() -> None:
    plan = _synthetic_plan(mean_completeness=0.0)
    card = project_plan_to_card(
        plan,
        panel_id="tektos.plan_approvals",
        approval_id="apex-1",
        tier=ChangeApprovalTier.HUMAN_REVIEW,
    )
    assert card.confidence == TEKTOS_PLAN_CARD_MIN_CONFIDENCE


def test_project_plan_to_card_tier_round_trips_as_string() -> None:
    plan = _synthetic_plan()
    card = project_plan_to_card(
        plan,
        panel_id="p",
        approval_id="a",
        tier=ChangeApprovalTier.AUTONOMOUS,
    )
    assert card.tier == "AUTONOMOUS"
    # to_delta must be JSON-shaped with the string tier.
    delta = card.to_delta()
    assert delta["tier"] == "AUTONOMOUS"
    assert delta["change_id"] == plan.change_id


def test_project_plan_to_card_rejects_non_plan_input() -> None:
    with pytest.raises(TypeError):
        project_plan_to_card(
            "not a plan",  # type: ignore[arg-type]
            panel_id="p",
            approval_id="a",
            tier=ChangeApprovalTier.HUMAN_REVIEW,
        )


def test_project_plan_to_card_rejects_empty_panel_id() -> None:
    plan = _synthetic_plan()
    with pytest.raises(ValueError):
        project_plan_to_card(
            plan,
            panel_id="",
            approval_id="a",
            tier=ChangeApprovalTier.HUMAN_REVIEW,
        )


def test_project_plan_to_card_rejects_empty_approval_id() -> None:
    plan = _synthetic_plan()
    with pytest.raises(ValueError):
        project_plan_to_card(
            plan,
            panel_id="p",
            approval_id="",
            tier=ChangeApprovalTier.HUMAN_REVIEW,
        )


def test_project_plan_to_card_rejects_non_tier_input() -> None:
    plan = _synthetic_plan()
    with pytest.raises(TypeError):
        project_plan_to_card(
            plan,
            panel_id="p",
            approval_id="a",
            tier="HUMAN_REVIEW",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# render_and_gate_plan_card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_and_gate_plan_card_uses_human_review_tier_fail_closed() -> None:
    """ADR-041 §Q4=A: every card MUST propose at HUMAN_REVIEW."""
    plan = _synthetic_plan()
    approval = _FakeApprovalGatewayPort(next_id="apex-42")
    memory = _FakeMemoryPort()

    card = await render_and_gate_plan_card(
        plan,
        panel_id="tektos.plan_approvals",
        approval=approval,
        memory=memory,
    )
    assert len(approval.calls) == 1
    assert approval.calls[0]["tier"] is ChangeApprovalTier.HUMAN_REVIEW
    assert approval.calls[0]["proposing_domain"] == TEKTOS_PLAN_PROPOSING_DOMAIN
    assert card.tier == "HUMAN_REVIEW"
    assert card.approval_id == "apex-42"


@pytest.mark.asyncio
async def test_render_and_gate_plan_card_writes_memory_event_with_locked_provenance() -> None:
    plan = _synthetic_plan(change_id="add-x", mean_completeness=0.6)
    approval = _FakeApprovalGatewayPort(next_id="apex-100")
    memory = _FakeMemoryPort()

    await render_and_gate_plan_card(
        plan,
        panel_id="tektos.plan_approvals",
        approval=approval,
        memory=memory,
    )
    assert len(memory.writes) == 1
    w = memory.writes[0]
    assert w["provenance"] == TEKTOS_PLAN_RENDERER_PROVENANCE
    assert w["predicate"] == TEKTOS_PLAN_CARD_PREDICATE
    assert w["subject"] == "add-x::tektos.plan_approvals"
    assert w["confidence"] == 0.6
    assert w["attributes"]["approval_id"] == "apex-100"
    assert w["attributes"]["tier"] == "HUMAN_REVIEW"
    assert w["attributes"]["panel_id"] == "tektos.plan_approvals"


@pytest.mark.asyncio
async def test_render_and_gate_plan_card_intention_id_is_deterministic() -> None:
    """Same change_id → same intention_id (correlates retries)."""
    plan = _synthetic_plan(change_id="add-y")
    approval = _FakeApprovalGatewayPort()
    memory = _FakeMemoryPort()

    await render_and_gate_plan_card(
        plan, panel_id="p", approval=approval, memory=memory
    )
    assert approval.calls[0]["intention_id"] == "tektos.plan.add-y"


@pytest.mark.asyncio
async def test_render_and_gate_plan_card_never_bypasses_memory_port_zero_trust_guard() -> None:
    """ADR-008: if MemoryPort rejects, exception propagates."""
    plan = _synthetic_plan()
    approval = _FakeApprovalGatewayPort()
    memory = _RejectingMemoryPort()

    with pytest.raises(ValueError, match="rejecting memory port"):
        await render_and_gate_plan_card(
            plan,
            panel_id="p",
            approval=approval,  # type: ignore[arg-type]
            memory=memory,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_render_and_gate_plan_card_rejects_empty_approval_id() -> None:
    plan = _synthetic_plan()
    approval = _FakeApprovalGatewayPort(next_id="")
    memory = _FakeMemoryPort()
    with pytest.raises(ValueError, match="non-string/empty approval_id"):
        await render_and_gate_plan_card(
            plan, panel_id="p", approval=approval, memory=memory
        )


@pytest.mark.asyncio
async def test_render_and_gate_plan_card_rejects_non_plan_input() -> None:
    approval = _FakeApprovalGatewayPort()
    memory = _FakeMemoryPort()
    with pytest.raises(TypeError):
        await render_and_gate_plan_card(
            "not a plan",  # type: ignore[arg-type]
            panel_id="p",
            approval=approval,
            memory=memory,
        )


# ---------------------------------------------------------------------------
# TektosPlugin descriptor + start/stop
# ---------------------------------------------------------------------------


def test_build_tektos_descriptor_shape_matches_adr_041() -> None:
    d = build_tektos_descriptor()
    assert isinstance(d, PluginDescriptor)
    assert d.name == TEKTOS_PLUGIN_NAME == "tektos"
    assert d.state_namespace == TEKTOS_STATE_NAMESPACE == "tektos"
    assert d.version == TEKTOS_VERSION == "0.1.0"
    assert d.kernel_compat == TEKTOS_KERNEL_COMPAT == "0.1.x"
    # ADR-045: Stage 3.11 adds one Route so `_derive_parity`
    # returns COMPLIANT (routes AND panels populated).
    # Stage 14.11 (GUI surfacing) adds a second Route (/tektos-ultima)
    # for the absorbed native page tree — the descriptor now carries 2.
    assert len(d.routes) == 2
    r = d.routes[0]
    assert isinstance(r, Route)
    assert r.path == TEKTOS_UI_ROUTE_PATH == "/tektos"
    assert r.label == TEKTOS_UI_ROUTE_LABEL == "Tektos"
    r2 = d.routes[1]
    assert r2.path == "/tektos-ultima"
    assert r2.label == "Tektos-Ultima"
    assert r.icon == TEKTOS_UI_ROUTE_ICON
    assert r.lazy_module == TEKTOS_UI_ROUTE_LAZY_MODULE == "tektos/pages/DashboardPage"
    assert d.design_tokens == {}
    assert len(d.panels) == 1
    p = d.panels[0]
    assert isinstance(p, Panel)
    assert p.id == TEKTOS_PLAN_APPROVAL_PANEL_ID == "tektos.plan_approvals"
    assert p.slot is PanelSlot.APPROVALS_QUEUE
    assert p.priority == TEKTOS_PLAN_APPROVAL_PANEL_PRIORITY == 90
    assert p.lazy_module == TEKTOS_PLAN_APPROVAL_LAZY_MODULE
    assert p.plugin_name == "tektos"


def test_tektos_panel_priority_below_praxis_approvals_panel() -> None:
    """ADR-033 §Q1=C: Praxis approvals panel is priority 100. Tektos must
    render BELOW it in the same slot (ADR-031 priority-DESC ordering)."""
    from plugins.praxis.plugin import PRAXIS_APPROVALS_PANEL_PRIORITY

    tektos_priority = build_tektos_descriptor().panels[0].priority
    assert tektos_priority < PRAXIS_APPROVALS_PANEL_PRIORITY


@pytest.mark.asyncio
async def test_tektos_plugin_start_registers_descriptor() -> None:
    fc = _FakeFrontendContract()
    plugin = TektosPlugin(frontend_contract_port=fc)
    assert plugin.is_started is False
    assert plugin.registration is None

    await plugin.start()
    assert plugin.is_started is True
    assert plugin.registration is not None
    assert plugin.registration.descriptor.name == "tektos"
    # ADR-045 (Stage 3.11): Route + Panel → COMPLIANT via
    # `adapters/frontend_contract/kernel/adapter.py::_derive_parity`.
    assert plugin.registration.ui_parity_status is UiParityStatus.COMPLIANT
    assert len(fc.registrations) == 1


@pytest.mark.asyncio
async def test_tektos_plugin_start_is_idempotent() -> None:
    fc = _FakeFrontendContract()
    plugin = TektosPlugin(frontend_contract_port=fc)
    await plugin.start()
    await plugin.start()
    assert len(fc.registrations) == 1


@pytest.mark.asyncio
async def test_tektos_plugin_stop_deregisters_and_is_idempotent() -> None:
    fc = _FakeFrontendContract()
    plugin = TektosPlugin(frontend_contract_port=fc)
    await plugin.stop()  # never started; no-op
    assert fc.unregistered == []
    await plugin.start()
    await plugin.stop()
    assert fc.unregistered == ["tektos"]
    assert plugin.is_started is False
    assert plugin.registration is None
    await plugin.stop()  # second stop
    assert fc.unregistered == ["tektos"]  # unchanged


# ---------------------------------------------------------------------------
# ADR-007: no-cross-plugin-import guard
# ---------------------------------------------------------------------------


def _renderer_and_plugin_modules() -> list[str]:
    """Every module under plugins/tektos/renderer + the plugin bootstrap."""
    root = Path(__file__).parent.parent  # plugins/tektos
    files: list[Path] = list((root / "renderer").rglob("*.py"))
    files.append(root / "plugin.py")
    return [str(f) for f in files]


def _module_imports_other_plugins(source: str) -> list[str]:
    """Return sorted list of ``plugins.<other>`` imports (excluding
    ``plugins.tektos.*``)."""
    tree = ast.parse(source)
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(
                    "plugins."
                ) and not alias.name.startswith("plugins.tektos"):
                    hits.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("plugins.") and not mod.startswith(
                "plugins.tektos"
            ):
                hits.add(mod)
    return sorted(hits)


def test_renderer_and_plugin_import_no_other_plugins_adr_007() -> None:
    """ADR-007: Tektos renderer + plugin bootstrap must not import any
    other plugin's package. Imports allowed: ``ports.*``,
    ``plugins.tektos.*``, standard library, and third-party (none needed)."""
    offenders: dict[str, list[str]] = {}
    for path in _renderer_and_plugin_modules():
        source = Path(path).read_text(encoding="utf-8")
        bad = _module_imports_other_plugins(source)
        if bad:
            offenders[path] = bad
    assert offenders == {}, (
        "ADR-007 violation — Tektos renderer/plugin imports another plugin: "
        + repr(offenders)
    )


def test_render_and_gate_plan_card_signature_matches_adr_041() -> None:
    """Locked signature — protects against silent surface drift."""
    sig = inspect.signature(render_and_gate_plan_card)
    params = list(sig.parameters.keys())
    assert params == ["plan", "panel_id", "approval", "memory"]


# ---------------------------------------------------------------------------
# ADR-041 DoD literal: end-to-end on the Stage 3.6 add-dark-mode fixture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_produce_plan_renders_as_approvable_card_via_frontend_contract_port_build_sequence_3_7_dod() -> (  # noqa: E501
    None
):
    """Stage 3.7 Definition of Done literal.

    "Plans render as user-approvable UI cards."

    1. Run Stage 3.6 ``produce_plan`` on the committed real fixture
       ``plugins/tektos/tests/fixtures/openspec/add-dark-mode``.
    2. Render the resulting ``Plan`` via ``render_and_gate_plan_card``:
        - fake ``ApprovalGatewayPort`` records HUMAN_REVIEW propose call
        - fake ``MemoryPort`` records the ``tektos.plan.card_rendered``
          write with locked provenance
    3. Bootstrap ``TektosPlugin`` against a fake ``FrontendContractPort``.
       Verify the plan-approval ``Panel`` is registered on
       ``APPROVALS_QUEUE`` at priority 90 with ``lazy_module=
       tektos/panels/PlanApprovalPanel``.
    4. Assert the returned ``PlanCard`` contains the change_id, delta
       aggregation, clamped confidence, HUMAN_REVIEW tier, and the
       apex approval_id so the frontend has everything it needs to
       render the card.
    """
    assert (
        ADD_DARK_MODE_FIXTURE / "proposal.md"
    ).exists(), "Stage 3.6 fixture missing"

    # Step 1: reuse the Stage 3.6 pipeline.
    stage_36_memory = _FakeMemoryPort()
    result = await produce_plan(ADD_DARK_MODE_FIXTURE, stage_36_memory)
    plan = result.plan
    assert plan.change_id == "add-dark-mode"
    assert plan.mean_completeness > 0.0

    # Step 2: render + gate.
    approval = _FakeApprovalGatewayPort(next_id="apex-dark-mode-1")
    stage_37_memory = _FakeMemoryPort()
    card = await render_and_gate_plan_card(
        plan,
        panel_id=TEKTOS_PLAN_APPROVAL_PANEL_ID,
        approval=approval,
        memory=stage_37_memory,
    )

    # Approval was proposed once, at HUMAN_REVIEW, by "tektos".
    assert len(approval.calls) == 1
    prop = approval.calls[0]
    assert prop["tier"] is ChangeApprovalTier.HUMAN_REVIEW
    assert prop["proposing_domain"] == "tektos"
    assert prop["intention_id"] == "tektos.plan.add-dark-mode"
    assert prop["delta"]["change_id"] == "add-dark-mode"

    # MemoryPort recorded exactly one write with locked provenance +
    # predicate, and the confidence is the clamped plan mean.
    assert len(stage_37_memory.writes) == 1
    w = stage_37_memory.writes[0]
    assert w["predicate"] == "tektos.plan.card_rendered"
    assert w["provenance"] == "tektos_plan_renderer"
    assert w["subject"] == "add-dark-mode::tektos.plan_approvals"
    assert w["confidence"] == clamp_card_confidence(plan.mean_completeness)
    assert w["attributes"]["approval_id"] == "apex-dark-mode-1"
    assert w["attributes"]["tier"] == "HUMAN_REVIEW"

    # Step 3: FrontendContractPort registration.
    fc = _FakeFrontendContract()
    plugin = TektosPlugin(frontend_contract_port=fc)
    await plugin.start()
    reg = plugin.registration
    assert reg is not None
    assert reg.descriptor.name == "tektos"
    assert len(reg.descriptor.panels) == 1
    panel = reg.descriptor.panels[0]
    assert panel.slot is PanelSlot.APPROVALS_QUEUE
    assert panel.priority == 90
    assert panel.lazy_module == "tektos/panels/PlanApprovalPanel"
    # ADR-045: Stage 3.11 flips ui_parity_status to COMPLIANT.
    assert reg.ui_parity_status is UiParityStatus.COMPLIANT

    # Step 4: card completeness — the projection carries every field a
    # frontend needs to render an approvable card.
    assert card.change_id == "add-dark-mode"
    assert card.approval_id == "apex-dark-mode-1"
    assert card.tier == "HUMAN_REVIEW"
    assert card.panel_id == "tektos.plan_approvals"
    assert card.rendered_summary == plan.rendered_summary
    assert card.task_count == plan.task_count
    assert card.done_task_count == plan.done_task_count
    # The add-dark-mode fixture has 2 ADDED + 1 MODIFIED + 1 REMOVED
    # in the single ui/ delta spec.
    assert card.delta_added == 2
    assert card.delta_modified == 1
    assert card.delta_removed == 1

    # Idempotent teardown.
    await plugin.stop()
    assert plugin.is_started is False
