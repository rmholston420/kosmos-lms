"""NoOpVisionAdapter — protocol-conforming VisionPort with placeholder outputs.

Required for CI and for composing tests that need a VisionPort without
hitting Ollama or Tesseract (ADR-098 D1).
"""

from __future__ import annotations

from ports.vision import (
    OCRResult,
    VisionDescription,
    VisionDetection,
)

__all__ = ["NoOpVisionAdapter"]


class NoOpVisionAdapter:
    """Protocol-conforming VisionPort adapter — placeholder results only.

    Satisfies ``isinstance(NoOpVisionAdapter(), VisionPort)``.
    """

    def __init__(self) -> None:
        self._closed = False

    async def describe(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> VisionDescription:
        self._require_open()
        return VisionDescription(text="", model="noop", confidence=0.0)

    async def extract_text(
        self,
        image: bytes,
        *,
        mime: str,
    ) -> OCRResult:
        self._require_open()
        return OCRResult(text="", blocks=(), confidence=0.0)

    async def detect(
        self,
        image: bytes,
        *,
        mime: str,
        categories: tuple[str, ...] | None = None,
    ) -> tuple[VisionDetection, ...]:
        self._require_open()
        return ()

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True

    # -----------------------------------------------------------------
    def _require_open(self) -> None:
        if self._closed:
            from adapters.vision import VisionAdapterUnavailable
            raise VisionAdapterUnavailable("NoOpVisionAdapter is closed")
