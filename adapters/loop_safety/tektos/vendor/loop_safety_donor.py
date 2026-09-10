# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/runtime/loop_safety.py
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole copyright).
# Modifications from upstream: none (verbatim vendor snapshot).
# See docs/adrs/ADR-092-tektos-runtime-absorption-scope.md and PORTING_LEDGER.md.

"""Loop safety — prevent infinite agent loops.

Tier 1: Hard limits (deterministic enforcement)
- max_turns: Maximum LLM turns per prompt (already 10, but configurable)
- max_tokens: Token budget per turn and per session
- max_wall_time: Maximum wall-clock time per prompt

Tier 2: Repetition detection (behavioral guardrail)
- Detect when the agent repeats the same tool calls in the same order
- Detect when the agent produces identical text responses
- Detect when the agent oscillates between two states

Tier 3: Circuit breaker (emergency stop)
- If repetition threshold is exceeded, force-stop and report
- If token budget is exceeded, truncate and report
- If wall time is exceeded, force-stop and report

This is the safety net that prevents Tektos from becoming a token-burning
black hole. Without it, a confused agent can run forever.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class LoopState(str, Enum):
    """States for the loop safety monitor."""

    NORMAL = "normal"
    WARNING = "warning"  # Approaching limits
    CRITICAL = "critical"  # Exceeded threshold, will stop next turn
    STOPPED = "stopped"  # Loop has been stopped


class StopReason(str, Enum):
    """Why the loop was stopped."""

    MAX_TURNS = "max_turns"
    MAX_TOKENS = "max_tokens"
    MAX_WALL_TIME = "max_wall_time"
    REPETITION = "repetition"
    CIRCUIT_BREAKER = "circuit_breaker"


@dataclass
class TurnSnapshot:
    """Snapshot of a single LLM turn for repetition detection."""

    turn_num: int
    tool_calls: tuple[str, ...]  # tool names, frozen for hashability
    input_ids: tuple[str, ...] = ()  # "name:hash(args)" per call — distinguishes
    # different commands that use the same tool
    text_length: int = 0
    tokens_used: int = 0


@dataclass
class LoopSafetyConfig:
    """Configuration for loop safety limits."""

    # Hard limits
    max_turns: int = 15
    max_tokens_per_turn: int = 8192
    max_tokens_total: int = 65536
    max_wall_time_seconds: float = 300.0

    # Repetition detection
    repetition_window: int = 3
    repetition_threshold: int = 2

    # Circuit breaker
    warning_threshold_pct: float = 0.8
    circuit_breaker_enabled: bool = True


@dataclass
class LoopSafetyReport:
    """Report on loop safety status."""

    state: LoopState
    stop_reason: StopReason | None = None
    current_turn: int = 0
    max_turns: int = 15
    turns_remaining: int = 15
    tokens_used: int = 0
    tokens_total: int = 0
    tokens_remaining: int = 0
    wall_time_seconds: float = 0.0
    wall_time_remaining: float = 0.0
    repetition_count: int = 0
    last_tool_sequence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def is_safe(self) -> bool:
        # WARNING is a non-fatal advisory tier — the agent may continue.
        # Only CRITICAL/STOPPED (hard limits, confirmed repetition) are unsafe.
        return self.state not in (LoopState.CRITICAL, LoopState.STOPPED)

    def is_critical(self) -> bool:
        return self.state in (LoopState.CRITICAL, LoopState.STOPPED)


class LoopSafetyMonitor:
    """Monitors agent loops and enforces safety limits.

    Usage:
        monitor = LoopSafetyMonitor()
        report = monitor.check_turn(turn_num=1, tokens_used=100, tool_calls=["bash"])

        if report.is_critical():
            # Stop the agent gracefully
            break
    """

    def __init__(self, config: LoopSafetyConfig | None = None) -> None:
        self.config = config or LoopSafetyConfig()
        self._snapshots: deque[TurnSnapshot] = deque(maxlen=50)
        self._start_time: float = time.monotonic()
        self._total_tokens: int = 0
        self._state: LoopState = LoopState.NORMAL
        self._stop_reason: StopReason | None = None
        self._repetition_count: int = 0
        self._has_warned_threshold: bool = False

    def check_turn(
        self,
        turn_num: int,
        tokens_used: int = 0,
        tool_calls: list[str] | None = None,
        text_length: int = 0,
        input_ids: list[str] | None = None,
    ) -> LoopSafetyReport:
        """Check if the current turn is safe to continue.

        Args:
            turn_num: Current turn number (1-indexed).
            tokens_used: Tokens used in this turn.
            tool_calls: List of tool names called in this turn.
            text_length: Character length of assistant text in this turn.
            input_ids: Per-call "name:hash(args)" identifiers. When provided,
                repetition detection compares these (actual command content)
                instead of bare tool names, so a sequence of *different* bash
                commands is not flagged as a loop.

        Returns:
            LoopSafetyReport reflecting the current state AFTER this turn.
        """
        # 1. Record snapshot
        self._snapshots.append(
            TurnSnapshot(
                turn_num=turn_num,
                tool_calls=tuple(tool_calls or []),
                input_ids=tuple(input_ids or []),
                text_length=text_length,
                tokens_used=tokens_used,
            )
        )
        self._total_tokens += tokens_used
        wall_time = time.monotonic() - self._start_time

        # 2. Evaluate hard limits FIRST
        if turn_num >= self.config.max_turns:
            self._state = LoopState.STOPPED
            self._stop_reason = StopReason.MAX_TURNS
            return self._build_report(
                turn_num,
                tool_calls or [],
                wall_time,
                tokens_used,
                stop_reason=StopReason.MAX_TURNS,
            )

        if self._total_tokens >= self.config.max_tokens_total:
            self._state = LoopState.STOPPED
            self._stop_reason = StopReason.MAX_TOKENS
            return self._build_report(
                turn_num,
                tool_calls or [],
                wall_time,
                tokens_used,
                stop_reason=StopReason.MAX_TOKENS,
            )

        if wall_time >= self.config.max_wall_time_seconds:
            self._state = LoopState.STOPPED
            self._stop_reason = StopReason.MAX_WALL_TIME
            return self._build_report(
                turn_num,
                tool_calls or [],
                wall_time,
                tokens_used,
                stop_reason=StopReason.MAX_WALL_TIME,
            )

        # 3. Check repetition detection
        rep_detected = False
        rep_count = 0
        if len(self._snapshots) >= self.config.repetition_window:
            recent = list(self._snapshots)[-self.config.repetition_window :]
            if self._detect_repetition(recent):
                self._repetition_count += 1
                rep_detected = True
                rep_count = self._repetition_count

                if rep_count >= self.config.repetition_threshold:
                    self._state = LoopState.STOPPED
                    self._stop_reason = StopReason.REPETITION
                    return self._build_report(
                        turn_num,
                        tool_calls or [],
                        wall_time,
                        tokens_used,
                        rep_count=rep_count,
                        stop_reason=StopReason.REPETITION,
                    )
                elif rep_count >= 1:
                    self._state = LoopState.WARNING
            elif self._state == LoopState.WARNING and not self._has_warned_threshold:
                # Behavior changed — repetition no longer detected on this
                # window. Demote back to NORMAL so a recovered agent is not
                # latched in WARNING for the rest of the session.
                self._repetition_count = 0
                self._state = LoopState.NORMAL

        # 4. Check warning thresholds
        if self._state == LoopState.NORMAL and not self._has_warned_threshold:
            token_pct = self._total_tokens / max(1, self.config.max_tokens_total)
            turn_pct = turn_num / max(1, self.config.max_turns)
            time_pct = wall_time / max(0.001, self.config.max_wall_time_seconds)
            if (
                turn_pct >= self.config.warning_threshold_pct
                or token_pct >= self.config.warning_threshold_pct
                or time_pct >= self.config.warning_threshold_pct
            ):
                self._state = LoopState.WARNING
                self._has_warned_threshold = True

        return self._build_report(
            turn_num,
            tool_calls or [],
            wall_time,
            tokens_used,
            rep_count=self._repetition_count if rep_detected else 0,
        )

    def _build_report(
        self,
        turn_num: int,
        tool_calls: list[str],
        wall_time: float,
        tokens_used: int,
        rep_count: int = 0,
        stop_reason: StopReason | None = None,
    ) -> LoopSafetyReport:
        """Construct the final report after all checks."""
        warnings: list[str] = []

        if stop_reason == StopReason.MAX_TURNS:
            warnings.append(f"Loop stopped: reached max turns ({self.config.max_turns})")
        elif stop_reason == StopReason.MAX_TOKENS:
            warnings.append(f"Loop stopped: reached max tokens ({self.config.max_tokens_total})")
        elif stop_reason == StopReason.MAX_WALL_TIME:
            warnings.append(
                f"Loop stopped: exceeded max wall time ({self.config.max_wall_time_seconds}s)"
            )
        elif stop_reason == StopReason.REPETITION:
            warnings.append(f"Loop stopped: repetitive behavior ({rep_count} cycles)")
        elif self._state == LoopState.WARNING and not rep_count:
            warnings.append(
                f"Warning: approaching safety limits "
                f"(turns {turn_num}/{self.config.max_turns}, "
                f"tokens {self._total_tokens}/{self.config.max_tokens_total})"
            )
        elif rep_count > 0:
            warnings.append(
                f"Warning: repetitive behavior detected (turn {turn_num}, count {rep_count})"
            )

        return LoopSafetyReport(
            state=self._state,
            stop_reason=stop_reason or self._stop_reason,
            current_turn=turn_num,
            max_turns=self.config.max_turns,
            turns_remaining=max(0, self.config.max_turns - turn_num),
            tokens_used=self._total_tokens,
            tokens_total=self.config.max_tokens_total,
            tokens_remaining=max(0, self.config.max_tokens_total - self._total_tokens),
            wall_time_seconds=wall_time,
            wall_time_remaining=max(0, self.config.max_wall_time_seconds - wall_time),
            repetition_count=rep_count,
            last_tool_sequence=tool_calls,
            warnings=warnings,
        )

    def _detect_repetition(self, snapshots: list[TurnSnapshot]) -> bool:
        """Detect if recent turns show repetitive behavior.

        Patterns detected:
        1. Same tool call sequence repeated across N turns
        2. Same text length repeated (stuck in output generation)
        3. Pure tool-call loops with zero text output
        """
        if len(snapshots) < self.config.repetition_threshold:
            return False

        # Only consider turns that actually made tool calls for pattern 1
        toolful = [s for s in snapshots if s.tool_calls]
        if len(toolful) >= self.config.repetition_threshold:
            # Prefer comparing actual command content (input_ids) so that a
            # sequence of *different* bash commands is not flagged as a loop.
            with_inputs = [s for s in toolful if s.input_ids]
            seq_getter = (
                (lambda s: s.input_ids)
                if len(with_inputs) == len(toolful)
                else (lambda s: s.tool_calls)
            )
            sequences = [seq_getter(s) for s in toolful]
            last_seq = sequences[-1]
            if last_seq:  # non-empty
                match_count = sum(1 for ts in sequences[:-1] if ts == last_seq)
                if match_count >= self.config.repetition_threshold - 1:
                    return True

        # Pattern 2: same text length repeated (stuck in output generation).
        # Only applies to turns with NO tool calls — a turn that emits similar
        # text while also making different tool calls is legitimate progress,
        # not a loop. Requiring zero tools avoids false positives on agents
        # that produce comparable-length reasoning before each distinct command.
        if len(snapshots) >= 3:
            recent_text = [s for s in snapshots[-3:] if not s.tool_calls]
            if len(recent_text) == 3:
                lengths = [s.text_length for s in recent_text]
                min_len = min(lengths)
                if min_len > 0 and max(lengths) / min_len <= 1.10:
                    return True

        # Pattern 3: repeated tool calls with zero text output
        recent = snapshots[-self.config.repetition_window :]
        textless_tool_turns = sum(1 for s in recent if s.text_length == 0 and s.tool_calls)
        if textless_tool_turns >= self.config.repetition_threshold:
            return True

        return False

    def get_report(self) -> LoopSafetyReport:
        """Get current loop safety report without consuming a turn."""
        wall_time = time.monotonic() - self._start_time
        last_tools = list(self._snapshots[-1].tool_calls) if self._snapshots else []
        return LoopSafetyReport(
            state=self._state,
            stop_reason=self._stop_reason,
            current_turn=len(self._snapshots),
            max_turns=self.config.max_turns,
            turns_remaining=max(0, self.config.max_turns - len(self._snapshots)),
            tokens_used=self._total_tokens,
            tokens_total=self.config.max_tokens_total,
            tokens_remaining=max(0, self.config.max_tokens_total - self._total_tokens),
            wall_time_seconds=wall_time,
            wall_time_remaining=max(0, self.config.max_wall_time_seconds - wall_time),
            repetition_count=self._repetition_count,
            last_tool_sequence=last_tools,
            warnings=[],
        )

    def reset(self) -> None:
        """Reset the monitor for a new prompt/session."""
        self._snapshots.clear()
        self._start_time = time.monotonic()
        self._total_tokens = 0
        self._state = LoopState.NORMAL
        self._stop_reason = None
        self._repetition_count = 0
        self._has_warned_threshold = False

    def detect_stall(
        self, event_count: int = 0, tool_call_count: int = 0, text_length: int = 0
    ) -> bool:
        """Detect if the agent is stalled (not making progress).

        A stall is when the agent has made very few events/tool calls
        and is producing minimal text — indicating it's stuck.

        Returns True if a stall is detected.
        """
        # Stall conditions: very few events AND few tool calls AND little text
        if event_count < 30 and tool_call_count < 3 and text_length < 200:
            return True
        # Also detect: many turns but no tool calls (pure text looping)
        if len(self._snapshots) >= 5 and tool_call_count == 0:
            return True
        return False

    @property
    def state(self) -> LoopState:
        return self._state

    @property
    def stop_reason(self) -> StopReason | None:
        return self._stop_reason
