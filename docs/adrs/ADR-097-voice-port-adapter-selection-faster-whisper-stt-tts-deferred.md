# ADR-097 — VoicePort adapter selection: faster-whisper STT lands; TTS engine deferred

**Status:** Ratified
**Locked:** ADR-145 (2026-09-26) — Stage 14 program freeze; this ADR is locked (see ADR-145).
**Lock-in phase:** Stage 6.5
**Supersedes:** —

## Context

ADR-083 locked `VoicePort` surface at Stage 6.5. Adapter selection was explicitly deferred to the same stage per `kosmos-port-workflow`. Candidates listed there:

- STT: Whisper.cpp (primary), faster-whisper (alternative).
- TTS: Piper (primary), Coqui TTS (alternative).

Two facts drive this ADR:

1. **Piper is no longer MIT.** rhasspy/piper was archived on 2025-10-06; active development moved to `OHF-Voice/piper1-gpl` — GPL-3.0. Piper's runtime dependency `espeak-ng` is also GPL. GPL-3.0 in the kosmos-lms monorepo would viralize every downstream consumer; per `kosmos-port-workflow` §3 GPL is non-permissive → refuse without explicit user override + ADR (this ADR records the refusal instead of the override).
2. **Coqui TTS is dead** as of late 2023; MPL-2.0 forks exist (`idiap/coqui-ai-TTS` being the most active) but require a standalone evaluation against latency + quality + Colossus resource envelope. Doing that evaluation inside Stage 6.5 would gate the whole Voice + Vision slice on TTS quality — which is not on the Stage 6.5 DoD critical path (DoD is `transcribe` + Vision verbs + MemoryPort round-trip; `synthesize` is not exercised).

Tektos-Ultima donor `src/tektos/voice.py` uses `faster-whisper` for STT (MIT, still active — SYSTRAN-maintained) and `edge-tts` for TTS. `edge-tts` uses Microsoft's Edge cloud TTS service — not self-hosted, contradicts persistent user preference "free, self-hosted, open-source tooling that runs on Linux." Also reject.

## Decision

### D1 — Adopt faster-whisper as the Stage 6.5 STT adapter

`adapters/voice/faster_whisper/adapter.py` implements `VoicePort.transcribe` + `VoicePort.list_voices` + `VoicePort.is_healthy` + `VoicePort.close`. `synthesize` raises `TTSNotConfigured` (see D3).

Model: `large-v3-turbo` (donor default; overridable via env `KOSMOS_WHISPER_MODEL`).
Device: `cpu` default (Colossus GPU reserved for llama-server per Tektos donor rationale); overridable via `KOSMOS_WHISPER_DEVICE`.
Compute type: `int8` default (memory-efficient; per donor); overridable via `KOSMOS_WHISPER_COMPUTE_TYPE`.

`faster-whisper` is a hard runtime dependency (no lazy import) at Stage 6.5 to keep the adapter constructor honest. If the package is not installed, `is_healthy()` returns `False` and every method raises `VoiceAdapterUnavailable` with the exact install hint. This satisfies the `kosmos-port-workflow` stop condition "adapter fails contract if the vendor dep is missing" while keeping CI green (CI wires the `NoOpVoiceAdapter` instead of `FasterWhisperVoiceAdapter`).

### D2 — Vendor donor `STTEngine` behaviour, not code

The donor `STTEngine` is 47 lines including init boilerplate. Re-implementing behind a formal port (result shape → `Transcript` value object; explicit `mime` + `hint` args; async signature) is smaller than a direct port + wrapper. No line-for-line vendoring; the donor is inspected via `kosmos-port-workflow` §2 and rewritten to the port. The `PORTING_LEDGER` row records this as **HAND-BUILT (donor-informed)** with the donor URL + commit SHA cited so any future divergence is traceable.

### D3 — Defer TTS engine selection to Stage 6.5+1

`FasterWhisperVoiceAdapter.synthesize` raises `TTSNotConfigured("TTS engine deferred to Stage 6.5+1 ADR after benchmark; Piper GPL-blocked, Coqui MPL-fork evaluation pending. Use NoOpVoiceAdapter for tests.")`.

`NoOpVoiceAdapter.synthesize` returns a fixed 100 ms silent WAV (44 bytes of PCM zeros) so the protocol conformance test passes without a real engine.

TTS engine selection ADR (post-Stage 6.5) will evaluate at minimum:
- **idiap/coqui-ai-TTS** — MPL-2.0, active fork of Coqui.
- **StyleTTS2** — MIT, higher quality but heavier.
- **Kokoro-82M** — Apache-2.0, small footprint high quality, released late 2024.
- **Sonos/tts-openvoice** or similar OpenVoice-derived.

That ADR will be triggered when the frontend TTS use-case surfaces (currently no Stage 6.5+n item requires it).

### D4 — `NoOpVoiceAdapter` shape

- `transcribe` returns `Transcript(text="", confidence=0.0, language="und", segments=())`.
- `synthesize` returns `AudioClip(bytes=<44-byte silent WAV>, mime="audio/wav", duration_s=0.1, voice=voice or "noop")`.
- `list_voices` returns `(VoiceProfile(voice_id="noop", name="No-op", language="und", gender="neutral"),)`.
- `is_healthy` returns `True` until `close()` is called, then `False`.
- Required by CI (per the ADR-082 rule 4 analogue for voice — no test may spawn a Whisper model).

### D5 — Adapter directory layout

```
adapters/voice/
    __init__.py
    noop/
        __init__.py
        adapter.py
        test_contract.py
    faster_whisper/
        __init__.py
        adapter.py
        test_contract.py
```

Errors are declared once at `adapters/voice/__init__.py`:
- `VoiceAdapterUnavailable(RuntimeError)` — adapter cannot serve calls (dep missing, model not loaded, closed).
- `TTSNotConfigured(NotImplementedError)` — TTS deliberately absent for this Stage per D3.

## Rationale

- **faster-whisper over Whisper.cpp:** the donor already exercises faster-whisper on Colossus (CPU, int8, large-v3-turbo) — this validates the resource envelope in production and eliminates a whole class of "does the model actually load on the target box?" risk. Whisper.cpp would require a separate C++ binding + build step. faster-whisper is pip-installable, MIT-licensed, and maintained by SYSTRAN.
- **Vendoring behaviour, not code:** the donor STT surface is 47 lines of glue code with heavy coupling to donor logging + tmp-file conventions. A port-conforming rewrite is smaller than the wrapper needed to isolate the donor version behind the port. `PORTING_LEDGER` still records donor URL + commit SHA so the design lineage is auditable.
- **TTS deferral over Piper GPL adoption:** blocked by kosmos-port-workflow §3. Deferring keeps Stage 6.5 DoD intact.
- **TTS deferral over Coqui-fork adoption inside Stage 6.5:** would tie DoD to a benchmark decision, adding scope creep. Post-Stage ADR is the right shape.
- **`NoOpVoiceAdapter` retained:** required to prove protocol conformance without loading a 3 GB Whisper model in CI.
- **Rejected: fold STT + TTS into separate adapters (`SttFasterWhisperAdapter`, `TtsNoopAdapter`).** They implement the same `VoicePort` — splitting them requires callers to hold two ports, contradicting ADR-083's single-port decision (§Rationale).

## Consequences

- Files created:
  - `adapters/voice/__init__.py` (error taxonomy)
  - `adapters/voice/noop/__init__.py`, `adapters/voice/noop/adapter.py`, `adapters/voice/noop/test_contract.py`
  - `adapters/voice/faster_whisper/__init__.py`, `adapters/voice/faster_whisper/adapter.py`, `adapters/voice/faster_whisper/test_contract.py`
- Files updated:
  - `PORTING_LEDGER.md` — 1 new HAND-BUILT (donor-informed) row for FasterWhisperVoiceAdapter; 1 new HAND-BUILT row for NoOpVoiceAdapter; 1 new REJECTED row for Piper (with reason) and edge-tts (with reason).
- Runtime deps added (extras): `faster-whisper` under a new `voice` optional extra so the base install stays lean.
- TTS engine remains unselected until Stage 6.5+1 ADR.

## Testing

Contract tests validate:
- `NoOpVoiceAdapter` satisfies the `VoicePort` `runtime_checkable` isinstance check.
- `FasterWhisperVoiceAdapter` satisfies the `runtime_checkable` isinstance check via a stubbed model attribute (the test does NOT load a real model).
- `FasterWhisperVoiceAdapter.synthesize` raises `TTSNotConfigured` with `"ADR-097"` in the message.
- `FasterWhisperVoiceAdapter.transcribe` with a stubbed `_model.transcribe` returning canned segments produces a well-formed `Transcript` with `0.0 <= confidence <= 1.0` and segments preserving timing invariants.
- `is_healthy` toggles false after `close`.

## Lock-in phase

Locked at Stage 6.5.

## References

- ADR-083 (VoicePort), ADR-096 (Stage 6.5 scope)
- Donor: `src/tektos/voice.py` (upstream commit `2b45cac1f9ac214c85ff53571b949445b5415209`)
- `kosmos-port-workflow` §3 (license filter)
- Persistent user preference: "free, self-hosted, open-source tooling that runs on Linux"
