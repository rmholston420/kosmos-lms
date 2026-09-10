"""adapters.voice — VoicePort adapters (ADR-097).

Errors:

- ``VoiceAdapterUnavailable`` — adapter cannot serve calls (vendor dep
  missing, model not loaded, or the adapter has been closed).
- ``TTSNotConfigured`` — TTS engine selection was deliberately deferred at
  Stage 6.5 (Piper GPL-blocked, Coqui MPL-fork evaluation pending). Callers
  needing synthesis MUST route through ``NoOpVoiceAdapter`` for CI or wait
  for the Stage 6.5+1 TTS-engine ADR (ADR-097 D3).
"""

from __future__ import annotations

__all__ = [
    "TTSNotConfigured",
    "VoiceAdapterUnavailable",
]


class VoiceAdapterUnavailable(RuntimeError):
    """A VoicePort adapter cannot serve calls (dep missing, closed, etc.)."""


class TTSNotConfigured(NotImplementedError):
    """TTS engine deliberately unselected at Stage 6.5 (ADR-097 D3)."""
