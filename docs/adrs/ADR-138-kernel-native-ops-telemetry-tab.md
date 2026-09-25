# ADR-138: kernel-native ops Telemetry tab (hardware telemetry)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.22 (endpoint split, telemetry family)
- **Supersedes:** none

## Context

The ops Telemetry tab (`ui/app/tektos-ultima/ops/page.tsx`, ADR-112) polled the ADR-109 gateway to `:8020/api/telemetry` — the standalone Tektos engine's live hardware collector. The donor's collector (tektos-ultima-v1 `agents/manager/telemetry.py`) uses NVML with a `nvidia-smi` + `/proc` fallback and returns the canonical envelope:

```
{
  "gpu": { temperature, utilization, memory_used, memory_total,
           power_draw, power_limit, fan_speed,
           clocks_graphics, clocks_memory, memory_utilization },
  "system": { cpu_util, mem_used_gb, mem_total_gb, mem_percent,
              disk_used_gb, disk_total_gb, disk_percent },
  "timestamp": <epoch seconds>
}
```

The kernel had **no** `/api/telemetry`. Two important findings shaped this ADR:

1. **The tab was broken before the split.** It parsed a *flat* shape (`temperature_gpu`, `thermal_zone`, `power_state`, `memory.used_mb`) that matched neither the donor's nested envelope nor anything else — so every metric rendered "—" already.
2. **The kernel already has a sibling sampler.** The ADR-121 `ThermalWatchdog` (`kernel/tektos_thermal_watchdog.py`) serves `GET /api/thermal/status` for the dashboard thermal card — GPU temp/power/clock, CPU temp, a 60-sample history, and sustained-cooldown *enforcement* (the watchdog can act, not just read).

## Decision (user-chosen 2026-09-25)

**Option 3 of 3:** the ops tab keeps polling a **new kernel `GET /api/telemetry`** that re-implements the donor's full canonical shape as the kernel's **own** sampler — deliberately separate from the ADR-121 watchdog.

- **`kernel/tektos_telemetry.py`** (new module): `read_gpu()` (three `nvidia-smi` queries: 7 base fields, clocks, memory utilization — split exactly as in the donor, because combined queries fail wholesale on older drivers) + `read_system()` (`/proc/stat` CPU lifetime total-vs-idle, `/proc/meminfo` mem, `shutil.disk_usage` disk) + `collect()` (the `{gpu, system, timestamp}` envelope).
- **Why no NVML:** `pynvml` is optional in `pyproject.toml` and **not installed** in the kernel venv. The donor's NVML primary path is therefore unreachable in the kernel; the donor's `nvidia-smi` CLI + `/proc` fallback is the honest portable read — and it is exactly the path the donor itself uses when NVML is absent. No dependency added.
- **Two samplers, two contracts — deliberate duplication.** ADR-121 watchdog: dashboard card + cooldown *enforcement* (acts). ADR-138 telemetry: ops tab *sensor set* (utilization, VRAM, fan, CPU/mem/disk — read-only, one sample per request). No shared mutable state; a future consolidation can alias one into the other, but today the contracts differ enough (enforcement vs. breadth) that merging would couple two UI surfaces to each other's polling cadence.
- **Degradation, never 500:** every hardware boundary degrades to the donor's zero defaults (`power_limit` defaults to 400 W — the RTX 5090 login cap from `nvidia-clock-lock.service`). A read failure is degraded, not fatal. The endpoint adds **no** handler-level `try/except` — same honest-failure convention as `/api/thermal/status`: a programming error 500s rather than being masked.
- **Blocking I/O off the event loop:** the endpoint runs `collect()` via `asyncio.to_thread` (three subprocess queries + `/proc` reads, bounded at 10 s worst case per query).
- **UI reframe (T5):** `TelemetryTab` now reads the nested envelope (base `""`, same-origin kernel). GPU temp/utilization/power/VRAM sparklines (5 s poll, 120 samples) plus GPU-mem-util/fan/clocks and CPU/RAM/disk metrics. VRAM is raw **MiB** from `nvidia-smi` (donor fidelity) rendered as GiB on display. Timestamp is epoch seconds (donor shape), rendered via `Date`. Honest footer: kernel-native, separate sampler from the dashboard thermal card.

## Consequences

- **Positive:** the ops Telemetry tab renders real live data (verified: 47 °C, 71.38/400 W, 29.9/32.6 GiB VRAM, 2497 MHz gfx clock) instead of all "—". One fewer ops-page gateway proxy. Donor-shape fidelity means the UI contract is stable across the :8020 retirement.
- **Negative:** two GPU samplers run in the kernel (watchdog every 5 s + telemetry per poll). Bounded cost — both are `nvidia-smi` reads, and the telemetry one only runs while the tab is open.
- **Non-consequence:** no new dependency (pynvml stays optional/uninstalled). No change to the ADR-121 watchdog or its cooldown enforcement.

## Slices

| Slice | Commit | Content |
|-------|--------|---------|
| T1+T2 | `8257893` | `kernel/tektos_telemetry.py` + 6/6 collector tests (GPU-free, injected boundaries) |
| T3+T4 | `967949f` | `GET /api/telemetry` endpoint + 3/3 endpoint tests (ASGITransport, collector injected) |
| T5 | `0c56442` | TelemetryTab reframe + header doc, `next build` EXIT 0, live-verified, bundle check clean |
| T6 | — | this ADR + README row + BUILD_LOG 11.22 + full regression |

## Test evidence

- `tests/kernel/test_stage_11_22_adr_138_telemetry_collector.py` — 6/6: full read, all-failed zero defaults, short-CSV per-position degrade, system shape+degrade, envelope, real `/proc` sanity.
- `tests/kernel/test_stage_11_22_adr_138_telemetry_endpoint.py` — 3/3: verbatim envelope passthrough, fully-degraded sample still 200, no aliasing across requests. Fixture keeps the real registry (the kill-switch middleware reads `registry.suspended`).
- Full regression (`tests/kernel plugins/tektos tests/adapters`): exit 0 (2 Colossus-only interactive skips).
- `next build` EXIT 0; bundle check: `temperature_gpu` absent, `/api/telemetry` present.
- Live: `curl :8000/api/telemetry` → real nvidia-smi sample, 200.
