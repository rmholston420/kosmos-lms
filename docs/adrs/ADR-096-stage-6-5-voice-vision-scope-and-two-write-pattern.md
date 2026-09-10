# ADR-096 — Stage 6.5 Voice + Vision port-in scope and the `tektos_frontend` two-write pattern

**Status:** Ratified
**Lock-in phase:** Stage 6.5
**Supersedes:** —

## Context

Stage 6.5 (per `docs/Kosmos-Build-Sequence-v26.md`) locks in the first adapters behind `VoicePort` (ADR-083) and `VisionPort` (ADR-084). Both port docstrings + ADRs specify:

- `provenance="tektos_frontend"` for MemoryPort writes on user-driven turns (spec §25.4 taxonomy row).
- `confidence` **passed through** from the model result (`Transcript.confidence` for voice; `VisionDescription.confidence` / `OCRResult.confidence` / `VisionDetection.confidence` for vision).

But `docs/Kosmos-Build-Sequence-v26.md` Stage 6.5 DoD reads:

> VisionPort round-trips a small PNG through Tektos frontend and back into `MemoryPort` with `provenance=tektos_frontend` and `confidence=1.0`.

And spec §25.4 pins the `tektos_frontend` row at `confidence=1.0`.

The two statements only agree if you split the write into **two** events per call:

1. **Ingest event** — the user uploaded/spoke this. That is a hard observable fact; `confidence=1.0` per §25.4.
2. **Result event** — the model derived this from the ingest. That inherits the model's confidence (per ADR-083 rule 1 + ADR-084 rule 1 passthrough).

This ADR locks that two-write pattern and lists the exact scope of the Stage 6.5 slice.

## Decision

### D1 — Two-write pattern for `tektos_frontend` MemoryPort writes

Every user-driven `VoicePort.transcribe` / `VisionPort.describe` / `VisionPort.extract_text` / `VisionPort.detect` call MUST produce **two** `MemoryPort.write_event` calls, in this exact order:

1. **Ingest triple.** Subject = the ingest URI (see D2); predicate = `"tektos_frontend.ingested"`; object = the mime type. `provenance="tektos_frontend"`, `confidence=1.0`, `attributes={"kind": "voice"|"vision", "sha256": <hash>, "byte_len": <n>, "mime": <mime>}`.
2. **Result triple.** Subject = the ingest URI; predicate = the model verb — `"tektos_frontend.transcribed"` / `"tektos_frontend.described"` / `"tektos_frontend.extracted_text"` / `"tektos_frontend.detected"`; object = the result summary (transcript text, description text, or a compact detections/OCR summary — never the raw bytes). `provenance="tektos_frontend"`, `confidence=<result.confidence>` (passthrough per ADR-083 / ADR-084), `attributes={"model": <name>, ...}`.

Neither write blocks the caller's return; both are `await`-ed before the port method returns.

`synthesize()` (TTS side of `VoicePort`) writes ZERO `MemoryPort` triples per ADR-083 rule 2 (the source text was already persisted upstream).

### D2 — Content-addressed ingest URI

The ingest URI for both voice bytes and image bytes is:

```
kosmos://blob/<sha256-hex>
```

Bytes land in `adapters/data/blobs/<sha256-hex>` (flat directory keyed by content hash; see D3). The URI is the value stored in the subject of both MemoryPort triples. Raw bytes NEVER land in `MemoryPort` (per ADR-084 rule 2 and by extension for voice bytes).

### D3 — `BlobStore` helper (not a new formal port)

Ships as `adapters/data/blobs/blob_store.py` — a two-method sync helper:

- `put_bytes(data: bytes) -> str` returns the sha256 hex.
- `open_path(sha256: str) -> pathlib.Path` returns the on-disk path (or raises `FileNotFoundError`).

This is **not** a new formal Kosmos port. It's a helper co-located with `adapters/data/` (which already exists for JSON-LD envelopes per ADR-028). If a future stage requires swappable blob backends (S3, IPFS), a formal `BlobPort` may be authored then; Stage 6.5 keeps the surface intentionally small.

Storage layout:
```
adapters/data/blobs/
    <sha256-hex-0>[0..2]/<sha256-hex-2..>   # 2-char shard prefix
```

Root is configurable via env `KOSMOS_BLOB_ROOT` (default `adapters/data/blobs/store/`).

### D4 — Stage 6.5 scope: exactly two `VoicePort` adapters + three `VisionPort` adapters + one shared helper

Ships in Stage 6.5:

**Voice** — `adapters/voice/`
- `noop/adapter.py` — `NoOpVoiceAdapter` (CI + integration bootstrap).
- `faster_whisper/adapter.py` — `FasterWhisperVoiceAdapter` (STT only — TTS raises `TTSNotConfigured`).

**Vision** — `adapters/vision/`
- `noop/adapter.py` — `NoOpVisionAdapter`.
- `ollama_qwen_vl/adapter.py` — `OllamaQwenVLVisionAdapter` (`describe` + `detect`).
- `tesseract/adapter.py` — `TesseractVisionAdapter` (`extract_text` only — `describe` / `detect` raise `VisionCapabilityUnsupported`).

**Shared helper** — `adapters/tektos_frontend/`
- `frontend_memory_writer.py` — `TektosFrontendMemoryWriter` implementing the D1 two-write pattern via injected `MemoryPort` + `BlobStore`.

**Explicit Stage 6.5 exclusions (deferred):**
- **TTS engine selection.** Piper (ADR-083 primary) archived Oct 2025; active fork `OHF-Voice/piper1-gpl` is **GPL-3.0** — non-permissive per `kosmos-port-workflow` §3. Coqui TTS project shuttered late 2023; MPL-2.0 forks (e.g. idiap/coqui-ai-TTS) require standalone evaluation. Deferred to a Stage 6.5+1 ADR after benchmark. Until then `VoicePort.synthesize` on the faster-whisper adapter raises `TTSNotConfigured`; NoOp adapter returns silent audio for CI.
- **`VoicePort` streaming variants.** Donor `TTSVoice.synthesize_stream` (async chunks) is not on the port surface at ADR-083. If added, requires a port amendment.
- **Wake-word detection + VAD.** Donor `VoiceActivityDetector` + `WakeWordDetector` + `VoiceManager` (an audio-loop orchestrator) are out of scope — none map to the `VoicePort` surface. Deferred to a hypothetical `VoiceOrchestrationPort` if / when that surface is proposed.
- **VisionPort image bytes over EventBus.** Only the URI + result summary flow through `EventBusPort`; bytes stay in `adapters/data/blobs/`.
- **Frontend UI wiring.** The `tektos-ultima` iframe (ADR-091) does not yet POST audio/image blobs to the bridge in Stage 6.5. Stage 6.5 lands the server-side adapters + writer + contract tests; the browser-side capture path is Stage 6.6.

### D5 — Approval-tier posture

None of the Stage 6.5 adapter methods route through `ApprovalGatewayPort`. All four verbs are read-only w.r.t. user state (`transcribe`, `describe`, `extract_text`, `detect`) and produce only MemoryPort observations; no filesystem mutation, no shell exec, no external API call from `transcribe`/`extract_text` (the Ollama adapter calls `http://127.0.0.1:11434` — loopback only, subject to the sandbox `network="loopback"` policy when composed under Stage 4.7 tool registry).

`synthesize()` also skips approval — it produces bytes returned to the caller, no side effect (ADR-083 rule 2).

## Rationale

- **Two-write over one.** A single triple cannot honestly say both "user did this" (hard fact) and "model believes result is X with confidence C" (soft fact). Splitting keeps §25.4's `confidence=1.0` invariant for the ingest row and preserves ADR-083 / ADR-084 passthrough for the derived row. Downstream consumers (Hindsight, immune detectors) can filter by predicate to get either the raw event stream or the model-derived stream.
- **Content-addressed URIs over auto-increment IDs.** Deduplicates re-uploads of the same image / same utterance for free; makes replay tests trivially reproducible; matches the ADR-084 rule 2 spec.
- **Helper over port for `BlobStore`.** A formal port for a two-method blob accessor is over-engineered when only two adapter families need it. `kosmos-port-workflow` §5 requires "every vendored component sits behind exactly one adapter under a formal port" — `BlobStore` is Kosmos-native (not vendored) and consumed only by our own adapters, so the rule does not fire. A future third consumer or a swappable backend would trigger a `BlobPort` ADR.
- **Piper deferral over GPL adoption.** GPL-3.0 in a Kosmos monorepo would viralize the entire scaffold; user's stated preference (persistent user context) is "free, self-hosted, open-source tooling that runs on Linux" — that does not extend to accepting a copyleft license which restricts downstream distribution. faster-whisper (MIT) + Tesseract (Apache-2.0) + Qwen2.5-VL via Ollama (Apache-2.0) all meet the same "free / self-hosted / Linux" bar without the license contamination. TTS is not on the Stage 6.5 DoD critical path (DoD is `transcribe` + `describe` + `extract_text` + `detect` + MemoryPort round-trip); deferring TTS engine choice does not block the slice.
- **Rejected: NoOpTTS satisfies TTS at Stage 6.5.** The user's preference list includes "adapting proven open-source systems over reimplementing mature capabilities" — silently shipping a NoOp as the "TTS solution" would be a covert reimplementation choice. Making the deferral explicit under ADR-097 keeps the port-workflow discipline honest.
- **Rejected: fold blob storage into `DataPort`.** `DataPort` (ADR-028) is JSON-LD canonical export with per-envelope migration semantics — coupling raw binary storage to it would break its cleanly-separated invariants (immutable envelopes, canonical hash of JCS-canonicalized JSON). A separate helper is smaller and safer.
- **Rejected: single writer method taking both ingest + result at once.** Would couple the two writes into one atomic call, which contradicts the port abstraction — VisionPort.detect returns a tuple of detections but the writer must fan out to one triple per detection would be a mistake; instead the writer emits one summary triple for the result and lets consumers query the raw result via the ingest URI.

## Consequences

- Files created:
  - `docs/adrs/ADR-096-stage-6-5-voice-vision-scope-and-two-write-pattern.md` (this ADR)
  - `adapters/data/blobs/__init__.py`, `adapters/data/blobs/blob_store.py`, `adapters/data/blobs/test_blob_store.py`
  - `adapters/tektos_frontend/__init__.py`, `adapters/tektos_frontend/frontend_memory_writer.py`, `adapters/tektos_frontend/test_memory_writer.py`
- Files updated:
  - `docs/Kosmos-Build-Sequence-v26.md` Stage 6.5 stanza — LANDED marker; DoD clause expanded to name the two-write pattern.
  - `PORTING_LEDGER.md` — new rows per ADR-097 + ADR-098 (see those ADRs).
  - `docs/adrs/README.md` — new rows for ADR-096 / ADR-097 / ADR-098; open-decisions sentence extended.
- Ports affected: `VoicePort` (adapters land), `VisionPort` (adapters land), `MemoryPort` (two-write pattern locked). No new port surface.
- Adapter selection: locked in ADR-097 (voice) and ADR-098 (vision).
- Provenance / confidence discipline: ingest row `confidence=1.0` (satisfies §25.4); result row uses model passthrough (satisfies ADR-083 / ADR-084 rule 1).

## Testing

DoD tests land in the adapter test suites:
- `VoicePort` round-trip: `FasterWhisperVoiceAdapter.transcribe` + `TektosFrontendMemoryWriter.record_voice` → assert exactly two `MemoryPort.write_event` calls with correct predicates + confidences.
- `VisionPort` round-trip: `OllamaQwenVLVisionAdapter.describe` (or `TesseractVisionAdapter.extract_text`) + `TektosFrontendMemoryWriter.record_vision` → same shape assertion.
- `BlobStore.put_bytes` idempotence (same bytes → same hash → single on-disk file).

## Lock-in phase

Locked at Stage 6.5.

## References

- ADR-083 (VoicePort surface), ADR-084 (VisionPort surface), ADR-028 (DataPort), ADR-027 (MemoryPort zero-trust)
- ADR-078 (Kosmos-Build-Spec-v26 cut — §25.4 provenance taxonomy)
- ADR-097 (VoicePort adapter selection — this Stage), ADR-098 (VisionPort adapter selection — this Stage)
- `docs/Kosmos-Build-Sequence-v26.md` §Stage 6.5
