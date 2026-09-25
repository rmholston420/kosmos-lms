"""ADR-143 T3 / S3 — kernel learning driver (queue + env-gated cycles).

Covers the donor-faithful port of the ``main.py:1224-1288`` scaffolding:
* env gate defaults off; interval default 1800s
* enqueue / queue cap (drop-oldest) / empty-prompt rejection
* background task: one cycle per wake, loop-agnostic via DI seam
* disabled → no task; enabled but unwired → task no-ops, status honest
* status wire shape (enabled/interval/queue_length/orchestrator_ready/...)
* run_cycle_now manual trigger (honest skip when unwired)
* singleton seam
"""

from __future__ import annotations

import asyncio
from typing import Any
from dataclasses import dataclass, field

import pytest

from kernel.learning import (
    LearningDriver,
    get_learning_driver,
    reset_learning_driver,
)


@dataclass
class FakeCycle:
    cycle_id: str = "cyc-1"
    status: str = "complete"
    prompt: str = "p"
    syntheses: list = field(default_factory=lambda: ["s1"])
    experience_stored: list = field(default_factory=lambda: ["e1"])
    duration_seconds: float | None = 1.5
    error: str | None = None


class FakeLoop:
    """Loop double with the duck-typed surface the driver needs."""

    def __init__(self, fail: bool = False):
        self.calls: list[str] = []
        self._fail = fail
        self.health = {"total_cycles": 0, "success_rate": 1.0}

    def run(self, prompt: str) -> FakeCycle:
        self.calls.append(prompt)
        if self._fail:
            raise RuntimeError("loop exploded")
        return FakeCycle(prompt=prompt)

    def get_loop_health(self) -> dict:
        return self.health

    def __len__(self) -> int:
        return len(self.calls)


@pytest.fixture
def driver() -> LearningDriver:
    return LearningDriver(enabled=False, interval=0.01)


# ── env gate + defaults ────────────────────────────────────────────────────


def test_env_gate_defaults_off(monkeypatch):
    monkeypatch.delenv("TEKTOS_SELF_IMPROVEMENT_ENABLED", raising=False)
    d = LearningDriver()
    assert d.enabled is False
    assert d.interval == 1800.0


def test_env_gate_reads_env(monkeypatch):
    monkeypatch.setenv("TEKTOS_SELF_IMPROVEMENT_ENABLED", "true")
    monkeypatch.setenv("TEKTOS_SELF_IMPROVEMENT_INTERVAL", "42")
    d = LearningDriver()
    assert d.enabled is True
    assert d.interval == 42.0


def test_enable_toggles(monkeypatch):
    monkeypatch.delenv("TEKTOS_SELF_IMPROVEMENT_ENABLED", raising=False)
    d = LearningDriver()
    assert d.enabled is False
    d.enable()
    assert d.enabled is True


# ── queue ──────────────────────────────────────────────────────────────────


def test_enqueue_and_len(driver):
    assert driver.enqueue("prompt a") == 1
    assert driver.enqueue("prompt b") == 2
    assert len(driver) == 2
    status = driver.get_status()
    assert status["queue_length"] == 2
    assert status["queued_prompts"] == ["prompt a", "prompt b"]


def test_enqueue_rejects_empty(driver):
    with pytest.raises(ValueError):
        driver.enqueue("   ")


def test_queue_cap_drops_oldest(driver):
    d = LearningDriver(enabled=False, interval=0.01, max_queue=3)
    for i in range(5):
        d.enqueue(f"p{i}")
    assert list(d._queue) == ["p2", "p3", "p4"]


# ── status wire shape ──────────────────────────────────────────────────────


def test_status_unwired_honest(driver):
    s = driver.get_status()
    assert s["enabled"] is False
    assert s["driver_running"] is False
    assert s["orchestrator_ready"] is False
    assert s["interval_seconds"] == 0.01
    assert s["queue_length"] == 0
    assert s["recent_cycles"] == []
    assert "loop_health" not in s  # no loop → no health section


def test_status_with_loop(driver):
    loop = FakeLoop()
    driver.set_loop(loop)
    assert driver.loop_ready is True
    s = driver.get_status()
    assert s["orchestrator_ready"] is True
    assert s["loop_health"] == loop.health
    assert s["loop_cycles"] == 0


# ── background task ────────────────────────────────────────────────────────


async def test_disabled_does_not_start(driver):
    await driver.start()
    assert driver.running is False


async def test_enabled_wired_runs_one_cycle_per_wake():
    loop = FakeLoop()
    d = LearningDriver(loop=loop, enabled=True, interval=0.01)
    d.enqueue("queued prompt")
    await d.start()
    try:
        # The first wake pops the one queued prompt; subsequent wakes no-op.
        await asyncio.sleep(0.06)
    finally:
        await d.stop()
    assert loop.calls == ["queued prompt"]
    assert d.running is False
    s = d.get_status()
    assert s["recent_cycles"][0]["id"] == "cyc-1"
    assert s["recent_cycles"][0]["status"] == "complete"
    assert s["recent_cycles"][0]["syntheses"] == 1
    assert s["recent_cycles"][0]["experiences"] == 1


async def test_enabled_unwired_skips_cycles():
    d = LearningDriver(enabled=True, interval=0.01)
    d.enqueue("orphan prompt")
    await d.start()
    try:
        await asyncio.sleep(0.05)
    finally:
        await d.stop()
    s = d.get_status()
    assert s["orchestrator_ready"] is False
    assert s["driver_running"] is False
    # prompt remains queued (nothing consumed it)
    assert s["queue_length"] == 1


async def test_cycle_failure_logged_not_fatal():
    loop = FakeLoop(fail=True)
    d = LearningDriver(loop=loop, enabled=True, interval=0.01)
    d.enqueue("bad prompt")
    await d.start()
    try:
        await asyncio.sleep(0.05)
    finally:
        await d.stop()
    s = d.get_status()
    assert s["recent_cycles"][0]["status"] == "failed"
    assert "loop exploded" in s["recent_cycles"][0]["error"]
    # driver survived the failure (task was cancelled by stop, not by crash)


# ── manual trigger ─────────────────────────────────────────────────────────


async def test_run_cycle_now_unwired_skips(driver):
    result = await driver.run_cycle_now("p")
    assert result == {
        "status": "skipped",
        "reason": "no loop wired (orchestrator_ready=false)",
    }


async def test_run_cycle_now_wired_runs(driver):
    loop = FakeLoop()
    driver.set_loop(loop)
    result = await driver.run_cycle_now("manual prompt")
    assert loop.calls == ["manual prompt"]
    assert result["status"] == "complete"
    assert result["id"] == "cyc-1"
    assert driver.get_status()["recent_cycles"][0]["id"] == "cyc-1"


# ── singleton ──────────────────────────────────────────────────────────────


def test_singleton_seam():
    reset_learning_driver()
    try:
        a = get_learning_driver(enabled=False)
        b = get_learning_driver()
        assert a is b
        reset_learning_driver()
        c = get_learning_driver(enabled=True)
        assert c is not a
        assert c.enabled is True
    finally:
        reset_learning_driver()
