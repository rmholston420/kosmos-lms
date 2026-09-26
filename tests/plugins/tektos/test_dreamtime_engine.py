"""T8c-8a — dreamtime substrate port (ADR-141).

Donor: tektos-ultima-v1 src/tektos/memory/memory_system.py — MemoryTier/Hemisphere/
MemoryEntry/DreamState/DreamResult (models) + DreamtimeEngine (735-993), verbatim.

Kernel referent: plugins/tektos/memory/dreamtime.py — verbatim engine + models +
DictMemoryStore adapter (donor MemorySystem call surface over the T6 dict store).

Tests exercise the engine against a FakeStore implementing the 4 donor methods —
no SQLite, no GPU, no network. Boot wiring (registry slot) + the 4 HTTP routes
land in T8c-8b.
"""

from __future__ import annotations

from plugins.tektos.memory.dreamtime import (
    DictMemoryStore,
    DreamResult,
    DreamState,
    DreamtimeEngine,
    Hemisphere,
    MemoryEntry,
    MemoryTier,
)


class FakeStore:
    """Implements the 4 donor MemorySystem methods DictMemoryStore needs."""

    def __init__(self) -> None:
        self.lt: list[dict] = []
        self.proc: list[dict] = []
        self.lt_limit: int | None = None

    def load_long_term(self, limit: int = 20) -> list[dict]:
        self.lt_limit = limit
        return list(self.lt)[:limit]

    def load_procedural(self, limit: int = 1000) -> list[dict]:
        return list(self.proc)[:limit]

    def save_long_term(self, entry: dict) -> str:
        self.lt.append(entry)
        return entry["id"]

    def save_procedural(self, entry: dict) -> str:
        self.proc.append(entry)
        return entry["id"]


def _lt_entry(
    content: str,
    hemisphere: str = "left",
    what: str = "",
    novel: bool = False,
    score: float = 0.0,
) -> dict:
    return {
        "id": f"mem-{abs(hash(content)) % 10**8:08d}",
        "content": content,
        "hemisphere": hemisphere,
        "is_novel": novel,
        "novelty_score": score,
        "timestamp": "2026-09-26T00:00:00+00:00",
        "who": "",
        "what": what,
        "where": "",
        "when": "",
        "why": "",
        "how": "",
        "metadata": {},
    }


def test_dict_store_maps_rows_to_memory_entries():
    store = FakeStore()
    store.lt.append(_lt_entry("alpha concept", hemisphere="right", what="alpha concept"))
    adapter = DictMemoryStore(store)
    entries = adapter.get_recent_long_term(limit=5)
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, MemoryEntry)
    assert e.tier == MemoryTier.LONG_TERM
    assert e.hemisphere == Hemisphere.RIGHT
    assert e.content == "alpha concept"
    assert e.what == "alpha concept"


def test_dict_store_add_long_term_roundtrip():
    store = FakeStore()
    adapter = DictMemoryStore(store)
    e = adapter.add_long_term_memory(
        content="a memory",
        hemisphere=Hemisphere.RIGHT,
        is_novel=True,
        novelty_score=0.3,
        what="a memory",
    )
    assert isinstance(e, MemoryEntry)
    assert e.tier == MemoryTier.LONG_TERM
    assert len(store.lt) == 1
    assert store.lt[0]["content"] == "a memory"
    assert store.lt[0]["hemisphere"] == "right"
    assert store.lt[0]["is_novel"] is True
    assert store.lt[0]["novelty_score"] == 0.3


def test_dict_store_add_procedural_pops_hemisphere_kwarg():
    # The verbatim engine passes hemisphere= as a kwarg to add_procedural_memory
    # (whose donor signature has no such param) — the adapter must absorb it.
    store = FakeStore()
    adapter = DictMemoryStore(store)
    e = adapter.add_procedural_memory(
        content="a skill",
        hemisphere=Hemisphere.RIGHT,
        is_novel=True,
        novelty_score=0.8,
        what="dreamtime_insight",
    )
    assert isinstance(e, MemoryEntry)
    assert e.tier == MemoryTier.PROCEDURAL
    assert len(store.proc) == 1
    assert store.proc[0]["content"] == "a skill"


def test_engine_full_pipeline_generates_insights_and_saves():
    store = FakeStore()
    store.lt.append(_lt_entry("billing refactor unknown?", what="billing refactor"))
    store.lt.append(
        _lt_entry("billing rules right-brain", hemisphere="right", what="billing rules", novel=True)
    )
    store.lt.append(_lt_entry("emergent billing insight", what="billing insight", novel=True))
    engine = DreamtimeEngine(DictMemoryStore(store))
    result = engine.run_contemplation(max_memories=10)
    assert isinstance(result, DreamResult)
    assert result.source_count == 3
    assert result.insight_count >= 1
    # cross-domain connection (shared "billing") + synthesis + gap
    joined = " ".join(result.insights)
    assert "Connection" in joined
    assert "Synthesis" in joined
    assert "Gap" in joined
    assert result.is_novel is True
    # insights persisted (novelty>0.5 → procedural, else long-term)
    assert len(store.lt) + len(store.proc) > 3
    # state machine returns to IDLE and records history
    assert engine.state == DreamState.IDLE
    assert engine.get_dream_history() == [result]


def test_engine_empty_store_returns_zero_result():
    engine = DreamtimeEngine(DictMemoryStore(FakeStore()))
    result = engine.run_contemplation(max_memories=10)
    assert result.source_count == 0
    assert result.insight_count == 0
    assert result.is_novel is False
    assert result.novelty_score == 0.0
    assert result.insights == []
    assert engine.state == DreamState.IDLE


def test_engine_focus_area_filters_gathered_memories():
    store = FakeStore()
    store.lt.append(_lt_entry("about billing", what="billing"))
    store.lt.append(_lt_entry("about cooking pasta", what="cooking"))
    engine = DreamtimeEngine(DictMemoryStore(store))
    gathered = engine.begin_contemplation(max_memories=10, focus_area="billing")
    assert len(gathered) == 1
    assert gathered[0].content == "about billing"
    # begin_contemplation is the only state transition before process;
    # after gather the state is PROCESSING
    assert engine.state == DreamState.PROCESSING


def test_summary_shape_donor_wire():
    store = FakeStore()
    store.lt.append(_lt_entry("billing refactor unknown?", what="billing"))
    engine = DreamtimeEngine(DictMemoryStore(store))
    engine.run_contemplation(max_memories=10)
    s = engine.get_summary()
    assert s["state"] == "idle"
    assert s["total_dreams"] == 1
    assert s["total_insights"] >= 1
    assert isinstance(s["recent_dreams"], list)
    rd = s["recent_dreams"][0]
    for key in ("id", "source_count", "insight_count", "is_novel", "novelty_score", "timestamp"):
        assert key in rd
