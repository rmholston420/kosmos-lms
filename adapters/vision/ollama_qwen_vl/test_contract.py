"""Contract test — OllamaQwenVLVisionAdapter (ADR-098).

Uses monkey-patched httpx.AsyncClient — no real Ollama process required.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from adapters.vision import VisionAdapterUnavailable, VisionCapabilityUnsupported
from adapters.vision.ollama_qwen_vl import OllamaQwenVLVisionAdapter
from ports.vision import VisionDescription, VisionPort


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.fixture()
def adapter_with_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> OllamaQwenVLVisionAdapter:
    """An adapter whose AsyncClient uses an httpx MockTransport."""
    handler = getattr(request, "param", None)

    def default_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": ""})

    transport = _mock_transport(handler or default_handler)

    real_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    return OllamaQwenVLVisionAdapter(base_url="http://127.0.0.1:11434", model="qwen2.5-vl:7b")


def test_isinstance_vision_port(adapter_with_mock_transport: OllamaQwenVLVisionAdapter) -> None:
    assert isinstance(adapter_with_mock_transport, VisionPort)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_with_mock_transport",
    [lambda req: httpx.Response(200, json={"response": "A red bicycle leans against a stone wall."})],
    indirect=True,
)
async def test_describe_returns_well_formed_description(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    d = await adapter_with_mock_transport.describe(b"\x89PNG\x00\x00", mime="image/png")
    assert isinstance(d, VisionDescription)
    assert d.text == "A red bicycle leans against a stone wall."
    assert d.model == "qwen2.5-vl:7b"
    assert 0.0 <= d.confidence <= 1.0


@pytest.mark.asyncio
async def test_extract_text_raises_vision_capability_unsupported(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    with pytest.raises(VisionCapabilityUnsupported) as exc:
        await adapter_with_mock_transport.extract_text(b"\x89PNG", mime="image/png")
    assert "ADR-098" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_with_mock_transport",
    [
        lambda req: httpx.Response(
            200,
            json={
                "response": json.dumps(
                    [
                        {"category": "cat", "bbox": [10, 20, 30, 40], "confidence": 0.9},
                        {"category": "dog", "bbox": [50, 60, 70, 80], "confidence": 0.7},
                    ]
                )
            },
        )
    ],
    indirect=True,
)
async def test_detect_parses_json_list(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    dets = await adapter_with_mock_transport.detect(b"\x89PNG", mime="image/png")
    assert len(dets) == 2
    cat, dog = dets
    assert cat.category == "cat"
    assert cat.bbox == (10, 20, 30, 40)
    assert cat.confidence == pytest.approx(0.9)
    assert dog.category == "dog"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_with_mock_transport",
    [
        lambda req: httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {"detections": [{"category": "car", "bbox": [1, 2, 3, 4]}]}
                )
            },
        )
    ],
    indirect=True,
)
async def test_detect_parses_json_dict_with_detections_key(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    dets = await adapter_with_mock_transport.detect(b"\x89PNG", mime="image/png")
    assert len(dets) == 1
    assert dets[0].category == "car"
    assert dets[0].confidence == pytest.approx(0.5)  # default when omitted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_with_mock_transport",
    [lambda req: httpx.Response(200, json={"response": "not-json-at-all"})],
    indirect=True,
)
async def test_detect_returns_empty_on_malformed_json(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    dets = await adapter_with_mock_transport.detect(b"\x89PNG", mime="image/png")
    assert dets == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_with_mock_transport",
    [lambda req: httpx.Response(503, text="Service Unavailable")],
    indirect=True,
)
async def test_describe_raises_when_ollama_errors(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    with pytest.raises(VisionAdapterUnavailable):
        await adapter_with_mock_transport.describe(b"\x89PNG", mime="image/png")


@pytest.mark.asyncio
async def test_describe_rejects_empty_bytes(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    with pytest.raises(ValueError):
        await adapter_with_mock_transport.describe(b"", mime="image/png")


@pytest.mark.asyncio
async def test_close_makes_calls_raise(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    await adapter_with_mock_transport.close()
    with pytest.raises(VisionAdapterUnavailable):
        await adapter_with_mock_transport.describe(b"\x89PNG", mime="image/png")


@pytest.mark.asyncio
async def test_close_idempotent(
    adapter_with_mock_transport: OllamaQwenVLVisionAdapter,
) -> None:
    await adapter_with_mock_transport.close()
    await adapter_with_mock_transport.close()  # must not raise


def test_is_healthy_false_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Ollama listening → is_healthy() returns False, does not raise."""
    a = OllamaQwenVLVisionAdapter(base_url="http://127.0.0.1:59999", model="qwen2.5-vl:7b")
    assert a.is_healthy() is False
