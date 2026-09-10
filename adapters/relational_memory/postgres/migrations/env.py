"""Alembic env — reads DSN from KOSMOS_POSTGRES_URI at runtime.

Design notes:
- We do NOT define SQLAlchemy models here; the schema is authored as raw
  SQL in the version files (Postgres-specific: tsvector generated columns,
  pgvector, pg_uuidv7). This matches ADR-102 D3 (asyncpg + raw SQL, no ORM).
- URL is pulled from env each run so operators can point at different
  environments (dev/staging/prod) without editing alembic.ini.
- Async run — asyncpg is our runtime driver; using it here keeps migration
  and app on the same driver family.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    url = os.environ.get("KOSMOS_POSTGRES_URI")
    if not url:
        sys.stderr.write(
            "alembic: KOSMOS_POSTGRES_URI is not set. Export it before running "
            "migrations, e.g.:\n"
            "  export KOSMOS_POSTGRES_URI=postgres://kosmos@localhost:5432/kosmos\n"
        )
        raise SystemExit(2)
    # SQLAlchemy needs the +asyncpg driver suffix; asyncpg's asyncpg.connect
    # accepts the bare postgres:// form. Normalize here.
    if url.startswith("postgres://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _resolve_url()

    engine = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
