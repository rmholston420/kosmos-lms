# ADR-111 — Tektos-Ultima native sessions + chat page

- **Status**: Ratified
- **Date**: 2026-09-24
- **Stage**: 9.3 (Tektos integration)
- **Supersedes**: nothing (complements ADR-109, ADR-110)
- **Related**: ADR-109 (API gateway), ADR-110 (native dashboard), ADR-101 (gateway soft-fail), ADR-091 (iframe bridge — stays at `/tektos-ultima/legacy/` until Stage 5)

## Context

Stages 9.1–9.2 replaced the iframe dashboard with a native subsystem-status
grid. The core value of the Tektos standalone (`:5556`) is its **IDE**:
create sessions, chat with the agent, watch the stream, fork/archive.
Without a native equivalent the iframe can never be retired.

This stage adds `ui/app/tektos-ultima/sessions/page.tsx` — a native
sessions + chat page that drives Tektos exclusively through the kernel
gateway (ADR-109), never hitting `:8020` directly.

## Decision

1. **Single page, two panes.** Left: session list (active / archived
   tabs), New-session form with model picker. Right: chat pane with the
   23-type protocol event stream (ADR: Tektos `protocol/envelope.py`)
   rendered as assistant messages with reasoning, tool calls, stop
   reason, and resource warnings.

2. **Transport.** REST for list/create/fork/archive/model-switch
   (`/api/tektos-ultima/gateway/api/sessions/...`); **SSE via
   `fetch` + `ReadableStream`** for `/api/prompt/sse` (OpenAI
   chat-completion chunk format terminated by `[DONE]`) so the request
   body (model, prompt) can be POSTed — `EventSource` is GET-only.

3. **History = replay + tab memory.** Tektos persists assistant turns as
   replay events (`assistant.reasoning/delta/completed`, …) but does
   **not** emit `user.*` events; user prompts are reconstructed from tab
   memory (same-session continuation only). Cross-tab history for user
   turns is a documented known limitation (Tektos-side gap, not a UI
   choice).

4. **Polling, not push, for the list.** The session list refreshes every
   10 s plus on every local mutation — Tektos has no WS list channel;
   this matches the standalone frontend's behaviour.

5. **Null-guards everywhere** (`Array.isArray`, `isObj`), per the panel
   hardening convention — a Tektos shape change degrades one pane, not
   the page.

## Consequences

- The kernel remains a pure proxy (ADR-109 unchanged); no new kernel code.
- One real upstream bug found and fixed in Tektos itself:
  `POST /api/sessions/{id}/archive` 500'd (`is_archived` is a derived
  read-only property; the endpoint also reset `status` to `created`,
  which would have un-archived). Fixed at the status level
  (tektos-ultima-v1 `3249060`).
- Test coverage: `ui/tests/21-tektos-ultima-sessions.spec.ts` — 3
  serial tests against the **live** kernel + live GPU LLM (no mocks):
  boot/empty-state, create→prompt→streamed `PONG`→render, and
  model-switch/fork/archive list deltas. Every session created is
  archived in `afterEach` so runs leak no state.

## Reversibility

High — delete the route directory and the spec; the gateway and
dashboard from 9.1/9.2 are untouched.
