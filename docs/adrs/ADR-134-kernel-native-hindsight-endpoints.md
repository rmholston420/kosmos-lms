# ADR-134: kernel-native Hindsight endpoints (`/api/hindsight/*`)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.18 (endpoint split, hindsight family)
- **Supersedes:** none

## Context

The panels HindsightTab (`ui/app/tektos-ultima/panels/page.tsx`) proxied
two endpoints to the *standalone* Tektos engine (`:8020`):
`GET /api/hindsight/status` and `GET /api/hindsight/experiences`. The
standalone engine holds an in-process `HindsightClient`
(`src/tektos/memory/hindsight_client.py`) that talks to the Hindsight
daemon — but the daemon itself (default `http://127.0.0.1:9178`,
`KOSMOS_HINDSIGHT_URL`) is **standalone infrastructure with a v1 REST
API**: it is not a kernel lane (no `registry.hindsight`), and it does not
know whether the kernel or the standalone engine is its client.

The kernel already probes the daemon:
`kernel/tektos_data_services.py::_probe_hindsight` (ADR-117 data-services,
pure `GET /health` against `KOSMOS_HINDSIGHT_URL`, always-200 degrade
contract). What was missing: the *recall* leg — the daemon's
`POST /v1/{profile}/banks/{bank_id}/memories/recall` had no kernel
route, so experiences had to go through the standalone engine.

## Decision

Two kernel-native `GET` endpoints, donor wire shapes (the HindsightTab
is drop-in compatible — no parse/render change):

- **H2a (slice H2a, `9d68492`)** — `kernel/tektos_hindsight.py` (~84
  lines): config helpers (`_base_url()` = `KOSMOS_HINDSIGHT_URL` default
  `:9178`; `_profile()` / `_bank_id()` env-overridable, default
  `default`); `_recall()` — the daemon's v1 recall POST with donor
  fidelity: no `limit` in the request body (v1 `RecallRequest` has none;
  the client slices), empty/whitespace query → neutral sentinel
  `"tektos"` (v1 rejects empty queries with 422); `get_experiences()` —
  the donor's tag-preferring order (items whose `tags` include
  `context` first, remainder fills, truncated to `limit`).
- **H2b (slice H2b, `9d68492`)** — endpoints in `kernel/app.py`:
  `/api/hindsight/status` reuses the ADR-117 `_probe_hindsight()` and
  adds the donor's identity fields (`bank_id`, `profile`); always 200
  (`status: unreachable` when the daemon is down — same degrade
  contract as the probe). `/api/hindsight/experiences[?context=&limit=]`
  returns the donor's raw list; `limit` clamped 1–100; `ConnectError` →
  503 "daemon unreachable" (the donor's `not_initialized` degrade);
  other HTTP errors → 500 with detail.
- **H3 (slice H3, `768ef06`)** — panels `g()` re-point: the two
  hindsight calls pass `base: ""` (kernel-native, same pattern as
  ADR-129/130/133); page header doc updated (hindsight now
  kernel-native alongside logs, directory, immune).

## Honest limits

- The donor also exposed `POST /api/hindsight/{retain,recall,reflect}` —
  write/action endpoints. The panels tab is GET-only (the page mutates
  nothing), so the kernel split lands the read paths only; retain/
  reflect stay on the standalone engine until a kernel consumer needs
  them (the module's `_recall` is reusable for that).
- Hindsight daemon reachability is probed per-request (2 s timeout on
  status, 5 s on recall) — no cached health, matching the ADR-117 probe.
- Profile/bank identity is env-configured (`KOSMOS_HINDSIGHT_PROFILE` /
  `KOSMOS_HINDSIGHT_BANK`, default `default`) — the standalone engine's
  donor defaults.

## Verification

- 7/7 tests (`test_stage_11_18_adr_134_hindsight.py` — fake
  `httpx.AsyncClient` injected by monkeypatch: recall URL/bank/profile
  + empty-query sentinel; tag-preferring order; limit truncation; status
  donor shape incl. identity fields; experiences raw list + context
  forwarding; 503 when the daemon is down — GPU-free).
- Full `tests/kernel` + `plugins/tektos` regression green (only known
  Colossus-only interactive skips).
- `next build` green; live on restarted kernel (:8000, real Hindsight
  daemon :9178): status `{service: hindsight, status: connected,
  healthy: true, base_url: :9178, bank_id: default, profile: default}`;
  experiences `[]` — the bank is genuinely empty (honest, not
  fabricated).

## Consequences

- HindsightTab no longer touches the `:8020` gateway; remaining
  GATEWAY refs on panels belong to later Stage 11 families.
- Commit chain: H2a+H2b+H2c `9d68492` → H3 `768ef06` → docs (this ADR +
  README row + BUILD_LOG 11.18).
