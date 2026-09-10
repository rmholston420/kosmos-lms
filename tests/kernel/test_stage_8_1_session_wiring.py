"""Stage 8.1 — kernel-boot SessionPort wiring (ADR-103).

Fast-tier tests over the ``KOSMOS_SESSION`` env-gate wired into
``kernel/app.py::_boot_session``. Six scenarios per ADR-103 D4:

1. Unset                -> registry.session=None; no error registered.
2. Explicit ``off``     -> same as unset (silent).
3. ``inmemory``         -> InMemorySessionAdapter wired.
4. ``tektos``           -> TektosSessionAdapter wired; event_bus injected.
5. Unknown value        -> registry.errors[...] set.
6. Boot order           -> _boot_session runs AFTER _boot_relational_memory
                           so the mirror wire is populated when both are on.

Zero live I/O — every path drives through the FastAPI lifespan against
in-memory adapters.
"""

from __future__ import annotations

import os

# --- Env preamble: pin safe defaults; each test overrides selectively. -----
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("KOSMOS_SESSION", None)
os.environ.pop("KOSMOS_RELATIONAL_MEMORY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _reset_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_mode: str | None,
    relational_mode: str | None = None,
) -> None:
    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")
    if session_mode is None:
        monkeypatch.delenv("KOSMOS_SESSION", raising=False)
    else:
        monkeypatch.setenv("KOSMOS_SESSION", session_mode)
    if relational_mode is None:
        monkeypatch.delenv("KOSMOS_RELATIONAL_MEMORY", raising=False)
    else:
        monkeypatch.setenv("KOSMOS_RELATIONAL_MEMORY", relational_mode)


def _drive_lifespan_and_inspect():
    from kernel import app as kernel_app_module

    with TestClient(kernel_app_module.app) as _:
        pass
    return kernel_app_module.registry


# ---------------------------------------------------------------------------
# Test 1 — unset -> silent None
# ---------------------------------------------------------------------------


def test_unset_leaves_session_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, session_mode=None)

    registry = _drive_lifespan_and_inspect()

    assert registry.session is None
    assert "session" not in registry.errors


# ---------------------------------------------------------------------------
# Test 2 — explicit off -> silent None
# ---------------------------------------------------------------------------


def test_explicit_off_leaves_session_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, session_mode="off")

    registry = _drive_lifespan_and_inspect()

    assert registry.session is None
    assert "session" not in registry.errors


# ---------------------------------------------------------------------------
# Test 3 — inmemory adapter wired
# ---------------------------------------------------------------------------


def test_inmemory_mode_wires_inmemory_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters.session.inmemory.adapter import InMemorySessionAdapter

    _reset_env(monkeypatch, session_mode="inmemory")

    registry = _drive_lifespan_and_inspect()

    assert isinstance(registry.session, InMemorySessionAdapter)
    assert registry.session.is_healthy() is True
    assert "session" not in registry.errors


# ---------------------------------------------------------------------------
# Test 4 — tektos adapter wired (event_bus available)
# ---------------------------------------------------------------------------


def test_tektos_mode_wires_tektos_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters.session.tektos.adapter import TektosSessionAdapter

    _reset_env(monkeypatch, session_mode="tektos")

    registry = _drive_lifespan_and_inspect()

    # event_bus is booted unconditionally, so tektos wire succeeds.
    assert isinstance(registry.session, TektosSessionAdapter)
    assert registry.session.is_healthy() is True
    assert "session" not in registry.errors


# ---------------------------------------------------------------------------
# Test 5 — unknown value registers an error
# ---------------------------------------------------------------------------


def test_unknown_mode_registers_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, session_mode="mystery")

    registry = _drive_lifespan_and_inspect()

    assert registry.session is None
    assert "session" in registry.errors
    assert "mystery" in registry.errors["session"]


# ---------------------------------------------------------------------------
# Test 6 — boot order: session runs after relational_memory
# ---------------------------------------------------------------------------


def test_boot_order_session_after_relational_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both are on, tektos SessionPort observes the RelationalMemoryPort."""
    from adapters.relational_memory import NoOpRelationalMemoryAdapter
    from adapters.session.tektos import vendor_bindings
    from adapters.session.tektos.adapter import TektosSessionAdapter

    _reset_env(
        monkeypatch, session_mode="tektos", relational_mode="noop"
    )

    registry = _drive_lifespan_and_inspect()

    assert isinstance(registry.session, TektosSessionAdapter)
    assert isinstance(registry.relational_memory, NoOpRelationalMemoryAdapter)
    # The shim was bound with the same relational_memory instance.
    assert vendor_bindings._relational_memory is registry.relational_memory
