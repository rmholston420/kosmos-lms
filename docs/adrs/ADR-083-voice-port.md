# ADR-083 — VoicePort (new formal port)

**Status:** Ratified
**Lock-in phase:** Stage 6.5
**Supersedes:** —

## Context

Tektos-Ultima ships a set of frontend panels that expect voice input (STT for command entry) and voice output (TTS for status readbacks). The current implementation calls browser Web Speech API directly. In kosmos-lms this must sit behind a formal port so:

1. Server-side STT/TTS (using a local model on Colossus, e.g. Whisper.cpp for STT, Piper for TTS) becomes swappable.
2. Voice envelopes reach `EventBusPort` so other plugins (Praxis, Phrouros) can react.
3. The kosmos-lms shell can share one voice service across Tektos and future plugins (Kosmos-wide voice command surface).

## Decision

Introduce **`VoicePort`** as the 20th formal Kosmos port at `ports/voice.py`.

### Protocol surface

```python
@runtime_checkable
class VoicePort(Protocol):
    async def transcribe(self, audio: bytes, *, mime: str, hint: str | None = None) -> Transcript: ...
    async def synthesize(self, text: str, *, voice: str | None = None) -> AudioClip: ...
    async def list_voices(self) -> tuple[VoiceProfile, ...]: ...
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...
```

Value objects (frozen dataclasses):

- `Transcript{text: str, confidence: float, language: str, segments: tuple[TranscriptSegment, ...]}`.
- `TranscriptSegment{start_s: float, end_s: float, text: str, confidence: float}`.
- `AudioClip{bytes: bytes, mime: str, duration_s: float, voice: str}`.
- `VoiceProfile{voice_id: str, name: str, language: str, gender: Literal["neutral","masculine","feminine"]}`.

### Enforcement rules

1. `transcribe()` results MUST be written to `MemoryPort` when originating from a user-driven turn, with `provenance="tektos_frontend"` and `confidence=Transcript.confidence` (passthrough) per §25.4.
2. `synthesize()` does not write to `MemoryPort` (side-effect only; the source text was already persisted).
3. Adapters live under `adapters/voice/<vendor>/`. The initial adapter is TBD in Stage 6.5 (candidates evaluated per `kosmos-port-workflow`); a `NoOpVoiceAdapter` returns a placeholder transcript for CI.

## Rationale

- **Formal port over browser-only Web Speech**: enables server-side local models (Whisper.cpp, Piper) which give better latency + privacy + offline capability than browser APIs.
- **Confidence passthrough on transcribe writes**: STT confidence is a real signal (unlike immune/thermal where confidence is always 1.0); passthrough preserves it so downstream consumers can weight it.
- **Rejected: fold STT and TTS into separate ports (`STTPort`, `TTSPort`).** They share adapter code (both wrap the same audio model server most of the time); one port keeps the callable surface small.

## Consequences

- Files created (this ADR): `ports/voice.py`; `tests/ports/test_voice_protocol.py`.
- Files planned (Stage 6.5): `adapters/voice/<tbd>/adapter.py`, `adapters/voice/noop/adapter.py`, both with `test_contract.py`.
- Adapter selection deferred to Stage 6.5 per `kosmos-port-workflow` (evaluate Whisper.cpp + Piper primary; alternative: faster-whisper + Coqui TTS).

## Lock-in phase

Locked at Stage 6.5. The **port surface** is locked here; adapter selection is a separate lock at Stage 6.5.

## References

- ADR-077, ADR-078 (v26 §25.4)
- ADR-027 (`MemoryPort` zero-trust write contract)
