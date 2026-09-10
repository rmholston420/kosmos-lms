"""adapters.relational_memory.postgres — asyncpg + pgvector adapter (ADR-102 D2).

Production backend. Postgres 18 + pgvector 0.8.1 + pg_uuidv7 (all OSS,
permissive licenses). Alembic migrations at
``adapters/relational_memory/postgres/migrations/``.

Kernel wiring env vars:

- ``KOSMOS_RELATIONAL_MEMORY=postgres``
- ``KOSMOS_POSTGRES_URI=postgres://kosmos@localhost:5432/kosmos``

Migration workflow (per ADR-102 D7 — no auto-migrate on boot):

    export KOSMOS_POSTGRES_URI=postgres://kosmos:secret@localhost:5432/kosmos
    alembic -c adapters/relational_memory/postgres/migrations/alembic.ini upgrade head

Vendored dependencies (per PORTING_LEDGER):

- asyncpg 0.31.0 (Apache-2.0)
- pgvector 0.5.0 (MIT) — Python client for pgvector Postgres extension
- alembic 1.19.2 (MIT) — SQL migration framework
"""

from .adapter import PostgresRelationalMemoryAdapter

__all__ = ["PostgresRelationalMemoryAdapter"]
