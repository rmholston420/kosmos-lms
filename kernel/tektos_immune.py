"""ADR-133 — kernel-native immune endpoints (donor wire shapes).

The panels page ImmuneTab used to call ``:8020/api/immune/*`` — the
*standalone* engine's in-memory ImmuneSystem (threat/response stores).
In the kernel the immune referent is ``registry.immune``
(``TektosImmuneAdapter``, ADR-079): detector metadata comes straight
from ``list_detectors()``; there is no separate threat store because
**every scan publishes** ``immune.verdict.<decision>`` envelopes to the
event bus (ADR-079 rule 1). So history endpoints read the bus, the
same way ``kernel.tektos_replay`` does:

1. read the verdict event types via ``read_recent``,
2. sort by backend entry id (Valkey ``ms-seq`` ids are lexicographic),
3. map each envelope to the donor shapes the UI folds::

    detectors          → {detectors: [{name, type, enabled}], count}
    threats            → {threats: [{timestamp, detector, severity,
                                     description, resolved}], count}
    responses          → {responses: [{timestamp, decision, reason,
                                       hit_count, detectors}]}
    memory             → {total_threats_observed, active_threats,
                          resolved_threats, uptime_hours}
    memory/entries     → {response_history: [verdict rows]}

Threat semantics: a verdict with ``decision != "allow"`` (or any
non-allow hit) is a threat; ``resolved`` tracks decision (``allow`` →
resolved, ``warn``/``block`` → active). ``allow`` verdicts are
responses-only, not threats — the donor's "threat" is something a
detector flagged, and a clean scan flags nothing.
"""

from __future__ import annotations

from typing import Any

from ports.event_envelope import EventEnvelope

# ADR-079 rule 1: scan() publishes immune.verdict.<decision>.
VERDICT_EVENT_TYPES: tuple[str, ...] = (
    "immune.verdict.allow",
    "immune.verdict.warn",
    "immune.verdict.block",
)

# Bus retention window per verdict stream (the donor kept its whole
# in-memory store; the kernel keeps a bounded ring — the UI shows at
# most 50 threats / 20 responses / 20 entries, so 500 has headroom).
DEFAULT_COUNT = 500


def _entry_sort_key(entry_id: str) -> tuple[int, int]:
    """Valkey entry id ``<ms>-<seq>`` → numeric sort key.

    Lexicographic order breaks at digit-count boundaries
    (``9-0`` vs ``10-0``); parse both halves to int.
    """
    parts = entry_id.split("-")
    try:
        if len(parts) == 2:
            return (int(parts[0]), int(parts[1]))
        return (int(parts[0]), 0)
    except (ValueError, IndexError):  # pragma: no cover — synthetic ids
        return (-1, 0)


async def _read_verdicts(
    event_bus: Any,
    *,
    count: int = DEFAULT_COUNT,
) -> list[EventEnvelope]:
    """All verdict envelopes, oldest first. One bad stream is skipped."""
    collected: list[tuple[str, EventEnvelope]] = []
    for et in VERDICT_EVENT_TYPES:
        try:
            items = await event_bus.read_recent(event_type=et, count=count)
        except Exception:  # noqa: BLE001 — one bad stream shouldn't kill the tab
            continue
        collected.extend(items)
    collected.sort(key=lambda item: _entry_sort_key(item[0]))
    return [envelope for _, envelope in collected]


def _verdict_row(envelope: EventEnvelope) -> dict[str, Any]:
    """One verdict envelope → the row shape shared by threats/responses/entries."""
    payload = envelope.payload or {}
    hits = payload.get("hits") or []
    ts = envelope.occurred_at.isoformat()
    return {
        "timestamp": ts,
        "decision": payload.get("decision", "allow"),
        "reason": payload.get("reason", ""),
        "hit_count": payload.get("hit_count", len(hits)),
        "source_plugin": payload.get("source_plugin", ""),
        "kind": payload.get("kind", ""),
        "hits": hits,
        # Donor-compat aliases the UI threat table reads:
        "detector": next(
            (h.get("detector") for h in hits if h.get("detector")), ""
        ),
        "severity": next(
            (h.get("severity") for h in hits if h.get("severity")),
            payload.get("decision", "allow"),
        ),
        "description": payload.get("reason", ""),
    }


async def get_detectors(immune: Any) -> dict[str, Any]:
    """Donor shape ``{detectors: [{name, type}], count}``.

    ``type`` in the donor is the detector *class* name; the kernel's
    ``DetectorInfo`` carries no class name, so ``type`` is the
    ``severity_ceiling``-tagged adapter class name — a stable
    non-fabricated identifier. ``enabled`` is always true (detectors
    register or don't; there is no per-detector kill switch).
    """
    infos = await immune.list_detectors()
    rows = [
        {
            "name": info.name,
            "type": f"TektosDetector[{info.severity_ceiling}]",
            "severity_ceiling": info.severity_ceiling,
            "description": info.description,
            "enabled": True,
        }
        for info in infos
    ]
    return {"detectors": rows, "count": len(rows)}


async def get_threats(
    event_bus: Any, *, resolved: bool = False, count: int = DEFAULT_COUNT
) -> dict[str, Any]:
    """Donor shape ``{threats: [...], count}``.

    A threat is a verdict with a non-allow outcome. ``resolved=True``
    includes allow verdicts (the donor's resolved partition); by
    default only active (warn/block) threats are returned.
    """
    verdicts = await _read_verdicts(event_bus, count=count)
    rows: list[dict[str, Any]] = []
    for envelope in verdicts:
        row = _verdict_row(envelope)
        active = row["decision"] in ("warn", "block")
        if active or resolved:
            row["resolved"] = not active
            rows.append(row)
    return {"threats": rows, "count": len(rows)}


async def get_responses(
    event_bus: Any, *, limit: int = 20
) -> dict[str, Any]:
    """Donor shape ``{responses: [...]}`` — newest first (response history)."""
    verdicts = await _read_verdicts(event_bus)
    rows = [_verdict_row(e) for e in verdicts]
    return {"responses": list(reversed(rows))[:limit]}


async def get_memory_summary(
    event_bus: Any, *, started_at: Any = None
) -> dict[str, Any]:
    """Donor shape ``{total_threats_observed, active_threats, resolved_threats, uptime_hours}``.

    ``uptime_hours`` is the adapter's process uptime when
    ``started_at`` (a ``datetime``) is supplied; ``None`` otherwise
    (the UI renders ``—``).
    """
    verdicts = await _read_verdicts(event_bus)
    threats = [
        r for r in (_verdict_row(e) for e in verdicts) if r["decision"] in ("warn", "block")
    ]
    summary: dict[str, Any] = {
        "total_threats_observed": len(verdicts),
        "active_threats": len(threats),
        "resolved_threats": len(verdicts) - len(threats),
    }
    if started_at is not None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        summary["uptime_hours"] = max(
            0.0, (now - started_at).total_seconds() / 3600.0
        )
    return summary


async def get_memory_entries(
    event_bus: Any, *, limit: int = 50
) -> dict[str, Any]:
    """Donor shape ``{response_history: [...]}`` (the UI reads this key first)."""
    verdicts = await _read_verdicts(event_bus)
    rows = [_verdict_row(e) for e in verdicts]
    return {"response_history": list(reversed(rows))[:limit]}
