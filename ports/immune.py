"""ports.immune — ImmunePort Protocol (ADR-079).

Formal Kosmos port for immune-system scanning of events before they take effect.
Locked at Stage 3.13. First adapter (Tektos-Ultima donor: 12 detectors including
SecretExposureDetector with 12 regex patterns) lands under
``adapters/immune/tektos/``.

Enforcement rules (per ADR-079 + spec §25.4):

1. Every ``scan()`` result MUST be published on ``EventBusPort`` under envelope
   kind ``immune.verdict.<decision>`` (``allow`` / ``warn`` / ``block``).
2. Every ``scan()`` call that returns ``block`` MUST also write a ``MemoryPort``
   event with ``provenance="immune_verdict"`` and ``confidence=1.0``.
3. ``register_detector()`` is idempotent by ``detector.name``.
4. Adapters live under ``adapters/immune/<vendor>/`` and MUST implement this
   Protocol in full.
5. Port-level guard rejects ``scan()`` calls with ``source_plugin=""``
   (mirrors ADR-023 rule 2).

Canonical shape (matches ADR-022/023/024/025/026/027):

- Backend-touching methods are async.
- ``is_healthy()`` is sync + non-throwing (ADR-023 rule 5).
- ``close()`` is async + idempotent.
- Typed value objects returned from reads (no raw dicts).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = [
    "Detector",
    "DetectorHit",
    "DetectorInfo",
    "ImmunePort",
    "ImmuneScanRequest",
    "ImmuneVerdict",
    "ImmuneVerdictDecision",
    "validate_scan_request",
]


ImmuneVerdictDecision = Literal["allow", "warn", "block"]
"""Ternary immune verdict — see ADR-079."""

DetectorSeverity = Literal["info", "warn", "block"]
"""Severity ceiling a detector may emit."""


@dataclass(frozen=True, slots=True)
class ImmuneScanRequest:
    """Immutable payload for an ``ImmunePort.scan()`` call.

    ``payload`` is the thing being scanned (event body, LLM output, tool
    invocation, etc.). ``kind`` is a subsystem-scoped classifier (e.g.
    ``"tektos.tool.invocation"``). ``source_plugin`` MUST be non-empty per
    ADR-079 rule 5 — port-level guard rejects blank values.
    """

    payload: dict[str, Any]
    kind: str
    source_plugin: str


@dataclass(frozen=True, slots=True)
class DetectorHit:
    """One detector's finding within an ``ImmuneVerdict``. Immutable."""

    detector_name: str
    severity: DetectorSeverity
    evidence: str


@dataclass(frozen=True, slots=True)
class ImmuneVerdict:
    """Outcome of a scan. Immutable.

    ``decision`` is the aggregate — ``block`` if any hit is ``block``,
    ``warn`` if any hit is ``warn`` and none is ``block``, else ``allow``.
    Adapters are responsible for computing the aggregate; callers should
    trust ``decision`` rather than re-scanning ``detector_hits``.
    """

    decision: ImmuneVerdictDecision
    detector_hits: tuple[DetectorHit, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class DetectorInfo:
    """Metadata for a registered detector. Immutable."""

    name: str
    severity_ceiling: DetectorSeverity
    description: str


@runtime_checkable
class Detector(Protocol):
    """One immune detector. Adapters compose many of these.

    A ``Detector`` is a callable-shaped object with a stable ``name`` and a
    ``severity_ceiling`` (the strongest verdict this detector may emit).
    """

    name: str
    severity_ceiling: DetectorSeverity

    async def evaluate(self, request: ImmuneScanRequest) -> tuple[DetectorHit, ...]:
        """Return zero or more hits for this scan request."""
        ...


def validate_scan_request(request: ImmuneScanRequest) -> None:
    """Enforce ADR-079 rule 5 at the port layer.

    Raises ``ValueError`` on invalid input. Non-bypassable.
    """
    if not request.source_plugin:
        raise ValueError(
            "ImmuneScanRequest.source_plugin MUST be non-empty (ADR-079 rule 5)."
        )
    if not request.kind:
        raise ValueError("ImmuneScanRequest.kind MUST be non-empty.")


@runtime_checkable
class ImmunePort(Protocol):
    """Formal Kosmos contract for immune-system scanning.

    Adapters MUST implement every method. Port-level guards
    (``validate_scan_request``) run at adapter entry — do not bypass.
    """

    # ── Scanning ──────────────────────────────────────────────────────────

    async def scan(self, request: ImmuneScanRequest) -> ImmuneVerdict:
        """Scan ``request`` against all registered detectors.

        MUST publish ``immune.verdict.<decision>`` on ``EventBusPort`` after
        computing the verdict (ADR-079 rule 1). If ``decision == "block"``,
        MUST also write a ``MemoryPort`` event with
        ``provenance="immune_verdict"`` and ``confidence=1.0`` (rule 2).
        """
        ...

    # ── Detector registry ────────────────────────────────────────────────

    async def register_detector(self, detector: Detector) -> None:
        """Register ``detector`` for future scans. Idempotent by name."""
        ...

    async def list_detectors(self) -> tuple[DetectorInfo, ...]:
        """Return metadata for every registered detector."""
        ...

    # ── Health & lifecycle ────────────────────────────────────────────────

    def is_healthy(self) -> bool:  # sync + non-throwing per ADR-023 rule 5
        """Return True iff the adapter is ready to serve scans.

        MUST NOT raise; catch adapter-internal errors and return False.
        """
        ...

    async def close(self) -> None:
        """Release adapter resources. Idempotent — calling twice is a no-op."""
        ...
