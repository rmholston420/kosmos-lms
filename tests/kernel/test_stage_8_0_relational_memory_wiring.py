"""Stage 8.0 — kernel-boot RelationalMemoryPort wiring (ADR-102).

Fast-tier tests over the ``KOSMOS_RELATIONAL_MEMORY`` env-gate wired into
``kernel/app.py::_boot_relational_memory``. Six scenarios per ADR-102 D6:

1. Unset               -> relational_memory=None; no error registered.
2. Explicit ``off``    -> same as unset (silent).
3. ``noop``            -> NoOpRelationalMemoryAdapter wired.
4. ``postgres`` without KOSMOS_POSTGRES_URI -> registry.errors[...] set.
5. ``postgres`` with unreachable DSN        -> relational_memory=None with warning.
6. Unknown value ``mystery``                -> registry.errors[...] set.

Zero live I/O: the postgres adapter constructs lazily (pool opened on
first async call), and ``is_healthy()`` is a non-throwing sync check. So
Cloud CI can drive every path without a running Postgres.
"""

from __future__ import annotations

import os

# --- Env preamble: pin safe defaults; each test overrides selectively. -----
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("KOSMOS_MEMORY_LEXICAL", None)
os.environ.pop("KOSMOS_RELATIONAL_MEMORY", None)
os.environ.pop("KOSMOS_POSTGRES_URI", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _reset_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str | None,
    dsn: str | None = None,
) -> None:
    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")
    monkeypatch.delenv("KOSMOS_MEMORY_LEXICAL", raising=False)
    if mode is None:
        monkeypatch.delenv("KOSMOS_RELATIONAL_MEMORY", raising=False)
    else:
        monkeypatch.setenv("KOSMOS_RELATIONAL_MEMORY", mode)
    if dsn is None:
        monkeypatch.delenv("KOSMOS_POSTGRES_URI", raising=False)
    else:
        monkeypatch.setenv("KOSMOS_POSTGRES_URI", dsn)


def _drive_lifespan_and_inspect():
    from kernel import app as kernel_app_module

    with TestClient(kernel_app_module.app) as _:
        pass
    return kernel_app_module.registry


# ---------------------------------------------------------------------------
# Test 1 — unset -> silent None
# ---------------------------------------------------------------------------


def test_unset_leaves_relational_memory_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, mode=None)

    registry = _drive_lifespan_and_inspect()

    assert registry.relational_memory is None, (
        "relational_memory must default to None when KOSMOS_RELATIONAL_MEMORY "
        "is unset (ADR-102 D6)."
    )
    assert "relational_memory" not in registry.errors, (
        f"unset should not register an error; got "
        f"errors={registry.errors.get('relational_memory')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — off -> silent None (same as unset)
# ---------------------------------------------------------------------------


def test_explicit_off_leaves_relational_memory_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, mode="off")

    registry = _drive_lifespan_and_inspect()

    assert registry.relational_memory is None
    assert "relational_memory" not in registry.errors


# ---------------------------------------------------------------------------
# Test 3 — noop -> NoOpRelationalMemoryAdapter wired
# ---------------------------------------------------------------------------


def test_noop_wires_aiosqlite_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_env(monkeypatch, mode="noop")

    registry = _drive_lifespan_and_inspect()

    assert registry.relational_memory is not None, (
        f"noop must wire the adapter; errors={registry.errors!r}"
    )
    from adapters.relational_memory import NoOpRelationalMemoryAdapter

    assert isinstance(registry.relational_memory, NoOpRelationalMemoryAdapter)
    assert registry.relational_memory.is_healthy() is True


# ---------------------------------------------------------------------------
# Test 4 — postgres without KOSMOS_POSTGRES_URI -> registry.errors set
# ---------------------------------------------------------------------------


def test_postgres_without_dsn_registers_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, mode="postgres", dsn=None)

    registry = _drive_lifespan_and_inspect()

    assert registry.relational_memory is None
    err = registry.errors.get("relational_memory", "")
    assert "KOSMOS_POSTGRES_URI" in err, (
        f"error must name the missing env var; got {err!r}"
    )
    assert "ADR-102" in err, (
        f"error should reference ADR-102 for traceability; got {err!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — postgres with unreachable DSN -> None with warning (no crash)
# ---------------------------------------------------------------------------


def test_postgres_with_dsn_degrades_gracefully_when_pool_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a DSN provided, the adapter constructs; is_healthy() is a sync
    non-throwing check that returns True on construction. The pool is
    opened lazily on the first async call. So Stage 8.0 boots into a
    "constructed but unverified" state — matching ADR-101's pattern where
    DozerDbGraphBackend also defers connection to first use.
    """
    _reset_env(
        monkeypatch,
        mode="postgres",
        dsn="postgres://kosmos@localhost:15432/nonexistent",  # unroutable port
    )

    registry = _drive_lifespan_and_inspect()

    # Construction succeeds; the actual connection failure will surface on
    # first async call. This is the same "lazy driver" pattern as ADR-100 D1.
    from adapters.relational_memory import PostgresRelationalMemoryAdapter

    if PostgresRelationalMemoryAdapter is None:  # asyncpg not installed
        assert registry.relational_memory is None
        return

    assert registry.relational_memory is not None, (
        f"adapter should construct even without a live pool; "
        f"errors={registry.errors!r}"
    )
    assert isinstance(registry.relational_memory, PostgresRelationalMemoryAdapter)


# ---------------------------------------------------------------------------
# Test 6 — unknown value -> registry.errors set with allowed enum
# ---------------------------------------------------------------------------


def test_unknown_mode_registers_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_env(monkeypatch, mode="mystery")

    registry = _drive_lifespan_and_inspect()

    assert registry.relational_memory is None
    err = registry.errors.get("relational_memory", "")
    assert "mystery" in err
    assert "off" in err and "noop" in err and "postgres" in err, (
        f"error should enumerate allowed values; got {err!r}"
    )
    assert "ADR-102" in err
