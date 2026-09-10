"""TesseractVisionAdapter — OCR-only VisionPort adapter (ADR-098 D1).

Wraps ``pytesseract`` (Apache-2.0). Requires the system ``tesseract-ocr``
binary. ``describe`` and ``detect`` raise ``VisionCapabilityUnsupported``.
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Any

from adapters.vision import VisionAdapterUnavailable, VisionCapabilityUnsupported
from ports.vision import (
    OCRBlock,
    OCRResult,
    VisionDescription,
    VisionDetection,
)

__all__ = ["TesseractVisionAdapter"]


class TesseractVisionAdapter:
    """Async wrapper around pytesseract / tesseract-ocr.

    Loads lazily; the constructor never raises. Use ``is_healthy()`` to
    check whether the binary + Python bindings are actually available.
    """

    def __init__(self, *, tesseract_cmd: str | None = None) -> None:
        self._closed = False
        self._tesseract_cmd = tesseract_cmd or os.environ.get("KOSMOS_TESSERACT_CMD")

    async def describe(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> VisionDescription:
        raise VisionCapabilityUnsupported(
            "TesseractVisionAdapter is OCR-only — use OllamaQwenVLVisionAdapter "
            "for describe/detect. See ADR-098 D2."
        )

    async def detect(
        self,
        image: bytes,
        *,
        mime: str,
        categories: tuple[str, ...] | None = None,
    ) -> tuple[VisionDetection, ...]:
        raise VisionCapabilityUnsupported(
            "TesseractVisionAdapter is OCR-only — use OllamaQwenVLVisionAdapter "
            "for describe/detect. See ADR-098 D2."
        )

    async def extract_text(
        self,
        image: bytes,
        *,
        mime: str,
    ) -> OCRResult:
        self._require_open()
        if not isinstance(image, (bytes, bytearray)) or not image:
            raise ValueError("VisionPort image argument must be non-empty bytes")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._extract_sync, bytes(image))

    def _extract_sync(self, image: bytes) -> OCRResult:
        try:
            import pytesseract  # type: ignore[import-untyped]
            from PIL import Image  # type: ignore[import-untyped]
        except ImportError as exc:
            raise VisionAdapterUnavailable(
                "TesseractVisionAdapter requires pytesseract + Pillow. "
                "Install with: pip install pytesseract Pillow"
            ) from exc

        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        try:
            with Image.open(io.BytesIO(image)) as img:
                img.load()
                data = pytesseract.image_to_data(
                    img, output_type=pytesseract.Output.DICT
                )
        except Exception as exc:  # noqa: BLE001
            raise VisionAdapterUnavailable(
                f"Tesseract extract_text failed ({type(exc).__name__}: {exc})"
            ) from exc

        blocks: list[OCRBlock] = []
        confidences: list[float] = []
        texts_line: list[str] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = str(data["text"][i]).strip()
            try:
                conf_raw = float(data["conf"][i])
            except (TypeError, ValueError):
                conf_raw = -1.0
            if not text or conf_raw < 0:
                continue
            conf = max(0.0, min(1.0, conf_raw / 100.0))
            try:
                x = int(data["left"][i])
                y = int(data["top"][i])
                w = int(data["width"][i])
                h = int(data["height"][i])
            except (TypeError, ValueError, KeyError):
                continue
            blocks.append(OCRBlock(text=text, bbox=(x, y, w, h), confidence=conf))
            confidences.append(conf)
            texts_line.append(text)

        aggregate = (sum(confidences) / len(confidences)) if confidences else 0.0
        return OCRResult(
            text=" ".join(texts_line).strip(),
            blocks=tuple(blocks),
            confidence=aggregate,
        )

    def is_healthy(self) -> bool:
        if self._closed:
            return False
        try:
            import pytesseract  # type: ignore[import-untyped]

            if self._tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd
            pytesseract.get_tesseract_version()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        self._closed = True

    # -----------------------------------------------------------------
    def _require_open(self) -> None:
        if self._closed:
            raise VisionAdapterUnavailable("TesseractVisionAdapter is closed")


# unused imports guard
_ = Any
