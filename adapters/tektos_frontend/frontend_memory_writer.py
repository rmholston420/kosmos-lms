"""TektosFrontendMemoryWriter — implements ADR-096 D1 two-write pattern.

Every user-driven VoicePort.transcribe / VisionPort.describe /
VisionPort.extract_text / VisionPort.detect call fans out into two
MemoryPort.write_event calls:

1. Ingest triple  — subject=<kosmos://blob/<sha>>, predicate=
   "tektos_frontend.ingested", object=<mime>, confidence=1.0 (per §25.4).
2. Result triple  — subject=<kosmos://blob/<sha>>, predicate=<verb>,
   object=<summary>, confidence=<result.confidence> (per ADR-083/084
   passthrough).

Bytes land in the BlobStore, not in MemoryPort (per ADR-084 rule 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from adapters.data.blobs import BlobStore, kosmos_blob_uri

if TYPE_CHECKING:
    from ports.memory import MemoryEventId, MemoryPort
    from ports.vision import OCRResult, VisionDescription, VisionDetection
    from ports.voice import Transcript


__all__ = [
    "TektosFrontendMemoryWriter",
    "VoiceIngest",
    "VisionIngest",
]


_PROVENANCE = "tektos_frontend"
_INGEST_PREDICATE = "tektos_frontend.ingested"
_VOICE_RESULT_PREDICATE = "tektos_frontend.transcribed"
_VISION_DESCRIBE_PREDICATE = "tektos_frontend.described"
_VISION_OCR_PREDICATE = "tektos_frontend.extracted_text"
_VISION_DETECT_PREDICATE = "tektos_frontend.detected"


@dataclass(frozen=True, slots=True)
class VoiceIngest:
    """Return value from record_voice — the two MemoryEventIds + blob URI."""

    ingest_event: "MemoryEventId"
    result_event: "MemoryEventId"
    blob_uri: str
    sha256: str


@dataclass(frozen=True, slots=True)
class VisionIngest:
    """Return value from record_vision_* — the two MemoryEventIds + blob URI."""

    ingest_event: "MemoryEventId"
    result_event: "MemoryEventId"
    blob_uri: str
    sha256: str
    result_attributes: dict[str, Any] = field(default_factory=dict)


def _summarize_ocr(result: "OCRResult") -> str:
    """Return a compact one-line summary of an OCRResult (never raw bytes)."""
    text = (result.text or "").strip().replace("\n", " ")
    if len(text) <= 256:
        return text
    return text[:253] + "..."


def _summarize_detections(detections: "tuple[VisionDetection, ...]") -> str:
    """Return a compact summary: 'cat×2, dog×1' style, capped at 256 chars."""
    if not detections:
        return "no detections"
    counts: dict[str, int] = {}
    for d in detections:
        counts[d.category] = counts.get(d.category, 0) + 1
    parts = [f"{cat}\u00d7{n}" for cat, n in sorted(counts.items())]
    summary = ", ".join(parts)
    if len(summary) <= 256:
        return summary
    return summary[:253] + "..."


class TektosFrontendMemoryWriter:
    """Writer that owns the two-write pattern (ADR-096 D1).

    Injected with a MemoryPort adapter and a BlobStore. Callers (voice /
    vision adapters) hand it (audio-or-image bytes + mime + result) and it
    handles the blob-store put + the two MemoryPort.write_event calls.
    """

    def __init__(
        self,
        *,
        memory: "MemoryPort",
        blobs: BlobStore,
    ) -> None:
        self._memory = memory
        self._blobs = blobs

    # ------------------------------------------------------------------
    # Voice
    # ------------------------------------------------------------------

    async def record_voice(
        self,
        *,
        audio: bytes,
        mime: str,
        transcript: "Transcript",
    ) -> VoiceIngest:
        """Persist the audio blob + write the two MemoryPort triples."""
        sha = self._blobs.put_bytes(audio)
        uri = kosmos_blob_uri(sha)

        ingest_event = await self._memory.write_event(
            uri,
            _INGEST_PREDICATE,
            mime,
            provenance=_PROVENANCE,
            confidence=1.0,
            attributes={
                "kind": "voice",
                "sha256": sha,
                "byte_len": len(audio),
                "mime": mime,
            },
        )

        text_object = transcript.text if len(transcript.text) <= 4096 else transcript.text[:4093] + "..."
        result_event = await self._memory.write_event(
            uri,
            _VOICE_RESULT_PREDICATE,
            text_object,
            provenance=_PROVENANCE,
            confidence=float(transcript.confidence),
            attributes={
                "kind": "voice_transcript",
                "language": transcript.language,
                "segment_count": len(transcript.segments),
                "sha256": sha,
            },
        )

        return VoiceIngest(
            ingest_event=ingest_event,
            result_event=result_event,
            blob_uri=uri,
            sha256=sha,
        )

    # ------------------------------------------------------------------
    # Vision
    # ------------------------------------------------------------------

    async def record_vision_description(
        self,
        *,
        image: bytes,
        mime: str,
        description: "VisionDescription",
    ) -> VisionIngest:
        sha = self._blobs.put_bytes(image)
        uri = kosmos_blob_uri(sha)

        ingest_event = await self._memory.write_event(
            uri,
            _INGEST_PREDICATE,
            mime,
            provenance=_PROVENANCE,
            confidence=1.0,
            attributes={
                "kind": "vision",
                "sha256": sha,
                "byte_len": len(image),
                "mime": mime,
            },
        )

        text_object = (
            description.text
            if len(description.text) <= 4096
            else description.text[:4093] + "..."
        )
        attrs = {
            "kind": "vision_description",
            "model": description.model,
            "sha256": sha,
        }
        result_event = await self._memory.write_event(
            uri,
            _VISION_DESCRIBE_PREDICATE,
            text_object,
            provenance=_PROVENANCE,
            confidence=float(description.confidence),
            attributes=attrs,
        )

        return VisionIngest(
            ingest_event=ingest_event,
            result_event=result_event,
            blob_uri=uri,
            sha256=sha,
            result_attributes=attrs,
        )

    async def record_vision_ocr(
        self,
        *,
        image: bytes,
        mime: str,
        ocr: "OCRResult",
    ) -> VisionIngest:
        sha = self._blobs.put_bytes(image)
        uri = kosmos_blob_uri(sha)

        ingest_event = await self._memory.write_event(
            uri,
            _INGEST_PREDICATE,
            mime,
            provenance=_PROVENANCE,
            confidence=1.0,
            attributes={
                "kind": "vision",
                "sha256": sha,
                "byte_len": len(image),
                "mime": mime,
            },
        )

        attrs = {
            "kind": "vision_ocr",
            "block_count": len(ocr.blocks),
            "sha256": sha,
        }
        result_event = await self._memory.write_event(
            uri,
            _VISION_OCR_PREDICATE,
            _summarize_ocr(ocr),
            provenance=_PROVENANCE,
            confidence=float(ocr.confidence),
            attributes=attrs,
        )

        return VisionIngest(
            ingest_event=ingest_event,
            result_event=result_event,
            blob_uri=uri,
            sha256=sha,
            result_attributes=attrs,
        )

    async def record_vision_detections(
        self,
        *,
        image: bytes,
        mime: str,
        detections: "tuple[VisionDetection, ...]",
        model: str,
    ) -> VisionIngest:
        sha = self._blobs.put_bytes(image)
        uri = kosmos_blob_uri(sha)

        ingest_event = await self._memory.write_event(
            uri,
            _INGEST_PREDICATE,
            mime,
            provenance=_PROVENANCE,
            confidence=1.0,
            attributes={
                "kind": "vision",
                "sha256": sha,
                "byte_len": len(image),
                "mime": mime,
            },
        )

        # Aggregate confidence: mean of per-detection confidences (empty → 0.0).
        if detections:
            agg = sum(float(d.confidence) for d in detections) / len(detections)
        else:
            agg = 0.0
        # Guard against float drift outside [0.0, 1.0].
        agg = max(0.0, min(1.0, agg))

        attrs = {
            "kind": "vision_detections",
            "model": model,
            "detection_count": len(detections),
            "sha256": sha,
        }
        result_event = await self._memory.write_event(
            uri,
            _VISION_DETECT_PREDICATE,
            _summarize_detections(detections),
            provenance=_PROVENANCE,
            confidence=agg,
            attributes=attrs,
        )

        return VisionIngest(
            ingest_event=ingest_event,
            result_event=result_event,
            blob_uri=uri,
            sha256=sha,
            result_attributes=attrs,
        )
