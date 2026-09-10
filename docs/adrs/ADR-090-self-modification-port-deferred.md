# ADR-090 — SelfModificationPort (PROPOSED; DEFERRED)

**Status:** Proposed (**DEFERRED** — no ratification without explicit user approval)
**Lock-in phase:** TBD (earliest Stage 5.6; not ratified in Stage 5.6)
**Supersedes:** —

## Context

Tektos-Ultima ships `self_improve/` and `self_repair/` sub-packages that modify Tektos's own source under agent control. In kosmos-lms these must exist behind a formal port so all self-modification paths are observable, gated by `ApprovalPort`, and provenance-tagged on `MemoryPort` (`provenance="tektos_self_modification"`, `confidence ≤ 0.9`, per §25.4).

But **the port itself is a load-bearing safety decision**. Any port that ratifies "the agent may edit its own source" is one of the highest-risk decisions in the Kosmos ADR ledger. It cannot be ratified as part of a bulk Stage 1 port-skeleton commit.

## Decision

**Propose** `SelfModificationPort` with a minimal surface. **Do not ratify** in Stage 1.

### Proposed surface (subject to revision at ratification)

```python
@runtime_checkable
class SelfModificationPort(Protocol):
    async def propose(self, change: SelfModificationProposal) -> ProposalId: ...
    async def approve(self, proposal_id: ProposalId, approver: str) -> None: ...
    async def apply(self, proposal_id: ProposalId) -> ApplyResult: ...
    async def rollback(self, apply_id: str) -> None: ...
    async def list_pending(self) -> tuple[SelfModificationProposal, ...]: ...
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...
```

Value objects (frozen dataclasses):

- `SelfModificationProposal{proposal_id: ProposalId, source_agent: str, target_path: str, patch: str, reason: str, proposed_at: datetime}`.
- `ApplyResult{apply_id: str, applied_at: datetime, applier: str, git_sha: str}`.

### Interim behaviour (Stage 5.6, without this ADR ratified)

Per §25.3 and Stage 5.6 DoD in `Kosmos-Build-Sequence-v26.md`:

1. Self-improve and self-repair sub-packages land at `plugins/tektos/self_improve/` and `plugins/tektos/self_repair/`.
2. All self-modification paths are gated behind `ApprovalPort` — the agent may **propose**, never **apply**.
3. Every proposal is a `MemoryPort` write with `provenance="tektos_self_modification"` and `confidence ≤ 0.9`.
4. Filesystem mutation is disallowed until ADR-090 ratifies the formal port.
5. A scripted round-trip test proves the deny path (no ApprovalPort verdict → no apply).

### Ratification pre-conditions

Before this ADR can move from PROPOSED to RATIFIED, all of the following MUST hold:

1. `SelfModificationPort` Protocol surface reviewed and stable across a full session of proposed-but-not-applied traffic.
2. `ImmunePort` `SelfModificationDetector` in production and green on a full test corpus.
3. `LoopSafetyPort` interlocks (including read-only budget per ADR-088) proven not to falsely block legitimate self-modification proposals.
4. A rollback path (`SelfModificationPort.rollback()`) demonstrated end-to-end on a scripted change.
5. Explicit user (rmholston420) approval, recorded in the ADR ratification block.

Absent any of these, the ADR remains PROPOSED.

## Rationale

- **Proposed rather than absent** so the surface is enumerated and referenced by Stage 5.6 code that lands the proposal path.
- **DEFERRED** because the safety implications warrant a dedicated ratification cycle, not a bulk Stage 1 commit.
- **No apply path in interim behaviour** so no code accidentally self-modifies during the deferred period.

## Consequences

- No `ports/self_modification.py` lands in Stage 1 (only ADR file lands).
- Stage 5.6 self-improve / self-repair sub-packages land under the interim rules above.
- When ratification pre-conditions are met, `ports/self_modification.py` lands as a separate commit and this ADR flips PROPOSED → RATIFIED with a status-amendment block per `kosmos-adr-authoring`.

## Lock-in phase

Ratification lock TBD (earliest Stage 5.6 + 1 session; no ratification during any bulk-ADR commit).

## References

- ADR-077, ADR-078 (v26 §25.3, §25.4)
- ADR-079 (ImmunePort — SelfModificationDetector is one of the 12)
- ADR-080, ADR-088 (LoopSafetyPort + read-only-budget interlock)
- ADR-019 (Approval UX specification)
- ADR-014 (UI Parity — self-modification UI surface will require parity)
