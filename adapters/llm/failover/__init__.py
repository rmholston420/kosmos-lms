"""Composite LLMPort adapter: primary + fallback with automatic failback.

ADR-116 (Ratified 2026-09-25): llama.cpp :8090 (Qwen3.8-27B) is the
primary LLM lane for Kosmos (the same shared inference server Hermes
Agent uses); Ollama :11434 is fallback-only, engaged automatically when
the primary fails, with automatic failback. This adapter is the only
code that implements that policy; the sub-adapters stay dumb transports.
"""

from adapters.llm.failover.adapter import FailoverLLMAdapter

__all__ = ["FailoverLLMAdapter"]
