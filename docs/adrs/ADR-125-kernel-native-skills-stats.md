# ADR-125: kernel-native `/api/skills/stats` — Tektos Manager archetype tracker

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.9 (endpoint split, skills family)
- **Supersedes:** none (removes the ADR-109 gateway proxy for the Skills card)

## Context

The Skills card fetched `/api/skills/stats` through the ADR-109 gateway
proxy to the retired `:8020` engine. Its envelope — `total_skills: 24`,
`active_skills: 24`, `top_skills` with usage counters, 16 `categories` —
is the **standalone engine's own skill manager**: 24 vendored skills with
per-skill usage statistics. The kernel has no referent for any of it:

- The kernel has no skills adapter and no skills registry.
- The donor skill-registry subsystem (`src/tektos/skills/manager.py`,
  830 LOC) is **explicitly deferred** by ADR-108 D9 — "a future
  skill-registry stage".
- The kernel's real skills-*adjacent* surface is the **Tektos Manager's
  archetype tracker** (`plugins/tektos/manager/archetype_tracker.py`,
  landed Stage 8.6): it watches Tektos task outcomes and flags recurring
  patterns as *skill candidates* (archetypes that hit a frequency
  threshold without a permanent structure yet). It is the direct
  precursor to the deferred registry — the tracker emits the feedback
  that the registry would act on.

### Layering decision (user directive, 2026-09-25)

The user asked whether Kosmos-LMS and Tektos should share skills
infrastructure or keep separate. Decision: **policy stays plugin-level,
substrate is kernel-level.** Skill *content and detection* ("what counts
as a useful Tektos skill") is Tektos policy and lives in
`plugins/tektos/`. The shared substrate — persist, approve, apply,
rollback for self-modification — is the deferred `SelfModificationPort`
(ADR-090, PROPOSED): a kernel port that both Kosmos-LMS and Tektos would
route through when ratified. Ground check: Tektos's self-improvement
machinery (`self_improve/proposer.py`, `self_repair/proposer.py`) already
consumes the four shared kernel ports (`MemoryPort` ×14, `EventBusPort`
×8, `SelfModificationPort` ×4, `ApprovalPort` ×3 references). So the
Skills card is a **Tektos card reading a Tektos surface** — endpoint
kernel-native (no `:8020` proxy, Stage 11's non-negotiable rule), data
source `registry.tektos_manager.archetypes`.

## Decision

### D1 — enable the Manager lane (env)

`KOSMOS_TEKTOS_MANAGER=on` in `ops/systemd/kosmos-kernel.local.env`. The
ADR-108 engine is lightweight (deque + tracker, no background loops) but
requires `registry.relational_memory` — which is its **own gate**,
`KOSMOS_RELATIONAL_MEMORY` (default `off`, ADR-102 D6). The first boot
with only the manager gate returned `wired: false` with empty
`boot_errors` — the silent degrade path. Added
`KOSMOS_RELATIONAL_MEMORY=postgres` (the env file already carried
`KOSMOS_POSTGRES_URI`); the Postgres lane was live-verified before
wiring: real `write_narrative` round-trip against `127.0.0.1:5432`
succeeded (id returned).

### D2 — kernel-native `GET /api/skills/stats`

Always-200 envelope:

```json
{"status": "initialized", "healthy": true,
 "skills": {"registry": "deferred (ADR-108 D9)",
            "wired": true, "archetypes": 0, "at_threshold": 0,
            "threshold": 3, "total_events": 0, "archetype_list": []},
 "errors": [], "timestamp": "..."}
```

- `wired: false` (manager off — the ADR-108 default) is a valid
  **degraded** state, not an error: the skill registry is explicitly
  deferred and the card says so instead of fabricating a count (D5 rule,
  generalizing ADR-122/ADR-124).
- `archetypes` / `at_threshold` / `total_events` / `threshold` come from
  the live `ArchetypeTracker` (duck-typed access — ADR-007, no
  cross-plugin type import); `archetype_list` caps at 20 entries, sorted
  by occurrence count descending (tracker's `get_active_archetypes`
  order).
- **`at_threshold` = skill-candidate semantics** (live test caught the
  inconsistency): an archetype is a *candidate* iff `count >= threshold`
  **and** `permanent_structure_id is None` — mirroring the tracker's
  `should_create_structure` / `get_archetypes_at_threshold`. A raw
  count-only flag would have shown an already-crystallized pattern as a
  pending candidate.
- Tracker query raising → error entry + partial data, never 500.

### D3 — card re-point + parseCard rewrite

`ui/app/tektos-ultima/page.tsx`: Skills card `base: ""`. parseCard
renders: archetype count + candidates, top candidate category (or the
honest "no patterns yet (fills as Tektos runs)"), and
`threshold N · M events · registry deferred (ADR-108 D9)`. Manager
offline → `degraded` with the offline reason / first error.

## Consequences

- The kernel now boots the ADR-108 Manager + ADR-102 Postgres
  relational-memory lane — both are prerequisites for downstream Stage 11
  families (self_repair, experience replay) and cost nothing at rest.
- The card's number is honest by construction: 0 archetypes today
  because no Tektos tasks have flowed through the turn loop yet — it
  fills as real work happens, and each at-threshold entry names a
  concrete skill candidate.
- When ADR-090 (`SelfModificationPort`) ratifies, the "registry:
  deferred" line becomes the port-backed registry — no card redesign,
  the endpoint already reports the tracker as the candidate source.

## Verification

- 6/6 tests: `tests/kernel/test_stage_11_9_adr_125_skills_stats.py`
  (real `ArchetypeTracker` data, faked registry; degraded/wired/
  candidate/structure-created/no-tracker/raising-tracker paths).
- Live: `KOSMOS_TEKTOS_MANAGER=on` + `KOSMOS_RELATIONAL_MEMORY=postgres`
  → `boot_errors: {}`, endpoint `healthy: true, wired: true, threshold: 3`
  against the real manager (Postgres lane write round-trip verified
  pre-boot).
- Full `tests/kernel/` regression green; `tsc --noEmit` clean (one
  pre-existing Playwright-spec error in an untouched file), `next build`
  succeeds.
