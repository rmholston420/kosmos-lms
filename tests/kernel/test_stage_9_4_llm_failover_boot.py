"""Stage 9.4 · ADR-116 D4 — kernel LLM boot test.

Drives ``kernel/app.py::_build_llm_adapter`` (the module-level constructor
the lifespan ``_boot_llm`` delegates to) with monkeypatched env — no live
servers, no full-lifespan boot, no GPU. Proves the kernel's ``registry.llm``
is a FailoverLLMAdapter whose primary/fallback lanes are the exact concrete
adapters and read the ADR-116/ADR-132 env matrix, and that the default
(unset) config degrades to the sidecar primary (:8080) with the Collosus
CPU-fallback defaults (:8092).

ADR-132 (2026-09-25) rewire: the fallback lane is the CPU llama.cpp server
(:8092, granite4.1-8b-instruct) — NOT the Ollama lane (:11434), which is
retired from the failover path. The vision lane is llama.cpp Qwen3-VL on
:8094 and is not part of the text failover composite.
"""

from __future__ import annotations

import pytest

from adapters.llm.failover import FailoverLLMAdapter
from adapters.llm.llama_swap import LlamaSwapAdapter
from ports.llm import LLMPort

# ADR-116 D2 / ADR-132 env values (verified live against the :8090 and
# :8092 llama-servers).
_COLOSSUS = {
    "KOSMOS_LLAMA_SWAP_BASE_URL": "http://127.0.0.1:8090",
    "KOSMOS_LLAMA_SWAP_DEFAULT_MODEL": "qwen3.8-27b-code",
    "KOSMOS_LLM_FALLBACK_BASE_URL": "http://127.0.0.1:8092",
    "KOSMOS_LLM_FALLBACK_MODEL": "granite4.1-8b-instruct",
}


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "KOSMOS_LLAMA_SWAP_BASE_URL",
        "KOSMOS_LLAMA_SWAP_DEFAULT_MODEL",
        "KOSMOS_LLM_FALLBACK_BASE_URL",
        "KOSMOS_LLM_FALLBACK_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def _sub_adapters(llm: FailoverLLMAdapter) -> tuple[LlamaSwapAdapter, LlamaSwapAdapter]:
    """isinstance-narrow the sub-adapters to their concrete classes.

    Doubles as an assertion: the kernel must wire the *exact* transports
    (LlamaSwap primary, LlamaSwap CPU fallback) — not a stand-in, and not
    the retired Ollama fallback.
    """
    assert isinstance(llm, FailoverLLMAdapter)
    assert isinstance(llm, LLMPort), "composite must satisfy LLMPort at runtime"
    primary, fallback = llm._primary, llm._fallback
    assert isinstance(primary, LlamaSwapAdapter)
    assert isinstance(fallback, LlamaSwapAdapter)
    return primary, fallback


# ---------------------------------------------------------------------------
# 1. Collosus env -> primary :8090 / qwen3.8-27b-code, fallback :8092 /
#    granite4.1-8b-instruct
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
    # Primary lane: the shared llama.cpp GPU server, exact model it
    # advertises.
    assert primary._base_url == "http://127.0.0.1:8090"
    assert primary._default_model == "qwen3.8-27b-code"
    # Fallback lane: CPU llama.cpp :8092 with the resident Granite model.
    assert fallback._base_url == "http://127.0.0.1:8092"
    assert fallback._default_model == "granite4.1-8b-instruct"


# ---------------------------------------------------------------------------
# 2. Unset env -> sidecar primary (:8080) + Collosus CPU-fallback defaults
# ---------------------------------------------------------------------------


def test_unset_env_degrades_to_sidecar_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)

    from kernel.app import _build_llm_adapter

    llm = _build_llm_adapter()
    primary, fallback = _sub_adapters(llm)
    # Adapter default: llama-swap sidecar (:8080, qwen3:14b-q8_0). The
    # builder pins the fallback to the Collosus CPU defaults when no
    # KOSMOS_LLM_FALLBACK_* env is set.
    assert primary._base_url == "http://127.0.0.1:8080"
    assert primary._default_model == "qwen3:14b-q8_0"
    assert fallback._base_url == "http://127.0.0.1:8092"
    assert fallback._default_model == "granite4.1-8b-instruct"


# ---------------------------------------------------------------------------
# 3. Fallback base URL override reaches the fallback lane
# ---------------------------------------------------------------------------


def test_fallback_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("KOSMOS_LLM_FALLBACK_BASE_URL", "http://127.0.0.1:8093")
    monkeypatch.setenv("KOSMOS_LLM_FALLBACK_MODEL", "granite4.1-8b-instruct")

    from kernel.app import _build_llm_adapter

    llm = _build_llm_adapter()
    _, fallback = _sub_adapters(llm)
    assert fallback._base_url == "http://127.0.0.1:8093"
    assert fallback._default_model == "granite4.1-8b-instruct"


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
    assert fa._base_url == fb._base_url
    assert fa._default_model == fb._default_model
