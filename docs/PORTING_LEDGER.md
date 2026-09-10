# Kosmos Porting Ledger

**Rule:** Every OSS component vendored into Kosmos MUST be logged here **before** first commit that uses it. No exceptions.

**Fields per entry:**
- **Name** — canonical component name
- **Source** — upstream URL
- **Commit / Version** — exact SHA or release tag pinned
- **License** — SPDX identifier (only permissive: MIT, BSD-2/3, Apache-2.0, ISC, MPL-2.0)
- **Kosmos location** — where it lives in the repo
- **Port(s) used** — which formal port(s) it plugs into
- **Modifications** — bullet list of local changes; "none" if unmodified
- **ADR** — referencing ADR if any
- **Logged** — timestamp

**Status codes:** `PLANNED` (approved, not yet vendored) · `VENDORED` (in tree) · `EVALUATING` (spike/bench) · `REJECTED` (design reference only, do not vendor) · `SUPERSEDED` (replaced by another entry)

---

## Kernel-Layer Ports

### LLM stack

#### Ollama (consolidated adapter) — `VENDORED (Stage 1.1)`
- **Source (upstream runtime):** https://github.com/ollama/ollama (service; not vendored — runs as system service)
- **Adapter donor sources consolidated:**
  - [Rigpa-LMS/backend/src/rigpa/core/llm/ollama.py](https://github.com/rmholston420/Rigpa-LMS/blob/main/backend/src/rigpa/core/llm/ollama.py) — most complete: chat + generate + embed + model mgmt + lifecycle + singleton
  - [Rigpa-LMS/backend/src/rigpa/domains/integrations/ollama.py](https://github.com/rmholston420/Rigpa-LMS/blob/main/backend/src/rigpa/domains/integrations/ollama.py) — model list/pull/delete (folded into core)
  - [axiom/packages/axiom_providers/ollama.py](https://github.com/rmholston420/axiom/blob/main/packages/axiom_providers/ollama.py) — adds streaming (`generate_stream` via `httpx.stream`)
- **License:** MIT (Ollama upstream); donor code is user-authored under `rmholston420/*` (relicensable)
- **Kosmos location:** `adapters/llm/ollama/`
- **Port(s):** `LLMPort`
- **Modifications from consolidation:**
  - Base = Rigpa `core/llm/ollama.py` (async client + singleton + full API coverage)
  - Add streaming from axiom (`generate_stream`, `chat_stream`)
  - Drop Rigpa `domains/integrations/ollama.py` typed model schemas (fold into core; single `list_models` returning list[dict])
  - Keyword-only kwargs throughout (align with Kosmos convention seen in axiom)
  - Wrap all methods behind `LLMPort` Protocol
- **ADR:** ADR-012 (donor adapter consolidation) + ADR-022 (LLMPort surface expansion — defines the 10-method Protocol this adapter satisfies)
- **Logged:** 2026-07-29 21:05 EDT

#### llama-swap — `VENDORED` (Stage 1.3)
- **Source:** https://github.com/mostlygeek/llama-swap
- **Commit / Version:** `0c4233363ec589c439b7f7d12eaae2346811098d` (2026-07-28)
- **License:** MIT
- **Kosmos location:** `adapters/llm/llama_swap/` (HTTP-client adapter only; llama-swap runs as external Go daemon, not vendored source)
- **Port(s):** `LLMPort` (second adapter satisfying the Protocol — proves swappability against ADR-022 surface)
- **Modifications:**
  - HTTP-client adapter targets the OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/models`)
  - `generate` / `generate_text` implemented via `/v1/completions`
  - `chat` implemented via `/v1/chat/completions`
  - `generate_stream` implemented via SSE on `/v1/completions?stream=true`
  - `list_models` implemented via `/v1/models`
  - `pull_model` / `delete_model` raise `NotImplementedError` — llama-swap does not manage weights (models are pre-declared in its `config.yaml`). Documented capability subset per ADR-022 Consequences §Downstream stages
  - `is_healthy` uses `/health` (llama-swap-native), non-throwing per ADR-022 rule 3
- **ADR:** ADR-009 (llama-swap primary sidecar) + ADR-022 (LLMPort surface)
- **Logged:** 2026-07-29 21:35 EDT

#### router-mode fallback — `PLANNED (fallback only)`
- **Source:** internal build using llama.cpp server routes
- **License:** MIT (llama.cpp)
- **Port(s):** LLMPort
- **ADR:** ADR-009
- **Logged:** —

### Event Bus

#### redis-py (async) — `VENDORED` (Stage 1.4)
- **Source:** https://github.com/redis/redis-py
- **Commit / Version:** dependency — pinned via pyproject `redis>=5.0` (installed on Colossus at run time)
- **License:** MIT
- **Kosmos location:** `adapters/event_bus/valkey/` (HTTP-client adapter; Valkey/Redis runs as external service)
- **Port(s):** `EventBusPort` (ADR-023)
- **Modifications:**
  - `redis.asyncio` imported lazily so unit tests using the in-memory fake do not require `redis` to be installed
  - Adapter uses only `xadd` / `xrange` / `ping` / `aclose` — consumer-group calls (`xgroup_create`/`xreadgroup`/`xack`/`xpending`/`xclaim`) deferred to ADR-024
  - Envelope-first: adapter refuses raw-dict publish (`TypeError`); every published payload is a validated `EventEnvelope`
  - In-process fan-out via `asyncio.Queue.put_nowait()` runs alongside stream append (matches Rigpa `KernelEventBus` two-layer pattern)
- **ADR:** ADR-007 (events-only cross-plugin coupling) + ADR-023 (EventBusPort envelope-first MVP)
- **Logged:** 2026-07-29 21:32 EDT

#### Rigpa event envelope + stream-client pattern — `VENDORED` (Stage 1.4)
- **Source:** https://github.com/rmholston420/Rigpa-LMS (user's own repo; permissively-licensed donor)
  - `backend/src/rigpa/core/events/envelope.py`
  - `backend/src/rigpa/core/events/valkey.py` (StreamClient Protocol + InMemoryStreamClient fake)
  - `backend/src/rigpa/core/events/kernel_bus.py` (two-layer publish + in-process fan-out)
- **Commit / Version:** inspected at donor `main` on 2026-07-29
- **License:** user's own code; treated as permissive donor
- **Kosmos location:** `ports/event_envelope.py`, `adapters/event_bus/valkey/adapter.py`
- **Modifications:**
  - Envelope reimplemented as stdlib `@dataclass(frozen=True, slots=True)` (kernel has no Pydantic dependency at Stage 1.4)
  - Envelope adds explicit `__post_init__` validation for empty `event_type` / `producer_plugin` / `schema_version`
  - `StreamClient` Protocol extended to include `ping()` and `aclose()` (health + lifecycle per ADR-023)
  - `InMemoryStreamClient` adds `ping_should_fail` toggle so tests can exercise non-throwing `is_healthy` path
  - Two-layer publish pattern simplified: no transactional outbox (deferred until MemoryPort is online in Stage 5+); Stage 1.4 does stream-append + in-process fan-out only
- **ADR:** ADR-023 (envelope-first MVP)
- **Logged:** 2026-07-29 21:32 EDT

### Secrets

#### pyrage — `VENDORED` (Stage 1.5)
- **Source:** https://github.com/woodruffw/pyrage
- **Commit / Version:** dependency — pinned via pyproject `pyrage>=1.1` (Rust-compiled wheel installed on Colossus)
- **License:** Apache-2.0 / MIT (dual)
- **Kosmos location:** `adapters/secrets/age_file/adapter.py` (used inside `PyrageBackend` only)
- **Port(s):** `SecretsPort` (ADR-024)
- **Modifications:**
  - `pyrage` and `yaml` imported lazily so unit tests using `InMemoryAgeBackend` do not require either dependency installed
  - Only two operations used: `pyrage.decrypt(ciphertext, [identity])` and `pyrage.encrypt(plaintext, [recipient])`
  - Recipients derived from the identity file's public key so rotation writes are decryptable by the same identity; multi-recipient (§7 succession key escrow) is a future extension
- **ADR:** ADR-024 (SecretsPort age-file primary)
- **Logged:** 2026-07-29 21:36 EDT

#### PyYAML — `VENDORED` (Stage 1.5)
- **Source:** https://github.com/yaml/pyyaml
- **Commit / Version:** dependency — pinned via pyproject `PyYAML>=6.0`
- **License:** MIT
- **Kosmos location:** `adapters/secrets/age_file/adapter.py` (safe_load/safe_dump of the decrypted secrets mapping)
- **Port(s):** `SecretsPort`
- **Modifications:** `yaml.safe_load` / `yaml.safe_dump` only (no arbitrary-object deserialization)
- **ADR:** ADR-024
- **Logged:** 2026-07-29 21:36 EDT

#### Rigpa age-secrets loader pattern — `VENDORED` (Stage 1.5)
- **Source:** https://github.com/rmholston420/Rigpa-LMS (user's own repo; permissively-licensed donor)
  - `backend/src/rigpa/core/secrets.py` (age-file loader, `SecretSettings` + `load_secrets`)
  - `backend/src/rigpa/core/secrets_meta_model.py` (`SecretsMeta` ORM)
  - `docs/adr/0002-single-user-knowsys-vaults.md` (single-user framing)
- **Commit / Version:** inspected at donor `main` on 2026-07-29
- **License:** user's own code; treated as permissive donor
- **Kosmos location:** `ports/secrets.py`, `adapters/secrets/age_file/adapter.py`
- **Modifications:**
  - Rigpa uses `SecretSettings` Pydantic model wrapping every field in `SecretStr`; Kosmos uses `SecretValue` (stdlib frozen dataclass) so `ports/` has zero Pydantic dependency — same redaction guarantee, stricter accessor (`.reveal()` verb is grep-able audit anchor)
  - `SecretValue.__eq__` compares redacted repr so distinct secrets never appear equal in logs; `SecretValue.__reduce__` refuses pickling (Rigpa's SecretStr permits both)
  - Rotate is a filesystem operation on the whole file (§7 semantics) rather than field-level updates; write-to-temp + `os.replace` for POSIX atomicity
  - `AgeBackend` Protocol isolates age crypto so tests can inject a fake without installing `pyrage` — mirrors the Stage 1.4 `StreamClient` pattern
  - No Alembic migration for `SecretsMeta` at Stage 1.5; that lands with MemoryPort in Stage 5+
- **ADR:** ADR-024
- **Logged:** 2026-07-29 21:36 EDT

### Memory / Graph

#### DozerDB server — `VENDORED` (Compose service, real backend at Stage 4.2)
- **Source:** https://github.com/graphstack/DozerDB (community fork of Neo4j Community with enterprise-tier features backported permissively)
- **Commit / Version:** container image `graphstack/dozerdb:5.26.27` pinned in `ops/compose/memory.yml`
- **License:** Apache-2.0 (fork additions; upstream Neo4j Community is GPL-3, but DozerDB fork additions are permissive per ADR-008 requirement)
- **Kosmos location:** Docker Compose service `kosmos-dozerdb` at `ops/compose/memory.yml` (README `ops/compose/README.md`); Bolt on 7687; Colossus-local; DR-drill dump target per spec §184
- **Port(s):** `MemoryPort` (ADR-008 backend choice; ADR-027 surface + enforcement; ADR-047 real-backend landing at Stage 4.2)
- **Modifications:** none — upstream container image; heap capped at 4 GiB (`NEO4J_server_memory_heap_max__size=4G`) + page-cache capped at 2 GiB (`NEO4J_server_memory_pagecache_size=2G`) to sit inside Colossus's 128 GB envelope alongside Ollama + qwen3-coder residency
- **ADR:** ADR-008 + ADR-027 + ADR-047
- **Logged:** 2026-07-29 22:02 EDT (initial); 2026-07-30 07:45 EDT (`PLANNED` → `VENDORED` at Stage 4.2 lock-in)

#### neo4j (Python driver) — `VENDORED` (Stage 1.8)
- **Source:** https://github.com/neo4j/neo4j-python-driver
- **Commit / Version:** dependency — pinned via pyproject `neo4j>=5.26`
- **License:** Apache-2.0 AND Python-2.0 ([neo4j-python-driver LICENSE](https://github.com/neo4j/neo4j-python-driver/blob/6.x/LICENSE.txt))
- **Kosmos location:** `adapters/memory/dozerdb/adapter.py` (used inside the future `DozerDbGraphBackend` only)
- **Port(s):** `MemoryPort`
- **Modifications:**
  - Imported lazily behind `GraphBackend` Protocol so contract tests using `InMemoryGraphBackend` do not require the wheel installed — mirrors Stage 1.5 `PyrageBackend` / Stage 1.6 `OtelBackend` / Stage 1.7 `QdrantBackend` splits
  - `AsyncGraphDatabase` is the sole entry point (donor Rigpa `rigpa.core.neo4j` async singleton pattern); sync driver not used
  - DozerDB is Bolt-protocol compatible with Neo4j; no wire-protocol changes needed
- **ADR:** ADR-008 + ADR-027
- **Logged:** 2026-07-29 22:02 EDT

#### graphiti-core — `VENDORED` (Stage 1.8 stub → real backend Stage 4.2)
- **Source:** https://github.com/getzep/graphiti
- **Commit / Version:** dependency — pinned via pyproject `graphiti-core>=0.5`
- **License:** Apache-2.0 ([getzep/graphiti pyproject](https://github.com/getzep/graphiti/blob/main/pyproject.toml))
- **Kosmos location:** `adapters/memory/dozerdb/graphiti_temporal_index.py` (real `GraphitiTemporalIndex` at Stage 4.2); `adapters/memory/dozerdb/adapter.py` composes it behind the `TemporalIndex` Protocol
- **Port(s):** `MemoryPort` (temporal index only — Graphiti shares DozerDB's Neo4j-driver Bolt connection)
- **Modifications:**
  - Imported lazily behind `TemporalIndex` Protocol; contract tests use `InMemoryTemporalIndex` (list of typed episodes)
  - Graphiti sits atop the same DozerDB instance via the same `neo4j` driver — no second connection pool
  - **Stage 4.2 wiring (ADR-047):** instantiated with `OpenAIGenericClient` + `OpenAIEmbedder` + `OpenAIRerankerClient` all pointed at local Ollama (`http://localhost:11434/v1`, `qwen3-coder` LLM + `nomic-embed-text` embedder). Graphiti's default `OpenAIClient()` (reads `OPENAI_API_KEY`) is not used — violates Kosmos local-first custom instructions.
  - **Stage 4.2 fix:** we do **not** pass `uuid=<event_id>` to `add_episode()` — Graphiti's semantics look up an existing EpisodicNode by that UUID (raises `NodeNotFoundError`). Our event id is carried through `name="event-<event_id>"` and injected as `kosmos_event_id` inside the JSON body.
  - **Sequencing note:** pulled forward from Stage 4.2 to Stage 1.8 per ADR-027 Q1=A. Stage 4.2 delivered the real backend + `PORT_CONTRACTS.md` metrics (schema drift, edge-type churn, temporal-episode latency).
- **ADR:** ADR-027 + ADR-047
- **Logged:** 2026-07-29 22:02 EDT (initial); 2026-07-30 07:45 EDT (real backend at Stage 4.2)

#### agent-memory-guard v0.3.0 — `VENDORED` (Stage 1.8 stub → real backend Stage 4.2 → v0.3.0 bump Stage 4.3)
- **Source:** https://github.com/OWASP/www-project-agent-memory-guard
- **Commit / Version:** PyPI `agent-memory-guard==0.3.0` (pinned exactly; upstream release https://github.com/OWASP/www-project-agent-memory-guard/releases/tag/v0.3.0 published 2026-06-10; bumped from v0.2.2 at Stage 4.3 per ADR-048)
- **License:** OWASP Foundation (PyPI-shipped Python package; Python code under permissive OWASP terms; free redistribution)
- **Kosmos location:** `adapters/memory/dozerdb/amg_policy.py` hosts `AmgGuardPolicy` (real v0.3.0 wrapper — `MemoryGuard(policy=Policy.tiered()).write/snapshot/rollback` with optional `source_class`/`receipt_uri`/`cls`/`task_id`/`source` write kwargs threaded through `evaluate(payload)`); `adapters/memory/dozerdb/amg_v02_policy.py` reduced to a one-line re-export shim; `AmgV02Policy` retained as backwards-compat alias through Stage 5; `adapters/memory/dozerdb/adapter.py` composes it behind the `AmgPolicy` Protocol
- **Port(s):** `MemoryPort` (write-time policy filter, second layer after non-bypassable port-level guard)
- **Modifications:**
  - Imported lazily behind `AmgPolicy` Protocol; contract tests use `NoOpAmgPolicy` / `AlwaysBlockAmgPolicy` / `AlwaysQuarantineAmgPolicy`
  - Policy loaded from `ops/agent-memory-guard/policy.yaml` at adapter construction (YAML file lands with Compose); overrides the built-in preset when set
  - AMG provides SHA-256 cryptographic baseline + declarative YAML policy engine (`allow` / `redact` / `quarantine` / `block`) per spec §112
  - **Stage 4.2 (ADR-047):** stub `NoOpAmgPolicy` replaced by real `AmgV02Policy` at `adapters/memory/dozerdb/amg_v02_policy.py` wrapping `Policy.strict()`. Contract fakes (`AlwaysAllow`/`AlwaysBlock`/`AlwaysQuarantine`) preserved for always-green Protocol-conformance tests.
  - **Stage 4.3 (ADR-048):** bumped `agent-memory-guard==0.2.2` → `agent-memory-guard==0.3.0`. Concrete wrapper class renamed `AmgV02Policy` → `AmgGuardPolicy` in new module `adapters/memory/dozerdb/amg_policy.py`; default policy preset switched from `Policy.strict()` to v0.3.0's `Policy.tiered()` (new default memory-class taxonomy); `MemoryGuard.write` optional kwargs `source_class`/`receipt_uri`/`cls`/`task_id`/`source` are threaded through from `AmgGuardPolicy.evaluate(payload)` (opt-in per payload; omitted keys default to AMG's v0.2.2 shape). MCP server / CLI scanner / GitHub Action / LlamaIndex + CrewAI integrations / ML injection detector / Prometheus exporter deliberately **not adopted** at 4.3 — each is its own trade-off surface and belongs behind a future ADR when the need arrives (out of scope for one-person-module bump).
- **ADR:** ADR-027 + ADR-047 + ADR-048
- **Logged:** 2026-07-29 22:02 EDT (initial); 2026-07-30 07:45 EDT (real backend at Stage 4.2); 2026-07-30 07:56 EDT (v0.3.0 bump at Stage 4.3)

#### Rigpa-LMS MemoryBridge + GraphClient donor pattern — `VENDORED` (Stage 1.8)
- **Source:** https://github.com/rmholston420/Rigpa-LMS (user's own repo; permissively-licensed donor)
  - `backend/src/rigpa/core/graph/protocol.py` (Rigpa `GraphClient` Protocol — Cypher-shaped: `query_cypher / add_node / add_edge / is_healthy / close`)
  - `backend/src/rigpa/core/neo4j.py` (async driver singleton)
  - `backend/src/rigpa/domains/memory/bridge.py` (`MemoryBridge` — async Cypher wrapper for store/query/link/graph)
  - `backend/src/rigpa/domains/memory/schemas.py` (Pydantic v2 request/response models)
  - `backend/src/rigpa/domains/memory/service.py` (thin service layer over the bridge)
- **Commit / Version:** inspected at donor `main` on 2026-07-29 (cached at `/tmp/donor-mem/`)
- **License:** user's own code; treated as permissive donor
- **Kosmos location:** `ports/memory.py`, `adapters/memory/dozerdb/adapter.py`
- **Modifications:**
  - Rigpa `MemoryCreate` schema carries no `provenance` / no `confidence`; `MemoryBridge.store_memory` writes `str(metadata or {})` — not typed, no schema enforcement. Kosmos adds a non-bypassable port-level guard (`ports.memory.validate_zero_trust_write`) that rejects missing/invalid `provenance` or `confidence` at the top of every write method before any backend I/O; mirrors ADR-026 `VectorPort` zero-trust pattern.
  - Rigpa exposes no `quarantine_write` and no `query_temporal`; Kosmos ships all four spec verbs (write_event / query_temporal / link_entities / quarantine_write) day-one per ADR-027 Q1=A.
  - Rigpa's `Neo4jGraphClient` is a Phase-1 stub (only Kuzu is wired); Kosmos ships a live DozerDB backend via `neo4j` driver (Bolt).
  - Rigpa returns raw `dict[str, Any]` from queries; Kosmos returns typed `MemoryHit` — matches SearchPort ADR-021 / SecretsPort ADR-024 / VectorPort ADR-026 typing discipline.
  - Rigpa's `is_healthy` is async; Kosmos version is sync + non-throwing (ADR-023 rule 5) so it can be called in kernel hot paths without spawning a coroutine — reuses `try/except -> False` guard from ObservabilityPort.
  - CIDOC-CRM triple decomposition: Kosmos writes three graph nodes (subject Entity + object Entity + MemoryEvent) + two directed edges (`SUBJECT_OF` + `OBJECT_OF`) per `write_event` — Rigpa has no CRM concept.
  - Quarantine lane (spec §115): Kosmos writes `:Quarantined` nodes that are NOT indexed in the temporal index — they are not semantic memory until reviewed and promoted. Rigpa has no quarantine concept.
- **ADR:** ADR-027
- **Logged:** 2026-07-29 22:02 EDT

### Vector store

#### Qdrant server — `PLANNED` (Compose service; not vendored into Python code)
- **Source:** https://github.com/qdrant/qdrant
- **Commit / Version:** container image — pinned by Compose (added when Docker Compose lands post-Stage 1.7)
- **License:** Apache-2.0
- **Kosmos location:** Docker Compose service `qdrant`; ports 6333 (HTTP) + 6334 (gRPC); Colossus-local
- **Port(s):** `VectorPort` (ADR-026)
- **Modifications:** none — upstream container image; snapshot artifacts written to a bind-mounted volume for the four-store DR-drill (§11)
- **ADR:** ADR-026
- **Logged:** 2026-07-29 21:58 EDT

#### qdrant-client — `VENDORED` (Stage 1.7)
- **Source:** https://github.com/qdrant/qdrant-client
- **Commit / Version:** dependency — pinned via pyproject `qdrant-client>=1.11`
- **License:** Apache-2.0
- **Kosmos location:** `adapters/vector/qdrant/adapter.py` (used inside the future `RealQdrantBackend` only)
- **Port(s):** `VectorPort`
- **Modifications:**
  - Imported lazily behind `QdrantBackend` Protocol so contract tests using `InMemoryQdrantBackend` do not require the wheel installed — mirrors Stage 1.5 `PyrageBackend` / Stage 1.6 `OtelBackend` splits
  - `AsyncQdrantClient` is the sole entry point (donor Rigpa `rigpa.core.qdrant` pattern); sync client not used
  - Free-form point ids hashed to stable UUIDv5 under `POINT_ID_NAMESPACE` before hitting the client (Rigpa `QdrantClaimUpserter.claim_point_id` pattern); Qdrant only accepts numeric or UUID ids
  - Collection creation is idempotent (get-then-create fallback), dimension inferred from the first vector inserted (Rigpa `_ensure_collection` pattern)
- **ADR:** ADR-026
- **Logged:** 2026-07-29 21:58 EDT

#### Rigpa-LMS vector-Protocol donor pattern — `VENDORED` (Stage 1.7)
- **Source:** https://github.com/rmholston420/Rigpa-LMS (user's own repo; permissively-licensed donor)
  - `backend/src/rigpa/core/vectors/protocol.py` (Rigpa `VectorStore` Protocol — four verbs + `is_healthy`)
  - `backend/src/rigpa/core/qdrant.py` (async singleton client pattern)
  - `plugins/gnosis/src/rigpa_gnosis/services/qdrant_upserter.py` (`QdrantClaimUpserter` — UUIDv5 point-id normalization; idempotent `_ensure_collection`; typed payload assembly)
  - Rigpa ADR-036 (pgvector→Qdrant threshold decision; referenced but not adopted in Kosmos day-one)
- **Commit / Version:** inspected at donor `main` on 2026-07-29 (cached at `/tmp/donor-vec/`)
- **License:** user's own code; treated as permissive donor
- **Kosmos location:** `ports/vector.py`, `adapters/vector/qdrant/adapter.py`
- **Modifications:**
  - Rigpa `VectorStore` Protocol added no `snapshot`, no `close`, and no port-level `provenance`/`confidence` guard — Kosmos adds all three (ADR-026 Q1). `snapshot()` returns a typed `SnapshotHandle` so the §11 DR-drill can verify the artifact directly.
  - Rigpa `search` returned raw `dict[str, Any]`; Kosmos returns typed `VectorHit` — matches `SearchPort`/`SecretValue` typing discipline (ADR-021/024)
  - Rigpa allowed unlabeled writes (payload had no schema); Kosmos raises `ValueError` at the port layer if `payload` lacks `provenance` or `confidence` outside `[0.0, 1.0]`. Enforced via `ports.vector.validate_zero_trust_payload`; non-bypassable
  - Rigpa's `is_healthy` is async; Kosmos version is sync + non-throwing (ADR-023 rule 5 reused) so it can be called in kernel hot paths without spawning a coroutine
  - pgvector adapter (Rigpa's phase-1 backend) is deferred; trigger for a future pgvector ADR is documented in ADR-026 §Deferred capabilities
- **ADR:** ADR-026
- **Logged:** 2026-07-29 21:58 EDT

### Search

#### SearXNG (consolidated adapter) — `VENDORED (Stage 1.1)`
- **Source (upstream runtime):** https://github.com/searxng/searxng (service; not vendored — runs via Docker Compose)
- **Adapter donor sources consolidated:**
  - [Rigpa-LMS/backend/src/rigpa/domains/integrations/searxng.py](https://github.com/rmholston420/Rigpa-LMS/blob/main/backend/src/rigpa/domains/integrations/searxng.py) — JSON-only, typed `SearchResponse`, engine list, language param
  - [axiom/packages/axiom_providers/searxng.py](https://github.com/rmholston420/axiom/blob/main/packages/axiom_providers/searxng.py) — JSON-first + HTML-fallback parser for 403 responses, User-Agent header
- **License:** AGPL-3.0 (SearXNG upstream — service only, not linked into Kosmos code); donor adapters user-authored (relicensable)
- **Kosmos location:** `adapters/search/searxng/`
- **Port(s):** `SearchPort` (new, per ADR-021)
- **Modifications from consolidation:**
  - Base = Rigpa adapter (typed response, engine list, language)
  - Add axiom's HTML fallback for `format=json` 403 responses (adapter-internal)
  - Add axiom's User-Agent header (`KosmosSearchAdapter/0.1 (+local; rmholston420/kosmos)`)
  - Add `provenance` field to `SearchResponse` (mandatory per ADR-021 for zero-trust memory writes)
  - Add `latency_ms` timing
  - Return typed dataclasses from `ports/search.py` (not adapter-local classes)
  - Wrap behind `SearchPort` Protocol
- **Runtime note:** SearXNG service runs in its own container; AGPL applies only to the service binary, not to Kosmos's HTTP-client adapter. Verify at deploy.
- **ADR:** ADR-012 (consolidation) + ADR-021 (SearchPort introduction)
- **Logged:** 2026-07-29 21:05 EDT

### Event bus

#### Valkey (Redis fork) — `PLANNED`
- **Source:** https://github.com/valkey-io/valkey
- **License:** BSD-3-Clause
- **Kosmos location:** Docker Compose; `adapters/eventbus/valkey/`
- **Port(s):** EventBusPort
- **Logged:** —

### Secrets

#### Vault (HashiCorp) + `hvac` client — `PLANNED`
- **Source:** https://github.com/hashicorp/vault (server); https://github.com/hvac/hvac (Python)
- **License:** BUSL-1.1 (Vault server) — **REVIEW** for local single-user compliance; MPL-2.0 (hvac)
- **Kosmos location:** Compose (dev); systemd (prod); `adapters/secrets/vault/`
- **Port(s):** SecretsPort
- **Notes:** BUSL-1.1 permits local single-user use; document justification in ADR if concern
- **Logged:** —

### Observability

#### opentelemetry-sdk — `VENDORED` (Stage 1.6)
- **Source:** https://github.com/open-telemetry/opentelemetry-python
- **Commit / Version:** dependency — pinned via pyproject `opentelemetry-sdk>=1.27`
- **License:** Apache-2.0
- **Kosmos location:** `adapters/observability/otel_stack/adapter.py` (used inside the future `RealOtelBackend` only)
- **Port(s):** `ObservabilityPort` (ADR-025)
- **Modifications:**
  - Imported lazily behind `OtelBackend` Protocol so contract tests using `StubOtelBackend` do not require the wheel installed
  - Only `TracerProvider`, `MeterProvider`, span/`start_as_current_span`, counter/histogram, and resource attributes are used
- **ADR:** ADR-025
- **Logged:** 2026-07-29 21:52 EDT

#### opentelemetry-exporter-otlp-proto-grpc — `VENDORED` (Stage 1.6)
- **Source:** https://github.com/open-telemetry/opentelemetry-python (contrib exporters)
- **Commit / Version:** dependency — pinned via pyproject `opentelemetry-exporter-otlp-proto-grpc>=1.27`
- **License:** Apache-2.0
- **Kosmos location:** `adapters/observability/otel_stack/adapter.py` (`RealOtelBackend` OTLP wiring, added when LGTM stack lands)
- **Port(s):** `ObservabilityPort`
- **Modifications:** Endpoint defaults to `http://127.0.0.1:4317` (Colossus-local LGTM collector); OTLP failures degrade to no-op so a downed collector never crashes plugins
- **ADR:** ADR-025
- **Logged:** 2026-07-29 21:52 EDT

#### prometheus-client — `VENDORED` (Stage 1.6)
- **Source:** https://github.com/prometheus/client_python
- **Commit / Version:** dependency — pinned via pyproject `prometheus-client>=0.20`
- **License:** Apache-2.0
- **Kosmos location:** `adapters/observability/otel_stack/adapter.py` (Prometheus scrape endpoint at `:9090/metrics` for Grafana)
- **Port(s):** `ObservabilityPort`
- **Modifications:** Used only for the scrape-endpoint HTTP server; OTel meter is the primary write path (Prometheus is the read path for Grafana Alloy)
- **ADR:** ADR-025
- **Logged:** 2026-07-29 21:52 EDT

#### structlog — `VENDORED` (Stage 1.6)
- **Source:** https://github.com/hynek/structlog
- **Commit / Version:** dependency — pinned via pyproject `structlog>=24.1` (already present since Stage 0.1; now formalized against `ObservabilityPort`)
- **License:** Apache-2.0 / MIT (dual)
- **Kosmos location:** `adapters/observability/otel_stack/adapter.py` (bind_context/clear_context routed through `structlog.contextvars`)
- **Port(s):** `ObservabilityPort`
- **Modifications:**
  - Only `structlog.contextvars.bind_contextvars` and `clear_contextvars` are used from structlog directly; log formatting is delegated to the caller's processor chain
  - Mandatory correlation keys per Kosmos custom instructions (`plugin, request_id, user_id, trace_id, event`) are the contract; not enforced at runtime yet
- **ADR:** ADR-025
- **Logged:** 2026-07-29 21:52 EDT

#### Rigpa-LMS observability seam pattern — `VENDORED` (Stage 1.6)
- **Source:** https://github.com/rmholston420/Rigpa-LMS (user's own repo; permissively-licensed donor)
  - `backend/src/rigpa/observability/__init__.py`, `config.py`, `tracing.py`, `metrics.py`, `logging.py`
  - Rigpa ADR-044 (LGTM stack), ADR-013a (OTel adoption)
- **Commit / Version:** inspected at donor `main` on 2026-07-29 (cached at `/tmp/donor-obs/`)
- **License:** user's own code; treated as permissive donor
- **Kosmos location:** `ports/observability.py`, `adapters/observability/otel_stack/adapter.py`
- **Modifications:**
  - Rigpa layered OTel/Prometheus/structlog behind an `ObservabilityConfig` init; Kosmos formalizes the four verbs (`trace / score / log_cost / bind_context`) as a `Protocol` so plugins depend on the port not the vendors
  - `trace()` returns a `NoOpSpan` if the backend fails to open a span, so calling code never has to guard `with obs.trace(...):` — Rigpa's version implicitly assumed the backend was up
  - `log_cost()` writes both counters *and* attaches attributes to the currently active span (Rigpa only wrote counters), so trace views show spend inline with the request
  - `AgeBackend`-style Protocol seam (`OtelBackend`) mirrors the Stage 1.5 `PyrageBackend` split so tests never need any OTel wheel installed
  - `is_healthy` is non-throwing (ADR-023 rule 5); `close()` is idempotent — both stronger than Rigpa's originals
  - Langfuse (spec §4.1 aspirational) is deferred to a future second adapter for LLM-specific prompt/response/eval-score UX; ADR-025 sizes the trigger
- **ADR:** ADR-025
- **Logged:** 2026-07-29 21:52 EDT

### DataPort

#### rfc8785 (JCS canonicalizer) — `VENDORED` (Stage 1.10)
- **Source:** https://github.com/trailofbits/rfc8785.py
- **Commit / Version:** `rfc8785>=0.1.4` (verified via `gh api repos/trailofbits/rfc8785.py` on 2026-07-29)
- **License:** Apache-2.0 (SPDX: `Apache-2.0`)
- **Kosmos location:** runtime dep in `pyproject.toml`; used by `adapters/data/filesystem/adapter.py::JcsCanonicalizer` (lazy import at construction time)
- **Port(s):** DataPort
- **Modifications:** none — the wheel is invoked verbatim via `rfc8785.dumps(payload) -> bytes`. Contract tests use a pure-stdlib `SortedJsonCanonicalizer` double so tests do not depend on the wheel being installed.
- **ADR:** ADR-028
- **Logged:** 2026-07-29 22:35 EDT

#### cryptography — `VENDORED (deferred use)` (Stage 1.10)
- **Source:** https://github.com/pyca/cryptography
- **Commit / Version:** `cryptography>=49` (verified via `gh api repos/pyca/cryptography` on 2026-07-29)
- **License:** Apache-2.0 OR BSD-3-Clause (SPDX)
- **Kosmos location:** runtime dep in `pyproject.toml`; **not imported anywhere in Kosmos code at Stage 1.10**. Reserved for `Ed25519FileSigner` which lands at Stage 5 governance-key wiring (age-key-file-backed per ADR-024 SecretsPort pattern). Declared now so the dep exists at the moment the seam is populated, avoiding a future `pyproject` bump entangled with a governance ADR.
- **Port(s):** DataPort (via `Signer` Protocol seam)
- **Modifications:** none.
- **ADR:** ADR-028
- **Logged:** 2026-07-29 22:35 EDT

#### Rigpa-LMS knowsys export subsystem donor pattern — `VENDORED (pattern only; domain schema rejected)` (Stage 1.10)
- **Source:** https://github.com/rmholston420/Rigpa-LMS (user's own repo; permissively-licensed donor)
  - `plugins/knowsys/src/rigpa_knowsys/models/export.py` (`ExportEnvelope` SQLAlchemy row with `envelope_json_hash CHAR(64)` + Ed25519 base64 signature)
  - `plugins/knowsys/src/rigpa_knowsys/schemas/export.py` (Pydantic `ExportEnvelope` + `NoteExportItem` + `AttachmentRef` + `EXPORT_SIGNED_FIELDS` tuple + `signed_payload()`)
  - `plugins/knowsys/src/rigpa_knowsys/services/export_service.py` (`build_export_envelope / sign_envelope / verify_envelope_signature / import_envelope`)
  - `plugins/knowsys/src/rigpa_knowsys/routers/export.py` (FastAPI endpoints)
  - `plugins/knowsys/tests/test_export.py` (tampering, dedup, signature-failure test patterns)
  - `backend/src/rigpa/domains/knowledge/schema_registry.py` (`SchemaRegistry` + `SchemaValidationError`)
- **Commit / Version:** inspected at donor `main` on 2026-07-29 (cached at `/tmp/donor-dataport/`)
- **License:** user's own code; treated as permissive donor
- **Kosmos location:** `ports/data.py`, `adapters/data/filesystem/adapter.py`
- **Modifications:**
  - Rigpa's schema is **Knowsys-domain-locked** (PostgreSQL `Note`/`NoteAttachment` upsert, PARA folders, Ed25519 constitution key). Kosmos DataPort is **domain-neutral** — every plugin (Gnosis, Tektos, Oikos, Nomisma, Zetesis) will call `export_canonical` with its own `record_type`.
  - Rigpa uses `rigpa.domains.governance.constitution.signing.{canonicalize, sign, verify}` (Ed25519 with a live constitution key). Kosmos has no governance key at Stage 1.10 — signing is behind a pluggable `Signer` Protocol seam with `NoOpSigner` as Stage 1.10 primary. Envelopes remain hash-anchored (SHA-256 over JCS bytes) so DR-drill cross-verify per spec §187 still works. `Ed25519FileSigner` slots in at Stage 5 with zero port changes (mirrors ADR-027 seam pattern).
  - Rigpa persists envelopes as PostgreSQL rows in `notes_export_envelopes` with an `envelope_json_hash CHAR(64)` UNIQUE constraint providing dedup. Kosmos writes to `{root}/{record_type}/{sha256}.jsonld` — the filesystem path itself is the dedup key; matches project custom-instructions "single-user, local-first".
  - Rigpa has no `check_format_health` or `migrate_schema` verbs. Kosmos ships all three spec §4.1-line-93 verbs day-one per ADR-028 Q1=A (same discipline as ADR-027 Q1=A for MemoryPort).
  - Rigpa has no PII tier concept on the envelope. Kosmos requires a `pii_tier: PIITier` field per spec §150 four-tier classification; Restricted-tier records route under `{root}/restricted/{record_type}/` prefix to enable a future AES-256-at-rest wrapper (spec §147) at ops-deploy.
  - Rigpa has no never-overwrite migration guard. Kosmos ships one live at Stage 1.10 per spec §230/§232 (`MigrationTargetExists` raised on collision; idempotent same-hash re-runs allowed).
  - Rigpa signs a specific `EXPORT_SIGNED_FIELDS` subset. Kosmos signs the full envelope-minus-hash-minus-signature bytes; simpler contract, no field-inclusion registry to maintain.
- **ADR:** ADR-028
- **Logged:** 2026-07-29 22:35 EDT

#### FilesystemDataAdapter + three Protocol seams (`Canonicalizer` / `Signer` / `Storage`) — `KOSMOS-NATIVE` (Stage 1.10)
- **Source:** authored in this repo
- **Kosmos location:** `adapters/data/filesystem/adapter.py`
- **Port(s):** DataPort
- **Notes:** three injectable Protocol seams so contract tests run without any third-party imports; mirrors ADR-027 memory-adapter seam pattern (`GraphBackend` / `AmgPolicy` / `TemporalIndex`). Stage 1.10 primary composition: `SortedJsonCanonicalizer` (or `JcsCanonicalizer` in prod) + `NoOpSigner` + `FilesystemStorage`. Stage 5 governance-key wiring swaps in `Ed25519FileSigner` with zero port changes.
- **ADR:** ADR-028
- **Logged:** 2026-07-29 22:35 EDT

### ResourcePort

#### aiosqlite (`omnilib/aiosqlite`) — `VENDORED`
- **Source:** https://github.com/omnilib/aiosqlite
- **Commit / Version:** `>=0.20` (declared in `pyproject.toml` at Stage 1.11)
- **License:** MIT (verified via `gh api repos/omnilib/aiosqlite` on 2026-07-29; last push 2026-03-01, active)
- **Kosmos location:** runtime dep; lazy-imported inside `adapters/resource/sqlite/adapter.py::AioSqliteStorage.open`
- **Port(s):** `ResourcePort` (Storage seam)
- **Modifications:** none — upstream driver used unmodified.
- **Notes:** primary durable Storage backend at Stage 1.11. Opens one shared connection at adapter startup, enables `PRAGMA journal_mode=WAL`, reuses it for the whole adapter lifecycle (per spec §16 SQLite lifecycle rule). Contract tests use the pure-stdlib `InMemoryStorage` double so `aiosqlite` is not required to run the port's Protocol-conformance suite.
- **ADR:** ADR-029
- **Logged:** 2026-07-29 22:40 EDT

#### APEX `ResourceProtocol` pattern (`rmholston420/Rigpa-LMS`) — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (files: `backend/src/rigpa/domains/apex/protocols.py`, `.../models.py`, `.../service.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-resource/`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `ports/resource.py` (Protocol surface, six canonical kinds enum, Decimal balance semantics)
- **Port(s):** `ResourcePort`
- **Modifications:** dropped SQLAlchemy substrate (Rigpa's `Resource` ORM depends on `rigpa.db.base` + multi-tenant Users FK — domain-locked, incompatible with Kosmos single-user local-first per project custom instructions); reused pattern (six canonical kinds enum: time/money/attention/compute/knowledge/energy; `can_allocate/allocate/replenish` signatures; `NUMERIC(20,4)` Decimal precision preserved on the Port surface); made verbs async; added Q1=B priority-queue verbs (`enqueue`/`peek`/`dequeue`/`cancel`) per spec §172 fixed-order arbitration; added zero-trust port-level guard on all writes.
- **Notes:** matches ADR-028's rejection of Rigpa's Knowsys-domain-locked schema for the same domain-locking reason. Kosmos ports the pattern, not the ORM.
- **ADR:** ADR-029
- **Logged:** 2026-07-29 22:40 EDT

#### Rigpa-v2 priority-queue router pattern — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-v2 (file: `backend/src/rigpa/routers/priority_queue.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-resource/priority_queue.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `adapters/resource/sqlite/adapter.py` (priority-queue arbitration inside `SqliteResourceAdapter`)
- **Port(s):** `ResourcePort` (priority-queue verbs)
- **Modifications:** dropped FastAPI/Pydantic REST substrate (donor is HTTP-router-shaped, Kosmos ResourcePort is called in-process by plugins); reused pattern (UUID-keyed queue rows, `enqueue`/`peek`/`dequeue`/`cancel` verb naming, `(priority DESC, enqueued_at ASC)` ordering); replaced threaded in-memory dict with async SQLite (via `Storage` seam) so restarts don't wipe reservations (Build-Sequence §1.13 DoD + DR-drill §187 restart-durability); constrained donor's `priority: int 1-100` open scale to the fixed three-class `PriorityClass` IntEnum per spec §172 (`PHROUROS_ANOMALY=100 > TEKTOS_ACTIVE=50 > BACKGROUND=10`).
- **ADR:** ADR-029
- **Logged:** 2026-07-29 22:40 EDT

### NotificationPort

#### httpx (already vendored at ADR-021) — `VENDORED (reused)`
- **Source:** https://github.com/encode/httpx
- **Commit / Version:** existing project dep declared in `pyproject.toml` since Stage 1.1 (SearchPort)
- **License:** BSD-3-Clause (verified at ADR-021)
- **Kosmos location:** lazy-imported inside `adapters/notification/kernel/adapter.py::NtfySink._ensure_client`
- **Port(s):** `NotificationPort` (Sink seam via `NtfySink` stub)
- **Modifications:** none — upstream client used unmodified with `timeout=0.4` to protect Build-Sequence §1.12 <500ms DoD.
- **Notes:** no new runtime dep added at Stage 1.12; NtfySink reuses the existing httpx vendoring.
- **ADR:** ADR-030
- **Logged:** 2026-07-29 22:52 EDT

#### Rigpa-v2 `NotificationCenterService` pattern — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-v2 (files: `backend/src/rigpa/notifications/service.py`, `backend/src/rigpa/routers/notifications.py`, `backend/src/rigpa/routers/alerts.py`, `backend/src/rigpa/tektos/alert_service.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-notif/`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `adapters/notification/kernel/adapter.py::InProcessSink` (ring-buffer FIFO semantics + read/dismiss bookkeeping)
- **Port(s):** `NotificationPort` (primary Sink)
- **Modifications:** dropped FastAPI dependency-graph glue (Rigpa donor uses `Depends()` and `str` severity, domain-locked to Rigpa REST handlers); reused pattern (200-cap FIFO ring buffer, newest-first, per-notification UUID, thread-safe `RLock`, `read`/`dismissed` set bookkeeping, four-severity taxonomy); replaced open-set `str` severity with `AlgedonicTier` enum (INFO/WARN/ACTION/ALGEDONIC per spec §30/§280/§344); made verbs async; wrapped behind `Sink` Protocol seam so external sinks slot in without port-surface change.
- **Notes:** matches ADR-028/029 domain-locking rejection pattern. Kosmos ports the ring-buffer + read/dismiss pattern, not the FastAPI class.
- **ADR:** ADR-030
- **Logged:** 2026-07-29 22:52 EDT

#### Forge-OH `bff/routers/notifications.py` pattern — `PATTERN-VENDORED (reference only)`
- **Source:** https://github.com/rmholston420/Forge-OH (file: `bff/routers/notifications.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-notif/forge-notifications.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** reference for future kernel-dashboard-native `WebSocketSink` (deferred to Stage 1.14 FrontendContractPort landing)
- **Port(s):** `NotificationPort` (future dashboard-native Sink)
- **Modifications:** none at Stage 1.12; used as design reference for how the kernel dashboard will poll `InProcessSink.snapshot(limit)` at Stage 1.14.
- **ADR:** ADR-030
- **Logged:** 2026-07-29 22:52 EDT

### FrontendContractPort

#### Rigpa-LMS `RigpaFrontendPlugin` shape — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (file: `frontend/src/plugins/dashboard/index.ts`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-frontend/rigpa-dashboard-index.ts`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `ports/frontend_contract.py::PluginDescriptor` (Python dataclass mirror of donor TypeScript shape)
- **Port(s):** `FrontendContractPort` (primary descriptor shape)
- **Modifications:** ported donor `RigpaFrontendPlugin` shape (`name`, `stateNamespace`, `designTokens`, `routes` — each route with `path`/`label`/`icon` + lazy loader) to Python `PluginDescriptor` frozen dataclass; renamed camelCase to snake_case; typed `routes` as `tuple[Route, ...]` with `lazy_module: str` (frontend resolves via `import(lazy_module)`); extended with Kosmos-specific fields (`version`, `kernel_compat`, `panels: tuple[Panel, ...]`) driven by spec §280 nine-panel kernel dashboard; rejected donor `PluginRoutes.tsx` React-Suspense mount code as too domain-locked to Rigpa file-relative lazy semantics.
- **Notes:** kernel-side authority is Python (this port); frontend-side Next.js/React 19/Radix/shadcn/ui/Tailwind/Zustand/TanStack Query shell lands separately per spec §21.3.5 and consumes `KernelSchema` via HTTP.
- **ADR:** ADR-031
- **Logged:** 2026-07-29 23:05 EDT

#### Rigpa-LMS backend `RigpaPlugin` lifecycle protocol — `PATTERN-VENDORED (reference only)`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (file: `backend/src/rigpa_core/plugins/scaffold_plugin.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-frontend/rigpa-scaffold-plugin.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** reference for backend lifecycle contract (`startup`/`shutdown`/`health_check`) — not vendored at Stage 1.14; Kosmos exposes `is_healthy()` / `close()` on the port itself.
- **Port(s):** `FrontendContractPort` (informs future `PluginLifecyclePort` if needed)
- **Modifications:** none at Stage 1.14; Kosmos treats backend plugin lifecycle as orthogonal to frontend UI-schema publication.
- **ADR:** ADR-031
- **Logged:** 2026-07-29 23:05 EDT

#### `pathlib` + `json` (stdlib) — `VENDORED (reused stdlib)`
- **Source:** Python 3.12 standard library
- **Commit / Version:** stdlib
- **License:** PSF-2.0
- **Kosmos location:** `adapters/frontend_contract/kernel/adapter.py::FileManifestStore`
- **Port(s):** `FrontendContractPort` (ManifestStore stub for Stage 5 auditor wiring)
- **Modifications:** used unmodified with atomic tmp-rename write via `tempfile.mkstemp` + `Path.replace`; no new runtime dependency added at Stage 1.14.
- **Notes:** primary storage is `InMemoryManifestStore` (dict-backed) which is sufficient for §1.14 DoD; `FileManifestStore` is present as a proven-swappable stub only.
- **ADR:** ADR-031
- **Logged:** 2026-07-29 23:05 EDT

---

## Governance (Praxis / Phrouros)

### Praxis Constitution Loader

#### Rigpa-LMS `signing.py` (Ed25519 + JCS primitives) — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (file: `backend/src/rigpa/domains/governance/constitution/signing.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-constitution/signing.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `plugins/praxis/constitution/signing.py`
- **Port(s):** Praxis constitution boot-verification subsystem
- **Modifications:** swapped donor `jcs` (MIT) for Kosmos-native `rfc8785` (Apache-2.0, already a DataPort §1.10 dependency) to avoid dual RFC-8785 implementations; preserved `canonicalize`/`sign`/`verify`/`load_public_key`/`load_private_key` signatures verbatim; type-annotations retained; behavior identical (`verify` returns `bool`, never raises on signature failure).
- **ADR:** ADR-032
- **Logged:** 2026-07-29 23:15 EDT

#### Rigpa-LMS `verifier.py` (ConstitutionVerifier facade) — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (file: `backend/src/rigpa/domains/governance/constitution/verifier.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-constitution/verifier.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `plugins/praxis/constitution/verifier.py`
- **Port(s):** Praxis constitution boot-verification subsystem
- **Modifications:** default pubkey path relocated from Rigpa's `Path(__file__).with_name("pubkey.pem")` (co-located with verifier module) to Kosmos's `governance/constitution/pubkey.pem` (separate governance artifact tree); replaced donor `SignatureDecodeError(ValueError)` and bare `RuntimeError` raises with the Kosmos `ConstitutionError` hierarchy (`ConstitutionNotFoundError` for missing pubkey, `ConstitutionMalformedError` for unparseable PEM, boolean `False` return for signature-mismatch — matching donor's non-raising `verify()` semantics). No new runtime dependency.
- **ADR:** ADR-032
- **Logged:** 2026-07-29 23:15 EDT

#### Rigpa-LMS `amend_service.py` / `cli.py` / `service.py` / `models.py` / `schemas.py` — `PATTERN-VENDORED (reference only, deferred to Synedrion)`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (files: `backend/src/rigpa/domains/governance/constitution/{amend_service,cli,service,models,schemas}.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** none at Stage 2.1; deferred to Synedrion (Phase 6.3) per spec §278.
- **Port(s):** Praxis constitution boot-verification subsystem (future amendment surface only)
- **Modifications:** Kosmos does not ship the amendment workflow (donor `amend_service.py`: 157 lines proposing/signing/ratifying `ConstitutionAmendment` rows), CLI (donor `cli.py`: 164 lines), read HTTP surface (donor `service.py`: 74 lines list/diff/get_current), SQLAlchemy schema (donor `models.py`: 83 lines `ConstitutionVersion` + `ConstitutionAmendment` tables), or Pydantic serialization (donor `schemas.py`: 77 lines) at Stage 2.1. Spec §278 ties amendment CLI/UI landing to Synedrion (Phase 6.3). When Synedrion lands, it will re-vendor these five files and MUST cite this ledger entry.
- **ADR:** ADR-032 (deferred surface); future Synedrion ADR will supersede this entry.
- **Logged:** 2026-07-29 23:15 EDT

#### `rfc8785`, `cryptography`, `PyYAML` — `VENDORED (reused existing Kosmos deps)`
- **Source:** https://github.com/di/rfc8785.py, https://github.com/pyca/cryptography, https://github.com/yaml/pyyaml
- **Commit / Version:** `rfc8785>=0.1.4` (Apache-2.0), `cryptography>=49` (Apache-2.0 OR BSD-3), `PyYAML>=6.0` (MIT) — all three already declared in `pyproject.toml` from Stage 1.10 (DataPort) and Stage 1.5 (SecretsPort spike).
- **License:** Apache-2.0 / Apache-2.0 OR BSD-3 / MIT
- **Kosmos location:** `plugins/praxis/constitution/{signing.py,loader.py}`
- **Port(s):** Praxis constitution boot-verification subsystem
- **Modifications:** used unmodified. `rfc8785.dumps()` for JCS canonicalization (RFC 8785); `cryptography.hazmat.primitives.asymmetric.ed25519` for Ed25519 sign/verify; `yaml.safe_load` for YAML parse. Zero new runtime dependencies added at Stage 2.1.
- **ADR:** ADR-032
- **Logged:** 2026-07-29 23:15 EDT

---

#### agent-governance-toolkit — `PLANNED`
- **Source:** TBD (log at vendoring)
- **License:** verify permissive
- **Port(s):** governance internals
- **Logged:** —

---

### APEX Change Approval Tier engine

#### Rigpa-LMS `apex/protocols.py` (ChangeApprovalProtocol + Storage + Scheduler seams) — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (file: `backend/src/rigpa/domains/apex/protocols.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-apex/protocols.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `plugins/praxis/apex/protocol.py`
- **Port(s):** APEX change-approval subsystem (ADR-033)
- **Modifications:** kept the three-Protocol shape (`ChangeApprovalProtocol` + `Storage` + `Scheduler`) but replaced donor SQLAlchemy-flavored fields with stdlib-only frozen dataclasses; adapted verbs to explicit `async` (donor used sync + `run_in_executor`); added `SchedulerHandle` value object so `cancel(handle)` can round-trip through `FakeScheduler` without a global registry.
- **ADR:** ADR-033
- **Logged:** 2026-07-29 23:44 EDT

#### Rigpa-LMS `apex/models.py` (Intention + ApprovalRecord donor shape) — `PATTERN-VENDORED`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (file: `backend/src/rigpa/domains/apex/models.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-apex/models.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `plugins/praxis/apex/models.py`
- **Port(s):** APEX change-approval subsystem (ADR-033)
- **Modifications:** stripped SQLAlchemy Base + Column declarations; retained field names (`id`/`subject`/`target_trajectory`/`current_state`/`owning_domain`/`change_approval_tier`) so a future SqliteStorage adapter can round-trip donor-schema rows; added `ApprovalStatus` + `Trigger` enums as `str, Enum` for JSON-serializable event payloads; introduced `new_id()` + `utc_now()` helpers to keep call sites free of `uuid`/`datetime` imports.
- **ADR:** ADR-033
- **Logged:** 2026-07-29 23:44 EDT

#### Rigpa-LMS `apex/service.py` (state machine + tier semantics) — `PATTERN-VENDORED (rewritten async-first)`
- **Source:** https://github.com/rmholston420/Rigpa-LMS (file: `backend/src/rigpa/domains/apex/service.py`)
- **Commit / Version:** inspected at HEAD 2026-07-29 (cached at `/tmp/donor-apex/service.py`)
- **License:** internal donor (rmholston420); Kosmos vendors pattern only, not source.
- **Kosmos location:** `plugins/praxis/apex/engine.py`
- **Port(s):** APEX change-approval subsystem (ADR-033)
- **Modifications:** retained the three-tier state machine (AUTONOMOUS auto-approve; HUMAN_REVIEW single-shot timer; HUMAN_REQUIRED escalating cadence) and the resolve-cancels-timers invariant; replaced donor sync-notification calls with `NotificationPort.notify()` + `deliver_algedonic()` (ADR-030 surface); routed events through kernel `EventBusPort` with `producer_plugin="praxis"` per ADR-023; pre-schedules HUMAN_REQUIRED cadence up to a 30-day horizon that self-refreshes on fire (donor scheduled ticks one at a time on each callback). Rewrote every verb as `async` end-to-end; introduced `_handles` dict per approval so `resolve()` cancels the full pending set atomically.
- **ADR:** ADR-033
- **Logged:** 2026-07-29 23:44 EDT

#### `rfc8785`, `cryptography`, `aiosqlite`, `PyYAML` — `VENDORED (reused existing Kosmos deps)`
- **Source:** https://github.com/di/rfc8785.py, https://github.com/pyca/cryptography, https://github.com/omnilib/aiosqlite, https://github.com/yaml/pyyaml
- **Commit / Version:** `rfc8785>=0.1.4` (Apache-2.0), `cryptography>=49` (Apache-2.0 OR BSD-3), `aiosqlite>=0.20` (MIT), `PyYAML>=6.0` (MIT) — all four already declared in `pyproject.toml` from earlier Stage 1 ports (DataPort §1.10, SecretsPort §1.5, ResourcePort §1.11, Constitution Loader §2.1).
- **License:** Apache-2.0 / Apache-2.0 OR BSD-3 / MIT / MIT
- **Kosmos location:** `plugins/praxis/apex/{tokens.py,storage.py}`
- **Port(s):** APEX change-approval subsystem (ADR-033)
- **Modifications:** used unmodified. `rfc8785.dumps()` canonicalizes mobile-token payloads; `cryptography.hazmat.primitives.asymmetric.ed25519` provides Ed25519 sign/verify + PEM (de)serialization for the SecretsPort-backed signing key; `aiosqlite` will back the `SqliteStorage` durable adapter at Stage 5 (Stage 2.2 ships only the schema-documented stub). Zero new runtime dependencies added at Stage 2.2.
- **ADR:** ADR-033
- **Logged:** 2026-07-29 23:44 EDT

### Phrouros anomaly detector

#### Phrouros — `GREENFIELD` (no vendored OSS)
- **Source:** none. Phrouros is entirely greenfield Kosmos code. No permissively-licensed upstream anomaly-detection framework was adopted at Stage 2.3 — the surface is small (one real detector + three skeletons + an in-memory pub/sub feed), stdlib-only implementations satisfied every DoD, and every existing candidate (arize-phoenix, evidently, langfuse-python's client-side alerts) either drags a runtime (Postgres / cloud SaaS / OpenTelemetry heavyweight collector) or violates the local-first / single-user posture of ADR-005 / ADR-025.
- **Commit / Version:** —
- **License:** —
- **Kosmos location:** `plugins/phrouros/` (detector.py, detectors/{loop,model_swap_slo,stub_degradation,bus_factor_1}.py, engine.py, errors.py, models.py, plugin.py, tests/) + `ports/trace_feed.py` (new port module — sibling to writer-only ObservabilityPort per Q2=A).
- **Port(s):** TraceFeedPort (new, reader-only), NotificationPort (algedonic path), ResourcePort (compute reservation + fallback enqueue), EventBusPort (`phrouros.anomaly.detected` with `producer_plugin="praxis"`), FrontendContractPort (`AGENT_TRACE` panel).
- **Modifications:** stdlib-only. `asyncio` for pub/sub + engine loop, `collections.deque` for sliding-window history in `LoopDetector`, `dataclasses` for value objects, `decimal.Decimal` for compute reservation size (32 GB VRAM per §172), `datetime` for wall-clock windowing. Zero new runtime dependencies added at Stage 2.3.
- **Skeleton detectors:** `ModelSwapSloDetector` (§172 — Stage 3+), `StubDegradationDetector` (§273 — Stage 3+), `BusFactor1Detector` (§613 — Stage 6.5). All three raise `DetectorNotImplementedError` from `detect(...)` and `build_payload(...)`. When each stage lands, the real implementation ships in the same module and this ledger entry gets a follow-up sub-block.
- **ADR:** ADR-034
- **Logged:** 2026-07-30 00:15 EDT

---

### Stage-2 exit gate (AnomalyBridge + Tektos stub)

#### `AnomalyBridge` — `GREENFIELD` (no vendored OSS)
- **Source:** none. Bridge is entirely greenfield Kosmos code. No upstream framework was adopted at Stage 2.4 — the surface is a 1-topic subscribe → translate → propose → audit-publish loop that stdlib `asyncio` already supplies. Every candidate (celery, dramatiq, faststream, dispatch libs) either drags a broker runtime (Redis/RabbitMQ beyond kernel EventBus), a decorator surface incompatible with `EventBusPort.subscribe()` returning `asyncio.Queue`, or a plugin registry that would violate ADR-007 (would need to import Phrouros types).
- **Commit / Version:** —
- **License:** —
- **Kosmos location:** `plugins/praxis/apex/bridge.py` (Praxis-internal peer service; NOT owned by `PraxisPlugin`, matches ADR-033 decoupled-construction pattern) + `plugins/praxis/apex/tests/test_anomaly_bridge.py`.
- **Port(s):** EventBusPort (subscribe `phrouros.anomaly.detected`, publish `praxis.escalation.proposed`), APEX `ChangeApprovalProtocol` (`propose(tier=HUMAN_REQUIRED, proposing_domain="phrouros")`).
- **Modifications:** stdlib-only. `asyncio.Task` for background drain, `asyncio.Queue` (returned by `EventBusPort.subscribe`) as the ingress buffer, `ast` for the ADR-007 static-import check in tests. Zero new runtime dependencies at Stage 2.4. Design invariants: (a) idempotent `start()` / `stop()` (double-start no-op, double-stop no-op); (b) per-envelope errors caught + logged, one bad envelope cannot stop the escalator; (c) `stop()` cancels the background task, awaits it, then unsubscribes; (d) zero `plugins.phrouros` imports — event type is a duplicated local literal `EVENT_PHROUROS_ANOMALY_DETECTED = "phrouros.anomaly.detected"`, envelope payload read by string keys only; AST-verified in `test_bridge_never_imports_phrouros`.
- **ADR:** ADR-035
- **Logged:** 2026-07-30 00:35 EDT

#### `TektosSimulator` — `GREENFIELD` (test-only, no vendored OSS)
- **Source:** none. Test-only harness at Stage 2.4 to drive the exit-gate scenario. No upstream framework applicable — the simulator is a plain dataclass with three methods (`simulate_unauthorized_call` / `simulate_authorized_call` / `simulate_loop`) composed with an injected `TraceFeedPort`. Deleted or superseded at Stage 3 by the real Tektos coding plugin (Q6=A).
- **Commit / Version:** —
- **License:** —
- **Kosmos location:** `plugins/tektos/` (`__init__.py` namespace) + `plugins/tektos/stub/` (`__init__.py` re-export, `simulator.py`) + `plugins/tektos/tests/` (`__init__.py`, `test_stage_2_4_exit_gate.py`). Registered under `pyproject.toml` setuptools packages.
- **Port(s):** TraceFeedPort only (consumer via injected `trace_feed`).
- **Modifications:** stdlib-only. `dataclasses` for construction, `datetime` for `TraceEvent.timestamp`, `uuid` for `trace_id` / event ids. No `PluginDescriptor`, no `LifecyclePort` verbs, no `AGENT_TRACE` panel — the simulator is not a plugin. Design invariants: (a) `simulate_unauthorized_call(tool_name)` publishes one `TraceEvent(plugin="tektos", tool_name=<denied>)`; (b) `simulate_authorized_call(tool_name)` publishes a `TraceEvent(plugin="tektos", tool_name=<allowed>)`; (c) `simulate_loop(tool_name, count, window_s)` publishes N events at deterministic offsets within a window — drives the Stage-2.3 `LoopDetector` deterministically in the gate.
- **Deletion trigger:** Stage 3 real Tektos MVP (spec §3). When Tektos ships a real `PluginDescriptor` + LangGraph runtime, the entire `plugins/tektos/stub/` tree is deleted and this ledger entry is superseded by the Stage-3 Tektos entry.
- **ADR:** ADR-035
- **Logged:** 2026-07-30 00:35 EDT

---

## Tektos (Coding Plugin)

#### OpenHands SDK — `PATTERN-VENDORED (Stage 3.1)`
- **Source:** https://github.com/OpenHands/software-agent-sdk
- **Upstream commit:** `4b132eddb6cf414841439a46ce42ed2cd66a628a` (main branch, checked 2026-07-30)
- **License:** MIT
- **Kosmos location:** `plugins/tektos/agent.py` (no upstream source copied into the tree)
- **Port(s):** LLMPort (consumer of `generate_text`), MemoryPort (consumer of `query_temporal` + `write_event` with zero-trust `provenance`+`confidence`)
- **Modifications:** pattern-vendor — the `Agent`/`Conversation` public shape (`send_message()` + `run()`) is preserved and reimplemented in Kosmos-native Python over Kosmos ports; upstream Pydantic models, LiteLLM binding, sandboxed runtime, and tool framework are NOT ported at Stage 3.1 (main-repo runtime patterns arrive at Stage 3.2 with MCP transport). Every completed turn writes with fixed provenance `tektos_agent` + caller confidence in `(0.0, 1.0]` per ADR-008.
- **ADR:** ADR-036
- **Logged:** 2026-07-30 00:52 EDT

#### MCP python-sdk — `PATTERN-VENDORED`
- **Source:** https://github.com/modelcontextprotocol/python-sdk
- **Commit / Version:** `a4f4ccd091138771535e17191123f20b30fda68e`
- **License:** MIT
- **Kosmos location:** `ports/mcp.py` (Protocol + value objects, `MCP_PROTOCOL_VERSION="2024-11-05"`), `adapters/mcp/in_process/adapter.py` (in-process `MCPServer`), `adapters/mcp/stdio/adapter.py` (JSON-RPC-over-stdio client)
- **Port(s):** `MCPPort` (new at Stage 3.2)
- **Modifications:** PATTERN-VENDORED — no upstream source copied. Client-side JSON-RPC verbs (`initialize`, `tools/list`, `tools/call`) reimplemented from scratch behind `MCPPort` Protocol; zero new pip deps. In-process adapter added for deterministic tests; `MCPServer` Protocol added so plugins can provide fakes.
- **ADR:** ADR-037
- **Logged:** 2026-07-30 01:15 EDT

#### Playwright-MCP — `PATTERN-VENDORED`
- **Source:** https://github.com/microsoft/playwright-mcp
- **Commit / Version:** `55679f5f3d4b4f3e2534ec0ce2fc5683ba2eaf3f` (real subprocess); `plugins/tektos/mcp/fake_playwright_server.py` for deterministic tests
- **License:** Apache-2.0
- **Kosmos location:** `plugins/tektos/mcp/fake_playwright_server.py` (deterministic in-process fake with `browser_navigate` + `browser_snapshot` + `.invocations` recording); `adapters/mcp/stdio/adapter.py::playwright_stdio_adapter()` factory (spawns `npx -y @playwright/mcp@latest`); env-gated real integration test at `plugins/tektos/tests/test_playwright_stdio_integration.py`
- **Port(s):** `MCPPort` (consumed by `TektosAgent.call_tool`)
- **Modifications:** PATTERN-VENDORED — no upstream source copied. Real subprocess launched via `npx` when `KOSMOS_STAGE_32_REAL_PLAYWRIGHT=1`; not part of `make stage1-gate`. Fake server hard-codes tool schemas for `browser_navigate` / `browser_snapshot` and records invocations for test assertions.
- **ADR:** ADR-037
- **Logged:** 2026-07-30 01:15 EDT

#### aider repomap — `PATTERN-VENDORED`
- **Source:** https://github.com/Aider-AI/aider
- **Commit / Version:** `5dc9490bb35f` (upstream `aider/repomap.py` at 867 lines used as reference; only `.scm` query files copied verbatim)
- **License:** Apache-2.0
- **Kosmos location:** `plugins/tektos/repomap/{__init__,policy,tags,rank,render,indexer}.py` (in-tree reimplementation) + `plugins/tektos/repomap/queries/{python,javascript,typescript,rust,go,bash}-tags.scm` (verbatim vendored, attribution in `queries/ATTRIBUTION.md`)
- **Port(s):** consumed via `MemoryPort` only (no new port surface — Tektos-internal per ADR-023 envelope-first defer; `RepoMapPort` deferred until second consumer)
- **Modifications:** PATTERN-VENDOR — upstream `RepoMap` class rewritten as pure functions across five modules (`policy`, `tags`, `rank`, `render`, `indexer`) so no aider IO/CLI/Model coupling leaks in. `MemoryPort.write_event` calls emit locked provenance `"aider-repomap"` and confidence via `compute_freshness_confidence()` (linear-decay over 30-day window, floor 0.01 to satisfy ADR-008 zero-trust guard). Per-file `tektos.repomap.indexed` + per-run `tektos.repomap.snapshot` writes. NetworkX `pagerank_scipy` backend used for ranking (matches upstream). Tree-sitter cache directory `.kosmos.repomap.cache.v4` matches upstream `USING_TSL_PACK=True` `CACHE_VERSION=4`.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### tree-sitter — `PLANNED`
- **Source:** https://pypi.org/project/tree-sitter/ (>=0.24)
- **License:** MIT
- **Kosmos location:** used only inside `plugins/tektos/repomap/tags.py`
- **Port(s):** none directly (consumed by repomap module only)
- **Modifications:** none. Consumes the tree-sitter 0.23/0.24 API split (`Query.captures()` vs. `QueryCursor.captures()`) via a version-adaptive `_run_query` helper.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### tree-sitter-language-pack — `PLANNED`
- **Source:** https://pypi.org/project/tree-sitter-language-pack/ (>=1.13)
- **License:** MIT
- **Kosmos location:** loaded lazily inside `plugins/tektos/repomap/tags.py`
- **Port(s):** none directly (consumed by repomap module only)
- **Modifications:** none. Used purely to obtain compiled tree-sitter language grammars for `python`, `javascript`, `typescript`, `rust`, `go`, `bash`.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### networkx — `PLANNED`
- **Source:** https://pypi.org/project/networkx/ (>=3.4)
- **License:** BSD-3-Clause
- **Kosmos location:** used only inside `plugins/tektos/repomap/rank.py`
- **Port(s):** none directly (consumed by repomap module only)
- **Modifications:** none. `MultiDiGraph` + `pagerank_scipy(personalization=...)` reimplementation of aider's PageRank + ident-heuristic identifier weighting.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### scipy — `PLANNED`
- **Source:** https://pypi.org/project/scipy/ (>=1.14)
- **License:** BSD-3-Clause
- **Kosmos location:** transitive consumer for `networkx.pagerank_scipy` sparse backend
- **Port(s):** none directly (indirect via networkx)
- **Modifications:** none.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### grep-ast — `PLANNED`
- **Source:** https://pypi.org/project/grep-ast/ (>=0.9)
- **License:** Apache-2.0
- **Kosmos location:** used only inside `plugins/tektos/repomap/render.py`
- **Port(s):** none directly (consumed by repomap module only)
- **Modifications:** none. `TreeContext` used to produce the aider-style tree-context render.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### pygments — `PLANNED`
- **Source:** https://pypi.org/project/Pygments/ (>=2.18)
- **License:** BSD-2-Clause
- **Kosmos location:** used only inside `plugins/tektos/repomap/tags.py` as fallback for defs-only lexing when tree-sitter query returns no captures
- **Port(s):** none directly (consumed by repomap module only)
- **Modifications:** none.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### diskcache — `PLANNED`
- **Source:** https://pypi.org/project/diskcache/ (>=5.6)
- **License:** Apache-2.0
- **Kosmos location:** used only inside `plugins/tektos/repomap/tags.py` for the per-file tag cache under `<repo-root>/.kosmos.repomap.cache.v4`
- **Port(s):** none directly (consumed by repomap module only)
- **Modifications:** none. Cache keyed by `(path, mtime)`; entry invalidated on mtime change; matches upstream aider caching.
- **ADR:** ADR-038
- **Logged:** 2026-07-29 23:04 EDT

#### Bernstein Janitor — `EVALUATING` (spike per ADR-004)
- **Source:** log full URL at spike setup
- **License:** verify permissive before spike
- **Port(s):** internal Tektos loop
- **Adoption rule:** adopt iff fixture beats `local-agentic-loop-sample`
- **ADR:** ADR-004 (adr-bernstein-vendor)
- **Logged:** —

#### local-agentic-loop-sample — `PLANNED (baseline)`
- **Source:** TBD
- **License:** verify permissive
- **Port(s):** internal Tektos loop
- **Status note:** kept as baseline; may be superseded by Bernstein Janitor if spike passes
- **Logged:** —

#### Reflexion — `PLANNED`
- **Source:** https://github.com/noahshinn/reflexion (or canonical)
- **License:** MIT
- **Port(s):** MemoryPort (self-improvement traces)
- **Logged:** —

#### Voyager — `PLANNED`
- **Source:** https://github.com/MineDojo/Voyager
- **License:** MIT
- **Port(s):** MemoryPort
- **Logged:** —

#### OpenSpec — `PATTERN-VENDORED`
- **Source:** https://github.com/Fission-AI/OpenSpec
- **Commit / Version:** `2b3d368539132be6311e55db58899abbf5306b81`
- **License:** MIT
- **Kosmos location:** `plugins/tektos/openspec/{policy.py,models.py,parser.py,plan.py,__init__.py}`
- **Port(s):** Tektos-internal (deferred per ADR-023 envelope-first; port surface deferred until a second consumer emerges)
- **Modifications:** Reimplemented in Python (upstream is TypeScript/Node CLI); no upstream source files copied verbatim; algorithm ported from upstream `docs/concepts.md`, `docs/opsx.md`, and `openspec/changes/fix-spec-parser-fidelity/` unified-reader design. Kosmos parser is stdlib-only (no Node subprocess), fence-mask-aware, and writes through `MemoryPort` with `provenance="openspec-parser"`.
- **ADR:** ADR-005 · ADR-040
- **Logged:** 2026-07-30 EDT

#### spec-kit — `PLANNED`
- **Source:** TBD
- **License:** verify
- **Port(s):** FrontendContractPort
- **ADR:** ADR-005 · ADR-041
- **Note:** ADR-041 Q10=Option X defer — Stage 3.7 plan renderer landed pure-Python over the Stage 3.6 `Plan` dataclass (`plugins/tektos/renderer/`); Spec Kit vendor selection deferred until a later stage first requires it. ADR-005 "named alternative mode" position preserved verbatim.
- **Logged:** 2026-07-30 EDT

#### Pier eval harness — `VENDORED (dev dep, Stage 3.8)`
- **Source:** <https://github.com/datacurve-ai/pier>
- **Commit / Version:** upstream `fefa7475a32bb05271abdea378e8083c83eb5c35`; PyPI `datacurve-pier==0.3.0`
- **License:** Apache-2.0
- **Kosmos location:** `pyproject.toml [project.optional-dependencies] eval`; subprocess-only integration at `plugins/tektos/eval/harness.py` + kernel runner `scripts/pier_eval.py`
- **Port(s):** internal (no new port surface — envelope-first per ADR-023; verdicts flow into existing `MemoryPort`)
- **Modifications:** none — invoked as `pier run` subprocess through public CLI; trajectory JSON parsed into `TrialVerdict`
- **ADR:** ADR-006 (superseded) · ADR-042 (Ratified v25, authoritative)
- **Logged:** 2026-07-30 EDT

#### DeepSWE corpus subset — `VENDORED (manifest-only, Stage 3.9)`
- **Source:** https://github.com/datacurve-ai/deep-swe
- **Commit / Version:** `e016041a6ccf8da29906afc9a3f5a8df940a1f78` (2026-07-22)
- **License:** Apache-2.0 (upstream corpus repo); per-task SPDX verified below
- **Kosmos location:** `plugins/tektos/eval/corpora/deepswe/manifest.toml` (authoritative record); on-demand hydration into git-ignored `.eval-cache/deepswe/<commit>/tasks/`
- **Port(s):** none (Tektos-internal, envelope-first per ADR-023 — matches ADR-038 repomap + ADR-042 Pier decisions)
- **Modifications:** none — no upstream source copied; the manifest names 5 tasks (3 Python + 2 TypeScript) chosen deterministically by task-id sort from the 113-task corpus
- **ADR:** ADR-007-DeepSWE (Ratified v25, STATUS AMENDMENT 2026-07-30 pins the scope + defers DoD clause 3)
- **Logged:** 2026-07-30 EDT

**Pinned 5-task subset (per-task SPDX verified via GitHub API against each upstream repo):**

| task_id | language | upstream repo | base commit | SPDX |
|---|---|---|---|---|
| `adaptix-name-mapping-aliases` | python | `reagento/adaptix` | `a691069fcadf9131e5f7a5a130a022dc678f3e1d` | Apache-2.0 |
| `aiomonitor-task-snapshots-diff` | python | `aio-libs/aiomonitor` | `b73fea2e0682803bda7531c93cd1dfb360839175` | Apache-2.0 |
| `bandit-incremental-cache-control` | python | `PyCQA/bandit` | `765f00d3f202f83f61d03f882f80a2d5142d81f8` | Apache-2.0 |
| `arktype-json-schema-refs-dependencies` | typescript | `arktypeio/arktype` | `04355e8b26d1ad5264ef62314a2bc46c4de58ed8` | MIT |
| `awilix-async-container-initialization` | typescript | `jeffijoe/awilix` | `82ac179c1de4c216c4e333093044fac643303f0c` | MIT |

#### docling — `VENDORED (dev dep, Stage 3.10)`
- **Source:** https://github.com/docling-project/docling
- **Commit / Version:** `ba8251e9cda84bab44cebe3b884119d3f50cb12a` (PyPI `docling==2.116.0`)
- **License:** MIT
- **Kosmos location:** `pyproject.toml` `[project.optional-dependencies] ingest = ["docling==2.116.0"]` (dev-only; lazy import inside `plugins/tektos/ingest/harness.py::resolve_default_converter_factory`)
- **Port(s):** DataPort (envelope-first per ADR-023 — no new port surface added; canonical JSON-LD emitted via `DataPort.export_canonical`)
- **Modifications:** none — PATTERN-VENDOR (no upstream source copied; docling invoked through its own `docling.document_converter.DocumentConverter().convert(source).document.export_to_dict()` + `.export_to_markdown()` public API)
- **ADR:** ADR-044
- **Logged:** 2026-07-30 04:20 EDT

#### htmx — `VENDORED (Stage 3.11, ADR-045)`
- **Source:** https://github.com/bigskysoftware/htmx
- **Commit / Version:** `b82cf843e47e575dd8c2ad8fee547d8e2c3bb87f` (release tag `v2.0.4`)
- **License:** 0BSD (upstream `LICENSE` file, verified 2026-07-30; SPDX `0BSD`, permissively compatible)
- **Kosmos location:** `plugins/tektos/ui/htmx.min.js` (50917 bytes, sha256 `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447`); served in-process via `plugins.tektos.ui.server` route `/htmx.min.js`
- **Port(s):** none (browser-side runtime asset — no server port surface)
- **Modifications:** none — verbatim minified upstream artifact
- **ADR:** ADR-045
- **Logged:** 2026-07-30 05:14 EDT

#### fastapi — `VENDORED (Stage 3.11, ADR-045)`
- **Source:** https://github.com/fastapi/fastapi
- **Commit / Version:** PyPI `fastapi>=0.115` (dev install pinned at 0.141.1)
- **License:** MIT
- **Kosmos location:** `pyproject.toml` `[project.optional-dependencies] ui = ["fastapi>=0.115", "uvicorn>=0.32", "httpx>=0.27"]`; imported inside `plugins.tektos.ui.server.build_tektos_ui_app` (lazy import guarded so absence does not break the kernel import graph)
- **Port(s):** none (HTTP framework hosting the Tektos UI HTMX dashboard)
- **Modifications:** none — public API only
- **ADR:** ADR-045
- **Logged:** 2026-07-30 05:14 EDT

#### uvicorn — `VENDORED (Stage 3.11, ADR-045)`
- **Source:** https://github.com/encode/uvicorn
- **Commit / Version:** PyPI `uvicorn>=0.32` (dev install pinned at 0.52.0)
- **License:** BSD-3-Clause
- **Kosmos location:** `pyproject.toml` `[project.optional-dependencies] ui` (see htmx entry); invoked by `scripts/tektos_ui.py` for the env-gated interactive tier and `make ui-serve`
- **Port(s):** none (ASGI server for the UI process)
- **Modifications:** none — public CLI/API only
- **ADR:** ADR-045
- **Logged:** 2026-07-30 05:14 EDT

#### ruff — `VENDORED (dev dep)`
- **Source:** https://github.com/astral-sh/ruff
- **License:** MIT
- **Kosmos location:** `pyproject.toml` dev dep + pre-commit hook
- **Port(s):** none (build-time only)
- **Logged:** —

#### bandit — `VENDORED (dev dep)`
- **Source:** https://github.com/PyCQA/bandit
- **Commit / Version:** `bandit>=1.7` (installed 1.9.4)
- **License:** Apache-2.0
- **Kosmos location:** `[project.optional-dependencies] dev` + `[tool.bandit]` config in `pyproject.toml`
- **Port(s):** none (build-time only)
- **Modifications:** none — invoked via `.venv/bin/bandit -q -c pyproject.toml -r <path>` inside `scripts/stage3_gate.py` and via `make stage3-gate`
- **ADR:** ADR-046
- **Logged:** 2026-07-30 05:38 EDT

#### Tektos reflection + synthesis + experience-replay engines — `VENDORED (Stage 8.3, ADR-105)`
- **Source:** `rmholston420/tektos-ultima` (donor absorbed under FULL FORK + REWRITE license posture; re-licensed at port-in point per ADR-092)
- **Donor modules:** `src/tektos/reflection.py` (ReflectionEngine); `src/tektos/synthesis.py` (SynthesisEngine); `src/tektos/experience.py` (ExperienceReplay)
- **License:** MIT (kosmos-lms declares MIT; rmholston420 sole copyright holder)
- **Kosmos location:** `plugins/tektos/reflection/{__init__.py,models.py,engine.py,api.py}`; `plugins/tektos/synthesis/{__init__.py,models.py,engine.py,api.py}`; `plugins/tektos/experience/{__init__.py,models.py,replay.py,api.py}`; kernel wiring at `kernel/app.py::_boot_stage_8_x_engine` (originally `_boot_stage_8_3_engine`; renamed at 8.4)
- **Port(s):** `RelationalMemoryPort` (via `write_narrative`); `EventBusPort` (envelope-first per ADR-023); no new port surface (per ADR-105 D11/D12 REJECT of ReflectionPort/SynthesisPort/ExperiencePort at 8.3)
- **Modifications:** Rewritten as frozen slotted dataclasses (donor used pydantic models); every port call fail-open behind `try/except Exception` with `log.exception` (ADR-105 D9); donor's in-memory dict persistence replaced with `RelationalMemoryPort.write_narrative` + ring-buffer fallback (`maxlen=100`); env-gated behind `KOSMOS_TEKTOS_{REFLECTION,SYNTHESIS,EXPERIENCE}={off,on}` with degrade-to-None when `registry.relational_memory` is None (ADR-101); FastAPI router factories with `503` guard closure at `/tektos/api/{reflection,synthesis,experience}` prefixes; six locked provenance/predicate constants per engine.
- **ADR:** ADR-105
- **Logged:** 2026-09-10 06:52 EDT

#### Tektos spec-planner engine — `VENDORED (Stage 8.4, ADR-106)`
- **Source:** `rmholston420/tektos-ultima` (donor absorbed under FULL FORK + REWRITE license posture; re-licensed at port-in point per ADR-092)
- **Donor modules:** `src/tektos/spec_planner.py` (SpecPlanner); `src/tektos/language_game.py` (LanguageGameDetector); `src/tektos/disambiguator.py` (Disambiguator); `src/tektos/translator.py` (Translator); `src/tektos/template_selector.py` (TemplateSelector); `src/tektos/spec_generator.py` (SpecGenerator)
- **License:** MIT (kosmos-lms declares MIT; rmholston420 sole copyright holder)
- **Kosmos location:** `plugins/tektos/planner/{spec_models.py,language_game.py,disambiguator.py,translator.py,template_selector.py,spec_generator.py,spec_planner.py,api.py}`; `TektosSpecPlanner` engine exported from `plugins/tektos/planner/__init__.py`. Stage 4.7 `TektosTurnPlanner` seed (`turn_planner.py` + `test_turn_planner.py`) preserved unchanged per ADR-093/ADR-106 D1.
- **Port(s):** `RelationalMemoryPort` (via `write_narrative`); `EventBusPort` (envelope-first per ADR-023); no `PlannerPort` (ADR-106 D11 REJECT — `TektosPlugin.spec_planner: object | None` field IS the coupling surface); no `LLMPort` (ADR-106 D12 REJECT — donor pipeline is 100% rule-based).
- **Modifications:** Rewritten as frozen slotted dataclasses (donor used pydantic); donor's rule dictionaries (language-game classifier, disambiguator patterns, translator glossary, template rules, spec heuristics) preserved verbatim; every port call fail-open (`try/except Exception` with `log.exception`) per ADR-106 D9; ring-buffer fallback (`maxlen=100`); env-gated behind `KOSMOS_TEKTOS_SPEC_PLANNER={off,on}` with degrade-to-None when `registry.relational_memory` is None (ADR-101); FastAPI router factory with `503` guard closure at `/tektos/api/spec-planner/{plan,recent}`; locked constants `TEKTOS_SPEC_PLANNER_PROVENANCE="tektos.planner"` / `TEKTOS_SPEC_PLANNER_PREDICATE="tektos.planner.spec_generated"` / `TEKTOS_SPEC_PLANNER_DEFAULT_CONFIDENCE=0.75`. `LanguageGame` enum lands NOW (Stage 8.4) in `plugins/tektos/planner/spec_models.py`, discharging ADR-105 D9's forward deferral. Stage 8.4 lands rule-based rewrite only; LLMPort/RepoMapPort integration deferred to a later stage.
- **ADR:** ADR-106
- **Logged:** 2026-09-10 06:52 EDT

#### Tektos task-decomposer engine — `VENDORED (Stage 8.4, ADR-106)`
- **Source:** `rmholston420/tektos-ultima` (donor absorbed under FULL FORK + REWRITE license posture; re-licensed at port-in point per ADR-092)
- **Donor modules:** `src/tektos/task_decomposer.py` (TaskDecomposer + `format_for_prompt`)
- **License:** MIT (kosmos-lms declares MIT; rmholston420 sole copyright holder)
- **Kosmos location:** `plugins/tektos/decomposer/{__init__.py,models.py,engine.py,api.py}`
- **Port(s):** `RelationalMemoryPort` (via `write_narrative`); `EventBusPort` (envelope-first per ADR-023); no new port surface (ADR-106 D11 REJECT — `TektosPlugin.decomposer: object | None` field IS the coupling surface).
- **Modifications:** Rewritten as frozen slotted `SubTask` + `DecompositionPlan` dataclasses (donor used pydantic); donor's five branch-predicate rule dictionaries (build / write / regex / download-build / generic) preserved verbatim; every port call fail-open per ADR-106 D9; ring-buffer fallback (`maxlen=100`); env-gated behind `KOSMOS_TEKTOS_DECOMPOSER={off,on}` with degrade-to-None when `registry.relational_memory` is None (ADR-101); FastAPI router factory with `503` guard closure at `/tektos/api/decomposer/{decompose,recent}`; locked constants `TEKTOS_DECOMPOSER_PROVENANCE="tektos.decomposer"` / `TEKTOS_DECOMPOSER_PREDICATE="tektos.decomposer.plan_generated"` / `TEKTOS_DECOMPOSER_DEFAULT_CONFIDENCE=0.75`. Static `format_for_prompt` classmethod returns TASK DECOMPOSITION prompt shape verbatim from donor.
- **ADR:** ADR-106
- **Logged:** 2026-09-10 06:52 EDT

---

## Gnosis (Knowledge)

#### Superpowers KB (content corpus) — `INGESTED` (Stage 4.4, ADR-049)
- **Source:** https://github.com/obra/superpowers
- **Commit / Version:** `44c9b2d6e889982ac18c27d05a19fefe335194e1` (2026-07 HEAD)
- **License:** MIT
- **Classification:** **Content ingest** — not a code vendor. No upstream Python/Markdown is imported at runtime; the Markdown body of every `skills/*/*.md` file at the pinned SHA lands as data inside a MemoryPort fixture. Distinct from ADR-008's Tektos-UX "do not vendor code" rule (see ADR-049 §Context for the reconciliation with ADR-002 + ADR-016).
- **Kosmos location (Stage 4.4):** `adapters/memory/dozerdb/corpora/superpowers/` — corpus module, `__init__.py` re-exports, and `fixtures/superpowers.jsonl` (38 records, 9 typed cross-reference edges, ~310 KB).
- **Kosmos location (Phase 3):** relocates to `plugins/gnosis/humanities/personal_kb/` when Gnosis lands. Public loader shape stable across the move (`load_corpus`, `CORPUS` singleton, env override `KOSMOS_SUPERPOWERS_PATH`).
- **Port(s):** MemoryPort (`record_event`, `query_temporal`, typed-link retrieval via `CorpusEdge`). VectorPort surface deliberately NOT opened at 4.4 (ADR-049 Q4).
- **Modifications:** none to upstream content. Ingest pipeline (`scripts/ingest_superpowers.py`) parses inline Markdown `[text](path)` links into `attributes.references` and materializes them as typed `CorpusEdge` records at load time.
- **Refresh cadence:** pinned SHA + workspace-local CLI (`scripts/ingest_superpowers.py --sha <SHA> [--via gh|checkout]`). No cron, no runtime network fetch.
- **ADR:** ADR-049 (Stage 4.4 substrate landing); references ADR-002 + ADR-016 (Gnosis endpoint), ADR-007 (adapter-corpus, no plugin-to-plugin imports), ADR-008 (Tektos-UX code-vendor rule preserved), ADR-047 (Stage 4.2 corpora contract inherited).
- **Logged:** 2026-07-30 (Stage 4.4 landing)

#### Humanities canonical-text corpus — SuttaCentral Bilara — `INGESTED` (Stage 4.5, ADR-050)
- **Source:** https://github.com/suttacentral/bilara-data
- **Commit / Version:** `3c93d1cea80fdebcefb777c8724c35bd971f360a` (`published` branch tip on 2026-07-30)
- **License:** translations CC0-1.0 (Creative Commons Public Domain dedication per upstream `LICENSE.md`), Mahasangiti Pali root public-domain
- **Kosmos location (Stage 4.5):** `adapters/memory/dozerdb/corpora/humanities_bilara/` — corpus module, `__init__.py` re-exports, and `fixtures/humanities_bilara.jsonl` (141 records = 70 translation + 70 root + 1 translator actor; 140 typed CIDOC-CRM edges = 70 × `P73_is_translation_of` + 70 × `P94_was_created_by`; ~392 KB fixture).
- **Kosmos location (Phase 3):** relocates to `plugins/gnosis/humanities/canonical_kb/` when Gnosis lands. Public loader shape stable across the move (`load_corpus`, `CORPUS` singleton, env override `KOSMOS_HUMANITIES_BILARA_PATH`).
- **Stage 4.5 slice:** Bhikkhu Sujato's English translations of three Khuddaka Nikaya publications (scpub7 Dhammapada, scpub19 Khuddakapatha, scpub86 Cariyapitaka) mirrored by their Mahasangiti Pali root under `root/pli/ms/sutta/kn/{dhp,kp,cp}/`; single translator actor record from `_author.json`. Broader upstream slice (other translators, other nikayas, other target languages) available via re-ingest at the same pinned SHA — no adapter change required.
- **Port(s):** MemoryPort (`record_event`, `query_temporal`, typed CIDOC-CRM-link retrieval via `CorpusEdge`). VectorPort surface deliberately NOT opened at 4.5 (ADR-050 Q4).
- **Modifications:** none to upstream content. Ingest pipeline (`scripts/ingest_humanities.py`) walks `translation/<lang>/<translator>/**` + mirrored `root/<lang>/<edition>/**` at the pinned SHA, concatenates segment-keyed JSON values in insertion order into a single `body` string per record, and synthesizes actor records from `_author.json` so `P94_was_created_by` edges are resolvable inside the corpus. All CIDOC-CRM edge `kind` values are property URIs (`P73_is_translation_of`, `P94_was_created_by`) rather than generic `references`.
- **Refresh cadence:** pinned SHA + workspace-local CLI (`scripts/ingest_humanities.py --sha <SHA> [--via gh|checkout]`). No cron, no runtime network fetch. Blob-by-blob `gh api` fetches by default — respects Colossus disk headroom (upstream repo is ~920 MB; no full clone needed).
- **ADR:** ADR-050 (Stage 4.5 substrate landing); references ADR-002 + ADR-016 (Gnosis endpoint), ADR-007 (adapter-corpus, no plugin-to-plugin imports), ADR-047 (Stage 4.2 corpora contract inherited), ADR-049 (Superpowers KB precedent for content-ingest ≠ code-vendoring).
- **Rejected alternative (recorded, not re-litigable without new ADR):** 84000 (Kangyur/Tengyur, `github.com/84000`) at CC-BY-NC-4.0 — rejected on NC downstream propagation risk (ADR-050 Q1). 84000 remains open as a possible additional Stage 5+ corpus behind its own ADR after Gnosis exposes the multi-corpus retrieval surface.
- **Logged:** 2026-07-30 (Stage 4.5 landing)

---

## Zetesis (Research) — ADR-010 resolved 2026-07-30

#### LangChain Open Deep Research — `VENDORED (Stage 6.2 winner · LOCKED 2026-07-30)`
- **Source:** https://github.com/langchain-ai/open_deep_research
- **Commit / Version:** `d337ae32ed4ff8f4c6fbe192ba3bf1b2d6610799`
- **License:** MIT
- **Kosmos location:** `vendor/adr_010/open_deep_research/`
- **Port(s):** Stage 6.2 Zetesis inner-loop substrate (wraps `LLMPort` + `SearchPort` for the PLAN→SEARCH→SYNTHESIZE loop)
- **Modifications:** none (shallow-clone, `.git` stripped; UPSTREAM_SHA metadata added)
- **ADR:** ADR-010 (LOCKED amendment 2026-07-30)
- **Logged:** 2026-07-30 10:03 EDT · **Promoted EVAL-ONLY → VENDORED:** 2026-07-30 11:52 EDT
- **Head-to-head result:** 3/3 completion, aggregate 3.0/18 (16.7%) on 6-canonical-fact rubric (see `ops/benchmarks/artifacts/adr-010-2026-07-30/odr/`). Won by completing reliably on the Colossus envelope; AREX-Turbo produced no scorable final_answer in either cohort.
- **Stage 6.3 obligation:** substrate tuning — anchor prompts to canonical-facts pattern, raise `search_api=NONE`+MCP source-diversity floor, evaluate replacing qwen2.5:32b with a stronger open-weight model if VRAM budget permits.

#### AREX-Turbo inference bundle — `REJECTED (Stage 6.2 · on-shelf pending thermal remediation)`
- **Source:** https://huggingface.co/BAAI/AREX-Turbo (subpath `inference/`)
- **Commit / Version:** HF commit `129812742df4a5de27980ed07bda78d9d27c7370`
- **License:** Apache-2.0 (per HF card `cardData.license`; weights + inference bundle)
- **Kosmos location:** `vendor/adr_010/arex_inference/` (retained on-shelf; NOT deleted — revisit gate below)
- **Port(s):** none (rejected for Stage 6.2)
- **Modifications:** none (files copied verbatim: `README.md`, `__init__.py`, `inference.py`, `prompts.py`)
- **ADR:** ADR-010 (LOCKED amendment 2026-07-30 — REJECTED for Stage 6.2)
- **Logged:** 2026-07-30 10:03 EDT · **Status flipped VENDORED (EVAL-ONLY) → REJECTED:** 2026-07-30 11:52 EDT
- **Head-to-head result:** 0/3 completion at 32k context (all exhausted context before `<finish>`); 0/3 completion at 65k context (2× visit-tool 404s halted loop, 1× RTX 5090 display-blank thermal event above 85°C).
- **Note:** AREX code repo at `github.com/VectorSpaceLab/arex-model` was NOT vendored — repo ships without a LICENSE file, which per `kosmos-port-workflow` license discipline is non-permissive by default. Harness executor authored fresh from Apache-2.0 HF-shipped tool protocol. Retained bundle avoids re-fetch cost if revisited.
- **Revisit gate:** may re-open a new ADR (successor to ADR-010) if all four are true — (1) Colossus receives thermal remediation (undervolt/fan curve/thermal-pad refresh) documented in `SESSION_HANDOFF.md`; (2) sustained vLLM bfloat16 attention at ≥65k context runs 30 min under 82°C with fan-curve headroom; (3) an AREX-Base or successor checkpoint ships with a native low-memory tool loop that fits inside Colossus's proven envelope; (4) the current ODR substrate has been raised to ≥ 60% on the F1-F6 rubric and demonstrably plateaued.

---

## Koinonia / Synedrion (Agent-to-Agent)

#### a2a-sdk — `PLANNED (standalone transport)`
- **Source:** https://github.com/google/a2a (or canonical)
- **License:** Apache-2.0
- **Kosmos location:** `plugins/koinonia/vendor/a2a/`
- **Port(s):** EventBusPort (bridged), custom transport
- **ADR:** ADR-011 (a2a-sdk chosen over Moltbook transport)
- **Logged:** —

---

## Ops / Deploy

#### Coolify — `PLANNED`
- **Source:** https://github.com/coollabsio/coolify
- **License:** Apache-2.0
- **Kosmos location:** self-hosted single-node
- **Notes:** deploy convenience only; not required for kernel
- **Logged:** —

#### Kamal — `PLANNED`
- **Source:** https://github.com/basecamp/kamal
- **License:** MIT
- **Notes:** alternative deploy tool; hold as backup
- **Logged:** —

---

## Design References — Do Not Vendor

These informed design but are **not** in the tree. Recorded here so future maintainers know they were considered.

#### Superpowers (repo, methodology reference for Tektos UX) — `DESIGN REFERENCE`
- **Source:** https://github.com/obra/superpowers
- **Use:** shape of the Tektos skill-library UX per ADR-008 (agentskills.io format, when-to-use blocks, technique/protocol taxonomy). Superpowers's *code and Markdown files are not vendored into Tektos plugin code* — ADR-008 rule preserved.
- **Note:** distinct from the Personal-KB substrate ingest above under Gnosis (Stage 4.4 · ADR-049), which lands the same upstream repo's Markdown as MemoryPort **content** rather than plugin code.

#### Beads (task-state library) — `DESIGN REFERENCE`
- **Source:** TBD
- **Use:** informs TaskState modeling in Tektos and Oikos
- **ADR:** adr-beads-taskstate

#### karpathy/llm-council — `DESIGN REFERENCE`
- **Source:** https://github.com/karpathy/llm-council (or similar)
- **Use:** informs Synedrion multi-agent voting patterns

#### CMSgov BenefitAssist — `DESIGN REFERENCE`
- **Source:** CMS.gov open-source patterns
- **Use:** Oikos benefit-flow UX

#### 18F SNAP — `DESIGN REFERENCE`
- **Source:** 18F GitHub
- **Use:** Oikos benefit-flow UX

#### we-promise/sure — `REJECTED`
- **Reason:** does not fit Oikos zero-trust memory model / single-user constraints
- **Decision date:** TBD
- **Do not vendor without re-review + new ADR.**

---

## Ledger Maintenance

- Append entries in chronological order; do **not** re-order for prettiness.
- When a `PLANNED` entry is vendored: change status to `VENDORED`, add commit SHA, set `Logged` timestamp, and record the initial import commit hash of Kosmos in the entry.
- When a spike concludes: change `EVALUATING` → `VENDORED` or `REJECTED` with the benchmark reference.
- When one entry supersedes another: mark the older `SUPERSEDED` with a link to the new entry; do not delete.
- License must be re-verified at every version bump. Any change to a non-permissive license triggers immediate ADR.
