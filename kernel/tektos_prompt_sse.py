"""ADR-132 slice G — kernel-native prompt/sse (donor ``POST /api/prompt/sse``).

The donor engine streams ``OpenAI chat.completion.chunk`` frames to REST
clients (its WS is the primary path; this is the browser fetch fallback).
The kernel referent: a prompt runs through the kernel-owned
``TektosTurnLoop`` (Stage 8.2, ADR-104), which publishes
``tektos.agent.turn.*`` + ``session.*`` events to the event bus. The SSE
generator subscribes to those stream types and maps the envelopes that
belong to the session into the donor wire format — byte-compatible with
what the sessions page already parses (``data:`` lines of chunk JSON,
``choices[0].delta.content`` / ``finish_reason``).

Mapping (kernel events → donor chunks):
  ``turn.llm_completed``     → content chunk (delta.content = text)
  ``turn.tool_call`` (ok)    → tool_call delta (name; UI ignores, donor
                               parity so tool activity is visible)
  ``turn.completed``         → finish chunk (finish_reason = stop_reason)
  ``turn.failed``/``.blocked``→ error finish chunk (finish_reason = error)
  ``session.failed``         → error finish chunk
  (tool_call.rejected / sandbox / interrupted → no frame; UI doesn't fold
  them into the chat stream, and terminal handling happens via turn events)

The turn task is created at generator start so immune/loop-safety blocks
surface as ``turn.blocked`` frames even when no LLM call happens.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

from ports.event_bus import EventBusPort
from ports.event_envelope import EventEnvelope

logger = logging.getLogger(__name__)

# Turn event types the turn loop publishes (Stage 8.2/8.3).
_TURN_TYPES = (
    "tektos.agent.turn.started",
    "tektos.agent.turn.llm_completed",
    "tektos.agent.turn.tool_call",
    "tektos.agent.turn.tool_call.rejected",
    "tektos.agent.turn.sandbox_completed",
    "tektos.agent.turn.completed",
    "tektos.agent.turn.failed",
    "tektos.agent.turn.blocked",
    "tektos.agent.turn.interrupted",
)
# Vendor session lifecycle events that can terminate the stream.
_SESSION_TYPES = ("session.failed", "session.interrupted")

# Per-read timeout: no frame for this long → give up (client gone / LLM
# hung without publishing). Overall deadline: hard wall-clock cap.
_READ_TIMEOUT_S = 180.0
_TOTAL_TIMEOUT_S = 900.0


def sse_frame(data: Any, *, event: str | None = None) -> str:
    """One SSE frame, donor-compatible (event: line optional)."""
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data, ensure_ascii=True)}\n\n"


def _chunk(
    completion_id: str,
    created: int,
    model: str,
    *,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _error_chunk(
    completion_id: str,
    created: int,
    model: str,
    message: str,
) -> dict[str, Any]:
    chunk = _chunk(completion_id, created, model, delta={}, finish_reason="error")
    chunk["error"] = {"message": message, "type": "agent_error"}
    return chunk


def map_envelope(
    envelope: EventEnvelope,
    *,
    session_id: str,
    completion_id: str,
    created: int,
    model: str,
) -> tuple[str | None, bool]:
    """Map one bus envelope to ``(frame_or_None, is_terminal)``.

    ``frame_or_None`` is the serialized SSE frame (or ``None`` — no frame
    for this event, stream continues). ``is_terminal`` means the stream
    should close after this frame (turn/session finished, failed, or was
    blocked).
    """
    if envelope.payload.get("session_id") != session_id:
        return None, False
    et = envelope.event_type
    payload = envelope.payload

    if et == "tektos.agent.turn.llm_completed":
        text = payload.get("text", "")
        frame = sse_frame(
            _chunk(
                completion_id,
                created,
                model,
                delta={"content": text, "role": "assistant"},
            )
        )
        return frame, False

    if et == "tektos.agent.turn.tool_call":
        frame = sse_frame(
            _chunk(
                completion_id,
                created,
                model,
                delta={
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": f"call_{session_id[:8]}",
                            "type": "function",
                            "function": {
                                "name": payload.get("tool", ""),
                                "arguments": "",
                            },
                        }
                    ]
                },
            )
        )
        return frame, False

    if et == "tektos.agent.turn.completed":
        finish = payload.get("stop_reason") or "stop"
        frame = sse_frame(
            _chunk(
                completion_id,
                created,
                model,
                delta={},
                finish_reason=finish,
            )
        )
        return frame, True

    if et in ("tektos.agent.turn.failed", "tektos.agent.turn.blocked"):
        reason = payload.get("reason") or payload.get("stop_reason") or "error"
        frame = sse_frame(
            _error_chunk(
                completion_id,
                created,
                model,
                f"turn {et.rsplit('.', 1)[-1]}: {reason}",
            )
        )
        return frame, True

    if et == "session.failed":
        message = payload.get("error") or payload.get("reason") or "session failed"
        frame = sse_frame(
            _error_chunk(completion_id, created, model, str(message))
        )
        return frame, True

    # Everything else (started, tool_call.rejected, sandbox_completed,
    # interrupted, session.updated, ...) is not part of the chat stream.
    return None, False


async def stream_prompt_sse(
    *,
    bus: EventBusPort,
    loop: Any,  # TektosTurnLoop (registry.tektos_turn_loop)
    session_id: str,
    prompt: str,
    model: str,
) -> AsyncIterator[str]:
    """Run one turn and yield donor SSE frames until it completes.

    Subscribes to the turn + session stream types on the bus, runs the
    turn loop as a background task, and maps the session's events to
    frames. Always unsubscribes; the turn task is cancelled only on
    client disconnect (GeneratorExit), never on normal completion.
    """
    completion_id = f"chatcmpl-{session_id[:8]}"
    created = int(time.time())
    # subscribe is per-type (EventBusPort); one queue per stream type,
    # merged into a single fan-in queue the generator drains.
    subscriptions: list[tuple[str, asyncio.Queue[EventEnvelope]]] = [
        (t, bus.subscribe(t, maxsize=1024)) for t in (*_TURN_TYPES, *_SESSION_TYPES)
    ]
    merge: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=2048)

    async def _fanin(q: asyncio.Queue[EventEnvelope]) -> None:
        while True:
            merge.put_nowait(await q.get())

    fanin_tasks = [
        asyncio.create_task(_fanin(q), name=f"prompt-sse-fanin-{i}")
        for i, (_t, q) in enumerate(subscriptions)
    ]
    turn_task = asyncio.create_task(
        loop.run_turn(
            agent_id="tektos-sse",
            prompt=prompt,
            session_id=session_id,
        ),
        name=f"prompt-sse-turn-{session_id[:8]}",
    )
    try:
        deadline = time.monotonic() + _TOTAL_TIMEOUT_S
        while True:
            if time.monotonic() > deadline:
                logger.warning(
                    "prompt/sse: overall timeout for session=%s; closing stream",
                    session_id[:8],
                )
                yield sse_frame(
                    _error_chunk(
                        completion_id, created, model, "turn timed out"
                    )
                )
                return
            try:
                envelope = await asyncio.wait_for(merge.get(), timeout=_READ_TIMEOUT_S)
            except TimeoutError:
                logger.warning(
                    "prompt/sse: no events for %.0fs session=%s; closing stream",
                    _READ_TIMEOUT_S,
                    session_id[:8],
                )
                yield sse_frame(
                    _error_chunk(
                        completion_id, created, model, "no activity (timeout)"
                    )
                )
                return
            frame, terminal = map_envelope(
                envelope,
                session_id=session_id,
                completion_id=completion_id,
                created=created,
                model=model,
            )
            if frame is not None:
                yield frame
            if terminal:
                # Donor parity: the standalone :8020 stream terminated
                # with the OpenAI sentinel after the finish chunk.
                # Sent unquoted — the wire format is ``data: [DONE]``,
                # not a JSON string.
                yield "data: [DONE]\n\n"
                return
    finally:
        for et, q in subscriptions:
            bus.unsubscribe(et, q)
        for t in fanin_tasks:
            t.cancel()
        for t in fanin_tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        if not turn_task.done():
            # Client disconnected mid-turn: cancel it so it doesn't hold
            # LLM/sandbox resources past the request. The turn loop's
            # cancellation path publishes turn.interrupted for replay.
            turn_task.cancel()
            try:
                await turn_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
