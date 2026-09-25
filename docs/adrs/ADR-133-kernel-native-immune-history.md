# ADR-133: kernel-native immune history endpoints (`/api/immune/*`)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.17 (endpoint split, immune history family)
- **Supersedes:** none

## Context

The panels page ImmuneTab (`ui/app/tektos-ultima/panels/page.tsx`) proxied
five immune endpoints to the *standalone* Tektos engine (`:8020`):
`GET /api/immune/{detectors,threats,responses,memory,memory/entries}`.
The standalone `main.py` reads its in-memory `ImmuneSystem`
(threat/response stores, memory counts) directly — the kernel has no such
in-memory stores.

The kernel already has a live immune referent: `registry.immune`
(`TektosImmuneAdapter`, Stage 9.1, `KOSMOS_IMMUNE=on`, verified healthy in
`/health`). ADR-122 (Stage 11.6) already landed `GET /api/immune/health`
on it — detectors are read directly via `list_detectors()`. What ADR-122
deliberately left out: **threat/response history** — the adapter is
scan-on-request with no persistent ledger, so `active_threats: 0` was
the honest value there.

But ADR-079 rule 1 makes every immune scan publish
`immune.verdict.{allow|warn|block}` envelopes to the event bus, and
blocks additionally write `MemoryPort` entries. So the kernel-native
referent for *history* is the bus — read `immune.verdict.*` envelopes
off `registry.event_bus` and map them to the donor wire shapes. This is
the exact ADR-132 slice F pattern (bus-derived replay).

## Decision

Five kernel-native `GET` endpoints in `kernel/app.py`, donor wire shapes
(the panels tab is drop-in compatible — no parse/render change):

- **D1 (slice I2a, `1c1afea`)** — `kernel/tektos_immune.py` mapper module
  (~196 lines): `_read_verdicts()` (per-type `read_recent` off the bus,
  merged + `_entry_sort_key` ms-seq numeric sort — Valkey entry IDs are
  `ms-seq`, lexicographic sort breaks at digit-count boundaries, same
  fix as ADR-132 slice F); `_verdict_row()` (envelope → donor row:
  `timestamp/decision/reason/hit_count/source_plugin/kind/hits/detector/
  severity/description`); `get_detectors()` (live `list_detectors()`,
  element `{name,type,severity_ceiling,description,enabled}`);
  `get_threats()` (block/warn envelopes; `?resolved=true` includes allow);
  `get_responses()` (all verdicts, newest-first, `count`-capped);
  `get_memory_summary()` (`{total_threats_observed, active_threats
  (block/warn), resolved_threats (allow), uptime_hours}`);
  `get_memory_entries()` (`{response_history}`).
- **D2 (slices I2b+I2c, `a7fccb7`)** — endpoints on the kernel:
  `/api/immune/detectors`, `/api/immune/threats[?resolved=]`,
  `/api/immune/responses[?count=]`, `/api/immune/memory`,
  `/api/immune/memory/entries`. Degrade: `registry.immune` None → 503 on
  detectors; `registry.event_bus` None → 503 on the four bus-derived
  routes; `list_detectors()` raising → empty list + `error` field, never
  500.
- **D3 (slice I3, `b5feefa`)** — panels `g()` helper re-point: the five
  immune calls pass `base: ""` (kernel-native, same pattern as ADR-129/130);
  page header doc updated (immune now kernel-native alongside logs and
  directory). **Uptime bug fix found in live verification:** first draft
  computed kernel boot wall-time as
  `datetime.fromtimestamp(time.monotonic() - _KERNEL_BOOT_TS)` — but
  `time.monotonic()` is *not* epoch-based, so the result was a bogus
  epoch-scale value (~84 years uptime). Fixed to
  `datetime.now(timezone.utc) - timedelta(seconds=uptime)`; test gains an
  upper-bound assertion (`0 ≤ uptime_hours < 1.0` for an in-process
  kernel) that would have caught it.

## Honest limits

- History depth = bus retention: `read_recent` per verdict type
  (Valkey XREAD-style tail). A verdict published *after* the endpoint's
  retention window is gone — same limitation as ADR-132 slice F replay.
- `active_threats` counts block/warn verdicts within the retention window;
  there is no "threat cleared" lifecycle event in the kernel bus today, so
  "active" = "recently observed".
- Detectors are the 12 vendored donor detectors wrapped by the Stage 9.1
  adapter (live-verified count on Collosus).

## Verification

- 17/17 tests: mapper module 11 (`test_stage_11_17_adr_133_immune_mapper.py`
  — fake `read_recent` bus + fake immune adapter: verdict merge/sort,
  threat active-vs-resolved partition, responses newest-first + cap, memory
  summary math, entries passthrough, raising `list_detectors` degrade) and
  endpoints 6 (`test_stage_11_17_adr_133_immune_endpoint.py` — real kernel
  app, `FakeImmune` on `registry.immune`, `FakeBus` on `registry.event_bus`:
  shape per route, resolved partition, 503 offline × 2). GPU-free.
- Full `tests/kernel` + `plugins/tektos` regression green.
- `next build` green; live on restarted kernel (:8000, real Valkey bus):
  detectors `count:12` (prompt_injection … body_protection), responses and
  entries show real `tektos_runtime` allow verdicts
  (`tektos.agent.prompt`, "no detectors fired"), threats empty (honest —
  no block/warn in window), memory `total:2 active:0 resolved:2,
  uptime_hours ≈ 0.004` (sane, post-fix).

## Consequences

- Panels ImmuneTab no longer touches the `:8020` gateway; remaining
  GATEWAY refs on panels belong to later Stage 11 families.
- Commit chain: I2a `1c1afea` → I2b+I2c `a7fccb7` → I3 `b5feefa` →
  docs (this ADR + README row + BUILD_LOG 11.17).
