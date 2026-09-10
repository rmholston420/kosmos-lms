"""adapters.session — SessionPort adapters (ADR-103).

Two adapters ship at Stage 8.1:

- :class:`~adapters.session.inmemory.adapter.InMemorySessionAdapter` —
  port-clean asyncio-lock-protected in-memory adapter (CI-required).
- :class:`~adapters.session.tektos.adapter.TektosSessionAdapter` —
  fidelity port of the tektos-ultima donor FSM + SessionManager.

The tektos adapter is import-gated (its vendor tree imports lazily)
so the in-memory branch can be used in environments where the tektos
donor is not vendored.
"""

from __future__ import annotations

from adapters.session.inmemory.adapter import InMemorySessionAdapter

__all__ = ["InMemorySessionAdapter"]

try:
    from adapters.session.tektos.adapter import TektosSessionAdapter  # noqa: F401

    __all__.append("TektosSessionAdapter")
except Exception:  # pragma: no cover — surfaced by import-tier tests
    pass
