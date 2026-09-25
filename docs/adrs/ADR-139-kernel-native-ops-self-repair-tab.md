# ADR-139: kernel-native ops Self-Repair tab (split backends)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.23 (endpoint split, self-repair family)
- **Supersedes:** none

## Context

The ops Self-Repair tab (`ui/app/tektos-ultima/ops/page.tsx`, RepairTab)
polled three endpoints through the ADR-109 gateway to the standalone
Tektos API (:8020):

| Call | Donor behavior (:8020) |
|------|------------------------|
| `GET /api/self_repair/status` | full repair-engine status (running, uptime, repair counts, effectiveness) |
| `GET /api/self_repair/history` | the EXECUTING daemon's repair ledger (`{"history": [...]}`) |
| `POST /api/self_repair/repair` | manually triggers the repair loop |

The kernel already has a self-repair referent (ADR-128, Stage 11.11):
`GET /api/self_repair/status` returning the **propose-only** envelope —
`{status, healthy, note, proposer.{wired, tier, confidence, provenance},
strategies.{strategies_registered, categories, strategy_names}}` — an
HUMAN_REQUIRED proposer (19 static strategies) that publishes
`tektos.self_modification.proposed` on the event bus. The kernel has
**no execution path** (ADR-090: `apply()` raises) and **no repair
history endpoint**.

The tab's donor-shaped metrics (Enabled/Armed/Last check) referenced
fields the kernel envelope does not carry, so re-pointing the status
call alone would have rendered "—"s.

## Decision (user-chosen, reconfirmed 2026-09-25)

**Split backends.** Status is kernel-native; history + the repair
trigger stay on the **gateway** — i.e. the ADR-109 in-kernel reverse
proxy (`kernel/tektos_ultima_gateway.py`, same-origin :8000 routes
forwarding to :8020). That is a migration bridge, NOT a separate
service: it dies with :8020 at the Stage 14.5 `main.py` deletion
gate. The split is therefore **exit-gate debt by design**, not a
permanent architecture:

- **Run-repair trigger:** execution never comes into the kernel
  (ADR-090/128: self-modification is a human-approved proposal
  pipeline, `apply()` raises). At 14.5 the button is *removed, not
  disabled* — it retires with the engine; it is never "ported".
- **History (executed-repair ledger):** real data in :8020's process.
  At 14.5 it becomes a bus-derived PROPOSAL history
  (`tektos.self_modification.proposed` via `read_recent`, the ADR-133
  immune-history pattern) or an honest empty state.

User reconfirmation (2026-09-25, when asked whether to flip the tab
to fully kernel-native NOW vs. at 14.5): **keep as-is until 14.5** —
live executed-repair data stays served by the engine through the
bridge until deletion; the flip is the recorded residual delta.

1. **R1 — status kernel-native:** `g("/api/self_repair/status", "")`
   (base `""` = same-origin kernel, ADR-128 envelope). Metrics
   re-pointed to `Proposer` (wired/not wired), `Approval tier`
   (HUMAN_REQUIRED), `Strategies` (19 registered), `Events (engine)`.
   Donor execution fields (enabled/armed/last_check) no longer
   referenced.
2. **R2 — history + trigger unchanged:** `g("/api/self_repair/history")`
   and `act("/api/self_repair/repair")` keep the default `GATEWAY` base —
   the standalone engine's executed-repair ledger is REAL data until
   `main.py` retires (user chose real execution over an honest empty
   state). An explicit split note is rendered under the metrics:
   propose-only ADR-128, proposals published as
   `tektos.self_modification.proposed` for human approval, execution
   not wired in kernel.
3. **R3 — build + live verify:** `next build` EXIT 0; kernel status
   live (wired, HUMAN_REQUIRED, 19 strategies); gateway history live
   (`{"history":[]}`); null-guards via `isObj`/`Array.isArray` per the
   Stage 9.2/9.3 convention.
4. **R4 — docs:** this ADR + README row + BUILD_LOG 11.23.

## Alternatives rejected

- **Honest split (bus-derived proposal history):** new kernel
  `GET /api/self_repair/history` reading
  `tektos.self_modification.proposed` via `read_recent` (ADR-133
  pattern) + remove the trigger. Rejected: the executing engine's
  ledger is real data today and the user wants it until `main.py`
  deletion; the trigger would become dead UI.
- **UI-only minimal:** status → kernel, history as honest empty state,
  trigger removed. Rejected: same reason — loses live executed-repair
  data.
- **Status-only re-point without metric reframe:** rejected: the kernel
  envelope has no enabled/armed/last_check fields — the tab would show
  empty metrics.

## Consequences

- Ops page: **6 of 7 tabs fully kernel-native** (db, memory, skills,
  tools, logs, telemetry); self-repair is split (status kernel,
  history/trigger gateway). The only remaining ops-page gateway refs
  are the self-repair history/trigger + the page-level `/health`
  upstream probe (the "upstream down" banner), which folds into the
  `main.py` deletion exit gate.
- When the standalone engine retires (Stage 14.5 exit gate), the
  history section + trigger become the residual delta: either a
  bus-derived proposal history (ADR-133 pattern) or an honest empty
  state — decide at deletion time.
- Commit chain: R1-R3 = `283f1d4`; R4 = docs.
