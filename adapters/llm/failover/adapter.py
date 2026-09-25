"""FailoverLLMAdapter — composite LLMPort: primary + fallback with failback.

ADR-116 (Ratified 2026-09-25): llama.cpp on :8090 (Qwen3.8-27B) is the
primary LLM lane for Kosmos — the same shared inference server Hermes
Agent uses. Ollama (:11434) is fallback-only, engaged automatically when
the primary fails, with automatic failback (no operator action needed).

This is the *only* code that implements failover policy. The sub-adapters
(`LlamaSwapAdapter` for the OpenAI-/v1 transport, `OllamaAdapter` for the
native Ollama protocol) remain dumb transports.

Policy (ADR-116 §D1):

- Failover: on any transport/HTTP failure from the primary
  (``httpx.HTTPError``, ``ConnectionError``, ``TimeoutError``, ``OSError``)
  the same call is retried on the fallback. Non-transport exceptions
  (e.g. ``NotImplementedError`` from ``pull_model``) propagate — they are
  not backend failures.
- Streaming: failover can only engage *before the first delta is yielded*;
  after the first yield, errors propagate (mid-stream failover would
  duplicate tokens — rejected by design).
- Failback: the primary is sticky — every failing call retries the
  primary first before falling back, so a restarted llama-server is
  recovered on the next call with zero operator action.
- Telemetry: ``active_backend`` ("primary" | "fallback") reflects the
  backend serving the most recent completed call; ``failover_count``
  counts failover events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from ports.llm import LLMPort

# Transport/HTTP failure classes that count as "the backend is down".
# ConnectionError and TimeoutError are OSError subclasses;
# httpx.HTTPStatusError is an httpx.HTTPError subclass — both covered.
_BACKEND_ERRORS = (httpx.HTTPError, OSError)


class FailoverLLMAdapter:
    """Composite LLMPort: primary first, transparent fallback, failback.

    Satisfies the LLMPort Protocol at runtime (contract test asserts
    ``isinstance(FailoverLLMAdapter(...), LLMPort)``). All public methods
    use keyword-only kwargs (ADR-022 rule 1 parity with the sub-adapters).
    """

    def __init__(
        self,
        primary: LLMPort,
        fallback: LLMPort,
        *,
        failback: bool = True,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        # failback=True (default) is the ADR-116 policy: retry primary
        # first on every call. failback=False pins to the fallback once
        # engaged (kept for tests; not a documented operator knob).
        self._failback = failback
        self._pinned: str | None = None  # "fallback" once pinned
        self.active_backend: str = "primary"
        self.failover_count: int = 0

    # ── internal ───────────────────────────────────────────────────────────

    def _backends(self) -> tuple[LLMPort, LLMPort]:
        if self._failback or self._pinned is None:
            return self._primary, self._fallback
        return self._fallback, self._primary

    # ── Inference (non-streaming) ──────────────────────────────────────────

    async def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        first, second = self._backends()
        try:
            result = await first.generate(
                prompt=prompt, model=model, system=system, **options
            )
            self.active_backend = "primary" if first is self._primary else "fallback"
            return result
        except _BACKEND_ERRORS:
            self._engage_fallback(second)
            return await second.generate(
                prompt=prompt, model=model, system=system, **options
            )

    async def generate_text(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> str:
        first, second = self._backends()
        try:
            text = await first.generate_text(
                prompt=prompt, model=model, system=system, **options
            )
            self.active_backend = "primary" if first is self._primary else "fallback"
            return text
        except _BACKEND_ERRORS:
            self._engage_fallback(second)
            return await second.generate_text(
                prompt=prompt, model=model, system=system, **options
            )

    async def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        first, second = self._backends()
        try:
            result = await first.chat(messages=messages, model=model, **options)
            self.active_backend = "primary" if first is self._primary else "fallback"
            return result
        except _BACKEND_ERRORS:
            self._engage_fallback(second)
            return await second.chat(messages=messages, model=model, **options)

    # ── Inference (streaming) ──────────────────────────────────────────────

    def generate_stream(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> AsyncIterator[str]:
        return self._stream_failover(
            prompt=prompt, model=model, system=system, **options
        )

    async def _stream_failover(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> AsyncIterator[str]:
        first, second = self._backends()
        it = first.generate_stream(prompt=prompt, model=model, system=system, **options)
        try:
            head = await it.__anext__()
        except StopAsyncIteration:
            # Primary stream completed empty — a success, no failover.
            self.active_backend = "primary" if first is self._primary else "fallback"
            return
        except _BACKEND_ERRORS:
            # Failover before the first delta: no tokens were emitted, so
            # retrying on the fallback cannot duplicate content.
            self._engage_fallback(second)
            fallback_it = second.generate_stream(
                prompt=prompt, model=model, system=system, **options
            )
            async for chunk in fallback_it:
                yield chunk
            return
        self.active_backend = "primary" if first is self._primary else "fallback"
        yield head
        # Post-first-yield errors propagate (no mid-stream failover).
        async for chunk in it:
            yield chunk

    # ── Embeddings ─────────────────────────────────────────────────────────

    async def embed(
        self,
        *,
        input: str | list[str],
        model: str | None = None,
    ) -> dict[str, Any]:
        first, second = self._backends()
        try:
            result = await first.embed(input=input, model=model)
            self.active_backend = "primary" if first is self._primary else "fallback"
            return result
        except _BACKEND_ERRORS:
            self._engage_fallback(second)
            return await second.embed(input=input, model=model)

    # ── Model management ───────────────────────────────────────────────────

    async def list_models(self) -> list[dict[str, Any]]:
        first, second = self._backends()
        try:
            models = await first.list_models()
            self.active_backend = "primary" if first is self._primary else "fallback"
            return models
        except _BACKEND_ERRORS:
            self._engage_fallback(second)
            return await second.list_models()

    async def pull_model(self, *, name: str, insecure: bool = False) -> dict[str, Any]:
        # Capability, not availability: NotImplementedError from the
        # primary means "primary can't manage weights" — consult the
        # fallback. Transport failures fail over like everything else.
        try:
            return await self._primary.pull_model(name=name, insecure=insecure)
        except NotImplementedError:
            return await self._fallback.pull_model(name=name, insecure=insecure)
        except _BACKEND_ERRORS:
            self._engage_fallback(self._fallback)
            return await self._fallback.pull_model(name=name, insecure=insecure)

    async def delete_model(self, *, name: str) -> None:
        try:
            await self._primary.delete_model(name=name)
        except NotImplementedError:
            await self._fallback.delete_model(name=name)
        except _BACKEND_ERRORS:
            self._engage_fallback(self._fallback)
            await self._fallback.delete_model(name=name)

    # ── Health & lifecycle ─────────────────────────────────────────────────

    async def is_healthy(self) -> bool:
        """Non-throwing (ADR-022 rule 3): healthy if *either* backend is up."""
        primary_ok = await self._primary.is_healthy()
        if primary_ok:
            self.active_backend = "primary"
            return True
        fallback_ok = await self._fallback.is_healthy()
        if fallback_ok:
            self.active_backend = "fallback"
        return fallback_ok

    async def close(self) -> None:
        """Close both sub-adapters; idempotent (both sub-adapters are)."""
        await self._primary.close()
        await self._fallback.close()

    # ── internal ───────────────────────────────────────────────────────────

    def _engage_fallback(self, second: LLMPort) -> None:
        self.failover_count += 1
        self.active_backend = "fallback"
        if not self._failback:
            self._pinned = "fallback"
        assert second is self._fallback
