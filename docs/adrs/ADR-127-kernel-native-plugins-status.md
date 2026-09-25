# ADR-127: kernel-native `/api/plugins` — subsystems + frontend_contract descriptors

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.11 (endpoint split, plugins family)
- **Supersedes:** none

## Context

The Tektos dashboard **Plugins** card proxied `:8020/api/plugins` — the standalone
engine's *functional* search-provider plugin list (searxng / duckduckgo / farfalle /
tavily, loaded by the donor's `plugin_loader.py`).

User clarification (2026-09-25): **the kernel's `plugins/` packages (phrouros,
praxis, zetesis, tektos) are sub-systems, not real plugins.** A real plugin is a
loadable unit the kernel substrate can host generically. Recon confirmed the kernel
has *no functional plugin registry*:

1. `kernel/plugins/` = **sub-systems** — wired kernel components with registry slots
   (phrouros→`registry.phrouros`, zetesis→`registry.zetesis`, tektos→`registry.tektos`,
   praxis→apex engine via the approval slot). Not swappable units.
2. The kernel's *genuine* plugin mechanism is **`FrontendContractPort`**
   (`ports/frontend_contract.py`) — a frozen `PluginDescriptor` registry
   (name / version / kernel_compat / routes / panels / design-tokens). This is
   what the dashboard itself renders from, already exposed at
   `/api/kernel/plugins` (503-gated, frontend-contract shape).
3. Tektos's four functional search providers live **only** in the standalone
   `:8020` engine (and the donor). No kernel referent exists.

## Decision

`GET /api/plugins` (always 200) reports the kernel truth and marks the gap:

```json
{
  "status": "initialized | degraded",
  "healthy": true,
  "note": "kernel plugins/ packages are subsystems; plugin mechanism = frontend_contract descriptors",
  "subsystems": { "phrouros": true, "praxis": true, "zetesis": true, "tektos": true },
  "ui_plugins": {
    "count": 2,
    "plugins": [
      { "name": "tektos", "version": "1.0.0", "kernel_compat": "1.0",
        "routes": ["/tektos"], "panels": ["tektos-overview"] }
    ]
  },
  "functional": {
    "kernel_registry": "pending (follow-up ADR — loadable functional plugins usable Kosmos-wide)",
    "tektos_search_providers": "standalone engine (:8020/api/plugins)"
  },
  "errors": [],
  "timestamp": "..."
}
```

### D1 — subsystems, correctly labeled
`subsystems` reads the four `plugins/` packages' registry slots (wired = slot non-None),
the same way `/health` reports subsystems. `praxis` has no direct slot — its apex
engine is the approval subsystem (`KernelChangeApprovalAdapter`), so its wiring
tracks the `approval` slot. These are **never** reported as plugins.

### D2 — ui_plugins = the real plugin mechanism
`ui_plugins` is the `FrontendContractPort` descriptor list (`list_plugins()`),
duck-typed per ADR-007. When `frontend_contract` is `None` (boot failure) the card
degrades (`status: "degraded"`, empty list, no fabricated count). When the registry
is present but `list_plugins()` raises, it degrades *partially*: `healthy: true`,
`count: 0`, error entry — never 500.

### D3 — the functional gap is explicit
`functional.kernel_registry` states the kernel functional-registry is **pending**
(a follow-up ADR); `functional.tektos_search_providers` states the four search
providers remain on the standalone engine. This is the honest seam for the
"usable by Kosmos-LMS in general" follow-up.

## Consequences

- The Tektos dashboard Plugins card now reads kernel truth (`base: ""`, no proxy).
- Kernel sub-systems are surfaced with correct semantics (wired / not), not hidden
  behind a misleading "plugin count".
- The functional-plugin gap is a visible, named follow-up rather than a silent
  fabrication.

## Follow-up (deferred, out of Stage 11 scope)

Kernel **functional plugin registry**: a loadable-unit contract (search-provider
port + loader) so Tektos's search plugins — and any functional plugin — become
usable Kosmos-wide. This is feature work (new port + porting 4 providers, ~1.6k LOC
donor), deliberately cut from the endpoint-split slice to preserve the small-step
cadence. Tracked as a separate ADR.
