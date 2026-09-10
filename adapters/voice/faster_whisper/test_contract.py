"""Contract test — FasterWhisperVoiceAdapter (ADR-097 D1).

Uses stubbed model attributes. Does NOT load a real Whisper model.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from adapters.voice import TTSNotConfigured, VoiceAdapterUnavailable
from adapters.voice.faster_whisper import FasterWhisperVoiceAdapter
from ports.voice import Transcript, VoicePort


class _StubSegment:
    def __init__(self, start: float, end: float, text: str, avg_logprob: float = -0.2) -> None:
        self.start = start
        self.end = end
        self.text = text
        self.avg_logprob = avg_logprob


class _StubInfo:
    def __init__(self, language: str = "en") -> None:
        self.language = language


class _StubModel:
    def __init__(self, segments: list[_StubSegment], language: str = "en") -> None:
        self._segments = segments
        self._language = language

    def transcribe(self, path: str, **kwargs: Any):  # noqa: ANN401
        return iter(self._segments), _StubInfo(self._language)


@pytest.fixture()
def stubbed_adapter(monkeypatch: pytest.MonkeyPatch) -> FasterWhisperVoiceAdapter:
    """Adapter whose model is a stub — no real Whisper loaded."""
    # Provide a fake faster_whisper module so __init__ succeeds even if the
    # real package isn't installed.
    fake = types.ModuleType("faster_whisper")

    class _FakeWhisperModel:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    fake.WhisperModel = _FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", fake)

    adapter = FasterWhisperVoiceAdapter(model_name="test-model", device="cpu", compute_type="int8")
    # Swap in the deterministic stub post-construction.
    adapter._model = _StubModel(  # type: ignore[assignment]
        segments=[
            _StubSegment(0.0, 1.5, "hello", avg_logprob=-0.1),
            _StubSegment(1.5, 3.0, "world", avg_logprob=-0.3),
        ],
        language="en",
    )
    return adapter


def test_isinstance_voice_port(stubbed_adapter: FasterWhisperVoiceAdapter) -> None:
    assert isinstance(stubbed_adapter, VoicePort)


@pytest.mark.asyncio
async def test_transcribe_returns_well_formed_transcript(
    stubbed_adapter: FasterWhisperVoiceAdapter,
) -> None:
    audio = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40
    t = await stubbed_adapter.transcribe(audio, mime="audio/wav")
    assert isinstance(t, Transcript)
    assert t.text == "hello world"
    assert 0.0 <= t.confidence <= 1.0
    assert t.language == "en"
    assert len(t.segments) == 2
    for seg in t.segments:
        assert 0.0 <= seg.confidence <= 1.0
        assert seg.end_s >= seg.start_s


@pytest.mark.asyncio
async def test_synthesize_raises_tts_not_configured(
    stubbed_adapter: FasterWhisperVoiceAdapter,
) -> None:
    with pytest.raises(TTSNotConfigured) as exc:
        await stubbed_adapter.synthesize("hello")
    assert "ADR-097" in str(exc.value)


@pytest.mark.asyncio
async def test_list_voices_empty(stubbed_adapter: FasterWhisperVoiceAdapter) -> None:
    voices = await stubbed_adapter.list_voices()
    assert voices == ()


def test_is_healthy_true_when_model_loaded(stubbed_adapter: FasterWhisperVoiceAdapter) -> None:
    assert stubbed_adapter.is_healthy() is True


@pytest.mark.asyncio
async def test_close_makes_unhealthy_and_transcribe_raises(
    stubbed_adapter: FasterWhisperVoiceAdapter,
) -> None:
    await stubbed_adapter.close()
    assert stubbed_adapter.is_healthy() is False
    with pytest.raises(VoiceAdapterUnavailable):
        await stubbed_adapter.transcribe(b"\x00", mime="audio/wav")


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_audio(
    stubbed_adapter: FasterWhisperVoiceAdapter,
) -> None:
    with pytest.raises(ValueError):
        await stubbed_adapter.transcribe(b"", mime="audio/wav")


def test_is_healthy_false_when_dep_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When faster_whisper import fails, adapter reports unhealthy, not crash."""
    import sys
    # Ensure the real / any cached faster_whisper is invisible for this test.
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    adapter = FasterWhisperVoiceAdapter(model_name="x", device="cpu", compute_type="int8")
    assert adapter.is_healthy() is False


@pytest.mark.asyncio
async def test_transcribe_raises_when_dep_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    adapter = FasterWhisperVoiceAdapter(model_name="x", device="cpu", compute_type="int8")
    with pytest.raises(VoiceAdapterUnavailable):
        await adapter.transcribe(b"abc", mime="audio/wav")
