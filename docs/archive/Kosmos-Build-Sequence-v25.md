# Kosmos Build Sequence v25

**Purpose:** Executable, ordered task list. Each step lists Stage → Plugin/Kernel component → Ports touched → Definition of Done. Follow strictly top-to-bottom. If a step's DoD is not met, **stop** — do not proceed.

**Companion documents (must be present at build time):**
- `Kosmos-Build-Spec-v25.md` — full spec (this sequence is its executable index)
- `PORTING_LEDGER.md` — every OSS port logged here first, then adapted
- `adrs/ADR-###-*.md` — architectural decisions (all resolved except ADR-010)
- `BUILD_LOG.md` — append-only, timestamp every completed step
- `DEBUG_LOG.md` — append-only, search **before** diagnosing anything new
- `KNOWN_ISSUES.md` — running list of unresolved bugs / blocked work
- `SESSION_HANDOFF.md` — overwrite at end of every session
- `perplexity/skills/` — four Perplexity Computer skills that automate step compliance

**Golden rules (all steps):**
1. Vendor a permissively-licensed OSS component before hand-writing. Log in `PORTING_LEDGER.md` **before** first commit.
2. No plugin imports another plugin. All coupling via event bus or ports (ADR-007).
3. Zero-trust memory writes: no `MemoryPort.write` without `provenance` + `confidence` fields.
4. No cloud, no multi-user, no GitHub-native CI unless explicitly requested.
5. Every step's completion appended to `BUILD_LOG.md` with timestamp + files touched + ports affected.

---

## Stage 0 — Repo Bootstrap (Day 0, ~4h)

### 0.1 Create monorepo skeleton
- **Ports touched:** none
- **DoD:**
  - `kosmos/` directory created (fresh, not a fork of Rigpa-LMS)
  - Top-level dirs: `kernel/`, `plugins/`, `ports/`, `adapters/`, `governance/`, `ops/`, `docs/`, `adrs/`, `templates/`, `.perplexity/skills/`
  - `pyproject.toml` with `uv` as package manager, Python 3.12 pinned, `ruff` + `bandit` + `pytest` dev dependencies
  - `.pre-commit-config.yaml` runs ruff + bandit + secret-scan on every commit
  - Git initialized, first commit tagged `v25.0.0-bootstrap`

### 0.2 Copy templates
- `cp templates/{BUILD_LOG,DEBUG_LOG,KNOWN_ISSUES,SESSION_HANDOFF}.md ./`
- Copy full `Kosmos-Build-Spec-v25.md` + `Kosmos-Build-Sequence-v25.md` + `PORTING_LEDGER.md` + `adrs/` into `docs/`
- **DoD:** All logs exist, empty, and are appended to on the very next commit.

### 0.3 Install Perplexity Computer skills into user library
- Zip each `.perplexity/skills/kosmos-*/` and upload to Perplexity user skill scope
- Verify each skill loads: `list_skills(query="kosmos")` returns all four
- **DoD:** `kosmos-port-workflow`, `kosmos-adr-authoring`, `kosmos-log-maintenance`, `kosmos-spec-diff` all loadable.

---

## Stage 1 — Kernel Ports + Foundational Adapters (Week 1, ~5 days)

Ports are the immortal contracts. Adapters may be swapped later; ports may not change without an ADR.

### 1.1 Consolidate donor adapters (ADR-012)
- **Donor:** `Rigpa-LMS/*` — inspect for `ollama.py` and `searxng.py` duplicates
- **Action:** Merge duplicates into single canonical adapters at `adapters/llm/ollama.py` and `adapters/search/searxng.py`
- **DoD:** No duplicates remain; single implementation covers all call sites; test suite green.

### 1.2 Define ten formal ports
Write pure Python `Protocol` interfaces (no implementations) at `ports/`:
- `LLMPort` — generate, embed, tool-call
- `MemoryPort` — write(provenance, confidence), read, evict
- `VectorPort` — upsert, query, delete
- `EventBusPort` — publish, subscribe, ack
- `SecretsPort` — get, put, rotate
- `ObservabilityPort` — trace, log_event, metric
- `FrontendContractPort` — declarative UI schema
- `ResourcePort` — reserve/release GPU + RAM slots
- `DataPort` — read/write JSON-LD documents
- `NotificationPort` — send algedonic alerts
- **DoD:** Every port has type-checked signatures; `mypy --strict ports/` passes.

### 1.3 LLMPort adapter — llama-swap primary (ADR-009)
- **Port:** `PORTING_LEDGER.md` entry for `llama-swap` (source URL, commit SHA, SPDX)
- **Action:** Wrap llama-swap behind `LLMPort`. Add router-mode fallback stub (behind feature flag).
- **DoD:** `pytest adapters/llm/test_llama_swap.py -k contract` green.

### 1.4 SecretsPort adapter — Vault (dev mode)
- **Port:** `hvac` (already permissively licensed)
- **Action:** Vault in dev-mode Docker Compose; systemd unit for prod. All secrets rotate via `SecretsPort.rotate`.
- **DoD:** Restart Vault, all consumers reconnect; no plaintext secret anywhere on disk.

### 1.5 ObservabilityPort adapter — Langfuse
- **Port:** Langfuse OSS
- **DoD:** One end-to-end trace visible in Langfuse UI for a scripted LLM call.

### 1.6 EventBusPort adapter — Valkey Streams
- **DoD:** Publish → subscribe round-trip test passes; consumer group survives broker restart.

### 1.7 Model-swap SLO validation (ADR-009 lock-in)
- **Benchmark on Colossus:**
  - Cold-load target: **<8s**
  - Warm-swap target: **<2s**
  - Priority queue: Phrouros anomaly > active Tektos > Synedrion/Zetesis background
- **If llama-swap fails SLO** → switch to router-mode fallback, log decision in ADR-009 amendment, append to `BUILD_LOG.md`.
- **DoD:** SLO measured, recorded in `ops/benchmarks/model-swap-2026-XX-XX.md`; ADR-009 status set to `LOCKED` or `AMENDED`.

### 1.8 MemoryPort formalized — DozerDB + Graphiti + Agent Memory Guard (ADR-008 + ADR-027)
- **Port:** MemoryPort (full surface: write_event / query_temporal / link_entities / quarantine_write + is_healthy + close)
- **Backend:** DozerDB (community Neo4j fork with enterprise features, ADR-008); Graphiti temporal index atop the same DozerDB via `neo4j` driver (Apache-2.0); Agent Memory Guard v0.2.2 write-time policy filter (OWASP)
- **Action:**
  1. Log DozerDB + `neo4j` driver + graphiti-core + agent-memory-guard v0.2.2 + Rigpa donor pattern in `PORTING_LEDGER.md`
  2. Declare `MemoryPort` Protocol + typed value objects (`MemoryEventId`, `MemoryHit`) + non-bypassable port-level guard (`validate_zero_trust_write`) in `ports/memory.py`
  3. Ship `DozerDbMemoryAdapter` + three injectable Protocol seams (`GraphBackend`, `AmgPolicy`, `TemporalIndex`) with in-memory test doubles for each
  4. Write-time enforcement order: port-level guard → AMG policy verdict → graph transaction (CIDOC-CRM triple decomposition) → temporal index registration
  5. Deploy DozerDB via Docker Compose (out-of-scope for Stage 1.8 code; lands with Compose ops-deploy stage per spec §21)
- **DoD:**
  - `MemoryPort` isinstance check passes on `DozerDbMemoryAdapter`
  - Port-level guard rejects missing/invalid `provenance` or `confidence` (100% negative-case matrix)
  - AMG `block` → raises `MemoryWriteBlocked`; `quarantine` → routes to quarantine lane (not indexed in temporal); `redact` → uses redacted payload; `allow` → normal write
  - `is_healthy()` sync + non-throwing; `close()` idempotent + swallows backend close errors
  - All four verbs green under contract tests using `InMemoryGraphBackend` + `NoOpAmgPolicy` + `InMemoryTemporalIndex`

### 1.9 Memory-bridge redundancy comparison (ADR-013)
- Compare `Rigpa-LMS/memory/bridge.py` against Gnosis schema. Pick the survivor.
- **DoD:** ADR-013 status = `LOCKED`; one bridge implementation; other deleted.

### 1.10 DataPort adapter — JSON-LD file store (ADR-028)
- **Action:** Local filesystem-backed JSON-LD store with JCS (RFC 8785, `rfc8785` Apache-2.0) canonicalization, pluggable `Signer` Protocol seam (`NoOpSigner` primary; `Ed25519FileSigner` deferred to Stage 5 governance-key wiring via `cryptography>=49` Apache-2.0 OR BSD-3), non-bypassable port-level zero-trust guard on `provenance`/`confidence`/`pii_tier`, four-tier PII routing (Restricted under `restricted/` prefix), and live never-overwrite migration guard (spec §230, §232). YAML permitted for config only; TOON only in LLM context (measured).
- **Ports:** DataPort (ADR-028 surface + enforcement)
- **DoD:** `DataPort` full three-verb surface implemented; `FilesystemDataAdapter` composes `Canonicalizer`/`Signer`/`Storage` Protocol seams; canonical envelopes round-trip losslessly (recompute `canonical_hash` ≡ stored `canonical_hash`); `check_format_health` flags hash-tampering; `migrate_schema` never-overwrite guard live (idempotent same-hash re-runs allowed, collision raises `MigrationTargetExists`); ADR-028 status = `Ratified v25`; contract tests green (47 tests, cumulative 223/223).
- **Locked:** 2026-07-29 EDT (ADR-028); primary Stage 1.10 signer is `NoOpSigner` — envelopes are hash-anchored, signatures activate at Stage 5.

### 1.11 ResourcePort adapter — APEX substrate + priority queue (ADR-029)
- **Action:** Ship full ResourcePort surface (spec §4.1 line 92 verbs + priority-queue verbs `enqueue`/`peek`/`dequeue`/`cancel` per spec §172). SQLite primary (WAL, `aiosqlite>=0.20` MIT) with pluggable `Storage` Protocol seam (`InMemoryStorage` test double). Six canonical `ResourceKind` enum (time/money/attention/compute/knowledge/energy). Fixed priority order: `PHROUROS_ANOMALY` > `TEKTOS_ACTIVE` > `BACKGROUND`. Non-bypassable port-level zero-trust guard rejects missing/invalid `kind`/`amount`/`intent`/`priority_class`/`requester`. Decimal balance precision preserved end-to-end (no float drift). Landed at Stage 1.11 instead of the aspirational §1.13 slot; §1.13 marked satisfied by this landing.
- **DoD:** Attempt to reserve 40 GB VRAM on a 32 GB card → clean rejection (Build-Sequence §1.13 DoD). 54 contract tests green.
- **Locked:** 2026-07-29 EDT (ADR-029).

### 1.12 NotificationPort adapter — algedonic channel (landed 2026-07-29 22:52 EDT per ADR-030)
- **Status:** Ratified v25 — shipped in this session.
- **Action:** `KernelNotificationAdapter` implements full `NotificationPort` surface (spec §4.1 `notify` / `subscribe_channel` / `ack_receipt` **plus** Q1=B `deliver_algedonic` fast-path + `check_delivery_slo` self-probe) with `AlgedonicTier` enum (INFO/WARN/ACTION/ALGEDONIC per spec §30/§280/§344). One injectable Protocol seam: `Sink` — primary `InProcessSink` (thread-safe 200-cap FIFO ring buffer, newest-first, matches Rigpa `NotificationCenterService` donor pattern; kernel dashboard polls `snapshot(limit)`; `mark_read`/`mark_dismissed` bookkeeping) + stub `NtfySink` (lazy `httpx` import, 0.4s timeout to protect DoD, `AlgedonicTier`→ntfy-priority mapping). Algedonic fast-path fans out to all sinks concurrently via `asyncio.gather(*, return_exceptions=True)` so latency is bounded by slowest sink, not the sum. Port-level non-bypassable zero-trust `validate_notification` guard rejects missing/invalid `tier`/`source`/`title`/`body`. `is_healthy` sync non-throwing (ADR-023 rule 5); `close` idempotent async, cascades to sinks. SMS mobile-fallback deferred to §344.4 (requires Stage 5 governance-key wiring).
- **DoD:** Priority alert delivered within 500ms end-to-end. ✔ (literally verified by `test_algedonic_delivery_under_500ms_dod`: `deliver_algedonic` → `InProcessSink` → `receipt.latency_ms < 500`; 59/59 contract tests pass; full suite 336/336 pass.)

### 1.13 ResourcePort adapter — GPU/RAM reservation (satisfied at Stage 1.11 per ADR-029)
- **Status:** Historically listed here in the aspirational sequence; the actual landing shipped at Stage 1.11 with ADR-029. Retained as a numbering-slot placeholder; DoD satisfied.
- **DoD:** Attempt to reserve 40GB VRAM on a 32GB card → clean rejection. ✔ (Stage 1.11)

### 1.14 FrontendContractPort adapter — declarative UI schema (landed 2026-07-29 23:05 EDT per ADR-031)
- **Action:** Ship full FrontendContractPort surface (spec §4.1 line 91 verbs — `register_plugin`/`unregister_plugin`/`list_plugins`/`get_route_manifest`/`get_design_tokens`/`get_state_namespaces`/`get_panel_manifest`/`check_ui_parity`/`render_kernel_schema` plus `is_healthy`/`close` lifecycle) per **ADR-031**. Primary `KernelFrontendContractAdapter` (pure stdlib, zero new deps) with pluggable `ManifestStore` Protocol seam: `InMemoryManifestStore` (dict-backed) primary + `FileManifestStore` (stdlib `pathlib`+`json`, atomic tmp-rename write) stub deferred to Stage 5 auditor wiring. Mirrors Rigpa-LMS `RigpaFrontendPlugin` donor shape (name/state_namespace/design_tokens/routes) extended with typed `Panel` value objects across nine `PanelSlot`s (spec §280 + §17.9 + §17.13) + `version`/`kernel_compat`. `UiParityStatus` enum {NOT_STARTED, IN_PROGRESS, COMPLIANT, GRANDFATHERED}. Non-bypassable port-level zero-trust guard rejects missing/invalid required fields, invalid plugin-name regex, empty route/panel `lazy_module`, and duplicate registrations. Design-token merge is last-registered-wins; panel ordering is `priority DESC` with insertion-order tiebreaker.
- **DoD:** Empty kernel dashboard renders "Kosmos" title from a schema, no plugin loaded — `render_kernel_schema()` returns `KernelSchema(title="Kosmos", plugins=(), panels=())` (test `test_empty_dashboard_renders_kosmos_title_build_sequence_1_14_dod` literally satisfies this). 56 contract tests green (392 suite total).

### 1.15 Stage-1 exit gate (landed 2026-07-29 23:12 EDT)
- All **eleven** ports have working adapters (SearchPort §1.1 / LLMPort §1.2 / EventBusPort §1.4 / SecretsPort §1.5 / ObservabilityPort §1.6 / VectorPort §1.7 / MemoryPort §1.8 / DataPort §1.10 / ResourcePort §1.11 / NotificationPort §1.12 / FrontendContractPort §1.14 — §1.13 slot absorbed by §1.11 per ADR-029)
- All ADR statuses: **Ratified v25** / **Ratified** / **LOCKED** except ADR-010 (**OPEN**, deferred to pre-Phase-6.2), audited against `docs/adrs/README.md` summary table
- BUILD_LOG shows every Stage-1 sub-stage (1.1 through 1.14, minus the aspirational §1.9 and the §1.13-satisfied-at-§1.11 slots) with America/Detroit timestamps
- **DoD:** `make stage1-gate` runs `scripts/stage1_gate.py` — audits eleven ports+adapters+contract-tests, audits ADR statuses via `docs/adrs/README.md`, audits BUILD_LOG per-sub-stage entries, runs full pytest suite — all four criteria green. **PASS** (392/392 tests).

---

## Stage 2 — Praxis + Phrouros (Governance) (Week 2)

### 2.1 Praxis constitution loader (landed 2026-07-29 23:15 EDT per ADR-032)
- **Ports:** FrontendContractPort (kernel-side plugin registration); `DataPort` and `SecretsPort` remain in the aspirational Stage-2.1 scope but are not required for the DoD — the boot-time load-and-verify path reads directly from `governance/constitution/versions/vNNNN.{yaml,json,sig}` and `governance/constitution/pubkey.pem` on the filesystem; DataPort integration will land when the amendment workflow lands at Synedrion (Phase 6.3) per spec §278; SecretsPort integration will land when Restricted-tier private-key material is externalized (currently the genesis privkey lives ephemerally under gitignored `.secrets/genesis/privkey.pem`).
- **Action:** Boot-time load-and-verify of the ratified `vNNNN.{yaml,json,sig}` constitution triplet, Ed25519 JWS over JCS canonical JSON (RFC 8785), against the co-located `pubkey.pem`. Three-tier invariant chain: (1) all three artifacts + pubkey exist, (2) on-disk JSON is the JCS canonicalization of parsed on-disk YAML, (3) Ed25519 signature verifies against pubkey over the canonical JSON. Any failure raises a `ConstitutionError` subclass from `ConstitutionLoader.__init__` — that raise IS the boot-refusal signal. Praxis plugin (`plugins.praxis.plugin.PraxisPlugin`) runs verification **before** any FrontendContractPort call, so tamper leaves the kernel with no partially-registered plugin. Per ADR-032 Q1=B: verifier + loader + standalone `signing.py` helper ship at 2.1; amend service, CLI, HTTP surface, SQLAlchemy models, Pydantic schemas all deferred to Synedrion (Phase 6.3) per spec §278. Per ADR-032 Q2=A: Praxis registers a `PluginDescriptor` with `panels=(Panel(id="praxis.governance", slot=GOVERNANCE, priority=100, lazy_module="praxis/panels/GovernancePanel", plugin_name="praxis"),)` and `ui_parity_status=IN_PROGRESS` — no §17.1 amendment; IN_PROGRESS handles the case natively; Stage 3.5 Next.js shell resolves the lazy_module reference and promotes to COMPLIANT.
- **DoD:** Tampered constitution → boot refused. Test `test_tampered_constitution_refuses_boot_build_sequence_2_1_dod` in `plugins/praxis/tests/test_constitution_loader.py` literally satisfies this by editing the on-disk YAML post-ratification and asserting `ConstitutionLoader(constitution_dir=..., verify_on_init=True)` raises `ConstitutionTamperError`. **PASS** (40 Praxis contract tests green; full suite 432/432).

### 2.2 APEX Change Approval Tier engine (landed 2026-07-29 23:44 EDT per ADR-033)
- **Ports:** EventBusPort, NotificationPort, SecretsPort (mobile signed-token key backing per ADR-024 + Q1=C)
- **Tiers:** `AUTONOMOUS` (persist APPROVED + emit `apex.intention.approved`; no scheduler wiring), `HUMAN_REVIEW` (persist PENDING; one-shot `AlgedonicTier.ACTION` notification via `NotificationPort.notify(channel="approvals")`; schedule single missed-review callback at T+4h that flips status to `REVIEW_MISSED` and fires `apex.review.missed`; execution unblocked per spec §14), `HUMAN_REQUIRED` (persist PENDING; schedule escalating `NotificationPort.deliver_algedonic()` cadence at T+24h then every 6h up to a 30-day self-refreshing horizon; each tick short-circuits if the record is no longer PENDING).
- **Action:** Kernel-wide `ChangeApprovalProtocol` at `plugins/praxis/apex/protocol.py` with async `propose`/`resolve`/`list_pending`/`get_by_id`/`list_by_intention` verbs. `KernelChangeApprovalAdapter` (engine.py) composes three seams: `Storage` (`InMemoryStorage` primary + `SqliteStorage` stub for Stage 5 durable audit), `Scheduler` (Q2=A — `InProcessScheduler` asyncio-task-backed primary + `FakeScheduler` deterministic test double + `NullScheduler` no-op), and `EventBusPort` (envelopes carry `producer_plugin="praxis"` per ADR-023). Q1=C ships the full §17.13 UX including `MobileTokenService` (tokens.py) — Ed25519 mint/verify with 24h TTL, JCS-canonical payload + base64url wire format, tamper-first signature verify, signing key loaded from `SecretsPort` under logical name `apex.approval.mobile_token.signing_key` (Restricted tier). `EscalationPolicy` (policy.py) scaffolds classification of all nine spec §14 kernel-wide Tier-2 triggers so any plugin can call it before `propose(...)` to force `HUMAN_REQUIRED`. `PraxisPlugin.build_praxis_descriptor()` now registers a second `Panel(id="praxis.approvals", slot=APPROVALS_QUEUE, priority=100, lazy_module="praxis/panels/ApprovalsQueuePanel")` in addition to the governance panel from §2.1. Zero new runtime deps: reuses `rfc8785>=0.1.4`, `cryptography>=49`, `aiosqlite>=0.20`. ADR-007 respected (Praxis imports no other plugin); ADR-008 respected (no MemoryPort writes at 2.2 — Storage seam only, MemoryPort will back durable audit at Stage 5).
- **DoD:** All three tiers exercised in `pytest -k apex_tiers`. **PASS** (82 APEX contract tests green: 28 in `test_apex_tiers.py` covering AUTONOMOUS · HUMAN_REVIEW · HUMAN_REQUIRED persistence + event fan-out + cadence + resolve cancels + double-resolve rejection + all-three-tiers DoD literal; 18 in `test_mobile_token.py` covering roundtrip + expiry + tamper + malformed + non-Ed25519 key rejection; 18 in `test_scheduler.py` covering FakeScheduler capture/ordering/idempotence + NullScheduler no-op + InProcessScheduler smoke; 18 in `test_policy.py` covering all nine §14 triggers + conservative-default behavior. Full suite 514/514 green; `make stage1-gate` PASS regression.

### 2.3 Phrouros anomaly detector — **LANDED**
- **Ports:** **TraceFeedPort** (new; `ports/trace_feed.py`), NotificationPort, ResourcePort, EventBusPort, FrontendContractPort. Deliberately NOT ObservabilityPort — that port is writer-only per ADR-025; Phrouros needs a reader seam.
- **Action:** `PhrourosPlugin` subscribes to TraceFeedPort at start; each `TraceEvent` is fanned into the detector tuple (first-match-wins). On anomaly the engine (a) publishes `phrouros.anomaly.detected` via EventBusPort with `producer_plugin="praxis"` (ADR-023), (b) calls `NotificationPort.deliver_algedonic()` directly (Q1=A — no APEX `propose()` at this stage), (c) calls `ResourcePort.allocate(ResourceKind.COMPUTE, Decimal("32"), intent="phrouros_diagnostics", priority_class=PriorityClass.PHROUROS_ANOMALY, requester="phrouros")` with `ResourceExhausted` → `enqueue()` fallback.
- **Detectors shipped:** real `LoopDetector` (sliding-window per `(trace_id, plugin, tool_name)`, default threshold=5 / window=30s, deque-backed, clears window after fire); skeletons `ModelSwapSloDetector` §172 · `StubDegradationDetector` §273 · `BusFactor1Detector` §613 all raising `DetectorNotImplementedError` (Q3=B).
- **Plugin descriptor:** `PhrourosPlugin` registers one `Panel(id="phrouros.trace", slot=PanelSlot.AGENT_TRACE, priority=100, lazy_module="phrouros/panels/AgentTracePanel")` (Q5=A).
- **New port:** `TraceFeedPort` with `InMemoryTraceFeedAdapter` primary (pure asyncio pub/sub, snapshot-list fan-out to survive mid-fan-out unsubscribe, `subscriber_count` accessor, idempotent `close`) + `LangfuseTraceFeedAdapter` stub (Stage 5). Q2=A locked.
- **Compliance:** ADR-007 respected (Phrouros imports zero other plugins — grep-verified in `engine.py` and `plugin.py`). ADR-008 respected (no MemoryPort writes at 2.3; audit persistence deferred to Stage 5). ADR-023 respected (every emitted envelope carries `producer_plugin="praxis"`).
- **DoD:** synthetic looping tool call (five identical `(plugin, tool_name)` events on one `trace_id` within a 30-second window) triggers algedonic alert + compute reservation. **Landed** — see `plugins/phrouros/tests/test_loop_detector.py::test_synthetic_looping_tool_call_triggers_phrouros_loop_alert_within_30s_build_sequence_2_3_dod` and `plugins/phrouros/tests/test_phrouros_engine.py::test_synthetic_loop_via_engine_emits_event_and_algedonic_and_reserves_compute_within_30s_build_sequence_2_3_dod`. Full pytest 569/569 green; `make stage1-gate` PASS.
- **Locked answers:** Q1=A · Q2=A · Q3=B · Q4=A · Q5=A — see **ADR-034**.

### 2.4 Stage-2 exit gate — **LANDED**
- **Ports:** TraceFeedPort (in), EventBusPort (bridge subscribe + audit publish), NotificationPort (via APEX HUMAN_REQUIRED cadence), APEX `ChangeApprovalProtocol` (via bridge). No new ports.
- **Action:** end-to-end unauthorized-action gate. `TektosSimulator` (test-only stub at `plugins/tektos/stub/`, Q6=A, deleted-or-superseded at Stage 3) publishes a `TraceEvent(plugin="tektos", tool_name=<denied>)` on TraceFeedPort. Phrouros engine fans event to detector tuple; new `UnauthorizedToolDetector` (Q4=A, hardcoded `frozenset[str]` allowlist, stateless per event, plugin-agnostic) fires → `UnauthorizedToolAnomaly` with new `AnomalyKind.UNAUTHORIZED_TOOL`. Engine publishes `phrouros.anomaly.detected` with `producer_plugin="praxis"` per ADR-023. `AnomalyBridge` (Q3=A / Q5=A) subscribed to that event on start translates envelope → `ChangeApprovalProtocol.propose(intention_id=f"anomaly:{anomaly_id}", tier=HUMAN_REQUIRED, proposing_domain="phrouros")` and publishes `praxis.escalation.proposed` audit event. APEX HUMAN_REQUIRED path fires `deliver_algedonic()` cadence → user notified.
- **Detectors active in the gate:** Stage-2.3 `LoopDetector` + new real `UnauthorizedToolDetector` (Q2=C — proves detector-tuple seam supports multiple concurrent real detectors).
- **Bridge location:** `plugins/praxis/apex/bridge.py::AnomalyBridge` — Praxis-internal peer service, composes `ChangeApprovalProtocol` directly (NOT owned by `PraxisPlugin`, matching ADR-033 decoupled-construction pattern). Idempotent `start()` / `stop()`; background `asyncio.Task` reads the `asyncio.Queue` returned by `EventBusPort.subscribe("phrouros.anomaly.detected")`; per-envelope errors logged and swallowed so one bad envelope cannot stop the escalator.
- **Tektos stub:** `plugins/tektos/stub/TektosSimulator` — plain dataclass composed with `TraceFeedPort`. No `PluginDescriptor`, no lifecycle, no AGENT_TRACE panel. Public API `simulate_unauthorized_call` / `simulate_authorized_call` / `simulate_loop`. Deleted or superseded at Stage 3 real Tektos MVP (Q6=A).
- **Compliance:** ADR-007 respected — bridge has zero `plugins.phrouros` imports (AST-verified in `test_anomaly_bridge.py::test_bridge_never_imports_phrouros`); bridge reads envelope payload by string keys only. ADR-008 respected — no MemoryPort writes at 2.4. ADR-023 respected — both anomaly and audit envelopes carry `producer_plugin="praxis"`.
- **DoD:** `test_unauthorized_tool_call_detected_and_escalated_and_user_notified_build_sequence_2_4_dod` in `plugins/tektos/tests/test_stage_2_4_exit_gate.py` — asserts (1) `phrouros.anomaly.detected` published, (2) `praxis.escalation.proposed` published by bridge, (3) APEX approval created with tier=HUMAN_REQUIRED, (4) `deliver_algedonic()` fires end-to-end. **Landed** — 6 Stage-2.4 tests green (1 DoD literal + 3 simulator sanity + 2 bridge extras); 13 `UnauthorizedToolDetector` tests green; 10 `AnomalyBridge` tests green. Full pytest **598/598** green; `make stage1-gate` PASS.
- **Locked answers:** Q1=A · Q2=C · Q3=A · Q4=A · Q5=A · Q6=A — see **ADR-035**.

---

## Stage 3 — Tektos (Coding Plugin) MVP (Weeks 3-4)

Reference: Spec §18. This is the largest single-plugin build.

### 3.1 Vendor OpenHands SDK — **LANDED**
- **Ports:** `LLMPort` (consumer of `generate_text` only — Q3=A minimal loop), `MemoryPort` (consumer of `query_temporal` + `write_event` with zero-trust `provenance` + `confidence`). No new ports.
- **Vendor mode:** PATTERN-VENDORED (Q2=A) — upstream `OpenHands/software-agent-sdk` (MIT) `Agent`/`Conversation` API shape rewritten in `plugins/tektos/agent.py::TektosAgent`. No upstream source copied into the tree. `PORTING_LEDGER.md` entry updated PLANNED → PATTERN-VENDORED with source URL, upstream commit, SPDX license, Kosmos location, port list, modifications.
- **Repo scope:** SDK repo only (Q1=A). `OpenHands/OpenHands` main-repo runtime patterns (workspace, event bus, sandboxed runtime) deferred to Stage 3.2 alongside MCP transport.
- **Agent surface:** `TektosAgent(llm, memory, subject?, model?, system_prompt?, confidence?, context_limit?)`. `send_message(content: str) -> turn_id` queues one user turn; `await run() -> TektosStep` executes one iteration (read prior via `query_temporal(TEKTOS_MEMORY_PREDICATE, limit=context_limit)` → assemble prompt (`[prior]` lines + pending content) → `await llm.generate_text(prompt, model, system)` → `await memory.write_event(subject, TEKTOS_MEMORY_PREDICATE, response, provenance="tektos_agent", confidence, attributes={turn_id, role, prompt_len, response_len})`). Second `run()` on same turn raises `TektosAgentNotStartedError`. `send_message` again yields a fresh turn id.
- **Locked constants:** `TEKTOS_AGENT_PROVENANCE="tektos_agent"` (every Tektos MemoryPort write), `TEKTOS_MEMORY_PREDICATE="tektos.turn.completed"` (canonical completed-turn predicate), default confidence `0.75` (Reflexion replaces at Stage 3.5). Domain-specific `TektosInvalidConfidenceError` fails fast for `<=0.0` or `>1.0` before the port-level guard fires.
- **Descriptor:** none at 3.1 (Q4=B). Spec §17.1 UI Parity Rule Phase-2 grandfathering applies; `FrontendContractPort` registration + `AGENT_TRACE` panel land at Stage 3.7 (spec-kit renderer).
- **Stub fate:** `plugins/tektos/stub/TektosSimulator` KEPT ALIVE through 3.1 (Q5=B). Stage-2.4 exit-gate DoD test (`test_unauthorized_tool_call_detected_and_escalated_and_user_notified_build_sequence_2_4_dod`) binds to it unchanged. Simulator deleted at Stage 3.2 when MCP tool calls emit real `TraceEvent`s through `TraceFeedPort`.
- **Compliance:** ADR-007 respected — AST-verified in `test_tektos_agent_imports_no_other_plugins_adr_007`; `plugins/tektos/agent.py` imports zero other plugin packages. ADR-008 respected — every `MemoryPort.write_event` carries `provenance="tektos_agent"` + confidence in `(0.0, 1.0]`; test `test_default_provenance_and_confidence_pass_port_guard` calls `validate_zero_trust_write` against the recorded write. ADR-022 respected — Tektos consumes `LLMPort.generate_text` verb only; every other verb on the fake port raises `NotImplementedError` to prove the surface. ADR-023 not exercised at 3.1 (no `EventBusPort` publish path yet; arrives at 3.2 with MCP tool calls).
- **DoD:** `test_tektos_agent_reads_and_writes_via_kosmos_ports_only_build_sequence_3_1_dod` in `plugins/tektos/tests/test_tektos_agent.py` — asserts (1) prior context read via `query_temporal`, (2) `generate_text` called once with prompt containing both prior + pending content, (3) `write_event` recorded with `provenance="tektos_agent"` + confidence 0.85 in `(0,1]` + locked predicate, (4) returned `TektosStep` records turn_id / response / memory_event_id / confidence / model. **Landed** — 18 Stage-3.1 contract tests green (1 DoD literal + 2 Protocol conformance + 4 construction guards + 1 run-without-send + 1 turn-id + 2 empty-memory / context_limit=0 + 1 second-run refuse + 1 multi-turn + 1 zero-trust passthrough + 3 locked constants + 1 message helpers + 1 ADR-007 AST). Full pytest **616/616** green; `make stage1-gate` PASS.
- **Locked answers:** Q1=A · Q2=A · Q3=A · Q4=B · Q5=B · Q6=A — see **ADR-036**.

### 3.2 Vendor MCP python-sdk + Playwright-MCP — **LANDED**
- **Ports:** new `MCPPort` at `ports/mcp.py` (async `initialize` / `list_tools` / `call_tool` / `close` + `is_healthy`; locked `MCP_PROTOCOL_VERSION="2024-11-05"`; value objects `MCPTool` / `MCPToolResult` / `MCPToolCallError` + `MCPServer` Protocol for in-process backends). Amends ADR-033 by promoting `ChangeApprovalTier` + a narrow propose-only `ApprovalGatewayPort` Protocol to `ports/approval.py` so non-Praxis plugins (Tektos at 3.2, others downstream) can gate actions through APEX without violating ADR-007; `plugins/praxis/apex/tier.py` re-exports for backwards compat. Existing ports consumed: `ApprovalGatewayPort` (Q3=A tool-call gating), `TraceFeedPort` (Q3=A trace-first emission before APEX gate), `MemoryPort` (per successful call, zero-trust write with `provenance="tektos_agent"` + confidence).
- **Vendor mode:** MCP python-sdk PATTERN-VENDORED (Q1=A) — upstream `modelcontextprotocol/python-sdk@a4f4ccd` (MIT) client-side verbs reimplemented as JSON-RPC-over-stdio in `adapters/mcp/stdio/adapter.py`; zero new pip deps. Playwright-MCP PATTERN-VENDORED (Q2=C) via `playwright_stdio_adapter()` factory that spawns `npx -y @playwright/mcp@latest` (Apache-2.0, upstream `microsoft/playwright-mcp@55679f5`). `PORTING_LEDGER.md` promoted both entries PLANNED → PATTERN-VENDORED.
- **Transport double (Q2=C):** both paths ship. `InProcessMCPAdapter(server=FakePlaywrightServer)` at `adapters/mcp/in_process/adapter.py` + `plugins/tektos/mcp/fake_playwright_server.py` — deterministic canned `browser_navigate` + `browser_snapshot` tools with `.invocations` recording for tests; drives the DoD literal + Stage-2.4 gate rewire. Real `StdioMCPAdapter` against `@playwright/mcp` is env-gated by `KOSMOS_STAGE_32_REAL_PLAYWRIGHT=1` in `plugins/tektos/tests/test_playwright_stdio_integration.py`, not part of `make stage1-gate`.
- **Agent surface:** `TektosAgent` gains `async call_tool(name, arguments, *, turn_id=None) -> TektosStep`. Flow: resolve tier via `resolve_tier(name)` against hardcoded `TEKTOS_TOOL_TIER_MAP` (fail-closed `DEFAULT_TIER=HUMAN_REQUIRED`) → publish `TraceEvent(plugin="tektos", tool_name=name, trace_id=turn_id, attributes={"tier", "arguments"})` on injected `TraceFeedPort` (trace-first — Phrouros observes every attempt) → `ApprovalGatewayPort.propose(intention_id=f"tektos.tool:{turn_id}:{name}", delta={"tool", "arguments"}, tier, proposing_domain="tektos", diff_preview={"tool"})` → AUTONOMOUS proceeds, HUMAN_REVIEW/HUMAN_REQUIRED raise `TektosToolCallPending(approval_id, tool_name)` → `MCPPort.call_tool(name, arguments)` → `MemoryPort.write_event(subject, predicate=TEKTOS_TOOL_PREDICATE, object=result.tool_name, provenance=TEKTOS_AGENT_PROVENANCE, confidence, attributes={turn_id, tool_name, tool_arguments, is_error, content_blocks, approval_id, tier})`. Returned `TektosStep` extended with optional `tool_name` / `tool_arguments` / `tool_result` / `approval_id`; the Stage-3.1 `send_message`+`run` LLM-only surface is unchanged.
- **Locked constants:** `MCP_PROTOCOL_VERSION="2024-11-05"` (`ports/mcp.py`), `TEKTOS_TOOL_PREDICATE="tektos.tool.completed"` (`plugins/tektos/mcp/tool_policy.py`), `TEKTOS_TOOL_TIER_MAP`: `browser_navigate`/`browser_snapshot`=AUTONOMOUS, `browser_click`/`browser_type`=HUMAN_REVIEW, `shell_exec`/`file_write`=HUMAN_REQUIRED. Retained from 3.1: `TEKTOS_MEMORY_PREDICATE="tektos.turn.completed"`, `TEKTOS_AGENT_PROVENANCE="tektos_agent"`, default confidence `0.75`.
- **Stub deletion (Q4=A):** `plugins/tektos/stub/` deleted per ADR-036 Q5=B trigger firing. Stage-2.4 exit-gate test rewired to construct a real `TektosAgent` with `InProcessMCPAdapter(FakePlaywrightServer)` + minimal `_FakeLLM` (raises on use) + `_FakeMemory` (records writes) + real `KernelChangeApprovalAdapter` + `InMemoryTraceFeedAdapter`; helpers `_emit_tool_call` / `_emit_tool_loop` invoke the real `call_tool` path and absorb `TektosToolCallPending` for tools the tier map fails-closed on. Assertions filter `apex.list_pending()` by `proposing_domain == "phrouros"` so Tektos's own tool-call proposals don't collide with Phrouros anomaly proposals. `TestTektosSimulator` class replaced by `TestTektosAgentTraceEmission`.
- **Compliance:** ADR-007 respected — `test_tektos_agent_imports_no_other_plugins_adr_007` still green; Tektos imports only from `ports.approval` / `ports.mcp` / `ports.trace_feed` / `ports.memory` / `ports.llm` at runtime. ADR-008 respected — every successful tool call writes with `provenance=TEKTOS_AGENT_PROVENANCE` + confidence in `(0,1]` + `is_error` / `approval_id` / `tier` in attributes. ADR-022 respected — LLM path unchanged. ADR-033 amended in-flight (tier + narrow gateway port promoted to `ports/approval.py`); the full `ChangeApprovalProtocol` stays inside Praxis. ADR-035 preserved — Stage-2.4 gate DoD literal test still passes end-to-end with real Tektos as the trace source. ADR-036 fulfilled at Q5=B trigger.
- **DoD:** `test_browser_navigate_end_to_end_autonomous` in `plugins/tektos/tests/test_tektos_mcp.py` — `TektosAgent.call_tool("browser_navigate", {"url": "https://example.invalid/"})` through AUTONOMOUS auto-approval, in-process fake Playwright MCP server, MemoryPort write with locked predicate + provenance + confidence, TraceEvent emitted before APEX gate, APEX APPROVED record persisted with `proposing_domain="tektos"`. **Landed** — 8 Tektos-MCP + 12 in-process adapter + 9 stdio adapter + 5 rewired Stage-2.4 gate tests green; full pytest **644/644** green + 2 env-gated Playwright skips; `make stage1-gate` PASS.
- **Locked answers:** Q1=A · Q2=C · Q3=A · Q4=A · Q5=A · Q6=A — see **ADR-037**.

### 3.3 Vendor aider repomap
- **Ports:** MemoryPort (per-file + per-run writes); no new port surface (Q2=A(revised) — Tektos-internal, ADR-023 envelope-first defer).
- **Action:** PATTERN-VENDOR aider's repomap algorithm (Apache-2.0) at `plugins/tektos/repomap/{policy,tags,rank,render,indexer}.py`. Only the 6 tree-sitter `.scm` query files (`python`, `javascript`, `typescript`, `rust`, `go`, `bash`) are copied verbatim from upstream `Aider-AI/aider@5dc9490bb35f` under `plugins/tektos/repomap/queries/` with `ATTRIBUTION.md`. Every indexed file emits one `MemoryPort.write_event(subject=<repo-relative-path>, predicate="tektos.repomap.indexed", provenance="aider-repomap", confidence=freshness)`; every run emits one `predicate="tektos.repomap.snapshot"` write with mean confidence + total files + rendered map + cache version.
- **Freshness formula (locked in `policy.py::compute_freshness_confidence`):** `confidence = max(REPOMAP_MIN_CONFIDENCE, 1.0 - min(1.0, age_days / REPOMAP_FRESHNESS_WINDOW_DAYS))` — linear decay over a 30-day window, clamped to `REPOMAP_MIN_CONFIDENCE=0.01` so old files remain queryable and ADR-008 zero-trust guard (`confidence > 0`) never trips.
- **Locked constants (`plugins/tektos/repomap/policy.py`):** `REPOMAP_PROVENANCE="aider-repomap"`, `REPOMAP_INDEXED_PREDICATE="tektos.repomap.indexed"`, `REPOMAP_SNAPSHOT_PREDICATE="tektos.repomap.snapshot"`, `REPOMAP_FRESHNESS_WINDOW_DAYS=30.0`, `REPOMAP_DEFAULT_MAP_TOKENS=1024`, `REPOMAP_CACHE_VERSION=4`, `REPOMAP_MIN_CONFIDENCE=0.01`.
- **New pip deps (7, gated under Stage 3.3 marker in `pyproject.toml`):** `tree-sitter>=0.24`, `tree-sitter-language-pack>=1.13`, `networkx>=3.4`, `scipy>=1.14` (networkx PageRank sparse backend), `grep-ast>=0.9`, `pygments>=2.18`, `diskcache>=5.6`.
- **Compliance:** ADR-007 respected — repomap is Tektos-internal, no cross-plugin imports. ADR-008 respected — every `MemoryPort.write_event` carries `provenance="aider-repomap"` and confidence in `(0, 1]`, enforced at call site by `ports.memory.validate_zero_trust_write`. ADR-023 respected — no new port surface introduced yet; `RepoMapPort` deferred until a second consumer exists. ADR-036/037 preserved.
- **DoD:** Tiered per Q5=C. Fast smoke (`make stage1-gate`): 500-file synthetic corpus with reference graph; asserts per-file writes (500 rows with provenance + confidence in `(0,1]`), exactly one snapshot write, and queryability via `MemoryPort.query_temporal("tektos.repomap.indexed", limit=100)` returning 100 rows. Env-gated 10k literal (`KOSMOS_STAGE_33_LARGE_CORPUS=1`): 10,000-file synthetic corpus, same contract, exercised on Colossus. Env-gated real-corpus (`KOSMOS_STAGE_33_REAL_CORPUS=1`): sparse-checkout of `cpython/Lib/json`, full pipeline end-to-end. **Landed** — 31 new repomap contract tests green (locked constants, freshness formula, tree-sitter tag extraction, PageRank ordering, tree-context render + token budget, indexer end-to-end + freshness fall-off + queryability, 500-file smoke); full pytest **675/675** green + 4 env-gated skips; `make stage1-gate` PASS.
- **Locked answers:** Q1=A · Q2=A(revised) · Q3=C · Q4=B · Q5=C · Q6=A — see **ADR-038**.

### 3.4 Bernstein Janitor spike test (ADR-004) — **DEFERRED to Phase 4 per ADR-039**
- **Status:** Deferred to a Stage 4.X slot in Phase 4 rollout planning. ADR-004 §Build-Order Placement literal: "scheduled immediately before Tektos Phase 4 begins." Prerequisites (`SandboxProvider` + `WorktreeProvider` in `ports/`, Postgres TaskState schema) named in ADR-004 §Evaluation Plan step 2 do not exist at Phase 3. See `docs/adrs/ADR-039-stage-3-4-and-3-5-defer.md`.
- **Phase 3 action:** none. Phase 3 advances directly from Stage 3.3 (LANDED) to Stage 3.6 (OpenSpec).

#### Original §3.4 scope (deferred)
- **Action:**
  1. Set up minimal Bernstein Janitor fixture
  2. Run identical repo cleanup task on both Bernstein Janitor and `local-agentic-loop-sample`
  3. Compare: correctness, speed, resource footprint, integration surface area
- **Decision rule:** **Adopt Bernstein Janitor iff fixture beats local-agentic-loop-sample**. Otherwise stay with local-agentic-loop-sample.
- **DoD (when executed at Phase 4):** ADR-004 status = `LOCKED` with benchmark evidence in `ops/benchmarks/bernstein-vs-lals-<yyyy-mm-dd>.md`.

### 3.5 Reflexion + Voyager port — **DEFERRED to Phase 5 per ADR-039**
- **Status:** Deferred to a Stage 5.X slot in Phase 5 rollout planning. §3.5 DoD literal ("Reflexion cycle logged in Langfuse") depends on Langfuse, which ADR-025 defers and ADR-034 §Stage 5 assigns to a primary `LangfuseTraceFeedAdapter` that lands at Stage 5. See `docs/adrs/ADR-039-stage-3-4-and-3-5-defer.md`.
- **Phase 3 action:** none.

#### Original §3.5 scope (deferred)
- **Action:** Wrap for Tektos self-improvement loop; memory writes must carry provenance
- **DoD (when executed at Phase 5):** Reflexion cycle logged in Langfuse.

### 3.6 OpenSpec (ADR-005 · ADR-040) — spec engine — **LANDED 2026-07-30**
- **DoD (literal):** Tektos accepts an OpenSpec doc and produces a plan — anchored by `pytest plugins/tektos/tests/test_openspec.py::test_produce_plan_on_add_dark_mode_fixture_writes_queryable_events_build_sequence_3_6_dod`.
- **Landed:** Pattern-vendored `Fission-AI/OpenSpec@2b3d368` (MIT) as stdlib-only Python parser at `plugins/tektos/openspec/{policy,models,parser,plan}.py` + real fixture at `plugins/tektos/tests/fixtures/openspec/add-dark-mode/`; every parse emits a `tektos.openspec.artifact.parsed` MemoryPort event and `produce_plan()` emits a `tektos.openspec.plan.produced` MemoryPort event with `confidence` = mean per-artifact completeness (clamped to `OPENSPEC_MIN_CONFIDENCE=0.05`).
- **Port surface:** Tektos-internal only per ADR-040 Q2 (ADR-023 envelope-first defer). No new `ports/*.py`. `DataPort` (ADR-028 JSON-LD export) untouched.
- **Tests:** 30 new `plugins/tektos/tests/test_openspec.py` (locked constants, completeness formula, fence-mask semantics, section iteration, artifact parsing, delta spec ADDED/MODIFIED/REMOVED, task parsing + fenced-block filtering, directory walk + required-artifact enforcement, DoD literal, minimal-artifact case, ADR-007 AST guard, ADR-008 zero-trust passthrough). 705 total green + 4 env-gated skips. `make stage1-gate` PASS.
- **See:** ADR-040, ADR-005 (STATUS AMENDMENT 2026-07-30), PORTING_LEDGER “OpenSpec — PATTERN-VENDORED”.

### 3.7 spec-kit — plan renderer (LANDED)
- **DoD (literal):** Plans render as user-approvable UI cards — anchored by `pytest plugins/tektos/tests/test_plan_renderer.py::test_produce_plan_renders_as_approvable_card_via_frontend_contract_port_build_sequence_3_7_dod`.
- **Landed:** Pure-Python renderer at `plugins/tektos/renderer/{__init__,policy,models,project}.py` over the Stage 3.6 `Plan` dataclass (Q1=B no upstream vendored); first Tektos `PluginDescriptor` at `plugins/tektos/plugin.py` (`TektosPlugin` + `build_tektos_descriptor()` mirroring `plugins/phrouros/plugin.py` bootstrap shape) firing ADR-036 Q4=B `PluginDescriptor` deferral trigger; every card proposes through `ApprovalGatewayPort.propose(...)` at fail-closed `ChangeApprovalTier.HUMAN_REVIEW` (ADR-037 default) and emits a `tektos.plan.card_rendered` MemoryPort event with `provenance="tektos_plan_renderer"` + confidence `clamp(plan.mean_completeness, 0.05, 1.0)`; `Panel(id="tektos.plan_approvals", slot=APPROVALS_QUEUE, priority=90, lazy_module="tektos/panels/PlanApprovalPanel")` sits BELOW Praxis `praxis.approvals` at priority 100 (ADR-033 §Q1=C). `ui_parity_status=IN_PROGRESS` at 3.7 → COMPLIANT at Stage 3.11.
- **Port surface:** No new port — `FrontendContractPort` (ADR-031) reused envelope-first per ADR-023 / ADR-038 / ADR-040 defer pattern.
- **Tests:** 28 new `plugins/tektos/tests/test_plan_renderer.py` (locked constants, `clamp_card_confidence` bounds + non-finite rejection, `project_plan_to_card` delta aggregation + confidence clamp + tier round-trip + input validation, `render_and_gate_plan_card` HUMAN_REVIEW fail-closed + locked provenance/predicate + deterministic intention_id `tektos.plan.<change_id>` + zero-trust propagation + empty approval_id rejection, `TektosPlugin.start`/`stop` idempotency + descriptor shape + Tektos-below-Praxis priority contract, ADR-007 AST guard, signature stability, end-to-end DoD literal on committed `add-dark-mode` fixture). 733 total green + 4 env-gated skips. `make stage1-gate` PASS.
- **See:** ADR-041, ADR-036 (STATUS AMENDMENT 2026-07-30 for Q4=B trigger firing), ADR-005, PORTING_LEDGER “spec-kit — PLANNED” (ADR pointer updated to `ADR-005 · ADR-041`).

### 3.8 Pier eval harness (LANDED)
- **DoD (literal):** Every Tektos plan runs through Pier before user review — anchored by `pytest plugins/tektos/tests/test_pier_eval.py::test_tektos_plan_runs_through_pier_before_user_review_build_sequence_3_8_dod`.
- **Landed:** Tektos-internal Pier eval subsystem at `plugins/tektos/eval/{__init__,policy,models,harness}.py` invoking `datacurve-pier==0.3.0` (Apache-2.0; upstream `datacurve-ai/pier@fefa7475a32bb05271abdea378e8083c83eb5c35`) as a subprocess through `pier run` — no in-process import, so the fast unit tier runs without the package installed. Kernel runner `scripts/pier_eval.py` (`--task ... --agent ... --env docker`) plus `Makefile eval-gate` target. One committed Harbor fixture `plugins/tektos/eval/tasks/tektos-plan-execution-smoke/` (rename `greet_old` → `greet` task with three verifier assertions). Every trial emits exactly one `tektos.eval.trial_completed` MemoryPort event with `provenance="pier-eval-harness"`, `subject="<change_id?>::<task_name>::<trial_id>"`, `object=outcome.value`, `confidence=1.0` on PASS / `0.0` on FAIL or ERROR, and `attributes` carrying `outcome`, `verifier_exit_code`, `trajectory_dir`, `pier_env`, `pier_version`, `pier_commit`, `peak_context_tokens`, `llm_call_count`, and optional `change_id`. Docker-only `PierEnv` per Colossus local-first invariant. Verdicts are **advisory only** (ADR-042 Q7=B, revised from Q7=A): plan cards stay in `HUMAN_REVIEW` and the user is the sole approver — Q7=B was chosen after the ADR-007 mechanism review flagged that no Tektos-only path to `plugins.praxis.apex.protocol.ChangeApprovalProtocol.resolve()` exists without either violating ADR-007 (importing Praxis) or doubling Stage 3.8 scope (adding a Praxis event-bus subscriber) or reversing ADR-037 (widening `ApprovalGatewayPort` with `resolve`). Automated approval deferred to a future ADR (candidate ADR-043 event-driven auto-approve) if experience shows manual review is a bottleneck.
- **Port surface:** No new port — envelope-first per ADR-023, matching ADR-038 / ADR-040 / ADR-041 defer pattern. Verdicts flow through the existing `MemoryPort`.
- **Tests:** 14 new fast unit tests in `plugins/tektos/tests/test_pier_eval.py` (locked policy constants, `confidence_for_outcome` bounds + `TypeError` on non-enum, `PierEnv(PIER_DEFAULT_ENV) is PierEnv.DOCKER`, `TrialVerdict.to_attributes` JSON round-trip with no enum leakage, `run_pier_trial` PASS + FAIL + non-Harbor-directory rejection using a fake `pier` CLI shim, `record_pier_verdict` locked-shape write with `change_id` in subject + attributes, FAIL + ERROR verdicts use `PIER_MIN_CONFIDENCE=0.0`, `run_and_record_trial` records an ERROR event before re-raising `PierTrialFailure`, committed Harbor fixture shape assertion, ADR-007 AST guard `test_eval_subsystem_imports_no_other_plugins_adr_007`, DoD literal end-to-end) plus 1 env-gated real-Pier tier gated by `KOSMOS_STAGE_38_REAL_PIER=1` (requires Docker daemon + `pip install -e '.[eval]'`). 747 total green + 5 env-gated skips. `make stage1-gate` PASS.
- **See:** ADR-042 (Ratified v25, authoritative), ADR-006 (STATUS AMENDMENT 2026-07-30 — superseded), PORTING_LEDGER "Pier eval harness — VENDORED (dev dep, Stage 3.8)".

### 3.9 DeepSWE corpus subset (LANDED)
- **DoD (literal):** Benchmark run recorded — anchored by `pytest plugins/tektos/tests/test_deepswe_corpus.py::test_deepswe_subset_benchmark_run_recorded_build_sequence_3_9_dod`.
- **Landed:** DeepSWE corpus subset subsystem at `plugins/tektos/eval/corpora/deepswe/{__init__,manifest.toml,policy,models,loader,harness}.py`. **Manifest-only vendoring** per ADR-007-DeepSWE STATUS AMENDMENT 2026-07-30 — no upstream source is copied; the pinned `manifest.toml` records the upstream commit `e016041a6ccf8da29906afc9a3f5a8df940a1f78` (Apache-2.0, 2026-07-22) plus 5 tasks (3 Python + 2 TypeScript) chosen deterministically by task-id sort from the 113-task corpus, with per-task upstream repo + base commit + SPDX verified via the GitHub API. Corpus is hydrated on demand into a git-ignored `.eval-cache/deepswe/<commit>/tasks/` via `scripts/deepswe_fetch.py` (`git clone --filter=blob:none --no-checkout && git checkout <commit>`) and executed via `scripts/deepswe_run.py --agent nop --env docker`, both wired to `Makefile deepswe-fetch` / `deepswe-gate` targets. Each subset task runs through Stage 3.8's `run_pier_trial`, outcomes are aggregated into a single `CorpusRunSummary`, and exactly one aggregate `tektos.eval.corpus_run_completed` MemoryPort event is written by `record_corpus_run` with `provenance="deepswe-eval-corpus"`, `subject="deepswe::<upstream_commit>::<sample_seed>::<run_id>"`, `object="<n_pass>/<n_total>"`, `confidence=n_pass/n_total` (clamped to `[0.0, 1.0]`, 0.0 when `n_total=0`), and `attributes` carrying `run_id`, `corpus`, `upstream_commit`, `sample_seed`, `subset_task_ids`, `outcomes`, per-task `trial_event_ids`, `n_pass`/`n_fail`/`n_error`/`n_total`, `pier_version`, `pier_env`, `started_at`, `finished_at`. Per-trial `tektos.eval.trial_completed` events from Stage 3.8 remain unchanged — the aggregate event is additive.
- **Port surface:** No new port — envelope-first per ADR-023, matching ADR-038 / ADR-040 / ADR-041 / ADR-042 defer pattern. All writes go through the existing `MemoryPort`.
- **Deferrals recorded via ADR STATUS AMENDMENT:** ADR-007-DeepSWE DoD clause 3 (context-rot regression cross-check) is DEFERRED until a Kosmos-native context-rot regression suite lands as its own stage — v20.2 §3 is a pre-v25 reference and v25 has not yet cut a replacement suite. Unblock condition documented inline in the ADR STATUS AMENDMENT block.
- **Tests:** 18 new fast unit tests in `plugins/tektos/tests/test_deepswe_corpus.py` (locked policy constants, `corpus_run_confidence` bounds + `TypeError` on non-int + `ValueError` on negative / pass>total, committed manifest loads 5 tasks 3py/2ts, every subset entry has permissive SPDX, subset ids unique + sorted deterministically, loader rejects missing file + non-permissive SPDX + subset-size mismatch + upstream-commit mismatch, `build_corpus_run_summary` outcome counts + length mismatch + unknown verdict string, `CorpusRunSummary.to_attributes` JSON round-trip, `record_corpus_run` locked-shape write with a fake MemoryPort + all-PASS gets `DEEPSWE_MAX_CONFIDENCE` + all-FAIL gets `DEEPSWE_MIN_CONFIDENCE`, ADR-007 AST guard `test_deepswe_corpus_imports_no_other_plugins_adr_007`, DoD literal end-to-end wiring manifest → fake Pier CLI shim → aggregate summary → single MemoryPort event with `object="3/5"` and `confidence=0.6`) plus 1 env-gated real-DeepSWE tier gated by `KOSMOS_STAGE_39_REAL_DEEPSWE=1` (requires Docker daemon + `datacurve-pier` installed + network access on first fetch). 765 total green + 6 env-gated skips. `make stage1-gate` PASS.
- **See:** ADR-007-DeepSWE (Ratified v25, STATUS AMENDMENT 2026-07-30 pins scope + defers DoD clause 3), PORTING_LEDGER "DeepSWE corpus subset — VENDORED (manifest-only, Stage 3.9)".

### 3.10 docling — document ingestion (LANDED 2026-07-30 04:20 EDT — ADR-044)
- **DoD:** PDF/DOCX/HTML → structured JSON-LD via DataPort.
- **Landed:** Tektos-internal docling ingest subsystem at `plugins/tektos/ingest/{__init__,policy,models,harness}.py` PATTERN-VENDORING `docling==2.116.0` (MIT; upstream `docling-project/docling@ba8251e9cda84bab44cebe3b884119d3f50cb12a`) as a dev-only optional dep — docling is a **lazy** import inside `resolve_default_converter_factory()`, so the Stage-1 gate runs with docling uninstalled. Kernel runner `scripts/docling_ingest.py` (`--source <path> --output <dir>`) + `Makefile ingest-doc` target. Committed micro-fixtures at `plugins/tektos/tests/fixtures/docling/{sample.pdf, sample.docx, sample.html}` (hand-rolled minimal PDF/DOCX + trivial HTML — total ~2 KB, no external assets, no network). Every successful ingest writes exactly one canonical JSON-LD envelope through `DataPort.export_canonical` with locked shape: `record_type="tektos.ingest.document"`, `provenance="tektos-docling-ingest"`, `confidence=1.0` (`DOCLING_SUCCESS_CONFIDENCE`), default `pii_tier=PIITier.INTERNAL` (caller may override to `SENSITIVE` or `RESTRICTED`; RESTRICTED routes under `{root}/restricted/{record_type}/` per Spec §147), `source_citation.upstream_commit=ba8251e9cda84bab44cebe3b884119d3f50cb12a`, `source_citation.upstream_license="MIT"`, `attributes={source_extension, docling_dict_keys, docling_markdown_length, converter_class, run_id, ingested_at, page_count?}`, `payload={docling_dict, docling_markdown}`. Extension whitelist `DOCLING_SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".html"})` enforced **before** the converter is resolved, so unsupported inputs never touch docling. Any failure (unsupported ext, missing source, docling raising) raises `DoclingIngestFailure` and **no** envelope is written (fail-closed per ADR-044 Q4=A). No new port surface — envelope-first per ADR-023 defer pattern proven at ADR-038/040/041/042. No plugin↔plugin coupling.
- **Files touched:** `plugins/tektos/ingest/__init__.py` (NEW), `plugins/tektos/ingest/policy.py` (NEW; locked constants), `plugins/tektos/ingest/models.py` (NEW; `DoclingSource`, `DoclingRun`, `DoclingIngestFailure`), `plugins/tektos/ingest/harness.py` (NEW; `ingest_document`, `record_ingest_envelope`, `run_and_record_ingest`, `resolve_default_converter_factory`), `plugins/tektos/tests/test_docling_ingest.py` (NEW; 26 fast unit tests + 1 env-gated real-docling tier), `plugins/tektos/tests/fixtures/docling/sample.{pdf,docx,html}` (NEW; committed micro-fixtures), `scripts/docling_ingest.py` (NEW; kernel runner), `Makefile` (new `ingest-doc` target + `.PHONY`), `pyproject.toml` (adds `[project.optional-dependencies] ingest = ["docling==2.116.0"]` + `plugins.tektos.ingest` in setuptools packages), `docs/adrs/ADR-044-tektos-docling-document-ingestion.md` (NEW), `docs/Kosmos-Build-Spec-v25.md` §17 (ADR-044 row) + §18.5 (docling row license `Apache-2.0` → `MIT`), `docs/adrs/README.md` (ADR-044 row), `docs/PORTING_LEDGER.md` (docling `PLANNED` → `VENDORED (dev dep, Stage 3.10)` with commit/license/port/ADR/logged fields).
- **Tests:** 26 new fast unit tests in `plugins/tektos/tests/test_docling_ingest.py` (locked policy constants, `confidence_for_success` bounds + `TypeError` on non-bool, `DOCLING_SUPPORTED_EXTENSIONS` frozen membership + immutability, `DoclingSource.is_supported` case-insensitive extension guard + missing-file rejection, `DoclingRun.to_attributes` JSON round-trip with no enum leakage, `ingest_document` PASS path against fake docling shim + `DoclingIngestFailure` on unsupported extension + missing source + docling raising + non-dict `export_to_dict` return + non-str `export_to_markdown` return, `record_ingest_envelope` locked-shape write against a fake `DataPort` + provenance/confidence/pii_tier passthrough + INTERNAL default + SENSITIVE override + RESTRICTED override routes to `restricted/` prefix + `source_citation.upstream_commit`/`upstream_license` populated, `run_and_record_ingest` end-to-end wiring on all three committed fixtures + writes exactly one envelope per source + failure path records **no** envelope, kernel runner `scripts/docling_ingest.py` end-to-end against fake shim + `--output` directory populated + exit-code 0 on success + exit-code 1 on `DoclingIngestFailure`, committed fixtures shape assertion (all three fixtures present + non-zero-byte + correct extensions), ADR-007 AST guard `test_docling_ingest_imports_no_other_plugins_adr_007` walks every `.py` under `plugins/tektos/ingest/` and rejects any `import plugins.<other>`, DoD literal `test_pdf_docx_html_ingest_produces_structured_jsonld_via_dataport_build_sequence_3_10_dod` — feeds all three committed fixtures through `run_and_record_ingest`, asserts three DataPort envelopes emitted with `@type="CanonicalExport"`, `record_type="tektos.ingest.document"`, canonical hash present, and payload carrying both `docling_dict` and `docling_markdown`) plus 1 env-gated real-docling tier gated by `KOSMOS_STAGE_310_REAL_DOCLING=1` (requires `.venv/bin/pip install -e '.[ingest]'`). 791 total green + 7 env-gated skips. `make stage1-gate` PASS.
- **See:** ADR-044 (Ratified v25), PORTING_LEDGER "docling — VENDORED (dev dep, Stage 3.10)".

### 3.11 Tektos UI (FrontendContractPort) (LANDED 2026-07-30 05:14 EDT — ADR-045)
- **DoD:** Plan → Approve → Execute → Diff flow visible in kernel dashboard.
- **Landed:** Tektos UI HTMX dashboard at `plugins/tektos/ui/{__init__,policy,models,executor,templates,server}.py` — FastAPI-backed dashboard (Q1a=A) serving vendored HTMX 2.0.4 (`plugins/tektos/ui/htmx.min.js` 50917 B, sha256 `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447`, upstream `bigskysoftware/htmx@b82cf843e47e575dd8c2ad8fee547d8e2c3bb87f`, license `0BSD`) at `/htmx.min.js` on `127.0.0.1:8765` (Q1c=A). Six-route surface (Q1e=A): `GET /`, `GET /plan/{approval_id}`, `POST /plan/{approval_id}/approve`, `POST /plan/{approval_id}/execute`, `POST /plan/{approval_id}/diff`, `GET /healthz`, plus static `GET /htmx.min.js`. No auth (Q1g=A — single-user local-first invariant). Fast unit tier uses FastAPI TestClient (Q1d=A) so DoD literal never binds a real port. Reuses ADR-041 `Panel(id="tektos.plan_approvals", slot=APPROVALS_QUEUE)` (Q2=A) — flips `ui_parity_status` IN_PROGRESS → COMPLIANT by adding one `Route(path="/tektos", label="Tektos", icon="📐", lazy_module="tektos/pages/DashboardPage")` on the Tektos descriptor so `_derive_parity(routes ∧ panels)` returns COMPLIANT. Vendor-neutral `NopExecutor` implements `ExecutorPort` Protocol (Q3=A) so `/execute` is a real HTTP surface without wiring a live agent at 3.11. Pure-stdlib `difflib.unified_diff` renders `/diff` (Q4=A — no new dep). Three per-transition MemoryPort events (Q5=A) with locked shape `subject="<change_id>::<approval_id>"`, `provenance="tektos_ui"`, `confidence=1.0`: predicates `tektos.plan.approved` / `tektos.plan.executed` / `tektos.plan.diff_rendered`. All Tektos plans stay at `HUMAN_REVIEW` (Q6=A — no tier changes at 3.11). Two-tier tests (Q7=B): fast unit tier default + env-gated interactive tier `KOSMOS_STAGE_311_INTERACTIVE=1` spawning `scripts/tektos_ui.py` via uvicorn. New `ApprovalResolverPort` in `ports/approval.py` (Q_res_1=B, promoted from intra-Praxis `ChangeApprovalProtocol`; ADR-007 respected — downstream plugins depend only on `ports.approval`) with port-level `list_pending(*, proposing_domain=None)` filter; `PraxisApprovalResolverAdapter` at `adapters/approval_resolver/praxis/adapter.py` wraps `KernelChangeApprovalAdapter` and applies filter client-side. UI approvals set `resolved_by="tektos_ui"` (Q_res_2=B — audit trail distinguishes UI-driven resolutions from CLI/API). `ApprovalRecord`+`ApprovalStatus` promoted from `plugins/praxis/apex/models.py` to `ports/approval.py` (Promotion=A); `plugins.praxis.apex.models` re-exports for backward compat.
- **Files touched:** `ports/approval.py` (NEW; `ChangeApprovalTier`, `ApprovalStatus`, `ApprovalRecord`, `ApprovalGatewayPort`, `ApprovalResolverPort`), `plugins/praxis/apex/models.py` (backward-compat re-exports), `plugins/tektos/ui/__init__.py` (NEW; public surface), `plugins/tektos/ui/policy.py` (NEW; locked constants), `plugins/tektos/ui/models.py` (NEW; `ExecutionResult`, `DiffRender`), `plugins/tektos/ui/executor.py` (NEW; `ExecutorPort`, `NopExecutor`, `render_unified_diff`, `compute_diff_sha256`), `plugins/tektos/ui/templates.py` (NEW; HTML fragment helpers), `plugins/tektos/ui/server.py` (NEW; `build_tektos_ui_app`), `plugins/tektos/ui/htmx.min.js` (NEW; vendored 50917 B), `plugins/tektos/plugin.py` (adds one `Route(path="/tektos", ...)` to `build_tektos_descriptor()`), `plugins/tektos/tests/test_plan_renderer.py` (Route+COMPLIANT parity updates + fake `_derive_parity`), `plugins/tektos/tests/test_tektos_ui.py` (NEW; 24 fast unit tests + 1 env-gated interactive tier + DoD literal anchor), `adapters/approval_resolver/__init__.py` (NEW), `adapters/approval_resolver/praxis/__init__.py` (NEW), `adapters/approval_resolver/praxis/adapter.py` (NEW; `PraxisApprovalResolverAdapter` wraps `KernelChangeApprovalAdapter`), `adapters/approval_resolver/praxis/test_contract.py` (NEW; 5 contract tests), `scripts/tektos_ui.py` (NEW; uvicorn runner for interactive tier), `Makefile` (new `ui-serve` target + `.PHONY`), `pyproject.toml` (adds `[project.optional-dependencies] ui = ["fastapi>=0.115", "uvicorn>=0.32", "httpx>=0.27"]`, adds `plugins.tektos.ui` + `adapters.approval_resolver` + `adapters.approval_resolver.praxis` to setuptools packages, adds `[tool.setuptools.package-data] "plugins.tektos.ui" = ["htmx.min.js"]`), `docs/adrs/ADR-045-tektos-ui-htmx-dashboard.md` (NEW), `docs/adrs/ADR-041-tektos-plan-renderer-and-first-plugin-descriptor.md` (STATUS AMENDMENT: ui_parity_status IN_PROGRESS → COMPLIANT), `docs/Kosmos-Build-Spec-v25.md` §17 (ADR-045 row), `docs/adrs/README.md` (ADR-045 row), `docs/PORTING_LEDGER.md` (htmx + fastapi + uvicorn VENDORED rows).
- **Locked constants (`plugins/tektos/ui/policy.py`):** `TEKTOS_UI_PROVENANCE="tektos_ui"`, `TEKTOS_UI_RESOLVED_BY="tektos_ui"`, `TEKTOS_UI_HOST="127.0.0.1"`, `TEKTOS_UI_PORT=8765`, `TEKTOS_UI_PLAN_APPROVED_PREDICATE="tektos.plan.approved"`, `TEKTOS_UI_PLAN_EXECUTED_PREDICATE="tektos.plan.executed"`, `TEKTOS_UI_PLAN_DIFF_RENDERED_PREDICATE="tektos.plan.diff_rendered"`, `TEKTOS_UI_SUCCESS_CONFIDENCE=1.0`, `TEKTOS_UI_HTMX_VERSION="2.0.4"`, `TEKTOS_UI_HTMX_UPSTREAM_COMMIT="b82cf843e47e575dd8c2ad8fee547d8e2c3bb87f"`, `TEKTOS_UI_HTMX_UPSTREAM_LICENSE="0BSD"`, `TEKTOS_UI_HTMX_SHA256="e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447"`, `TEKTOS_UI_ROUTE_PATH="/tektos"`, `TEKTOS_UI_ROUTE_LABEL="Tektos"`, `TEKTOS_UI_ROUTE_ICON="📐"`, `TEKTOS_UI_ROUTE_LAZY_MODULE="tektos/pages/DashboardPage"`, `TEKTOS_UI_INDEX_PATH="/"`, `TEKTOS_UI_PLAN_DETAIL_PATH="/plan/{approval_id}"`, `TEKTOS_UI_PLAN_APPROVE_PATH="/plan/{approval_id}/approve"`, `TEKTOS_UI_PLAN_EXECUTE_PATH="/plan/{approval_id}/execute"`, `TEKTOS_UI_PLAN_DIFF_PATH="/plan/{approval_id}/diff"`, `TEKTOS_UI_HEALTHZ_PATH="/healthz"`, `TEKTOS_UI_HTMX_JS_PATH="/htmx.min.js"`. `TEKTOS_UI_PROPOSING_DOMAIN="tektos"` in `server.py`.
- **Tests:** 815 total green + 8 env-gated skips (24 new UI fast unit tests + 1 env-gated interactive tier + 5 adapter contract tests + 3 updates to `test_plan_renderer.py`). DoD literal anchor `pytest plugins/tektos/tests/test_tektos_ui.py::test_plan_approve_execute_diff_flow_visible_in_kernel_dashboard_build_sequence_3_11_dod`.
- **See:** ADR-045 (Ratified v25), ADR-041 (STATUS AMENDMENT 2026-07-30 — ui_parity_status IN_PROGRESS → COMPLIANT), PORTING_LEDGER "htmx — VENDORED (Stage 3.11, ADR-045)", "fastapi — VENDORED (Stage 3.11, ADR-045)", "uvicorn — VENDORED (Stage 3.11, ADR-045)".

### 3.12 Stage-3 exit gate (LANDED 2026-07-30 05:47 EDT — ADR-046)
- **Scope frozen:** Tektos completes one non-trivial refactor on a real Kosmos file end-to-end via the full 3.1→3.2→3.3→3.6→3.7→3.11 pipeline (3.8 Pier + 3.10 docling deferred to Phase 4 per ADR-039-adjacent scope). **DoD:** Refactor commit passes ruff + bandit + pytest.
- **Landed:** Refactor target `plugins/tektos/ui/templates.py` (Q1=A) via extract-method (Q2=A) — new `_escape_record_fields(record) -> tuple[str,str,str,str]` helper unifies four `html.escape(str(...))` calls previously duplicated across `render_pending_row` + `render_plan_detail`; 24/24 pre-existing UI tests pass over the refactored surface. Pipeline depth Q3=B fires real 3.1 TektosAgent → 3.2 MCP `file_write` gate raises `TektosToolCallPending` fail-closed → 3.3 repomap indexer surfaces `_escape_record_fields` in `rendered_map` → 3.6 openspec `produce_plan` on committed fixture → 3.7 plan-renderer + APEX HUMAN_REVIEW propose → 3.11 TestClient exercises `/plan/{approval_id}/approve|execute|diff`. Q3.1=C two-tier LLM: fast tier uses Interp-2 human-authored deterministic instruction so the DoD passes on any machine; interactive tier `KOSMOS_STAGE_312_INTERACTIVE=1` uses Interp-1 real Ollama on Colossus. Q4=A `bandit>=1.7` added to `[project.optional-dependencies] dev` + `[tool.bandit]` config (`exclude_dirs=[".venv","build","dist","__pycache__"]`, `skips=["B101"]`). Q5=A new `scripts/stage3_gate.py` mirrors `scripts/stage1_gate.py` shape (5 pass criteria: BUILD_LOG entry, refactor commit SHA discoverable by `git log --grep="Stage 3.12 · Tektos refactor · extract-method"`, ruff clean on refactor target, bandit clean, full pytest green); `Makefile` gains `stage3-gate` target. Q6=A two-commit shape: commit 1 authored `Tektos <tektos@kosmos.local>` refactor-only with subject literal `Stage 3.12 · Tektos refactor · extract-method`; commit 2 rmholston420 with DoD test + gate + ADR + fanout + logs; tag `stage-3-12-complete` on commit 2. Q7=A fake Pier (not exercised). Q8=A FastAPI `TestClient` only for 3.11 UI touchpoint. Q9=A single composite ADR-046. Q10=A DoD literal test name `test_tektos_refactors_real_kosmos_file_end_to_end_passes_ruff_bandit_pytest_build_sequence_3_12_dod`. Fixture change committed at `plugins/tektos/tests/fixtures/openspec/refactor-tektos-ui-templates-extract-escape-helpers/{proposal.md, tasks.md, specs/tektos-ui-templates/spec.md}`.
- **Tests:** 825 total green + 9 env-gated skips (5 new fast tests + 1 env-gated interactive tier). DoD literal anchor `pytest plugins/tektos/tests/test_stage_3_12_exit_gate.py::test_tektos_refactors_real_kosmos_file_end_to_end_passes_ruff_bandit_pytest_build_sequence_3_12_dod`.
- **See:** ADR-046 (Ratified v25), PORTING_LEDGER "bandit — VENDORED (dev dep) (Stage 3.12, ADR-046)".

---

## Stage 4 — Gnosis (Knowledge) — Absorbs Knowsys (ADR-016) (Weeks 5-6)

### 4.1 Knowsys → Gnosis merge — **LANDED 2026-07-30 (commit follows)**
- **Outcome:** ADR-016 flipped to **LOCKED**. `plugins/knowsys/` was never ported from Rigpa-LMS into Kosmos (verified via repo scan) — mirrors the ADR-013 lock-in pattern (loser rejected at the source of choice, not by deleting non-existent code).
- **DoD literal met:**
  - `grep -rniE "^(from|import).*knowsys" --include="*.py"` → zero results.
  - ADR-016 status line + spec §17 row + `docs/adrs/README.md` index row + `docs/Kosmos-ADRs-Bundle.md` mirror all read **LOCKED**.
- **Cleanup shipped alongside lock-in:**
  - `adapters/observability/otel_stack/test_contract.py` — test span name `plugin.knowsys.index` → `plugin.gnosis.index` (2 spots) + `plugin="knowsys"` context-binding attributes → `plugin="gnosis"` (2 spots).
  - `plugins/tektos/tests/test_tektos_agent.py` — dropped `"plugins.knowsys"` from the `forbidden_prefixes` tuple (would forbid a non-existent module; Gnosis will become a valid import in Stage 4.4 so we deliberately do NOT swap in `"plugins.gnosis"`).
- **Deliberately unchanged:** Rigpa Knowsys export subsystem remains VENDORED-pattern-only in `PORTING_LEDGER.md` §DataPort per ADR-028 — pattern reference, not a Kosmos plugin.
- **Test status:** fast tier 825 passed + 9 skipped (unchanged from baseline).
- **Next:** Stage 4.2 (Graphiti tuning — largely landed at Stage 1.8 per ADR-027 Q1=A).

### 4.2 Graphiti temporal-index tuning + benchmarks — **LANDED** (2026-07-30, ADR-047)
- **Ports:** MemoryPort, VectorPort
- **Note:** graphiti-core is already **VENDORED at Stage 1.8** (ADR-027 Q1=A). Stage 4.2 delivered tuning + `PORT_CONTRACTS.md` metrics: real DozerDB/Graphiti/AMG backends replaced Stage-1.8 stubs; three corpora exercise schema drift + edge-type churn; local Ollama (`qwen3-coder` + `nomic-embed-text`) replaces hosted OpenAI as Graphiti's LLM/embedder/cross-encoder.
- **Action:** Real backends + Hybrid-tier corpora + Compose service + `docs/PORT_CONTRACTS.md` — see ADR-047.
- **DoD (met):** Three corpora ingest via `record_event`; every DoD-asserted `TemporalQuery` finds its `expected_event_ids` and rejects its `forbidden_event_ids` on the always-green fast tier; live-tier first run 37 passed / 137.29 s on Colossus with metrics recorded in `docs/PORT_CONTRACTS.md`.
- **Tag:** `stage-4-2-complete`.

### 4.3 Agent Memory Guard latest release check — **LANDED** (2026-07-30, ADR-048)
- **Ports:** MemoryPort (`AmgPolicy` write-time filter)
- **Action:** Checked upstream https://github.com/OWASP/www-project-agent-memory-guard/releases — v0.3.0 released 2026-06-10 (MCP server, CLI scanner, ML injection detector, GitHub Action, LlamaIndex + CrewAI integrations, Prometheus exporter, `Policy.tiered()` preset with default memory-class taxonomy, `SecurityEvent.source_class`/`receipt_uri`/`retire_if`). v0.3.0 public API is a strict superset of v0.2.2 (all new `MemoryGuard.write` kwargs optional; `Policy.strict()` still present). Adopted via ADR-048: `pyproject.toml` pin bumped `agent-memory-guard==0.2.2` → `==0.3.0`; concrete wrapper renamed `AmgV02Policy` → `AmgGuardPolicy` in new module `adapters/memory/dozerdb/amg_policy.py` (backcompat alias retained through Stage 5); default preset switched to `Policy.tiered()`; write kwargs `source_class`/`receipt_uri`/`cls`/`task_id`/`source` threaded through opt-in via payload keys and stripped from JSON body. MCP / CLI / GitHub Action / integrations / ML detector deliberately NOT adopted at 4.3 (each is its own future ADR).
- **DoD (met):** Version recorded in `BUILD_LOG.md` + `PORTING_LEDGER.md` (v0.2.2 → v0.3.0 amendment with ADR-048 reference). Contract test renamed `test_amg_v02_policy_contract.py` → `test_amg_policy_contract.py` with new coverage: default-preset assertion, strict opt-in, unknown-preset fail-safe, backcompat alias resolution, all five v0.3.0 write kwargs forwarding, routing-key body stripping. 20 fast + 2 env-gated live tests; DozerDB adapter fast-tier 130 passed / 7 skipped.
- **Tag:** `stage-4-3-complete`.

### 4.4 Superpowers KB port — **LANDED** (2026-07-30, ADR-049)
- **Ports:** MemoryPort (`record_event`, `query_temporal`, typed-link retrieval via new `CorpusEdge`).
- **Action:** Landed `obra/superpowers` @ `44c9b2d6e889982ac18c27d05a19fefe335194e1` (MIT) as the fourth Stage 4.2-shaped corpus, colocated with `rigpa-export` at `adapters/memory/dozerdb/corpora/superpowers/`. Full-body Markdown ingest, one MemoryPort record per `skills/*/*.md` file at the pinned SHA — 38 records across 14 skill directories, ~310 KB fixture. Inline `[text](path)` links between sibling files parse into typed `CorpusEdge` records at load time (9 edges at 4.4 landing). Ingest pipeline is workspace-local (`scripts/ingest_superpowers.py --sha <SHA>` — not committed to plugin space, not invoked at runtime). Env override `KOSMOS_SUPERPOWERS_PATH` accepts an alternate JSONL. VectorPort surface deliberately NOT opened (ADR-049 Q4). `models.py` gains `CorpusEdge` dataclass; `Corpus` gains optional `edges` field (defaults to `()`, backward-compatible with Stage 4.2 corpora); construction-time invariants enforce src/dst resolvability. `ALL_CORPORA` grows to four; parametrized invariant tests + env-gated live tier extend automatically. Superpowers corpus relocates to `plugins/gnosis/humanities/personal_kb/` at Phase 3 (public loader shape stable across the move); adapter-corpus location is a Stage 4.4 landing site, not the endpoint. Reconciles ADR-008 (Tektos-UX "do not vendor code") with ADR-002 + ADR-016 (Personal-KB substrate under Gnosis) per ADR-049 §Context: Superpowers content enters Kosmos as MemoryPort **data**, not as Tektos plugin code.
- **DoD (met):** Every Superpowers fact carries `body` + `source_commit` + `license="MIT"` + `upstream_url` + typed `references`; every `CorpusEdge` resolves to a fact in the same corpus at construction time; ADR-007 AST scan recurses into subpackages and passes; DozerDB adapter fast tier 142 passed / 8 skipped (up from 130/7 at Stage 4.3, delta = +7 new fast tests + 5 parametrized invariant extensions + 1 new env-gated live-tier corpus parametrization).
- **Tag:** `stage-4-4-complete`.

### 4.5 Humanities corpus port — **LANDED** (2026-07-30, ADR-050)
- **Ports:** MemoryPort (`record_event`, `query_temporal`, typed CIDOC-CRM-link retrieval via `CorpusEdge`).
- **Action:** Landed `suttacentral/bilara-data` @ `3c93d1cea80fdebcefb777c8724c35bd971f360a` (translations CC0-1.0, Mahasangiti Pali root public-domain) as the fifth Stage 4.2-shaped corpus, `humanities-bilara`, at `adapters/memory/dozerdb/corpora/humanities_bilara/`. Pivoted from 84000 CC-BY-NC-4.0 to Bilara CC0 to eliminate NC downstream propagation risk (ADR-050 Q1); Bilara's directory mirror between `translation/<lang>/<translator>/**` and `root/<lang>/<edition>/**` is literally CIDOC-CRM `P73_has_translation`. Full-body segment-keyed JSON ingest, one MemoryPort record per `translation/<lang>/<translator>/**/*.json` at the pinned SHA + one per mirrored `root/<lang>/<edition>/**/*.json` + one per referenced translator `E21_Person` actor from `_author.json` — Stage 4.5 slice = Bhikkhu Sujato's English translations of scpub7 Dhammapada + scpub19 Khuddakapatha + scpub86 Cariyapitaka mirrored by Mahasangiti Pali root under `root/pli/ms/sutta/kn/{dhp,kp,cp}/` = 141 records (70 translation + 70 root + 1 actor), ~392 KB fixture. Directory mirror + `_author.json` attribution parse into typed `CorpusEdge` with CIDOC-CRM property URIs `P73_is_translation_of` (70) + `P94_was_created_by` (70) = 140 edges at 4.5 landing. Ingest pipeline is workspace-local (`scripts/ingest_humanities.py --sha <SHA> [--via gh|checkout]` — not committed to plugin space, not invoked at runtime). Env override `KOSMOS_HUMANITIES_BILARA_PATH` accepts an alternate JSONL. VectorPort surface deliberately NOT opened (ADR-050 Q4). Untyped `references` kind explicitly rejected — CIDOC-CRM property URIs required for external KG interop. Loader validates three subject namespaces (`bilara/actor/`, `bilara/root/`, `bilara/translation/`) with per-namespace required-attribute lists; unknown namespaces rejected. `ALL_CORPORA` grows to five; parametrized invariant tests + env-gated live tier extend automatically. Stage 4.2 hand-authored `humanities_cidoc_sample` corpus stays as fast-tier CIDOC-CRM invariants probe — NOT superseded. Bilara corpus relocates to `plugins/gnosis/humanities/canonical_kb/` at Phase 3 (public loader shape stable across the move); adapter-corpus location is a Stage 4.5 landing site, not the endpoint. Reconciles ADR-002 + ADR-016 (Humanities substrate under Gnosis) with Stage 4.2 corpora contract (ADR-047) per ADR-050 §Context: Bilara content enters Kosmos as MemoryPort **data**, not plugin code.
- **DoD (met):** Every Bilara body-carrying fact carries `body` + `source_commit` + `license` (`CC0-1.0` or `public-domain`) + `upstream_url` + typed `references`; actor records carry `author_uid` + `source_commit` + `license` + `crm_class="E21_Person"`; every `CorpusEdge` uses a CIDOC-CRM property URI as its `kind` and resolves to a fact in the same corpus at construction time; every translation record has exactly one root mirror at the same `bilara_uid` (bijection guard); DozerDB adapter fast tier 155 passed / 9 skipped (up from 142/8 at Stage 4.4, delta = +7 new fast tests + 5 parametrized invariant extensions + 1 new env-gated live-tier corpus parametrization).
- **Tag:** `stage-4-5-complete`.

### 4.6 Stage-4 exit gate — **LANDED** (2026-07-30, ADR-051)
- **Ports:** MemoryPort (read surface via corpora registry — no new port).
- **Action:** Materialized the Stage 4.6 exit gate as an adapter-side FastAPI application factory at `adapters/memory/dozerdb/gate/`, federated across all five landed corpora (`synthetic-lifeline`, `humanities-cidoc-sample`, `rigpa-export`, `superpowers`, `humanities-bilara`). Six locked routes mirror the Tektos UI (Stage 3.11) shape: `/` (dashboard listing every corpus + edge-kind census + licenses), `/corpus/{name}` (detail with 20-fact sample), `/corpus/{name}/provenance/{event_id}` (full chain with source+timestamp+confidence + inbound/outbound edges + CIDOC-CRM attributes), `/corpus/{name}/query` (temporal query, params `q`+`as_of`+`limit`, deterministic sort by `as_of`+`event_id`), `/corpus/{name}/traverse/{event_id}` (outbound typed edges only), `/healthz`. FastAPI factory `build_stage_46_gate_app(*, corpora)` returns a fresh app on every call, zero global state; templates are pure-Python HTML fragment renderers with `html.escape` on every user-supplied string, no jinja/htmx/template engine. Value objects `ClaimEnvelope`, `EdgeEnvelope`, `ProvenanceChain`, `CorpusSummary` are frozen slotted dataclasses; retrieval helpers `build_provenance_chain`, `traverse_typed_edges`, `summarize_corpus`, `query_temporal_fast` are pure functions over `Corpus`. Route paths, host/port, provenance string, default confidence, and the six-route tuple all live in `policy.py` as module constants. Gate binds `127.0.0.1:8746` (distinct from Tektos UI 8765); no port collision. `STAGE_46_PROVENANCE="stage_46_gate"` reserved for any future write path; default confidence `1.0` (Stage 5 Graphiti derivations will introduce sub-1.0 confidence). Rejected `plugins/gnosis/ui/` per ADR-051 Q1 — Gnosis has no code at Stage 4.5 landing, stub plugin would need deletion at Phase 3. The Stage 4.6 DoD verb reads at the retrieval surface, not at a plugin; landing the surface adapter-side satisfies the DoD and stays open to either wrap-or-replace by Phase 3 Gnosis. No new pip dep — FastAPI already vendored from Stage 3.11 Tektos UI, no PORTING_LEDGER change. ADR-007 enforced at test time by an AST scan that walks `gate/*.py` and asserts no `import plugins.*` / `from plugins.* import`. Zero-trust invariants preserved — the gate is read-only at 4.6.
- **DoD (met):** Every fact across the five landed corpora (214 asserted end-to-end) renders as a `ProvenanceChain` carrying `provenance`+timezone-aware `as_of`+`confidence ∈ (0,1]`; every typed `CorpusEdge` in every corpus resolves to a fact in the same corpus; canned Bilara temporal query returns exactly 70 translation records with the provenance triple; canned CIDOC-CRM traversal from any Bilara translation resolves to exactly `{P73_is_translation_of, P94_was_created_by}`; Bilara edge census is exactly `{P73_is_translation_of: 70, P94_was_created_by: 70}`; `/healthz` returns `ok · 5 corpora`; the six-route tuple in `STAGE_46_ROUTES` is locked. Gate app is stateless — same factory call twice returns two fresh apps. DozerDB adapter fast tier 174 passed / 10 skipped (up from 155/9 at Stage 4.5, delta = +19 new fast tests + 1 env-gated live tier). Whole-repo fast tier 957 passed / 19 skipped.
- **Tag:** `stage-4-6-complete`.

---

## Stage 5 — Oikos (Household Administration) (Weeks 7-8) — **DEFERRED (2026-07-30, ADR-052 §Q1 amends ADR-015)**

> **Deferral note (2026-07-30):** At Stage 4.6 landing (commit `5ce3917`, tag `stage-4-6-complete`), the user elected to defer all of Stage 5 (Oikos skeleton + bill tracking + maintenance schedule + household inventory + benefit-assist + Stage-5 exit gate) and jump directly to Stage 6.1 (Zetesis skeleton). ADR-015's Oikos-ahead-of-Zetesis rationale is preserved but amended; when the user returns to Stage 5, ADR-015 re-activates as guidance for the order of Phase-5 substages. Stage 6.1 landed 2026-07-30 (see §6.1 below + ADR-052).

Reference: Spec §19.

### 5.1 Oikos plugin skeleton
- **Ports:** DataPort, MemoryPort, NotificationPort, EventBusPort
- **DoD:** Plugin loads, empty dashboard tab renders.

### 5.2 Bill/subscription tracking
- **DoD:** Ingest a bill statement (docling), extract structured data, upcoming-payment reminder fires.

### 5.3 Vehicle/appliance maintenance schedule
- **DoD:** Add asset with maintenance interval → algedonic reminder at threshold.

### 5.4 Household inventory (JSON-LD)
- **DoD:** Add/remove/query items.

### 5.5 Benefit-assist patterns (CMSgov BenefitAssist + 18F SNAP references)
- **Note:** Design reference only; we-promise/sure REJECTED (see PORTING_LEDGER).
- **DoD:** UX patterns adopted where applicable; log design decisions in `docs/oikos-ux-decisions.md`.

### 5.6 Stage-5 exit gate
- Oikos runs one full monthly household cycle end-to-end (bills + inventory + reminders)
- **DoD:** No manual data entry required except initial seed.

---

## Stage 6 — Zetesis (Research) + ADR-010 Resolution (Weeks 9-10) — **STARTED EARLY (Stage-5 deferred; see §5 note + ADR-052 §Q1)**

### 6.1 Zetesis skeleton — **LANDED** (2026-07-30, ADR-052)
- **Ports (10 required + 1 optional — Q7=B-plus, corrects the pre-2026-07-30 4-port list):**
  - **Required (non-None):** FrontendContractPort, LLMPort, MemoryPort, VectorPort, DataPort, SearchPort, EventBusPort, ResourcePort, NotificationPort, ObservabilityPort.
  - **Optional (defaults to `None`):** SecretsPort (wired when Zetesis first consumes a non-local SearXNG backend or paywalled data source).
- **Action:** Kernel-plugin at `plugins/zetesis/` with dataclass-plus-async-start-stop shape mirroring Praxis (Stage 2.1) / Phrouros (Stage 2.3) / Tektos (Stage 3.1+). `build_zetesis_descriptor()` returns a `PluginDescriptor` with **zero panels, zero routes, empty design tokens** — kernel discovers Zetesis via `FrontendContractPort.register_plugin` but nothing renders yet; UI surface lands at Stage 6.3/6.4 when real research output exists (Q2=A). Skeleton is **inner-loop-agnostic**: all 10 required business ports are held as constructor dependencies but **called zero times** at 6.1; no `ResearchInnerLoop` Protocol seam; ADR-010 head-to-head (AREX vs. LangChain Open Deep Research) remains fully open pre-§6.2 (Q3=A). Locked MemoryPort constants at 6.1 (Q4=confirmed): `ZETESIS_MEMORY_PROVENANCE="zetesis_research"`, `ZETESIS_MEMORY_PREDICATE="zetesis.research.completed"`, `ZETESIS_MEMORY_DEFAULT_CONFIDENCE=0.75` (mirrors ADR-036 Tektos pre-Reflexion default; sits in `(0,1]` per ADR-008). The real `ZetesisPlugin` **is** the `zetesis-stub` from spec §191 + §1.6 (Q5=C); no separate stub package; Phase-1 stub-role debt closes at 6.1 landing — Tektos Phase-10 model-swap-under-load rig will bind to `ZetesisPlugin` directly via ResourcePort priority-queue arbitration (spec §172). Enforcement: `test_start_touches_no_business_port` binds all 10 required ports to `_UntouchablePort` sentinels that raise `AssertionError` on any attribute access; `start()` completing without raising proves zero business-port calls at 6.1. `SecretsPort` optional-slot verified both with `None` (default) and with a real port instance. New files: `plugins/zetesis/{__init__.py, plugin.py, tests/__init__.py, tests/test_zetesis_plugin.py}`. No new pip deps; no PORTING_LEDGER change (skeleton is purpose-written, no OSS port).
- **ADR-007:** Enforced at test time by an AST scan (`test_zetesis_package_never_imports_other_plugins_adr_007`) that walks `plugins/zetesis/**/*.py` and asserts no `import plugins.praxis`/`plugins.phrouros`/`plugins.tektos` or `from plugins.{praxis,phrouros,tektos} import` statement exists. Cross-plugin coupling routes through `EventBusPort` only (once exercised at Stage 6.3+).
- **ADR-008:** Zero-trust write invariants pinned at 6.1 — every Stage-6.3+ Zetesis write path will carry `ZETESIS_MEMORY_PROVENANCE` + `ZETESIS_MEMORY_DEFAULT_CONFIDENCE ∈ (0,1]`. No writes fire at 6.1.
- **ADR-010:** Preserved OPEN. Zetesis at 6.1 makes zero `LLMPort` calls; head-to-head eval at §6.2 remains pristine apples-to-apples.
- **ADR-015:** Amended (see ADR-052 §Q1 + the status-amendment block at the head of `docs/adrs/ADR-015-oikos-before-zetesis.md`). Stage 5 deferred, not cancelled.
- **ADR-021:** SearchPort promoted to a required Zetesis constructor slot at 6.1 (Q7=B-plus) — reinforces "web search is first-class."
- **ADR-029:** ResourcePort slot wired at 6.1 so Stage 6.3's first LLM inference call will pass through the fixed priority order (`Phrouros anomaly > Tektos active > Synedrion/Zetesis background`) by construction.
- **DoD:** Plugin loads.
- **DoD anchor:** `pytest plugins/zetesis/` — 29 fast tests green (locked constants 8, descriptor shape 5, construction/lifecycle/idempotency 11, ADR-007 AST guard 1, port-surface holds 2, `_UntouchablePort` proof 1, SecretsPort optional-slot 1). Whole-repo fast tier: **986 passed / 19 skipped** (up from 957 / 19 at Stage 4.6, delta +29 = new Zetesis tier exactly).
- **Tag:** `stage-6-1-complete`.

### 6.2 **ADR-010 head-to-head eval (PRE-Phase-6.2)** — **LANDED 2026-07-30**
- **Options:** AREX-Turbo (BAAI, Apache-2.0) vs. LangChain Open Deep Research (`d337ae3`, MIT)
- **Fixture:** Identical 6-canonical-fact multi-source research task on Colossus with shared SearXNG substrate (`ops/benchmarks/adr_010/fixtures/adr_010_question.json`)
- **Metrics:** Six locked metrics per trial (see `ops/benchmarks/adr_010/metrics.py`); blind manual rating against F1-F6 canonical facts
- **Result:** **Winner = Open Deep Research** (3/3 completion; aggregate 3.0/18 on 6-canonical-fact rubric). **AREX-Turbo rejected for Stage 6.2** (0/3 completion at 32k context; 0/3 completion at 65k retry — RTX 5090 thermal-blank at >85°C halted the run). Winner locked on completion reliability under the Colossus envelope; substrate answer-quality tuning owned by Stage 6.3.
- **Artifacts:** `ops/benchmarks/artifacts/adr-010-2026-07-30/{arex,odr}/` (six trial JSONs committed at `e882b2a`)
- **DoD:** [x] ADR-010 status = `LOCKED` with winner named and benchmark artifacts committed. [x] `PORTING_LEDGER.md` ODR promoted EVAL-ONLY → VENDORED; AREX-Turbo flipped to REJECTED for Stage 6.2 (on-shelf).
- **Tag:** `stage-6-2-complete`
- **Colossus thermal envelope constraint (documented, carries forward):** sustained vLLM bfloat16 attention with a 65k KV cache tripped a display-blank thermal event above 85°C twice this session. Until thermal remediation (undervolt / fan-curve / thermal-pad refresh) is done and re-verified, vLLM inference on Colossus runs with `--enforce-eager --gpu-memory-utilization 0.75 --max-model-len 32768` as the safe operating envelope.

### 6.3 Wire winning inner-loop
- **DoD:** Zetesis produces a multi-source research report with citations.

### 6.4 Stage-6 exit gate
- Zetesis answers a hard research question with 5+ diverse sources and full provenance
- **DoD:** Report renders in dashboard with expandable source tree.

---

## Stage 7 — Koinonia (Agent-to-Agent) (Week 11)

### 7.1 Vendor a2a-sdk as standalone transport (ADR-011)
- **Not** using Moltbook transport (ADR-011 resolution)
- **DoD:** Two Kosmos plugins exchange messages over a2a-sdk.

### 7.2 Synedrion (multi-agent coordination)
- **DoD:** Three-agent scenario completes with EventBus + a2a messages.

### 7.3 Stage-7 exit gate
- Cross-plugin workflow (e.g., Zetesis asks Tektos to prototype something)
- **DoD:** End-to-end trace visible in Langfuse.

---

## Stage 8 — Remaining Plugins (Weeks 12+)

### 8.1 Nomisma (finance)
- **Ports:** DataPort, MemoryPort, NotificationPort
- **DoD:** Ingest one bank export, categorize, monthly summary.

### 8.2 Hygieia (health)
- **DoD:** Ingest wearable export, trend view.

### 8.3 Axiomeon / Holon (theoretical work)
- **DoD:** JSON-LD authoring tool operational.

---

## Stage 9 — Longevity & DR

### 9.1 Four-store DR drill (quarterly recurring — first execution required here)
- **Stores:** DozerDB (memory), Qdrant (vectors), Valkey (bus), Vault (secrets)
- **Action:** Backup → simulated total loss → restore → integrity verification
- **DoD:** Recovery time recorded; runbook updated at `ops/dr/quarterly-drill.md`.

### 9.2 Bus-factor documentation
- **DoD:** Any component fully documented such that a second maintainer could take over.

### 9.3 Hardware portability check
- **DoD:** Compose stack boots on a second (spec-lower) machine and runs Stage-5 exit scenario.

---

## Stage 10 — Program Sign-Off

- All ADRs `LOCKED` (including ADR-010 by Stage 6)
- All stages' exit gates green
- BUILD_LOG unbroken from bootstrap to sign-off
- DEBUG_LOG shows all bugs closed or triaged into KNOWN_ISSUES
- SESSION_HANDOFF reflects "PROGRAM COMPLETE" state
- Recurring actions (Spec §23) scheduled on the calendar:
  - OSS cannibalization scan — per phase gate + quarterly
  - Agent Memory Guard release check — quarterly
  - Four-store DR drill — quarterly
  - ADR review — annually

---

## Cross-Cutting Recurring Duties (every step)

1. **Before** starting a step: read `SESSION_HANDOFF.md` and `KNOWN_ISSUES.md`.
2. **Before** diagnosing any bug: `grep -i "<symptom>" DEBUG_LOG.md`.
3. **Before** hand-writing code: run `kosmos-port-workflow` skill to check for a permissively-licensed OSS port.
4. **Before** committing a decision that reshapes the architecture: run `kosmos-adr-authoring` skill.
5. **After** every step: `kosmos-log-maintenance` skill appends `BUILD_LOG.md` and (if applicable) `DEBUG_LOG.md`.
6. **End of session:** overwrite `SESSION_HANDOFF.md` with current stage + next action.

---

## Stop Conditions

Stop and ask the user if any of the following occur:
- A step's DoD cannot be met with the specified adapter
- An ADR flagged decision reappears (spec change not reflected in ADR)
- A port contract would need to change to complete a step
- Two consecutive steps produce the same DEBUG_LOG symptom
- The Colossus resource envelope (128GB RAM / 32GB VRAM) would be exceeded
