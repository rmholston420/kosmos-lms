"""ports.voice — VoicePort Protocol (ADR-083).

Formal Kosmos port for speech-to-text + text-to-speech. Locked at Stage 6.5
(surface); adapter selection separately locked at Stage 6.5. Candidates per
``kosmos-port-workflow``: Whisper.cpp + Piper primary; alternatives
faster-whisper + Coqui TTS.

Enforcement rules (per ADR-083 + spec §25.4):

1. ``transcribe()`` results MUST be written to ``MemoryPort`` when originating
   from a user-driven turn, with ``provenance="tektos_frontend"`` and
   ``confidence=Transcript.confidence`` (passthrough).
2. ``synthesize()`` does NOT write to ``MemoryPort`` (side-effect only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "AudioClip",
    "Transcript",
    "TranscriptSegment",
    "VoiceGender",
    "VoicePort",
    "VoiceProfile",
]


VoiceGender = Literal["neutral", "masculine", "feminine"]


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """One time-bounded segment of a transcript. Immutable."""

    start_s: float
    end_s: float
    text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class Transcript:
    """Immutable STT result.

    ``confidence`` is the aggregate for the full utterance; per-segment
    confidences live in ``segments``. Aggregate is the value passed to
    ``MemoryPort`` write per spec §25.4.
    """

    text: str
    confidence: float
    language: str
    segments: tuple[TranscriptSegment, ...]


@dataclass(frozen=True, slots=True)
class AudioClip:
    """Immutable TTS output."""

    bytes: bytes
    mime: str
    duration_s: float
    voice: str


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Metadata for one available TTS voice."""

    voice_id: str
    name: str
    language: str
    gender: VoiceGender


@runtime_checkable
class VoicePort(Protocol):
    """Formal Kosmos contract for speech I/O."""

    # ── STT ───────────────────────────────────────────────────────────────

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        hint: str | None = None,
    ) -> Transcript:
        """Transcribe ``audio`` (raw bytes with declared ``mime``).

        ``hint`` is an optional biasing prompt (e.g. the current UI context).
        """
        ...

    # ── TTS ───────────────────────────────────────────────────────────────

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
    ) -> AudioClip:
        """Synthesize ``text`` as speech. ``voice=None`` uses the adapter default.
        """
        ...

    async def list_voices(self) -> tuple[VoiceProfile, ...]:
        """Return every voice available in this adapter."""
        ...

    # ── Health & lifecycle ────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Return True iff the adapter can serve calls. Non-throwing."""
        ...

    async def close(self) -> None:
        """Release adapter resources. Idempotent."""
        ...
