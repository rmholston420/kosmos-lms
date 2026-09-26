"""RAGRetriever — Retrieval-Augmented Generation service for Tektos.

Provides:
- Document chunking (code files, memory entries, session events)
- Embedding generation via EmbedderClient
- SQLite-backed vector index with cosine similarity search
- Semantic retrieval over codebase, memory, and events
- Automatic context injection when context window fills

Usage:
    retriever = RAGRetriever(embedder_client, project_root="/path/to/repo")
    await retriever.start()
    await retriever.index_codebase()
    results = await retriever.retrieve("how does the tool registry work", top_k=5)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger("tektos.rag")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK_SIZE = 512  # tokens per chunk (approx chars)
CHUNK_OVERLAP = 64  # overlapping tokens between chunks
MAX_CHUNK_CHARS = 2048  # hard cap on chunk size in characters
DEFAULT_TOP_K = 5
SIMILARITY_THRESHOLD = 0.3  # minimum cosine similarity to return a result

# File extensions to index
CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".sh",
    ".bash",
    ".sql",
    ".proto",
    ".graphql",
    ".env",
    ".dockerfile",
}

# Directories to skip during indexing
SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
    "data",
    "checkpoints",
    "evaluations",
    "observability",
    "sandbox",
    "tmp",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RetrievalResult:
    """A single result from a RAG retrieval."""

    source: str  # "code", "memory", "event", "file"
    source_id: str  # file path, memory entry id, event id
    content: str  # the chunk text
    score: float  # cosine similarity [0, 1]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A chunked piece of text with its embedding."""

    id: str  # SHA256 of (source, content)
    source: str  # "code", "memory", "event", "file"
    source_id: str  # file path, memory id, event id
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string."""
    if not text:
        return 0
    words = len(text.split())
    code_markers = text.count("{") + text.count("}") + text.count("(") + text.count(")")
    tokens = words * 4
    if code_markers > words * 0.3:
        tokens = words * 3.5
    if len(text) > 10000:
        tokens = int(tokens * 0.95)
    return max(1, int(tokens))


def chunk_text(
    text: str,
    source: str,
    source_id: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split text into overlapping chunks with embeddings-ready IDs."""
    if not text.strip():
        return []

    # Estimate token count and split by character chunks
    total_tokens = estimate_tokens(text)
    char_chunk_size = int(len(text) / max(1, total_tokens // chunk_size))
    char_chunk_size = max(100, min(char_chunk_size, MAX_CHUNK_CHARS))

    chunks: list[Chunk] = []
    start = 0
    chunk_idx = 0

    while start < len(text):
        end = min(start + char_chunk_size, len(text))

        # Try to break at a natural boundary — but only scan a small window
        # to avoid O(n²) on long strings
        if end < len(text):
            # Look for a boundary in the last 200 chars of the chunk
            search_window = text[max(start, end - 200) : end]
            for pattern in [r"\n\n", r"\n", r"\.\s+", r",\s+", r"\s"]:
                match = re.search(pattern, search_window)
                if match:
                    # Adjust end to the boundary position relative to start
                    boundary_pos = max(start, end - 200) + match.end()
                    if boundary_pos > start + char_chunk_size // 2:
                        end = boundary_pos
                    break

        chunk_text = text[start:end].strip()
        if not chunk_text:
            start = end + 1
            continue

        chunk_id = hashlib.sha256(
            f"{source}:{source_id}:{chunk_idx}:{chunk_text}".encode()
        ).hexdigest()[:16]
        chunks.append(
            Chunk(
                id=chunk_id,
                source=source,
                source_id=source_id,
                content=chunk_text,
            )
        )
        chunk_idx += 1
        start = end - chunk_overlap if end < len(text) else end

    return chunks


def chunk_python_file(content: str, file_path: str) -> list[Chunk]:
    """Smart chunking for Python files — chunk by function/class boundaries."""
    lines = content.split("\n")
    chunks: list[Chunk] = []
    current_chunk_lines: list[str] = []
    current_chunk_tokens = 0

    def flush_chunk():
        nonlocal current_chunk_lines, current_chunk_tokens
        if current_chunk_lines:
            text = "\n".join(current_chunk_lines).strip()
            if text:
                chunks.extend(chunk_text(text, "code", file_path))
        current_chunk_lines = []
        current_chunk_tokens = 0

    for line in lines:
        line_tokens = estimate_tokens(line)

        # Start a new chunk at function/class definitions if current chunk is getting large
        if (
            line.strip().startswith(("def ", "class ", "async def "))
            and current_chunk_tokens > CHUNK_SIZE // 2
        ):
            flush_chunk()

        current_chunk_lines.append(line)
        current_chunk_tokens += line_tokens

        if current_chunk_tokens >= CHUNK_SIZE:
            flush_chunk()

    flush_chunk()

    # If no chunks were created (file is small), chunk the whole thing
    if not chunks and content.strip():
        chunks = chunk_text(content, "code", file_path)

    return chunks


def chunk_file_content(content: str, file_path: str) -> list[Chunk]:
    """Chunk any file content, using smart strategies for known types."""
    ext = Path(file_path).suffix.lower()

    if ext == ".py":
        return chunk_python_file(content, file_path)

    # For other files, use generic chunking
    return chunk_text(content, "code", file_path)


# ---------------------------------------------------------------------------
# Vector math
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def l2_normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector (for cosine similarity via dot product)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# RAGRetriever
# ---------------------------------------------------------------------------


class RAGRetriever:
    """RAG retrieval service — chunks, embeds, indexes, and retrieves.

    Stores indexed chunks in a local SQLite database with a vector column.
    Supports retrieval over codebase files, memory entries, and session events.
    """

    def __init__(
        self,
        embedder_client: Any,
        project_root: str = ".",
        db_path: str | None = None,
    ) -> None:
        self._embedder = embedder_client
        self._project_root = Path(project_root)
        self._db_path = db_path or str(self._project_root / "data" / "tektos_rag.db")
        self._db: aiosqlite.Connection | None = None
        self._initialized = False
        self._indexing = False
        self._indexed_files: dict[str, float] = {}  # file_path -> mtime at index time

    async def start(self) -> None:
        """Initialize the SQLite database and verify embedder connectivity."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        # Create the chunks table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,
                metadata TEXT DEFAULT '{}',
                indexed_at REAL NOT NULL
            )
        """)

        # Create indexes for efficient querying
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id)
        """)

        await self._db.commit()
        self._initialized = True
        log.info("RAGRetriever initialized: db=%s", self._db_path)

    async def stop(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False
            log.info("RAGRetriever stopped")

    # ── Indexing ──────────────────────────────────────────────────────────

    async def index_codebase(self, project_root: str | None = None) -> int:
        """Scan and index all code files in the project.

        Returns the number of chunks indexed.
        """
        root = Path(project_root or self._project_root)
        if not root.exists():
            log.warning("Project root does not exist: %s", root)
            return 0

        self._indexing = True
        total_chunks = 0
        indexed = 0
        skipped = 0

        try:
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue

                # Check extension
                if file_path.suffix.lower() not in CODE_EXTENSIONS:
                    skipped += 1
                    continue

                # Check skip directories
                rel = file_path.relative_to(root)
                parts = rel.parts
                if any(part in SKIP_DIRS for part in parts):
                    skipped += 1
                    continue

                # Check if file needs re-indexing (mtime changed)
                try:
                    mtime = file_path.stat().st_mtime
                except OSError:
                    continue

                if mtime <= self._indexed_files.get(str(file_path), 0):
                    continue  # No change

                # Read and chunk
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                if not content.strip():
                    continue

                chunks = chunk_file_content(content, str(file_path))
                for chunk in chunks:
                    await self._store_chunk(chunk)
                    total_chunks += 1

                self._indexed_files[str(file_path)] = mtime
                indexed += 1

                # Log progress every 50 files
                if indexed % 50 == 0:
                    log.info("Indexing progress: %d files, %d chunks", indexed, total_chunks)

        finally:
            self._indexing = False

        if self._db:
            await self._db.commit()
        log.info(
            "Codebase indexing complete: %d files, %d chunks, %d skipped",
            indexed,
            total_chunks,
            skipped,
        )
        return total_chunks

    async def index_memory_entries(self, entries: list[dict[str, Any]]) -> int:
        """Index memory entries for semantic retrieval.

        Args:
            entries: List of memory entry dicts with 'content', 'category', 'source' keys.

        Returns the number of chunks indexed.
        """
        total_chunks = 0
        for entry in entries:
            content = entry.get("content", "")
            if not content.strip():
                continue

            source_id = entry.get("id", entry.get("source", "unknown"))
            category = entry.get("category", "context")
            chunks = chunk_text(content, "memory", source_id)

            for chunk in chunks:
                chunk.metadata["category"] = category
                chunk.metadata["source"] = entry.get("source", "")
                await self._store_chunk(chunk)
                total_chunks += 1

        if self._db:
            await self._db.commit()
        log.info("Memory indexing complete: %d chunks", total_chunks)
        return total_chunks

    async def index_session_events(self, events: list[dict[str, Any]]) -> int:
        """Index session events for semantic retrieval.

        Args:
            events: List of session event dicts.

        Returns the number of chunks indexed.
        """
        total_chunks = 0
        for event in events:
            text = self._extract_event_text(event)
            if not text.strip():
                continue

            event_id = event.get("id", event.get("event_id", str(id(event))))
            chunks = chunk_text(text, "event", event_id)

            for chunk in chunks:
                chunk.metadata["event_type"] = event.get("event_type", "")
                chunk.metadata["timestamp"] = event.get("timestamp", "")
                await self._store_chunk(chunk)
                total_chunks += 1

        if self._db:
            await self._db.commit()
        log.info("Event indexing complete: %d chunks", total_chunks)
        return total_chunks

    async def _store_chunk(self, chunk: Chunk) -> None:
        """Store a chunk in the SQLite database."""
        if not self._db:
            return
        embedding_blob = None
        if chunk.embedding:
            embedding_blob = json.dumps(chunk.embedding).encode("utf-8")

        await self._db.execute(
            """
            INSERT OR REPLACE INTO chunks (id, source, source_id, content, embedding, metadata, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                chunk.id,
                chunk.source,
                chunk.source_id,
                chunk.content,
                embedding_blob,
                json.dumps(chunk.metadata),
                time.time(),
            ),
        )

    @staticmethod
    def _extract_event_text(event: dict[str, Any]) -> str:
        """Extract meaningful text from a session event."""
        parts = []
        payload = event.get("payload", event)

        for key in [
            "assistant_text",
            "content",
            "message",
            "tool_output",
            "task_description",
            "error",
            "result",
        ]:
            val = payload.get(key)
            if val and isinstance(val, str) and val.strip():
                parts.append(val)

        return " ".join(parts)

    # ── Embedding ─────────────────────────────────────────────────────────

    async def _embed_chunks(self, chunks: list[Chunk]) -> None:
        """Generate embeddings for a batch of chunks via the embedder client."""
        if not self._embedder:
            log.warning("No embedder client available for RAG indexing")
            return

        texts = [c.content for c in chunks if c.content.strip()]
        if not texts:
            return

        try:
            result = await self._embedder.embed_batch(texts)
            for i, chunk in enumerate(chunks):
                if i < len(result.embeddings):
                    chunk.embedding = result.embeddings[i]
        except Exception as e:
            log.warning("Embedding failed for %d chunks: %s", len(chunks), e)

    async def _embed_and_store(self, chunks: list[Chunk]) -> None:
        """Embed chunks and store them in the database."""
        if not self._embedder:
            # Store without embeddings — will use keyword fallback
            for chunk in chunks:
                await self._store_chunk(chunk)
            return

        # Batch embed
        await self._embed_chunks(chunks)

        # Store with embeddings
        for chunk in chunks:
            await self._store_chunk(chunk)

    # ── Retrieval ─────────────────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        sources: list[str] | None = None,
        min_score: float = SIMILARITY_THRESHOLD,
    ) -> list[RetrievalResult]:
        """Retrieve relevant chunks for a query.

        Args:
            query: The search query.
            top_k: Maximum number of results.
            sources: Filter by source types ("code", "memory", "event", "file").
            min_score: Minimum cosine similarity threshold.

        Returns:
            List of RetrievalResult, ordered by relevance.
        """
        if not self._initialized:
            log.warning("RAGRetriever not initialized")
            return []

        # Try embedding-based retrieval first
        if self._embedder:
            try:
                results = await self._retrieve_with_embedding(query, top_k, sources, min_score)
                if results:
                    return results
            except Exception as e:
                log.warning("Embedding retrieval failed, falling back to keyword: %s", e)

        # Fallback: keyword-based retrieval
        return await self._retrieve_keyword(query, top_k, sources, min_score)

    async def _retrieve_with_embedding(
        self,
        query: str,
        top_k: int,
        sources: list[str] | None,
        min_score: float,
    ) -> list[RetrievalResult]:
        """Retrieve using embedding similarity."""
        # Embed the query
        query_result = await self._embedder.embed(query)
        if not query_result.embeddings:
            return []

        query_vec = query_result.embeddings[0]

        # Fetch all chunks (or filter by source)
        query_str = (
            "SELECT id, source, source_id, content, metadata, indexed_at, embedding FROM chunks"
        )
        params: list[Any] = []
        where_clauses = []

        if sources:
            placeholders = ",".join(["?"] * len(sources))
            where_clauses.append(f"source IN ({placeholders})")
            params.extend(sources)

        if where_clauses:
            query_str += " WHERE " + " AND ".join(where_clauses)

        query_str += " ORDER BY indexed_at DESC"

        if not self._db:
            return []

        async with self._db.execute(query_str, params) as cursor:
            rows = await cursor.fetchall()

        # Compute similarity for each chunk
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            row[0]
            source = row[1]
            source_id = row[2]
            content = row[3]
            metadata_json = row[4]
            row[5]
            embedding_blob = row[6]
            metadata = json.loads(metadata_json) if metadata_json else {}

            if not embedding_blob:
                continue

            chunk_vec = json.loads(embedding_blob)
            sim = cosine_similarity(query_vec, chunk_vec)

            if sim >= min_score:
                scored.append(
                    (
                        sim,
                        {
                            "source": source,
                            "source_id": source_id,
                            "content": content,
                            "metadata": metadata,
                        },
                    )
                )

        # Sort by similarity and return top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for sim, data in scored[:top_k]:
            results.append(
                RetrievalResult(
                    source=data["source"],
                    source_id=data["source_id"],
                    content=data["content"],
                    score=sim,
                    metadata=data["metadata"],
                )
            )

        return results

    async def _retrieve_keyword(
        self,
        query: str,
        top_k: int,
        sources: list[str] | None,
        min_score: float,
    ) -> list[RetrievalResult]:
        """Keyword-based retrieval fallback."""
        query_terms = set(query.lower().split())
        if not query_terms:
            return []

        query_str = "SELECT id, source, source_id, content, metadata FROM chunks"
        params: list[Any] = []
        where_clauses = []

        if sources:
            placeholders = ",".join(["?"] * len(sources))
            where_clauses.append(f"source IN ({placeholders})")
            params.extend(sources)

        if where_clauses:
            query_str += " WHERE " + " AND ".join(where_clauses)

        if not self._db:
            return []

        async with self._db.execute(query_str, params) as cursor:
            rows = await cursor.fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            chunk_id, source, source_id, content, metadata_json = row
            metadata = json.loads(metadata_json) if metadata_json else {}

            content_lower = content.lower()
            score = sum(1 for term in query_terms if term in content_lower)
            # Normalize by query length
            score = score / len(query_terms)

            if score >= min_score:
                scored.append(
                    (
                        score,
                        {
                            "source": source,
                            "source_id": source_id,
                            "content": content,
                            "metadata": metadata,
                        },
                    )
                )

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, data in scored[:top_k]:
            results.append(
                RetrievalResult(
                    source=data["source"],
                    source_id=data["source_id"],
                    content=data["content"],
                    score=score,
                    metadata=data["metadata"],
                )
            )

        return results

    # ── Convenience methods ───────────────────────────────────────────────

    async def retrieve_code(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = SIMILARITY_THRESHOLD,
    ) -> list[RetrievalResult]:
        """Retrieve relevant code chunks."""
        return await self.retrieve(query, top_k=top_k, sources=["code"], min_score=min_score)

    async def retrieve_memory(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = SIMILARITY_THRESHOLD,
    ) -> list[RetrievalResult]:
        """Retrieve relevant memory chunks."""
        return await self.retrieve(query, top_k=top_k, sources=["memory"], min_score=min_score)

    async def retrieve_events(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = SIMILARITY_THRESHOLD,
    ) -> list[RetrievalResult]:
        """Retrieve relevant session event chunks."""
        return await self.retrieve(query, top_k=top_k, sources=["event"], min_score=min_score)

    async def retrieve_all(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = SIMILARITY_THRESHOLD,
    ) -> list[RetrievalResult]:
        """Retrieve from all sources."""
        return await self.retrieve(query, top_k=top_k, min_score=min_score)

    # ── Context injection ─────────────────────────────────────────────────

    async def build_context_prompt(
        self,
        query: str,
        max_tokens: int = 16384,
        top_k: int = 5,
    ) -> str:
        """Build a context prompt by retrieving relevant chunks for a query.

        Used to inject relevant context into the agent's prompt when
        the context window is filling up or when the agent needs external knowledge.
        """
        results = await self.retrieve_all(query, top_k=top_k)
        if not results:
            return ""

        parts = ["# Retrieved Context\n"]
        total_tokens = 0

        for i, result in enumerate(results, 1):
            chunk_prompt = f"## [{result.source}] {result.source_id} (score: {result.score:.3f})\n\n{result.content}\n"
            chunk_tokens = estimate_tokens(chunk_prompt)

            if total_tokens + chunk_tokens > max_tokens:
                parts.append(f"\n... ({top_k - i + 1} more results omitted due to token limit)")
                break

            parts.append(chunk_prompt)
            total_tokens += chunk_tokens

        return "\n".join(parts)

    # ── Stats ─────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """Get statistics about the RAG index."""
        if not self._db:
            return {"error": "RAGRetriever not initialized"}

        async with self._db.execute("SELECT COUNT(*) FROM chunks") as cursor:
            total = (await cursor.fetchone())[0]

        async with self._db.execute(
            "SELECT source, COUNT(*) FROM chunks GROUP BY source"
        ) as cursor:
            by_source = dict(await cursor.fetchall())

        return {
            "total_chunks": total,
            "by_source": by_source,
            "indexed_files": len(self._indexed_files),
        }

    async def reindex(self, project_root: str | None = None) -> int:
        """Clear the index and re-index everything."""
        if self._db:
            await self._db.execute("DELETE FROM chunks")
            await self._db.commit()
        self._indexed_files.clear()
        log.info("RAG index cleared, re-indexing...")
        return await self.index_codebase(project_root)


# ── Module-level singleton accessor ────────────────────────────────────────

_rag_retriever: RAGRetriever | None = None


def get_rag_retriever() -> RAGRetriever | None:
    """Get the module-level RAGRetriever singleton (set during lifespan)."""
    return _rag_retriever


def set_rag_retriever(retriever: RAGRetriever) -> None:
    """Set the module-level RAGRetriever singleton."""
    global _rag_retriever
    _rag_retriever = retriever
