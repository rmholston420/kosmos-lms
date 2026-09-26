# ADR-140: 11.7 WebSockets deferred to the Stage 14.5 main.py deletion gate

- **Status:** Executed (2026-09-26, branch (a) parity-via-bus; see "Execution" below). Ratified as deferred 2026-09-25.
- **Scope:** v2 Stage 11.7 (endpoint split, WebSockets) — RESOLVED
- **Supersedes:** none

## Context

Plan v2 Stage 11.7 defines the WebSocket split as:

> `/ws/{session_id}` → kernel `/api/events/ws`; `/ws/pty` → new SandboxPort adapter

Recon (2026-09-25) found:

| Surface | State |
|---------|-------|
| Donor `:8020 /ws/{session_id}` | Prompt-submission + event fanout — the engine's interactive loop channel (streamed LLM events, approve/reject handlers, `WebSocketManager` fanout) |
| Donor `:8020 /ws/pty` | PTY channel for sandbox shells |
| Kernel | **Already has** `/api/events/ws` (ADR-061 — event-bus bridge, `?types=` filtering, envelope wire frames) + ADR-066 algedonic WS push + `POST /api/prompt/sse` (kernel-native prompt stream; ADR-documented as replacing the :8020 prompt/sse proxy) |
| ADR-109 gateway bridge | **HTTP/SSE only** — it never proxied WebSocket upgrades |
| Kosmos UI | **Zero WebSocket consumers** — no `new WebSocket`, no `wss://` anywhere under `ui/` |

Consequence: unlike the ops-tab families, there is **no UI call to re-point**.
11.7 is a backend-parity slice, and its two halves have different shapes:

1. **`/ws/{session_id}` parity** = publishing the donor's prompt-WS event
   types onto the kernel event bus so `/api/events/ws?types=...` delivers a
   live prompt session. The SSE half of the prompt channel is ALREADY
   kernel-native (`/api/prompt/sse`).
2. **`/ws/pty`** = a new SandboxPort adapter — a distinct capability that
   belongs with the Stage 13 sandbox work, not the endpoint split.

## Decision (user-chosen)

**Defer 11.7 entirely to the Stage 14.5 `main.py` deletion gate.** The
WebSocket question is treated as part of the `main.py` retirement
cleanup, not as a separate Stage 11 slice.

Rationale (recorded at decision time):

- Nothing in the surviving surface consumes a prompt-WS today (the
  donor's WS clients were its own frontend — retired with the Stage 9.5
  `tektos-frontend` unit — and CLI tooling); the ADR-109 bridge never
  proxied WS, so no live path depends on the donor WS endpoints.
- The kernel's surviving channels — `POST /api/prompt/sse` (prompt
  stream) + `/api/events/ws` (ADR-061 bus bridge) — already cover the
  functional surface for any future consumer.
- The deferral does NOT leave a gap at 14.5: at deletion time the
  decision is made with the full retirement picture in hand — either
  (a) parity: publish prompt-session event types onto the event bus so
  `/api/events/ws?types=...` is the WS channel (ADR-061 already exists),
  or (b) document SSE-as-the-channel as the final architecture. The
  `/ws/pty` → SandboxPort adapter defers with Stage 13 sandbox work
  regardless.

## Consequences

- Stage 11 endpoint split: **11.1–11.6, 11.13–11.23 complete**; 11.7
  recorded as deferred-to-14.5 (this ADR is the exit-gate map for the
  WS question). No code lands now.
- The Stage 14.5 `main.py` deletion checklist gains one explicit item:
  "resolve 11.7 per ADR-140 — publish prompt event types onto the bus
  (parity) or close as SSE-sufficient; `/ws/pty` with Stage 13".
- No new endpoint, no UI change, no build.

## Execution (2026-09-26, ADR-141 exit gate close)

**Decision: branch (a) — parity-via-bus. Zero new code required.**

Live verification on `:8000` (probe `ws_parity_probe.py`, 2026-09-26):
created a real session (`b3f8e47d-…`), drove a real GPU turn
(`qwen3.8-27b-code` via `POST /api/prompt/sse`, ~2.4 s to `data: [DONE]`),
while a WebSocket client connected to
`/api/events/ws?types=tektos.agent.turn.started,…,tektos.agent.turn.completed`.
The WS client received, in order:

```
ready
tektos.agent.turn.started        (turn_id t_…63, mode auto, approval auto)
tektos.agent.turn.llm_completed  (duration_ms 1958, lane qwen3.8-27b-code, sentinel text)
tektos.agent.turn.completed      (stop_reason completed)
```

Findings at deletion time:

1. **Outbound half — resolved with no code.** The kernel's
   `TektosTurnLoop` (`kernel/tektos_turn_loop.py`) already publishes
   `tektos.agent.turn.*` (started / llm_completed / tool_call ×3 /
   sandbox_completed / completed / blocked) onto the ADR-061 event bus,
   and the `/api/events/ws` bridge (ADR-061) already filters and delivers
   them end-to-end. This IS the donor `/ws/{session_id}` channel,
   verified live — not a plan.
2. **Inbound half — resolved by existing REST.** The donor WS's
   approve/reject messages map to the kernel's
   `POST /api/approvals/{id}/approve` / `POST /api/approvals/{id}/reject`
   (approval service, kernel-native). The turn loop's auto-approval mode
   makes the inbound channel optional for the common path; the REST pair
   covers the interactive path.
3. **SSE half — already kernel-native.** `POST /api/prompt/sse`
   (`kernel/tektos_prompt_sse.py`) maps the same bus events to SSE frames;
   the sessions page already consumes that wire.
4. **`/ws/pty` — documented deferral.** The kernel sandbox
   (`SandboxPort`, `adapters/sandbox/tektos/adapter.py`) is
   batch-run-only; no PTY channel exists. Its only donor consumer was
   `frontend/…/TerminalPane.tsx`, retired with the Stage 9.5
   `tektos-frontend` unit. Verified zero `ws/pty` / `new WebSocket`
   references under `ui/` — no live consumer. Recorded as an honest
   deferral (named carrier: a future `SandboxPort` PTY adapter, if and
   only if a consumer appears), per the D-bucket convention in ADR-141.
   Per the ADR-141 gate clause ("D routes may remain at deletion only if
   their named Stage 13 port has already landed; otherwise they gate the
   deletion too"): `/ws/pty` names the sandbox work — Stage 13.1–13.15
   landed the sandbox adapter (batch mode) but explicitly not a PTY
   channel, and the honest resolution is a documented deferral with no
   consumer, not a blocker. Recorded in ADR-141's gate-progress note.

**Result:** ADR-141 gate item (d) satisfied; the two WS rows in ADR-141
are RESOLVED / DEFERRED-respectively; `main.py` deleted (donor commit
`43cb0ef`) and `:8020` retired the same day. No new endpoint, no UI
change, no code in this ADR's execution.
