"""Stage 8.7 — kernel-boot Tektos Orchestrator wiring (ADR-114 D6).

Fast-tier tests over the ``KOSMOS_TEKTOS_ORCHESTRATOR`` env-gate wired
into ``kernel/app.py``. Scenarios per ADR-114 D6:

- Unset              → registry.tektos_orchestrator=None; no error.
- Explicit ``off``   → same as unset (silent).
- Unknown value      → registry.errors["tektos_orchestrator"] set.
- ``on`` without RelationalMemoryPort → None + degrade (ADR-101).
- Boot order         → tektos_orchestrator wires AFTER _boot_tektos_manager.
- TektosPlugin dataclass fields exist (ADR-114 D5).
- _BootRegistry has the three new slots.
"""

from __future__ import annotations

import os

# --- Env preamble ---
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("KOSMOS_TEKTOS_ORCHESTRATOR", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _reset_env(monkeypatch: pytest.MonkeyPatch, mode: str | None = None) -> None:
    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")
    if mode is None:
        monkeypatch.delenv("KOSMOS_TEKTOS_ORCHESTRATOR", raising=False)
    else:
        monkeypatch.setenv("KOSMOS_TEKTOS_ORCHESTRATOR", mode)


def _drive_lifespan_and_inspect():
    from kernel import app as kernel_app_module

    kernel_app_module.registry.errors.clear()
    with TestClient(kernel_app_module.app) as _:
        pass
    return kernel_app_module.registry


# ---------------------------------------------------------------------------
# Env-gate scenarios
# ---------------------------------------------------------------------------


def test_unset_leaves_orchestrator_slot_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch)
    registry = _drive_lifespan_and_inspect()
    assert registry.tektos_orchestrator is None
    assert "tektos_orchestrator" not in registry.errors


def test_explicit_off_leaves_orchestrator_slot_none_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_env(monkeypatch, "off")
    registry = _drive_lifespan_and_inspect()
    assert registry.tektos_orchestrator is None
    assert "tektos_orchestrator" not in registry.errors


def test_unknown_mode_registers_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_env(monkeypatch, "mystery")
    registry = _drive_lifespan_and_inspect()
    assert registry.tektos_orchestrator is None
    assert "tektos_orchestrator" in registry.errors
    assert "mystery" in registry.errors["tektos_orchestrator"]


def test_on_without_relational_memory_degrades_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-114 D6: ``on`` requires ``registry.relational_memory`` non-None."""

    _reset_env(monkeypatch, "on")
    registry = _drive_lifespan_and_inspect()
    if getattr(registry, "relational_memory", None) is None:
        assert registry.tektos_orchestrator is None
        assert "tektos_orchestrator" not in registry.errors


# ---------------------------------------------------------------------------
# Boot order
# ---------------------------------------------------------------------------


def test_boot_order_orchestrator_slot_after_manager() -> None:
    """ADR-114 D6: ``_boot_tektos_orchestrator`` must run AFTER
    ``_boot_tektos_manager`` so ``registry.relational_memory`` +
    ``registry.event_bus`` + ``registry.sandbox`` + ``registry.llm``
    have already been booted upstream."""

    import inspect

    from kernel import app as kernel_app_module

    src = inspect.getsource(kernel_app_module)
    idx_mgr = src.index("registry.tektos_manager = _boot_tektos_manager")
    idx_orch = src.index(
        "registry.tektos_orchestrator = _boot_tektos_orchestrator"
    )
    assert idx_mgr < idx_orch, (
        "ADR-114 D6 requires _boot_tektos_orchestrator assignment to run "
        "AFTER _boot_tektos_manager assignment."
    )


# ---------------------------------------------------------------------------
# Dataclass slots
# ---------------------------------------------------------------------------


def test_plugin_fields_exist() -> None:
    """ADR-114 D5: TektosPlugin carries the three engine slots."""

    from plugins.tektos.plugin import TektosPlugin

    for name in (
        "orchestrator",
        "hierarchical_agent",
        "long_running_agent",
    ):
        assert name in TektosPlugin.__dataclass_fields__, (
            f"TektosPlugin missing Stage 8.7 field {name!r} (ADR-114 D5)."
        )
    defaults = TektosPlugin.__dataclass_fields__
    for name in ("orchestrator", "hierarchical_agent", "long_running_agent"):
        assert defaults[name].default is None


def test_registry_slots_exist() -> None:
    """ADR-114 D6: _BootRegistry carries the three Stage 8.7 slots."""

    from kernel.app import registry

    for name in (
        "tektos_orchestrator",
        "tektos_hierarchical",
        "tektos_long_running",
    ):
        assert hasattr(registry, name), (
            f"_BootRegistry missing Stage 8.7 slot {name!r} (ADR-114 D6)."
        )
