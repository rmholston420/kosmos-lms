"""FrontendContractPort — declarative UI schema for the kernel dashboard (ADR-031).

Declared surface per spec §4.1 line 91 (Q1=B full surface):

    register_plugin() · unregister_plugin() · list_plugins()
    get_route_manifest() · get_design_tokens() · get_state_namespaces()
    get_panel_manifest() · check_ui_parity() · render_kernel_schema()

Plus lifecycle:

    is_healthy() · close()

Non-bypassable zero-trust :func:`validate_plugin_descriptor` runs at the
top of :meth:`FrontendContractPort.register_plugin` before any store
I/O, mirroring ADR-026/027/028/029/030.

One injectable Protocol seam so contract tests use a pure-stdlib double
(no third-party imports required for test execution):

    ManifestStore — async ``save(schema) -> None`` / ``load() -> KernelSchema | None``

ADR-089 (2026-09-10) extends this port with ``PanelKind.IFRAME`` so the
Kosmos Next 16.2.11 shell can host the Tektos Next 15.4 UI as a
microfrontend under ``/tektos/frontend``. Iframe panels carry an
``IframeConfig`` (``src``, ``sandbox``, ``title``, ``size_hint``); the
kernel dashboard renders them behind a same-origin reverse proxy with a
postMessage bridge that validates ``event.origin`` and re-publishes
cross-boundary events on server-side ``EventBusPort``. CSP
``frame-ancestors 'self'`` MUST be set globally by the shell.

See ADR-031 for the base contract; ADR-089 for the iframe extension.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "DEFAULT_IFRAME_SANDBOX",
    "FrontendContractPort",
    "IframeConfig",
    "KERNEL_SCHEMA_TITLE",
    "KernelSchema",
    "ManifestStore",
    "PLUGIN_REQUIRED_FIELDS",
    "Panel",
    "PanelKind",
    "PanelSlot",
    "PluginDescriptor",
    "PluginDescriptorRejected",
    "PluginNotFound",
    "PluginRegistration",
    "Route",
    "UiParityStatus",
    "validate_plugin_descriptor",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UiParityStatus(str, Enum):
    """Per spec §7 / §17.1 UI Parity Rule."""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLIANT = "COMPLIANT"
    GRANDFATHERED = "GRANDFATHERED"


class PanelSlot(str, Enum):
    """The kernel-dashboard slots enumerated by spec §280 + §17.9 + §17.13."""

    ALGEDONIC = "ALGEDONIC"
    GOVERNANCE = "GOVERNANCE"
    MEMORY_INTEGRITY = "MEMORY_INTEGRITY"
    MODEL_SWAP_SLO = "MODEL_SWAP_SLO"
    STUB_DEGRADATION = "STUB_DEGRADATION"
    CONTEXT_PRESSURE = "CONTEXT_PRESSURE"
    HARDWARE_RESILIENCE = "HARDWARE_RESILIENCE"
    APPROVALS_QUEUE = "APPROVALS_QUEUE"
    AGENT_TRACE = "AGENT_TRACE"


class PanelKind(str, Enum):
    """How a panel's contents are produced (ADR-089).

    ``LAZY_MODULE`` — default, matches Rigpa donor shape: the frontend
    resolves ``Panel.lazy_module`` via ``import(...)`` and renders its
    exported React component in-tree.

    ``IFRAME``      — the frontend renders an ``<iframe>`` pointing at
    ``Panel.iframe.src`` behind a same-origin reverse proxy, with the
    HTML ``sandbox`` attributes from ``Panel.iframe.sandbox`` and a
    postMessage bridge that validates ``event.origin`` before
    re-publishing to server-side ``EventBusPort``.
    """

    LAZY_MODULE = "LAZY_MODULE"
    IFRAME = "IFRAME"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PLUGIN_REQUIRED_FIELDS = frozenset(
    {"name", "state_namespace", "version", "kernel_compat"}
)
"""Fields the port-level zero-trust guard mandates on every descriptor."""


KERNEL_SCHEMA_TITLE: str = "Kosmos"
"""Build-Sequence §1.14 DoD anchor: empty dashboard renders this title."""


DEFAULT_IFRAME_SANDBOX: tuple[str, ...] = (
    "allow-same-origin",
    "allow-scripts",
    "allow-forms",
)
"""Default HTML ``sandbox`` tokens for ``PanelKind.IFRAME`` panels (ADR-089).

Mirror the Tektos-Ultima frontend's own iframe embed defaults. Panels MAY
replace this set (e.g. add ``allow-popups``) but MUST NOT drop
``allow-same-origin`` while the postMessage bridge is required for event
relay.
"""


_PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# Value objects (all frozen dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Route:
    """A route contributed by a plugin.

    ``lazy_module`` is the string identifier the frontend resolves via
    ``import(lazy_module)`` (Rigpa donor: `() => import("./views/X")`).
    """

    path: str
    label: str
    icon: str
    lazy_module: str


@dataclass(frozen=True, slots=True)
class IframeConfig:
    """Iframe-rendering config for a ``PanelKind.IFRAME`` panel (ADR-089).

    ``src`` is a same-origin URL served by the kernel's reverse proxy
    (e.g. ``/tektos/frontend``). ``sandbox`` is the HTML sandbox token
    set applied to the iframe. ``title`` is the accessible name. ``size_hint``
    (``"small" | "medium" | "large" | "full"``) advises the shell on
    default sizing; the shell may override.
    """

    src: str
    title: str
    sandbox: tuple[str, ...] = DEFAULT_IFRAME_SANDBOX
    size_hint: str = "medium"


@dataclass(frozen=True, slots=True)
class Panel:
    """A kernel-dashboard panel contributed by a plugin.

    Higher :attr:`priority` renders first
    (matches ADR-029 priority-queue ordering).

    ``kind`` defaults to ``PanelKind.LAZY_MODULE`` (the pre-ADR-089 shape,
    so existing panels keep working unmodified). When ``kind`` is
    ``PanelKind.IFRAME``, ``iframe`` MUST be non-``None`` and
    ``lazy_module`` MAY be a sentinel like ``"iframe://<panel_id>"``
    (validators only require it non-empty).
    """

    id: str
    slot: PanelSlot
    priority: int
    lazy_module: str
    plugin_name: str
    kind: PanelKind = PanelKind.LAZY_MODULE
    iframe: IframeConfig | None = None


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    """A plugin's frontend-side declaration.

    Mirrors Rigpa-LMS ``RigpaFrontendPlugin`` donor shape (name /
    stateNamespace / designTokens / routes) plus Kosmos-specific
    additions (version / kernel_compat / panels).
    """

    name: str
    state_namespace: str
    version: str
    kernel_compat: str
    design_tokens: Mapping[str, str] = field(default_factory=dict)
    routes: tuple[Route, ...] = ()
    panels: tuple[Panel, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    """Returned by :meth:`FrontendContractPort.register_plugin`."""

    descriptor: PluginDescriptor
    registered_at: datetime
    ui_parity_status: UiParityStatus


@dataclass(frozen=True, slots=True)
class KernelSchema:
    """Top-level payload returned by :meth:`FrontendContractPort.render_kernel_schema`.

    Build-Sequence §1.14 DoD is satisfied when this contains
    ``title=KERNEL_SCHEMA_TITLE`` (``"Kosmos"``) with empty plugins and
    panels.
    """

    title: str
    plugins: tuple[PluginDescriptor, ...]
    panels: tuple[Panel, ...]
    design_tokens: Mapping[str, str]
    generated_at: datetime


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PluginDescriptorRejected(ValueError):
    """Raised by :func:`validate_plugin_descriptor` on missing/invalid fields."""


class PluginNotFound(KeyError):
    """Raised by lookup verbs on unknown plugin names."""


# ---------------------------------------------------------------------------
# Zero-trust guard (non-bypassable)
# ---------------------------------------------------------------------------


def validate_plugin_descriptor(descriptor: PluginDescriptor) -> None:
    """Reject registrations missing or containing invalid required fields."""
    if not isinstance(descriptor, PluginDescriptor):
        raise PluginDescriptorRejected(
            f"descriptor rejected: expected PluginDescriptor, got "
            f"{type(descriptor).__name__!r}"
        )

    for name in ("name", "state_namespace", "version", "kernel_compat"):
        value = getattr(descriptor, name)
        if not isinstance(value, str) or not value:
            raise PluginDescriptorRejected(
                f"descriptor rejected: {name!r} must be a non-empty str, "
                f"got {type(value).__name__!r}"
            )

    if not _PLUGIN_NAME_RE.fullmatch(descriptor.name):
        raise PluginDescriptorRejected(
            f"descriptor rejected: 'name' must be lowercase-alphanumeric "
            f"with single-hyphen separators, got {descriptor.name!r}"
        )

    for i, route in enumerate(descriptor.routes):
        if not isinstance(route, Route):
            raise PluginDescriptorRejected(
                f"descriptor rejected: routes[{i}] must be Route, "
                f"got {type(route).__name__!r}"
            )
        if not isinstance(route.lazy_module, str) or not route.lazy_module:
            raise PluginDescriptorRejected(
                f"descriptor rejected: routes[{i}].lazy_module must be a "
                f"non-empty str"
            )

    for i, panel in enumerate(descriptor.panels):
        if not isinstance(panel, Panel):
            raise PluginDescriptorRejected(
                f"descriptor rejected: panels[{i}] must be Panel, "
                f"got {type(panel).__name__!r}"
            )
        if not isinstance(panel.slot, PanelSlot):
            raise PluginDescriptorRejected(
                f"descriptor rejected: panels[{i}].slot must be PanelSlot "
                f"enum member, got {type(panel.slot).__name__!r}"
            )
        if not isinstance(panel.lazy_module, str) or not panel.lazy_module:
            raise PluginDescriptorRejected(
                f"descriptor rejected: panels[{i}].lazy_module must be a "
                f"non-empty str"
            )
        if not isinstance(panel.kind, PanelKind):
            raise PluginDescriptorRejected(
                f"descriptor rejected: panels[{i}].kind must be PanelKind "
                f"enum member, got {type(panel.kind).__name__!r}"
            )
        if panel.kind is PanelKind.IFRAME:
            if not isinstance(panel.iframe, IframeConfig):
                raise PluginDescriptorRejected(
                    f"descriptor rejected: panels[{i}].iframe must be "
                    f"IframeConfig when kind=IFRAME (ADR-089), got "
                    f"{type(panel.iframe).__name__!r}"
                )
            if not isinstance(panel.iframe.src, str) or not panel.iframe.src:
                raise PluginDescriptorRejected(
                    f"descriptor rejected: panels[{i}].iframe.src must be a "
                    f"non-empty str (ADR-089)"
                )
            if not isinstance(panel.iframe.title, str) or not panel.iframe.title:
                raise PluginDescriptorRejected(
                    f"descriptor rejected: panels[{i}].iframe.title must be a "
                    f"non-empty str (ADR-089)"
                )
            if "allow-same-origin" not in panel.iframe.sandbox:
                raise PluginDescriptorRejected(
                    f"descriptor rejected: panels[{i}].iframe.sandbox must "
                    f"include 'allow-same-origin' for postMessage bridge "
                    f"(ADR-089)"
                )
        elif panel.iframe is not None:
            raise PluginDescriptorRejected(
                f"descriptor rejected: panels[{i}].iframe must be None when "
                f"kind={panel.kind.value} (ADR-089)"
            )


# ---------------------------------------------------------------------------
# Injectable Protocol seam
# ---------------------------------------------------------------------------


@runtime_checkable
class ManifestStore(Protocol):
    """Pluggable storage backend for the plugin manifest.

    Contract:

    - :meth:`save` overwrites any previous manifest atomically.
    - :meth:`load` returns ``None`` when no manifest has been saved yet.
    - Neither method raises for transport errors; adapters normalize
      failures to ``None`` on load and swallow errors on save (logged
      via ObservabilityPort when wired).
    """

    async def save(self, schema: KernelSchema) -> None: ...

    async def load(self) -> KernelSchema | None: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# FrontendContractPort Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class FrontendContractPort(Protocol):
    """Kosmos FrontendContractPort — declarative UI schema (ADR-031)."""

    async def register_plugin(
        self, descriptor: PluginDescriptor
    ) -> PluginRegistration:
        """Register ``descriptor``. Guard runs first; store persists."""
        ...

    async def unregister_plugin(self, name: str) -> bool:
        """Remove ``name`` from the registry. Returns ``False`` if unknown."""
        ...

    async def list_plugins(self) -> list[PluginDescriptor]:
        """Return all registered plugin descriptors."""
        ...

    async def get_route_manifest(self) -> list[Route]:
        """Return every route contributed by every registered plugin."""
        ...

    async def get_design_tokens(self) -> dict[str, str]:
        """Return merged design tokens (last-registered-wins on collision)."""
        ...

    async def get_state_namespaces(self) -> list[str]:
        """Return every state namespace claimed by a registered plugin."""
        ...

    async def get_panel_manifest(
        self, slot: PanelSlot | None = None
    ) -> list[Panel]:
        """Return panels, filtered by ``slot`` if given, sorted priority DESC."""
        ...

    async def check_ui_parity(self, name: str) -> UiParityStatus:
        """Return the UI-parity status for a registered plugin."""
        ...

    async def render_kernel_schema(self) -> KernelSchema:
        """Return the top-level payload the kernel dashboard renders.

        With no plugin registered, ``title == KERNEL_SCHEMA_TITLE`` and
        both ``plugins`` and ``panels`` are empty — literally satisfies
        Build-Sequence §1.14 DoD.
        """
        ...

    def is_healthy(self) -> bool:
        """Sync, non-throwing health probe (ADR-023 rule 5)."""
        ...

    async def close(self) -> None:
        """Idempotent teardown; cascades to :class:`ManifestStore`."""
        ...
