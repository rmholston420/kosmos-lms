"""Stage 11.13 — ADR-129 kernel log ring: /api/logs.

The ops Logs tab previously proxied ``:8020/api/logs`` — the
*standalone* Tektos engine's records (``tektos.thermal.*``,
``tektos.self_repair.*``). The kernel's referent is the kernel's OWN
records: a bounded, thread-safe ``logging.Handler`` ring on the process
root logger, exposed as ``GET /api/logs``.

Tests run GPU-free: no network, no Postgres.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import kernel.app as kapp
from kernel.app import app


@pytest.fixture(autouse=True)
def _isolated_ring(monkeypatch: pytest.MonkeyPatch):
    """Give each test a fresh empty ring on the root logger; restore after.

    Records flow through the handler *installed on the root logger*
    (propagation), so both the root handler and the ``kapp._log_ring``
    global (what the endpoint reads) are swapped together.
    """
    installed = kapp._log_ring
    assert installed is not None
    fresh = kapp._KosmosLogRing()
    root = logging.getLogger()
    root.removeHandler(installed)
    root.addHandler(fresh)
    monkeypatch.setattr(kapp, "_log_ring", fresh)
    yield
    root.removeHandler(fresh)
    root.addHandler(installed)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _emit(logger_name: str, level: int, msg: str) -> None:
    logging.getLogger(logger_name).log(level, msg)


# ── Shape + determinism ───────────────────────────────────────────────────


def test_logs_shape_empty(client: TestClient) -> None:
    r = client.get("/api/logs")
    assert r.status_code == 200
    o = r.json()
    assert o["logs"] == []
    assert o["count"] == 0
    assert o["max_records"] == kapp._LOG_RING_MAX
    assert o["level_histogram"] == {}
    assert "timestamp" in o


def test_logs_records_captured_and_oldest_first(client: TestClient) -> None:
    _emit("kernel.app", logging.INFO, "first record")
    _emit("kernel.app", logging.ERROR, "second record")
    o = client.get("/api/logs").json()
    assert o["count"] == 2
    # oldest-first: display order matches emission order
    assert [e["message"] for e in o["logs"]] == ["first record", "second record"]
    # :8020-compatible element schema
    assert set(o["logs"][0].keys()) == {"timestamp", "level", "logger", "message"}
    assert o["logs"][1]["level"] == "ERROR"
    assert o["logs"][1]["logger"] == "kernel.app"
    assert o["level_histogram"] == {"INFO": 1, "ERROR": 1}


# ── Ring behaviour ────────────────────────────────────────────────────────


def test_ring_drops_debug_and_library_noise() -> None:
    ring = kapp._log_ring
    assert ring is not None
    _emit("kernel.app", logging.DEBUG, "debug (dropped)")
    _emit("uvicorn.access", logging.INFO, "access log (dropped)")
    _emit("uvicorn", logging.INFO, "uvicorn root (dropped)")
    _emit("httpx", logging.INFO, "httpx (dropped)")
    _emit("httpcore.connection", logging.INFO, "httpcore (dropped)")
    _emit("kernel.app", logging.WARNING, "kept warning")
    assert len(ring) == 1
    assert ring.snapshot()[0]["message"] == "kept warning"


def test_ring_is_bounded() -> None:
    ring = kapp._KosmosLogRing(maxlen=5)
    for i in range(12):
        ring.emit(logging.LogRecord("kernel.test", logging.INFO, "t", 1, f"rec-{i}", None, None))
    assert len(ring) == 5
    # oldest evicted — the LAST 5 remain, oldest-first
    assert [e["message"] for e in ring.snapshot()] == ["rec-7", "rec-8", "rec-9", "rec-10", "rec-11"]


def test_redact_dsn_masks_password_only() -> None:
    assert (
        kapp._redact_dsn("postgresql://kosmos:secret123@127.0.0.1:5432/kosmos")
        == "postgresql://kosmos:***@127.0.0.1:5432/kosmos"
    )
    # no user:pass segment → untouched (host:port colon must not be eaten)
    assert kapp._redact_dsn("no-creds://host:5432/db") == "no-creds://host:5432/db"
    assert kapp._redact_dsn("sqlite:///path.db") == "sqlite:///path.db"


# ── Handler wiring ────────────────────────────────────────────────────────


def test_install_is_idempotent() -> None:
    before = len(logging.getLogger().handlers)
    a = kapp._install_log_ring()
    b = kapp._install_log_ring()
    after = len(logging.getLogger().handlers)
    assert a is b
    assert after == before  # no double-attach


def test_emit_is_thread_safe() -> None:
    import threading

    ring = kapp._KosmosLogRing(maxlen=10_000)
    root = logging.getLogger()
    root.addHandler(ring)
    try:
        threads = [
            threading.Thread(
                target=lambda i: [
                    ring.emit(
                        logging.LogRecord("kernel.t", logging.INFO, "t", 1, f"{i}-{j}", None, None)
                    )
                    for j in range(50)
                ],
                args=(ti,),
            )
            for ti in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        root.removeHandler(ring)
    assert len(ring) == 400
    assert len(ring.snapshot()) == 400
