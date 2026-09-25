"""Contract test — FailoverLLMAdapter (ADR-116, Stage 9.4).

Policy under test (ADR-116 §D1): primary-first, transparent failover on
transport/HTTP errors, pre-first-delta-only streaming failover, sticky
failback, non-throwing health, capability passthrough on model management.

All tests use stub adapters — no network, no GPU (ADR-116 §D4).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from adapters.llm.failover import FailoverLLMAdapter
from ports.llm import LLMPort


# ── stubs ─────────────────────────────────────────────────────────────────


class StubLLM:
    """Minimal LLMPort stub with scripted results/exceptions.

    ``calls`` records ``(method, kwargs)`` per invocation so tests can
    assert call order (the failback assertions depend on it).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = 0
        self.generate_result: dict[str, Any] = {"generated": name, "ok": True}
        self.chat_result: dict[str, Any] = {"message": {"content": name}, "ok": True}
        self.generate_raise: Exception | None = None
        self.stream_chunks: list[str] = [f"{name}-1", f"{name}-2"]
        self.stream_raise: Exception | None = None
        self.healthy: bool = True
        self.pull_raise: Exception | None = None

    # inference
    async def generate(self, *, prompt: str, model=None, system=None, **opts) -> dict[str, Any]:
        self.calls.append(("generate", dict(prompt=prompt, model=model, system=system, **opts)))
        if self.generate_raise:
            raise self.generate_raise
        return self.generate_result

    async def generate_text(self, *, prompt: str, model=None, system=None, **opts) -> str:
        self.calls.append(("generate_text", dict(prompt=prompt, model=model, system=system, **opts)))
        if self.generate_raise:
            raise self.generate_raise
        return self.generate_result["generated"]

    async def chat(self, *, messages: list[dict[str, str]], model=None, **opts) -> dict[str, Any]:
        self.calls.append(("chat", dict(messages=messages, model=model, **opts)))
        if self.generate_raise:
            raise self.generate_raise
        return self.chat_result

    def generate_stream(self, *, prompt: str, model=None, system=None, **opts) -> AsyncIterator[str]:
        self.calls.append(("generate_stream", dict(prompt=prompt, model=model, system=system, **opts)))
        return self._stream()

    async def _stream(self) -> AsyncIterator[str]:
        if self.stream_raise:
            raise self.stream_raise
        for chunk in self.stream_chunks:
            yield chunk

    # embeddings
    async def embed(self, *, input: str | list[str], model=None) -> dict[str, Any]:
        if self.generate_raise:
            raise self.generate_raise
        return {"input": [input] if isinstance(input, str) else input, "v": 1}

    # model management
    async def list_models(self) -> list[dict[str, Any]]:
        if self.generate_raise:
            raise self.generate_raise
        return [{"name": self.name}]

    async def pull_model(self, *, name: str, insecure: bool = False) -> dict[str, Any]:
        self.calls.append(("pull_model", dict(name=name)))
        if self.pull_raise:
            raise self.pull_raise
        return {"status": "ok"}

    async def delete_model(self, *, name: str) -> None:
        self.calls.append(("delete_model", dict(name=name)))
        if self.pull_raise:
            raise self.pull_raise

    # health & lifecycle
    async def is_healthy(self) -> bool:
        return self.healthy

    async def close(self) -> None:
        self.closed += 1


def _adapter(primary: StubLLM | None = None, fallback: StubLLM | None = None, **kw: Any) -> tuple[FailoverLLMAdapter, StubLLM, StubLLM]:
    p = primary or StubLLM("primary")
    f = fallback or StubLLM("fallback")
    return FailoverLLMAdapter(p, f, **kw), p, f


# ── 1. protocol conformance ───────────────────────────────────────────────


def test_failover_adapter_satisfies_llm_port_protocol() -> None:
    """The load-bearing assertion: consumers hold LLMPort, so the composite
    must satisfy the runtime-checkable Protocol (ADR-116 §D1)."""
    adapter, _, _ = _adapter()
    assert isinstance(adapter, LLMPort), (
        "FailoverLLMAdapter does not satisfy LLMPort — check method signatures"
    )


# ── 2. happy path: primary serves, fallback untouched ────────────────────


@pytest.mark.parametrize("method", ["generate", "generate_text", "chat"])
async def test_happy_path_primary_serves(method: str) -> None:
    adapter, p, f = _adapter()
    if method == "generate":
        result = await adapter.generate(prompt="hi")
        assert result == p.generate_result
    elif method == "generate_text":
        assert await adapter.generate_text(prompt="hi") == "primary"
    else:
        result = await adapter.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == p.chat_result
    assert f.calls == [], "fallback must not be touched on the happy path"
    assert adapter.active_backend == "primary"
    assert adapter.failover_count == 0


# ── 3. failover on ConnectError ───────────────────────────────────────────


async def test_failover_on_connect_error() -> None:
    adapter, p, f = _adapter()
    p.generate_raise = httpx.ConnectError("connection refused")
    result = await adapter.generate(prompt="hi")
    assert result == f.generate_result
    assert adapter.active_backend == "fallback"
    assert adapter.failover_count == 1
    assert [c[0] for c in p.calls] == ["generate"]
    assert [c[0] for c in f.calls] == ["generate"]


# ── 4. failback: next call retries primary first ─────────────────────────


async def test_failback_retries_primary_first() -> None:
    adapter, p, f = _adapter()
    p.generate_raise = httpx.ConnectError("down")
    await adapter.generate(prompt="one")  # fails over
    assert adapter.active_backend == "fallback"

    p.generate_raise = None  # llama-server "restarts"
    result = await adapter.generate(prompt="two")  # must retry primary first
    assert result == p.generate_result
    assert adapter.active_backend == "primary"
    # call order on the second attempt: primary consulted, success
    assert [c[1]["prompt"] for c in p.calls] == ["one", "two"]
    assert [c[1]["prompt"] for c in f.calls] == ["one"]


# ── 5. both down: exception propagates, no silent success ────────────────


async def test_both_down_propagates() -> None:
    adapter, p, f = _adapter()
    p.generate_raise = httpx.ConnectError("primary down")
    f.generate_raise = httpx.ConnectError("fallback down")
    with pytest.raises(httpx.ConnectError):
        await adapter.generate(prompt="hi")
    assert adapter.failover_count == 1


# ── 6. streaming: failover pre-first-delta; post-yield propagates ────────


async def test_stream_failover_before_first_delta() -> None:
    adapter, p, f = _adapter()
    p.stream_raise = httpx.ConnectError("primary down")
    chunks = [c async for c in adapter.generate_stream(prompt="hi")]
    assert chunks == ["fallback-1", "fallback-2"]
    assert adapter.active_backend == "fallback"
    assert adapter.failover_count == 1


async def test_stream_post_first_yield_error_propagates() -> None:
    """Mid-stream failover would duplicate tokens — rejected by design."""
    p = StubLLM("primary")
    f = StubLLM("fallback")

    async def bad_stream() -> AsyncIterator[str]:
        yield "primary-1"
        raise httpx.ConnectError("died mid-stream")

    p.generate_stream = lambda **kw: bad_stream()  # type: ignore[method-assign]
    adapter = FailoverLLMAdapter(p, f)
    chunks: list[str] = []
    with pytest.raises(httpx.ConnectError):
        async for c in adapter.generate_stream(prompt="hi"):
            chunks.append(c)
    assert chunks == ["primary-1"], "partial output is delivered, then the error propagates"
    assert adapter.failover_count == 0, "no failover may engage after the first delta"
    assert f.calls == []


# ── 7. is_healthy: either-up semantics, never raises ─────────────────────


async def test_is_healthy_either_up() -> None:
    adapter, p, f = _adapter()
    p.healthy = False
    f.healthy = True
    assert await adapter.is_healthy() is True
    assert adapter.active_backend == "fallback"


async def test_is_healthy_both_down() -> None:
    """Both backends down -> False, still returned (not raised)."""
    adapter, p, f = _adapter()
    p.healthy = False
    f.healthy = False
    result = await adapter.is_healthy()  # must not raise
    assert result is False


# ── 8. model management: NotImplementedError -> fallback ─────────────────


async def test_pull_model_not_implemented_falls_through() -> None:
    adapter, p, f = _adapter()
    p.pull_raise = NotImplementedError("no pull here")
    result = await adapter.pull_model(name="some-model")
    assert result == {"status": "ok"}
    assert [c[0] for c in f.calls] == ["pull_model"]
    # capability passthrough is NOT a failover event
    assert adapter.failover_count == 0


async def test_delete_model_not_implemented_falls_through() -> None:
    adapter, p, f = _adapter()
    p.pull_raise = NotImplementedError("no delete here")
    await adapter.delete_model(name="some-model")
    assert [c[0] for c in f.calls] == ["delete_model"]


# ── 9. close() closes both exactly once ──────────────────────────────────


async def test_close_closes_both_sub_adapters() -> None:
    adapter, p, f = _adapter()
    await adapter.close()
    assert p.closed == 1
    assert f.closed == 1


# ── 10. keyword-only signature discipline (ADR-022 rule 1 parity) ───────


def test_public_methods_keyword_only() -> None:
    import inspect

    for name in ("generate", "generate_text", "chat", "generate_stream", "embed"):
        sig = inspect.signature(getattr(FailoverLLMAdapter, name))
        for pos, param in sig.parameters.items():
            if pos in ("self",):
                continue
            assert param.kind in (
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.VAR_KEYWORD,
            ), f"{name}.{pos} must be keyword-only"


# ── 11. initial telemetry state ──────────────────────────────────────────


def test_initial_telemetry_state() -> None:
    adapter, _, _ = _adapter()
    assert adapter.active_backend == "primary"
    assert adapter.failover_count == 0


# ── 12. 4xx model-not-found failover ─────────────────────────────────────


async def test_failover_on_model_not_found() -> None:
    """The exact misconfig class ADR-116 D2's env vars prevent: wrong
    default model on the primary lane -> 4xx -> fallback engaged."""
    adapter, p, f = _adapter()
    req = httpx.Request("POST", "http://127.0.0.1:8090/v1/chat/completions")
    err = httpx.HTTPStatusError(
        "model not found", request=req, response=httpx.Response(400, request=req)
    )
    p.generate_raise = err
    result = await adapter.generate(prompt="hi")
    assert result == f.generate_result
    assert adapter.active_backend == "fallback"
    assert adapter.failover_count == 1


# ── supplementary: non-transport exceptions do NOT fail over ─────────────


async def test_non_transport_exception_propagates() -> None:
    adapter, p, f = _adapter()
    p.generate_raise = ValueError("bad prompt shape")
    with pytest.raises(ValueError):
        await adapter.generate(prompt="hi")
    assert f.calls == []
    assert adapter.failover_count == 0


# ── supplementary: failback=False pins to fallback ───────────────────────


async def test_pinned_fallback_when_failback_disabled() -> None:
    adapter, p, f = _adapter(failback=False)
    p.generate_raise = httpx.ConnectError("down")
    await adapter.generate(prompt="one")
    p.generate_raise = None  # primary recovered...
    result = await adapter.generate(prompt="two")  # ...but we stay pinned
    assert result == f.generate_result
    assert [c[1]["prompt"] for c in f.calls] == ["one", "two"]
    assert [c[1]["prompt"] for c in p.calls] == ["one"]
