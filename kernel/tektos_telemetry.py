"""kernel.tektos_telemetry — ADR-138 kernel-native hardware telemetry.

v2 Stage 11.22 (Endpoint Split — telemetry family). The ops Telemetry tab
polled the ADR-109 gateway to the retired :8020 standalone engine's
``GET /api/telemetry``. That endpoint is a live hardware collector:
NVML (pynvml) for GPU, with an ``nvidia-smi`` CLI + ``/proc`` fallback,
returning the canonical ``{gpu, system, timestamp}`` envelope.

This module re-implements that collector **kernel-natively**, as a
separate sampler from the ADR-121 ``ThermalWatchdog`` (the watchdog
samples temp/power/clock for sustained-cooldown enforcement and serves
``/api/thermal/status`` for the dashboard Thermal card; this one serves
the ops Telemetry tab's broader sensor set).

Constraints:

* **No pynvml / psutil in the kernel venv** (both are optional and not
  installed) — so this is the donor's *fallback* path, verbatim in
  shape: ``nvidia-smi`` for GPU, ``/proc`` + ``shutil.disk_usage`` for
  system. The donor's NVML primary is unreachable in the kernel env;
  the CLI fallback is the honest, portable read (the donor itself
  falls back to it whenever NVML is absent).
* **Never raises, never fabricates.** A failed read returns the donor's
  zero defaults for that field, not an exception and not a stale value.
* **GPU-free testable** — the single subprocess boundary
  (``_run_nvidia_smi``) and the three system readers are injectable, so
  the whole collector is unit-testable without a GPU or a real
  ``/proc``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Callable, Optional

__all__ = ["collect", "read_gpu", "read_system", "DEFAULT_POWER_LIMIT_W"]

# Donor default when nvidia-smi reports no power.limit (RTX 5090 login
# default is 400 W via nvidia-clock-lock.service).
DEFAULT_POWER_LIMIT_W = 400


# ── GPU (nvidia-smi CLI, donor fallback fidelity) ───────────────────────


def _run_nvidia_smi(fields: list[str]) -> Optional[list[float]]:
    """One ``nvidia-smi`` query for a comma-joined field list.

    Returns the parsed floats, or ``None`` on any failure (missing
    binary, nonzero exit, unparsable output). The caller treats ``None``
    as "keep the zero defaults" — a read failure is degraded, not fatal.
    """
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(fields)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode != 0:
            return None
        return [float(v) for v in out.stdout.strip().split(",")]
    except Exception:  # noqa: BLE001 — collector must never die on a read
        return None


def read_gpu(*, run: Callable[[list[str]], Optional[list[float]]] = _run_nvidia_smi) -> dict[str, Any]:
    """GPU sensor read via nvidia-smi (donor fallback shape, verbatim).

    Field set + zero-defaults match the donor's ``_get_gpu_via_nvidia_smi``
    exactly, so the ops tab's contract is unchanged. Three queries, as in
    the donor: the 7 base fields, clocks, then memory utilization (kept
    separate because older drivers may lack the later fields — a combined
    query would then fail wholesale).
    """
    base: dict[str, Any] = {
        "temperature": 0,
        "utilization": 0,
        "memory_used": 0,
        "memory_total": 0,
        "power_draw": 0,
        "power_limit": DEFAULT_POWER_LIMIT_W,
        "fan_speed": 0,
        "clocks_graphics": 0,
        "clocks_memory": 0,
        "memory_utilization": 0,
    }
    vals = run(
        [
            "temperature.gpu",
            "utilization.gpu",
            "memory.used",
            "memory.total",
            "power.draw",
            "power.limit",
            "fan.speed",
        ]
    )
    if vals:
        # Per-position guards, donor fidelity: a short CSV fills the
        # leading fields and leaves the rest at their zero defaults.
        base["temperature"] = vals[0] if len(vals) > 0 else 0
        base["utilization"] = vals[1] if len(vals) > 1 else 0
        base["memory_used"] = vals[2] if len(vals) > 2 else 0
        base["memory_total"] = vals[3] if len(vals) > 3 else 0
        base["power_draw"] = vals[4] if len(vals) > 4 else 0
        base["power_limit"] = vals[5] if len(vals) > 5 else DEFAULT_POWER_LIMIT_W
        base["fan_speed"] = int(vals[6]) if len(vals) > 6 else 0
    clocks = run(["clocks.current.graphics", "clocks.current.memory"])
    if clocks and len(clocks) >= 2:
        base["clocks_graphics"] = int(clocks[0])
        base["clocks_memory"] = int(clocks[1])
    mem_util = run(["utilization.memory"])
    if mem_util and len(mem_util) >= 1:
        base["memory_utilization"] = mem_util[0]
    return base


# ── System (CPU / memory / disk, donor /proc fidelity) ───────────────────


def _read_cpu_util() -> float:
    """CPU utilization from /proc/stat (donor: lifetime total-vs-idle)."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        idle = float(parts[4]) if len(parts) > 4 else 0
        total = sum(float(x) for x in parts[1:])
        return round(((total - idle) / total) * 100 if total > 0 else 0, 1)
    except Exception:  # noqa: BLE001
        return 0.0


def _read_mem() -> tuple[float, float, float]:
    """(used_gb, total_gb, percent) from /proc/meminfo (donor fidelity)."""
    try:
        mi: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                tokens = val.strip().split()
                if not tokens:
                    continue
                mi[key.strip()] = int(tokens[0]) * 1024  # kB → bytes
        used = (
            mi.get("MemTotal", 0)
            - mi.get("MemFree", 0)
            - mi.get("Buffers", 0)
            - mi.get("Cached", 0)
        )
        total = mi.get("MemTotal", 1)
        return (
            round(used / (1024**3), 1),
            round(total / (1024**3), 1),
            round(used / total * 100 if total > 0 else 0, 1),
        )
    except Exception:  # noqa: BLE001
        return 0.0, 1.0, 0.0


def _read_disk() -> tuple[float, float, float]:
    """(used_gb, total_gb, percent) for / (donor: shutil.disk_usage)."""
    try:
        d = shutil.disk_usage("/")
        return (
            round(d.used / (1024**3), 1),
            round(d.total / (1024**3), 1),
            round(d.used / d.total * 100 if d.total > 0 else 0, 1),
        )
    except Exception:  # noqa: BLE001
        return 0.0, 1.0, 0.0


def read_system(
    *,
    cpu_reader: Callable[[], float] = _read_cpu_util,
    mem_reader: Callable[[], tuple[float, float, float]] = _read_mem,
    disk_reader: Callable[[], tuple[float, float, float]] = _read_disk,
) -> dict[str, Any]:
    """System metrics (donor ``_get_system_metrics`` shape, verbatim)."""
    mem_used, mem_total, mem_pct = mem_reader()
    disk_used, disk_total, disk_pct = disk_reader()
    return {
        "cpu_util": cpu_reader(),
        "mem_used_gb": mem_used,
        "mem_total_gb": mem_total,
        "mem_percent": mem_pct,
        "disk_used_gb": disk_used,
        "disk_total_gb": disk_total,
        "disk_percent": disk_pct,
    }


# ── Collector (canonical {gpu, system, timestamp} envelope) ──────────────


def collect(
    *,
    read_gpu_fn: Callable[..., dict[str, Any]] = read_gpu,
    read_system_fn: Callable[..., dict[str, Any]] = read_system,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """One telemetry sample in the donor's canonical envelope.

    ``read_gpu_fn`` / ``read_system_fn`` are injectable so the collector is
    GPU-free testable (tests pass scripted readers); ``now`` is injectable
    for deterministic timestamps. The endpoint calls ``collect()`` with the
    real readers.
    """
    return {
        "gpu": read_gpu_fn(),
        "system": read_system_fn(),
        "timestamp": now(),
    }
