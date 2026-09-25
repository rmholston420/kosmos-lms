# ADR-131: kernel-native Tektos session lifecycle (`/api/sessions*`)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.15 (endpoint split, sessions family)
- **Supersedes:** none

## Context

The sessions page (`ui/app/tektos-ultima/sessions/page.tsx`) proxied
`:8020/api/sessions*` — the *standalone* Tektos engine's SessionManager.
The kernel already had a referent: `registry.session`, booted under
`KOSMOS_SESSION=tektos` as `TektosSessionAdapter`
(`adapters/session/tektos/adapter.py`) — a fidelity port of the donor
SessionManager behind the ADR-103 SessionPort contract.

A *Tektos* session is deliberately NOT served by the generic inmemory
SessionPort adapter: that one is kernel FSM plumbing (created → ready →
running → …) with no model/title/cwd/root lineage. The Tektos adapter
carries `model`, `cwd`, `title`, `tag`, `root_session_id`, fork/resume
lineage, and per-session FSM history — the referent the sessions page
shows.

`KOSMOS_SESSION` was **not set** in `ops/systemd/kosmos-kernel.local.env`
before this stage, so `registry.session` was `None` at boot and the
adapter never wired.

## Decision

### D1 — boot gate: `KOSMOS_SESSION=tektos`
Added to `ops/systemd/kosmos-kernel.local.env`. Boot log now records
`kosmos.session: wired (ADR-103); adapter=tektos mirror=on`.

### D2 — lifecycle endpoints on the kernel (donor-faithful shapes)
Seven endpoints in `kernel/app.py`, speaking the ADR-103 SessionPort
contract so **any** installed SessionPort works (tests use the inmemory
adapter; production uses the Tektos adapter):

| Route | Shape (donor-faithful) |
|---|---|
| `GET /api/sessions[?archived=true]` | **raw JSON array** of session objects |
| `GET /api/sessions/{id}` | session object + ADR-103 superset `state`, `state_history` |
| `POST /api/sessions` | `{id, title, model, cwd, status}`; `model` required (422) |
| `PATCH /api/sessions/{id}` | rename — `{id, title, model, status, is_archived, tag}` |
| `POST /api/sessions/{id}/fork` | `{id, title, model, status, parent_title}` |
| `POST /api/sessions/{id}/archive` | `{ok: true}` |
| `POST /api/sessions/{id}/interrupt` | `{ok: true}` |

`DELETE /api/sessions/{id}` returns `{ok, events_deleted}`. All routes
are `503` (with the `KOSMOS_SESSION=tektos` hint) when the port is
offline, and `404` for unknown ids.

Fidelity notes (found during live verification):

- **Delete:** the vendor `delete_session` returns `0` for a session with
  no events (and `0` when unknown, instead of raising) — the first draft
  mapped `deleted <= 0` to 404 and therefore 404'd *successful* deletes.
  The endpoint now checks existence first (`get_session` is `None` →
  404) and otherwise returns the vendor count.
- **Interrupt:** the ADR-103 FSM only allows `RUNNING → INTERRUPTED`; a
  not-running session raises `InvalidTransitionError`. The donor's
  observable endpoint behavior for that case is a no-op `{ok: true}`, so
  the endpoint catches `InvalidTransitionError` and returns ok.
- **Fork title:** the vendor prefixes `fork of <title>` and the donor
  wraps it again (`Fork of fork of …`). The UI only reads `id` from the
  fork response, so the donor's observable string is preserved verbatim.

### D3 — sessions page re-point
`const KERNEL = ""` added; the six lifecycle `fetch()` calls
(list, create, interrupt, fork, archive) re-pointed to the kernel base.
The conversation endpoints (`/api/models`, `/replay`, `/prompt/sse`,
model-switch) stay on `GATEWAY` until **ADR-132**.

### D4 — log-ring noise: `neo4j`
64× `neo4j.notifications` Cypher-deprecation WARNINGs (one per query)
were flooding the 500-record `/api/logs` ring at boot. `"neo4j"` added
to `_KosmosLogRing._NOISE_PREFIXES`.

## Consequences

- The sessions page is fully kernel-native for the lifecycle: it lists,
  creates, renames, forks, archives, interrupts, and deletes sessions on
  `registry.session` — the Tektos adapter under `KOSMOS_SESSION=tektos`
  — not the standalone engine.
- The endpoints are port-agnostic (SessionPort contract); the referent
  is a boot-env decision, and a 503 + hint surfaces the missing gate.
- ADR-132 (conversation: models, prompt/sse, replay, model-switch) is
  the next slice; the page keeps the `GATEWAY` constant until then.
