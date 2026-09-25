# ADR-132: Kernel-native Tektos conversation endpoints (models, model-switch, replay, prompt/SSE)

**Status:** Ratified (2026-09-25)
**Scope:** v2 Stage 11.16 (Endpoint Split, conversation family)
**Supersedes:** the `:8020` proxies for the four remaining conversation endpoints on the sessions page.

## Context

After ADR-131 (Stage 11.15) moved the session *lifecycle* (list/create/get/rename/fork/archive/interrupt/delete) to kernel endpoints, the sessions page (`ui/app/tektos-ultima/sessions/page.tsx`) still proxied four conversation endpoints to the **standalone** Tektos backend on `:8020` via `kernel/tektos_ultima_gateway.py`:

1. `GET /api/models` — the model picker.
2. `POST /api/sessions/{id}/model` — mid-session model switch.
3. `GET /api/sessions/{id}/replay` — full conversation replay.
4. `POST /api/prompt/sse` — the live streaming prompt (SSE).

The standalone service is the retirement target of the Endpoint Split: the kernel must serve every sessions-page call natively (same origin), probing the kernel's own adapters/config rather than a second process.

### LLM topology (fixed in `c2728e6`, user-corrected 2026-09-25)

The model picker and the SSE stream must reflect the **kernel's** LLM lanes, not the standalone engine's:

- **Primary (GPU):** llama.cpp `:8090` — `qwen3.8-27b-code`.
- **Fallback (CPU):** llama.cpp `:8092` — `granite4.1-8b-instruct`, used **only when `:8090` is down** (FailoverLLMAdapter ordering).
- **Vision:** llama.cpp `:8094` — Qwen3-VL.
- **Embedder (CPU):** llama.cpp `:8091` — qwen3-embedding-0.6b.
- **Ollama `:11434`:** retired from the Tektos/kernel LLM path (still a system service).

## Decision

Four slices, each committed independently (donor wire shapes preserved so the UI needs minimal re-pointing):

### Slice D — `GET /api/models` (commit `d198346`)

Kernel-native model list built **from the kernel's ADR-116 LLM config** (`registry.llm` FailoverLLMAdapter lane order + the dedicated vision lane), not by shelling out to `:8020`. Returns the donor shape `[{id, role, endpoint, …}]` so the picker and the SSE `model` field stay consistent with the kernel's actual routing.

### Slice E — `POST /api/sessions/{id}/model` (commit `8112673`)

Mid-session model switch, three layers:

- **vendor:** `switch_model()` on the vendor session manager — mutates `session.model` and appends a `session.updated {changes: {model, from}}` event so the switch is visible in replay.
- **adapter:** `TektosSessionAdapter.set_session_model()` pass-through (model lineage lives on the Tektos referent, not the generic ADR-103 SessionPort — same pattern as the ADR-131 `get_state`/`get_history` introspection).
- **endpoint:** returns donor shape `{ok, model, old_model}`; 404 unknown session, 422 missing/invalid `model`, 503 offline or non-Tektos port.

UI model-switch fetch re-pointed `GATEWAY` → `KERNEL`.

### Slice F — `GET /api/sessions/{id}/replay` (commits `60357c2` chain)

Full conversation replay. The kernel has no per-session event store, so the endpoint reads the known Tektos event types off the **event bus** (`registry.event_bus.read_recent`), filters to the session, and maps `tektos.agent.turn.*` → the donor chat-event types in `kernel/tektos_replay.py` (164-line mapper + `_entry_sort_key`). Donor shape: `[{seq, type, payload, protocol_version, created_at}]` oldest first.

Recon fidelity fixes:

- **Valkey entry IDs are `ms-seq`** — lexicographic sort breaks at digit-count boundaries; `_entry_sort_key` parses to `tuple[int, int]`.
- **`session.ready` is WS-only** — the vendor `create_session` publishes only `session.created`; `session.ready` fires from `add_ws_connection`. The mapper does not expect `session.ready` in the HTTP replay path.

UI replay fetch re-pointed `GATEWAY` → `KERNEL`.

### Slice G — `POST /api/prompt/sse` (commit `3df98a6`)

The live streaming prompt. New standalone module `kernel/tektos_prompt_sse.py` (~294 lines) keeps `kernel/app.py` lean:

- `stream_prompt_sse(session_id, prompt, bus, turn_loop, llm) -> AsyncIterator[str]`.
- **Fan-in pattern:** one task per subscribed event type → a single `fanin_queue` → one consumer (EventBusPort.subscribe is per-type).
- Calls `turn_loop.run_turn()` in a task; maps events → **OpenAI `chat.completion.chunk` frames** (donor wire format):
  `data: {"id":"chatcmpl-<session[:8]>","object":"chat.completion.chunk","created":…,"model":"…","choices":[{"index":0,"delta":{…},"finish_reason":null}]}`.
- Terminal: `finish_reason:"stop"` chunk, then the unquoted OpenAI sentinel `data: [DONE]\n\n` (donor parity — emitted as a raw string, NOT JSON-encoded).
- `finally`: cancel fan-in tasks, unsubscribe per type, cancel the turn task.
- Endpoint (before `/api/sessions/{id}/fork`): body `{session_id, prompt, images?}`; 404 when `registry.tektos_turn_loop` is None; `StreamingResponse(..., media_type="text/event-stream")` — the first StreamingResponse in the kernel.

**Gap 2 fix (turn-loop boot).** `registry.thermal` and `registry.loop_safety` were **never declared** in `_BootRegistry`; the Tektos plugin carries neither; Stage 8.2 wiring tests masked the gap by injecting stubs. `_boot_tektos_turn_loop` therefore always degraded to `None`. Fixed inline in the boot function:

- `thermal` → fall back to `registry.thermal_watchdog` (the kernel's own watchdog, already alive; the turn loop's only `ThermalPort` call is `pressure()`, which it exposes). Note: `thermal_watchdog` ≠ `thermal` — two different objects bridged by the fallback.
- `loop_safety` → construct `TektosLoopSafetyAdapter(event_bus=registry.event_bus)` inline (all deps optional; surface needed: `begin_turn`, `check_repetition`, `record_tool_call`, `end_turn`).

`KOSMOS_TEKTOS_TURN_LOOP=on` added to `ops/systemd/kosmos-kernel.local.env` (gitignored; value not documented here).

**`/health` ghost (lesson, not a bug).** `/health`'s `subsystems` dict does **not** include a `tektos_turn_loop` key — `.get("tektos_turn_loop")` returns `None` for a *missing* key, which mimics a degrade. The turn loop actually boots fine; the correct verification is a live SSE POST, not the health endpoint.

UI re-point: `${GATEWAY}/api/prompt/sse` → `${KERNEL}/api/prompt/sse`; the `GATEWAY` constant removed from the page entirely — **zero gateway references remain on the sessions page** (all 9 calls kernel-native).

## Tests

- Slice D: `tests/kernel/test_stage_11_16_adr_132_models.py` — 7 tests (4-lane shape, role/endpoint invariants, FailoverLLMAdapter ordering).
- Slice E: `tests/kernel/test_stage_11_16_adr_132_model_switch.py` — 8 tests (switch shape + `session.updated` append + 404/422/503 paths).
- Slice F: `test_stage_11_16_adr_132_replay_mapper.py` (8) + `test_stage_11_16_adr_132_replay_endpoint.py` (7) — `ms-seq` sort, event-type mapping, WS-only `session.ready` exclusion.
- Slice G: `test_stage_11_16_adr_132_prompt_sse.py` (12 — module level, FanOutBus + FakeTurnLoop) + `test_stage_11_16_adr_132_prompt_sse_endpoint.py` (4 — endpoint level, FanOutBus + ScriptedLoop, `_ClosableClient` stream reader). Both parse the unquoted `[DONE]` sentinel (`_has_done` / `(frames, done)` tuple).

Full `tests/kernel` + `plugins/tektos` regression green (~910 tests, known Colossus-only interactive skips). `tsc` + `next build` green.

## Verification (live)

Kernel restarted with `KOSMOS_TEKTOS_TURN_LOOP=on`:

- `POST /api/sessions` → session created.
- `POST /api/prompt/sse` → **200 OK**, real `chat.completion.chunk` frames with `model: qwen3.8-27b-code`, content deltas, `finish_reason:"stop"`, terminated by `data: [DONE]`.

End-to-end SSE works on the kernel with the real GPU llama-server.

## Consequences

- The sessions page is now **100% kernel-native**; `kernel/tektos_ultima_gateway.py` has **zero** conversation endpoints (it retains only the remaining data-service families until their own slices).
- The SSE path is the kernel's first `StreamingResponse`; future streaming endpoints should follow the `tektos_prompt_sse.py` fan-in module pattern (generator + per-type unsubscribe + turn-task cancellation in `finally`).
- `_BootRegistry` still does not *declare* `thermal`/`loop_safety` slots — the Gap 2 fix bridges inside `_boot_tektos_turn_loop`. A future ADR should promote them to declared registry slots if a second consumer appears (YAGNI today).
- Ollama stays out of the kernel LLM path; `/api/models` reflects the four llama.cpp lanes.

## Amendment log

- 2026-09-25: Ratified. Slices D (`d198346`), E (`8112673`), F (`60357c2`), G (`3df98a6`) landed. `[DONE]` sentinel parity added in G follow-up.
