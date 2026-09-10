# ADR-103 — SessionPort (24th formal port) + Tektos-Ultima fidelity port for Stage 8.1

**Status:** Ratified v25
**Lock-in phase:** Stage 8.1
**Supersedes:** —

## Context

Plan v2 (`docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md`) commits Stages 8.1–8.7 + Stage 13 to a **fidelity-port** integration of the Tektos-Ultima runtime under `adapters/<port>/tektos/vendor/` (donor verbatim under `vendor/`, façades + import boundaries rewritten). Q2=A locks fidelity over rewrite.

Stage 8.1's slice is the session lifecycle FSM — the substrate every downstream Tektos slice (8.2 turn loop, 8.3 reflection, 8.4 planner, 8.5 executor, 8.6 manager, 8.7 multi-agent) writes against. The donor code lives at:

- `src/tektos/state_machine.py` (235 lines) — `StateMachine` singleton, `State` enum (created/ready/running/interrupted/failed/idle), `Transition` frozen dataclass, `StateChange` dataclass, `VALID_TRANSITIONS` (7 transitions), `InvalidTransitionError`, `get_state_machine`/`reset_state_machine` module-level globals. Emits `session.state_change` events via `tektos.event_bus.get_event_bus().publish(event_type, session_id, payload)` — a 3-arg positional signature that predates ADR-023's envelope-first `EventBusPort`.
- `src/tektos/runtime/session.py` (494 lines) — `LiveSession` dataclass + async `SessionManager` (asyncio.Lock-protected). API: `create_session`, `get_session`, `list_sessions`, `add_ws_connection`, `remove_ws_connection`, `interrupt_session`, `complete_session`, `archive_session`, `fork_session`, `resume_session`, `rename_session`, `tag_session`, `delete_session`, `reap_failed_sessions`, `search_sessions`. Persists lifecycle events through `tektos.store.event_store.append_event(session_id, event_type, payload)` — an SQLite append-only event store (323 lines) with FTS that no Kosmos port covers.
- `src/tektos/runtime/session_state.py` (356 lines) — `SessionState` + `SessionStateManager` for `LAST_KNOWN_STATE.md` markdown persistence. Structured progress state, not FSM. **Out of Stage 8.1 scope** — deferred to a future stage adjacent to Hindsight/handoff work.

The donor emits every state transition to the event bus and every lifecycle change to the event store. Neither pathway maps 1:1 to a Kosmos port today:

- `tektos.event_bus.publish(event_type, session_id, payload)` violates ADR-023 (`EventBusPort` is envelope-first — `publish(EventEnvelope)` with `producer_plugin` non-empty).
- `tektos.store.event_store.append_event(...)` has no formal-port coverage (Stage 8.0 added `RelationalMemoryPort` for the R1 audit ledger + R2 episodic narratives, but the SQLite event store is a distinct, replay-oriented substrate that predates Kosmos).

Stage 8.1 must (a) introduce a **`SessionPort`** as the 24th formal port; (b) land a fidelity port of the donor FSM + session manager under `adapters/session/tektos/vendor/`; (c) rewrite the two import boundaries at the adapter façade only; (d) provide an in-memory adapter for CI parity; (e) wire the adapter into the kernel behind an env-gate mirroring Stage 8.0's ADR-101 degrade pattern.

## Decision

Ship Stage 8.1 as:

**D1 — Formal port `SessionPort` at `ports/session.py` (24th port).**

Protocol methods:

- `create_session(*, model, cwd, permission_mode="auto", resume_session_id=None, fork_session_id=None) -> LiveSession`
- `get_session(session_id) -> LiveSession | None`
- `list_sessions(*, archived=False) -> list[LiveSession]`
- `attach_client(session_id, client_id) -> bool` (port-neutral rename of donor `add_ws_connection`)
- `detach_client(session_id, client_id) -> None` (port-neutral rename of donor `remove_ws_connection`)
- `start_turn(session_id, *, reason="") -> StateTransition` (drives `ready → running`)
- `complete_turn(session_id, *, reason="") -> StateTransition` (drives `running → ready`)
- `fail_turn(session_id, *, reason="") -> StateTransition` (drives `running → failed`)
- `interrupt_turn(session_id, *, reason="") -> StateTransition` (drives `running → interrupted`)
- `archive_session(session_id) -> None`
- `fork_session(source_session_id, *, model, cwd=".") -> LiveSession`
- `resume_session(session_id) -> LiveSession`
- `rename_session(session_id, new_title) -> None`
- `tag_session(session_id, tag) -> None`
- `delete_session(session_id) -> int` (returns count of purged events)
- `reap_failed_sessions(*, timeout=300.0) -> int`
- `search_sessions(*, query, sort="updated_at", order="desc") -> list[LiveSession]`
- `get_state(session_id) -> SessionState` (returns FSM state, defaults CREATED)
- `get_history(session_id) -> list[StateTransition]`
- `get_allowed_transitions(current_state) -> tuple[SessionState, ...]`
- `is_healthy() -> bool` (sync, non-throwing, mirrors ADR-022 rule 3 + ADR-100 D1)
- `close() -> None` (async, idempotent)

Frozen slotted dataclasses:

- `LiveSession` — id (str), model (str), cwd (str), permission_mode (str), status (str), title (str), tag (str), root_session_id (str | None), created_at (float, monotonic), updated_at (float, monotonic), seq (int), attached_clients (frozenset[str]).
- `StateTransition` — session_id, from_state (str), to_state (str), reason (str), timestamp_iso (str, UTC ISO-8601), timestamp_mono (float).

Enum:

- `SessionState(str, Enum)` — CREATED, READY, RUNNING, INTERRUPTED, FAILED, IDLE, ARCHIVED. Renamed from donor `State` to avoid namespace collision with donor `session_state.SessionState` (which is out-of-scope for 8.1). Adds `ARCHIVED` as a first-class enum member (donor uses the raw string `"archived"` in `archive_session`).

Exception: `InvalidTransitionError`.

Transition table: the seven donor transitions plus four Kosmos delta transitions. Three of the deltas lift the donor's raw-string archival path into an explicit FSM edge; the fourth (`IDLE → READY`) fills a gap in the donor table where reattach after IDLE has no legal edge — the donor allows this in practice via `set_state`, but the transition table omits it, so an FSM-strict adapter would reject it. Kosmos takes the correct edge into the table:

```
CREATED     → READY               (donor)
READY       → RUNNING             (donor)
READY       → IDLE                (donor)
RUNNING     → READY               (donor)
RUNNING     → FAILED              (donor)
RUNNING     → INTERRUPTED         (donor)
INTERRUPTED → READY               (donor)
IDLE        → READY               (delta: client reattached to idle session)
READY       → ARCHIVED            (delta: replaces donor raw-string transition)
IDLE        → ARCHIVED            (delta)
INTERRUPTED → ARCHIVED            (delta)
```

**D2 — Two adapters, mirroring Stage 8.0 shape.**

- `adapters/session/inmemory/adapter.py` — port-clean `InMemorySessionAdapter`. asyncio.Lock-protected dict of sessions + per-session history list. No event-bus or memory-port coupling. Required for CI + dev; the adapter dependency Stage 8.2's turn loop can bind against without dragging in the tektos donor tree.
- `adapters/session/tektos/adapter.py` — `TektosSessionAdapter`, **fidelity port**. Copies donor `state_machine.py` verbatim to `adapters/session/tektos/vendor/state_machine.py` and donor `session.py` verbatim to `adapters/session/tektos/vendor/session.py`. Adapter façade rewrites two import boundaries:
  - Vendor `state_machine.py` `from tektos.event_bus import get_event_bus` → `from adapters.session.tektos.vendor_bindings import get_event_bus_shim`, where the shim wraps 3-arg positional calls into `EventEnvelope(producer_plugin="tektos.session", event_type=<name>, payload={"session_id": ..., **payload})` and delegates to an `EventBusPort` injected at adapter construction.
  - Vendor `session.py` `from tektos.store.event_store import append_event` → `from adapters.session.tektos.vendor_bindings import append_event_shim`, where the shim publishes the lifecycle envelope through the same injected `EventBusPort` (event-bus-only routing at Stage 8.1; the SQLite event store itself is deferred to Stage 13 per Plan v2). Vendor `delete_session`'s call to `store_delete(session_id)` is shimmed to return `0` at Stage 8.1 with an INFO log citing the deferral.
  - Vendor `session.py`'s `from tektos.state_machine import ...` is rewritten to point at the sibling vendored `adapters.session.tektos.vendor.state_machine`, so the two donor files stay a single self-consistent unit under `vendor/`.
- `TektosSessionAdapter` constructor accepts `event_bus: EventBusPort` (required) and `relational_memory: RelationalMemoryPort | None = None` (optional). When `relational_memory` is provided, **every** successful `StateTransition` is mirrored into the Stage 8.0 audit ledger via `record_event(kind="session.state_change", entity_id=session_id, payload={...}, provenance="tektos.session", confidence=1.0)` — Stage 8.0's first real downstream consumer. Failures in the mirror path degrade to a warning log; they do NOT roll back the FSM transition (the FSM is the source of truth, the ledger is derived audit).

**D3 — No `EventStorePort` at Stage 8.1.**

Session lifecycle events route through `EventBusPort` at Stage 8.1. The SQLite append-only event store donor (`src/tektos/store/event_store.py`, 323 lines with FTS) is deferred to Stage 13's "remaining donor subsystems" slot per Plan v2. Rationale: (a) `EventBusPort` already gives cross-process delivery via `read_recent` and (post-ADR-024) consumer groups; (b) adding a 25th port at Stage 8.1 over-scopes the FSM slice; (c) Stage 13's ADR can weigh a new `EventStorePort` against extending `RelationalMemoryPort` with a raw-event append path.

**D4 — Kernel wiring `kernel/app.py::_boot_session`.**

Env-gate `KOSMOS_SESSION={off,inmemory,tektos}` (default `off` silent). `tektos` branch requires the already-booted `registry.event_bus`; `RelationalMemoryPort` is optional (adapter uses whatever `registry.relational_memory` holds, `None` OK). Health-check failure → `registry.session=None` with warning log citing ADR-103 D4 (mirrors ADR-101 D3 and ADR-102 D6 patterns). Unknown env value → `RuntimeError` captured in `registry.errors["session"]` enumerating the allowed set. New `_BootRegistry.session: Any = None` slot. Boot order: `_boot_relational_memory` (Stage 8.0) → `_boot_session` (new) → `_boot_gnosis_seeder` (unchanged) → rest.

**D5 — TektosPlugin dataclass unchanged at Stage 8.1.**

The plugin descriptor + `TektosPlugin` dataclass at `plugins/tektos/plugin.py` stay untouched at 8.1. The session adapter is a kernel-wide capability held by `registry.session`; downstream Stage 8.2 code will thread it into `TektosPlugin` when the turn loop needs it, guarded by its own ADR. This preserves Stage 3.7's descriptor lock and honours ADR-063 (no implicit widening of plugin surfaces).

**D6 — Fidelity-port rule enforcement.**

Donor files under `adapters/session/tektos/vendor/` are copied verbatim from the tektos-ultima donor SHA that Plan v2 pins, then modified only as explicitly enumerated in D2. Every modification is enumerated in `PORTING_LEDGER.md`'s Stage 8.1 entry. If a donor idiosyncrasy violates a Kosmos invariant (e.g. the module-level singleton `get_state_machine()` interacting badly with per-adapter isolation), the fix lands as a documented modification in the ledger, not as a rewrite. The kill switch defined in Plan v2 remains: if a fidelity port collides with a Kosmos invariant that cannot be reconciled with a small modification, stop the slice, author a rejection ADR, and rewrite that specific module against the contract.

**D7 — `SessionState` naming.**

The port enum is `SessionState` (not donor `State`). The donor `src/tektos/runtime/session_state.py::SessionState` dataclass is out of Stage 8.1 scope; when a future stage lands that subsystem, it MUST rename to avoid the collision (e.g. `SessionSnapshot`). Recorded here so the rename cost is visible up-front.

**D8 — Test surface.**

- `adapters/session/inmemory/test_contract.py` — 25+ fast tests: full FSM path coverage (every valid transition + representative invalid transitions), thread-safety under `asyncio.gather` fan-out, `search_sessions` filter + sort, `reap_failed_sessions` timeout logic, `fork_session` root_id propagation, `resume_session` archive-required guard, `is_healthy` non-throwing after `close`, contract-level Protocol conformance via `isinstance(adapter, SessionPort)`.
- `adapters/session/tektos/test_contract.py` — 30+ fast tests: donor FSM invariants preserved (State enum members, VALID_TRANSITIONS shape, transition history ordering, invalid-attempt counter), event-envelope wrapping (every state change publishes an `EventEnvelope` with `producer_plugin="tektos.session"`, `event_type="session.state_change"`, and the donor's `from_state`/`to_state`/`reason` payload triple), event-bus routing of donor `append_event(...)` calls with correct event-type mapping (`session.created`, `session.ready`, `session.interrupted`, `session.failed`, `session.updated`), optional `RelationalMemoryPort` mirror path (mock adapter captures 1 `record_event` per state change, correct kind + provenance + confidence, transition succeeds even when mirror raises), `delete_session` returns 0 with INFO log at Stage 8.1 per D2 deferral, Protocol conformance.
- `tests/kernel/test_stage_8_1_session_wiring.py` — 6 fast tests: unset → `session=None`; `off` → same; `inmemory` → wired + healthy; `tektos` without event bus wired → error in `registry.errors["session"]`; `tektos` with event bus wired → `TektosSessionAdapter` constructed and healthy; unknown value → error enumerating allowed set.

**D9 — Deferrals recorded.**

- `EventStorePort` (25th port candidate) — deferred to Stage 13.
- Donor `session_state.py` (LAST_KNOWN_STATE.md persistence) — deferred to a future Hindsight-adjacent stage.
- `TektosPlugin` dataclass growth to carry `session_port` — deferred to Stage 8.2.
- Cross-process session-state broadcasting via `EventBusPort.read_recent` consumer groups — deferred to ADR-024 landing.
- `SessionState` naming collision resolution against donor `session_state.SessionState` — recorded here as a future-stage rename obligation.

## Rationale

**Fidelity over rewrite (Q2=A).** The donor `state_machine.py` documents PlexClaw bug fixes in its module docstring (bug #1 dead branch removed, bug #8 failed-session cleanup, bug #10 status-after-interrupt). Rewriting the FSM from scratch discards that debugging history. The fidelity-port shape preserves the invariants along with the code that encodes them.

**Rename `add_ws_connection` → `attach_client` at the port boundary.** The donor's WebSocket coupling belongs to the transport layer, not the FSM. The port must be transport-neutral so Stage 11's 154-endpoint split and the Kosmos-LMS microfrontend shell (ADR-091) can attach different client types (WebSocket, SSE, HTTP long-poll, in-process test harness) without a port amendment. The vendor code inside `adapters/session/tektos/vendor/session.py` keeps its `add_ws_connection` name; the adapter façade exposes `attach_client` and dispatches internally.

**No `EventStorePort` at 8.1.** Adding a 25th formal port for the SQLite event store at Stage 8.1 would over-scope the slice, and it would pre-empt Stage 13's design authority. `EventBusPort` already covers the lifecycle-event fan-out need; the SQLite store adds replay + FTS but nothing Stage 8.1's downstream consumers (turn loop, planner, executor) require.

**Optional `RelationalMemoryPort` mirror.** Stage 8.0 landed the audit ledger with no downstream consumer. Wiring the session FSM as the first consumer both (a) validates Stage 8.0's real-world shape end-to-end and (b) gives the operator a full replay of every session state change through `RelationalMemoryPort.query_events`. Making the mirror optional keeps the adapter usable in test/dev where postgres is not wired.

**Two adapters at 8.1.** The in-memory adapter unblocks Stage 8.2's turn-loop tests without pulling the entire tektos donor tree into the fast-tier surface. The tektos adapter is the production path.

**Kernel does not auto-migrate any donor state.** Consistent with ADR-063 (no implicit schema changes). Session adapters build fresh state on boot; persistence is `RelationalMemoryPort` (opt-in) and Stage 13's event store (future).

## Rejects

- **Extending `EventBusPort` to accept 3-arg positional `publish`.** Violates ADR-023 envelope-first rule. The wrapping shim inside the tektos adapter is a strictly local concern, not a port amendment.
- **Rewriting the FSM against a fresh contract.** Discards donor bug-fix history; violates Q2=A.
- **Reusing `MemoryPort` for lifecycle events.** `MemoryPort` is the graph/temporal substrate; session lifecycle is a distinct pub-sub concern. Cross-cutting into `MemoryPort` would blur ADR-008's zero-trust write contract with high-frequency lifecycle churn.
- **New `EventStorePort` at Stage 8.1.** Over-scopes the slice; deferred to Stage 13.
- **Growing `TektosPlugin` dataclass at 8.1.** Stage 3.7 lock (ADR-036 §Q4=B trigger) stays until Stage 8.2 has a concrete `session_port` consumer.
- **Keeping donor `add_ws_connection` / `remove_ws_connection` names on the port.** Transport-coupled naming leaks WebSocket assumptions into a transport-neutral contract.
- **Making `RelationalMemoryPort` mirror mandatory.** Would force every session-adapter user to also wire postgres, breaking the CI-required in-memory path.

## Consequences

### Files added

- `ports/session.py` (~300 lines — Protocol + `SessionState` enum + 2 frozen dataclasses + `InvalidTransitionError` + `VALID_TRANSITIONS` tuple + `is_valid_transition` helper)
- `adapters/session/__init__.py` — exports both adapters (tektos import gated)
- `adapters/session/inmemory/__init__.py` + `adapter.py` + `test_contract.py`
- `adapters/session/tektos/__init__.py` + `adapter.py` + `vendor_bindings.py` + `test_contract.py`
- `adapters/session/tektos/vendor/__init__.py` + `state_machine.py` (donor verbatim) + `session.py` (donor verbatim except three enumerated import rewrites)
- `tests/kernel/test_stage_8_1_session_wiring.py` (~180 lines, 6 tests)

### Files modified

- `kernel/app.py` — new `_BootRegistry.session: Any = None` slot + new `_boot_session()` method + boot-order insertion after `_boot_relational_memory`
- `PORTING_LEDGER.md` — new Stage 8.1 section (2 vendored files from tektos-ultima donor)
- `docs/Kosmos-Build-Spec-v26.md` — §4.1 Ports table gets `SessionPort` row; §17 ADR table gets ADR-103 row
- `docs/Kosmos-Build-Sequence-v26.md` — Stage 8.1 stanza appended
- `docs/adrs/README.md` — ADR-103 index row appended
- `BUILD_LOG.md` — Stage 8.1 landing entry appended

### Downstream ADRs unlocked

- Stage 8.2 (turn-loop absorption) can now bind `TektosTurnLoop` to `registry.session`.
- Stage 8.3–8.7 (reflection, planner, executor, manager, multi-agent) all consume `registry.session` state transitions as their coordination substrate.
- Stage 13's `EventStorePort` ADR can now be authored with the SessionPort shape as a concrete downstream consumer.

### Invariants preserved

- ADR-007 (events-only cross-plugin coupling): new adapter subpackages under `adapters/session/`; no cross-plugin imports.
- ADR-008 (zero-trust memory writes): optional `RelationalMemoryPort` mirror path supplies `provenance="tektos.session"` + `confidence=1.0` at every write.
- ADR-022 (health-check non-throwing rule): `is_healthy()` returns bool without raising.
- ADR-023 (event-bus envelope-first): every donor 3-arg positional publish is wrapped into a proper `EventEnvelope` at the shim boundary.
- ADR-063 (no implicit schema changes on boot): kernel does not auto-migrate; adapters start empty.
- ADR-100 / ADR-101 / ADR-102 degrade pattern: unhealthy adapter → `registry.session=None` with warning log.

## Lock-in phase

Stage 8.1.

## References

- Plan v2: `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md` (fidelity-port rule; Stages 8.1–8.7 sequence)
- ADR-023 (EventBusPort envelope-first MVP)
- ADR-063 (no implicit schema changes on boot)
- ADR-091 (microfrontend shell integration — reverse proxy at :5556)
- ADR-092 (Tektos runtime absorption scope)
- ADR-100 (DozerDbLexicalIndex — health-check pattern donor)
- ADR-101 (Stage 7.4+2 kernel-boot lexical wiring — degrade-pattern donor)
- ADR-102 (RelationalMemoryPort — mirror-target port, also degrade-pattern donor)
- Donor: `tektos-ultima/src/tektos/state_machine.py` + `tektos-ultima/src/tektos/runtime/session.py`
