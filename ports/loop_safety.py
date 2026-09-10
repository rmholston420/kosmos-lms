"""ports.loop_safety — LoopSafetyPort Protocol (ADR-080, ADR-088).

Formal Kosmos port for per-turn agent loop safety. Locked at Stage 3.13.
First adapter (Tektos-Ultima donor: 3-tier caps + repetition detector +
read-only budget interlock) lands under ``adapters/loop_safety/tektos/``.

Enforcement rules (per ADR-080 + ADR-088 + spec §25.6, §25.7):

1. Every state transition MUST publish ``loop_safety.<status>`` on
   ``EventBusPort`` with the ``TurnHandle.turn_id`` as correlation id.
2. Every terminal state (``exhausted`` / ``repetition`` / ``budget_exhausted``)
   MUST write a ``MemoryPort`` event with ``provenance="loop_safety"`` and
   ``confidence=1.0``.
3. ``record_tool_call(read_only=True)`` decrements the read-only budget.
   When it hits zero, the next such call returns ``"budget_exhausted"``
   (ADR-088) and forces text-only turn completion.
4. Non-read-only tool calls do NOT consume the read-only budget.
5. Budget resets at ``begin_turn()`` — no cross-turn carryover.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "LoopCaps",
    "LoopSafetyPort",
    "LoopSafetyState",
    "LoopSafetyStatus",
    "TurnHandle",
    "TurnSummary",
    "validate_loop_caps",
]


LoopSafetyStatus = Literal[
    "ok",
    "warn",
    "exhausted",
    "repetition",
    "budget_exhausted",
]
"""Per-turn loop-safety state — see ADR-080 + ADR-088."""


@dataclass(frozen=True, slots=True)
class LoopCaps:
    """Per-turn safety caps. Immutable.

    Defaults match spec §25.7 (from Tektos-Ultima's operational values).
    Callers may override per turn via ``LoopSafetyPort.begin_turn(config=...)``.
    """

    max_turns: int = 15
    max_tokens_total: int = 65_536
    max_wall_time_seconds: int = 300
    repetition_window: int = 3
    read_only_budget: int = 10  # ADR-088 interlock default


@dataclass(frozen=True, slots=True)
class TurnHandle:
    """Opaque handle returned from ``begin_turn``. Immutable.

    Callers pass this to every ``record_*`` / ``check_*`` / ``end_turn`` call
    to identify which turn they are talking about.
    """

    turn_id: str
    agent_id: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class LoopSafetyState:
    """Immutable state snapshot returned from every recording call.

    ``budget_remaining`` is the read-only tool-call budget remaining for the
    current turn (see ADR-088).
    """

    status: LoopSafetyStatus
    detail: str
    budget_remaining: int


@dataclass(frozen=True, slots=True)
class TurnSummary:
    """Immutable summary returned from ``end_turn``."""

    turn_id: str
    ended_at: datetime
    tokens_total: int
    tool_calls: int
    read_only_calls: int
    terminal_status: LoopSafetyStatus


def validate_loop_caps(caps: LoopCaps) -> None:
    """Enforce sanity bounds at the port layer. Raises ``ValueError``."""
    if caps.max_turns <= 0:
        raise ValueError("LoopCaps.max_turns must be > 0.")
    if caps.max_tokens_total <= 0:
        raise ValueError("LoopCaps.max_tokens_total must be > 0.")
    if caps.max_wall_time_seconds <= 0:
        raise ValueError("LoopCaps.max_wall_time_seconds must be > 0.")
    if caps.repetition_window <= 0:
        raise ValueError("LoopCaps.repetition_window must be > 0.")
    if caps.read_only_budget < 0:
        raise ValueError("LoopCaps.read_only_budget must be >= 0.")


@runtime_checkable
class LoopSafetyPort(Protocol):
    """Formal Kosmos contract for per-turn loop safety enforcement."""

    # ── Turn lifecycle ────────────────────────────────────────────────────

    async def begin_turn(
        self,
        agent_id: str,
        config: LoopCaps | None = None,
    ) -> TurnHandle:
        """Open a new safety-tracked turn for ``agent_id``.

        ``config`` defaults to the adapter's configured ``LoopCaps``; callers
        may pass a stricter set. Resets the read-only budget (ADR-088).
        """
        ...

    async def end_turn(self, handle: TurnHandle) -> TurnSummary:
        """Close the turn and return its summary.

        Idempotent — calling twice on the same handle returns the same summary.
        """
        ...

    # ── Recording (each may transition state) ─────────────────────────────

    async def record_tokens(
        self,
        handle: TurnHandle,
        tokens: int,
    ) -> LoopSafetyState:
        """Record ``tokens`` produced this turn. Returns current state."""
        ...

    async def record_tool_call(
        self,
        handle: TurnHandle,
        *,
        read_only: bool,
    ) -> LoopSafetyState:
        """Record a tool call. Consumes read-only budget iff ``read_only=True``.

        When the read-only budget is exhausted, returns
        ``status="budget_exhausted"`` and publishes
        ``loop_safety.read_only_budget_exhausted`` on ``EventBusPort``
        (ADR-088). Runtime MUST complete the turn with text only after that.
        """
        ...

    async def check_repetition(
        self,
        handle: TurnHandle,
        action_hash: str,
    ) -> LoopSafetyState:
        """Return ``status="repetition"`` if ``action_hash`` recurs within
        ``LoopCaps.repetition_window`` consecutive calls; else ``"ok"``."""
        ...

    # ── Health & lifecycle ────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Return True iff the adapter is ready. Non-throwing."""
        ...

    async def close(self) -> None:
        """Release adapter resources. Idempotent."""
        ...
