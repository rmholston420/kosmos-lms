# ADR-109 — Tektos-Ultima API Gateway (Stage 9.1)

**Status:** Ratified v25
**Lock-in phase:** Tektos integration Stage 9.1
**Supersedes:** —

## Context

The user's standing goal is to fully integrate Tektos (`~/dev/tektos-ultima-v1`) into kosmos-lms (`~/dev/kosmos-lms`). Scope was confirmed in-session (2026-09-24):

1. **Stage 9.1 (this ADR)** — native kernel API gateway: kernel-side proxy from `/api/tektos-ultima/gateway/*` to the standalone Tektos API (`TEKTOS_ULTIMA_API_URL`, default `http://127.0.0.1:8020`).
2. Stages 9.2–9.4 — native kosmos pages (`/tektos-ultima/*`) replace the ADR-091 iframe proxy, driving the Tektos API exclusively through this gateway.
3. Stage 9.5 — parity verification against `:5556`; retire iframe proxy + `KosmosIframeCSPMiddleware`.
4. The standalone Tektos process keeps running until Stage 9.5 parity is proven (user decision, 2026-09-24); engine porting is a later, separate phase.

Relevant existing state:

- ADR-091 (Stage 2) mounted `kernel/tektos_ultima_bridge.py`: the `/tektos-ultima` page is an iframe to the standalone frontend (`:5556`) with an API-redirect proxy and CSP middleware. That surface stays until Stage 9.5.
- The standalone Tektos API exposes **145 routes** (`/openapi.json` verified live on 2026-09-24), including `POST /api/prompt/sse` (`text/event-stream`) used for live prompt streaming, plus sessions, memory, skills, tools, telemetry, DB, thermal, immune, and self-repair surfaces.
- ADR-101 requires boot-time degrade for optional adapters; ADR-092 forbids event-shape breaks; ADR-007 forbids cross-plugin imports. The gateway is a kernel component, so it couples to no plugin.
- `TEKTOS_ULTIMA_API_URL` already exists as the bridge's upstream env var (default `http://127.0.0.1:8020`); the gateway reuses the same variable so one knob controls both surfaces.

Options considered:

1. **Bake Tektos routes into the kernel app as native endpoints.** Rejected — 145 routes would fork the Tektos codebase into the kernel; every upstream change would need a kernel mirror; violates the single-source-of-truth invariant behind ADR-092.
2. **Browser calls :8020 directly (CORS).** Rejected — the standalone API has no CORS config, the browser would need the upstream URL at build time, and Collosus port changes would require a UI rebuild. The kernel must own the upstream base URL.
3. **Extending the ADR-091 bridge router with gateway routes.** Rejected — the bridge router is registry-coupled (mounted with `registry`) and its job is iframe lifecycle; mixing a live proxy in would blur the Stage 9.5 retirement boundary.
4. **CHOSEN — dedicated `kernel/tektos_ultima_gateway.py` module** with `build_tektos_ultima_gateway_router()`, mounted in `kernel/app.py` next to the bridge, no registry coupling, per-request typed 503/502 degrade.

## Decision

### D1 — Route shape

Gateway prefix `/api/tektos-ultima/gateway`. Two routes:

- `GET /api/tektos-ultima/gateway/health` — upstream reachability probe returning `{upstream, reachable, status_code, body?}`; 503 + typed envelope when the Tektos API is down. Registered before the catch-all so it wins for `/health`.
- `{GET,POST,PUT,PATCH,DELETE} /api/tektos-ultima/gateway/{upstream_path:path}` — transparent proxy: a request to `…/gateway/api/sessions` proxies to `{base}/api/sessions`. Status code, body, and content-type pass through unmodified.

### D2 — No registry coupling; per-request degrade

The gateway is a pure proxy: it never touches `registry`, so it can mount unconditionally and never appears in boot `registry.errors`. Upstream failure produces a typed envelope per request:

- connect/resolve/DNS failure → `503 {"error": "tektos_ultima_unavailable", "detail": …, "upstream": …}`
- unexpected proxy fault → `502 {"error": "tektos_ultima_proxy_error", "detail": …}`

The kernel itself stays 200 on `/health` and every other endpoint (ADR-101 spirit, request-scoped instead of boot-scoped).

### D3 — Header / body / query hygiene

Hop-by-hop headers (`host`, `content-length`, `accept-encoding`, `connection`) are stripped before forwarding; request body bytes and query params pass through verbatim. Responses use `starlette Response` (not `JSONResponse`) so non-JSON upstream bodies (HTML, octet-stream) are not corrupted.

### D4 — SSE lifecycle

When the upstream response is `text/event-stream`, the gateway streams it chunk-by-chunk (`httpx` `client.send(req, stream=True)` → `StreamingResponse(aiter_bytes())`) with `Cache-Control: no-cache` + `X-Accel-Buffering: no`. The `httpx.AsyncClient` is deliberately **not** in an `async with` block on the SSE path: the forward generator owns it and closes both response and client in its `finally`, so a browser disconnect tears down the upstream request. On a mid-stream upstream drop the generator emits one terminal `event: proxy_error` frame so clients can render a clean error.

### D5 — Env var

`TEKTOS_ULTIMA_API_URL` (same variable as the ADR-091 bridge; default `http://127.0.0.1:8020`), read per-request so tests and Collosus port changes need no kernel restart.

### D6 — Tests

`tests/kernel/test_stage_9_1_tektos_ultima_gateway.py` — contract tests against a **real** fake upstream (FastAPI + uvicorn on a random 127.0.0.1 port), not mocks: health reachable/unavailable, GET+POST passthrough (body, query, media type), status-code passthrough (404), SSE passthrough (3 frames), upstream-down 503 envelope. Live verification against the real Tektos API on :8020 (`/health`, `/api/health`) additionally performed in-session.

### D7 — Explicit deferrals

- Native pages (Stages 9.2–9.4), iframe retirement (Stage 9.5), engine porting (later phase), and any kernel-side Tektos session ownership all remain out of scope for this ADR.
- No new formal port: the gateway is a kernel transport concern, and the Tektos API is an opaque upstream until engine porting happens.

## Consequences

- `/tektos-ultima` native pages get a stable same-origin API surface (`/api/tektos-ultima/gateway/*`) with one upstream knob and typed outage envelopes — Stages 9.2–9.4 build on it.
- The ADR-091 iframe bridge and the gateway coexist until Stage 9.5; the bridge is the retirement target.
- One extra hop for all Tektos traffic; acceptable on loopback (negligible latency) and buys build-time independence from upstream port changes.

## STATUS AMENDMENT (2026-09-26, ADR-144 / Stage 14.1)

**Module DELETED.** `kernel/tektos_ultima_gateway.py` and its D6 contract test
are removed (`git rm`). Every consumer that this ADR served (dashboard cards,
sessions, ops, panels) was re-pointed to kernel-native endpoints by
Stages 11.1–11.23 + ADR-141 Stage 13.x + `646174a`, so the proxy carried no
surviving traffic. The `KosmosCSPMiddleware` (ADR-089 `frame-ancestors
'self'` hardening) that ADR-113 D3 had placed in this module was extracted
**byte-identical to `kernel/csp.py` first**, and survives kernel-wide.
`/api/tektos-ultima/gateway/*` now 404s. This ADR's D1–D6 describe the
bridge's historical contract; ADR-144 records the deletion. The `TEKTOS_ULTIMA_API_URL`
env var stays defined for the :8020 backend's own lifetime (systemd unit)
until the main.py deletion step retires :8020.
