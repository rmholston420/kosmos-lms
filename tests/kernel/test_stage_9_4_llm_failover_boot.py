"""Stage 9.4 · ADR-116 D4 — kernel LLM boot test.

Drives ``kernel/app.py::_build_llm_adapter`` (the module-level constructor
the lifespan ``_boot_llm`` delegates to) with monkeypatched env — no live
servers, no full-lifespan boot, no GPU. Proves the kernel's ``registry.llm``
is a FailoverLLMAdapter whose primary/fallback lanes are the exact concrete
adapters and read the ADR-116 D3 env matrix, and that the default (unset)
config degrades to the pre-ADR-116 behavior (llama-swap sidecar :8080
primary, which then fails over to Ollama).
"""

from __future__ import annotations

import pytest

from adapters.llm.failover import FailoverLLMAdapter
from adapters.llm.llama_swap import LlamaSwapAdapter
from adapters.llm.ollama.adapter import OllamaAdapter
from ports.llm import LLMPort

# ADR-116 D2 env values (verified live against the :8090 llama-server).
_COLOSSUS = {
    "KOSMOS_LLAMA_SWAP_BASE_URL": "http://127.0.0.1:8090",
    "KOSMOS_LLAMA_SWAP_DEFAULT_MODEL": "qwen3.8-27b-code",
    "KOSMOS_OLLAMA_DEFAULT_MODEL": "qwen3-vl:4b",
}


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "KOSMOS_LLAMA_SWAP_BASE_URL",
        "KOSMOS_LLAMA_SWAP_DEFAULT_MODEL",
        "KOSMOS_OLLAMA_BASE_URL",
        "KOSMOS_OLLAMA_DEFAULT_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def _sub_adapters(llm: FailoverLLMAdapter) -> tuple[LlamaSwapAdapter, OllamaAdapter]:
    """isinstance-narrow the sub-adapters to their concrete classes.

    Doubles as an assertion: the kernel must wire the *exact* transports
    (LlamaSwap primary, Ollama fallback) — not a stand-in.
    """
    assert isinstance(llm, FailoverLLMAdapter)
    assert isinstance(llm, LLMPort), "composite must satisfy LLMPort at runtime"
    primary, fallback = llm._primary, llm._fallback
    assert isinstance(primary, LlamaSwapAdapter)
    assert isinstance(fallback, OllamaAdapter)
    return primary, fallback


# ---------------------------------------------------------------------------
# 1. Colossus env -> primary :8090 / qwen3.8-27b-code, fallback :11434 / qwen3-vl:4b
# ---------------------------------------------------------------------------


def test_colossus_env_selects_primary_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    for k, v in _COLOSSUS.items():
        monkeypatch.setenv(k, v)

    from kernel.app import _build_llm_adapter

    llm = _build_llm_adapter()
    # Initial telemetry state (ADR-116 §D1).
    assert llm.active_backend == "primary"
    assert llm.failover_count == 0

    primary, fallback = _sub_adapters(llm)
    # Primary lane: the shared llama.cpp server, exact model it advertises.
    assert primary._base_url == "http://127.0.0.1:8090"
    assert primary._default_model == "qwen3.8-27b-code"
    # Fallback lane: Ollama default base (:11434) with the pinned VL model.
    assert fallback._base_url == "http://127.0.0.1:11434"
    assert fallback._default_model == "qwen3-vl:4b"


# ---------------------------------------------------------------------------
# 2. Unset env -> pre-ADR-116 degrade (llama-swap :8080 primary, Ollama fb)
# ---------------------------------------------------------------------------


def test_unset_env_degrades_to_sidecar_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)

    from kernel.app import _build_llm_adapter

    llm = _build_llm_adapter()
    primary, fallback = _sub_adapters(llm)
    # Adapter defaults: llama-swap sidecar (:8080, qwen3:14b-q8_0). Every call
    # then fails over to Ollama = the pre-ADR-116 behavior (ADR-116 §D2).
    assert primary._base_url == "http://127.0.0.1:8080"
    assert primary._default_model == "qwen3:14b-q8_0"
    # Ollama base still defaults to :11434.
    assert fallback._base_url == "http://127.0.0.1:11434"


# ---------------------------------------------------------------------------
# 3. Ollama base URL override reaches the fallback lane
# ---------------------------------------------------------------------------


def test_ollama_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("KOSMOS_OLLAMA_BASE_URL", "http://127.0.0.1:11435")

    from kernel.app import _build_llm_adapter

    llm = _build_llm_adapter()
    _, fallback = _sub_adapters(llm)
    assert fallback._base_url == "http://127.0.0.1:11435"


# ---------------------------------------------------------------------------
# 4. Builder is deterministic (no shared state across invocations)
# ---------------------------------------------------------------------------


def test_builder_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    for k, v in _COLOSSUS.items():
        monkeypatch.setenv(k, v)

    from kernel.app import _build_llm_adapter

    a, b = _build_llm_adapter(), _build_llm_adapter()
    pa, fa = _sub_adapters(a)
    pb, fb = _sub_adapters(b)
    assert a is not b
    assert pa._base_url == pb._base_url
    assert pa._default_model == pb._default_model
    assert fa._default_model == fb._default_model
