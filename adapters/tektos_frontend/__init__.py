"""adapters.tektos_frontend — shared helpers for user-driven UI ingest.

Provides the two-write pattern (ADR-096 D1) that both VoicePort and
VisionPort adapters use when writing to MemoryPort on behalf of a
user-initiated frontend action.
"""

from adapters.tektos_frontend.frontend_memory_writer import (
    TektosFrontendMemoryWriter,
    VoiceIngest,
    VisionIngest,
)

__all__ = [
    "TektosFrontendMemoryWriter",
    "VoiceIngest",
    "VisionIngest",
]
