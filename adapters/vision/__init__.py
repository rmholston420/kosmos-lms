"""adapters.vision — VisionPort adapters (ADR-098).

Errors:

- ``VisionAdapterUnavailable`` — adapter cannot serve (Ollama unreachable,
  tesseract binary missing, dep missing, or closed).
- ``VisionCapabilityUnsupported`` — this adapter does not implement this
  verb by design (see ADR-098 D2 — split adapters, not composite).
"""

from __future__ import annotations

__all__ = [
    "VisionAdapterUnavailable",
    "VisionCapabilityUnsupported",
]


class VisionAdapterUnavailable(RuntimeError):
    """A VisionPort adapter cannot serve calls."""


class VisionCapabilityUnsupported(NotImplementedError):
    """This adapter does not implement this verb by design (ADR-098 D2)."""
