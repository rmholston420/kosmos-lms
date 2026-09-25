"""adapters.vector.qdrant.real_backend — RealQdrantBackend (ADR-026 / ADR-074 D2).

Wraps ``qdrant_client.AsyncQdrantClient`` behind the
:class:`~adapters.vector.qdrant.adapter.QdrantBackend` Protocol so
:class:`QdrantVectorAdapter` can talk to a live Qdrant server (default
``http://127.0.0.1:6333`` on Colossus).

Design invariants
-----------------

1. **Lazy import.** ``qdrant_client`` is imported inside ``__init__`` so
   the wider module tree stays importable in environments that only
   want the in-memory backend (contract tests, CI without Docker).

2. **Cosine distance.** Every kernel-owned memory collection is created
   with ``Distance.COSINE`` so nearest-neighbour scores are consistent
   with the embedding model (``nomic-embed-text`` is L2-normalized by
   Ollama's ``/api/embed`` endpoint).

3. **Deterministic point ids.** The adapter passes stringified UUIDs
   through ``_to_point_id``; those become Qdrant point-ids directly.

4. **Idempotent snapshot handle.** Qdrant's snapshot response contains
   ``name``/``creation_time``/``location`` — we map those into the
   port's :class:`SnapshotHandle` shape.

5. **Sync ``is_healthy``.** Qdrant's health check is a plain HTTP GET on
   ``/healthz`` (urllib, no event loop — ADR-124 D6; a loop-spawning
   async-client probe broke once the shared client bound to the kernel's
   main loop). On error return ``False`` (ADR-023 rule 5).

References:
    - ADR-026 (VectorPort — the port this backend serves)
    - ADR-074 §D2 (kernel wiring)
    - Qdrant Python client:
      https://python-client.qdrant.tech/qdrant_client.async_qdrant_client
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ports.vector import SnapshotHandle, VectorHit

__all__ = ["RealQdrantBackend"]


log = logging.getLogger(__name__)


class RealQdrantBackend:
    """QdrantBackend backed by ``qdrant_client.AsyncQdrantClient``.

    Parameters
    ----------
    url:
        Full HTTP URL (e.g. ``http://127.0.0.1:6333``). Passed directly
        to ``AsyncQdrantClient(url=...)``.
    api_key:
        Optional Qdrant Cloud API key. Kosmos is local-first so this is
        usually ``None`` on Colossus.
    """

    def __init__(
        self,
        *,
        url: str = "http://127.0.0.1:6333",
        api_key: str | None = None,
    ) -> None:
        # Lazy import so contract tests don't need qdrant-client installed.
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.http import models as rest_models

        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._rest = rest_models
        self._url = url
        self._api_key = api_key
        self._closed = False
        self._known_collections: set[str] = set()

    async def ensure_collection(self, name: str, *, dim: int) -> None:
        """Idempotent create-if-absent for ``name`` at cosine dim ``dim``."""
        if name in self._known_collections:
            return
        try:
            exists = await self._client.collection_exists(name)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "RealQdrantBackend: collection_exists(%s) raised: %s",
                name,
                exc,
            )
            raise
        if not exists:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=self._rest.VectorParams(
                    size=dim,
                    distance=self._rest.Distance.COSINE,
                ),
            )
        self._known_collections.add(name)

    async def upsert_point(
        self,
        collection: str,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        point = self._rest.PointStruct(
            id=point_id,
            vector=list(vector),
            payload=dict(payload),
        )
        await self._client.upsert(
            collection_name=collection,
            points=[point],
            wait=True,
        )

    async def search_points(
        self,
        collection: str,
        query_vector: list[float],
        limit: int,
        filter: dict[str, Any] | None,  # noqa: A002 — matches Protocol
    ) -> list[VectorHit]:
        qfilter = None
        if filter:
            conditions = [
                self._rest.FieldCondition(
                    key=str(k),
                    match=self._rest.MatchValue(value=v),
                )
                for k, v in filter.items()
            ]
            qfilter = self._rest.Filter(must=conditions)
        try:
            resp = await self._client.query_points(
                collection_name=collection,
                query=list(query_vector),
                limit=limit,
                query_filter=qfilter,
                with_payload=True,
            )
        except Exception as exc:  # noqa: BLE001
            # Collection missing / server down — degrade to empty. The
            # adapter's search() layer surfaces this as an empty list;
            # callers (SemanticMemoryPath) already log-and-continue.
            log.warning(
                "RealQdrantBackend: query_points(%s) raised: %s",
                collection,
                exc,
            )
            return []

        # AsyncQdrantClient.query_points returns a
        # ``QueryResponse`` with a ``.points`` list on modern client
        # versions and a raw list on older ones. Support both.
        points = getattr(resp, "points", None)
        if points is None:
            points = resp
        out: list[VectorHit] = []
        for p in points:
            out.append(
                VectorHit(
                    id=str(p.id),
                    score=float(p.score) if p.score is not None else 0.0,
                    payload=dict(p.payload or {}),
                )
            )
        return out

    async def delete_point(self, collection: str, point_id: str) -> None:
        await self._client.delete(
            collection_name=collection,
            points_selector=self._rest.PointIdsList(points=[point_id]),
            wait=True,
        )

    async def create_snapshot(self, collection: str) -> SnapshotHandle:
        resp = await self._client.create_snapshot(collection_name=collection)
        name = getattr(resp, "name", None) or getattr(resp, "snapshot_name", "")
        location = getattr(resp, "location", "") or ""
        created = (
            getattr(resp, "creation_time", None)
            or getattr(resp, "created_at", None)
            or datetime.now(timezone.utc).isoformat()
        )
        return SnapshotHandle(
            collection=collection,
            name=str(name),
            path=str(location),
            created_at=str(created),
        )

    def is_healthy(self) -> bool:
        """Non-throwing sync probe (ADR-023 rule 5).

        Plain synchronous HTTP GET on ``/healthz`` (urllib, no event loop).

        ADR-124 D6 (bug fix): the previous implementation ran
        ``self._client.get_collections()`` (AsyncQdrantClient) on a freshly
        spawned event loop. But the async client's HTTP pool binds to the
        FIRST loop it touches — after kernel boot (main loop) every sync
        probe failed with "coroutine was never awaited" → permanent false
        negative. A loop-free HTTP call sidesteps the whole class.
        ``/healthz`` is the same endpoint the ADR-117 data-services probe
        uses. Returns False on any failure (ADR-023 rule 5).
        """
        if self._closed:
            return False
        try:
            import urllib.request

            req = urllib.request.Request(f"{self._url}/healthz", method="GET")
            if self._api_key:
                req.add_header("api-key", self._api_key)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:  # noqa: BLE001
            log.debug("RealQdrantBackend.is_healthy: %s", exc)
            return False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._client.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("RealQdrantBackend.close raised: %s", exc)
