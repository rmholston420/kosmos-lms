# ADR-140: 11.7 WebSockets deferred to the Stage 14.5 main.py deletion gate

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.7 (endpoint split, WebSockets) — DEFERRED
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
