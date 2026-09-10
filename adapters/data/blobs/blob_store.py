"""BlobStore — content-addressed blob storage helper (ADR-096 D3).

Two-method sync helper for storing raw bytes keyed by SHA-256 hex.

Storage layout::

    <root>/<sha256[0:2]>/<sha256[2:]>

The 2-char shard prefix keeps any single directory under ~65 K files even
with millions of blobs.

Root is configurable via env ``KOSMOS_BLOB_ROOT``; defaults to
``adapters/data/blobs/store/`` relative to the repo root.

Not a formal Kosmos port. Not registered with a Protocol. Two consumers as
of Stage 6.5:

- ``adapters/voice/faster_whisper/adapter.py`` (audio bytes)
- ``adapters/vision/ollama_qwen_vl/adapter.py`` +
  ``adapters/vision/tesseract/adapter.py`` (image bytes)

If a third consumer or a swappable backend emerges, a formal ``BlobPort``
ADR is the correct next step (see ADR-096 §Rationale).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

__all__ = [
    "BlobStore",
    "kosmos_blob_uri",
    "sha256_of",
]


def sha256_of(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def kosmos_blob_uri(sha256_hex: str) -> str:
    """Return the canonical ``kosmos://blob/<sha256>`` URI (ADR-096 D2)."""
    if not isinstance(sha256_hex, str) or len(sha256_hex) != 64:
        raise ValueError(
            f"kosmos_blob_uri expects 64-char SHA-256 hex, got {sha256_hex!r}"
        )
    return f"kosmos://blob/{sha256_hex}"


def _default_root() -> Path:
    """Resolve the default blob-store root.

    Priority:
    1. Env ``KOSMOS_BLOB_ROOT`` if set.
    2. ``adapters/data/blobs/store/`` under this file's package parent.
    """
    env = os.environ.get("KOSMOS_BLOB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # This file lives at adapters/data/blobs/blob_store.py; store/ is a
    # sibling of this module.
    return Path(__file__).resolve().parent / "store"


class BlobStore:
    """Content-addressed blob storage (ADR-096 D3).

    Idempotent: writing the same bytes twice yields the same hex digest and
    a single file on disk (the second write is a no-op).

    Thread- and process-safe for concurrent ``put_bytes`` on the same
    content: writes go to a per-process temp file first, then rename to the
    final path (POSIX rename is atomic on the same filesystem). Concurrent
    writes of *different* content are naturally independent.
    """

    def __init__(self, *, root: Path | str | None = None) -> None:
        self._root = (
            Path(root).expanduser().resolve() if root is not None else _default_root()
        )
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, sha256_hex: str) -> Path:
        if len(sha256_hex) != 64:
            raise ValueError(
                f"BlobStore expects 64-char SHA-256 hex, got {sha256_hex!r}"
            )
        return self._root / sha256_hex[:2] / sha256_hex[2:]

    def put_bytes(self, data: bytes) -> str:
        """Store ``data``; return its SHA-256 hex digest.

        Idempotent: repeated calls with identical ``data`` return the same
        digest and do not rewrite the on-disk file.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(
                f"BlobStore.put_bytes expects bytes, got {type(data).__name__}"
            )
        digest = sha256_of(bytes(data))
        target = self._path_for(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp path in the same directory, then atomic rename.
        tmp = target.parent / f".{digest}.tmp.{os.getpid()}"
        tmp.write_bytes(bytes(data))
        try:
            os.replace(tmp, target)
        except OSError:
            # If another process won the race and target now exists,
            # discard our temp and treat as success.
            if target.exists():
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
            else:
                raise
        return digest

    def open_path(self, sha256_hex: str) -> Path:
        """Return the on-disk path for ``sha256_hex``.

        Raises ``FileNotFoundError`` if no such blob has been stored.
        """
        p = self._path_for(sha256_hex)
        if not p.exists():
            raise FileNotFoundError(f"No blob stored for {sha256_hex} at {p}")
        return p

    def has(self, sha256_hex: str) -> bool:
        """Return True iff a blob for ``sha256_hex`` exists on disk."""
        return self._path_for(sha256_hex).exists()
