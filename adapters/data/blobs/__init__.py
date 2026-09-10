"""adapters.data.blobs — content-addressed blob storage (ADR-096 D3).

Kosmos-native two-method helper for storing raw bytes keyed by their SHA-256
hex hash. Used by the Stage 6.5 voice + vision adapters to keep image / audio
bytes out of MemoryPort.

NOT a formal Kosmos port — see ADR-096 §Rationale for why a helper is the
right shape here.
"""

from adapters.data.blobs.blob_store import (
    BlobStore,
    kosmos_blob_uri,
    sha256_of,
)

__all__ = [
    "BlobStore",
    "kosmos_blob_uri",
    "sha256_of",
]
