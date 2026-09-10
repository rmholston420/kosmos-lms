"""adapters.immune.tektos — TektosImmuneAdapter.

Reference implementation of ``ports.immune.ImmunePort`` seeded with three
vendored donor detectors (ADR-092 §2):

* ``PromptInjectionDetector`` — 7 regex families for injection patterns.
* ``SecretExposureDetector`` — 12 regex families for credential leakage.
* ``DangerousCommandDetector`` — bash-write intent classifier
  (uses vendored ``_bash_command_writes`` + ``_bash_write_targets`` helpers).

Donor detectors take a ``vendor.immune_donor.ImmuneContext`` and return
``list[vendor.immune_donor.Threat]``. The port contract takes a
``ports.immune.ImmuneScanRequest`` and returns
``tuple[ports.immune.DetectorHit, ...]``. This adapter wraps each donor
detector in a ``_DetectorAdapter`` that performs the shape translation
plus severity mapping.

Aggregation policy per ADR-079: ``block`` if any hit is ``block``,
``warn`` if any is ``warn`` and none is ``block``, else ``allow``. Every
verdict publishes ``immune.verdict.<decision>`` on the injected
``EventBusPort``; every ``block`` verdict additionally writes a
``MemoryPort`` event with ``provenance="immune_verdict"``,
``confidence=1.0``.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ports.event_envelope import EventEnvelope
from ports.immune import (
    Detector,
    DetectorHit,
    DetectorInfo,
    DetectorSeverity,
    ImmuneScanRequest,
    ImmuneVerdict,
    ImmuneVerdictDecision,
    validate_scan_request,
)

from .vendor.immune_donor import (
    DangerousCommandDetector,
    ImmuneContext,
    PromptInjectionDetector,
    SecretExposureDetector,
    Threat,
    ThreatSeverity,
)

logger = logging.getLogger(__name__)

__all__ = ["TektosImmuneAdapter", "build_seed_detectors"]


# ── Port dependency Protocols ────────────────────────────────────────────


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class _MemoryLike(Protocol):
    async def write_event(  # pragma: no cover
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        attributes: dict | None = None,
    ) -> str: ...


# ── Donor severity → port severity mapping (ADR-079) ─────────────────────


def _donor_severity_to_port(sev: ThreatSeverity) -> DetectorSeverity:
    """Map donor ThreatSeverity IntEnum to the port's three-tier ceiling.

    Donor values (from vendor.immune_donor):
        LOW = 1, MEDIUM = 2, HIGH = 3, CRITICAL = 4

    Port values:
        info → advisory only (LOW)
        warn → advisory but noteworthy (MEDIUM)
        block → hard stop (HIGH or CRITICAL)
    """
    if sev >= ThreatSeverity.HIGH:
        return "block"
    if sev >= ThreatSeverity.MEDIUM:
        return "warn"
    return "info"


def _hit_severity_rank(sev: DetectorSeverity) -> int:
    return {"info": 0, "warn": 1, "block": 2}[sev]


# ── Detector wrapper: donor → port ───────────────────────────────────────


class _DetectorAdapter:
    """Wrap a vendored donor detector to satisfy ``ports.immune.Detector``.

    Attributes ``name`` and ``severity_ceiling`` come from the wrapper's
    constructor; ``evaluate`` calls the donor's ``detect`` and translates
    each returned ``Threat`` into a ``DetectorHit``.
    """

    def __init__(
        self,
        name: str,
        severity_ceiling: DetectorSeverity,
        donor,
    ) -> None:
        self.name = name
        self.severity_ceiling = severity_ceiling
        self._donor = donor

    async def evaluate(
        self, request: ImmuneScanRequest
    ) -> tuple[DetectorHit, ...]:
        ctx = self._request_to_context(request)
        threats: list[Threat] = await self._donor.detect(ctx)
        hits: list[DetectorHit] = []
        for threat in threats:
            sev = _donor_severity_to_port(threat.severity)
            # A detector must not exceed its declared ceiling.
            if _hit_severity_rank(sev) > _hit_severity_rank(self.severity_ceiling):
                sev = self.severity_ceiling
            hits.append(
                DetectorHit(
                    detector_name=self.name,
                    severity=sev,
                    evidence=threat.description,
                )
            )
        return tuple(hits)

    def _request_to_context(self, request: ImmuneScanRequest) -> ImmuneContext:
        """Translate the port's payload dict into the donor's context shape.

        Field mapping:
        * ``payload["prompt"]`` or ``payload["task_description"]`` → ctx.task_description
        * ``payload["tool_name"]`` → ctx.tool_name
        * ``payload["tool_input"]`` → ctx.tool_input
        * ``payload["session_id"]`` → ctx.session_id
        * anything else → ctx.metadata

        Unknown keys land in ``metadata`` so no information is dropped.
        """
        payload = request.payload
        known_keys = {"prompt", "task_description", "tool_name", "tool_input", "session_id"}
        metadata = {k: v for k, v in payload.items() if k not in known_keys}
        metadata["kind"] = request.kind
        metadata["source_plugin"] = request.source_plugin
        return ImmuneContext(
            session_id=payload.get("session_id"),
            tool_name=payload.get("tool_name"),
            tool_input=payload.get("tool_input"),
            task_description=payload.get("prompt") or payload.get("task_description"),
            metadata=metadata,
        )


def build_seed_detectors() -> tuple[_DetectorAdapter, ...]:
    """Return the three ADR-092 seed detectors ready to register.

    Each ceiling reflects the donor's own maximum severity:
    * prompt_injection → ``block`` (HIGH severity for multi-match)
    * secret_exposure → ``block`` (CRITICAL for known keys)
    * dangerous_command → ``block`` (CRITICAL for rm -rf /)
    """
    return (
        _DetectorAdapter(
            "prompt_injection",
            "block",
            PromptInjectionDetector(),
        ),
        _DetectorAdapter(
            "secret_exposure",
            "block",
            SecretExposureDetector(),
        ),
        _DetectorAdapter(
            "dangerous_command",
            "block",
            DangerousCommandDetector(),
        ),
    )


# ── Adapter ──────────────────────────────────────────────────────────────


class TektosImmuneAdapter:
    """ImmunePort adapter composing donor detectors.

    Constructed empty; call ``register_detector`` for each detector to
    add, or pass ``initial_detectors`` at construction. Use the module-
    level ``build_seed_detectors()`` helper for the ADR-092 seed set.
    """

    def __init__(
        self,
        *,
        initial_detectors: tuple[Detector, ...] = (),
        event_bus: _EventBusLike | None = None,
        memory: _MemoryLike | None = None,
    ) -> None:
        self._detectors: dict[str, Detector] = {}
        for d in initial_detectors:
            self._detectors[d.name] = d
        self._event_bus = event_bus
        self._memory = memory
        self._closed = False

    async def scan(self, request: ImmuneScanRequest) -> ImmuneVerdict:
        if self._closed:
            raise RuntimeError("TektosImmuneAdapter is closed.")
        validate_scan_request(request)
        all_hits: list[DetectorHit] = []
        for detector in self._detectors.values():
            try:
                detector_hits = await detector.evaluate(request)
            except Exception:  # noqa: BLE001 — one bad detector must not down the port
                logger.exception(
                    "immune detector %s raised during evaluate", detector.name
                )
                continue
            all_hits.extend(detector_hits)
        decision = self._aggregate(all_hits)
        reason = self._reason_for(decision, all_hits)
        verdict = ImmuneVerdict(
            decision=decision,
            detector_hits=tuple(all_hits),
            reason=reason,
        )
        await self._publish_verdict(request, verdict)
        if decision == "block":
            await self._record_block_memory(request, verdict)
        return verdict

    async def register_detector(self, detector: Detector) -> None:
        # ADR-079 rule 3: idempotent by name
        self._detectors[detector.name] = detector

    async def list_detectors(self) -> tuple[DetectorInfo, ...]:
        return tuple(
            DetectorInfo(
                name=d.name,
                severity_ceiling=d.severity_ceiling,
                description=getattr(d, "__doc__", "") or "",
            )
            for d in self._detectors.values()
        )

    def is_healthy(self) -> bool:
        try:
            return not self._closed
        except Exception:  # noqa: BLE001 — ADR-023 rule 5
            return False

    async def close(self) -> None:
        self._closed = True
        self._detectors.clear()

    # ── Internal ──────────────────────────────────────────────────────

    @staticmethod
    def _aggregate(hits: list[DetectorHit]) -> ImmuneVerdictDecision:
        if any(h.severity == "block" for h in hits):
            return "block"
        if any(h.severity == "warn" for h in hits):
            return "warn"
        return "allow"

    @staticmethod
    def _reason_for(
        decision: ImmuneVerdictDecision, hits: list[DetectorHit]
    ) -> str:
        if not hits:
            return "no detectors fired"
        if decision == "allow":
            return "only info-severity hits"
        top = [h for h in hits if h.severity == decision]
        names = ", ".join(sorted({h.detector_name for h in top}))
        return f"{decision} from: {names}"

    async def _publish_verdict(
        self, request: ImmuneScanRequest, verdict: ImmuneVerdict
    ) -> None:
        if self._event_bus is None:
            return
        try:
            envelope = EventEnvelope(
                event_type=f"immune.verdict.{verdict.decision}",
                producer_plugin="tektos_immune_adapter",
                payload={
                    "source_plugin": request.source_plugin,
                    "kind": request.kind,
                    "decision": verdict.decision,
                    "reason": verdict.reason,
                    "hit_count": len(verdict.detector_hits),
                    "hits": [
                        {
                            "detector": h.detector_name,
                            "severity": h.severity,
                            "evidence": h.evidence,
                        }
                        for h in verdict.detector_hits
                    ],
                    "source": "tektos_immune",
                },
            )
            await self._event_bus.publish(envelope)
        except Exception:  # noqa: BLE001
            logger.exception(
                "immune verdict publish failed (decision=%s)", verdict.decision
            )

    async def _record_block_memory(
        self, request: ImmuneScanRequest, verdict: ImmuneVerdict
    ) -> None:
        if self._memory is None:
            return
        try:
            await self._memory.write_event(
                subject=f"immune:scan:{request.source_plugin}",
                predicate="blocked_by",
                object=verdict.reason,
                provenance="immune_verdict",
                confidence=1.0,
                attributes={
                    "kind": request.kind,
                    "hit_count": len(verdict.detector_hits),
                    "detectors": sorted(
                        {h.detector_name for h in verdict.detector_hits if h.severity == "block"}
                    ),
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("immune block memory write failed")
