"""adapters.embeddings.llama.adapter — LlamaEmbeddingsAdapter (ADR-124).

Primary ``EmbeddingsPort`` implementation for the llama.cpp embedder
(``qwen3-embedding-0.6b`` on ``:8091``), served via llama-server's
OpenAI-compatible ``/v1/embeddings`` endpoint.

Why a sibling adapter (not a re-pointed Ollama adapter):
- llama-server speaks the OpenAI-compat protocol (``/v1/embeddings``),
  Ollama speaks its native ``/api/embed`` — different request/response
  shapes, different auth semantics (none), different model catalog
  endpoint (``/v1/models`` vs ``/api/tags``).
- The embedder runs CPU-only by design (``--device none`` in the
  ``llama-embedder-8091`` user service) to keep the RTX 5090's 32 GB
  free for the 27B primary lane on :8090.

Env vars (constructor args override):
    KOSMOS_EMBEDDER_BASE_URL   llama-server root, defaults to
                               ``http://127.0.0.1:8091`` (no ``/v1``
                               suffix — this adapter adds it).
    KOSMOS_EMBEDDER_MODEL      Default model, defaults to
                               ``qwen3-embedding-0.6b`` (1024-dim).

References:
    - ADR-124 (this adapter's authority)
    - ADR-073 (EmbeddingsPort contract)
    - `ports/embeddings.py` (protocol contract)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ports.embeddings import EmbeddingError, EmbeddingsPort

log = logging.getLogger(__name__)


# Static model → dimension table (ADR-073 contract: ``dimensions()``
# should NOT need a live probe on collection-create).
_MODEL_DIMENSIONS: dict[str, int] = {
    "qwen3-embedding-0.6b": 1024,
    "qwen3-embedding-0.6b:latest": 1024,
    "qwen3-embedding-4b": 2560,
}


class LlamaEmbeddingsAdapter:
    """Native ``/v1/embeddings`` adapter satisfying ``EmbeddingsPort``.

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
            or os.environ.get("KOSMOS_EMBEDDER_BASE_URL")
            or "http://127.0.0.1:8091"
        )
        resolved_model = (
            default_model
            or os.environ.get("KOSMOS_EMBEDDER_MODEL")
            or "qwen3-embedding-0.6b"
        )
        # Normalise: accept either the root or a pre-suffixed /v1 URL.
        resolved_url = resolved_url.rstrip("/")
        if resolved_url.endswith("/v1"):
            resolved_url = resolved_url[: -len("/v1")]
        self._base_url = resolved_url
        self._default_model = resolved_model
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    # ── Client lifecycle ────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise EmbeddingError("LlamaEmbeddingsAdapter is closed")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout
            )
        return self._client

    # ── EmbeddingsPort ──────────────────────────────────────────────────

    async def embed(
        self,
        *,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Embed ``texts`` (batch-only, per ADR-073) via ``/v1/embeddings``.

        Raises ``EmbeddingError`` on any HTTP/protocol failure — the
        whole batch fails atomically (no partial results).
        """
        resolved = model or self._default_model
        client = self._get_client()
        try:
            resp = await client.post(
                "/v1/embeddings",
                json={"model": resolved, "input": texts},
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                f"embed request failed: {type(exc).__name__}: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise EmbeddingError(
                f"embed HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data: dict[str, Any] = resp.json()
            rows = sorted(data["data"], key=lambda d: d["index"])
            embeddings = [list(d["embedding"]) for d in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError(
                f"malformed /v1/embeddings response: {exc}"
            ) from exc
        if len(embeddings) != len(texts):
            raise EmbeddingError(
                f"embed count mismatch: got {len(embeddings)}, "
                f"want {len(texts)}"
            )
        return embeddings

    async def dimensions(self, *, model: str | None = None) -> int:
        resolved = model or self._default_model
        dim = _MODEL_DIMENSIONS.get(resolved)
        if dim is None:
            # Fallback: live probe with a single short input. Adapters
            # SHOULD extend _MODEL_DIMENSIONS to avoid the round-trip.
            probe = await self.embed(texts=["probe"], model=resolved)
            if not probe or not probe[0]:
                raise EmbeddingError(
                    f"Unable to determine dimensions for model {resolved!r}"
                )
            dim = len(probe[0])
            _MODEL_DIMENSIONS[resolved] = dim
        return dim

    def is_healthy(self) -> bool:
        """Sync + non-throwing readiness probe (ADR-023 rule 5)."""
        if self._closed:
            return False
        try:
            with httpx.Client(base_url=self._base_url, timeout=2.0) as c:
                resp = c.get("/health")
                if resp.status_code != 200:
                    return False
                body = resp.json()
                return body.get("status") == "ok"
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
                log.debug(
                    "LlamaEmbeddingsAdapter close: aclose raised", exc_info=True
                )
            self._client = None

    # ── observability (ADR-124, Stage 11.8) ─────────────────────────────

    @property
    def model(self) -> str:
        """The configured embedder model name (e.g. ``qwen3-embedding-0.6b``)."""
        return self._default_model

    @property
    def base_url(self) -> str:
        """The llama-server root URL this adapter embeds against."""
        return self._base_url


__all__ = ["LlamaEmbeddingsAdapter"]
