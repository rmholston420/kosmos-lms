# ADR-084 — VisionPort (new formal port)

**Status:** Ratified
**Lock-in phase:** Stage 6.5
**Supersedes:** —

## Context

Tektos-Ultima frontend panels accept screenshots, error-message images, and drag-and-drop image inputs. The current implementation base64-encodes them into LLM prompts inline. In kosmos-lms this must sit behind a formal port so:

1. Multimodal image ingest is a Kosmos-wide capability (Kosmos GUI can accept image inputs beyond Tektos).
2. Image inputs are observable on `EventBusPort` and persisted to `MemoryPort` with provenance for reproducibility.
3. The image → vision-model call is one abstraction, allowing swap between local multimodal (e.g. LLaVA, Qwen2-VL) and cloud API without touching callers.

## Decision

Introduce **`VisionPort`** as the 21st formal Kosmos port at `ports/vision.py`.

### Protocol surface

```python
@runtime_checkable
class VisionPort(Protocol):
    async def describe(self, image: bytes, *, mime: str, prompt: str | None = None) -> VisionDescription: ...
    async def extract_text(self, image: bytes, *, mime: str) -> OCRResult: ...
    async def detect(self, image: bytes, *, mime: str, categories: tuple[str, ...] | None = None) -> tuple[VisionDetection, ...]: ...
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...
```

Value objects (frozen dataclasses):

- `VisionDescription{text: str, model: str, confidence: float}`.
- `OCRResult{text: str, blocks: tuple[OCRBlock, ...], confidence: float}`.
- `OCRBlock{text: str, bbox: tuple[int, int, int, int], confidence: float}`.
- `VisionDetection{category: str, bbox: tuple[int, int, int, int], confidence: float}`.

### Enforcement rules

1. Every `describe()` / `extract_text()` / `detect()` call originating from a user-driven turn MUST write the source image reference (not the bytes) + the result to `MemoryPort` with `provenance="tektos_frontend"` and `confidence` from the result (passthrough) per §25.4.
2. Image bytes are not stored in `MemoryPort` — they land in `adapters/data/` blob storage with a content-address hash; the `MemoryPort` write references the hash.
3. Adapters live under `adapters/vision/<vendor>/`. The initial adapter is TBD in Stage 6.5 (candidates: LLaVA via Ollama, Qwen2-VL via Ollama, Tesseract for OCR-only paths); a `NoOpVisionAdapter` returns a placeholder description for CI.

## Rationale

- **Formal port over inline base64**: enables local multimodal model swap and separates image storage from image analysis.
- **Content-address blob storage** (not `MemoryPort` bytes): large binaries do not belong in the graph store; the graph gets the hash, `adapters/data/` gets the bytes.
- **Rejected: fold into a generic `MultimodalPort`.** Audio (VoicePort) and image (VisionPort) have different value objects, different adapters, and different lifecycles. A shared abstraction would leak both.

## Consequences

- Files created (this ADR): `ports/vision.py`; `tests/ports/test_vision_protocol.py`.
- Files planned (Stage 6.5): `adapters/vision/<tbd>/adapter.py`, `adapters/vision/noop/adapter.py`, both with `test_contract.py`.
- Adapter selection deferred to Stage 6.5.

## Lock-in phase

Locked at Stage 6.5 (port surface); adapter selection separately locked at Stage 6.5.

## References

- ADR-077, ADR-078 (v26 §25.4)
- ADR-027 (`MemoryPort` zero-trust write contract)
- ADR-028 (`DataPort` for blob storage)
