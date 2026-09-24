"""Vendor bindings — the ONLY translation layer between donor code and Kosmos.

Per ADR-103 D2 and the kosmos-port-workflow fidelity rule, donor files
under ``adapters/session/tektos/vendor/`` are kept **verbatim** with
exactly three import-line rewrites:

1. Vendor ``state_machine.py``
   ``from tektos.event_bus import get_event_bus``
   → ``from adapters.session.tektos.vendor_bindings import get_event_bus``

2. Vendor ``session.py``
   ``from tektos.state_machine import State, get_state_machine``
   → ``from adapters.session.tektos.vendor.state_machine import State, get_state_machine``

3. Vendor ``session.py``
   ``from tektos.store.event_store import append_event``
   → ``from adapters.session.tektos.vendor_bindings import append_event``

   (also ``from tektos.store.event_store import delete_session as store_delete``
   in ``_delete_events`` → ``from adapters.session.tektos.vendor_bindings
   import store_delete``.)

All four names (``get_event_bus``, ``append_event``, ``store_delete``, plus
the ``bind_event_bus`` / ``bind_relational_memory`` install helpers) resolve
to shims that forward into the Kosmos ports injected at ``TektosSessionAdapter``
construction time.

Adapter-level rules:

- Shims MUST NOT raise on donor-side call. Donor code wraps its calls in
  broad ``try/except`` blocks already; failures surface via WARNING logs.
- Shims are **process-global** and bound at adapter construction. Multiple
  ``TektosSessionAdapter`` instances in one process is not supported at
  Stage 8.1 (matches donor singleton assumption). If needed later this
  becomes ADR territory.
- The RelationalMemoryPort mirror path is threaded through
  ``bind_relational_memory`` + the ``_maybe_mirror`` helper here, so the
  vendor code stays completely unaware of Stage 8.0.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "bind_event_bus",
    "bind_relational_memory",
    "unbind_all",
    "get_event_bus",
    "append_event",
    "store_delete",
]


# ---------------------------------------------------------------------------
# Module-level singletons — bound at TektosSessionAdapter construction.
# ---------------------------------------------------------------------------

_event_bus: Any | None = None
_relational_memory: Any | None = None
# Strong references to in-flight mirror tasks. The event loop holds only weak
# refs to tasks, so without this set a GC sweep could drop a scheduled
# write mid-flight and silently lose a session audit-ledger entry.
_pending_mirror_tasks: set[asyncio.Future] = set()


def bind_event_bus(event_bus: Any) -> None:
    """Install the injected EventBusPort. Idempotent (rebinds)."""
    global _event_bus
    _event_bus = event_bus


def bind_relational_memory(memory: Any | None) -> None:
    """Install the optional RelationalMemoryPort mirror target."""
    global _relational_memory
    _relational_memory = memory


def unbind_all() -> None:
    """Reset both singletons. Used by tests to prevent cross-test leaks."""
    global _event_bus, _relational_memory
    _event_bus = None
    _relational_memory = None


# ---------------------------------------------------------------------------
# Envelope construction
# ---------------------------------------------------------------------------


def _build_envelope(
    event_type: str,
    session_id: str,
    payload: dict[str, Any] | None,
) -> Any:
    """Build an ADR-023-compliant ``EventEnvelope`` for the injected bus.

    Imported lazily so port-scope imports don't drag in the envelope
    module at module load and the in-memory adapter branch stays free
    of that dependency.
    """
    from ports.event_envelope import EventEnvelope

    body = dict(payload or {})
    body.setdefault("session_id", session_id)
    return EventEnvelope(
        producer_plugin="tektos.session",
        event_type=event_type,
        payload=body,
    )


# ---------------------------------------------------------------------------
# EventBusPort shim
# ---------------------------------------------------------------------------


class _EventBusShim:
    """Wraps 3-arg positional ``publish(event_type, session_id, payload)``
    donor calls into an envelope-first :class:`EventBusPort` publish."""

    def __init__(self, event_bus: Any) -> None:
        self._bus = event_bus

    def publish(
        self,
        event_type: str,
        session_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            envelope = _build_envelope(event_type, session_id, payload)
        except Exception:  # pragma: no cover — degenerate envelope build
            log.exception("Failed to build event envelope for %s", event_type)
            return
        try:
            result = self._bus.publish(envelope)
            if inspect.isawaitable(result):
                # Donor publish is sync-fire-and-forget. Schedule the
                # coroutine so the caller isn't obliged to await.
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # No running loop — drive synchronously.
                    asyncio.run(result)  # type: ignore[arg-type]
                else:
                    loop.create_task(result)  # type: ignore[arg-type]
        except Exception:
            log.exception("EventBus publish failed for %s", event_type)

        # After every publish, mirror to RelationalMemoryPort when bound.
        _maybe_mirror(event_type, session_id, payload or {})


def get_event_bus() -> _EventBusShim:
    """Donor call site: ``get_event_bus().publish(...)``. Returns a shim
    that adapts positional donor publishes to envelope-first Kosmos.

    Raises ``RuntimeError`` when no adapter has been constructed —
    this is a programming error, not a runtime one, so it should
    surface loudly during tests rather than degrade silently.
    """
    if _event_bus is None:
        raise RuntimeError(
            "adapters.session.tektos.vendor_bindings.get_event_bus() called "
            "before TektosSessionAdapter constructed a bound event bus"
        )
    return _EventBusShim(_event_bus)


# ---------------------------------------------------------------------------
# EventStorePort shim (deferred to Stage 13; publishes envelope only)
# ---------------------------------------------------------------------------


async def append_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Donor call site: ``await append_event(session_id, event_type, {...})``.

    Stage 8.1 routes lifecycle events through the same EventBusPort
    used by state transitions. ADR-103 D3 defers a durable
    ``EventStorePort`` to Stage 13.
    """
    if _event_bus is None:
        log.warning(
            "append_event called for %s/%s with no bound event bus", session_id, event_type
        )
        return
    try:
        envelope = _build_envelope(event_type, session_id, payload)
    except Exception:  # pragma: no cover
        log.exception("Failed to build event envelope for %s", event_type)
        return
    try:
        result = _event_bus.publish(envelope)
        if inspect.isawaitable(result):
            await result  # type: ignore[misc]
    except Exception:
        log.exception("EventBus publish failed for %s", event_type)
    _maybe_mirror(event_type, session_id, payload or {})


async def store_delete(session_id: str) -> int:
    """Donor call site: ``await store_delete(session_id)`` inside
    ``SessionManager._delete_events``.

    Stage 8.1 has no event store; returns 0 with an INFO log per
    ADR-103 D3.
    """
    log.info(
        "adapters.session.tektos.store_delete(%s): deferred to Stage 13 (ADR-103 D3)",
        session_id,
    )
    return 0


# ---------------------------------------------------------------------------
# RelationalMemoryPort mirror
# ---------------------------------------------------------------------------


def _maybe_mirror(
    event_type: str,
    session_id: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort mirror to the Stage 8.0 audit ledger.

    Failures are logged but never re-raised — the FSM is the source
    of truth, the ledger is derived audit (ADR-103 D2).
    """
    memory = _relational_memory
    if memory is None:
        return
    try:
        # Kind lifted from event_type without the "session." prefix
        # when present. Falls back to the raw event_type when the donor
        # emits something outside the session.* namespace.
        kind = (
            f"session.{event_type.split('.', 1)[1]}"
            if event_type.startswith("session.")
            else event_type
        )
        # RelationalMemoryPort.record_event may be sync or async depending
        # on adapter; the port protocol is async, so schedule when needed.
        result = memory.record_event(
            kind=kind,
            entity_id=session_id,
            payload=dict(payload),
            provenance="tektos.session",
            confidence=1.0,
        )
        if inspect.isawaitable(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(result)  # type: ignore[arg-type]
            else:
                task = asyncio.ensure_future(result)
                # Hold a strong ref until completion; the loop only holds a
                # weak ref, so without this the task can be GC'd mid-flight.
                _pending_mirror_tasks.add(task)
                task.add_done_callback(_pending_mirror_tasks.discard)
    except Exception:
        log.exception(
            "RelationalMemoryPort mirror failed for %s/%s", session_id, event_type
        )
