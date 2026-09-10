# ADR-081 — ThermalPort (new formal port)

**Status:** Ratified
**Lock-in phase:** Stage 3.13
**Supersedes:** —

## Context

Colossus runs an RTX 5090 (32 GB VRAM, Blackwell/SM_120, liquid-cooled, on a 1600 W PSU behind an X870E Aorus Pro Ice). Tektos-Ultima maintains a PID thermal controller with three thresholds (yellow 51 °C, cap 80 °C, red 88 °C) and a 400 W GPU power cap. Thermal red states must be observable by `LLMPort` (to refuse new inference), `ResourcePort` (to shape back-pressure), and Praxis governance (to record the event).

In Tektos-Ultima this is inline in the runtime. In kosmos-lms it must be a formal port so every plugin sees the same thermal signal and no plugin can bypass a red state.

## Decision

Introduce **`ThermalPort`** as the 18th formal Kosmos port at `ports/thermal.py`.

### Protocol surface

```python
@runtime_checkable
class ThermalPort(Protocol):
    async def sample(self) -> ThermalSample: ...
    def pressure(self) -> ThermalPressure: ...   # sync, non-throwing, cached last-sample
    async def apply_power_cap(self, watts: int) -> None: ...
    async def release_power_cap(self) -> None: ...
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...
```

Value objects (frozen dataclasses):

- `ThermalSample{sampled_at: datetime, gpu_temp_c: float, power_w: float, fan_pct: int | None}`.
- `ThermalPressure{level: Literal["green","yellow","cap","red"], gpu_temp_c: float, power_cap_w: int | None}`.

### Enforcement rules

1. Every crossing of a threshold (green ↔ yellow ↔ cap ↔ red) MUST publish an envelope on `EventBusPort` under `thermal.<level>` with the current `ThermalSample`.
2. Every red-level transition MUST also write a `MemoryPort` event with `provenance="thermal"` and `confidence=1.0` per §25.4.
3. `pressure()` is sync + non-throwing (per convention) so any hot-path caller (LLMPort adapter, ResourcePort) can consult it without an `await`.
4. `apply_power_cap()` is idempotent; calling with the current cap is a no-op.
5. Adapters live under `adapters/thermal/<vendor>/`. The Tektos-Ultima adapter uses `nvidia-smi` + PID loop; a `NoOpThermalAdapter` is available for CI (returns synthetic green samples).

### Threshold ownership

Thresholds are configuration on the adapter, not on the port. The port surface is thermal-hardware-agnostic (a future adapter for CPU-only or Apple Silicon systems reuses the same Protocol).

## Rationale

- **Formal port over inline runtime check**: red states must gate `LLMPort` inference; only a port surface enforces that.
- **`pressure()` sync**: hot-path callers (per-request throttling) cannot afford an `await`.
- **Power-cap methods on the same port** (rather than a `PowerPort`): coupling is tight — thermal state determines cap; separating them adds an event round-trip.
- **Rejected: fold into `ResourcePort`.** ResourcePort is System-3 control (six canonical kinds); thermal is a hardware sensor stream. Overloading ResourcePort with sensor data mixes life-cycles.

## Consequences

- Files created (this ADR): `ports/thermal.py`; `tests/ports/test_thermal_protocol.py`.
- Files planned (Stage 3.13): `adapters/thermal/tektos/adapter.py`, `adapters/thermal/noop/adapter.py`, both with `test_contract.py`.
- `LLMPort` adapters will consult `ThermalPort.pressure()` before each inference and raise if `level == "red"`. That coupling lands in Stage 3.13 as part of the LLMPort adapter update, not this ADR.
- Kernel boot order (§25.5) places `thermal` third (after `immune`, `loop_safety`).

## Lock-in phase

Locked at Stage 3.13.

## References

- ADR-077 (integration cut), ADR-078 (v26 §25.7 thresholds table)
- ADR-023 (`EventBusPort` envelope-first MVP)
- ADR-027 (`MemoryPort` zero-trust write contract)
- ADR-029 (`ResourcePort` — why thermal is NOT folded in)
