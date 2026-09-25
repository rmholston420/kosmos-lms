"""ADR-137 slice B3 — kernel-native GET /api/db endpoint tests.

GPU-free: real kernel app via ASGITransport, monkeypatched registry
lanes (no store is contacted — the endpoint reads booted state only,
per the ADR-137 user decision).

Slices:
- envelope: status/healthy/stores[4]/note/timestamp
- all four stores wired → healthy True, boot_error None
- degraded lanes (None + boot error) → healthy False, boot_error
  surfaced, other stores unaffected
- all lanes offline still 200 (degraded is not an error)
- note names the honest referent (systemd-managed, donor retired)

Every test restores the four registry lanes it touched.
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import kernel.app as kernel_app
from kernel.app import app, registry

SLOTS = ["relational_memory", "memory", "vector", "event_bus"]
ERROR_KEYS = ["relational_memory", "memory", "vector", "event_bus"]


class _Booted:
    """Any non-None object satisfies the endpoint's 'booted' check."""


def _apply(values: list[Any], errors: list[str | None]) -> list[tuple[Any, str | None]]:
    """Set the four lanes + their boot errors; return prior state."""
    prior: list[tuple[Any, str | None]] = []
    for slot, value, err_key, error in zip(SLOTS, values, ERROR_KEYS, errors):
        prev_value = getattr(registry, slot)
        prev_err = registry.errors.get(err_key)
        setattr(registry, slot, value)
        if error is None:
            registry.errors.pop(err_key, None)
        else:
            registry.errors[err_key] = error
        prior.append((prev_value, prev_err))
    return prior


def _restore(prior: list[tuple[Any, str | None]]) -> None:
    for (prev_value, prev_err), slot, err_key in zip(prior, SLOTS, ERROR_KEYS):
        setattr(registry, slot, prev_value)
        if prev_err is None:
            registry.errors.pop(err_key, None)
        else:
            registry.errors[err_key] = prev_err


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_db_envelope_all_wired(client: AsyncClient) -> None:
    prior = _apply([_Booted()] * 4, [None] * 4)
    try:
        r = await client.get("/api/db")
    finally:
        _restore(prior)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "initialized"
    assert body["healthy"] is True
    assert isinstance(body["timestamp"], str)
    assert "systemd-managed" in body["note"]
    assert "main.py" in body["note"]
    stores = {s["store"]: s for s in body["stores"]}
    assert set(stores) == {"postgres", "dozerdb", "qdrant", "valkey"}
    for s in stores.values():
        assert s["wired"] is True
        assert s["boot_error"] is None
        assert "systemd" in s["management"]


async def test_db_degraded_lane_honest(client: AsyncClient) -> None:
    prior = _apply(
        [_Booted(), None, None, _Booted()],
        [None, "dozerdb bolt unavailable", "qdrant down", None],
    )
    try:
        r = await client.get("/api/db")
    finally:
        _restore(prior)

    assert r.status_code == 200  # degraded is not an error
    body = r.json()
    assert body["healthy"] is False
    stores = {s["store"]: s for s in body["stores"]}
    assert stores["postgres"]["wired"] is True
    assert stores["postgres"]["boot_error"] is None
    assert stores["dozerdb"]["wired"] is False
    assert stores["dozerdb"]["boot_error"] == "dozerdb bolt unavailable"
    assert stores["qdrant"]["wired"] is False
    assert stores["qdrant"]["boot_error"] == "qdrant down"
    assert stores["valkey"]["wired"] is True


async def test_db_all_offline_still_200(client: AsyncClient) -> None:
    prior = _apply(
        [None, None, None, None],
        ["pg down", "bolt down", "qdrant down", "valkey down"],
    )
    try:
        r = await client.get("/api/db")
    finally:
        _restore(prior)

    assert r.status_code == 200
    body = r.json()
    assert body["healthy"] is False
    assert all(s["wired"] is False for s in body["stores"])
    # the note never changes with state — the honest referent is constant
    assert "systemd-managed" in body["note"]
    assert "main.py" in body["note"]
