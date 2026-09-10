"""Tektos plugin bootstrap (Stage 3.7, ADR-041).

Fires the ADR-036 §Q4=B trigger that deferred Tektos's first
:class:`~ports.frontend_contract.PluginDescriptor` registration to
Stage 3.7. Mirrors :class:`~plugins.phrouros.plugin.PhrourosPlugin`'s
shape:

- Dataclass with cheap side-effect-free construction.
- Async :meth:`start` — registers the
  :class:`~ports.frontend_contract.PluginDescriptor` with
  :class:`~ports.frontend_contract.FrontendContractPort`. Idempotent.
- Async :meth:`stop` — idempotent.

The registered descriptor contributes exactly one
:class:`~ports.frontend_contract.Panel` on
:attr:`~ports.frontend_contract.PanelSlot.APPROVALS_QUEUE` at
``priority=90`` (below Praxis's own ``priority=100`` panel per
ADR-033 §Q1). Ordering is priority-DESC per ADR-031, so Praxis
approvals render above Tektos plan cards in the same slot.

``ui_parity_status`` is :attr:`UiParityStatus.IN_PROGRESS` at 3.7;
COMPLIANT flips at Stage 3.11 (ADR-045) via the addition of a
single :class:`~ports.frontend_contract.Route` below. Praxis
(ADR-032) and Phrouros (ADR-034) remain IN_PROGRESS.

ADR-007: this module imports only from ``ports.*`` and its own
``plugins.tektos.renderer`` subpackage. It MUST NOT import any other
plugin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ports.frontend_contract import (
    FrontendContractPort,
    Panel,
    PanelSlot,
    PluginDescriptor,
    PluginRegistration,
    Route,
)

from .ui.policy import (
    TEKTOS_UI_ROUTE_ICON,
    TEKTOS_UI_ROUTE_LABEL,
    TEKTOS_UI_ROUTE_LAZY_MODULE,
    TEKTOS_UI_ROUTE_PATH,
)

__all__ = [
    "TEKTOS_KERNEL_COMPAT",
    "TEKTOS_PLAN_APPROVAL_PANEL_ID",
    "TEKTOS_PLAN_APPROVAL_PANEL_PRIORITY",
    "TEKTOS_PLAN_APPROVAL_LAZY_MODULE",
    "TEKTOS_PLUGIN_NAME",
    "TEKTOS_STATE_NAMESPACE",
    "TEKTOS_VERSION",
    "TektosPlugin",
    "build_tektos_descriptor",
]


TEKTOS_PLUGIN_NAME: str = "tektos"
"""Locked plugin name — matches ``TEKTOS_PLAN_PROPOSING_DOMAIN`` in
:mod:`plugins.tektos.renderer.policy` and ADR-036's ``proposing_domain``."""

TEKTOS_STATE_NAMESPACE: str = "tektos"
"""Locked state namespace mirroring the plugin name (ADR-031 shape)."""

TEKTOS_VERSION: str = "0.1.0"
"""Semantic version. Bumps require an ADR."""

TEKTOS_KERNEL_COMPAT: str = "0.1.x"
"""Kernel-compat range. Matches every other Phase-1/Phase-2/Phase-3 plugin."""


TEKTOS_PLAN_APPROVAL_PANEL_ID: str = "tektos.plan_approvals"
"""Panel id for the Stage 3.7 plan-approval card panel.

Namespaced under ``tektos.`` so it does not collide with Praxis's
own ``praxis.approvals`` panel (ADR-033 §Q1) on the same slot."""

TEKTOS_PLAN_APPROVAL_LAZY_MODULE: str = "tektos/panels/PlanApprovalPanel"
"""Frontend module identifier the Stage 3.5-deferred Next.js shell
will eventually resolve. Deferred renderer per ADR-039 (§3.5 defer);
declared here so the ADR-031 descriptor is complete at 3.7."""

TEKTOS_PLAN_APPROVAL_PANEL_PRIORITY: int = 90
"""Priority within :attr:`PanelSlot.APPROVALS_QUEUE`.

Praxis's ``praxis.approvals`` panel is registered at ``priority=100``
per ADR-033 §Q1=C. ADR-031 orders panels priority-DESC with
insertion-order tiebreak, so Praxis renders above Tektos in the same
slot. This is intentional: Praxis governance approvals outrank
Tektos plan approvals in the queue."""


def build_tektos_descriptor() -> PluginDescriptor:
    """Construct the Tektos :class:`PluginDescriptor`.

    Pure function — no I/O, no side effects. Split out for testability
    (contract tests inspect the descriptor without instantiating the
    plugin). Matches the same pattern as
    :func:`plugins.phrouros.plugin.build_phrouros_descriptor`.
    """
    plan_approval_panel = Panel(
        id=TEKTOS_PLAN_APPROVAL_PANEL_ID,
        slot=PanelSlot.APPROVALS_QUEUE,
        priority=TEKTOS_PLAN_APPROVAL_PANEL_PRIORITY,
        lazy_module=TEKTOS_PLAN_APPROVAL_LAZY_MODULE,
        plugin_name=TEKTOS_PLUGIN_NAME,
    )
    dashboard_route = Route(
        path=TEKTOS_UI_ROUTE_PATH,
        label=TEKTOS_UI_ROUTE_LABEL,
        icon=TEKTOS_UI_ROUTE_ICON,
        lazy_module=TEKTOS_UI_ROUTE_LAZY_MODULE,
    )
    return PluginDescriptor(
        name=TEKTOS_PLUGIN_NAME,
        state_namespace=TEKTOS_STATE_NAMESPACE,
        version=TEKTOS_VERSION,
        kernel_compat=TEKTOS_KERNEL_COMPAT,
        design_tokens={},
        routes=(dashboard_route,),
        panels=(plan_approval_panel,),
    )


@dataclass
class TektosPlugin:
    """Kosmos Tektos plugin (Phase 3 spec-driven code agent).

    Args:
        frontend_contract_port: kernel-side registration surface
            (:class:`FrontendContractPort`).

    Stage 3.7 landing scope: descriptor-only registration. Later
    stages will inject the OpenSpec engine (Stage 3.6, already
    landed), Tektos agent (Stage 3.1, already landed) and MCP tool
    router (Stage 3.2, already landed) as fields on this class. At
    3.7 we lock the FrontendContractPort registration and nothing
    more — matches ADR-036 §Q4=B trigger contract.
    """

    frontend_contract_port: FrontendContractPort

    # Stage 8.2 (ADR-104 D11): optional handle to the kernel-wired
    # ``TektosTurnLoop``. Populated at kernel-boot time by
    # ``kernel/app.py::_boot_tektos_turn_loop`` when
    # ``KOSMOS_TEKTOS_TURN_LOOP=on``. Stays ``None`` when the loop is
    # off, unwired, or degrade-suppressed. Kept as ``Any`` typing via
    # forward-string annotation would violate ADR-007 (no cross-plugin
    # type-import in this dataclass), so we intentionally type this as
    # ``object | None`` — downstream call sites should isinstance-check
    # or duck-type off it.
    turn_loop: object | None = field(default=None)

    # Stage 8.3 (ADR-105 D5): optional handles to the kernel-wired
    # reflection / synthesis / experience-replay engines. Populated at
    # kernel-boot time by
    # ``kernel/app.py::_boot_tektos_{reflection,synthesis,experience}``
    # when the corresponding ``KOSMOS_TEKTOS_{REFLECTION,SYNTHESIS,EXPERIENCE}=on``
    # env-gate is set and ``registry.relational_memory`` is bound. Each
    # stays ``None`` when the engine is off, unwired, or
    # degrade-suppressed. Typed as ``object | None`` for the same
    # ADR-007 reason as ``turn_loop`` above.
    reflection: object | None = field(default=None)
    synthesis: object | None = field(default=None)
    experience: object | None = field(default=None)

    _started: bool = field(default=False, init=False, repr=False)
    _registration: PluginRegistration | None = field(
        default=None, init=False, repr=False
    )

    async def start(self) -> None:
        """Register the descriptor. Idempotent."""
        if self._started:
            return
        descriptor = build_tektos_descriptor()
        self._registration = await self.frontend_contract_port.register_plugin(
            descriptor
        )
        self._started = True

    async def stop(self) -> None:
        """Deregister the descriptor via
        :meth:`FrontendContractPort.unregister_plugin`. Idempotent.

        Matches the Praxis/Phrouros shape — deregistration is the
        symmetric counterpart to :meth:`start` so tests can spin up
        and tear down the plugin cleanly.
        """
        if not self._started:
            return
        await self.frontend_contract_port.unregister_plugin(TEKTOS_PLUGIN_NAME)
        self._registration = None
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def registration(self) -> PluginRegistration | None:
        return self._registration
