"""ADR-133 slice I2a — kernel.tektos_immune mapper module tests.

GPU-free: fake event bus (``read_recent`` returning Valkey-shaped
``(entry_id, EventEnvelope)`` rows) + fake immune adapter
(``list_detectors`` / ``is_healthy``).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kernel import tektos_immune as ti  # noqa: E402
from ports.event_envelope import EventEnvelope  # noqa: E402
from ports.immune import DetectorInfo  # noqa: E402


class FakeBus:
    """read_recent bus: per-type lists of (entry_id, envelope)."""

    def __init__(self, streams: dict[str, list]) -> None:
        self.streams = streams

    async def read_recent(self, *, event_type, count=None):
        items = list(self.streams.get(event_type, []))
        if count is not None:
            items = items[-count:]
        return items


def _env(event_type: str, entry_id: str, ts_s: int, payload: dict) -> tuple:
    envelope = EventEnvelope(
        event_type=event_type,
        producer_plugin="tektos_immune_adapter",
        payload=payload,
        occurred_at=datetime.fromtimestamp(ts_s, tz=timezone.utc),
    )
    return (entry_id, envelope)


def _verdict_payload(decision: str, hits: list[dict], reason: str = "r") -> dict:
    return {
        "source_plugin": "tektos_manager",
        "kind": "tektos.tool.invocation",
        "decision": decision,
        "reason": reason,
        "hit_count": len(hits),
        "hits": hits,
        "source": "tektos_immune",
    }


class FakeImmune:
    def __init__(self, infos: list[DetectorInfo] | None = None) -> None:
        self._infos = tuple(
            infos
            if infos is not None
            else [
                DetectorInfo(
                    name="prompt_injection",
                    severity_ceiling="block",
                    description="detects prompt injection",
                ),
                DetectorInfo(
                    name="excessive_repetition",
                    severity_ceiling="warn",
                    description="detects repetition",
                ),
            ]
        )

    async def list_detectors(self) -> tuple:
        return self._infos

    def is_healthy(self) -> bool:
        return True


def _streams_one_of_each() -> dict[str, list]:
    """One block (t=100), one warn (t=200), one allow (t=300)."""
    return {
        "immune.verdict.block": [
            _env(
                "immune.verdict.block",
                "100-1",
                100,
                _verdict_payload(
                    "block",
                    [{"detector": "prompt_injection", "severity": "block", "evidence": "injected"}],
                    "injection detected",
                ),
            )
        ],
        "immune.verdict.warn": [
            _env(
                "immune.verdict.warn",
                "200-1",
                200,
                _verdict_payload(
                    "warn",
                    [{"detector": "excessive_repetition", "severity": "warn", "evidence": "repeated 3x"}],
                    "repeating",
                ),
            )
        ],
        "immune.verdict.allow": [
            _env(
                "immune.verdict.allow",
                "300-1",
                300,
                _verdict_payload("allow", [], "clean"),
            )
        ],
    }


# ---------------------------------------------------------------------------
# detectors
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_detectors_shape() -> None:
    out = await ti.get_detectors(FakeImmune())
    assert out["count"] == 2
    names = {d["name"] for d in out["detectors"]}
    assert names == {"prompt_injection", "excessive_repetition"}
    d = next(x for x in out["detectors"] if x["name"] == "prompt_injection")
    assert d["enabled"] is True
    assert d["severity_ceiling"] == "block"
    assert "TektosDetector" in d["type"]  # donor's `type` slot, non-fabricated
    assert d["description"]


@pytest.mark.anyio
async def test_detectors_empty() -> None:
    out = await ti.get_detectors(FakeImmune([]))
    assert out == {"detectors": [], "count": 0}


# ---------------------------------------------------------------------------
# threats
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_threats_active_only_by_default() -> None:
    bus = FakeBus(_streams_one_of_each())
    out = await ti.get_threats(bus)
    assert out["count"] == 2  # block + warn, allow excluded
    rows = out["threats"]
    assert all(r["resolved"] is False for r in rows)
    # oldest first: block (t=100) before warn (t=200)
    assert rows[0]["detector"] == "prompt_injection"
    assert rows[0]["severity"] == "block"
    assert rows[0]["description"] == "injection detected"
    assert rows[0]["timestamp"].endswith("+00:00")


@pytest.mark.anyio
async def test_threats_resolved_includes_allow() -> None:
    bus = FakeBus(_streams_one_of_each())
    out = await ti.get_threats(bus, resolved=True)
    assert out["count"] == 3
    allow_row = next(r for r in out["threats"] if r["decision"] == "allow")
    assert allow_row["resolved"] is True


@pytest.mark.anyio
async def test_threats_empty() -> None:
    bus = FakeBus({})
    out = await ti.get_threats(bus)
    assert out == {"threats": [], "count": 0}


# ---------------------------------------------------------------------------
# ms-seq numeric sort (lexicographic breaks at digit-count boundaries)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_threats_numeric_sort_across_digit_boundaries() -> None:
    # Lexicographically "9-0" > "10-0"; numerically 9 < 10.
    streams = {
        "immune.verdict.warn": [
            _env(
                "immune.verdict.warn",
                "10000-0",
                10000,
                _verdict_payload("warn", [{"detector": "late", "severity": "warn", "evidence": "e"}]),
            ),
            _env(
                "immune.verdict.warn",
                "9-0",
                9,
                _verdict_payload("warn", [{"detector": "early", "severity": "warn", "evidence": "e"}]),
            ),
        ]
    }
    out = await ti.get_threats(FakeBus(streams))
    assert [r["detector"] for r in out["threats"]] == ["early", "late"]


# ---------------------------------------------------------------------------
# responses / memory / entries
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_responses_newest_first_and_limit() -> None:
    bus = FakeBus(_streams_one_of_each())
    out = await ti.get_responses(bus, limit=20)
    rows = out["responses"]
    assert len(rows) == 3
    # newest first: allow (t=300), warn (t=200), block (t=100)
    assert [r["decision"] for r in rows] == ["allow", "warn", "block"]
    assert rows[0]["hit_count"] == 0
    out1 = await ti.get_responses(bus, limit=1)
    assert len(out1["responses"]) == 1


@pytest.mark.anyio
async def test_memory_summary_counts() -> None:
    bus = FakeBus(_streams_one_of_each())
    started = datetime.fromtimestamp(0, tz=timezone.utc)
    out = await ti.get_memory_summary(bus, started_at=started)
    assert out["total_threats_observed"] == 3
    assert out["active_threats"] == 2
    assert out["resolved_threats"] == 1
    assert isinstance(out["uptime_hours"], float) and out["uptime_hours"] > 0


@pytest.mark.anyio
async def test_memory_summary_without_started_at_has_no_uptime() -> None:
    bus = FakeBus(_streams_one_of_each())
    out = await ti.get_memory_summary(bus)
    assert "uptime_hours" not in out


@pytest.mark.anyio
async def test_memory_entries_key_and_order() -> None:
    bus = FakeBus(_streams_one_of_each())
    out = await ti.get_memory_entries(bus, limit=2)
    assert list(out.keys()) == ["response_history"]
    assert len(out["response_history"]) == 2
    # newest first
    assert out["response_history"][0]["decision"] == "allow"


# ---------------------------------------------------------------------------
# fault isolation: one bad stream must not kill the tab
# ---------------------------------------------------------------------------


class BrokenStreamBus:
    async def read_recent(self, *, event_type, count=None):
        if event_type == "immune.verdict.block":
            raise RuntimeError("stream down")
        return _streams_one_of_each().get(event_type, [])


@pytest.mark.anyio
async def test_broken_stream_is_skipped() -> None:
    out = await ti.get_threats(BrokenStreamBus())
    assert out["count"] == 1  # only the warn survives
    assert out["threats"][0]["detector"] == "excessive_repetition"
