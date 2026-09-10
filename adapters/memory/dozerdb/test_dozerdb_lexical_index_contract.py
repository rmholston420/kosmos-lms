"""Contract tests for `DozerDbLexicalIndex` (ADR-100).

Fast tier: mocked `neo4j.AsyncGraphDatabase` — no live DozerDB required.
Live tier: env-gated `KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL=1` — real Bolt
round-trip against `ops/compose/memory.yml`.

Mirrors the discipline used by `test_dozerdb_graph_backend_contract.py`
(Stage 4.2 baseline) so both DozerDB adapters share the same shape.
"""

from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.memory.dozerdb import DozerDbLexicalIndex, LexicalIndex
from adapters.memory.dozerdb.dozerdb_lexical_index import _validate_identifier
from ports.memory import MemoryHit

# ── Helpers ────────────────────────────────────────────────────────────────


class _FakeAsyncResult:
    """Async iterator over canned Neo4j-like records."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            row = next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None
        return row


class _FakeSession:
    def __init__(self, canned_rows_per_call: list[list[dict]]) -> None:
        # A list of canned row-sets, consumed in order across .run() calls.
        self._canned_rows_per_call = list(canned_rows_per_call)
        self.calls: list[tuple[str, dict]] = []
        self.run = AsyncMock(side_effect=self._run_impl)

    async def _run_impl(self, cypher, params):
        self.calls.append((cypher, dict(params)))
        rows = self._canned_rows_per_call.pop(0) if self._canned_rows_per_call else []
        return _FakeAsyncResult(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeDriver:
    """Fake `neo4j.AsyncDriver` whose sessions all share one call log.

    The Cypher call sequence (bootstrap → MERGE → queryNodes) crosses
    multiple sessions in real driver usage; the test needs one flat call
    log to make ordering assertions.
    """

    def __init__(self, canned_rows_per_call: list[list[dict]] | None = None) -> None:
        self._canned = list(canned_rows_per_call or [])
        self.sessions: list[_FakeSession] = []
        self.session_databases: list[str] = []
        self.close = AsyncMock()

    def session(self, *, database: str):
        self.session_databases.append(database)
        # Every session pops from the shared canned queue, so the
        # sequence of `.run` calls across sessions sees them in order.
        session = _FakeSession(self._canned)
        # Point the session at the same list so the shared queue drains.
        session._canned_rows_per_call = self._canned
        self.sessions.append(session)
        return session

    @property
    def all_calls(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for s in self.sessions:
            out.extend(s.calls)
        return out


def _install_fake_neo4j(monkeypatch, driver: _FakeDriver) -> None:
    fake = types.ModuleType("neo4j")
    fake.AsyncGraphDatabase = types.SimpleNamespace(
        driver=MagicMock(return_value=driver)
    )
    monkeypatch.setitem(sys.modules, "neo4j", fake)


def _new_index(monkeypatch, driver: _FakeDriver) -> DozerDbLexicalIndex:
    _install_fake_neo4j(monkeypatch, driver)
    return DozerDbLexicalIndex("bolt://localhost:7687", "neo4j", "pw")


# ── Protocol conformance ───────────────────────────────────────────────────


def test_index_is_runtime_checkable_lexical_index(monkeypatch):
    """`DozerDbLexicalIndex` satisfies `LexicalIndex` (Protocol)."""
    idx = _new_index(monkeypatch, _FakeDriver())
    assert isinstance(idx, LexicalIndex)


# ── Identifier guard (Cypher-injection defence — ADR-100 D2) ───────────────


@pytest.mark.parametrize(
    "bad",
    [
        "Foo; DROP DATABASE neo4j",
        "MemoryEvent WHERE 1=1",
        "with-dash",
        "",
        "1BadLabel",
        "`quoted`",
    ],
)
def test_identifier_guard_rejects_bad_labels(bad):
    with pytest.raises(ValueError, match="invalid Cypher"):
        _validate_identifier("label", bad)


def test_constructor_rejects_bad_label(monkeypatch):
    _install_fake_neo4j(monkeypatch, _FakeDriver())
    with pytest.raises(ValueError, match="invalid Cypher label"):
        DozerDbLexicalIndex(
            "bolt://localhost:7687", "neo4j", "pw", label="Foo; DROP"
        )


def test_constructor_rejects_bad_index_name(monkeypatch):
    _install_fake_neo4j(monkeypatch, _FakeDriver())
    with pytest.raises(ValueError, match="invalid Cypher index_name"):
        DozerDbLexicalIndex(
            "bolt://localhost:7687", "neo4j", "pw", index_name="`quoted`"
        )


# ── Bootstrap-then-index Cypher shape (ADR-100 D2 + D3) ────────────────────


@pytest.mark.asyncio
async def test_index_event_bootstraps_then_merges(monkeypatch):
    driver = _FakeDriver(canned_rows_per_call=[[], []])
    idx = _new_index(monkeypatch, driver)
    as_of = datetime(2026, 9, 10, 3, 29, tzinfo=timezone.utc)

    await idx.index_event(
        "evt-1",
        {
            "subject": "agent",
            "predicate": "runs",
            "object": "kosmos",
            "attributes": {"corpus_name": "alpha"},
        },
        as_of=as_of,
    )

    calls = driver.all_calls
    assert len(calls) == 2, f"expected [bootstrap, merge], got {calls!r}"

    bootstrap_cypher, _ = calls[0]
    assert "CREATE FULLTEXT INDEX memory_event_fulltext IF NOT EXISTS" in bootstrap_cypher
    assert "FOR (n:MemoryEvent)" in bootstrap_cypher
    assert "ON EACH [n.text]" in bootstrap_cypher

    merge_cypher, merge_params = calls[1]
    assert "MERGE (n:MemoryEvent {id: $id})" in merge_cypher
    assert "SET n.text = $text" in merge_cypher
    assert "n.as_of = datetime($as_of_iso)" in merge_cypher
    assert "n.corpus_name = $corpus" in merge_cypher
    assert merge_params == {
        "id": "evt-1",
        "text": "agent runs kosmos",
        "as_of_iso": as_of.isoformat(),
        "corpus": "alpha",
    }


@pytest.mark.asyncio
async def test_index_event_bootstrap_is_idempotent_across_calls(monkeypatch):
    """Second `index_event` skips the CREATE FULLTEXT INDEX Cypher."""
    driver = _FakeDriver(canned_rows_per_call=[[], [], []])
    idx = _new_index(monkeypatch, driver)
    as_of = datetime(2026, 9, 10, 3, 29, tzinfo=timezone.utc)

    await idx.index_event("evt-1", {"subject": "a", "predicate": "b", "object": "c"}, as_of=as_of)
    await idx.index_event("evt-2", {"subject": "d", "predicate": "e", "object": "f"}, as_of=as_of)

    calls = driver.all_calls
    # 1 bootstrap + 2 MERGEs
    assert len(calls) == 3
    bootstrap_count = sum(1 for c, _ in calls if "CREATE FULLTEXT INDEX" in c)
    merge_count = sum(1 for c, _ in calls if c.startswith("MERGE (n:MemoryEvent"))
    assert bootstrap_count == 1
    assert merge_count == 2


@pytest.mark.asyncio
async def test_index_event_missing_corpus_writes_null(monkeypatch):
    driver = _FakeDriver(canned_rows_per_call=[[], []])
    idx = _new_index(monkeypatch, driver)
    await idx.index_event(
        "evt-x",
        {"subject": "s", "predicate": "p", "object": "o"},
        as_of=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    _, merge_params = driver.all_calls[1]
    assert merge_params["corpus"] is None


# ── search_lexical Cypher shape + payload rehydration (ADR-100 D4) ─────────


@pytest.mark.asyncio
async def test_search_lexical_returns_ordered_memoryhits(monkeypatch):
    canned_hit_rows = [
        {"id": "evt-a", "text": "agent runs kosmos", "corpus_name": "alpha", "as_of": None, "score": 3.14},
        {"id": "evt-b", "text": "agent stops kosmos", "corpus_name": "alpha", "as_of": None, "score": 1.59},
    ]
    # Bootstrap (empty) then queryNodes (2 rows).
    driver = _FakeDriver(canned_rows_per_call=[[], canned_hit_rows])
    idx = _new_index(monkeypatch, driver)

    hits = await idx.search_lexical("agent", corpus="alpha", limit=10)

    assert len(hits) == 2
    assert all(isinstance(h, MemoryHit) for h in hits)
    assert hits[0].id == "evt-a"
    assert hits[0].score == pytest.approx(3.14)
    assert hits[0].payload == {"text": "agent runs kosmos", "attributes": {"corpus_name": "alpha"}}
    assert hits[1].id == "evt-b"
    assert hits[1].score == pytest.approx(1.59)


@pytest.mark.asyncio
async def test_search_lexical_cypher_uses_fulltext_procedure(monkeypatch):
    driver = _FakeDriver(canned_rows_per_call=[[], []])
    idx = _new_index(monkeypatch, driver)
    await idx.search_lexical("agent", corpus="alpha", limit=7)

    calls = driver.all_calls
    # bootstrap + queryNodes
    assert len(calls) == 2
    query_cypher, query_params = calls[1]
    assert "CALL db.index.fulltext.queryNodes($index_name, $query)" in query_cypher
    assert "YIELD node, score" in query_cypher
    assert "WHERE $corpus IS NULL OR node.corpus_name = $corpus" in query_cypher
    assert "ORDER BY score DESC" in query_cypher
    assert "LIMIT $limit" in query_cypher
    assert query_params == {
        "index_name": "memory_event_fulltext",
        "query": "agent",
        "corpus": "alpha",
        "limit": 7,
    }


@pytest.mark.asyncio
async def test_search_lexical_corpus_none_passes_null(monkeypatch):
    driver = _FakeDriver(canned_rows_per_call=[[], []])
    idx = _new_index(monkeypatch, driver)
    await idx.search_lexical("agent", corpus=None, limit=5)
    _, params = driver.all_calls[1]
    assert params["corpus"] is None


@pytest.mark.asyncio
async def test_search_lexical_empty_query_short_circuits(monkeypatch):
    driver = _FakeDriver(canned_rows_per_call=[])
    idx = _new_index(monkeypatch, driver)
    hits = await idx.search_lexical("", corpus=None, limit=10)
    assert hits == []
    assert driver.all_calls == []  # no bootstrap, no queryNodes


@pytest.mark.asyncio
async def test_search_lexical_hit_without_corpus_returns_minimal_payload(monkeypatch):
    canned = [{"id": "evt-y", "text": "hello world", "corpus_name": None, "as_of": None, "score": 0.5}]
    driver = _FakeDriver(canned_rows_per_call=[[], canned])
    idx = _new_index(monkeypatch, driver)
    hits = await idx.search_lexical("hello", corpus=None, limit=1)
    assert len(hits) == 1
    assert hits[0].payload == {"text": "hello world"}


@pytest.mark.asyncio
async def test_search_lexical_procedure_failure_degrades_to_empty(monkeypatch, caplog):
    """Lucene parse errors or missing-index errors return []; do not raise."""

    class _FailingSession(_FakeSession):
        def __init__(self):
            super().__init__([[]])

        async def _run_impl(self, cypher, params):
            self.calls.append((cypher, dict(params)))
            if "queryNodes" in cypher:
                raise RuntimeError("Neo4j:ClientError:Procedure.ProcedureCallFailed")
            return _FakeAsyncResult([])

    driver = _FakeDriver()

    def _session(*, database):
        driver.session_databases.append(database)
        s = _FailingSession()
        driver.sessions.append(s)
        return s

    driver.session = _session  # type: ignore[method-assign]

    idx = _new_index(monkeypatch, driver)
    with caplog.at_level("WARNING"):
        hits = await idx.search_lexical("bad(query", corpus=None, limit=5)
    assert hits == []
    assert any("procedure call failed" in r.getMessage().lower() for r in caplog.records)


# ── Health / close (ADR-023 rule 5) ────────────────────────────────────────


def test_is_healthy_true_on_construction(monkeypatch):
    idx = _new_index(monkeypatch, _FakeDriver())
    assert idx.is_healthy() is True


@pytest.mark.asyncio
async def test_is_healthy_false_after_close(monkeypatch):
    idx = _new_index(monkeypatch, _FakeDriver())
    await idx.close()
    assert idx.is_healthy() is False


@pytest.mark.asyncio
async def test_close_is_idempotent(monkeypatch):
    driver = _FakeDriver()
    idx = _new_index(monkeypatch, driver)
    await idx.close()
    await idx.close()  # second close is a no-op, must not raise
    # Underlying driver.close called exactly once.
    assert driver.close.call_count == 1


@pytest.mark.asyncio
async def test_close_swallows_driver_error(monkeypatch, caplog):
    driver = _FakeDriver()
    driver.close = AsyncMock(side_effect=RuntimeError("bolt teardown boom"))
    idx = _new_index(monkeypatch, driver)
    with caplog.at_level("WARNING"):
        await idx.close()  # must not raise
    assert idx.is_healthy() is False
    assert any("swallowed driver error" in r.getMessage() for r in caplog.records)


def test_is_healthy_false_when_driver_init_fails(monkeypatch):
    """Driver-build exception is captured into `_init_error`; is_healthy → False."""
    fake = types.ModuleType("neo4j")

    def _boom(*args, **kwargs):
        raise RuntimeError("cannot resolve bolt host")

    fake.AsyncGraphDatabase = types.SimpleNamespace(driver=MagicMock(side_effect=_boom))
    monkeypatch.setitem(sys.modules, "neo4j", fake)
    idx = DozerDbLexicalIndex("bolt://nowhere:7687", "neo4j", "pw")
    assert idx.is_healthy() is False
    assert idx._init_error is not None  # noqa: SLF001 — test-only introspection


@pytest.mark.asyncio
async def test_index_event_after_close_raises(monkeypatch):
    idx = _new_index(monkeypatch, _FakeDriver())
    await idx.close()
    with pytest.raises(RuntimeError, match="closed"):
        await idx.index_event(
            "evt-z",
            {"subject": "s", "predicate": "p", "object": "o"},
            as_of=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )


# ── Session database wiring ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_uses_configured_database(monkeypatch):
    driver = _FakeDriver(canned_rows_per_call=[[], []])
    _install_fake_neo4j(monkeypatch, driver)
    idx = DozerDbLexicalIndex(
        "bolt://localhost:7687", "neo4j", "pw", database="kosmos_test"
    )
    await idx.index_event(
        "evt-1",
        {"subject": "s", "predicate": "p", "object": "o"},
        as_of=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    assert driver.session_databases == ["kosmos_test", "kosmos_test"]


# ── Env-gated live tier ────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.getenv("KOSMOS_STAGE_74_REAL_DOZERDB_LEXICAL"),
    reason="live tier requires docker compose -f ops/compose/memory.yml up",
)
@pytest.mark.asyncio
async def test_live_round_trip_against_dozerdb():
    uri = os.getenv("MEMORY_BOLT_URI", "bolt://localhost:7687")
    user = os.getenv("MEMORY_BOLT_USER", "neo4j")
    pw = os.getenv("MEMORY_BOLT_PASSWORD", "kosmos-dev-password")
    idx = DozerDbLexicalIndex(uri, user, pw, index_name="kosmos_test_fulltext")
    try:
        assert idx.is_healthy()
        as_of = datetime(2026, 9, 10, tzinfo=timezone.utc)
        await idx.index_event(
            "live-1",
            {"subject": "kosmos", "predicate": "runs", "object": "smoke", "attributes": {"corpus_name": "live"}},
            as_of=as_of,
        )
        await idx.index_event(
            "live-2",
            {"subject": "kosmos", "predicate": "hosts", "object": "smoke", "attributes": {"corpus_name": "other"}},
            as_of=as_of,
        )
        # Corpus-scoped read should filter to "live" only.
        hits = await idx.search_lexical("smoke", corpus="live", limit=10)
        assert any(h.id == "live-1" for h in hits)
        assert not any(h.id == "live-2" for h in hits)
    finally:
        # Best-effort cleanup so the live tier is repeatable.
        try:
            await idx._run(
                f"MATCH (n:MemoryEvent) WHERE n.id IN $ids DETACH DELETE n",
                {"ids": ["live-1", "live-2"]},
            )
        except Exception:  # noqa: BLE001
            pass
        await idx.close()
