"""Stage 7.4+2 — kernel-boot lexical wiring for the MemoryPort (ADR-101).

Fast-tier tests over the ``KOSMOS_MEMORY_LEXICAL`` env-gate wired into
``kernel/app.py::_boot_memory``. Six scenarios per ADR-101 D5:

1. Unset          → ``lexical=None``; search_hybrid raises NotImplementedError.
2. Explicit ``off`` → same as unset.
3. ``dozerdb`` + backend=in_memory (invalid shape) → registry.errors["memory"].
4. ``dozerdb`` + backend=dozerdb + healthy driver → lexical wired.
5. ``dozerdb`` + backend=dozerdb + unhealthy driver → lexical=None + warning.
6. Unknown value ``mystery`` → registry.errors["memory"] enumerates allowed values.

Zero live I/O — DozerDbGraphBackend and DozerDbLexicalIndex both construct
lazily (they capture failures in ``_init_error`` and expose ``is_healthy()``),
so we can drive the real code paths without a running Bolt endpoint.

Tests use ``TestClient(app)`` to fire the lifespan; the module-scoped
``registry`` singleton is inspected after each boot.
"""

from __future__ import annotations

import importlib
import logging
import os

# --------------------------------------------------------------------------
# Env preamble — pin to safe defaults; each test overrides selectively.
# Follows the same pattern as tests/kernel/test_stage_6_5_7_gnosis_retrieval.py:
# kernel.app builds its FastAPI app at import time, so a shell env carrying
# KOSMOS_MEMORY_BACKEND=dozerdb from a live smoke would try to hit real
# services during the very first TestClient(...) __enter__.
# --------------------------------------------------------------------------
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("KOSMOS_MEMORY_LEXICAL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _reset_env_lexical(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    """Set or unset KOSMOS_MEMORY_LEXICAL and reset backend to in_memory."""
    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")
    if value is None:
        monkeypatch.delenv("KOSMOS_MEMORY_LEXICAL", raising=False)
    else:
        monkeypatch.setenv("KOSMOS_MEMORY_LEXICAL", value)


def _drive_lifespan_and_inspect():
    """Fire the app lifespan and return the module-level registry snapshot."""
    from kernel import app as kernel_app_module

    with TestClient(kernel_app_module.app) as _:
        pass
    return kernel_app_module.registry


# ---------------------------------------------------------------------------
# Test 1 — KOSMOS_MEMORY_LEXICAL unset → lexical=None; search_hybrid raises.
# ---------------------------------------------------------------------------


def test_lexical_unset_leaves_lexical_none_and_search_hybrid_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env_lexical(monkeypatch, None)

    registry = _drive_lifespan_and_inspect()

    assert registry.memory is not None, (
        f"memory boot should succeed with defaults; errors={registry.errors!r}"
    )
    assert getattr(registry.memory, "_lexical", "sentinel") is None, (
        "lexical lane must default to None when KOSMOS_MEMORY_LEXICAL unset "
        "(ADR-101 D2)."
    )

    # search_hybrid must raise NotImplementedError per ADR-085 / ADR-099 D3.
    import asyncio

    async def _call() -> None:
        await registry.memory.search_hybrid("anything")

    with pytest.raises(NotImplementedError):
        asyncio.run(_call())


# ---------------------------------------------------------------------------
# Test 2 — KOSMOS_MEMORY_LEXICAL=off → same as unset.
# ---------------------------------------------------------------------------


def test_lexical_explicit_off_leaves_lexical_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env_lexical(monkeypatch, "off")

    registry = _drive_lifespan_and_inspect()

    assert registry.memory is not None, (
        f"memory boot should succeed with lexical=off; errors={registry.errors!r}"
    )
    assert getattr(registry.memory, "_lexical", "sentinel") is None


# ---------------------------------------------------------------------------
# Test 3 — KOSMOS_MEMORY_LEXICAL=dozerdb + KOSMOS_MEMORY_BACKEND=in_memory
# is the reject-shape combination from ADR-101 D2.
# ---------------------------------------------------------------------------


def test_lexical_dozerdb_with_in_memory_backend_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env_lexical(monkeypatch, "dozerdb")  # backend stays in_memory

    registry = _drive_lifespan_and_inspect()

    assert registry.memory is None, (
        "memory subsystem must fail to boot when the lexical/backend shape "
        "is invalid (ADR-101 D2)."
    )
    err = registry.errors.get("memory", "")
    assert "KOSMOS_MEMORY_LEXICAL=dozerdb" in err
    assert "KOSMOS_MEMORY_BACKEND=dozerdb" in err
    assert "ADR-101" in err, (
        f"error message should reference ADR-101 for traceability; got {err!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — KOSMOS_MEMORY_LEXICAL=dozerdb + backend=dozerdb + Bolt env set →
# lexical wired (DozerDbLexicalIndex constructs lazily with no network I/O).
# ---------------------------------------------------------------------------


def test_lexical_dozerdb_healthy_wires_the_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Full dozerdb env pointing at an unreachable host — construction is
    # lazy per DozerDbLexicalIndex + DozerDbGraphBackend contracts, so
    # is_healthy() returns True right after __init__.
    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "dozerdb")
    monkeypatch.setenv("KOSMOS_MEMORY_LEXICAL", "dozerdb")
    monkeypatch.setenv("KOSMOS_DOZERDB_URI", "bolt://127.0.0.1:9")  # port 9 discard
    monkeypatch.setenv("KOSMOS_DOZERDB_USER", "neo4j")
    monkeypatch.setenv("KOSMOS_DOZERDB_PASSWORD", "kosmos-test-password")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")

    registry = _drive_lifespan_and_inspect()

    # Memory adapter must construct even though we cannot reach the Bolt
    # endpoint — driver instantiation is lazy on both DozerDbGraphBackend
    # and DozerDbLexicalIndex (see adapters/memory/dozerdb/*.py).
    assert registry.memory is not None, (
        f"memory boot with dozerdb+dozerdb-lexical must succeed under lazy "
        f"driver semantics; errors={registry.errors!r}"
    )

    lex = getattr(registry.memory, "_lexical", None)
    assert lex is not None, (
        "lexical lane must be wired when KOSMOS_MEMORY_LEXICAL=dozerdb "
        "and KOSMOS_MEMORY_BACKEND=dozerdb (ADR-101 D1)."
    )

    # Should be the real production adapter, not the in-memory test backend.
    from adapters.memory.dozerdb.dozerdb_lexical_index import DozerDbLexicalIndex

    assert isinstance(lex, DozerDbLexicalIndex), (
        f"expected DozerDbLexicalIndex, got {type(lex).__name__}"
    )
    assert lex.is_healthy() is True


# ---------------------------------------------------------------------------
# Test 5 — construction failure falls through to lexical=None with a warning.
# We simulate a bad driver by monkeypatching neo4j.AsyncGraphDatabase.driver
# to raise. The wiring's try/except must swallow the failure and log a
# warning that references ADR-101 D3.
# ---------------------------------------------------------------------------


def test_lexical_dozerdb_unhealthy_falls_through_to_none(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import neo4j

    # Force the lexical adapter's lazy driver call to raise; the graph
    # backend's is a separate call site further up the chain — it will
    # also raise, so memory boot as a whole will fail. To isolate the
    # lexical-fall-through path we instead patch only the class method
    # used inside DozerDbLexicalIndex.__init__ so the graph backend's
    # earlier call succeeds and the lexical branch fails.
    #
    # Both adapters do ``from neo4j import AsyncGraphDatabase`` inside
    # their __init__. Patch the shared class attribute.
    orig_driver = neo4j.AsyncGraphDatabase.driver
    call_count = {"n": 0}

    def _flaky_driver(*args, **kwargs):
        call_count["n"] += 1
        # First call = graph backend (must succeed lazily); second call
        # = lexical adapter (make it raise so we exercise ADR-101 D3).
        if call_count["n"] == 1:
            return orig_driver(*args, **kwargs)
        raise RuntimeError("boom-lexical-driver")

    monkeypatch.setattr(
        neo4j.AsyncGraphDatabase, "driver", staticmethod(_flaky_driver)
    )

    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "dozerdb")
    monkeypatch.setenv("KOSMOS_MEMORY_LEXICAL", "dozerdb")
    monkeypatch.setenv("KOSMOS_DOZERDB_URI", "bolt://127.0.0.1:9")
    monkeypatch.setenv("KOSMOS_DOZERDB_USER", "neo4j")
    monkeypatch.setenv("KOSMOS_DOZERDB_PASSWORD", "kosmos-test-password")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")

    with caplog.at_level(logging.WARNING, logger="kernel.app"):
        registry = _drive_lifespan_and_inspect()

    # Memory adapter still constructed (graph backend lazy path).
    assert registry.memory is not None, (
        f"memory subsystem must still boot even when lexical construction "
        f"fails (ADR-101 D3 fall-through); errors={registry.errors!r}"
    )
    # Lexical fell through to None.
    assert getattr(registry.memory, "_lexical", "sentinel") is None, (
        "unhealthy lexical must fall through to lexical=None (ADR-101 D3)."
    )
    # Warning was logged and mentions ADR-101 D3.
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("ADR-101 D3" in (r.getMessage()) for r in warnings), (
        "ADR-101 D3 fall-through must log a warning citing the ADR; "
        f"captured warnings={[r.getMessage() for r in warnings]!r}"
    )


# ---------------------------------------------------------------------------
# Test 6 — unknown KOSMOS_MEMORY_LEXICAL value fails with a message
# enumerating the allowed values.
# ---------------------------------------------------------------------------


def test_lexical_unknown_value_rejects_with_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env_lexical(monkeypatch, "mystery")

    registry = _drive_lifespan_and_inspect()

    assert registry.memory is None, (
        "memory subsystem must fail to boot on an unknown lexical mode "
        "(ADR-101 D2)."
    )
    err = registry.errors.get("memory", "")
    # Message must include the offending value and the allowed enumeration.
    assert "mystery" in err
    assert "off" in err and "dozerdb" in err
    assert "ADR-101" in err
