"""adapters.relational_memory.noop — aiosqlite in-memory adapter (ADR-102 D2).

Required for CI and dev environments without Postgres. Uses aiosqlite as an
in-process, zero-dependency SQL engine. pgvector shape stored as JSON blob
(``search_narratives`` falls back to full-text-scan over ``body`` when only
tsvector-equivalent is available).

Vendored dependency: ``aiosqlite`` (MIT, ships with stdlib sqlite3 module).
"""

from .adapter import NoOpRelationalMemoryAdapter

__all__ = ["NoOpRelationalMemoryAdapter"]
