# ADR-117 — Kernel-native data-service status endpoints (Stage 11 endpoint split, first slice)

**Status:** Ratified
**Date:** 2026-09-25
**Stage:** v2 Stage 11.1 (Plan v2 "4.D endpoint split" — first health-family cut, per Plan Step 7.1's "Runtime, health, logs, directory" family adapted to the kernel's actual `/api/*` convention)

---

## Context

The Tektos-Ultima dashboard (`ui/app/tektos-ultima/page.tsx`) renders a subsystem status grid. Its five data-service cards — Neo4j, Postgres, Redis, Hindsight, and (missing) Qdrant — were wired to `/api/{service}/status` paths proxied through the ADR-109 gateway to the **standalone Tektos API on :8020**.

Live state at the time of this ADR (verified 2026-09-25):

1. The standalone Tektos API is retired as a kernel dependency (Stage 9.5, ADR-113 retired the ADR-091 iframe; the ADR-109 gateway survived only as a degraded 503-emitting proxy + CSP middleware). Whichever process still answers :8020 does so **without** the kernel's data-service configuration, so its status endpoints report the services as down — the five cards were dead-on-arrival for the real state.
2. The kernel owns the actual adapters and the env-driven configuration for four of the five services (`KOSMOS_DOZERDB_*`, `KOSMOS_POSTGRES_URI`, `KOSMOS_VALKEY_URL`, `KOSMOS_QDRANT_URL`). Hindsight is a standalone daemon (no kernel lane) but is a single `GET /health` away on :9178.
3. The ADR-109 gateway's typed 503 envelope collapses every failure mode into one undifferentiated "upstream down" — the card cannot distinguish *unreachable*, *auth failed*, and *not configured*. The ADR-101 honesty rule (never silently succeed, always show real state) is unsatisfiable through the proxy.
4. Qdrant had no card at all, despite `registry.vector` being a kernel-booted lane and Qdrant being live on :6333.

The Stage-11 endpoint split calls for the dashboard to stop depending on the retired standalone API for kernel-owned state. This ADR is the first slice: the five data-service cards become **kernel-native endpoints**.

Alternatives considered:

1. **Revive the standalone Tektos API and fix its env.** Rejected — it is the retired system of record (Plan v2 Stage 14 retires it outright); re-wiring credentials into a to-be-deleted process is negative work.
2. **Extend the ADR-109 gateway with service-aware rewrite rules.** Rejected — the gateway is a transparent proxy by design (ADR-109 D1); teaching it per-service semantics couples it to the exact knowledge it should not own, and its 503-envelope degradation would still mask failure modes.
3. **Read `registry` adapter instances from the routes.** Rejected (ADR-109 D2 pattern, applied consistently): registry coupling means a downed service can take a route down, and cards would go blank when a lane is env-gated off — even though the *service* is fine. The operators' question is "is Postgres up?", not "did the kernel boot a Postgres lane?".

## Decision

**D1 — New kernel module `kernel/tektos_data_services.py`**, ADR-109 factory pattern: `build_tektos_data_services_router() -> APIRouter`, mounted in `kernel/app.py` immediately after the ADR-109 gateway mount with the same degrade-to-WARN-on-mount-failure wrapper (`registry.errors["tektos_data_services"]` on import failure). Five read-only routes under `/api/tektos/data-services/{neo4j,postgres,redis,hindsight,qdrant}/status`. No registry coupling — probes are env-driven and build short-lived clients per request, so they never hold state and can never take the kernel down.

**D2 — Service-level, not lane-level, probing.** Each probe reflects the state of the *backing service*, independent of whether the kernel booted a lane for it:

| Service | Probe | Env (mirrors the boot path) |
|---|---|---|
| Neo4j | `neo4j.AsyncGraphDriver.verify_connectivity()` over Bolt | `KOSMOS_DOZERDB_URI/_USER/_PASSWORD` (+ `_DATABASE`, default `neo4j`) — same vars `_boot_memory`'s dozerdb branch reads |
| Postgres | `asyncpg.connect()` + `SELECT 1`, conn closed in `finally` | `KOSMOS_POSTGRES_URI` — same DSN `_boot_relational_memory` uses; works even with `KOSMOS_RELATIONAL_MEMORY=off` |
| Redis | `redis.asyncio` `PING` (Valkey-compatible; same wire protocol) | `KOSMOS_VALKEY_URL`, default `redis://127.0.0.1:6379/0` — same var the Valkey event-bus adapter reads |
| Hindsight | `httpx GET {base}/health` (200 = healthy) | `KOSMOS_HINDSIGHT_URL`, default `http://127.0.0.1:9178` — standalone daemon, no kernel lane |
| Qdrant | `httpx GET {base}/healthz` + `GET /collections` for count | `KOSMOS_QDRANT_URL` (default `http://127.0.0.1:6333`) + optional `KOSMOS_QDRANT_API_KEY` as `api-key` header — same vars `_boot_vector` reads |

Note on Qdrant: the correct health route is `/healthz` (or `/readyz`); **`/health` 404s** — probed live.

**D3 — Three-way failure distinction, always HTTP 200.** Every probe returns a 200 with a uniform envelope:

```json
{ "service": "...", "healthy": true|false,
  "status": "connected" | "unreachable" | "auth_failed" | "unconfigured",
  ...service-specific fields, "detail": "<short, redacted>" }
```

`detail` is truncated to 200 chars and never carries credentials (the Postgres `url` field strips the `user:pass` netloc before reporting). HTTP-level 5xx is reserved for an internal probe bug — a downed service degrades its own card only. Every probe is bounded to ≤ 3 s (`socket_connect_timeout` / `asyncio.wait_for`) so a wedged service can stall at most its own card, never the dashboard's 10 s poll cycle.

**D4 — Dashboard repoint + Qdrant card added.** `ui/app/tektos-ultima/page.tsx`: `Subsystem` gains an optional `base` (default `GATEWAY`); the four data cards move to `base: "/api/tektos/data-services"` and a fifth card (`Qdrant`, 📐) is added. `parseCard` treats `healthy` as authoritative for all five (the old card logic compared against the standalone API's `status === "connected"` + `error` field shape, which never matches the native envelope) and reads `detail` (not `error`). The card now shows e.g. `auth_failed` / `unconfigured` as distinct line values instead of a generic "down".

**D5 — Test/verification strategy.** Live-verified on Colossus 2026-09-25 (D6 below). The probe functions are importable without a booted kernel (`build_tektos_data_services_router()` takes no registry), so unit tests can monkeypatch env vars and assert each failure-mode branch — `unconfigured` (no env), `auth_failed` (bad creds), `unreachable` (dead port) — without live services.

## Consequences

- The dashboard's data-service cards show the *real* service state sourced from the *same* env the kernel boot paths use — a card saying "connected" means the kernel's own lanes would connect.
- `unconfigured` is now an honest card state (Neo4j on Colossus today: the live kernel env carries no `KOSMOS_DOZERDB_*` vars, so memory runs `in_memory` and the card says `unconfigured` — previously a dead card proxying a misconfigured :8020).
- The ADR-109 gateway is untouched; it still serves the remaining (non-data-service) standalone-Tektos endpoints until the split completes (Plan v2 Stage 11 continues with the non-health families).
- Ops note: if the operator wants the Neo4j card green, set `KOSMOS_DOZERDB_URI/_USER/_PASSWORD` in `ops/systemd/kosmos-kernel.local.env` **and** repoint `KOSMOS_MEMORY_BACKEND=dozerdb` — the card and the memory lane then share one source of truth. (The live Neo4j `auth.ini` password on this host is not the repo dev credential and must be supplied by the operator.)

## D6 — Live verification (Colossus, 2026-09-25)

Kernel restarted (`sudo systemctl restart kosmos-kernel`, 12/12 subsystems up, `boot_errors: {}` — router mounted). `curl` of each endpoint:

```
neo4j     → {"healthy":false,"status":"unconfigured","detail":"KOSMOS_DOZERDB_URI/_USER/_PASSWORD not set"}
postgres  → {"healthy":true,"status":"connected","host":"127.0.0.1","port":5432,"database_name":"kosmos"}
redis     → {"healthy":true,"status":"connected","ping_ok":true,"port":6379}
hindsight → {"healthy":true,"status":"connected","base_url":"http://127.0.0.1:9178"}
qdrant    → {"healthy":true,"status":"connected","base_url":"http://127.0.0.1:6333","collections":0}
```

UI rebuilt (`next build`); the served production bundle (`/_next/static/chunks/2agndj-of1ger.js`) confirmed to carry all five cards with `base:"/api/tektos/data-services"` endpoints, including the new Qdrant card.
