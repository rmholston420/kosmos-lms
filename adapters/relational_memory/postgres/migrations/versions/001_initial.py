"""Initial schema for RelationalMemoryPort (ADR-102 D3).

Creates:
- Extensions: pg_uuidv7 (for UUIDv7 primary keys), vector (pgvector),
  pg_trgm (trigram index for fallback lexical scan).
- ledger_events table (R1 audit ledger).
- narratives table (R2 episodic narratives) with tsvector generated column,
  GIN full-text index, HNSW pgvector index, GIN tags index.

Per ADR-102 D3, embedding dimension is 1536 (matches OpenAI text-embedding-3
and the current EmbeddingsPort default). Redeployments that need a different
dim will author a new migration that ALTERs the column and re-indexes.

Revision ID: 001_initial
Revises:
Create Date: 2026-09-10 04:50:00 EDT
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ─────────────────────────────────────────────────────────
    # pg_uuidv7 provides uuid_generate_v7() (or uuidv7() depending on
    # extension version). We prefer uuid_generate_v7() from the widely-used
    # pgxn build; fall back to gen_random_uuid() if extension is unavailable.
    op.execute(
        """
        DO $$
        BEGIN
            BEGIN
                CREATE EXTENSION IF NOT EXISTS pg_uuidv7;
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE
                    'pg_uuidv7 unavailable; using gen_random_uuid() '
                    'as PK default. Install pg_uuidv7 for temporal-ordered UUIDs.';
            END;
        END
        $$;
        """
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")    # pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")   # trigram lexical

    # ── Helper: choose PK default expression ──────────────────────────────
    # We use a SQL function wrapper so both extensions can serve. If
    # uuid_generate_v7() exists, use it; otherwise gen_random_uuid().
    op.execute(
        """
        CREATE OR REPLACE FUNCTION kosmos_uuid7()
        RETURNS uuid
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_proc WHERE proname = 'uuid_generate_v7'
            ) THEN
                RETURN uuid_generate_v7();
            END IF;
            RETURN gen_random_uuid();
        END;
        $$;
        """
    )

    # ── ledger_events (R1) ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ledger_events (
            event_id     uuid PRIMARY KEY DEFAULT kosmos_uuid7(),
            kind         text NOT NULL,
            session_id   text,
            agent_id     text,
            payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
            confidence   double precision NOT NULL
                          CHECK (confidence >= 0 AND confidence <= 1),
            provenance   text NOT NULL CHECK (length(trim(provenance)) > 0),
            created_at   timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_ledger_kind_time "
        "ON ledger_events (kind text_pattern_ops, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_ledger_session_time "
        "ON ledger_events (session_id, created_at DESC) "
        "WHERE session_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX idx_ledger_agent_time "
        "ON ledger_events (agent_id, created_at DESC) "
        "WHERE agent_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX idx_ledger_payload_gin "
        "ON ledger_events USING GIN (payload jsonb_path_ops);"
    )

    # ── narratives (R2) ───────────────────────────────────────────────────
    # embedding dim = 1536 per ADR-102 D3.
    op.execute(
        """
        CREATE TABLE narratives (
            narrative_id uuid PRIMARY KEY DEFAULT kosmos_uuid7(),
            session_id   text NOT NULL,
            agent_id     text,
            title        text NOT NULL CHECK (length(trim(title)) > 0),
            body         text NOT NULL,
            tags         text[] NOT NULL DEFAULT ARRAY[]::text[],
            embedding    vector(1536),
            confidence   double precision NOT NULL
                          CHECK (confidence >= 0 AND confidence <= 1),
            provenance   text NOT NULL CHECK (length(trim(provenance)) > 0),
            created_at   timestamptz NOT NULL DEFAULT now(),
            body_tsv     tsvector GENERATED ALWAYS AS
                          (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))) STORED
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_narr_body_tsv ON narratives USING GIN (body_tsv);"
    )
    op.execute(
        "CREATE INDEX idx_narr_tags_gin ON narratives USING GIN (tags);"
    )
    op.execute(
        "CREATE INDEX idx_narr_session_time "
        "ON narratives (session_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_narr_agent_time "
        "ON narratives (agent_id, created_at DESC) "
        "WHERE agent_id IS NOT NULL;"
    )
    # HNSW index on embedding — cosine distance operator ``vector_cosine_ops``.
    # HNSW is more memory-hungry than IVFFlat but has better recall at low
    # index build cost. m=16, ef_construction=64 match pgvector defaults.
    op.execute(
        "CREATE INDEX idx_narr_embedding_hnsw "
        "ON narratives USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS narratives;")
    op.execute("DROP TABLE IF EXISTS ledger_events;")
    op.execute("DROP FUNCTION IF EXISTS kosmos_uuid7();")
    # Leave extensions installed — other tenants may rely on them.
