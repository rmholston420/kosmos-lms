"""ADR-141 Stage 13.12 — voice ×3: donor VoiceManager → kernel substrate.

Donor `tektos/voice.py` (310 LOC, all third-party deps lazy — edge-tts,
faster-whisper, pydub, numpy — zero `tektos.*` imports; the "tektos"
strings are the logger name, wake word, and error messages, kept
verbatim) → `kernel/voice.py` byte-verbatim (generic STT/TTS/VAD/wake-word
orchestration → kernel per the governing layering rule). Booted at the
composition root (`registry.tektos_voice`) with the donor's non-fatal
`await initialize()` semantics (main.py:899-910: failure → slot None →
routes in their "not initialized" state) + a kernel-side
`KOSMOS_TEKTOS_VOICE` gate (default on).

Donor routes main.py:2229-2301, wire-verbatim:
  GET  /api/voice/state   (200 {"error": ...} when slot None — NOT 503)
  POST /api/voice/stt     (multipart 'audio' → {"text", "wake_word_detected"};
                           503 pair when slot None)
  POST /api/voice/tts     (JSON {"text"} → audio/mpeg MP3 stream;
                           503 pair when slot None)

These tests run the REAL substrate: Whisper (Systran/faster-whisper-base,
already cached in ~/.cache/huggingface — the donor's TEKTOS_WHISPER_MODEL
env, set here to the small cached model for test speed) transcribing a
real generated WAV, and edge-tts (real Microsoft neural voice over the
network) synthesizing a real MP3. No mocks.
"""

from __future__ import annotations

import io
import struct
import wave

import kernel.app as ka
from fastapi.testclient import TestClient
import pytest

# TEKTOS_WHISPER_MODEL is the donor substrate's own env knob (voice.py:77).
# base (cached, ~74 MB int8) keeps the STT test fast; the boot code path
# (initialize → WhisperModel(...)) is identical for any model name.
import os

os.environ["TEKTOS_WHISPER_MODEL"] = "base"


def _silence_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    """Real 16-bit PCM mono WAV of pure silence (stdlib only)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * int(rate * seconds), *([0] * int(rate * seconds))))
    return buf.getvalue()


def _wait_whisper(manager, deadline: float = 240.0):
    """Wait for the boot task's `await manager.initialize()` to finish
    loading the Whisper model (real CPU load — base, cached)."""
    import time

    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if manager is None:
            raise AssertionError("voice slot nulled — initialize failed (non-fatal path)")
        if manager.stt._model is not None:
            return manager
        time.sleep(0.5)
    raise AssertionError("Whisper model did not load in time")


def test_voice_state_envelope(client):
    """GET /api/voice/state → donor get_state() envelope (5 fields)."""
    _wait_whisper(ka.registry.tektos_voice)
    r = client[0].get("/api/voice/state")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "is_listening": False,
        "is_speaking": False,
        "is_wake_word_detected": False,
        "last_transcript": "",
        "last_tts_text": "",
    }


def test_voice_stt_real_whisper(client):
    """POST /api/voice/stt → REAL Whisper transcription of a real
    generated silence WAV through the full pydub → faster-whisper path."""
    _wait_whisper(ka.registry.tektos_voice)
    audio = _silence_wav(1.0)
    r = client[0].post(
        "/api/voice/stt",
        files={"audio": ("test.wav", audio, "audio/wav")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "text" in body
    assert body["wake_word_detected"] is False
    # state side-effect: transcript recorded (silence → empty or near-empty)
    s = client[0].get("/api/voice/state").json()
    assert s["last_transcript"] == body["text"]


def test_voice_tts_real_edge(client):
    """POST /api/voice/tts → REAL edge-tts (Microsoft neural voice, real
    network) → audio/mpeg MP3 stream with the donor's attachment header."""
    _wait_whisper(ka.registry.tektos_voice)
    r = client[0].post("/api/voice/tts", json={"text": "Hello from the kernel voice."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.headers["content-disposition"] == "attachment; filename=tektos_speech.mp3"
    body = r.content
    assert len(body) > 1000  # a real MP3, not an empty stream
    assert body[:3] == b"ID3" or body[:2] == b"\xff\xfb" or body[:2] == b"\xff\xf3"
    # state side-effect: the spoken text is recorded
    s = client[0].get("/api/voice/state").json()
    assert s["last_tts_text"] == "Hello from the kernel voice."


def test_voice_gate_off_surfaces(client, monkeypatch):
    """Slot None (gate off / initialize failed) → donor-verbatim
    surfaces: state → 200 {"error": ...} (NOT 503), stt/tts → 503 pair."""
    monkeypatch.setattr(ka.registry, "tektos_voice", None)
    r = client[0].get("/api/voice/state")
    assert r.status_code == 200
    assert r.json() == {"error": "Voice system not initialized"}
    r = client[0].post(
        "/api/voice/stt",
        files={"audio": ("t.wav", _silence_wav(0.2), "audio/wav")},
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "Voice system not initialized"
    r = client[0].post("/api/voice/tts", json={"text": "hi"})
    assert r.status_code == 503
    assert r.json()["detail"] == "Voice system not initialized"


@pytest.fixture(scope="module")
def client():
    """Full kernel lifespan; the boot task runs the donor's non-fatal
    `await manager.initialize()` (real Whisper load) for the module."""
    with TestClient(ka.app) as tc:
        yield tc, None
