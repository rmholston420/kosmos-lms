# ADR-137: kernel-native ops Database tab (data-layer status)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.21 (endpoint split, database family)
- **Supersedes:** none

## Context

The ops DB tab (Stage 9.4, ADR-112) proxied 7 calls to the standalone
Tektos engine's `:8020` API through the kernel gateway (ADR-109 D1):
`GET /api/db`, `/api/db/backups`, `/api/db/schema`, `/api/db/analyze`
+ `POST /api/db/backup`, `/api/db/optimize`, `/api/db/restore`. All
manage the standalone engine's **own SQLite file** (`data/tektos.db`,
via `DatabaseManager`): table counts, journal mode, FK state, schema
dump, integrity checks, and file-level backup/optimize/restore.

Recon findings:

1. **No kernel referent exists.** The kernel has zero `/api/db*`
   endpoints and no single "the database" — the kernel's persistence is
   *several separate systemd-managed stores*, each behind a boot
   registry lane: **Postgres** (relational memory), **DozerDB/Neo4j**
   (MemoryEvent graph, ADR-135 substrate), **Qdrant** (vector),
   **Valkey** (event bus).
2. **Keeping the proxy contradicts Stage 11's endgame.** These
   endpoints die with `main.py` deletion (the plan's exit gate) — a
   tab that keeps proxying :8020 cannot be part of the finished split.
3. The donor's controls (backup/optimize/restore, backups list,
   schema, analyze) have no kernel referent of any kind — they are
   SQLite-file operations.

## Decision

**Minimal data-layer status** (user decision, 2026-09-25):

- **New kernel-native `GET /api/db`** in `kernel/app.py`. Reports
  **only what `/health` already knows**: for each of the four
  persistence lanes, whether it booted (`registry` slot is non-None)
  plus its paired boot error from `registry.errors`. Envelope:
  `{status: "initialized", healthy: bool, stores: [{store, wired,
  boot_error, management}], note, timestamp}`.
- **No probes, no counts.** Per-store liveness/counts are ops-level
  (systemd service health, store CLI), not card-level — probing four
  infra services from a UI-poll endpoint (15 s interval) would put
  infra load in the hot path and blur the ops/kernel boundary.
- **Always 200.** A degraded lane is data, not an error.
- **Donor SQLite controls removed — not disabled** (ADR-135/136
  convention): no kernel referent exists for them, so a disabled
  button would be dead UI. The tab carries an honest note: retired
  with `main.py` deletion; the stores are systemd-managed
  infrastructure and their backups are ops-level.

Rejected alternatives:

- *Full "data layer status" with per-store probes + counts* — rejected
  by the user: probe/counts are ops-level, not card-level.
- *Keep proxying :8020 as "standalone infrastructure"* (the ADR-134
  Hindsight-daemon precedent) — rejected: unlike the Hindsight daemon
  (a live service that outlives `main.py`), `tektos.db` **dies with
  `main.py`**; there is nothing to proxy to at the exit gate.

## Consequences

- Ops page is now **5/7 kernel-native** (db, memory, skills, tools,
  logs); remaining gateway tabs: telemetry, self-repair + the
  page-level `/health` upstream probe (its own family).
- Store *management* (backup/restore/integrity) has an honest
  referent named in the UI note: systemd-managed infra, ops-level.
  If a kernel-native backup primitive is ever wanted, it is a new
  ADR — it must not silently re-enter as a card-level control.
- The endpoint is pure registry-read: trivially GPU-free testable
  (ASGITransport + lane patches, ADR-135/133/134 endpoint pattern).

## Slices

- **B2** — `GET /api/db` in `kernel/app.py` (`94f459a`)
- **B3** — endpoint tests, 3/3 (`94f459a`)
- **B4** — ops DbTab reframe + `next build` + live verify (`ccf7f04`)
- **B5** — full regression + docs (this commit)
