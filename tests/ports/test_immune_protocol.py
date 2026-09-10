"""Protocol conformance test for ImmunePort (ADR-079).

Any adapter satisfying ``ImmunePort`` MUST pass this test. Fast tier —
no network, no live event bus, no live memory. Uses a stub adapter that
returns a fixed verdict so we exercise the Protocol shape and port-level
guards, not the backend.
"""

from __future__ import annotations

import asyncio

import pytest

from ports.immune import (
    Detector,
    DetectorHit,
    DetectorInfo,
    ImmunePort,
    ImmuneScanRequest,
    ImmuneVerdict,
    validate_scan_request,
)


class _StubImmuneAdapter:
    """Minimal ImmunePort implementation used only for protocol tests."""

    def __init__(self) -> None:
        self._closed = False
        self._detectors: dict[str, Detector] = {}

    async def scan(self, request: ImmuneScanRequest) -> ImmuneVerdict:
        validate_scan_request(request)  # port-level guard first
        # Aggregate stub: allow unless payload has "block": True.
        if request.payload.get("block") is True:
            hit = DetectorHit(
                detector_name="stub",
                severity="block",
                evidence="stub-block",
            )
            return ImmuneVerdict(
                decision="block",
                detector_hits=(hit,),
                reason="stub blocked",
            )
        return ImmuneVerdict(decision="allow", detector_hits=(), reason="ok")

    async def register_detector(self, detector: Detector) -> None:
        self._detectors[detector.name] = detector  # idempotent by name

    async def list_detectors(self) -> tuple[DetectorInfo, ...]:
        return tuple(
            DetectorInfo(
                name=d.name,
                severity_ceiling=d.severity_ceiling,
                description="stub",
            )
            for d in self._detectors.values()
        )

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True


class _StubDetector:
    def __init__(self, name: str) -> None:
        self.name = name
        self.severity_ceiling = "block"

    async def evaluate(self, request: ImmuneScanRequest) -> tuple[DetectorHit, ...]:
        return ()


def test_stub_adapter_satisfies_protocol_runtime_checkable() -> None:
    assert isinstance(_StubImmuneAdapter(), ImmunePort)


def test_stub_detector_satisfies_detector_protocol() -> None:
    assert isinstance(_StubDetector("x"), Detector)


def test_scan_allow_verdict_shape() -> None:
    adapter = _StubImmuneAdapter()
    req = ImmuneScanRequest(payload={"x": 1}, kind="tektos.tool.invocation", source_plugin="tektos")
    verdict = asyncio.run(adapter.scan(req))
    assert verdict.decision == "allow"
    assert verdict.detector_hits == ()


def test_scan_block_verdict_shape() -> None:
    adapter = _StubImmuneAdapter()
    req = ImmuneScanRequest(payload={"block": True}, kind="tektos.tool.invocation", source_plugin="tektos")
    verdict = asyncio.run(adapter.scan(req))
    assert verdict.decision == "block"
    assert len(verdict.detector_hits) == 1
    assert verdict.detector_hits[0].severity == "block"


def test_scan_rejects_empty_source_plugin() -> None:
    # ADR-079 rule 5 enforced at port layer.
    with pytest.raises(ValueError, match="source_plugin"):
        validate_scan_request(
            ImmuneScanRequest(payload={}, kind="k", source_plugin="")
        )


def test_scan_rejects_empty_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        validate_scan_request(
            ImmuneScanRequest(payload={}, kind="", source_plugin="tektos")
        )


def test_register_detector_is_idempotent_by_name() -> None:
    adapter = _StubImmuneAdapter()

    async def _run() -> int:
        await adapter.register_detector(_StubDetector("dup"))
        await adapter.register_detector(_StubDetector("dup"))  # replace, don't append
        infos = await adapter.list_detectors()
        return len(infos)

    assert asyncio.run(_run()) == 1


def test_is_healthy_never_raises() -> None:
    adapter = _StubImmuneAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False


def test_close_is_idempotent() -> None:
    adapter = _StubImmuneAdapter()

    async def _run() -> None:
        await adapter.close()
        await adapter.close()

    asyncio.run(_run())
