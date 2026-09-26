# ADR-098 — VisionPort adapter selection: Qwen2.5-VL via Ollama + Tesseract OCR

**Status:** Ratified
**Locked:** ADR-145 (2026-09-26) — Stage 14 program freeze; this ADR is locked (see ADR-145).
**Lock-in phase:** Stage 6.5
**Supersedes:** —

## Context

ADR-084 locked `VisionPort` surface at Stage 6.5. Adapter selection deferred to the same stage per `kosmos-port-workflow`. ADR-084 candidates:

- Multimodal (describe / detect): LLaVA via Ollama, Qwen2-VL via Ollama.
- OCR-only (extract_text): Tesseract.

Tektos-Ultima donor has **no** vision code — nothing to vendor. Every adapter here is Kosmos-native.

Options evaluated:

| Model | License | Params | OCR quality | Notes |
|---|---|---|---|---|
| **Qwen2.5-VL 7B** | Apache-2.0 | 7B | Excellent (94.5% DocVQA) | Current-generation, strong OCR/document/chart understanding; ~6 GB VRAM Q4 |
| Qwen2-VL 7B | Apache-2.0 | 7B | Excellent | Superseded by 2.5 |
| Qwen3-VL | Apache-2.0 | 4B–235B | Very strong OCR | Newest but heavier at usable quality tiers |
| LLaVA 1.6 7B | Apache-2.0 | 7B | Fair | Older, weaker on OCR/documents |
| LLaVA 34B | Apache-2.0 | 34B | ~51% MMMU | 20+ GB VRAM — exceeds practical share of Colossus (32 GB VRAM, most reserved for llama-server + faster-whisper CPU load) |
| MiniCPM-V | Apache-2.0 | 1.3–8B | Strong on OCR at small footprint | Solid backup |
| Llama 3.2 Vision 11B | Llama Community License | 11B | Good on English photo Q&A | Non-Apache; Meta's custom license adds redistribution friction |
| Moondream | Apache-2.0 | 1.9B | Basic | Too lightweight for OCR primary |
| Gemma 3 Vision | Gemma Terms | Various | Good | Non-Apache license |

Tesseract (Apache-2.0) + pytesseract (Apache-2.0) remain the pragmatic OCR-only fast path — sub-second on printed text, no GPU, deterministic per-page confidence.

## Decision

### D1 — Ship two real vision adapters + NoOp

**`adapters/vision/ollama_qwen_vl/adapter.py` — `OllamaQwenVLVisionAdapter`**
- Backs `VisionPort.describe` and `VisionPort.detect`.
- `extract_text` raises `VisionCapabilityUnsupported("Use TesseractVisionAdapter for OCR — Qwen2.5-VL is capable of OCR but its confidence is uncalibrated for the extract_text passthrough contract. See ADR-098 D3.")`.
- Talks to Ollama at `http://127.0.0.1:11434/api/generate` (loopback only).
- Default model: `qwen2.5-vl:7b` (Apache-2.0). Overridable via env `KOSMOS_VISION_MODEL`.
- Base URL overridable via env `KOSMOS_OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`).
- HTTP calls use `httpx.AsyncClient` — already a Kosmos dependency (used by Ollama LLM adapter).

**`adapters/vision/tesseract/adapter.py` — `TesseractVisionAdapter`**
- Backs `VisionPort.extract_text`.
- `describe` and `detect` raise `VisionCapabilityUnsupported("Tesseract is OCR-only — use OllamaQwenVLVisionAdapter for describe/detect.")`.
- Wraps `pytesseract` (Apache-2.0 → Apache-2.0 wrapper).
- Requires the system `tesseract` binary; `is_healthy()` returns `False` if `pytesseract.get_tesseract_version()` raises.

**`adapters/vision/noop/adapter.py` — `NoOpVisionAdapter`**
- All three verbs return well-shaped placeholder results (empty description, empty OCR text, empty detections tuple) with `confidence=0.0`.
- Required for CI and for composing tests that need a `VisionPort` without hitting Ollama or Tesseract.

### D2 — Split adapters (not a composite)

Two real adapters — one per capability family — rather than a single "vision" adapter that internally routes describe→Ollama and extract_text→Tesseract. Rationale:

1. Different failure modes (Ollama process down vs. tesseract binary missing) require different `is_healthy()` reports.
2. The port surface's `runtime_checkable` protocol is already satisfied by an adapter that raises `VisionCapabilityUnsupported` for the verbs it does not implement — no need for a routing layer.
3. Composition, if it becomes valuable later, is a plugin concern (a Kosmos plugin can hold both adapters and dispatch), not an adapter concern.

### D3 — OCR routing

`OllamaQwenVLVisionAdapter.extract_text` is deliberately unsupported even though Qwen2.5-VL can OCR. Reason: the port contract specifies `OCRResult.blocks` with per-block bounding boxes and per-block confidences. Qwen2.5-VL returns free-text; extracting block-level bboxes from a VL model would require an additional layout-detection pass and confidence calibration. Tesseract returns block-level bboxes + confidences natively. Callers that need "OCR text out of an image with bboxes" route to Tesseract; callers that need "describe this document in prose" route to Qwen2.5-VL.

### D4 — Result confidence sources

- `VisionDescription.confidence` from Ollama: Qwen2.5-VL does not emit a confidence score. Adapter sets `confidence=0.5` as a **calibrated placeholder** — the "we did the call, model returned a description, we have no ground truth" default. Documented in the adapter docstring; not a per-instance ctor override.
- `OCRResult.confidence` from Tesseract: aggregate is the mean of block confidences (pytesseract exposes per-block confidence via `image_to_data`). Blocks with `conf == -1` (no OCR) are excluded from the aggregate. Empty result → `confidence=0.0`.
- `VisionDetection.confidence` from Ollama detect: Qwen2.5-VL is prompted to output detections as JSON. Model-declared confidence per detection is used verbatim; when the model does not supply one, `0.5` placeholder.

### D5 — Adapter directory layout

```
adapters/vision/
    __init__.py                # error taxonomy
    noop/
        __init__.py
        adapter.py
        test_contract.py
    ollama_qwen_vl/
        __init__.py
        adapter.py
        test_contract.py
    tesseract/
        __init__.py
        adapter.py
        test_contract.py
```

Errors at `adapters/vision/__init__.py`:
- `VisionAdapterUnavailable(RuntimeError)` — adapter cannot serve (dep missing, Ollama unreachable, closed).
- `VisionCapabilityUnsupported(NotImplementedError)` — this adapter does not implement this verb by design.

## Rationale

- **Qwen2.5-VL 7B over LLaVA:** better OCR (94.5% DocVQA vs. ~fair), better multilingual coverage (29 languages including CJK), same Apache-2.0 license, same VRAM envelope. LLaVA remains an in-family fallback (only requires flipping the env var `KOSMOS_VISION_MODEL=llava:7b`).
- **Qwen2.5 over Qwen3:** Qwen3-VL is newer but its usable quality tier lands at 8B+ (adds VRAM pressure); Qwen2.5-VL 7B is the sweet spot on Colossus's 32 GB VRAM (of which ~24 GB is typically committed to llama-server).
- **Ollama over direct HuggingFace + transformers:** Ollama is already a Kosmos runtime dependency (per `adapters/llm/ollama/`); zero incremental infra cost. Direct transformers path would double the CUDA memory pool contention.
- **Tesseract over EasyOCR / PaddleOCR:** Apache-2.0 (both alternatives are also Apache-2.0 / MIT but require heavier deps); Tesseract has native per-block bbox + confidence (both alternatives require post-processing to fit `OCRResult` shape); Tesseract is the OS-package default on Debian/Ubuntu (`apt install tesseract-ocr`) which matches user's Kubuntu workstation.
- **Rejected: single composite adapter routing describe→Ollama, extract_text→Tesseract.** See D2 — obscures failure modes and adds a routing layer with no clear owner.
- **Rejected: Llama 3.2 Vision.** Meta's community license restricts distribution + has usage-count triggers. Apache-2.0 alternatives with equivalent quality exist.
- **Rejected: cloud vision APIs (Google Vision, Azure Vision).** Contradict persistent user preference for self-hosted / offline / open-source.

## Consequences

- Files created:
  - `adapters/vision/__init__.py` (error taxonomy)
  - `adapters/vision/noop/__init__.py`, `adapters/vision/noop/adapter.py`, `adapters/vision/noop/test_contract.py`
  - `adapters/vision/ollama_qwen_vl/__init__.py`, `adapters/vision/ollama_qwen_vl/adapter.py`, `adapters/vision/ollama_qwen_vl/test_contract.py`
  - `adapters/vision/tesseract/__init__.py`, `adapters/vision/tesseract/adapter.py`, `adapters/vision/tesseract/test_contract.py`
- Files updated:
  - `PORTING_LEDGER.md` — 3 new HAND-BUILT rows (one per adapter); 1 REJECTED row (LLaVA-as-primary — kept as fallback via env var, so a footnote rather than a formal rejection).
- Runtime deps: `httpx` (already present); `pytesseract` under a new `vision` optional extra. `tesseract-ocr` OS binary required for real OCR; `ollama` process required for real describe/detect.
- No new port surface.

## Testing

Contract tests validate:
- Each of the three adapters satisfies the `VisionPort` `runtime_checkable` isinstance check.
- `NoOpVisionAdapter`: all three verbs return well-shaped results with `confidence=0.0`.
- `OllamaQwenVLVisionAdapter`: `extract_text` raises `VisionCapabilityUnsupported` with `"ADR-098"` in the message; `describe` with a stubbed `httpx.AsyncClient` returning a canned JSON response produces a well-shaped `VisionDescription`.
- `TesseractVisionAdapter`: `describe` and `detect` raise `VisionCapabilityUnsupported`; `extract_text` with stubbed `pytesseract.image_to_data` returns a well-shaped `OCRResult` with the aggregate confidence formula from D4.
- `is_healthy` false-report path: `OllamaQwenVLVisionAdapter.is_healthy()` returns `False` when the base URL is unreachable (checked lazily via a short-timeout GET).

## Lock-in phase

Locked at Stage 6.5.

## References

- ADR-084 (VisionPort), ADR-096 (Stage 6.5 scope)
- Vision model comparison (verified 2026-09-10):
  - Qwen2.5-VL: Apache-2.0, [Ollama library](https://ollama.com/library/qwen2.5-vl)
  - Tesseract: Apache-2.0, [github.com/tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract)
  - pytesseract: Apache-2.0, [github.com/madmaze/pytesseract](https://github.com/madmaze/pytesseract)
- `adapters/llm/ollama/` (existing Ollama HTTP client precedent)
