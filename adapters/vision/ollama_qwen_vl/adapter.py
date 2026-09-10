"""OllamaQwenVLVisionAdapter — describe + detect via Ollama-hosted Qwen2.5-VL (ADR-098 D1).

Talks to Ollama at ``http://127.0.0.1:11434/api/generate`` (loopback only).
Default model ``qwen2.5-vl:7b`` (Apache-2.0); override via env
``KOSMOS_VISION_MODEL``.

OCR (``extract_text``) is deliberately unsupported here — route those calls
to ``TesseractVisionAdapter`` per ADR-098 D3.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

from adapters.vision import VisionAdapterUnavailable, VisionCapabilityUnsupported
from ports.vision import (
    OCRResult,
    VisionDescription,
    VisionDetection,
)

__all__ = ["OllamaQwenVLVisionAdapter"]


def _default_base_url() -> str:
    return os.environ.get("KOSMOS_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def _default_model() -> str:
    return os.environ.get("KOSMOS_VISION_MODEL", "qwen2.5-vl:7b")


_DESCRIBE_PROMPT_DEFAULT = (
    "Describe this image in one concise paragraph. Focus on subjects, "
    "actions, and salient objects. Do not invent details."
)


class OllamaQwenVLVisionAdapter:
    """Async client for a local Ollama server serving a Qwen2.5-VL model."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._base_url = (base_url or _default_base_url()).rstrip("/")
        self._model = model or _default_model()
        self._timeout = float(timeout_seconds)
        self._closed = False
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )

    # -------------------------------------------------- protocol

    async def describe(
        self,
        image: bytes,
        *,
        mime: str,
        prompt: str | None = None,
    ) -> VisionDescription:
        self._require_open()
        self._require_image_bytes(image)
        body = {
            "model": self._model,
            "prompt": (prompt or _DESCRIBE_PROMPT_DEFAULT),
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
        }
        try:
            resp = await self._client.post("/api/generate", json=body)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VisionAdapterUnavailable(
                f"Ollama describe call failed ({type(exc).__name__}: {exc})"
            ) from exc

        text = str(data.get("response", "")).strip()
        return VisionDescription(text=text, model=self._model, confidence=0.5)

    async def extract_text(
        self,
        image: bytes,
        *,
        mime: str,
    ) -> OCRResult:
        raise VisionCapabilityUnsupported(
            "OllamaQwenVLVisionAdapter does not implement OCR. "
            "Use TesseractVisionAdapter for OCR — Qwen2.5-VL is capable of "
            "OCR but its confidence is uncalibrated for the extract_text "
            "passthrough contract. See ADR-098 D3."
        )

    async def detect(
        self,
        image: bytes,
        *,
        mime: str,
        categories: tuple[str, ...] | None = None,
    ) -> tuple[VisionDetection, ...]:
        self._require_open()
        self._require_image_bytes(image)

        cat_clause = (
            f" Only detect these categories: {', '.join(categories)}."
            if categories
            else ""
        )
        prompt = (
            "Detect the salient objects in this image. Respond with STRICT "
            "JSON: an array of objects, each with keys 'category' (string), "
            "'bbox' (array of four integers: x, y, width, height in pixel "
            "coordinates), and 'confidence' (float in [0,1]). No prose, no "
            "markdown fences, JSON only." + cat_clause
        )

        body = {
            "model": self._model,
            "prompt": prompt,
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
            "format": "json",
        }
        try:
            resp = await self._client.post("/api/generate", json=body)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VisionAdapterUnavailable(
                f"Ollama detect call failed ({type(exc).__name__}: {exc})"
            ) from exc

        raw = str(data.get("response", "")).strip()
        return _parse_detections(raw)

    def is_healthy(self) -> bool:
        if self._closed:
            return False
        # Fast, non-throwing probe — short-timeout GET /api/tags.
        try:
            # httpx has no sync method on AsyncClient; open a one-shot sync client.
            with httpx.Client(base_url=self._base_url, timeout=2.0) as probe:
                r = probe.get("/api/tags")
                return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------- helpers

    def _require_open(self) -> None:
        if self._closed:
            raise VisionAdapterUnavailable("OllamaQwenVLVisionAdapter is closed")

    @staticmethod
    def _require_image_bytes(image: bytes) -> None:
        if not isinstance(image, (bytes, bytearray)) or not image:
            raise ValueError("VisionPort image argument must be non-empty bytes")


def _parse_detections(raw: str) -> tuple[VisionDetection, ...]:
    """Parse a Qwen-VL JSON detections payload into VisionDetection tuple.

    Robust to a top-level list, top-level dict with a ``detections`` key, or
    a lone dict. Silently skips malformed entries rather than raising —
    partial-quality detections are more useful than none.
    """
    try:
        parsed: Any = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ()

    entries: list[Any] = []
    if isinstance(parsed, list):
        entries = parsed
    elif isinstance(parsed, dict):
        if "detections" in parsed and isinstance(parsed["detections"], list):
            entries = parsed["detections"]
        else:
            entries = [parsed]

    out: list[VisionDetection] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        cat = e.get("category") or e.get("label") or e.get("name")
        bbox = e.get("bbox") or e.get("box")
        conf = e.get("confidence") or e.get("score") or 0.5
        if not isinstance(cat, str) or not cat:
            continue
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            x, y, w, h = (int(round(float(v))) for v in bbox)
        except (TypeError, ValueError):
            continue
        try:
            c = float(conf)
        except (TypeError, ValueError):
            c = 0.5
        c = max(0.0, min(1.0, c))
        out.append(VisionDetection(category=cat, bbox=(x, y, w, h), confidence=c))
    return tuple(out)
