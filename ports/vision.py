"""ports.vision — VisionPort Protocol (ADR-084).

Formal Kosmos port for multimodal image ingest. Locked at Stage 6.5 (surface);
adapter selection separately locked at Stage 6.5. Candidates per
``kosmos-port-workflow``: LLaVA / Qwen2-VL via Ollama for
``describe`` / ``detect``; Tesseract for OCR-only paths.

Enforcement rules (per ADR-084 + spec §25.4):

1. Every call originating from a user-driven turn MUST write the **source
   image reference** (a content-addressed hash into ``adapters/data/`` blob
   storage — NOT the raw bytes) + the result to ``MemoryPort`` with
   ``provenance="tektos_frontend"`` and ``confidence`` passed through from
   the result.
2. Image bytes are stored in ``adapters/data/`` blob storage, keyed by their
   content hash; ``MemoryPort`` writes carry the hash only. This prevents
   large binaries from bloating the graph store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "OCRBlock",
    "OCRResult",
    "VisionDescription",
    "VisionDetection",
    "VisionPort",
]


@dataclass(frozen=True, slots=True)
class VisionDescription:
    """Immutable free-text description produced by a multimodal model."""

    text: str
    model: str
    confidence: float


@dataclass(frozen=True, slots=True)
class OCRBlock:
    """One OCR-detected text block with bounding box. Immutable.

    ``bbox`` is ``(x, y, w, h)`` in pixel coordinates.
    """

    text: str
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True, slots=True)
class OCRResult:
    """Immutable OCR result.

    ``text`` is the full concatenated text; ``blocks`` preserves layout.
    """

    text: str
    blocks: tuple[OCRBlock, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class VisionDetection:
    """One detected object/region. Immutable. ``bbox`` = ``(x, y, w, h)``."""

    category: str
    bbox: tuple[int, int, int, int]
    confidence: float


@runtime_checkable
class VisionPort(Protocol):
    """Formal Kosmos contract for multimodal image ingest."""

    # ── Description / OCR / detection ─────────────────────────────────────

    async def describe(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> VisionDescription:
        """Return a free-text description of ``image``.

        ``prompt`` is an optional biasing prompt to steer the description.
        """
        ...

    async def extract_text(
        self,
        image: bytes,
        *,
        mime: str,
    ) -> OCRResult:
        """OCR text out of ``image``, preserving block layout."""
        ...

    async def detect(
        self,
        image: bytes,
        *,
        mime: str,
        categories: tuple[str, ...] | None = None,
    ) -> tuple[VisionDetection, ...]:
        """Detect objects/regions in ``image``.

        ``categories=None`` means "detect everything the model knows";
        a tuple restricts detection to those category labels.
        """
        ...

    # ── Health & lifecycle ────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Return True iff the adapter can serve calls. Non-throwing."""
        ...

    async def close(self) -> None:
        """Release adapter resources. Idempotent."""
        ...
