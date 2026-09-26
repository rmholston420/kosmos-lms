"""ADR-141 Stage 13.11 — vision ×3: donor VisionClient → kernel substrate.

Donor `tektos/providers/vision_client.py` (239 LOC, stdlib + httpx, zero
`tektos.*` imports — the only "tektos" string is the logger name, kept
verbatim) → `kernel/vision_client.py` byte-verbatim (generic OpenAI-
compatible vision transport → kernel per the governing layering rule).
Booted from the ADR-132 vision-lane env pair (`KOSMOS_VISION_BASE_URL`
/:8094, `KOSMOS_VISION_MODEL`/qwen3-vl-4b — the same vars /api/models
reports) with the donor's /v1-suffix normalization and failure→None
boot semantics (main.py:920-945).

Donor routes main.py:4219-4352, wire-verbatim:
  POST /api/vision/analyze      (base64 image → description envelope)
  POST /api/vision/analyze-url  (URL → same envelope)
  GET  /api/vision/status       (ok/initialized/healthy/model/base_url;
                                 503 pair when the slot is None)

These tests stand up a REAL local OpenAI-compatible vision server
(stdlib http.server, real sockets — no mocks) and point
KOSMOS_VISION_BASE_URL at it, so the full httpx substrate (health probe,
image data-URL payload, response parsing, temp-file cleanup) runs for
real, deterministically, with no GPU dependency.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import kernel.app as ka
from fastapi.testclient import TestClient
import pytest

# Smallest valid 1x1 red PNG (stdlib-decodable, real pixels).
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="
)

_CANNED_COMPLETION = {
    "id": "cmpl-test",
    "model": "test-vl",
    "choices": [{"message": {"role": "assistant", "content": "A red square."}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    "timings": {"total_ms": 1},
}


class _Handler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible vision server (real HTTP)."""

    last_completions: dict | None = None

    def log_message(self, format: str, *args: object) -> None:  # silence
        pass

    def do_GET(self):
        if self.path == "/v1/health" or self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/img.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(_PNG)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            _Handler.last_completions = req
            body = json.dumps(_CANNED_COMPLETION).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def client():
    """Full kernel lifespan with the vision lane pointed at a real local
    OpenAI-compatible server (deterministic; no GPU dependency)."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    saved = {v: os.environ.get(v) for v in ("KOSMOS_VISION_BASE_URL", "KOSMOS_VISION_MODEL")}
    os.environ["KOSMOS_VISION_BASE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["KOSMOS_VISION_MODEL"] = "test-vl"
    try:
        with TestClient(ka.app) as tc:
            yield tc, port
    finally:
        for v, old in saved.items():
            if old is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = old
        server.shutdown()


def _wait_booted(vision, deadline: float = 20.0):
    import time

    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if vision is None:
            raise AssertionError("vision slot nulled — boot probe failed")
        if vision._client is not None:
            return vision
        time.sleep(0.2)
    raise AssertionError("vision boot probe did not complete in time")


def test_vision_status_initialized(client):
    """GET /api/vision/status → donor envelope (initialized/healthy)."""
    vision = _wait_booted(ka.registry.tektos_vision)
    r = client[0].get("/api/vision/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["initialized"] is True
    assert body["healthy"] is True
    assert body["model"] == "test-vl"
    assert body["base_url"].endswith("/v1")


def test_vision_analyze_base64_roundtrip(client):
    """POST /api/vision/analyze → real substrate round-trip: base64 PNG →
    temp file → data-URL payload → canned completion → donor envelope."""
    vision = _wait_booted(ka.registry.tektos_vision)
    b64 = base64.b64encode(_PNG).decode()
    r = client[0].post(
        "/api/vision/analyze",
        json={"session_id": "s1", "image_base64": b64, "prompt": "What color?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["session_id"] == "s1"
    assert body["text"] == "A red square."
    assert body["model"] == "test-vl"
    assert body["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    # the substrate sent a real image data-URL payload
    assert _Handler.last_completions is not None
    req = _Handler.last_completions
    assert req["model"] == "test-vl"
    content = req["messages"][-1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_analyze_url_roundtrip(client):
    """POST /api/vision/analyze-url → real HTTP fetch of the image → same
    donor envelope."""
    _wait_booted(ka.registry.tektos_vision)
    _, port = client
    r = client[0].post(
        "/api/vision/analyze-url",
        json={"session_id": "s2", "image_url": f"http://127.0.0.1:{port}/img.png"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["session_id"] == "s2"
    assert body["text"] == "A red square."


def test_vision_gate_off_503_pair(client, monkeypatch):
    """Slot None (gate off / probe failed) → donor-verbatim 503 on both
    analyze routes, not-initialized envelope on status at 200."""
    monkeypatch.setattr(ka.registry, "tektos_vision", None)
    r = client[0].post(
        "/api/vision/analyze",
        json={"session_id": "s3", "image_base64": "AAAA"},
    )
    assert r.status_code == 503
    assert "Vision client not initialized" in r.json()["detail"]
    r = client[0].post(
        "/api/vision/analyze-url", json={"session_id": "s3", "image_url": "http://x/i.png"}
    )
    assert r.status_code == 503
    r = client[0].get("/api/vision/status")
    assert r.status_code == 200
    assert r.json()["initialized"] is False
    assert r.json()["ok"] is False
