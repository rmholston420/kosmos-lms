"""ADR-138 slice T4 — GET /api/telemetry endpoint tests.

GPU-free: the real kernel app via ASGITransport with the collector
injected (the endpoint delegates to ``kernel.tektos_telemetry.collect``
in a worker thread; patching ``collect`` isolates the endpoint layer —
routing, thread hop, envelope passthrough, no 500 on degraded reads.
Collector-correctness itself is covered by the T2 tests).

The endpoint does NOT add a handler-level try/except: the collector is
designed so every hardware boundary degrades to the donor's zero
defaults internally (per-read guards). An unexpected raise there is a
programming error and a 500 surfaces it honestly — same convention as
the ADR-121 /api/thermal/status degrade path.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

import kernel.app as kernel_app


def _envelope(
    *,
    temp: float = 64.0,
    util: float = 87.0,
    mem_used: float = 15_000_000_000,
    mem_total: float = 32_000_000_000,
    power: float = 310.0,
    limit: float = 400.0,
    fan: int = 65,
    clk_g: int = 2410,
    clk_m: int = 28_000,
    mem_util: float = 72.0,
    cpu: float = 33.3,
    ts: float = 1_700_000_000.0,
) -> dict:
    """A donor-canonical sample (the T2 full-read shape)."""
    return {
        "gpu": {
            "temperature": temp,
            "utilization": util,
            "memory_used": mem_used,
            "memory_total": mem_total,
            "power_draw": power,
            "power_limit": limit,
            "fan_speed": fan,
            "clocks_graphics": clk_g,
            "clocks_memory": clk_m,
            "memory_utilization": mem_util,
        },
        "system": {
            "cpu_util": cpu,
            "mem_used_gb": 20.5,
            "mem_total_gb": 31.6,
            "mem_percent": 64.9,
            "disk_used_gb": 600.0,
            "disk_total_gb": 3800.0,
            "disk_percent": 15.8,
        },
        "timestamp": ts,
    }


@pytest_asyncio.fixture
async def client(monkeypatch):
    # Real registry (the kill-switch middleware reads registry.suspended);
    # only the telemetry collector is replaced — the endpoint delegates
    # to kernel.tektos_telemetry.collect, so patching it at module
    # attribute level isolates the endpoint layer.
    transport = ASGITransport(app=kernel_app.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_endpoint_passthrough_full_read(client, monkeypatch):
    """The endpoint returns collect()'s envelope verbatim — no mutation."""
    sample = _envelope()
    monkeypatch.setattr("kernel.tektos_telemetry.collect", lambda: sample)
    resp = await client.get("/api/telemetry")
    assert resp.status_code == 200
    body = resp.json()
    assert body == sample
    assert set(body) == {"gpu", "system", "timestamp"}
    assert body["gpu"]["temperature"] == 64.0
    assert body["system"]["cpu_util"] == 33.3


@pytest.mark.asyncio
async def test_endpoint_degraded_sample_still_200(client, monkeypatch):
    """A fully-failed collect (donor zero defaults) is a healthy 200 —
    degradation lives inside the collector, not the handler."""
    sample = _envelope(
        temp=0, util=0, mem_used=0, mem_total=0, power=0, limit=400, fan=0,
        clk_g=0, clk_m=0, mem_util=0, cpu=0,
    )
    sample["system"] = {
        "cpu_util": 0, "mem_used_gb": 0.0, "mem_total_gb": 1.0,
        "mem_percent": 0.0, "disk_used_gb": 0.0, "disk_total_gb": 1.0,
        "disk_percent": 0.0,
    }
    monkeypatch.setattr("kernel.tektos_telemetry.collect", lambda: sample)
    resp = await client.get("/api/telemetry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gpu"]["temperature"] == 0
    assert body["gpu"]["power_limit"] == 400
    assert body["system"]["mem_used_gb"] == 0.0


@pytest.mark.asyncio
async def test_endpoint_does_not_mutate_caller_sample(client, monkeypatch):
    """collect() may be called repeatedly by other consumers — the
    endpoint must not alias/mutate its input (fresh dict per request)."""
    a = _envelope()
    b = _envelope(temp=99.0)
    calls = iter([a, b])
    monkeypatch.setattr(
        "kernel.tektos_telemetry.collect", lambda: next(calls)
    )
    r1 = (await client.get("/api/telemetry")).json()
    r2 = (await client.get("/api/telemetry")).json()
    assert r1["gpu"]["temperature"] == 64.0
    assert r2["gpu"]["temperature"] == 99.0
    assert a["gpu"]["temperature"] == 64.0  # original untouched
    assert b["gpu"]["temperature"] == 99.0
