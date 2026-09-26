"""plugins.tektos.memory — Tektos cognitive memory (3-tier store + transfer log).

**ADR-141 T6 (2026-09-25):** donor ``MemoryPersistence`` port
(``persistence.py``) — the working / long_term / procedural tier store with
transfer log, per-tier decay, and the background decay scheduler. Per the
ADR-135 user decision this is Tektos cognitive *policy* (plugin layer),
booted by the ``kernel/app.py`` composition root (ADR-007: the plugin is
wired by the kernel, never the reverse).
"""

from plugins.tektos.memory.persistence import MemoryPersistence

__all__ = ["MemoryPersistence"]
