"""Consolidated Ollama adapter — Stage 1.1 (ADR-012).

Merges three donor sources:

- Rigpa-LMS/backend/src/rigpa/core/llm/ollama.py       (async client, singleton, chat + generate + embed + models + lifecycle)
- Rigpa-LMS/backend/src/rigpa/domains/integrations/ollama.py  (model list/pull/delete — folded in)
- axiom/packages/axiom_providers/ollama.py            (streaming — added)

Design rules from ADR-012 and Kosmos-Build-Spec-v25.md §4:
    - Keyword-only kwargs across the public API
    - No plugin imports this module directly (ADR-007); go via LLMPort protocol
    - Reuse a single httpx.AsyncClient (avoid per-call socket churn)
    - is_healthy() is cheap and non-throwing
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def _default_base_url() -> str:
    return os.environ.get("KOSMOS_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def _default_model() -> str:
    return os.environ.get("KOSMOS_OLLAMA_DEFAULT_MODEL", "llama3.1:latest")


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class OllamaAdapter:
    """Async client for the local Ollama HTTP API.

    Implements the LLMPort Protocol (see `ports/llm.py`; formalized in
    Stage 1.2 per ADR-022 — LLMPort surface expansion). Contract test in
    `test_contract.py` asserts `isinstance(OllamaAdapter(), LLMPort)` at
    runtime.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout_seconds: float = 120.0,
        max_concurrent: int = 1,
    ) -> None:
        self._base_url = (base_url or _default_base_url()).rstrip("/")
        self._default_model = default_model or _default_model()
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )
        # GPU-share guard: the shared llama-server (port 8090) runs
        # --parallel 2 so Hermes and Kosmos can interleave; this semaphore
        # keeps the Kosmos lane to one in-flight generation at a time so
        # it can never occupy both slots and starve the Hermes lane.
        self._gen_sem = asyncio.Semaphore(max(1, max_concurrent))

    # ── Generation (non-streaming) ─────────────────────────────────────────

    async def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        """POST /api/generate — returns the full response dict."""
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options

        async with self._gen_sem:
            resp = await self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def generate_text(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> str:
        """Convenience: return only the response text."""
        data = await self.generate(
            prompt=prompt, model=model, system=system, **options
        )
        return str(data.get("response", ""))

    # ── Generation (streaming) — from axiom donor ──────────────────────────

    async def generate_stream(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> AsyncIterator[str]:
        """Stream text deltas from Ollama /api/chat (streaming mode).

        Yields only non-empty content deltas; terminates on the `done: true`
        frame.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options

        async with self._gen_sem:
            async with self._client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break

    # ── Chat ───────────────────────────────────────────────────────────────

    async def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        """POST /api/chat — multi-turn, non-streaming."""
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        async with self._gen_sem:
            resp = await self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()

    # ── Embeddings ─────────────────────────────────────────────────────────

    async def embed(
        self,
        *,
        input: str | list[str],
        model: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/embed — return raw response dict with embeddings.

        .. deprecated:: ADR-073 (Ratified v25 2026-08-01)
           Use ``adapters.embeddings.ollama.adapter.OllamaEmbeddingsAdapter``
           via ``ports.embeddings.EmbeddingsPort`` instead.
        """
        import warnings

        warnings.warn(
            "OllamaAdapter.embed() is deprecated per ADR-073. "
            "Use OllamaEmbeddingsAdapter via EmbeddingsPort.",
            DeprecationWarning,
            stacklevel=2,
        )
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "input": input,
        }
        resp = await self._client.post("/api/embed", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Model management ───────────────────────────────────────────────────

    async def list_models(self) -> list[dict[str, Any]]:
        """GET /api/tags — return list of installed model dicts.

        Returns raw dicts, not typed schemas — the domain-integrations
        typed-schema variant from Rigpa is folded away per ADR-012.
        """
        resp = await self._client.get("/api/tags")
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("models", []))

    async def pull_model(self, *, name: str, insecure: bool = False) -> dict[str, Any]:
        """POST /api/pull — download a model."""
        payload: dict[str, Any] = {"name": name, "stream": False}
        if insecure:
            payload["insecure"] = True
        resp = await self._client.post(
            "/api/pull", json=payload, timeout=httpx.Timeout(600.0, connect=10.0)
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_model(self, *, name: str) -> None:
        """DELETE /api/delete — remove a model."""
        # httpx AsyncClient.delete does not accept `json=` on DELETE with body;
        # use request() with content= to send the JSON body explicitly.
        resp = await self._client.request(
            "DELETE",
            "/api/delete",
            content=json.dumps({"name": name}).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

    # ── Health & lifecycle ─────────────────────────────────────────────────

    async def is_healthy(self) -> bool:
        """GET / — non-throwing health probe."""
        try:
            resp = await self._client.get("/", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_adapter: OllamaAdapter | None = None


def get_ollama_adapter() -> OllamaAdapter:
    """Return the shared OllamaAdapter, creating it on first call."""
    global _adapter
    if _adapter is None:
        _adapter = OllamaAdapter()
    return _adapter


async def close_ollama_adapter() -> None:
    """Close the shared OllamaAdapter on app shutdown."""
    global _adapter
    if _adapter is not None:
        await _adapter.close()
        _adapter = None
