# ADR-079 — ImmunePort (new formal port)

**Status:** Ratified
**Locked:** ADR-145 (2026-09-26) — Stage 14 program freeze; this ADR is locked (see ADR-145).
**Lock-in phase:** Stage 3.13
**Supersedes:** —

## Context

Tektos-Ultima's immune subsystem is a 1,925-LOC layer with 12 detectors — including `SecretExposureDetector` (12 regex patterns), self-modification detectors, and prompt-injection detectors. In Tektos-Ultima it runs as an inline function call inside the runtime; in kosmos-lms it must sit behind a formal port so it is a Kosmos-wide capability (not a Tektos-plugin-private one) and so verdicts propagate through `EventBusPort` for other plugins (Phrouros anomaly, Praxis governance) to consume.

The existing Kosmos port inventory (15 ports) has no immune-scan surface. ADR-077 committed to introducing it as `ImmunePort`.

## Decision

Introduce **`ImmunePort`** as the 16th formal Kosmos port at `ports/immune.py`.

### Protocol surface (locked at Stage 3.13)

```python
@runtime_checkable
class ImmunePort(Protocol):
    async def scan(self, event: ImmuneScanRequest) -> ImmuneVerdict: ...
    async def register_detector(self, detector: Detector) -> None: ...
    async def list_detectors(self) -> tuple[DetectorInfo, ...]: ...
    def is_healthy(self) -> bool: ...   # sync, non-throwing
    async def close(self) -> None: ...  # idempotent
```

Value objects (frozen dataclasses):

- `ImmuneScanRequest{payload: dict, kind: str, source_plugin: str}` — the thing being scanned.
- `ImmuneVerdict{decision: Literal["allow","warn","block"], detector_hits: tuple[DetectorHit,...], reason: str}` — the outcome.
- `DetectorHit{detector_name: str, severity: Literal["info","warn","block"], evidence: str}`.
- `DetectorInfo{name: str, severity_ceiling: str, description: str}`.

### Enforcement rules

1. Every `scan()` result MUST be published on `EventBusPort` under envelope kind `immune.verdict.<decision>` (`immune.verdict.allow` / `.warn` / `.block`).
2. Every `scan()` call that returns `block` MUST also write a `MemoryPort` event with `provenance="immune_verdict"` and `confidence=1.0` per §25.4.
3. `register_detector()` is idempotent by `detector.name`. Re-registration is a no-op.
4. Adapters live under `adapters/immune/<vendor>/` and MUST implement this Protocol in full.
5. Port-level guard rejects `scan()` calls with `source_plugin=""` (mirrors `EventBusPort` rule 2 from ADR-023).

## Rationale

- **Formal port over Tektos-private module**: immune verdicts inform Phrouros anomaly detection, Praxis governance decisions, and future safety plugins; a plugin-private module would violate ADR-007 (events-only cross-plugin coupling) if any of them needed to consume verdicts.
- **`Detector` as a plugin abstraction inside the port**: allows immune adapters to compose donor detectors (Tektos-Ultima's 12) plus future kosmos-lms detectors without changing the port surface.
- **`decision` as a three-state enum**: matches Tektos-Ultima's behavior; simpler than an integer severity that adapters would coerce.
- **Rejected: fold into `ApprovalPort`.** Approval is human-in-the-loop for actions; immune is automated for events. Different life-cycles, different callers, different envelope taxonomies. Merging conflates two concerns.

## Consequences

- Files created (this ADR): `ports/immune.py` (Protocol + value objects + port-level guard); `tests/ports/test_immune_protocol.py` (stub-conformance test).
- Files planned (Stage 3.13): `adapters/immune/tektos/adapter.py`, `adapters/immune/tektos/test_contract.py`.
- Kernel boot order (§25.5) places `immune` **first** so downstream ports can subscribe to `immune.verdict.*` at their own boot.
- `PORTING_LEDGER.md` "Tektos-Ultima absorption" section already has a PLANNED entry for the Tektos immune adapter; that entry references this ADR.

## Lock-in phase

Locked at Stage 3.13. Superseded only by a rewrite ADR.

## References

- ADR-077 (integration cut) — parent decision
- ADR-078 (v26 spec cut) — §25.4 provenance taxonomy, §25.5 kernel boot order
- ADR-007 (events-only cross-plugin coupling) — why the port surface exists
- ADR-023 (`EventBusPort` envelope-first MVP) — verdict publication contract
- ADR-027 (`MemoryPort` zero-trust write contract) — verdict persistence contract
