"""Vision client for interacting with vision LLM servers.

Supports Qwen2.5-VL and other OpenAI-compatible vision APIs.
Handles image encoding and API calls to vision endpoints.

Usage:
    client = VisionClient(base_url="http://127.0.0.1:8083")
    result = await client.analyze(image_path, prompt="Describe this image")
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import pathlib
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("tektos.vision")


@dataclass
class VisionResult:
    """Result from a vision analysis."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    timings: dict[str, Any] = field(default_factory=dict)


class VisionClient:
    """Client for vision LLM inference via OpenAI-compatible API.

    Supports:
    - Qwen2.5-VL series (3B, 7B, 32B)
    - Any model with OpenAI-compatible /v1/chat/completions endpoint
    - Image URLs and base64-encoded images
    - Streaming responses
    """

    def __init__(
        self,
        base_url: str = os.getenv("TEKTOS_VISION_URL", "http://127.0.0.1:8083/v1"),
        model: str = "Qwen2.5-VL-3B-Instruct-Q4_K_M",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(300.0, connect=5.0, read=300.0, write=300.0, pool=5.0),
        )
        # Validate connection
        try:
            resp = await self._client.get("/health")
            resp.raise_for_status()
            log.info("Vision client connected: %s", self.base_url)
        except Exception as exc:
            log.warning("Vision endpoint not available at %s: %s", self.base_url, exc)
            raise

    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def analyze(
        self,
        image_path: str | pathlib.Path,
        prompt: str,
        system_prompt: str | None = None,
    ) -> VisionResult:
        """Analyze an image with the vision model.

        Args:
            image_path: Path to the image file.
            prompt: User prompt about the image.
            system_prompt: Optional system prompt override.

        Returns:
            VisionResult with the model's text response.
        """
        if not self._client:
            raise RuntimeError("VisionClient not started. Call start() first.")

        # Read and encode the image
        img_bytes = await self._read_image(image_path)
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime_type = self._get_mime_type(image_path)

        # Build messages
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{img_b64}",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        )

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        resp = await self._client.post(
            "/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

        data = resp.json()
        choice = data["choices"][0]

        return VisionResult(
            text=choice["message"]["content"],
            model=data.get("model", self.model),
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            total_tokens=data.get("usage", {}).get("total_tokens", 0),
            timings=data.get("timings", {}),
        )

    async def analyze_url(
        self,
        image_url: str,
        prompt: str,
        system_prompt: str | None = None,
    ) -> VisionResult:
        """Analyze an image from a URL."""
        if not self._client:
            raise RuntimeError("VisionClient not started. Call start() first.")

        # Download the image
        resp = await self._client.get(image_url)
        resp.raise_for_status()
        img_bytes = resp.content
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime_type = "image/png" if image_url.endswith(".png") else "image/jpeg"

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        )

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        resp = await self._client.post(
            "/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

        data = resp.json()
        choice = data["choices"][0]

        return VisionResult(
            text=choice["message"]["content"],
            model=data.get("model", self.model),
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            total_tokens=data.get("usage", {}).get("total_tokens", 0),
            timings=data.get("timings", {}),
        )

    async def health(self) -> bool:
        """Check if the vision endpoint is healthy."""
        if not self._client:
            return False
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _read_image(self, path: str | pathlib.Path) -> bytes:
        """Read an image file and return its bytes."""
        p = pathlib.Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Image not found: {path}")
        if not p.is_file():
            raise ValueError(f"Not a file: {path}")
        return p.read_bytes()

    def _get_mime_type(self, path: str | pathlib.Path) -> str:
        """Get the MIME type for an image file."""
        mime, _ = mimetypes.guess_type(str(path))
        if mime and mime.startswith("image/"):
            return mime
        return "image/png"  # Default fallback
