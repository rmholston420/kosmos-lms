"""FasterWhisperVoiceAdapter — Stage 6.5 STT adapter (ADR-097 D1).

Backs ``VoicePort.transcribe`` via SYSTRAN/faster-whisper (MIT). TTS is
deliberately deferred to a Stage 6.5+1 ADR; ``synthesize`` raises
``TTSNotConfigured`` (ADR-097 D3).

Model / device / compute-type are all env-overridable so the same adapter
serves Colossus (CPU, int8, large-v3-turbo) and lighter environments
without a source edit.

Design lineage: donor ``src/tektos/voice.py`` (upstream commit
``2b45cac1f9ac214c85ff53571b949445b5415209``) — behaviour is vendored,
not code; see ``PORTING_LEDGER.md``.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
from pathlib import Path
from typing import Any

from adapters.voice import TTSNotConfigured, VoiceAdapterUnavailable
from ports.voice import (
    AudioClip,
    Transcript,
    TranscriptSegment,
    VoiceProfile,
)

__all__ = ["FasterWhisperVoiceAdapter"]


def _default_model_name() -> str:
    return os.environ.get("KOSMOS_WHISPER_MODEL", "large-v3-turbo")


def _default_device() -> str:
    return os.environ.get("KOSMOS_WHISPER_DEVICE", "cpu")


def _default_compute_type() -> str:
    return os.environ.get("KOSMOS_WHISPER_COMPUTE_TYPE", "int8")


class FasterWhisperVoiceAdapter:
    """Async wrapper around a ``faster_whisper.WhisperModel``.

    Model loading is eager in ``__init__`` so ``is_healthy`` reflects reality
    rather than deferring the failure to first-call. On import-time /
    load-time failure, the constructor stores the exception and
    ``is_healthy`` returns ``False``; every method then raises
    ``VoiceAdapterUnavailable``.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        self._model_name = model_name or _default_model_name()
        self._device = device or _default_device()
        self._compute_type = compute_type or _default_compute_type()
        self._closed = False
        self._model: Any | None = None
        self._load_error: BaseException | None = None
        try:
            # Lazy import so tests can monkeypatch or stub before load.
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
        except Exception as exc:  # noqa: BLE001 — record; report via is_healthy
            self._load_error = exc

    # -------------------------------------------------- protocol methods

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        hint: str | None = None,
    ) -> Transcript:
        self._require_ready()
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise ValueError("FasterWhisperVoiceAdapter.transcribe requires non-empty audio bytes")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, bytes(audio), mime, hint)

    def _transcribe_sync(
        self,
        audio: bytes,
        mime: str,
        hint: str | None,
    ) -> Transcript:
        # faster-whisper accepts a path, a numpy array, or a file-like.
        # For robustness across mime types, spool to a temp file.
        suffix = _suffix_for_mime(mime)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as f:
                f.write(audio)
                tmp_path = Path(f.name)
            segments_iter, info = self._model.transcribe(  # type: ignore[union-attr]
                str(tmp_path),
                beam_size=5,
                initial_prompt=hint,
            )
            segments: list[TranscriptSegment] = []
            texts: list[str] = []
            conf_sum = 0.0
            conf_count = 0
            for seg in segments_iter:
                # faster-whisper Segment: .start, .end, .text, .avg_logprob
                # avg_logprob is a log-probability (<=0); convert to a
                # bounded pseudo-confidence via exp(); clamped for safety.
                logp = getattr(seg, "avg_logprob", 0.0) or 0.0
                try:
                    import math
                    conf = max(0.0, min(1.0, math.exp(logp)))
                except Exception:  # noqa: BLE001
                    conf = 0.5
                segments.append(
                    TranscriptSegment(
                        start_s=float(getattr(seg, "start", 0.0) or 0.0),
                        end_s=float(getattr(seg, "end", 0.0) or 0.0),
                        text=str(getattr(seg, "text", "")).strip(),
                        confidence=conf,
                    )
                )
                texts.append(str(getattr(seg, "text", "")).strip())
                conf_sum += conf
                conf_count += 1

            aggregate_conf = (conf_sum / conf_count) if conf_count else 0.0
            language = getattr(info, "language", "und") or "und"
            return Transcript(
                text=" ".join(t for t in texts if t).strip(),
                confidence=aggregate_conf,
                language=str(language),
                segments=tuple(segments),
            )
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
    ) -> AudioClip:
        raise TTSNotConfigured(
            "TTS engine deferred to Stage 6.5+1 ADR after benchmark; "
            "Piper GPL-blocked, Coqui MPL-fork evaluation pending. "
            "Use NoOpVoiceAdapter for tests. (ADR-097 D3)"
        )

    async def list_voices(self) -> tuple[VoiceProfile, ...]:
        # STT-only adapter has no synthesis voices to advertise.
        return ()

    def is_healthy(self) -> bool:
        return (not self._closed) and (self._model is not None) and (self._load_error is None)

    async def close(self) -> None:
        self._closed = True
        self._model = None

    # -------------------------------------------------- helpers

    def _require_ready(self) -> None:
        if self._closed:
            raise VoiceAdapterUnavailable("FasterWhisperVoiceAdapter is closed")
        if self._model is None:
            hint = ""
            if isinstance(self._load_error, ModuleNotFoundError):
                hint = " Install with: pip install faster-whisper"
            elif self._load_error is not None:
                hint = f" Underlying: {type(self._load_error).__name__}: {self._load_error}"
            raise VoiceAdapterUnavailable(
                f"faster-whisper model not loaded (model={self._model_name!r}, "
                f"device={self._device!r}, compute_type={self._compute_type!r}).{hint}"
            )


def _suffix_for_mime(mime: str) -> str:
    if not mime:
        return ".wav"
    m = mime.lower()
    if "wav" in m:
        return ".wav"
    if "mp3" in m or "mpeg" in m:
        return ".mp3"
    if "ogg" in m or "opus" in m:
        return ".ogg"
    if "webm" in m:
        return ".webm"
    if "flac" in m:
        return ".flac"
    if "mp4" in m or "aac" in m or "m4a" in m:
        return ".m4a"
    return ".wav"


# --- unused import guard (keep import list stable) ---
_ = io  # noqa: F841
