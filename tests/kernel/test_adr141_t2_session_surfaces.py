"""ADR-141 T2 — session-adjacent surfaces: state anchor + events + archive.

Wire-shape fidelity for the nine donor routes the :8020 proxy served from
``tektos-ultima-v1`` main.py:

- T2a  ``GET  /api/state/{sid}``                     (donor :4798)
- T2a  ``POST /api/state/{sid}/save``                (donor :4818, StateSaveRequest :4780)
- T2a  ``POST /api/state/{sid}/snapshot``            (donor :4866)
- T2b  ``GET  /api/sessions/{sid}/events``           (donor :4115, event_store.get_events :148)
- T2c  ``GET  /api/archive/sessions``                (donor :4141)
- T2c  ``GET  /api/archive/sessions/{sid}``          (donor :4163)
- T2c  ``GET  /api/archive/sessions/{sid}/messages`` (donor :4182)
- T2c  ``POST /api/archive/sessions/{sid}/rename``   (donor :4190)
- T2c  ``POST /api/archive/sessions/{sid}/tag``      (donor :4199)

Kernel referents: ``kernel/session_state.py`` (T2a — the 356-LOC donor port
with the per-session file fix), ``registry.session`` (the ADR-103
SessionPort — a real ``TektosSessionAdapter`` per the ADR-132 test pattern,
monkeypatched per test so nothing global leaks), and
``kernel/tektos_replay.get_events`` (T2b — filtered view over the same bus
read as ``/replay``).

TestClient is used WITHOUT lifespan (ADR-132 style): the session port and
event bus are fixture-installed, so no env gates and no cross-test state.
State files are keyed per-session under the process cwd
(``<cwd>/tektos_state/<sid>.md``); the fixture ``monkeypatch.chdir``s to
``tmp_path`` so no artifacts leak into the repo workspace.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adapters.session.tektos.adapter import TektosSessionAdapter
from kernel import app as ka
from ports.event_envelope import EventEnvelope


class FakeBus:
    """In-memory EventBusPort stand-in (ADR-132 style).

    Stream-per-event-type (like the Valkey backend) with a monotonic
    entry-id counter: ids sort numerically (ms, then seq) exactly like
    Valkey's ``ms-seq`` ids, so ``tektos_replay`` ordering holds.
    """

    def __init__(self) -> None:
        self.stores: dict[str, list[tuple[str, EventEnvelope]]] = {}
        self._n = 0
        self._lock = threading.Lock()

    async def publish(self, envelope: EventEnvelope) -> Any:
        with self._lock:
            self._n += 1
            entry_id = f"{self._n}-1"
            self.stores.setdefault(envelope.event_type, []).append(
                (entry_id, envelope)
            )
        return None

    async def read_recent(self, *, event_type: str, count: int | None = None) -> Any:
        items = list(self.stores.get(event_type, []))
        if count is not None:
            items = items[-count:]
        return items


@pytest.fixture()
def tc(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """Kernel app with a real TektosSessionAdapter + fake bus (ADR-132).

    No lifespan: the port is fixture-installed. ``_state_managers`` and
    ``registry.errors`` are cleared per test (module-level route state).
    cwd → ``tmp_path`` (auto-restored) so ``tektos_state/*.md`` files land
    in the temp dir, never the repo workspace.
    """
    monkeypatch.chdir(tmp_path)
    bus = FakeBus()
    port = TektosSessionAdapter(event_bus=bus)
    monkeypatch.setattr(ka.registry, "session", port)
    monkeypatch.setattr(ka.registry, "event_bus", bus)
    ka._state_managers.clear()
    ka.registry.errors.clear()
    yield TestClient(ka.app)


def _new_session(tc: TestClient, model: str = "m-test") -> str:
    r = tc.post("/api/sessions", json={"model": model})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _state_file(tc: TestClient, sid: str):
    """The live manager's per-session file (proves the kernel fix's keying)."""
    mgr = ka._state_managers.get(sid)
    assert mgr is not None, f"no state manager registered for {sid}"
    return mgr.state_file


# ── T2a: /api/state ─────────────────────────────────────────────────────────


def test_state_get_404_before_save(tc: TestClient) -> None:
    """Donor semantics: no manager + no file → 404 (main.py:4804-4806)."""
    r = tc.get("/api/state/t2a-ghost-1")
    assert r.status_code == 404
    assert "t2a-ghost-1" in r.json()["detail"]


def test_state_save_wire_and_file(tc: TestClient) -> None:
    """POST save returns {ok, version:1} (donor builds a fresh state) and
    lands the per-session file (the documented donor fix — the donor keyed
    every session at one shared path).
    """
    sid = "t2a-save"
    body = {
        "objective": "port T2",
        "progress": "state layer",
        "completion_pct": 42.0,
        "current_file": "kernel/app.py",
        "current_command": "pytest -q",
        "next_steps": ["T2b", "T2c"],
        "key_decisions": ["per-session files"],
        "constraints": ["no creds"],
        "blockers": ["none"],
        "todo_items": [{"content": "routes", "status": "completed"}],
        "notes": ["smoke"],
        "referenced_files": ["session_state.py"],
    }
    r = tc.post(f"/api/state/{sid}/save", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "version": 1}

    f = _state_file(tc, sid)
    assert f.exists(), "state file must exist for the saved session"
    assert f.parent.name == "tektos_state" and f.name == f"{sid}.md", (
        "donor fix: file must be keyed per-session"
    )
    md = f.read_text()
    assert md.startswith("# LAST_KNOWN_STATE.md")
    assert "**Session:** t2a-save" in md
    assert "**Completion:** 42.0%" in md
    f.unlink()  # keep the workspace tidy between tests


def test_state_get_wire(tc: TestClient) -> None:
    """GET returns {session_id, state: to_dict(), markdown} — donor shape
    (main.py:4808-4812); the parsed dict carries the saved fields.
    """
    sid = "t2a-get"
    tc.post(
        f"/api/state/{sid}/save",
        json={
            "objective": "port T2",
            "progress": "state layer",
            "completion_pct": 42.0,
            "current_file": "kernel/app.py",
            "next_steps": ["T2b", "T2c"],
            "key_decisions": ["per-session files"],
            "todo_items": [{"content": "routes", "status": "completed"}],
        },
    )
    r = tc.get(f"/api/state/{sid}")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"session_id", "state", "markdown"}
    assert d["session_id"] == sid
    s = d["state"]
    assert s["objective"] == "port T2"
    assert s["progress"] == "state layer"
    assert s["completion_pct"] == 42.0
    assert s["current_file"] == "kernel/app.py"
    assert s["next_steps"] == ["T2b", "T2c"]
    assert s["key_decisions"] == ["per-session files"]
    assert s["todo_items"] == [{"content": "routes", "status": "completed"}]
    assert d["markdown"].startswith("# LAST_KNOWN_STATE.md")


def test_state_snapshot_version_bump(tc: TestClient) -> None:
    """POST snapshot bumps version and returns the bumped value
    (main.py:4866-4892). Donor-faithful subtlety (verified against the
    donor manager): the markdown parser does not restore ``version``
    (``from_markdown`` keeps the dataclass default 1), so each snapshot
    loads 1 → bumps to 2 → returns 2, regardless of prior snapshots.
    Unknown session → 404.
    """
    sid = "t2a-snap"
    tc.post(f"/api/state/{sid}/save", json={"objective": "snap test"})
    r = tc.post(f"/api/state/{sid}/snapshot")
    assert r.json() == {"ok": True, "version": 2}
    r = tc.post(f"/api/state/{sid}/snapshot")
    assert r.json() == {"ok": True, "version": 2}, "donor: reload resets version to 1"
    r = tc.post("/api/state/t2a-ghost-2/snapshot")
    assert r.status_code == 404
    assert "t2a-ghost-2" in r.json()["detail"]


def test_state_sessions_isolated(tc: TestClient) -> None:
    """The documented donor fix: session B has no view of session A's file
    (the donor's shared path would cross-contaminate).
    """
    tc.post("/api/state/t2a-a/save", json={"objective": "A goal"})
    assert tc.get("/api/state/t2a-b").status_code == 404
    tc.post("/api/state/t2a-b/save", json={"objective": "B goal"})
    a = tc.get("/api/state/t2a-a").json()["state"]
    assert a["objective"] == "A goal"


def test_state_save_422_bad_body(tc: TestClient) -> None:
    """Pydantic gate on the donor StateSaveRequest field types."""
    r = tc.post("/api/state/t2a-bad/save", json={"completion_pct": "nope"})
    assert r.status_code == 422


# ── T2b: /api/sessions/{sid}/events ─────────────────────────────────────────


def test_events_raw_array_and_seq_order(tc: TestClient) -> None:
    """Donor wire: raw array of {seq, type, payload, protocol_version,
    created_at} in ascending seq (event_store.get_events ORDER BY seq ASC).
    The TektosSessionAdapter emits session.created (+archive) to the bus,
    so a created+archived session has lifecycle rows.
    """
    sid = _new_session(tc)
    tc.post(f"/api/sessions/{sid}/archive")
    r = tc.get(f"/api/sessions/{sid}/events")
    assert r.status_code == 200
    evs = r.json()
    assert isinstance(evs, list)
    assert evs, "a created+archived session must have at least lifecycle events"
    for e in evs:
        assert set(e) == {"seq", "type", "payload", "protocol_version", "created_at"}
    seqs = [e["seq"] for e in evs]
    assert seqs == sorted(seqs), "seq must be ascending"


def test_events_since_seq_and_limit(tc: TestClient) -> None:
    """since_seq keeps rows with seq > since_seq; limit caps after the
    filters (donor query semantics, event_store.py:148-177).
    """
    sid = _new_session(tc)
    tc.post(f"/api/sessions/{sid}/archive")
    all_evs = tc.get(f"/api/sessions/{sid}/events").json()
    assert len(all_evs) >= 2

    r = tc.get(
        f"/api/sessions/{sid}/events",
        params={"since_seq": all_evs[0]["seq"], "limit": 1},
    )
    got = r.json()
    assert len(got) == 1
    assert got[0]["seq"] == all_evs[1]["seq"]
    # since_seq=0 → everything (donor default)
    r = tc.get(f"/api/sessions/{sid}/events", params={"since_seq": 0})
    assert r.json() == all_evs


def test_events_event_type_filter(tc: TestClient) -> None:
    """event_type is an exact match on the (donor-mapped) type."""
    sid = _new_session(tc)
    tc.post(f"/api/sessions/{sid}/archive")
    all_evs = tc.get(f"/api/sessions/{sid}/events").json()
    t0 = all_evs[0]["type"]
    r = tc.get(f"/api/sessions/{sid}/events", params={"event_type": t0})
    got = r.json()
    assert got and all(e["type"] == t0 for e in got)
    expected = [e for e in all_evs if e["type"] == t0]
    assert got == expected
    r = tc.get(
        f"/api/sessions/{sid}/events", params={"event_type": "no-such-type"}
    )
    assert r.json() == []


# ── T2c: /api/archive ───────────────────────────────────────────────────────


def _archive_pair(tc: TestClient) -> tuple[str, str]:
    """One archived + one live session."""
    a = _new_session(tc, model="m-a")
    b = _new_session(tc, model="m-b")
    r = tc.post(f"/api/sessions/{a}/archive")
    assert r.status_code == 200, r.text
    return a, b


def test_archive_list_wire(tc: TestClient) -> None:
    """Donor wire (main.py:4141-4160): raw array, is_archived-filtered,
    donor field set {id,title,tag,model,root_session_id,updated_at,
    is_archived}.
    """
    a, b = _archive_pair(tc)
    r = tc.get("/api/archive/sessions")
    assert r.status_code == 200
    arr = r.json()
    assert isinstance(arr, list)
    mine = [e for e in arr if e["id"] == a]
    assert len(mine) == 1
    el = mine[0]
    assert set(el) == {
        "id",
        "title",
        "tag",
        "model",
        "root_session_id",
        "updated_at",
        "is_archived",
    }
    assert el["is_archived"] is True
    assert el["model"] == "m-a"
    # the live session is filtered out (donor `if s.is_archived`)
    assert all(e["id"] != b for e in arr)


def test_archive_list_search(tc: TestClient) -> None:
    """search runs the donor substring query over title/tag/id/root."""
    a, _ = _archive_pair(tc)
    r = tc.post(f"/api/archive/sessions/{a}/rename", json={"title": "t2c-search-me"})
    assert r.status_code == 200, r.text
    r = tc.get("/api/archive/sessions", params={"search": "t2c-search-me"})
    assert any(e["id"] == a for e in r.json())
    r = tc.get("/api/archive/sessions", params={"search": "no-match-xyz"})
    assert r.json() == []


def test_archive_detail_wire_and_guards(tc: TestClient) -> None:
    """Donor wire (main.py:4163-4180) + guards: 404 unknown, 400 not archived."""
    a, b = _archive_pair(tc)
    r = tc.get(f"/api/archive/sessions/{a}")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {
        "id",
        "title",
        "tag",
        "model",
        "root_session_id",
        "created_at",
        "updated_at",
    }
    assert d["model"] == "m-a"
    r = tc.get(f"/api/archive/sessions/{b}")
    assert r.status_code == 400
    assert "not archived" in r.json()["detail"]
    r = tc.get("/api/archive/sessions/t2c-ghost")
    assert r.status_code == 404


def test_archive_messages_wire(tc: TestClient) -> None:
    """Donor wire (main.py:4182-4186): get_replay(session_id) verbatim —
    the same bus read as /replay.
    """
    a, _ = _archive_pair(tc)
    r = tc.get(f"/api/archive/sessions/{a}/messages")
    assert r.status_code == 200
    evs = r.json()
    assert isinstance(evs, list)
    for e in evs:
        assert set(e) == {"seq", "type", "payload", "protocol_version", "created_at"}
    # identical to the /replay surface (same referent)
    assert evs == tc.get(f"/api/sessions/{a}/replay").json()


def test_archive_rename_and_tag(tc: TestClient) -> None:
    """Donor wire (main.py:4190-4206): {ok:true} on success, 404 on unknown
    (the vendor manager raises KeyError, caught exactly as in the donor).
    """
    a, _ = _archive_pair(tc)
    r = tc.post(f"/api/archive/sessions/{a}/rename", json={"title": "t2c-renamed"})
    assert r.json() == {"ok": True}
    assert tc.get(f"/api/sessions/{a}").json()["title"] == "t2c-renamed"

    r = tc.post(f"/api/archive/sessions/{a}/tag", json={"tag": "t2c-tag"})
    assert r.json() == {"ok": True}
    assert tc.get(f"/api/sessions/{a}").json()["tag"] == "t2c-tag"

    r = tc.post("/api/archive/sessions/t2c-ghost/rename", json={"title": "x"})
    assert r.status_code == 404
    r = tc.post("/api/archive/sessions/t2c-ghost/tag", json={"tag": "x"})
    assert r.status_code == 404


def test_archive_rename_422_missing_title(tc: TestClient) -> None:
    """Pydantic gate on the donor RenameRequest (title required)."""
    a, _ = _archive_pair(tc)
    r = tc.post(f"/api/archive/sessions/{a}/rename", json={})
    assert r.status_code == 422
