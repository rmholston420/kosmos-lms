"""Stage 8.6 · ADR-108 tests — :class:`ArchetypeTracker`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from plugins.tektos.manager import Archetype, ArchetypeEvent, ArchetypeTracker


def test_record_event_creates_archetype_and_first_event():
    tracker = ArchetypeTracker(threshold=3)
    event = tracker.record_event("cat_a", "first error", severity="warning")
    assert isinstance(event, ArchetypeEvent)
    assert len(tracker.events) == 1
    arche = tracker.get_archetype("cat_a")
    assert arche is not None
    assert arche.occurrence_count == 1
    assert arche.threshold == 3
    assert len(arche.events) == 1


def test_record_event_increments_existing_archetype():
    tracker = ArchetypeTracker(threshold=5)
    for i in range(4):
        tracker.record_event("cat_a", f"err {i}")
    arche = tracker.get_archetype("cat_a")
    assert arche is not None
    assert arche.occurrence_count == 4
    assert len(arche.events) == 4
    assert len(tracker.events) == 4


def test_get_archetype_returns_none_for_unknown_category():
    tracker = ArchetypeTracker()
    assert tracker.get_archetype("nope") is None


def test_get_active_archetypes_sorted_by_count_desc():
    tracker = ArchetypeTracker()
    tracker.record_event("small", "d")
    for _ in range(3):
        tracker.record_event("big", "d")
    for _ in range(2):
        tracker.record_event("mid", "d")
    active = tracker.get_active_archetypes()
    assert [a.category for a in active] == ["big", "mid", "small"]


def test_should_create_structure_false_below_threshold():
    tracker = ArchetypeTracker(threshold=3)
    tracker.record_event("cat_a", "d")
    assert tracker.should_create_structure("cat_a") is False


def test_should_create_structure_true_at_threshold_without_structure():
    tracker = ArchetypeTracker(threshold=2)
    tracker.record_event("cat_a", "d")
    tracker.record_event("cat_a", "d")
    assert tracker.should_create_structure("cat_a") is True


def test_should_create_structure_false_once_structure_marked():
    tracker = ArchetypeTracker(threshold=1)
    tracker.record_event("cat_a", "d")
    assert tracker.should_create_structure("cat_a") is True
    tracker.mark_structure_created("cat_a", "skill-xyz")
    assert tracker.should_create_structure("cat_a") is False


def test_should_create_structure_unknown_category_false():
    tracker = ArchetypeTracker(threshold=1)
    assert tracker.should_create_structure("never") is False


def test_get_archetypes_at_threshold_excludes_already_structured():
    tracker = ArchetypeTracker(threshold=1)
    tracker.record_event("done", "d")
    tracker.record_event("pending", "d")
    tracker.mark_structure_created("done", "s-1")
    at = tracker.get_archetypes_at_threshold()
    cats = {a.category for a in at}
    assert cats == {"pending"}


def test_get_archetype_counts_returns_snapshot():
    tracker = ArchetypeTracker()
    tracker.record_event("a", "d")
    tracker.record_event("a", "d")
    tracker.record_event("b", "d")
    assert tracker.get_archetype_counts() == {"a": 2, "b": 1}


def test_mark_structure_created_no_op_for_unknown_category():
    tracker = ArchetypeTracker()
    tracker.mark_structure_created("does_not_exist", "s-1")  # no raise
    assert tracker.get_archetype("does_not_exist") is None


def test_clear_events_bounds_the_global_event_log():
    tracker = ArchetypeTracker()
    for i in range(150):
        tracker.record_event("cat_a", f"d{i}")
    assert len(tracker.events) == 150
    tracker.clear_events(keep_last=50)
    assert len(tracker.events) == 50


def test_clear_events_no_op_when_under_keep_last():
    tracker = ArchetypeTracker()
    tracker.record_event("cat_a", "d")
    tracker.clear_events(keep_last=100)
    assert len(tracker.events) == 1


def test_archetype_dataclass_is_frozen():
    tracker = ArchetypeTracker()
    tracker.record_event("cat_a", "d")
    arche = tracker.get_archetype("cat_a")
    assert isinstance(arche, Archetype)
    with pytest.raises(FrozenInstanceError):
        arche.occurrence_count = 99  # type: ignore[misc]
