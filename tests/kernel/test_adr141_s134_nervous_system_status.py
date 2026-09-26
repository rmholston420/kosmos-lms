"""ADR-141 Stage 13.4 — /api/nervous-system/status.

One donor route (donor main.py:4725) over two EXISTING kernel referents —
no new substrate. The donor's "nervous system" = event bus + session state
machine; the kernel already owns both:

- ``registry.event_bus`` (boot slot, kernel/app.py:589), and
- the vendored FSM at ``adapters/session/tektos/vendor/state_machine.py``
  (donor ``tektos/state_machine.py`` copied verbatim into the session
  adapter; same ``_states`` / ``_transitions_completed`` surface;
  ``State`` is a ``str, Enum`` so ``dict(sm._states)`` serializes to
  state-name strings, donor-identical on the wire).

Wire lock (donor-verbatim, 200 always):
  {"status": "active", "event_bus": bool, "state_machine": bool,
   "total_sessions": <transitions_completed>, "states": {sid: state-name}}

The vendor FSM is a process-global singleton (donor design preserved), so
transition counts accumulate across tests in the same process — tests
assert SHAPE and monotonicity, not absolute zero.
"""
import os

import pytest

# env BEFORE kernel.app import (module-level, no re-import trickery).
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import kernel.app as ka  # noqa: E402
from adapters.session.tektos.vendor.state_machine import (  # noqa: E402
    State,
    get_state_machine,
)
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def env():
    with TestClient(ka.app) as client:
        yield {"client": client}


def _wire(r):
    return set(r.json().keys())


def test_nervous_system_status_wire_shape(env):
    r = env["client"].get("/api/nervous-system/status")
    assert r.status_code == 200
    body = r.json()
    assert _wire(r) == {
        "status",
        "event_bus",
        "state_machine",
        "total_sessions",
        "states",
    }
    # Donor returns unconditional "active" (a status surface, not a
    # wiring report — matches the donor, not the T1 orchestrator deviation).
    assert body["status"] == "active"
    assert isinstance(body["event_bus"], bool)
    assert isinstance(body["state_machine"], bool)
    assert isinstance(body["total_sessions"], int)
    assert isinstance(body["states"], dict)
    # states values are state-NAME strings (str-Enum serialized), not
    # enum reprs.
    for v in body["states"].values():
        assert isinstance(v, str)


def test_nervous_system_event_bus_reflects_registry(env):
    body = env["client"].get("/api/nervous-system/status").json()
    assert body["event_bus"] is (ka.registry.event_bus is not None)
    assert body["state_machine"] is True  # singleton always exists (donor)


def test_nervous_system_transition_visible(env):
    """A real FSM transition shows up in total_sessions + states (live)."""
    sm = get_state_machine()
    before = env["client"].get("/api/nervous-system/status").json()
    sid = "s134-test-session"
    sm.transition(sid, State.READY, "session created")
    sm.transition(sid, State.RUNNING, "processing prompt")
    after = env["client"].get("/api/nervous-system/status").json()
    assert after["total_sessions"] == before["total_sessions"] + 2
    assert after["states"][sid] == "running"
    assert before["states"].get(sid, "created") in ("created", "ready")
