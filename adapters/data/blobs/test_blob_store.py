"""Contract test for adapters/data/blobs/BlobStore (ADR-096 D3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from adapters.data.blobs import BlobStore, kosmos_blob_uri, sha256_of


def test_sha256_of_matches_stdlib() -> None:
    data = b"hello kosmos"
    assert sha256_of(data) == hashlib.sha256(data).hexdigest()


def test_kosmos_blob_uri_valid() -> None:
    digest = sha256_of(b"x")
    assert kosmos_blob_uri(digest) == f"kosmos://blob/{digest}"


def test_kosmos_blob_uri_rejects_short() -> None:
    with pytest.raises(ValueError):
        kosmos_blob_uri("deadbeef")


def test_put_bytes_returns_digest_and_writes_file(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    data = b"stage 6.5 voice + vision"
    digest = store.put_bytes(data)
    assert digest == sha256_of(data)
    on_disk = store.open_path(digest)
    assert on_disk.exists()
    assert on_disk.read_bytes() == data


def test_put_bytes_idempotent(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    data = b"repeat"
    d1 = store.put_bytes(data)
    mtime1 = store.open_path(d1).stat().st_mtime_ns
    d2 = store.put_bytes(data)
    mtime2 = store.open_path(d2).stat().st_mtime_ns
    assert d1 == d2
    assert mtime1 == mtime2, "second put_bytes must not rewrite existing blob"


def test_put_bytes_different_content_distinct_files(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    d1 = store.put_bytes(b"a")
    d2 = store.put_bytes(b"b")
    assert d1 != d2
    assert store.open_path(d1).read_bytes() == b"a"
    assert store.open_path(d2).read_bytes() == b"b"


def test_shard_layout(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    digest = store.put_bytes(b"shard me")
    p = store.open_path(digest)
    # <root>/<sha[0:2]>/<sha[2:]>
    assert p.parent.name == digest[:2]
    assert p.name == digest[2:]
    assert p.parent.parent == tmp_path


def test_open_path_missing_raises(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.open_path("0" * 64)


def test_has(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    digest = store.put_bytes(b"present")
    assert store.has(digest)
    assert not store.has("0" * 64)


def test_put_bytes_type_check(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    with pytest.raises(TypeError):
        store.put_bytes("not-bytes")  # type: ignore[arg-type]


def test_put_bytes_accepts_bytearray(tmp_path: Path) -> None:
    store = BlobStore(root=tmp_path)
    data = bytearray(b"mutable")
    digest = store.put_bytes(data)
    assert digest == sha256_of(bytes(data))


def test_env_var_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOSMOS_BLOB_ROOT", str(tmp_path / "custom"))
    store = BlobStore()
    assert store.root == (tmp_path / "custom").resolve()
    digest = store.put_bytes(b"env-driven")
    assert (store.root / digest[:2] / digest[2:]).exists()


def test_root_kwarg_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOSMOS_BLOB_ROOT", str(tmp_path / "env"))
    store = BlobStore(root=tmp_path / "kwarg")
    assert store.root == (tmp_path / "kwarg").resolve()
