"""NoOpVoiceAdapter — protocol-conforming VoicePort with placeholder outputs.

Required by CI so tests don't need to load a real Whisper model. Also used
as the TTS fallback until the Stage 6.5+1 TTS-engine ADR lands (ADR-097 D3).
"""

from __future__ import annotations

import struct

from ports.voice import (
    AudioClip,
    Transcript,
    VoiceProfile,
)

__all__ = ["NoOpVoiceAdapter"]


def _silent_wav_bytes(duration_s: float = 0.1, sample_rate: int = 8000) -> bytes:
    """Return a valid 8-bit-mono silent WAV of `duration_s` seconds.

    WAV format: 44-byte RIFF header + PCM audio (all 0x80 = mid-scale silence
    for unsigned 8-bit PCM).
    """
    num_samples = max(1, int(duration_s * sample_rate))
    pcm = b"\x80" * num_samples
    data_size = len(pcm)
    fmt_chunk_size = 16
    riff_size = 4 + (8 + fmt_chunk_size) + (8 + data_size)
    header = (
        b"RIFF"
        + struct.pack("<I", riff_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", fmt_chunk_size)
        + struct.pack("<H", 1)                # PCM
        + struct.pack("<H", 1)                # mono
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", sample_rate)      # byte rate
        + struct.pack("<H", 1)                # block align
        + struct.pack("<H", 8)                # bits/sample
        + b"data"
        + struct.pack("<I", data_size)
    )
    return header + pcm


class NoOpVoiceAdapter:
    """Protocol-conforming VoicePort adapter returning placeholder results.

    Satisfies ``isinstance(NoOpVoiceAdapter(), VoicePort)``.
    """

    def __init__(self) -> None:
        self._closed = False
        self._silent = _silent_wav_bytes(duration_s=0.1)

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        hint: str | None = None,
    ) -> Transcript:
        if self._closed:
            from adapters.voice import VoiceAdapterUnavailable
            raise VoiceAdapterUnavailable("NoOpVoiceAdapter is closed")
        return Transcript(text="", confidence=0.0, language="und", segments=())

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
    ) -> AudioClip:
        if self._closed:
            from adapters.voice import VoiceAdapterUnavailable
            raise VoiceAdapterUnavailable("NoOpVoiceAdapter is closed")
        return AudioClip(
            bytes=self._silent,
            mime="audio/wav",
            duration_s=0.1,
            voice=voice or "noop",
        )

    async def list_voices(self) -> tuple[VoiceProfile, ...]:
        return (
            VoiceProfile(
                voice_id="noop",
                name="No-op",
                language="und",
                gender="neutral",
            ),
        )

    def is_healthy(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True
