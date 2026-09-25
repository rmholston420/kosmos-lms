"""ADR-134 — kernel-native Hindsight endpoints (donor wire shapes).

The panels HindsightTab used to call ``:8020/api/hindsight/{status,
experiences}`` — the *standalone* engine's in-process ``HindsightClient``
(``src/tektos/memory/hindsight_client.py``) talking to the Hindsight
daemon. The daemon itself (default ``http://127.0.0.1:9178``,
``KOSMOS_HINDSIGHT_URL``) is standalone infrastructure with a v1 REST
API; the kernel already health-probes it in
``kernel/tektos_data_services.py::_probe_hindsight``. This module adds
the *recall* leg: ``GET /api/hindsight/experiences`` maps the daemon's
``POST /v1/{profile}/banks/{bank_id}/memories/recall`` to the donor's
experience list (tag-preferring ``context``, client-side ``limit``),
faithful to the donor client.
"""

from __future__ import annotations

import os
from typing import Any

_HINDSIGHT_DEFAULT_URL = "http://127.0.0.1:9178"


def _base_url() -> str:
    return (
        os.environ.get("KOSMOS_HINDSIGHT_URL") or _HINDSIGHT_DEFAULT_URL
    ).rstrip("/")


def _profile() -> str:
    return os.environ.get("KOSMOS_HINDSIGHT_PROFILE", "default")


def _bank_id() -> str:
    return os.environ.get("KOSMOS_HINDSIGHT_BANK", "default")


async def _recall(query: str, limit: int) -> list[dict[str, Any]]:
    """``POST /v1/{profile}/banks/{bank}/memories/recall`` → results.

    Donor fidelity: the v1 ``RecallRequest`` has no ``limit`` field — the
    client asks for the default set and slices; an empty/whitespace query
    is sent as the neutral sentinel ``"tektos"`` (v1 rejects empty
    queries with 422).
    """
    import httpx

    sent_query = query if query and query.strip() else "tektos"
    path = f"/v1/{_profile()}/banks/{_bank_id()}/memories/recall"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{_base_url()}{path}", json={"query": sent_query}
        )
        response.raise_for_status()
        data = response.json()
    results = data.get("results", []) if isinstance(data, dict) else []
    return results[:limit] if isinstance(results, list) else []


async def get_experiences(
    context: str = "", limit: int = 10
) -> list[dict[str, Any]]:
    """Donor ``HindsightClient.get_experiences`` — tag-preferring order.

    Items whose ``tags`` include ``context`` come first; the remainder
    fills from other results, truncated to ``limit``.
    """
    results = await _recall(context, limit=limit)
    preferred = [r for r in results if context in (r.get("tags") or [])]
    others = [r for r in results if r not in preferred]
    return (preferred + others)[:limit]


# ── Write leg (ADR-143 T3 / S5a): the learning substrate's dual-persist ──────


def retain(
    content: str,
    *,
    context: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Persist one memory to the Hindsight bank (donor ``HindsightClient.retain``).

    Donor fidelity: wraps the fact in an ``items`` list (single-item
    ``RetainRequest`` shape) and POSTs to the bank's ``memories``
    endpoint. SYNC on purpose — the kernel learning substrate
    (``kernel.learning.LearningEngine._save_to_hindsight``) calls it from a
    synchronous ``_save_experience`` path, exactly as the donor's sync
    ``HindsightClient.retain`` did.

    Fail-open at the call site: the engine wraps this in try/except and
    degrades (the experience still lands in the JSONL ledger). This
    function itself raises on transport/HTTP errors so the caller decides.
    """
    import httpx

    item: dict[str, Any] = {"content": content}
    if context is not None:
        item["context"] = context
    if tags is not None:
        item["tags"] = tags
    path = f"/v1/{_profile()}/banks/{_bank_id()}/memories"
    with httpx.Client(timeout=5.0) as client:
        response = client.post(f"{_base_url()}{path}", json={"items": [item]})
        response.raise_for_status()
        return response.json()
