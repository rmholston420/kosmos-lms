# ADR-102 — `RelationalMemoryPort`: Postgres as the 5th Memory Layer

**Status:** Ratified (2026-09-10)
**Lock-in phase:** Stage 8.0 (Plan v2)
**Supersedes:** —
**Amends:** ADR-027 (MemoryPort surface) — additive, non-breaking

---

## Context

The 2026-09-10 tri-repo audit (`KOSMOS_LMS_AUDIT_AND_UPDATED_PLAN.md`) identified that the current MemoryPort stack has 4 effective layers:

1. **Graph** — DozerDB via `DozerDbGraphBackend` (`adapters/memory/dozerdb/graph_backend.py`); triples + property edges (ADR-008, ADR-063).
2. **Lexical** — DozerDB Lucene fulltext via `DozerDbLexicalIndex` (ADR-100); `search_lexical`.
3. **Semantic** — `EmbeddingsPort` adapter (`ports/embeddings.py` ADR-073) with backend of choice; `search_semantic`.
4. **Episodic/file** — file-store under `adapters/data/blobs/` (ADR-096 D3), content-addressed by SHA-256; used by voice/vision two-write pattern.

The user (2026-09-10) stated that the 4/5-layer memory system includes Postgres as a distinct layer. Neither donor (Tektos-Ultima, Kosmos) ships a Postgres installer, and no prior ADR mentions Postgres. The Integration Plan v1 Step 8.5 lists "Postgres 18 + pgvector 0.8.1" in the data-services set without specifying its role.

Three roles are candidate uses for Postgres:

- **R1 — Relational metadata / audit trail.** Sessions, approvals, tool-invocation audit ledger, agent-turn ledger, ADR-088 read-only budget history, ADR-092 immune-event log. Currently scattered across `plugins/tektos/{runtime,tools}/*` in-memory dicts, file-store JSON blobs, and DozerDB properties. Strict schema + FK integrity + partial indexes make Postgres the right tool.
- **R2 — Episodic-narrative store.** Hindsight was retired at ADR-099, but its role (retrievable narratives of past sessions with rich time/tag/agent-scoped queries + pgvector semantic recall over narrative text) still fits Postgres+pgvector better than DozerDB properties or file-store.
- **R3 — Alternative semantic backend.** PgVector 0.8.1 as a second semantic backend behind the existing `EmbeddingsPort` adapter for A/B against the current adapter.

The port question is whether Postgres becomes a new formal port, an adapter of an existing port, or both.

## Decision

Ship a **new formal port** `ports/relational_memory.py` (23rd port) called `RelationalMemoryPort`. Ship two adapters at `adapters/relational_memory/{noop,postgres}/`. Postgres slots as the 5th memory layer with **combined R1 + R2 role** (audit ledger + episodic narrative store). Role R3 (pgvector as EmbeddingsPort alternative) is deferred to a future ADR — not folded into `RelationalMemoryPort`.

### D1 — Protocol surface

```python
class RelationalMemoryPort(Protocol):
    # session lifecycle
    async def transaction(self) -> AsyncContextManager["RelationalTx"]:
        """Begin a transaction. Commits on __aexit__ success, rolls back on exception."""

    # audit ledger surface (R1)
    async def record_event(
        self, *,
        kind: str,                 # e.g. "tool.invoked", "approval.proposed"
        session_id: str | None,
        agent_id: str | None,
        payload: dict[str, Any],
        confidence: float,          # zero-trust rule per ADR-008
        provenance: str,            # zero-trust rule per ADR-008
    ) -> str:
        """Append audit-ledger row; returns event_id (UUIDv7)."""

    async def query_events(
        self, *,
        kind_prefix: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> tuple[LedgerRow, ...]: ...

    # episodic narrative surface (R2)
    async def write_narrative(
        self, *,
        session_id: str,
        agent_id: str | None,
        title: str,
        body: str,
        tags: tuple[str, ...],
        embedding: tuple[float, ...] | None,   # pgvector; None on adapters without vector
        confidence: float,
        provenance: str,
    ) -> str:
        """Persist a narrative; returns narrative_id (UUIDv7)."""

    async def search_narratives(
        self, *,
        query: str,                             # full-text query
        embedding: tuple[float, ...] | None,    # if provided AND adapter supports pgvector, hybrid rank
        session_id: str | None = None,
        agent_id: str | None = None,
        tags: tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[NarrativeHit, ...]: ...

    # health
    def is_healthy(self) -> bool: ...
    async def close(self) -> None: ...
```

### D2 — Adapters

- `NoOpRelationalMemoryAdapter` (`adapters/relational_memory/noop/`) — sqlite in-memory backend (aiosqlite); pgvector shape stored as JSON blob (search falls back to full-text-scan). Zero external dependencies. Required for CI and dev environments without Postgres.
- `PostgresRelationalMemoryAdapter` (`adapters/relational_memory/postgres/`) — `asyncpg` + `pgvector.asyncpg` driver; Alembic migrations at `adapters/relational_memory/postgres/migrations/`; connection pool via `asyncpg.create_pool` with `min_size=2, max_size=10`.

### D3 — Schema (Postgres adapter)

Two tables managed by Alembic (initial migration `001_initial.sql`):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_uuidv7;   -- OSS extension, MIT

CREATE TABLE ledger_events (
    event_id       UUID PRIMARY KEY DEFAULT uuidv7(),
    kind           TEXT NOT NULL,
    session_id     TEXT,
    agent_id       TEXT,
    payload        JSONB NOT NULL,
    confidence     REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    provenance     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ledger_kind_time     ON ledger_events (kind, created_at DESC);
CREATE INDEX idx_ledger_session_time  ON ledger_events (session_id, created_at DESC)
    WHERE session_id IS NOT NULL;
CREATE INDEX idx_ledger_agent_time    ON ledger_events (agent_id, created_at DESC)
    WHERE agent_id IS NOT NULL;

CREATE TABLE narratives (
    narrative_id   UUID PRIMARY KEY DEFAULT uuidv7(),
    session_id     TEXT NOT NULL,
    agent_id       TEXT,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    body_tsv       TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', body)) STORED,
    tags           TEXT[] NOT NULL DEFAULT '{}',
    embedding      VECTOR(1536),      -- default OpenAI-family dimension; adapter validates
    confidence     REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    provenance     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_narr_session       ON narratives (session_id, created_at DESC);
CREATE INDEX idx_narr_agent         ON narratives (agent_id, created_at DESC)
    WHERE agent_id IS NOT NULL;
CREATE INDEX idx_narr_tags          ON narratives USING GIN (tags);
CREATE INDEX idx_narr_body_tsv      ON narratives USING GIN (body_tsv);
CREATE INDEX idx_narr_embedding     ON narratives USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
```

Embedding dimension: `1536` locked as default. Adapter constructor takes `embedding_dim: int | None`; None disables the embedding column (pure lexical narrative search). Non-default dims require an Alembic migration.

### D4 — Zero-trust write contract (parity with ADR-008)

Every `record_event` and `write_narrative` **must** carry `provenance: str` and `confidence: float` (0.0–1.0). The protocol rejects at the port layer if either is missing. This preserves the same discipline the graph and semantic layers already carry.

### D5 — No overlap with `MemoryPort.search_hybrid`

`MemoryPort.search_hybrid` (ADR-085 / ADR-099) fuses **lexical + semantic** over triples/events. `RelationalMemoryPort.search_narratives` fuses **tsvector + pgvector** over narrative documents. They serve different retrieval shapes (triples vs prose) and are not composed at the port layer. A future ADR may add a `MemoryPort` façade that fans out to both, but Stage 8.0 lands them side-by-side.

### D6 — Kernel-boot wiring

New env var `KOSMOS_RELATIONAL_MEMORY={off,noop,postgres}` (default `off`). When `noop`, uses aiosqlite in-memory (per-process). When `postgres`, requires `KOSMOS_POSTGRES_URI` (e.g. `postgres://kosmos@localhost:5432/kosmos`) and calls `is_healthy()` at boot; unhealthy falls through to `RelationalMemoryPort=None` with a warning log — plugins guard on `if registry.relational_memory is None:` and short-circuit. Follows ADR-101's opt-in-degrade pattern.

### D7 — Migration surface

Alembic (MIT) at `adapters/relational_memory/postgres/migrations/`. `alembic upgrade head` runs manually or via `ops/scripts/postgres-migrate.sh`. Kernel does NOT auto-migrate on boot (per ADR-063 no-implicit-schema-changes rule). CI runs migrations against an ephemeral Postgres in the compose stack.

### D8 — Deployment

- New file `ops/compose/postgres.yml` — Postgres 18 official image + pgvector extension + pg_uuidv7 extension + volume mount.
- New installer `deploy/data-services/install-postgres.sh` (in Stage 12) — apt-based Postgres 18 + extensions, systemd unit, initial DB + user, runs Alembic migrations.
- Colossus verification (Stage 12): `install-postgres.sh` + `alembic upgrade head` + `KOSMOS_RELATIONAL_MEMORY=postgres` + smoke test proving `record_event` + `search_narratives` round-trip.

## Rationale

**Why a new formal port** rather than extending `MemoryPort`? The MemoryPort surface (ADR-027 + ADR-085) targets triple/event graph memory with a specific fusion contract. Bolting relational audit + narrative search onto that surface violates single-responsibility and forces every MemoryPort adapter to implement SQL machinery it does not need. ADR-007 (events-only cross-plugin coupling) is not affected — `RelationalMemoryPort` is a formal port, plugins consume it through their factory, adapters live under `adapters/`.

**Why R1 + R2 together, R3 later?** R1 (audit ledger) and R2 (narratives) share the same Postgres instance, the same connection pool, and the same transactional semantics — bundling them into one port avoids two adapters + two schemas + two boot paths for the same backend. R3 (pgvector as EmbeddingsPort alternative) is a different port entirely (`EmbeddingsPort`) and would create confusion if folded here.

**Why 5th layer, not 4.5?** The user framed it as a 4/5-layer memory system. R1 + R2 combined constitute a distinct memory concern (relational-metadata + episodic-narrative) that neither the graph, lexical, semantic, nor blob layers cover today. Numbering it the 5th layer preserves the mental model.

**Why UUIDv7?** Time-ordered, index-friendly, url-safe. `pg_uuidv7` is a small OSS extension; if unavailable we fall back to `gen_random_uuid()` at cost of index locality.

**Why Alembic?** Kosmos already uses migration discipline for DozerDB (via Cypher migration files). Alembic is the SQL-migration equivalent, MIT-licensed, well-maintained, ships with tools we need (autogenerate, offline SQL emission, batch mode for future SQLite parity).

**Why not SQLAlchemy Core?** Would add a large dependency (~2 MB) for a narrow API. Direct asyncpg + string SQL keeps the adapter small (est. ~400 lines) and matches how `DozerDbGraphBackend` uses the raw neo4j driver.

## Consequences

**New files:**
- `ports/relational_memory.py` — Protocol + `LedgerRow`, `NarrativeHit` dataclasses
- `adapters/relational_memory/__init__.py`
- `adapters/relational_memory/noop/adapter.py` — aiosqlite backend
- `adapters/relational_memory/postgres/adapter.py` — asyncpg + pgvector
- `adapters/relational_memory/postgres/migrations/env.py` + `001_initial.py`
- `adapters/relational_memory/postgres/pool.py` — connection pool + retry
- `ops/compose/postgres.yml`
- `docs/adrs/ADR-102-relational-memory-port-postgres-5th-layer.md` (this file)
- Contract tests at `adapters/relational_memory/{noop,postgres}/test_contract.py` (fast-tier: noop; env-gated live-tier: postgres via `KOSMOS_STAGE_80_REAL_POSTGRES=1`)
- Kernel wiring in `kernel/app.py::_boot_relational_memory`
- Kernel-boot tests at `tests/kernel/test_stage_8_0_relational_memory_wiring.py`
- Update to `kernel/registry.py` — add `relational_memory: RelationalMemoryPort | None`

**Updated files:**
- `docs/adrs/README.md` — new row for ADR-102
- `PORTING_LEDGER.md` — new section for `relational_memory` (VENDORED asyncpg, pgvector, pg_uuidv7)
- `docs/Kosmos-Build-Spec-v26.md` — §4 (Ports) adds row 23; §17 (ADR table) adds ADR-102
- `docs/Kosmos-Build-Sequence-v26.md` — adds Stage 8.0 as first slice of Plan v2 execution
- `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md` — references ADR-102 as Stage 8.0 anchor

**Downstream:**
- Every plugin that currently records audit-trail data in ad-hoc places (`plugins/tektos/tools/*`, `plugins/tektos/runtime/turn_loop.py`, etc.) becomes a candidate for migration to `RelationalMemoryPort.record_event` — migration is not blocking and happens incrementally as those subsystems get Stage-8+ port-in work.
- ImmunePort event log (ADR-092) is a first candidate for migration once `RelationalMemoryPort` is wired.

## Lock-in phase

Plan v2 Stage 8.0 (first slice). All subsequent Plan v2 stages assume `RelationalMemoryPort` is available (may be `None` if not wired).

## References

- ADR-008 (MemoryPort zero-trust write contract)
- ADR-027 (MemoryPort surface)
- ADR-063 (single canonical memory-adapter construction site)
- ADR-073 (EmbeddingsPort)
- ADR-085 (MemoryPort.search_hybrid)
- ADR-099 (Stage 7.4 re-scope: H1 retired)
- ADR-100 (DozerDbLexicalIndex)
- ADR-101 (kernel-boot lexical wiring — degrade pattern)
- Plan v2: `docs/plans/KOSMOS_LMS_INTEGRATION_PLAN_v2.md` Stage 8.0
- 2026-09-10 tri-repo audit: `audit/KOSMOS_LMS_AUDIT_AND_UPDATED_PLAN.md`
