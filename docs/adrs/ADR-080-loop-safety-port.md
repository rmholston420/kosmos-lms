# ADR-080 — LoopSafetyPort (new formal port)

**Status:** Ratified
**Lock-in phase:** Stage 3.13
**Supersedes:** —

## Context

Tektos-Ultima runs an autonomous coding agent whose iteration loop can pathologically expand: turn count grows, token spend grows, wall time grows. Tektos-Ultima expresses loop safety as inline runtime checks with three tiers of caps (`max_turns=15`, `max_tokens_total=65 536`, `max_wall_time_seconds=300`) plus a repetition detector (`repetition_window=3`).

In kosmos-lms, loop-safety decisions must be observable to other plugins (Phrouros for anomaly, Praxis for governance) and enforceable at the port layer so no adapter or plugin can bypass them. ADR-088 further requires a read-only tool-call budget interlock that forces text-only completion when exhausted.

## Decision

Introduce **`LoopSafetyPort`** as the 17th formal Kosmos port at `ports/loop_safety.py`.

### Protocol surface

```python
@runtime_checkable
class LoopSafetyPort(Protocol):
    async def begin_turn(self, agent_id: str, config: LoopCaps | None = None) -> TurnHandle: ...
    async def record_tokens(self, handle: TurnHandle, tokens: int) -> LoopSafetyState: ...
    async def record_tool_call(self, handle: TurnHandle, *, read_only: bool) -> LoopSafetyState: ...
    async def check_repetition(self, handle: TurnHandle, action_hash: str) -> LoopSafetyState: ...
    async def end_turn(self, handle: TurnHandle) -> TurnSummary: ...
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...
```

Value objects (frozen dataclasses):

- `LoopCaps{max_turns: int = 15, max_tokens_total: int = 65_536, max_wall_time_seconds: int = 300, repetition_window: int = 3, read_only_budget: int = 10}` (per §25.7).
- `TurnHandle{turn_id: str, agent_id: str, started_at: datetime}` (opaque handle).
- `LoopSafetyState{status: Literal["ok","warn","exhausted","repetition","budget_exhausted"], detail: str, budget_remaining: int}`.
- `TurnSummary{turn_id: str, ended_at: datetime, tokens_total: int, tool_calls: int, read_only_calls: int, terminal_status: str}`.

### Enforcement rules

1. Every state transition (`ok → warn → exhausted`) MUST publish an envelope on `EventBusPort` under `loop_safety.<status>` with the `TurnHandle.turn_id` as correlation id.
2. Every terminal state (`exhausted`, `repetition`, `budget_exhausted`) MUST also write a `MemoryPort` event with `provenance="loop_safety"` and `confidence=1.0` per §25.4.
3. `record_tool_call(read_only=True)` decrements the read-only budget. When `budget_remaining == 0`, the next `record_tool_call(read_only=True)` returns `status="budget_exhausted"` per ADR-088. Non-read-only tool calls do not consume the budget.
4. The budget resets at `begin_turn()`; no cross-turn carryover.
5. `check_repetition()` returns `status="repetition"` when the same `action_hash` recurs within `repetition_window` consecutive calls.

## Rationale

- **Formal port over inline runtime check**: makes loop-safety verdicts observable and forbids adapters from silently raising caps.
- **`TurnHandle` opaque type over integer turn number**: decouples callers from the adapter's internal counter, allows adapters to serialize state to disk for post-mortem replay.
- **Read-only budget inside the same port** (rather than a separate `ReadOnlyBudgetPort`): shares the turn handle and simplifies the callable surface — one port to inject into the Tektos runtime instead of two.
- **Rejected: fold into `ResourcePort`.** ResourcePort deals with the APEX substrate (time/money/attention/compute/knowledge/energy) and is System-3 control. Loop safety is per-turn agent-runtime bookkeeping and is System-2 coordination. Different life-cycles, different granularity.

## Consequences

- Files created (this ADR): `ports/loop_safety.py`; `tests/ports/test_loop_safety_protocol.py`.
- Files planned (Stage 3.13): `adapters/loop_safety/tektos/adapter.py`, `adapters/loop_safety/tektos/test_contract.py`.
- Kernel boot order (§25.5) places `loop_safety` second (after `immune`), so downstream ports can subscribe to `loop_safety.*` at their own boot.
- ADR-088 (read-only-budget interlock) references this ADR for the enforcement mechanism.

## Lock-in phase

Locked at Stage 3.13.

## References

- ADR-077 (integration cut), ADR-078 (v26 §25.6, §25.7)
- ADR-088 (loop-safety read-only budget interlock)
- ADR-023 (`EventBusPort` envelope-first MVP)
- ADR-027 (`MemoryPort` zero-trust write contract)
