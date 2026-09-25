# ADR-122 — Kernel-native `/api/immune/health` (Immune card re-point)

- **Status:** Ratified
- **Date:** 2026-09-25
- **Stage:** 11.6 (Endpoint Split — immune family)

## Context

The Immune card on the Tektos dashboard fetched
`/api/tektos-ultima/gateway/api/immune/health` — an ADR-109 gateway proxy to
the **standalone** Tektos service on `:8020`. That response is a
system-health *composite*: `{overall, status, components: {gpu, context,
loop_safety, inference, threat_level}, active_threats, resolved_threats,
uptime_seconds}`.

The kernel is the runtime now. It already boots a **live**
`TektosImmuneAdapter` (`KOSMOS_IMMUNE=on`, Stage 9.1) on
`registry.immune` — but that port is a different *kind* of thing than the
standalone composite: a **scan-on-request detector registry** (9.1: 12
donor detectors wrapped to `ports.immune.Detector`). It has no
per-component scoring and no persistent threat ledger — `scan()` runs
detectors against a request, `list_detectors()` reports the registry,
`is_healthy()` reports liveness.

Per the Stage 11 pattern (ADR-117…121): serve what the kernel
**actually** has, in an envelope the existing card can already parse.

## Decision

**D1 — New kernel route `GET /api/immune/health`** in `kernel/app.py`
(after the ADR-121 thermal endpoint), reading the live
`registry.immune`:

- **adapter booted + healthy** → `status: "healthy"`, `overall: 1.0`,
  `detectors: [{name, severity_ceiling, description}, …]` (real `12
  detectors registered` on Collosus), `active_threats: 0` (honest: the
  kernel port has no persistent threat ledger — scans are
  request-scoped).
- **adapter `None` (KOSMOS_IMMUNE=off) or unhealthy** → `status:
  "degraded"`, `overall: 0.0`, `detail: "ImmunePort offline (…)"`.
- **`list_detectors()` raises** → still healthy with `0 detectors` (one
  bad read must not 500; ADR-023 rule 5).
- Always **200**, ≤ ms (in-memory registry, no I/O). `uptime_seconds` =
  this kernel process's uptime (monotonic since import).
- Envelope keeps the old keys (`overall`, `status`, `active_threats`,
  `uptime_seconds`) so `parseCard` works unchanged; adds `detectors`.

**D2 — UI re-point + card extension.** Immune card gets `base: ""`
(kernel root — `fetchJson` uses `??`, so `""` resolves to the kernel, not
the gateway). `parseCard` "immune" case gains a detector line: `12
detectors · prompt_injection, secret_exposure, dangerous_command,
context_collapse` (first 4 + count).

**D3 — `components: {}` is intentional, not a placeholder.** The kernel
port does not score gpu/context/loop_safety/inference/threat_level.
Shipping fabricated component scores would be dishonest telemetry; the
card renders from `status`/`overall`/`detectors`, which are real.

**D4 — `severity_ceiling` passthrough is defensive.** In the port it is
`Literal["info", "warn", "block"]` (plain strings), but the endpoint
handles an enum-shaped value too (`.value` when present), so a future
`Enum` migration of the severity type cannot 500 the card.

## Alternatives considered

- **Proxy through the ADR-109 gateway (status quo):** rejected — the
  whole point of Stage 11 is that `:8020` is being decommissioned; a
  proxy to a dying service is exactly what this stage removes.
- **Build a composite scorer in the kernel (mimic the 5 components):**
  rejected — would duplicate/overlap the Thermal, Inference, and LLM
  cards' real data, and invent state the kernel does not track.
- **Expose the last `scan()` verdict + threat ledger:** deferred — the
  kernel port has no scan history store yet. The endpoint shape has room
  for it (`active_threats` is already in the envelope); it is a later
  slice if/when a threat-ledger port lands.

## Consequences

- Immune card is kernel-native; the gateway proxy path is dead for it.
- Card now shows the **actual detector inventory** — operationally more
  useful than the old fabricated component scores (you can see which
  detectors are armed and at what ceiling).
- `boot_errors: {}` verified live on Collosus after restart; endpoint
  returns all 12 detectors in < 50 ms.
- 5/5 tests (healthy registry, none-registry degraded, unhealthy
  adapter degraded, `list_detectors` raising, severity passthrough) —
  GPU-free, no real adapter.

## Verification (live, 2026-09-25)

```
$ curl -s http://127.0.0.1:8000/api/immune/health | head
{"overall":1.0,"status":"healthy","components":{},
 "active_threats":0,"resolved_threats":0,"uptime_seconds":13.8,
 "detectors":[{"name":"prompt_injection","severity_ceiling":"block",…} …],
 "detail":"12 detectors registered", …}
```

Card: `Healthy · 0 active threats · 12 detectors · prompt_injection,
secret_exposure, dangerous_command, context_collapse`.
