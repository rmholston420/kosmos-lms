"""ADR-132 slice F — kernel-native session replay (donor wire shape).

The sessions page used to call ``:8020/api/sessions/{id}/replay``, which
returned the standalone engine's event-store rows::

    [{seq, type, payload, protocol_version, created_at}, ...]   # seq asc

The UI folds that list into a conversation on ``type`` (``assistant.delta``,
``tool.started``, ``assistant.completed``, ...). In the kernel the per-session
chat history lives in the event bus (Valkey, one stream per event type), not
in a per-session store, so this module:

1. reads the known Tektos event types from the bus (``read_recent``),
2. filters to the requested ``session_id`` (payload field),
3. sorts by the backend entry id (Valkey ms-seq ids are lexicographic),
4. maps kernel event types to the donor chat-event types the UI folds::

    tektos.agent.turn.llm_completed   → assistant.delta {text}
    tektos.agent.turn.tool_call       → tool.started / tool.completed
    tektos.agent.turn.sandbox_completed → tool.completed {status, output}
    tektos.agent.turn.completed       → assistant.completed {stop_reason}
    tektos.agent.turn.blocked         → (skipped — the vendor manager's
                                         session.failed already carries it)
    session.{created,ready,updated,interrupted,failed} → passthrough

Lifecycle passthrough events are included for donor fidelity (the UI's
``default`` case ignores them), and every row keeps the donor envelope shape
so the endpoint is drop-in compatible with ``:8020`` replay.
"""

from __future__ import annotations

from typing import Any

from ports.event_envelope import EventEnvelope

# Event types the kernel emits for Tektos sessions, in no particular order
# (ordering comes from the backend entry id, not this list).
TURN_EVENT_TYPES: tuple[str, ...] = (
    "tektos.agent.turn.started",
    "tektos.agent.turn.llm_completed",
    "tektos.agent.turn.tool_call",
    "tektos.agent.turn.sandbox_completed",
    "tektos.agent.turn.completed",
    "tektos.agent.turn.blocked",
)

LIFECYCLE_EVENT_TYPES: tuple[str, ...] = (
    "session.created",
    "session.ready",
    "session.updated",
    "session.interrupted",
    "session.failed",
)

REPLAY_EVENT_TYPES: tuple[str, ...] = TURN_EVENT_TYPES + LIFECYCLE_EVENT_TYPES


def _entry_sort_key(entry_id: str) -> tuple[int, int]:
    """Valkey entry id ``<ms>-<seq>`` → numeric sort key.

    Redis/Valkey compares ids numerically (``ms`` first, then ``seq``);
    a plain string sort is only safe while every id has the same digit
    count, which is not a guarantee we want to rely on.
    """
    ms, _, seq = entry_id.partition("-")
    try:
        return (int(ms), int(seq or 0))
    except ValueError:  # pragma: no cover — non-numeric ids are foreign
        return (0, 0)


def _map_envelope(envelope: EventEnvelope) -> dict[str, Any] | None:
    """Map one kernel envelope to a donor-shape row, or ``None`` to skip."""
    et = envelope.event_type
    p = envelope.payload or {}
    session_id = p.get("session_id")

    if et == "tektos.agent.turn.llm_completed":
        # ADR-132 slice F (F2a): the turn loop carries the assistant text
        # here so replay can reconstruct the conversation.
        return {"type": "assistant.delta", "payload": {"text": str(p.get("text", ""))}}

    if et == "tektos.agent.turn.tool_call":
        tool = str(p.get("tool") or "tool")
        if p.get("accepted"):
            return {
                "type": "tool.started",
                "payload": {"tool_name": tool, "tool_input": {}},
            }
        return {
            "type": "tool.completed",
            "payload": {
                "status": str(p.get("reason") or "rejected"),
                "output": "",
            },
        }

    if et == "tektos.agent.turn.sandbox_completed":
        exit_code = p.get("exit_code")
        status = "done" if exit_code == 0 else f"exit_{exit_code}"
        return {
            "type": "tool.completed",
            "payload": {
                "status": status,
                "output": (
                    f"exit_code={exit_code}, "
                    f"wall_seconds={p.get('wall_seconds')}"
                ),
            },
        }

    if et == "tektos.agent.turn.completed":
        return {
            "type": "assistant.completed",
            "payload": {"stop_reason": str(p.get("stop_reason") or "end_turn")},
        }

    if et == "tektos.agent.turn.blocked":
        # The turn loop calls the session port on block (thermal/immune),
        # which publishes session.failed — emitting that here too would
        # double the error note in the UI.
        return None

    if et in LIFECYCLE_EVENT_TYPES:
        body = dict(p)
        body.setdefault("session_id", session_id)
        return {"type": et, "payload": body}

    return None


async def get_replay(
    event_bus: Any,
    session_id: str,
    *,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """Full replay for one session, donor shape, oldest first.

    ``event_bus`` is anything with ``async read_recent(event_type=...,
    count=...) -> list[tuple[entry_id, EventEnvelope]]`` (the Valkey
    adapter satisfies this). Rows missing ``session_id`` in the payload
    are dropped; ``seq`` is renumbered 1..N over the surviving rows so the
    shape matches the donor store regardless of bus retention.
    """
    collected: list[tuple[str, EventEnvelope]] = []
    for et in REPLAY_EVENT_TYPES:
        try:
            items = await event_bus.read_recent(event_type=et, count=count)
        except Exception:  # noqa: BLE001 — one bad stream shouldn't kill replay
            continue
        for entry_id, envelope in items:
            if (envelope.payload or {}).get("session_id") != session_id:
                continue
            collected.append((entry_id, envelope))

    # Valkey entry ids are "ms-seq": sort numerically (ms, then seq).
    collected.sort(key=lambda item: _entry_sort_key(item[0]))

    rows: list[dict[str, Any]] = []
    seq = 0
    for _, envelope in collected:
        mapped = _map_envelope(envelope)
        if mapped is None:
            continue
        seq += 1
        rows.append(
            {
                "seq": seq,
                "type": mapped["type"],
                "payload": mapped["payload"],
                "protocol_version": envelope.schema_version,
                "created_at": int(envelope.occurred_at.timestamp() * 1000),
            }
        )
    return rows
