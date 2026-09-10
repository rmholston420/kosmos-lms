"""Contract test — TesseractVisionAdapter (ADR-098).

Stubs pytesseract + PIL so no real tesseract binary is required.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from adapters.vision import VisionCapabilityUnsupported
from adapters.vision.tesseract import TesseractVisionAdapter
from ports.vision import OCRResult, VisionPort


def _install_stubs(monkeypatch: pytest.MonkeyPatch, image_to_data: dict[str, list[Any]]) -> None:
    """Install fake pytesseract + PIL modules."""
    pyt = types.ModuleType("pytesseract")

    class _Output:
        DICT = "dict"

    class _Nested:
        tesseract_cmd = "tesseract"

    def _image_to_data(img: Any, output_type: Any = None) -> dict[str, list[Any]]:
        return image_to_data

    def _get_version() -> str:
        return "5.3.0"

    pyt.Output = _Output  # type: ignore[attr-defined]
    pyt.pytesseract = _Nested()  # type: ignore[attr-defined]
    pyt.image_to_data = _image_to_data  # type: ignore[attr-defined]
    pyt.get_tesseract_version = _get_version  # type: ignore[attr-defined]

    pil = types.ModuleType("PIL")
    pil_image = types.ModuleType("PIL.Image")

    class _Img:
        def __enter__(self) -> "_Img":
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def load(self) -> None:
            return None

    def _open(_fp: Any) -> _Img:
        return _Img()

    pil_image.open = _open  # type: ignore[attr-defined]
    pil.Image = pil_image  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pytesseract", pyt)
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image)


def test_isinstance_vision_port() -> None:
    assert isinstance(TesseractVisionAdapter(), VisionPort)


@pytest.mark.asyncio
async def test_describe_raises_capability_unsupported() -> None:
    with pytest.raises(VisionCapabilityUnsupported) as exc:
        await TesseractVisionAdapter().describe(b"\x89PNG", mime="image/png")
    assert "ADR-098" in str(exc.value)


@pytest.mark.asyncio
async def test_detect_raises_capability_unsupported() -> None:
    with pytest.raises(VisionCapabilityUnsupported):
        await TesseractVisionAdapter().detect(b"\x89PNG", mime="image/png")


@pytest.mark.asyncio
async def test_extract_text_parses_pytesseract_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(
        monkeypatch,
        image_to_data={
            "text": ["Hello", "World", "", "Skip"],
            "conf": ["95", "80", "-1", "-1"],
            "left": [10, 100, 0, 0],
            "top": [20, 20, 0, 0],
            "width": [50, 60, 0, 0],
            "height": [15, 15, 0, 0],
        },
    )
    a = TesseractVisionAdapter()
    r = await a.extract_text(b"\x89PNG\x00\x00", mime="image/png")
    assert isinstance(r, OCRResult)
    # Two valid blocks: "Hello" @ conf 0.95, "World" @ 0.80.  Others skipped.
    assert r.text == "Hello World"
    assert len(r.blocks) == 2
    assert r.blocks[0].text == "Hello"
    assert r.blocks[0].bbox == (10, 20, 50, 15)
    assert r.blocks[0].confidence == pytest.approx(0.95)
    assert r.blocks[1].confidence == pytest.approx(0.80)
    # Mean of 0.95, 0.80 = 0.875
    assert r.confidence == pytest.approx(0.875)


@pytest.mark.asyncio
async def test_extract_text_empty_all_conf_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(
        monkeypatch,
        image_to_data={
            "text": ["", "", ""],
            "conf": ["-1", "-1", "-1"],
            "left": [0, 0, 0],
            "top": [0, 0, 0],
            "width": [0, 0, 0],
            "height": [0, 0, 0],
        },
    )
    a = TesseractVisionAdapter()
    r = await a.extract_text(b"\x89PNG", mime="image/png")
    assert r.text == ""
    assert r.blocks == ()
    assert r.confidence == 0.0


@pytest.mark.asyncio
async def test_extract_text_rejects_empty_bytes() -> None:
    with pytest.raises(ValueError):
        await TesseractVisionAdapter().extract_text(b"", mime="image/png")


def test_is_healthy_true_when_stubs_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(
        monkeypatch,
        image_to_data={"text": [], "conf": [], "left": [], "top": [], "width": [], "height": []},
    )
    assert TesseractVisionAdapter().is_healthy() is True


def test_is_healthy_false_when_pytesseract_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    assert TesseractVisionAdapter().is_healthy() is False


@pytest.mark.asyncio
async def test_close_makes_calls_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(
        monkeypatch,
        image_to_data={"text": [], "conf": [], "left": [], "top": [], "width": [], "height": []},
    )
    from adapters.vision import VisionAdapterUnavailable
    a = TesseractVisionAdapter()
    await a.close()
    with pytest.raises(VisionAdapterUnavailable):
        await a.extract_text(b"\x89PNG", mime="image/png")
