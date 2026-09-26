"""ADR-141 Stage 13.5 — /api/observability/status.

One donor route (donor main.py:4673) — the donor just reports two
booleans: whether its private ``_telemetry_collector`` (long-running
daemon → ~/.tektos/telemetry) and ``_auto_recovery`` (service health
monitor) objects exist. Kernel referents:

- ``telemetry`` → the ADR-138 ON-DEMAND sampler (``kernel.tektos_telemetry``
  / ``GET /api/telemetry``). No running collector daemon in the kernel;
  the route reports whether the sampler module imports (wired referent).
- ``auto_recovery`` → ``registry.self_repair`` — the ADR-142 full donor
  self-repair engine (the auto-recovery supersession; boots
  unconditionally at lifespan per ADR-141 R6).

Wire: donor field set preserved verbatim + one additive ``note`` making
the daemon→kernel-mechanism mapping explicit (T1-orchestrator
honest-degrade pattern). 200 always.
"""
import os

import pytest

# env BEFORE kernel.app import (module-level, no re-import trickery).
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

import kernel.app as ka  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def env():
    with TestClient(ka.app) as client:
        yield {"client": client}


def test_observability_status_wire_shape(env):
    r = env["client"].get("/api/observability/status")
    assert r.status_code == 200
    body = r.json()
    # Donor field set verbatim + one additive `note`.
    assert set(body.keys()) == {
        "status",
        "telemetry",
        "auto_recovery",
        "note",
    }
    assert body["status"] == "active"
    assert isinstance(body["telemetry"], bool)
    assert isinstance(body["auto_recovery"], bool)
    assert isinstance(body["note"], str) and "kernel" in body["note"]


def test_observability_telemetry_reflects_sampler(env):
    """telemetry reports the kernel's ADR-138 sampler referent."""
    body = env["client"].get("/api/observability/status").json()
    try:
        from kernel.tektos_telemetry import collect  # noqa: F401

        expected = True
    except Exception:
        expected = False
    assert body["telemetry"] is expected
    assert body["telemetry"] is True  # sampler is a kernel module — wired


def test_observability_auto_recovery_reflects_registry(env):
    """auto_recovery mirrors registry.self_repair (ADR-142 engine)."""
    body = env["client"].get("/api/observability/status").json()
    assert body["auto_recovery"] is (ka.registry.self_repair is not None)
    # Engine boots unconditionally at lifespan (ADR-141 R6) → wired.
    assert body["auto_recovery"] is True
