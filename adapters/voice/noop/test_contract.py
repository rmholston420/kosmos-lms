"""Contract test — NoOpVoiceAdapter (ADR-097 D4)."""

from __future__ import annotations

import pytest

from adapters.voice import VoiceAdapterUnavailable
from adapters.voice.noop import NoOpVoiceAdapter
from ports.voice import AudioClip, Transcript, VoicePort


def test_isinstance_voice_port() -> None:
    assert isinstance(NoOpVoiceAdapter(), VoicePort)


@pytest.mark.asyncio
async def test_transcribe_returns_empty_transcript() -> None:
    adapter = NoOpVoiceAdapter()
    t = await adapter.transcribe(b"\x00" * 10, mime="audio/wav")
    assert isinstance(t, Transcript)
    assert t.text == ""
    assert t.confidence == 0.0
    assert t.language == "und"
    assert t.segments == ()


@pytest.mark.asyncio
async def test_synthesize_returns_silent_wav() -> None:
    adapter = NoOpVoiceAdapter()
    clip = await adapter.synthesize("hello")
    assert isinstance(clip, AudioClip)
    assert clip.mime == "audio/wav"
    assert clip.duration_s == pytest.approx(0.1)
    assert clip.bytes.startswith(b"RIFF") and b"WAVE" in clip.bytes[:12]
    assert len(clip.bytes) > 44  # header + at least 1 sample


@pytest.mark.asyncio
async def test_synthesize_honours_voice_arg() -> None:
    adapter = NoOpVoiceAdapter()
    clip = await adapter.synthesize("hi", voice="custom")
    assert clip.voice == "custom"


@pytest.mark.asyncio
async def test_list_voices_returns_noop_profile() -> None:
    profiles = await NoOpVoiceAdapter().list_voices()
    assert len(profiles) == 1
    assert profiles[0].voice_id == "noop"
    assert profiles[0].gender == "neutral"


def test_is_healthy_true_by_default() -> None:
    assert NoOpVoiceAdapter().is_healthy() is True


@pytest.mark.asyncio
async def test_close_makes_unhealthy_and_transcribe_raises() -> None:
    adapter = NoOpVoiceAdapter()
    await adapter.close()
    assert adapter.is_healthy() is False
    with pytest.raises(VoiceAdapterUnavailable):
        await adapter.transcribe(b"", mime="audio/wav")


@pytest.mark.asyncio
async def test_close_is_idempotent() -> None:
    adapter = NoOpVoiceAdapter()
    await adapter.close()
    await adapter.close()  # must not raise
    assert adapter.is_healthy() is False
