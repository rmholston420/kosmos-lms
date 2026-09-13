"""Stage 8.6 — kernel-boot Tektos Manager wiring (ADR-108 D6).

Fast-tier tests over the ``KOSMOS_TEKTOS_MANAGER`` env-gate wired into
``kernel/app.py``. Scenarios per ADR-108 D6:

- Unset            → registry.tektos_manager=None; no error.
- Explicit ``off`` → same as unset (silent).
- Unknown value    → registry.errors["tektos_manager"] set.
- ``on`` without RelationalMemoryPort → None + degrade (ADR-101).
- Boot order       → tektos_manager wires AFTER _boot_tektos_executor.
- TektosPlugin dataclass field exists for manager (ADR-108 D5).
- _BootRegistry has the new slot.
"""

from __future__ import annotations

import os

# --- Env preamble ---
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("KOSMOS_TEKTOS_MANAGER", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _reset_env(monkeypatch: pytest.MonkeyPatch, mode: str | None = None) -> None:
    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")
    if mode is None:
        monkeypatch.delenv("KOSMOS_TEKTOS_MANAGER", raising=False)
    else:
        monkeypatch.setenv("KOSMOS_TEKTOS_MANAGER", mode)


def _drive_lifespan_and_inspect():
    from kernel import app as kernel_app_module

    kernel_app_module.registry.errors.clear()
    with TestClient(kernel_app_module.app) as _:
        pass
    return kernel_app_module.registry


# ---------------------------------------------------------------------------
# Env-gate scenarios
# ---------------------------------------------------------------------------


def test_unset_leaves_manager_slot_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch)
    registry = _drive_lifespan_and_inspect()
    assert registry.tektos_manager is None
    assert "tektos_manager" not in registry.errors


def test_explicit_off_leaves_manager_slot_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, "off")
    registry = _drive_lifespan_and_inspect()
    assert registry.tektos_manager is None
    assert "tektos_manager" not in registry.errors


def test_unknown_mode_registers_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_env(monkeypatch, "mystery")
    registry = _drive_lifespan_and_inspect()
    assert registry.tektos_manager is None
    assert "tektos_manager" in registry.errors
    assert "mystery" in registry.errors["tektos_manager"]


def test_on_without_relational_memory_degrades_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-108 D6: ``on`` requires ``registry.relational_memory`` non-None."""

    _reset_env(monkeypatch, "on")
    registry = _drive_lifespan_and_inspect()
    if getattr(registry, "relational_memory", None) is None:
        assert registry.tektos_manager is None
        assert "tektos_manager" not in registry.errors


# ---------------------------------------------------------------------------
# Boot order
# ---------------------------------------------------------------------------


def test_boot_order_manager_slot_after_executor() -> None:
    """ADR-108 D6: ``_boot_tektos_manager`` must run AFTER
    ``_boot_tektos_executor`` so ``registry.relational_memory`` +
    ``registry.event_bus`` + ``registry.immune`` + ``registry.observability``
    have already been booted upstream."""

    import inspect

    from kernel import app as kernel_app_module

    src = inspect.getsource(kernel_app_module)
    idx_exec = src.index("registry.tektos_executor = _boot_tektos_executor")
    idx_mgr = src.index("registry.tektos_manager = _boot_tektos_manager")
    assert idx_exec < idx_mgr, (
        "ADR-108 D6 requires _boot_tektos_manager assignment to run AFTER "
        "_boot_tektos_executor assignment."
    )


# ---------------------------------------------------------------------------
# _BootRegistry surface
# ---------------------------------------------------------------------------


def test_boot_registry_has_tektos_manager_slot() -> None:
    from kernel import app as kernel_app_module

    assert hasattr(kernel_app_module.registry, "tektos_manager"), (
        "ADR-108 D6 requires _BootRegistry to expose tektos_manager"
    )


# ---------------------------------------------------------------------------
# TektosPlugin dataclass field surface (ADR-108 D5)
# ---------------------------------------------------------------------------


def test_tektos_plugin_dataclass_carries_manager_field() -> None:
    import dataclasses

    from plugins.tektos.plugin import TektosPlugin

    field_names = {f.name for f in dataclasses.fields(TektosPlugin)}
    assert "manager" in field_names, "TektosPlugin missing ADR-108 D5 field: manager"


def test_tektos_plugin_manager_field_default_none() -> None:
    import dataclasses

    from plugins.tektos.plugin import TektosPlugin

    fields_by_name = {f.name: f for f in dataclasses.fields(TektosPlugin)}
    manager_field = fields_by_name["manager"]
    assert manager_field.default is None
