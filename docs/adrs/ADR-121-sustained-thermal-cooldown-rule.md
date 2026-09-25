# ADR-121 — Sustained-temperature cooldown rule (ADR-081 extension) + kernel-native `/api/thermal/status`

- **Status:** Ratified
- **Date:** 2026-09-25
- **Stage:** 11.5 (Endpoint Split — thermal family)
- **Related:** ADR-081 (Colossus RTX 5090 thresholds), ADR-092 (thermal
  port/adapter), ADR-109 (gateway — the proxy being retired), ADR-118
  (the `nvidia-smi` read pattern this reuses)

## Context

Two problems in one slice:

1. **Endpoint split (thermal family).** The dashboard Thermal card
   fetched `/api/thermal/status` through the ADR-109 gateway proxy to
   the retired `:8020` standalone engine. Same class of defect as the
   Models and Inference cards fixed in ADR-119/120 — the kernel must be
   the source of truth.
2. **Missing policy.** The ADR-081 classifier is *instant-band*
   (green `<51`, yellow `[51,80)`, cap `[80,88)`, red `≥88`). It has no
   notion of *sustained* temperature. User policy (2026-09-25): the
   RTX 5090 must not *sustain* >75 °C for more than 1 minute — a
   minute-long hold means the liquid loop can't shed the load, even
   though every *instant* reading stays under the 80 °C cap band.

## Decision

**D1 — `SustainedCooldownRule` (pure, in `adapters/thermal/tektos/adapter.py`).**
A sustained-duration classifier, deliberately separate from the
instant bands: `evaluate(temp, at=ts)` tracks the continuous
at/above-threshold window and returns a `CooldownDecision`
(`active` / arming progress 0..1 / `seconds_over` / `reason`).
Defaults come from the extended ADR-081 profile:
`ColossusThermalThresholds.cooldown_c = 75.0`,
`cooldown_sustain_s = 60.0`.

- Fires when `temp ≥ 75 °C` for ≥ 60 s *continuously*.
- Drops below threshold → window resets (a burst is fine; a hold is not).
- `reset()` clears the window explicitly on failed sensor reads, so a
  stale pre-gap clock can never fire on the next good reading.
- Injected clock → unit-testable with no GPU.

**D2 — `ThermalWatchdog` (new `kernel/tektos_thermal_watchdog.py`).**
Background task started in `lifespan` (stopped before event-bus
teardown), sampling every 5 s:

- GPU via `nvidia-smi` in a worker thread (kernel venv has no pynvml —
  same bounded-read pattern as ADR-118); CPU via `/sys` hwmon
  (`k10temp` preferred, `/sys/class/thermal` fallback — no psutil).
- Each sample runs `SustainedCooldownRule` then classifies to the card's
  existing action vocabulary: `<75 °C → relax`, `75–80 °C → hold`
  (arming %), `≥80 °C → throttle`, rule-fired → `cooldown`.
- **Real enforcement:** firing drops the power cap to 350 W
  (`sudo nvidia-smi -pl 350`, the existing NOPASSWD entry); clearing
  restores the 400 W login default. Transitions publish
  `thermal.cooldown` / `thermal.cooldown_cleared` on the event bus.
- Degrade pattern (ADR-092): `snapshot()` never raises, never
  fabricates — a failed read holds `hold` + reason. Cap apply is
  best-effort (log on failure, never 500).
- Env-gated `KOSMOS_THERMAL_WATCHDOG` (default on; off in CI sandboxes).

**D3 — `GET /api/thermal/status` (kernel-native, in `kernel/app.py`).**
Serves the watchdog's in-memory snapshot. Envelope mirrors the old
`:8020` shape (`gpu.{temperature,action,reason,power_limit}`,
`cpu.temperature`, `regulation_count`, `history`) so the card parses it
unchanged, plus the new `gpu.cooldown` block
(`{active, threshold_c, sustain_s, seconds_over, arming}`). When the
watchdog is off, a one-shot `nvidia-smi`/`/sys` read degrades the
response (real temps, no rule enforcement). Always 200.

**D4 — UI (`page.tsx`).** Thermal card re-pointed via `base: ""`
(kernel-native root; `fetchJson` uses `??` so `""` is authoritative).
`parseCard` gained one line: when `cooldown.arming` or
`cooldown.active`, a `❄ arming X/60s at ≥75°C` /
`❄ cooldown · Xs ≥ 75°C` row appears; otherwise the card stays quiet.
No other card change.

## Verification

- 17/17 tests: 8 rule tests (boundary, burst, reset, injected clock) +
  9 watchdog tests (fire/cap/clear, gap-reset, no-fabrication,
  snapshot shape) — all GPU-free via faked reads/caps/clock.
- Live: `:8000/api/thermal/status` after restart returned
  `47°C GPU / 60°C CPU / relax / power_limit 400 / cooldown inactive`
  with `history` accumulating at 5 s cadence (`regulation_count`
  incrementing); `/health` `boot_errors: {}`.
- `next build` clean (only the pre-existing Playwright spec error);
  served chunk verified.

## Consequences

- The GPU now *actually* sheds load when it sustains >75 °C for
  >1 min — previously only the retired :8020 regulator (if running at
  all) had any action, and the kernel had no thermal enforcement.
- 350 W is a modest step (−12.5 % from the 400 W login cap) — enough
  to pull the steady state back under 75 °C without starving the
  27B inference lane. If it proves insufficient the knob is
  `COOLDOWN_POWER_CAP_W`, not a re-architecture.
- `thermal.cooldown` on the event bus lets the immune system /
  notifications observe sustained-heat events without polling.
- ADR-081 bands are untouched — the sustained rule is additive, so
  the existing `thermal.<level>` crossing events are unchanged.
