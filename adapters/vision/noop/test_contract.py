"""Contract test — NoOpVisionAdapter (ADR-098)."""

from __future__ import annotations

import pytest

from adapters.vision import VisionAdapterUnavailable
from adapters.vision.noop import NoOpVisionAdapter
from ports.vision import OCRResult, VisionDescription, VisionPort


def test_isinstance_vision_port() -> None:
    assert isinstance(NoOpVisionAdapter(), VisionPort)


@pytest.mark.asyncio
async def test_describe_returns_empty() -> None:
    d = await NoOpVisionAdapter().describe(b"\x89PNG", mime="image/png")
    assert isinstance(d, VisionDescription)
    assert d.text == ""
    assert d.confidence == 0.0
    assert d.model == "noop"


@pytest.mark.asyncio
async def test_extract_text_returns_empty() -> None:
    r = await NoOpVisionAdapter().extract_text(b"\x89PNG", mime="image/png")
    assert isinstance(r, OCRResult)
    assert r.text == ""
    assert r.blocks == ()
    assert r.confidence == 0.0


@pytest.mark.asyncio
async def test_detect_returns_empty_tuple() -> None:
    dets = await NoOpVisionAdapter().detect(b"\x89PNG", mime="image/png")
    assert dets == ()


def test_is_healthy_true_by_default() -> None:
    assert NoOpVisionAdapter().is_healthy() is True


@pytest.mark.asyncio
async def test_close_makes_unhealthy_and_calls_raise() -> None:
    a = NoOpVisionAdapter()
    await a.close()
    assert a.is_healthy() is False
    with pytest.raises(VisionAdapterUnavailable):
        await a.describe(b"", mime="image/png")


@pytest.mark.asyncio
async def test_close_idempotent() -> None:
    a = NoOpVisionAdapter()
    await a.close()
    await a.close()
    assert a.is_healthy() is False
