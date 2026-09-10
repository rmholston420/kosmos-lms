"""Protocol conformance test for VisionPort (ADR-084).

Any adapter satisfying ``VisionPort`` MUST pass this test. Fast tier — no
LLaVA, no Tesseract. Uses a stub adapter that returns fixed outputs.
"""

from __future__ import annotations

import asyncio

from ports.vision import (
    OCRBlock,
    OCRResult,
    VisionDescription,
    VisionDetection,
    VisionPort,
)


class _StubVisionAdapter:
    """Minimal VisionPort implementation used only for protocol tests."""

    def __init__(self) -> None:
        self._closed = False

    async def describe(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> VisionDescription:
        return VisionDescription(text="a cat", model="stub", confidence=0.8)

    async def extract_text(self, image: bytes, *, mime: str) -> OCRResult:
        block = OCRBlock(text="Hello", bbox=(0, 0, 10, 10), confidence=0.9)
        return OCRResult(text="Hello", blocks=(block,), confidence=0.9)

    async def detect(
        self,
        image: bytes,
        *,
        mime: str,
        categories: tuple[str, ...] | None = None,
    ) -> tuple[VisionDetection, ...]:
        return (
            VisionDetection(category="cat", bbox=(0, 0, 100, 100), confidence=0.85),
        )

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True


def test_stub_adapter_satisfies_protocol_runtime_checkable() -> None:
    assert isinstance(_StubVisionAdapter(), VisionPort)


def test_describe_returns_description_shape() -> None:
    adapter = _StubVisionAdapter()
    desc = asyncio.run(
        adapter.describe(b"\x00", mime="image/png", prompt=None)
    )
    assert isinstance(desc, VisionDescription)
    assert 0.0 <= desc.confidence <= 1.0
    assert desc.text
    assert desc.model


def test_extract_text_returns_ocr_result_shape() -> None:
    adapter = _StubVisionAdapter()
    result = asyncio.run(adapter.extract_text(b"\x00", mime="image/png"))
    assert isinstance(result, OCRResult)
    assert result.blocks
    for block in result.blocks:
        assert len(block.bbox) == 4
        assert 0.0 <= block.confidence <= 1.0


def test_detect_returns_tuple_of_detections() -> None:
    adapter = _StubVisionAdapter()
    detections = asyncio.run(
        adapter.detect(b"\x00", mime="image/png", categories=None)
    )
    assert isinstance(detections, tuple)
    for det in detections:
        assert isinstance(det, VisionDetection)
        assert len(det.bbox) == 4
        assert 0.0 <= det.confidence <= 1.0


def test_is_healthy_never_raises() -> None:
    adapter = _StubVisionAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False


def test_close_is_idempotent() -> None:
    adapter = _StubVisionAdapter()

    async def _run() -> None:
        await adapter.close()
        await adapter.close()

    asyncio.run(_run())
