# ADR-088 — Loop-safety read-only tool-call budget interlock

**Status:** Ratified
**Locked:** ADR-145 (2026-09-26) — Stage 14 program freeze; this ADR is locked (see ADR-145).
**Lock-in phase:** Stage 3.13
**Amends:** ADR-080 (LoopSafetyPort — this ADR ratifies the read-only-budget clause inside the port)

## Context

Project knowledge concept `read-only-tool-budget` documents a mechanism observed in Tektos-Ultima: caps read-only tool calls per turn to force text-only completion. Without this cap, a coding agent can enter a pathological read-only loop (grep → grep → grep, or read → read → read) that consumes tokens without producing agent progress and cannot terminate through the existing token/turn caps because each individual call is small.

Tektos-Ultima's implementation is inline. In kosmos-lms it must be enforced at the port layer (per `LoopSafetyPort` per ADR-080) so no adapter or plugin can bypass it.

## Decision

`LoopSafetyPort.record_tool_call(handle, read_only: bool)` is the interlock mechanism:

1. `LoopCaps.read_only_budget` (default: 10 per turn, matches spec §25.7) is the per-turn cap.
2. Each `record_tool_call(read_only=True)` decrements the remaining budget.
3. When `budget_remaining == 0`, the next `record_tool_call(read_only=True)` returns `status="budget_exhausted"` and publishes envelope `loop_safety.read_only_budget_exhausted` on `EventBusPort`.
4. The Tektos runtime, on receiving `status="budget_exhausted"`, MUST complete the current turn with text only (no further tool calls of any kind).
5. Non-read-only tool calls (writes, executions) do NOT consume the budget.
6. The budget resets at `begin_turn()`; no cross-turn carryover.

### Read-only classification (guidance)

A tool call is read-only iff it does not mutate any state (filesystem, database, network target, kernel port). Examples:

| Tool | Read-only? |
|---|---|
| `grep` / `rg` | yes |
| `read` / `cat` | yes |
| `ls` | yes |
| `git log` / `git diff` (no commit) | yes |
| `write` / `edit` | no |
| `bash` (arbitrary) | no (conservative — bash may mutate) |
| MCP resource fetch | yes |
| MCP tool call with side effects | no |

The tool registry (Stage 4.7) is responsible for tagging each tool's `read_only` attribute; `LoopSafetyPort` is not the classifier.

### Non-bypass rule

The interlock is enforced at `LoopSafetyPort`; the Tektos runtime cannot silently override it. Any override MUST be a formal Kosmos ADR (there is currently no override).

## Rationale

- **Port-layer enforcement over runtime-inline check**: makes the interlock observable to Phrouros anomaly detection and Praxis governance.
- **Default 10** matches Tektos-Ultima's observed value; tunable per turn via `LoopCaps.read_only_budget` for adapters that want a different cap (e.g. a research plugin might want 50).
- **`read_only` as caller-declared** rather than inferred: keeps the port free of tool-classification logic; the tool registry owns that.
- **Forced text-only completion** on exhaustion rather than aborting the turn: preserves whatever partial progress the agent has made.
- **Rejected: enforce the interlock in the Tektos runtime only.** Non-Tektos plugins might spawn agentic subroutines (Zetesis inner loop for example); enforcing at the port layer covers all of them uniformly.

## Consequences

- Files edited (this ADR): `ports/loop_safety.py` docstring for `record_tool_call` documents the interlock behaviour. Value object `LoopCaps.read_only_budget: int = 10` and `LoopSafetyState.status` literal `"budget_exhausted"` land as part of ADR-080's Protocol surface.
- Files planned (Stage 3.13): `adapters/loop_safety/tektos/adapter.py` implements the interlock; contract test asserts that the 11th read-only call in a turn returns `budget_exhausted` and publishes the envelope.
- Files planned (Stage 4.7): tool registry annotates each tool with `read_only: bool`; Tektos runtime propagates the flag to `LoopSafetyPort.record_tool_call`.
- Spec §25.6 mirrors this ADR verbatim.

## Lock-in phase

Locked at Stage 3.13.

## References

- ADR-080 (LoopSafetyPort — this amends its record_tool_call contract)
- ADR-023 (EventBusPort envelope-first MVP)
- Project knowledge concept `read-only-tool-budget`
- ADR-077, ADR-078 (v26 §25.6)
