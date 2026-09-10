# ADR-091 — Microfrontend Shell Integration (Tektos-Ultima)

**Status:** Ratified
**Lock-in phase:** Stage 2 (microfrontend shell)
**Supersedes:** —

## Context

ADR-089 ratified `FrontendContractPort.PanelKind.IFRAME` as the mechanism by
which absorbed applications land inside the Kosmos shell without being
re-implemented in the shell's Next.js codebase. Stage 2 lands the first
concrete use of that contract: the Tektos-Ultima frontend (the autonomous
coding-agent UI absorbed from `rmholston420/tektos-ultima` per ADR-077).

Three shape questions remained open after ADR-089:

1. **Route naming.** The existing `/tektos` route (`ui/app/tektos/page.tsx`)
   is the ADR-065 Tektos change-approval list — a distinct workload that must
   remain reachable, particularly during LLM outages (per ADR-065 Option B).
   Reusing `/tektos` for the absorbed autonomous-agent UI would displace it.

2. **Reverse-proxy topology.** The Kosmos UI is `output: "export"`, so
   Next.js `rewrites` in `next.config.js` are inert — there is no Node
   runtime in production to proxy through. The `Kosmos-Build-Spec-v26.md`
   §25.7 reserved-ports table pins the Tektos-Ultima frontend at `:5556`.
   The only entity able to serve the iframe over a same-origin path is the
   FastAPI kernel that already mounts `/tektos-ui`, `/gnosis-gate`, and the
   Kosmos static export at `/`.

3. **Bridge topology.** The postMessage bridge must (a) validate
   `event.origin` against the same-origin Kosmos base URL, (b) forward
   envelopes to `EventBusPort` server-side, and (c) enforce the ADR-086
   `tektos.*` namespace ceiling for bridge-originated envelopes.

## Decision

1. **Route naming.** Absorbed Tektos-Ultima UI lands at **`/tektos-ultima`**
   in the Kosmos shell. The existing `/tektos` (ADR-065 approval list)
   is preserved unchanged.
2. **Reverse proxy.** The FastAPI kernel exposes the microfrontend at
   `/tektos-ultima/frontend/*` via a Starlette streaming proxy adapter
   (Stage 2 uses an in-repo `httpx.AsyncClient`; a hardened adapter behind
   `ReverseProxyPort` is deferred to Stage 3.13 alongside sandbox / thermal
   adapters). The proxy target is configurable via
   `KOSMOS_TEKTOS_ULTIMA_UPSTREAM` (default `http://127.0.0.1:5556`,
   matching `Kosmos-Build-Spec-v26.md` §25.7).
3. **Panel manifest.** `/tektos-ultima` renders exactly one
   `PanelKind.IFRAME` panel per ADR-089:
   - `iframe.src = "/tektos-ultima/frontend/"` (same-origin, trailing slash
     to trigger upstream's root index).
   - `iframe.sandbox = DEFAULT_IFRAME_SANDBOX =
     ("allow-same-origin", "allow-scripts", "allow-forms")`.
   - Panel descriptor is validated at panel-render time through
     `validate_plugin_descriptor` before the iframe element is emitted.
4. **Server-side bridge.** New kernel route `POST /api/tektos-ultima/bridge`
   accepts a JSON envelope, coerces `source` to `"tektos-ultima"`, validates
   the ADR-086 namespace prefix (`tektos.*` only for bridge origination),
   and publishes to `EventBusPort`. Response is `202 Accepted` with the
   published `envelope_id`, or `400` on validation failure.
5. **Client-side bridge.** `ui/components/TektosUltimaBridge.tsx` installs a
   `window.addEventListener("message", ...)` handler that:
   - Rejects `event.source !== iframe.contentWindow`.
   - Rejects `event.origin !== window.location.origin` (same-origin
     enforced end-to-end).
   - Rejects any `data.kind` not matching `/^tektos\./`.
   - Otherwise POSTs the envelope to `/api/tektos-ultima/bridge`.
6. **CSP.** Kernel response middleware appends
   `Content-Security-Policy: frame-ancestors 'self'` to every HTML
   response (or reinforces existing CSP if present). The iframe element
   is emitted with the exact `sandbox` string derived from
   `DEFAULT_IFRAME_SANDBOX`.

## Rationale

- **Route naming.** Preserves ADR-065's independence-of-agent triage
  guarantee. `/tektos-ultima` is unambiguous and matches the Brain wiki
  entry `[[projects/tektos-ultima]]`.
- **Reverse proxy in kernel, not Next.** Static export cannot host runtime
  rewrites; kernel already owns same-origin mounts (`/tektos-ui`,
  `/gnosis-gate`, `/`) and is the natural place to add one more. A future
  `ReverseProxyPort` can back this without breaking the URL.
- **PanelKind.IFRAME direct use.** Exercising the contract at Stage 2 flushes
  out any ADR-089 gaps before the six ports gain concrete adapters at
  Stage 3.13 / 4.7. Same-origin iframe + `allow-same-origin` + `allow-scripts`
  is the minimum viable set for a React microfrontend that needs `fetch`
  and localStorage; `allow-forms` covers embedded auth flows.
- **Server-side bridge with 202.** Fire-and-forget semantics match
  `EventBusPort.publish` (best-effort, subscribers may be absent);
  `202 Accepted` communicates "queued, not persisted synchronously" to
  the iframe.
- **CSP frame-ancestors 'self'.** Prevents clickjacking of the entire
  Kosmos shell from a third-party origin; combined with the iframe
  sandbox, keeps the microfrontend from re-hosting arbitrary parent
  pages.

## Alternatives rejected

- **Displace `/tektos` with the absorbed UI.** Rejected: violates
  ADR-065 Option B (approval list must remain reachable during agent
  outages). Two workloads, two routes.
- **Serve upstream at a subdomain (`tektos.kosmos.local`).** Rejected:
  cross-origin defeats `allow-same-origin` and forces the bridge to
  either drop `event.origin` validation or maintain a per-origin
  allowlist. Same-origin proxy is simpler and strictly safer.
- **Skip the reverse proxy; render the iframe against
  `http://127.0.0.1:5556`.** Rejected: mixed-origin, breaks
  `frame-ancestors 'self'`, requires the user to know upstream
  ports, and permanently entangles browser state with dev-machine
  network topology.
- **Import Tektos-Ultima's React components directly into Kosmos `ui/`.**
  Rejected as ADR-089 already resolved: absorption is a microfrontend
  boundary, not a component-library merge; different release cadences,
  different lint/type baselines, different bundler configs. ADR-091
  operationalizes that choice.
- **Wire bridge as a raw WebSocket instead of `POST` + subsequent
  WS subscription.** Rejected for Stage 2 (extra moving parts to
  test); the existing `/api/events/ws` (ADR-061) is already the read
  path for the iframe to consume kernel events, so bridge only needs
  the write half.

## Consequences

**Files added:**
- `docs/adrs/ADR-091-microfrontend-shell-integration.md` (this file)
- `kernel/tektos_ultima_bridge.py` — proxy + bridge routes
- `ui/app/tektos-ultima/page.tsx` — panel-render + `<TektosUltimaBridge />`
- `ui/components/TektosUltimaBridge.tsx` — client bridge handler
- `ui/tests/tektos-ultima.spec.ts` — Playwright coverage

**Files amended:**
- `kernel/app.py` — mount bridge router before the `/` static export
- `docs/adrs/README.md` — index row for ADR-091
- `PORTING_LEDGER.md` — Tektos absorption row for "frontend / microfrontend
  shell" flipped from `PLANNED` → `SCAFFOLDED` (kernel mount + shell panel
  landed; upstream Tektos-Ultima frontend port lands in later stages)
- `.github/workflows/ci.yml` — Playwright chromium job added
- `BUILD_LOG.md` — one entry per Stage 2 subtask (per
  `kosmos-log-maintenance`)

**Rules enforced by this ADR:**
- No cross-origin iframe for absorbed microfrontends.
- Every bridge envelope carries a `tektos.*` `kind` and `source =
  "tektos-ultima"` on the server side.
- Static-export Next.js code never proxies at runtime; kernel owns all
  reverse proxies.

## Lock-in phase

Stage 2 (this stage).

## References

- ADR-077 — kosmos-lms integration cut
- ADR-086 — EventBusPort envelope taxonomy (`tektos.*` namespace)
- ADR-089 — FrontendContractPort.PanelKind.IFRAME
- ADR-065 — Tektos UI sub-app mount (route independence)
- `Kosmos-Build-Spec-v26.md` §25.2, §25.7
