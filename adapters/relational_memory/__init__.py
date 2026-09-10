"""adapters.relational_memory — RelationalMemoryPort implementations (ADR-102).

Two adapters ship at Stage 8.0:

- :class:`NoOpRelationalMemoryAdapter` — aiosqlite in-memory, CI + dev.
- :class:`PostgresRelationalMemoryAdapter` — asyncpg + pgvector, production.

Selection is driven by the kernel via the ``KOSMOS_RELATIONAL_MEMORY``
env var (see :mod:`kernel.app._boot_relational_memory`).
"""

from .noop import NoOpRelationalMemoryAdapter

# Postgres adapter deps (asyncpg + pgvector) are optional at import time —
# gate the import so environments without them still boot.
try:
    from .postgres import PostgresRelationalMemoryAdapter  # noqa: F401
except ImportError:  # pragma: no cover
    PostgresRelationalMemoryAdapter = None  # type: ignore[assignment]

__all__ = ["NoOpRelationalMemoryAdapter", "PostgresRelationalMemoryAdapter"]
