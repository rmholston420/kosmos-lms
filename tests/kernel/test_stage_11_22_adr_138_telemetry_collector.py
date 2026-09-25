"""ADR-138 slice T2 — kernel.tektos_telemetry unit tests.

GPU-free: every hardware boundary (nvidia-smi subprocess, /proc, shutil)
is injected. Asserts the donor's canonical ``{gpu, system, timestamp}``
shape + zero-default degrade on read failure (never fabricates).
"""
from __future__ import annotations

from kernel.tektos_telemetry import collect, read_gpu, read_system

# Donor base-7 nvidia-smi query: temperature,utilization,memory.used,
# memory.total,power.draw,power.limit,fan.speed
BASE7 = [68.0, 92.0, 21000.0, 32768.0, 390.5, 400.0, 55.0]
CLOCKS = [2410.0, 13001.0]
MEM_UTIL = [12.0]


def _fake_run(scripted: dict[str, list[float] | None]):
    """Map the queried field-list (joined) → scripted values or None."""
    def _run(fields: list[str]) -> list[float] | None:
        key = ",".join(fields)
        return scripted.get(key, None)
    return _run


def test_read_gpu_full():
    run = _fake_run({
        "temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit,fan.speed": BASE7,
        "clocks.current.graphics,clocks.current.memory": CLOCKS,
        "utilization.memory": MEM_UTIL,
    })
    gpu = read_gpu(run=run)
    assert gpu["temperature"] == 68.0
    assert gpu["utilization"] == 92.0
    assert gpu["memory_used"] == 21000.0
    assert gpu["memory_total"] == 32768.0
    assert gpu["power_draw"] == 390.5
    assert gpu["power_limit"] == 400.0
    assert gpu["fan_speed"] == 55  # int, as donor
    assert gpu["clocks_graphics"] == 2410  # int
    assert gpu["clocks_memory"] == 13001  # int
    assert gpu["memory_utilization"] == 12.0


def test_read_gpu_all_failed_zero_defaults():
    """A failed nvidia-smi → donor's zero defaults, power_limit=400."""
    gpu = read_gpu(run=lambda fields: None)
    assert gpu["temperature"] == 0
    assert gpu["utilization"] == 0
    assert gpu["memory_used"] == 0
    assert gpu["memory_total"] == 0
    assert gpu["power_draw"] == 0
    assert gpu["power_limit"] == 400  # donor default, not 0
    assert gpu["fan_speed"] == 0
    assert gpu["clocks_graphics"] == 0
    assert gpu["clocks_memory"] == 0
    assert gpu["memory_utilization"] == 0


def test_read_gpu_partial_base7_short():
    """Base query returns <7 values → base fields stay at zero defaults
    (donor: `len(vals) > N` guards each position)."""
    gpu = read_gpu(run=lambda fields: [68.0, 92.0] if "temperature.gpu" in ",".join(fields) else None)
    assert gpu["temperature"] == 68.0  # position 0 present
    assert gpu["utilization"] == 92.0  # position 1 present
    assert gpu["memory_used"] == 0     # position 2 absent → default
    assert gpu["fan_speed"] == 0


def test_read_system_shape_and_degrade():
    sysm = read_system(
        cpu_reader=lambda: 42.5,
        mem_reader=lambda: (58.3, 128.0, 45.5),
        disk_reader=lambda: (700.1, 4000.0, 17.5),
    )
    assert set(sysm) == {
        "cpu_util", "mem_used_gb", "mem_total_gb", "mem_percent",
        "disk_used_gb", "disk_total_gb", "disk_percent",
    }
    assert sysm["cpu_util"] == 42.5
    assert sysm["mem_used_gb"] == 58.3
    assert sysm["disk_percent"] == 17.5


def test_collect_envelope():
    tel = collect(
        read_gpu_fn=lambda: {"temperature": 68.0},
        read_system_fn=lambda: {"cpu_util": 1.0},
        now=lambda: 1_700_000_000.0,
    )
    assert set(tel) == {"gpu", "system", "timestamp"}
    assert tel["gpu"]["temperature"] == 68.0
    assert tel["system"]["cpu_util"] == 1.0
    assert tel["timestamp"] == 1_700_000_000.0


def test_read_system_real_proc():
    """Sanity against the REAL /proc (no GPU needed): shapes + sane ranges."""
    sysm = read_system()  # real readers
    assert isinstance(sysm["cpu_util"], float)
    assert 0.0 <= sysm["cpu_util"] <= 100.0
    assert sysm["mem_total_gb"] > 0.0
    assert 0.0 <= sysm["mem_percent"] <= 100.0
    assert sysm["disk_total_gb"] > 0.0
