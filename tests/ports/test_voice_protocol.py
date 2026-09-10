"""Protocol conformance test for VoicePort (ADR-083).

Any adapter satisfying ``VoicePort`` MUST pass this test. Fast tier — no
Whisper.cpp, no Piper. Uses a stub adapter that returns fixed transcripts.
"""

from __future__ import annotations

import asyncio

from ports.voice import (
    AudioClip,
    Transcript,
    TranscriptSegment,
    VoicePort,
    VoiceProfile,
)


class _StubVoiceAdapter:
    """Minimal VoicePort implementation used only for protocol tests."""

    def __init__(self) -> None:
        self._closed = False

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        hint: str | None = None,
    ) -> Transcript:
        return Transcript(
            text="hello",
            confidence=0.95,
            language="en",
            segments=(
                TranscriptSegment(start_s=0.0, end_s=0.5, text="hello", confidence=0.95),
            ),
        )

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
    ) -> AudioClip:
        return AudioClip(
            bytes=b"\x00\x00",
            mime="audio/wav",
            duration_s=0.1,
            voice=voice or "default",
        )

    async def list_voices(self) -> tuple[VoiceProfile, ...]:
        return (
            VoiceProfile(voice_id="default", name="Default", language="en", gender="neutral"),
        )

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True


def test_stub_adapter_satisfies_protocol_runtime_checkable() -> None:
    assert isinstance(_StubVoiceAdapter(), VoicePort)


def test_transcribe_returns_transcript_shape() -> None:
    adapter = _StubVoiceAdapter()
    transcript = asyncio.run(
        adapter.transcribe(b"\x00", mime="audio/wav", hint=None)
    )
    assert isinstance(transcript, Transcript)
    assert 0.0 <= transcript.confidence <= 1.0
    assert transcript.segments
    for seg in transcript.segments:
        assert seg.end_s >= seg.start_s
        assert 0.0 <= seg.confidence <= 1.0


def test_synthesize_returns_audio_clip_shape() -> None:
    adapter = _StubVoiceAdapter()
    clip = asyncio.run(adapter.synthesize("hi", voice="default"))
    assert isinstance(clip, AudioClip)
    assert clip.mime.startswith("audio/")
    assert clip.duration_s >= 0.0


def test_list_voices_returns_tuple() -> None:
    adapter = _StubVoiceAdapter()
    voices = asyncio.run(adapter.list_voices())
    assert isinstance(voices, tuple)
    assert all(isinstance(v, VoiceProfile) for v in voices)


def test_is_healthy_never_raises() -> None:
    adapter = _StubVoiceAdapter()
    assert adapter.is_healthy() is True
    asyncio.run(adapter.close())
    assert adapter.is_healthy() is False


def test_close_is_idempotent() -> None:
    adapter = _StubVoiceAdapter()

    async def _run() -> None:
        await adapter.close()
        await adapter.close()

    asyncio.run(_run())
