"""Contract test for TektosFrontendMemoryWriter (ADR-096 D1 two-write pattern)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from adapters.data.blobs import BlobStore, kosmos_blob_uri, sha256_of
from adapters.tektos_frontend import (
    TektosFrontendMemoryWriter,
    VisionIngest,
    VoiceIngest,
)
from ports.memory import MemoryEventId
from ports.vision import (
    OCRBlock,
    OCRResult,
    VisionDescription,
    VisionDetection,
)
from ports.voice import Transcript, TranscriptSegment


class _StubMemory:
    """Minimal MemoryPort test double capturing every write_event call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._counter = 0

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        source_citation: str | None = None,
        pii_tier: str = "Public",
        attributes: dict[str, Any] | None = None,
    ) -> MemoryEventId:
        self._counter += 1
        self.calls.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "provenance": provenance,
                "confidence": confidence,
                "source_citation": source_citation,
                "pii_tier": pii_tier,
                "attributes": attributes,
            }
        )
        return MemoryEventId(id=f"mem-{self._counter}", written_at=datetime.now(timezone.utc))


# ------------------------------------------------------------------ voice


@pytest.mark.asyncio
async def test_record_voice_writes_two_events_with_correct_shape(
    tmp_path: Path,
) -> None:
    mem = _StubMemory()
    blobs = BlobStore(root=tmp_path)
    writer = TektosFrontendMemoryWriter(memory=mem, blobs=blobs)

    audio = b"\x00" * 100
    transcript = Transcript(
        text="hello world",
        confidence=0.87,
        language="en",
        segments=(
            TranscriptSegment(start_s=0.0, end_s=1.0, text="hello world", confidence=0.87),
        ),
    )

    result: VoiceIngest = await writer.record_voice(
        audio=audio, mime="audio/wav", transcript=transcript
    )

    assert len(mem.calls) == 2
    ingest, res = mem.calls
    expected_sha = sha256_of(audio)
    expected_uri = kosmos_blob_uri(expected_sha)

    # Ingest triple
    assert ingest["subject"] == expected_uri
    assert ingest["predicate"] == "tektos_frontend.ingested"
    assert ingest["object"] == "audio/wav"
    assert ingest["provenance"] == "tektos_frontend"
    assert ingest["confidence"] == 1.0
    assert ingest["attributes"]["kind"] == "voice"
    assert ingest["attributes"]["sha256"] == expected_sha
    assert ingest["attributes"]["byte_len"] == 100

    # Result triple — confidence passthrough per ADR-083 rule 1
    assert res["subject"] == expected_uri
    assert res["predicate"] == "tektos_frontend.transcribed"
    assert res["object"] == "hello world"
    assert res["provenance"] == "tektos_frontend"
    assert res["confidence"] == pytest.approx(0.87)
    assert res["attributes"]["kind"] == "voice_transcript"
    assert res["attributes"]["language"] == "en"
    assert res["attributes"]["segment_count"] == 1

    # Return object
    assert result.sha256 == expected_sha
    assert result.blob_uri == expected_uri
    assert result.ingest_event.id == "mem-1"
    assert result.result_event.id == "mem-2"

    # Blob actually landed on disk
    assert blobs.open_path(expected_sha).read_bytes() == audio


@pytest.mark.asyncio
async def test_record_voice_truncates_very_long_transcript(tmp_path: Path) -> None:
    mem = _StubMemory()
    blobs = BlobStore(root=tmp_path)
    writer = TektosFrontendMemoryWriter(memory=mem, blobs=blobs)

    long_text = "x" * 5000
    transcript = Transcript(text=long_text, confidence=0.5, language="en", segments=())
    await writer.record_voice(audio=b"a", mime="audio/wav", transcript=transcript)

    res_object = mem.calls[1]["object"]
    assert len(res_object) == 4096
    assert res_object.endswith("...")


# ------------------------------------------------------------------ vision describe


@pytest.mark.asyncio
async def test_record_vision_description_writes_two_events(tmp_path: Path) -> None:
    mem = _StubMemory()
    blobs = BlobStore(root=tmp_path)
    writer = TektosFrontendMemoryWriter(memory=mem, blobs=blobs)

    image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    desc = VisionDescription(text="a cat sitting on a mat", model="qwen2.5-vl:7b", confidence=0.5)

    result = await writer.record_vision_description(
        image=image, mime="image/png", description=desc
    )

    assert len(mem.calls) == 2
    ingest, res = mem.calls
    expected_sha = sha256_of(image)

    assert ingest["predicate"] == "tektos_frontend.ingested"
    assert ingest["confidence"] == 1.0
    assert ingest["attributes"]["kind"] == "vision"
    assert ingest["object"] == "image/png"

    assert res["predicate"] == "tektos_frontend.described"
    assert res["object"] == "a cat sitting on a mat"
    assert res["confidence"] == pytest.approx(0.5)
    assert res["attributes"]["kind"] == "vision_description"
    assert res["attributes"]["model"] == "qwen2.5-vl:7b"

    assert result.sha256 == expected_sha


# ------------------------------------------------------------------ vision OCR


@pytest.mark.asyncio
async def test_record_vision_ocr_writes_two_events_and_summarizes(tmp_path: Path) -> None:
    mem = _StubMemory()
    blobs = BlobStore(root=tmp_path)
    writer = TektosFrontendMemoryWriter(memory=mem, blobs=blobs)

    image = b"\xff\xd8\xff" + b"\x00" * 20
    ocr = OCRResult(
        text="Hello\nWorld\nAgain",
        blocks=(
            OCRBlock(text="Hello", bbox=(0, 0, 10, 10), confidence=0.9),
            OCRBlock(text="World", bbox=(0, 20, 10, 10), confidence=0.8),
            OCRBlock(text="Again", bbox=(0, 40, 10, 10), confidence=0.7),
        ),
        confidence=0.8,
    )

    result = await writer.record_vision_ocr(image=image, mime="image/jpeg", ocr=ocr)

    assert len(mem.calls) == 2
    ingest, res = mem.calls

    assert ingest["predicate"] == "tektos_frontend.ingested"
    assert ingest["confidence"] == 1.0

    assert res["predicate"] == "tektos_frontend.extracted_text"
    # Newlines collapsed to spaces per _summarize_ocr
    assert res["object"] == "Hello World Again"
    assert res["confidence"] == pytest.approx(0.8)
    assert res["attributes"]["kind"] == "vision_ocr"
    assert res["attributes"]["block_count"] == 3

    assert result.sha256 == sha256_of(image)


# ------------------------------------------------------------------ vision detect


@pytest.mark.asyncio
async def test_record_vision_detections_aggregates_confidence(tmp_path: Path) -> None:
    mem = _StubMemory()
    blobs = BlobStore(root=tmp_path)
    writer = TektosFrontendMemoryWriter(memory=mem, blobs=blobs)

    image = b"\x00" * 32
    detections = (
        VisionDetection(category="cat", bbox=(0, 0, 10, 10), confidence=0.9),
        VisionDetection(category="cat", bbox=(20, 20, 10, 10), confidence=0.7),
        VisionDetection(category="dog", bbox=(40, 40, 10, 10), confidence=0.8),
    )

    await writer.record_vision_detections(
        image=image, mime="image/png", detections=detections, model="qwen2.5-vl:7b"
    )

    assert len(mem.calls) == 2
    res = mem.calls[1]
    # Mean of 0.9, 0.7, 0.8 == 0.8
    assert res["confidence"] == pytest.approx(0.8)
    # Summary: cat×2, dog×1
    assert res["object"] == "cat\u00d72, dog\u00d71"
    assert res["attributes"]["detection_count"] == 3
    assert res["attributes"]["model"] == "qwen2.5-vl:7b"


@pytest.mark.asyncio
async def test_record_vision_detections_empty_confidence_zero(tmp_path: Path) -> None:
    mem = _StubMemory()
    blobs = BlobStore(root=tmp_path)
    writer = TektosFrontendMemoryWriter(memory=mem, blobs=blobs)

    await writer.record_vision_detections(
        image=b"\x00", mime="image/png", detections=(), model="qwen2.5-vl:7b"
    )

    res = mem.calls[1]
    assert res["confidence"] == 0.0
    assert res["object"] == "no detections"
    assert res["attributes"]["detection_count"] == 0


# ------------------------------------------------------------------ blob dedup


@pytest.mark.asyncio
async def test_record_voice_dedupes_identical_bytes(tmp_path: Path) -> None:
    mem = _StubMemory()
    blobs = BlobStore(root=tmp_path)
    writer = TektosFrontendMemoryWriter(memory=mem, blobs=blobs)

    audio = b"same-audio"
    transcript = Transcript(text="x", confidence=0.5, language="en", segments=())

    r1 = await writer.record_voice(audio=audio, mime="audio/wav", transcript=transcript)
    r2 = await writer.record_voice(audio=audio, mime="audio/wav", transcript=transcript)

    assert r1.sha256 == r2.sha256
    assert r1.blob_uri == r2.blob_uri
    # Two calls each emit 2 events = 4 total
    assert len(mem.calls) == 4
