# ADR-089 — FrontendContractPort: add `PanelKind.IFRAME`

**Status:** Ratified
**Lock-in phase:** Stage 2 (kosmos-lms Stage 2 — plan §6)
**Amends:** the FrontendContractPort ratifying ADR (existing `PanelKind` enum extended)

## Context

Per §25.2, the Kosmos Next.js shell (`ui/`, Next 16.2.11) hosts the Tektos Next.js UI (`plugins/tektos/frontend/`, Next 15.4, 40 panels) as an **iframe/microfrontend** at `/tektos/frontend`, same origin via reverse proxy. `FrontendContractPort` currently registers panels as component descriptors mounted directly by the shell. There is no `IFRAME` panel kind, so Tektos frontend panels cannot register under the existing surface without violating the descriptor contract.

## Decision

Extend `FrontendContractPort`'s `PanelKind` enum with **`IFRAME`**.

### Panel descriptor extension

An `IFRAME` panel descriptor has:

- `kind = PanelKind.IFRAME`
- `src: str` — same-origin path served by the shell's reverse proxy (e.g. `/tektos/frontend/panels/agent-trace`).
- `sandbox: tuple[str, ...]` — HTML iframe sandbox attributes (default: `("allow-same-origin", "allow-scripts", "allow-forms")`; postMessage / clipboard / camera off unless declared).
- `title: str` — accessible label.
- `size_hint: PanelSize` (existing value object).

### Communication contract

- Iframe panels communicate with the shell via `window.postMessage` only.
- The shell's `EventBusPort` bridge (browser-side) listens for messages with envelope shape `{type: "kosmos.event", envelope: EventEnvelope}` and re-publishes on the server-side `EventBusPort`.
- Iframe messages MUST include `origin` validated against `window.location.origin`; cross-origin messages are dropped.

### Reverse proxy contract

- Shell (Next 16.2.11) mounts the Tektos Next 15.4 app under `/tektos/frontend/*` via a rewrite rule.
- Both dev and prod use the same rewrite; Tektos frontend dev-server runs on `:5556` locally (per §25.7) and the shell proxies to it.
- `Content-Security-Policy` `frame-ancestors 'self'` is set — iframe panels only load in the Kosmos shell, not embedded elsewhere.

## Rationale

- **`IFRAME` kind over full component absorption**: absorbing Tektos's 40 panels into the Kosmos shell requires Next 15 → 16 reconciliation, Monaco + xterm + D3 dependency merge, and a shared Tailwind theme, all on the critical path. Iframe defers that work and preserves Tektos's UI as-is.
- **Same-origin via reverse proxy**: iframe panels share the shell's cookies/session (auth is a single surface); cross-origin would force CORS work and split the session store.
- **postMessage over shared JS globals**: postMessage is the standard iframe boundary; sharing globals through the frame boundary is a well-known footgun.
- **CSP frame-ancestors 'self'**: closes the clickjacking attack surface.
- **Rejected: separate origin (`tektos.local`) for the iframe.** Splits session, forces CORS, complicates deployment. Same-origin via reverse proxy is standard.
- **Rejected: unified Next.js shell (absorb Tektos panels directly).** Next 15 → 16 reconciliation on the critical path is exactly what this ADR is designed to defer.

## Consequences

- Files edited (this ADR): `ports/frontend_contract.py` (add `IFRAME` to the `PanelKind` enum; extend `PanelDescriptor` union with `IframePanelDescriptor`).
- Files planned (Stage 2): `ui/next.config.js` gains `rewrites` for `/tektos/frontend/*`; `ui/lib/eventBusBridge.ts` implements postMessage bridge; a first `IFRAME` panel registers as a smoke test.
- CSP `frame-ancestors 'self'` set on the shell's response headers.
- Tektos frontend deployment surface unchanged (still Next 15.4, still port 5556 in dev).

## Lock-in phase

Locked at Stage 2 (kosmos-lms Stage 2). Superseded only by a future ADR that folds Tektos frontend into a unified shell.

## References

- ADR-077, ADR-078 (v26 §25.2)
- ADR-014 (UI Parity standing rule)
- ADR-072 (Stage 1.5 Wave F panel completion — precedent for panel-registry semantics)
- Project knowledge concept `gateway-proxy` — WebSocket bridge pattern
