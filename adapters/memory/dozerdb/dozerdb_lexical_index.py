"""adapters.memory.dozerdb.dozerdb_lexical_index — Real Neo4j-fulltext ``LexicalIndex`` (ADR-100).

Backs the ``LexicalIndex`` Protocol defined in
``adapters.memory.dozerdb.adapter`` with a DozerDB (Neo4j-Bolt-compatible)
Lucene fulltext index. Persistent across restarts; O(log N) query cost;
reuses the ``neo4j`` async driver already vendored in Stage 1.8 (per
ADR-100 D1).

Key invariants (Kosmos custom instructions + ADR-023 rule 5 + ADR-047):

- ``label`` and ``index_name`` are validated against the Neo4j identifier
  regex before literal interpolation into the ``CREATE FULLTEXT INDEX``
  Cypher statement (that statement does not accept ``$name`` parameter
  substitution for the index name). The guard is non-optional and matches
  ``DozerDbGraphBackend``'s Cypher-injection defence.
- Bootstrap is lazy — ``CREATE FULLTEXT INDEX ... IF NOT EXISTS`` fires
  on the first ``index_event`` call, gated by ``self._index_ready``.
  Construction never touches the network (mirrors ``DozerDbGraphBackend``).
- ``is_healthy`` is sync + non-throwing.
- ``close`` is async + idempotent + swallows driver errors into a warning.
- Lucene procedure failures degrade to ``[]`` with a warning log — the
  fusion caller (``DozerDbMemoryAdapter.search_hybrid``) still has the
  semantic leg to work with (ADR-100 D4).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from adapters.memory.dozerdb.adapter import _lex_text_from_payload
from ports.memory import MemoryHit

log = logging.getLogger(__name__)

# Same identifier grammar as ``DozerDbGraphBackend`` — no backtick-quoting,
# no injection surface. See ADR-047 rationale.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(kind: str, value: str) -> None:
    """Raise ValueError if `value` is not a safe Cypher identifier.

    ADR-100 D2 mandates this on ``label`` and ``index_name`` because
    ``CREATE FULLTEXT INDEX`` does not accept ``$name`` parameter
    substitution — the identifier is interpolated as a Cypher literal.
    """
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise ValueError(
            f"DozerDbLexicalIndex: invalid Cypher {kind} {value!r}; must match "
            f"{_IDENT_RE.pattern}. Reject-by-default guard for identifier injection."
        )


class DozerDbLexicalIndex:
    """Bolt-backed ``LexicalIndex`` for the DozerDbMemoryAdapter (ADR-100).

    Uses ``neo4j.AsyncGraphDatabase.driver`` as an async connection pool
    and a single Lucene fulltext index on ``(:MemoryEvent).text``. Both
    the node label and the index name are constructor-tunable so a
    multi-tenant DozerDB instance can host multiple Kosmos deployments
    without index-name collisions.

    Contract tests exercise this class with a mocked ``neo4j`` driver
    (`test_dozerdb_lexical_index_contract.py`) so the fast tier does not
    require a live DozerDB. The env-gated live tier
    (``KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL=1``) exercises the real
    driver against the compose service in ``ops/compose/memory.yml``.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        database: str = "neo4j",
        label: str = "MemoryEvent",
        index_name: str = "memory_event_fulltext",
    ) -> None:
        # Both go through the Cypher-injection guard because both will be
        # literally interpolated into `CREATE FULLTEXT INDEX ... FOR (n:<label>)`.
        _validate_identifier("label", label)
        _validate_identifier("index_name", index_name)
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._label = label
        self._index_name = index_name
        self._driver: Any | None = None
        self._closed = False
        self._init_error: str | None = None
        self._index_ready = False
        try:
            from neo4j import AsyncGraphDatabase  # lazy import — ADR-100 D1

            self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        except Exception as e:  # noqa: BLE001 — surface via is_healthy
            self._init_error = f"{type(e).__name__}: {e}"
            log.warning(
                "DozerDbLexicalIndex init failed (uri=%s): %s",
                uri,
                self._init_error,
            )

    # ── LexicalIndex Protocol surface ───────────────────────────────────

    async def index_event(
        self,
        event_id: str,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> None:
        """Index one MemoryPort write into the Lucene fulltext index.

        Idempotent per ``event_id`` — a subsequent write with the same
        id overwrites (MERGE + SET). The lazy fulltext-index bootstrap
        fires on the first call and is a no-op on subsequent calls
        (per Neo4j's ``IF NOT EXISTS`` semantics).
        """
        if self._closed or self._driver is None:
            raise RuntimeError(
                "DozerDbLexicalIndex is closed or the driver failed to init; "
                f"init_error={self._init_error!r}"
            )
        if not self._index_ready:
            await self._bootstrap_index()

        corpus = (payload.get("attributes") or {}).get("corpus_name")
        text = _lex_text_from_payload(payload)

        cypher = (
            f"MERGE (n:{self._label} {{id: $id}}) "
            f"SET n.text = $text, "
            f"    n.as_of = datetime($as_of_iso), "
            f"    n.corpus_name = $corpus"
        )
        await self._run(
            cypher,
            {
                "id": event_id,
                "text": text,
                "as_of_iso": as_of.isoformat(),
                "corpus": corpus,
            },
        )

    async def search_lexical(
        self,
        query: str,
        *,
        corpus: str | None,
        limit: int,
    ) -> list[MemoryHit]:
        """Lexical retrieval via ``db.index.fulltext.queryNodes`` (ADR-100 D4).

        Post-YIELD corpus filter (single-index design; see ADR-100
        Rationale). ``MemoryHit.payload`` is the minimal reconstruction
        described in ADR-100 D4 — callers who need the full triple
        rehydrate through ``MemoryPort.query_temporal``.

        On procedure-call failure (Lucene parse error, missing index,
        etc.) returns ``[]`` and logs a warning. This matches the
        log-only side-effect discipline established for lexical writes
        in ``DozerDbMemoryAdapter.write_event`` (ADR-099
        implementation).
        """
        if not query:
            return []
        if self._closed or self._driver is None:
            return []
        if not self._index_ready:
            # A search before any write is legal — bootstrap so the
            # `queryNodes` call doesn't fail on a missing index.
            try:
                await self._bootstrap_index()
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "DozerDbLexicalIndex.search_lexical: bootstrap failed: %s",
                    exc,
                )
                return []

        cypher = (
            "CALL db.index.fulltext.queryNodes($index_name, $query) "
            "YIELD node, score "
            "WHERE $corpus IS NULL OR node.corpus_name = $corpus "
            "RETURN node.id AS id, "
            "       node.text AS text, "
            "       node.corpus_name AS corpus_name, "
            "       node.as_of AS as_of, "
            "       score AS score "
            "ORDER BY score DESC "
            "LIMIT $limit"
        )
        try:
            rows = await self._run(
                cypher,
                {
                    "index_name": self._index_name,
                    "query": query,
                    "corpus": corpus,
                    "limit": int(limit),
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "DozerDbLexicalIndex.search_lexical: procedure call failed: %s",
                exc,
            )
            return []

        hits: list[MemoryHit] = []
        for row in rows:
            row_id = row.get("id")
            if row_id is None:
                # Defensive: a row without an id can't participate in RRF.
                continue
            attributes: dict[str, Any] = {}
            row_corpus = row.get("corpus_name")
            if row_corpus:
                attributes["corpus_name"] = row_corpus
            payload: dict[str, Any] = {"text": row.get("text", "")}
            if attributes:
                payload["attributes"] = attributes
            hits.append(
                MemoryHit(
                    id=str(row_id),
                    payload=payload,
                    score=float(row.get("score", 0.0)),
                    as_of=_coerce_as_of(row.get("as_of")),
                )
            )
        return hits

    # ── health / teardown ───────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Sync + non-throwing readiness probe (ADR-023 rule 5)."""
        if self._closed:
            return False
        if self._init_error is not None:
            return False
        return self._driver is not None

    async def close(self) -> None:
        """Idempotent close — swallows driver errors into a warning."""
        if self._closed:
            return
        self._closed = True
        driver = self._driver
        self._driver = None
        if driver is None:
            return
        try:
            await driver.close()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "DozerDbLexicalIndex.close swallowed driver error: %s: %s",
                type(e).__name__,
                e,
            )

    # ── internal ────────────────────────────────────────────────────────

    async def _bootstrap_index(self) -> None:
        """Create the Lucene fulltext index if not already present.

        Uses ``IF NOT EXISTS`` for idempotency (per Neo4j 5.x semantics).
        The index name and label are interpolated as Cypher literals
        (Neo4j does not accept ``$name`` substitution here), so both
        went through ``_validate_identifier`` at construction time
        (ADR-100 D2).
        """
        cypher = (
            f"CREATE FULLTEXT INDEX {self._index_name} IF NOT EXISTS "
            f"FOR (n:{self._label}) ON EACH [n.text]"
        )
        await self._run(cypher, {})
        self._index_ready = True

    async def _run(
        self,
        cypher: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self._closed or self._driver is None:
            raise RuntimeError(
                "DozerDbLexicalIndex is closed or the driver failed to init; "
                f"init_error={self._init_error!r}"
            )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params)
            records = [dict(r) async for r in result]
            return records


def _coerce_as_of(value: Any) -> datetime | None:
    """Best-effort coercion of a Neo4j ``datetime`` cell to Python ``datetime``.

    The real ``neo4j`` driver returns ``neo4j.time.DateTime`` for
    ``datetime()``-typed properties; those expose a ``.to_native()``
    that returns a standard-library ``datetime``. Mocked drivers may
    return a plain ``datetime`` directly (or ``None``).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        try:
            native = to_native()
        except Exception:  # noqa: BLE001
            return None
        if isinstance(native, datetime):
            return native
    return None
