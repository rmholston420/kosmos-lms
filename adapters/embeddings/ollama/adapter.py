"""adapters.embeddings.ollama.adapter — OllamaEmbeddingsAdapter (ADR-073).

Primary ``EmbeddingsPort`` implementation. Calls Ollama's **native**
``/api/embed`` endpoint (NOT the ``/v1/embeddings`` OpenAI-compat path)
so no fake api_key sentinel is required and error shapes match the rest
of `adapters/llm/ollama/adapter.py`.

Env vars (constructor args override):
    KOSMOS_OLLAMA_BASE_URL       Native Ollama root, defaults to
                                 ``http://127.0.0.1:11434``. Must be the
                                 native root, not the ``/v1`` compat prefix.
    KOSMOS_OLLAMA_EMBED_MODEL    Default embedding model, defaults to
                                 ``nomic-embed-text`` (768-dim).

References:
    - ADR-073 D2 (this adapter's authority)
    - ADR-063 (kernel-owned LLMPort — sibling adapter)
    - `ports/embeddings.py` (protocol contract)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ports.embeddings import EmbeddingError, EmbeddingsPort

log = logging.getLogger(__name__)


# Static model → dimension table. Keeps ``dimensions()`` from doing a
# live probe call on every VectorPort collection-create. Extend as new
# embed models are approved.
_MODEL_DIMENSIONS: dict[str, int] = {
    "nomic-embed-text": 768,
    "nomic-embed-text:latest": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "snowflake-arctic-embed": 1024,
}


class OllamaEmbeddingsAdapter:
    """Native ``/api/embed`` adapter satisfying ``EmbeddingsPort``.

    Thread-safety: the underlying ``httpx.AsyncClient`` is safe for
    concurrent use across coroutines, so ``embed`` calls interleave
    without an explicit lock.
    """

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        resolved_url = (
            base_url
            or os.environ.get("KOSMOS_OLLAMA_BASE_URL")
            or "http://127.0.0.1:11434"
        )
        resolved_model = (
            default_model
            or os.environ.get("KOSMOS_OLLAMA_EMBED_MODEL")
            or "nomic-embed-text"
        )
        self._base_url = resolved_url.rstrip("/")
        self._default_model = resolved_model
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    # ── Client lifecycle ────────────────────────────────────────────────────
    def _get_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("OllamaEmbeddingsAdapter is closed")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client

    # ── EmbeddingsPort ──────────────────────────────────────────────────────
    async def embed(
        self,
        *,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "input": texts,
        }
        try:
            resp = await self._get_client().post("/api/embed", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise EmbeddingError(
                f"Ollama /api/embed failed: {type(e).__name__}: {e}"
            ) from e

        data = resp.json()
        # Ollama native /api/embed response shape:
        #   {"model": "...", "embeddings": [[...], [...]], ...}
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingError(
                f"Ollama /api/embed returned malformed embeddings "
                f"(expected {len(texts)} vectors, got "
                f"{len(embeddings) if isinstance(embeddings, list) else 'non-list'})"
            )
        # Validate each vector is a list of floats. Bail on the whole
        # batch if any is not — never return partial results.
        for i, vec in enumerate(embeddings):
            if not isinstance(vec, list) or not vec:
                raise EmbeddingError(
                    f"Ollama /api/embed returned invalid vector at index {i}"
                )
        return embeddings

    # ── observability (ADR-124, Stage 11.8) ────────────────────────────────

    @property
    def model(self) -> str:
        """The configured embedder model name (e.g. ``nomic-embed-text``)."""
        return self._default_model

    @property
    def base_url(self) -> str:
        """The Ollama base URL this adapter embeds against."""
        return self._base_url

    async def dimensions(self, *, model: str | None = None) -> int:
        resolved = model or self._default_model
        # Strip Ollama version tag if present (e.g. "nomic-embed-text:latest")
        # — try both keyed lookups so callers can pass either form.
        dim = _MODEL_DIMENSIONS.get(resolved) or _MODEL_DIMENSIONS.get(
            resolved.split(":", 1)[0]
        )
        if dim is None:
            # Fallback: live probe with a single empty-ish input. Adapters
            # SHOULD extend _MODEL_DIMENSIONS to avoid the extra round-trip.
            probe = await self.embed(texts=["probe"], model=resolved)
            if not probe or not probe[0]:
                raise EmbeddingError(
                    f"Unable to determine dimensions for model {resolved!r}"
                )
            dim = len(probe[0])
            _MODEL_DIMENSIONS[resolved] = dim
        return dim

    def is_healthy(self) -> bool:
        if self._closed:
            return False
        # Reuse the shared client if constructed; otherwise a sync probe
        # against Ollama's tags endpoint. Non-throwing per ADR-023 rule 5.
        try:
            with httpx.Client(base_url=self._base_url, timeout=2.0) as c:
                resp = c.get("/api/tags")
                return resp.status_code == 200
        except Exception:  # noqa: BLE001 — health probe MUST NOT raise
            return False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001 — best-effort resource release
                log.debug("OllamaEmbeddingsAdapter close: aclose raised", exc_info=True)
            self._client = None
