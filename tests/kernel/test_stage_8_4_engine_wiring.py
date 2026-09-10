"""Stage 8.4 — kernel-boot Tektos spec-planner/decomposer wiring (ADR-106 D6).

Fast-tier tests over the two ``KOSMOS_TEKTOS_{SPEC_PLANNER,DECOMPOSER}`` env-gates
wired into ``kernel/app.py``. Scenarios per ADR-106 D6:

- Unset            → registry.tektos_{slot}=None; no error.
- Explicit ``off`` → same as unset (silent).
- Unknown value    → registry.errors[<slot>] set.
- ``on`` without RelationalMemoryPort → None + degrade (ADR-101).
- Boot order       → two slots wire AFTER _boot_tektos_experience.
- TektosPlugin dataclass fields exist for spec_planner + decomposer (ADR-106 D5).
"""

from __future__ import annotations

import os

# --- Env preamble: pin safe defaults; each test overrides selectively. -----
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
for _v in (
    "KOSMOS_TEKTOS_SPEC_PLANNER",
    "KOSMOS_TEKTOS_DECOMPOSER",
):
    os.environ.pop(_v, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_SLOTS = ("spec_planner", "decomposer")
_ENVS = {
    "spec_planner": "KOSMOS_TEKTOS_SPEC_PLANNER",
    "decomposer": "KOSMOS_TEKTOS_DECOMPOSER",
}


def _reset_env(monkeypatch: pytest.MonkeyPatch, **modes: str | None) -> None:
    monkeypatch.setenv("KOSMOS_MEMORY_BACKEND", "in_memory")
    monkeypatch.setenv("KOSMOS_GNOSIS_SEED", "0")
    for slot, env_var in _ENVS.items():
        mode = modes.get(slot)
        if mode is None:
            monkeypatch.delenv(env_var, raising=False)
        else:
            monkeypatch.setenv(env_var, mode)


def _drive_lifespan_and_inspect():
    from kernel import app as kernel_app_module

    kernel_app_module.registry.errors.clear()
    with TestClient(kernel_app_module.app) as _:
        pass
    return kernel_app_module.registry


# ---------------------------------------------------------------------------
# Env-gate scenarios per slot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", _SLOTS)
def test_unset_leaves_engine_slot_none_silently(
    monkeypatch: pytest.MonkeyPatch, slot: str
) -> None:
    _reset_env(monkeypatch)
    registry = _drive_lifespan_and_inspect()
    assert getattr(registry, f"tektos_{slot}") is None
    assert f"tektos_{slot}" not in registry.errors


@pytest.mark.parametrize("slot", _SLOTS)
def test_explicit_off_leaves_engine_slot_none_silently(
    monkeypatch: pytest.MonkeyPatch, slot: str
) -> None:
    _reset_env(monkeypatch, **{slot: "off"})
    registry = _drive_lifespan_and_inspect()
    assert getattr(registry, f"tektos_{slot}") is None
    assert f"tektos_{slot}" not in registry.errors


@pytest.mark.parametrize("slot", _SLOTS)
def test_unknown_mode_registers_error(
    monkeypatch: pytest.MonkeyPatch, slot: str
) -> None:
    _reset_env(monkeypatch, **{slot: "mystery"})
    registry = _drive_lifespan_and_inspect()
    assert getattr(registry, f"tektos_{slot}") is None
    assert f"tektos_{slot}" in registry.errors
    assert "mystery" in registry.errors[f"tektos_{slot}"]


@pytest.mark.parametrize("slot", _SLOTS)
def test_on_without_relational_memory_degrades_to_none(
    monkeypatch: pytest.MonkeyPatch, slot: str
) -> None:
    """ADR-106 D6: ``on`` requires ``registry.relational_memory`` non-None.

    In the fast-tier boot path with ``KOSMOS_MEMORY_BACKEND=in_memory`` the
    relational-memory adapter is not wired; the engine slot must degrade
    silently.
    """
    _reset_env(monkeypatch, **{slot: "on"})
    registry = _drive_lifespan_and_inspect()
    if getattr(registry, "relational_memory", None) is None:
        assert getattr(registry, f"tektos_{slot}") is None
        assert f"tektos_{slot}" not in registry.errors


# ---------------------------------------------------------------------------
# Boot order: two new slots wire AFTER tektos_experience
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", _SLOTS)
def test_boot_order_engine_slot_after_experience(slot: str) -> None:
    """Static ordering guarantee: source-level position of each
    ``registry.tektos_<slot> = _boot_tektos_<slot>`` assignment must be
    AFTER the ``registry.tektos_experience = _boot_tektos_experience``
    assignment (Stage 8.3 baseline)."""
    import inspect

    from kernel import app as kernel_app_module

    src = inspect.getsource(kernel_app_module)
    idx_exp = src.index("registry.tektos_experience = _boot_tektos_experience")
    idx_slot = src.index(f"registry.tektos_{slot} = _boot_tektos_{slot}")
    assert idx_exp < idx_slot, (
        f"ADR-106 D6 requires _boot_tektos_{slot} to run AFTER "
        f"_boot_tektos_experience so registry.relational_memory has "
        f"already been booted."
    )


# ---------------------------------------------------------------------------
# TektosPlugin dataclass field surface (ADR-106 D5)
# ---------------------------------------------------------------------------


def test_tektos_plugin_dataclass_carries_stage_8_4_engine_fields() -> None:
    """ADR-106 D5 amends the ``TektosPlugin`` dataclass with two new
    optional fields — ``spec_planner``, ``decomposer`` — each defaulting to
    ``None``."""
    import dataclasses

    from plugins.tektos.plugin import TektosPlugin

    field_names = {f.name for f in dataclasses.fields(TektosPlugin)}
    for slot in _SLOTS:
        assert slot in field_names, f"TektosPlugin missing ADR-106 D5 field: {slot}"
