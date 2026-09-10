# Kosmos-LMS Session Handoff — 2026-09-10 01:35 EDT

## Current build-sequencing position

- **Stage / phase:** Stage 2 complete → Stage 3 next
- **Plugin / kernel component:** Kosmos shell microfrontend integration (ADR-089 + ADR-091). Kernel now hosts `/tektos-ultima/frontend/*` reverse proxy, `POST /api/tektos-ultima/bridge`, and global `frame-ancestors 'self'` CSP.
- **Port(s) in progress:** none. Six new port skeletons from Stage 1 (`Immune`, `LoopSafety`, `Thermal`, `Sandbox`, `Voice`, `Vision`) remain awaiting adapter implementation (Stage 3.13 / 4.7 / 6.5 per `Kosmos-Build-Sequence-v26.md`).

## Completed this session (Stage 2)

- Stage 2.1 — **ADR-091** Ratified: `/tektos-ultima` shell route (preserves `/tektos` ADR-065 approval list); kernel Starlette reverse proxy at `/tektos-ultima/frontend/*`; `POST /api/tektos-ultima/bridge` with server-side `tektos.*` namespace enforcement (ADR-086); client-side handler validates `event.source === iframe.contentWindow` AND `event.origin === window.location.origin`; CSP `frame-ancestors 'self'`.
- Stage 2.2 — `kernel/tektos_ultima_bridge.py` streaming reverse proxy: hop-by-hop stripping (both directions), `X-Forwarded-*` injection, bounded `httpx` timeouts, `502 tektos_ultima_upstream_unreachable` diagnostic on `ConnectError`.
- Stage 2.3 — `ui/app/tektos-ultima/page.tsx`: single-panel client component with `DEFAULT_IFRAME_SANDBOX` (`allow-same-origin allow-scripts allow-forms`), `iframeRef` handed to `<TektosUltimaBridge />`.
- Stage 2.4 — `ui/components/TektosUltimaBridge.tsx`: 3-check origin policy (source/origin/`tektos.*` prefix), fire-and-forget `POST /api/tektos-ultima/bridge`, `credentials: "omit"`.
- Stage 2.5 — `POST /api/tektos-ultima/bridge`: `_validate_bridge_envelope` returns `202 Accepted { event_id }` or `400`/`503`/`502`; forces `payload.source="tektos-ultima"`; `EventEnvelope(producer_plugin="tektos_ultima_bridge")` per ADR-023 rule 2.
- Stage 2.6 — `KosmosIframeCSPMiddleware`: pure ASGI (streaming-safe), merges `frame-ancestors 'self'` into every HTTP response without buffering.
- Stage 2.7 — `ui/tests/20-tektos-ultima-shell.spec.ts`: 6 chromium tests (page renders + iframe attrs; proxy 502 diagnostic; bridge 202 on valid `tektos.*`; bridge 400 on `thermal.red` forgery; bridge 400 on missing kind; CSP header on `/`).
- Stage 2.8 — `.github/workflows/ci.yml`: new `frontend-e2e` job (Playwright chromium against booted kernel + built UI); summary job updated. **Refreshed stale `ui/package-lock.json`** (was blocking every `npm ci` job silently).

## Verification captured this session

- 53/53 port protocol conformance tests still green (`pytest tests/ports/ -q`).
- `mypy kernel/tektos_ultima_bridge.py` — no issues.
- `scripts/check_plugin_isolation.py` — baseline clean (ADR-007 not violated).
- `npx next build` — `/tektos-ultima` appears in prerendered route table alongside `/tektos`.
- In-memory FastAPI TestClient round-trip: bridge 202 valid / 400 thermal / 400 missing / 503 no-bus / proxy 502 upstream-absent / CSP header present on unrelated route.

## Remaining before current Definition of Done (Stage 2)

- Commit + push (this session's final action). Nothing else pending.

## Open questions / awaiting user answer

- none

## Exact next action

Pull Stage 2 to Collosus:

```bash
cd ~/dev/kosmos-lms
git pull origin main
```

Then, at the top of Stage 3, run:

```bash
pytest tests/ports/ -q                       # confirm 53 port tests still green
python scripts/check_plugin_isolation.py     # confirm ADR-007 baseline
(cd ui && npm ci && npx next build)          # confirm lockfile + build clean
```

## Stage 3 preview (next session focus)

Stage 3 begins the Tektos-Ultima **runtime absorption**:

1. Port `tektos/orchestrator` upstream into `plugins/tektos/runtime/` (event loop, turn boundary, LLM-tool call cycle) per `PORTING_LEDGER.md` "Tektos runtime core" entry. Bound by the six ports ratified in Stage 1: `LoopSafetyPort` gates turns, `ImmunePort` gates tool calls, `ThermalPort` throttles inference, `SandboxPort` runs shell/exec.
2. Land `adapters/immune/tektos/` (Stage 3.13), `adapters/loop_safety/tektos/` (Stage 3.13), `adapters/thermal/tektos/` (Stage 3.13) — first concrete adapters for the Stage 1 ports.
3. Once the Tektos-Ultima Next 15.4 frontend is dropped into `plugins/tektos/frontend/`, verify the ADR-091 proxy chain end-to-end against the real upstream (Playwright test #2 will flip from 502-assertion to 200-assertion by injecting `KOSMOS_TEKTOS_ULTIMA_UPSTREAM` at the workflow env).
4. Do NOT touch `/tektos` ADR-065 approval list — it stays reachable during any Tektos-Ultima runtime outage per ADR-091 rationale.
