"""Kernel-native data-service status endpoints (ADR-117, v2 Stage 11).

Stage-11 endpoint split, first slice: the Tektos-Ultima dashboard's five
data-service cards (Neo4j, Postgres, Redis/Valkey, Hindsight, Qdrant) used
to be proxied to the standalone Tektos API on :8020 through the ADR-109
gateway. That upstream retired — the cards went dead with it. These
endpoints probe the *services themselves* directly, using the same
env-driven configuration the kernel boot paths use (ADR-101 honesty rule:
the card always shows the real state, including "not configured" and
"auth failed" — never a silent success).

Design (ADR-117):

* Service-level, not lane-level. Each probe reflects the state of the
  backing service, independent of whether the kernel booted a lane for it
  (e.g. the Postgres card is green when the server is up even with
  ``KOSMOS_RELATIONAL_MEMORY=off``).
* Always HTTP 200 with a ``healthy`` flag (except a 500 on internal
  probe bug). A 502/503 envelope would collapse "unreachable",
  "auth failed", and "not configured" into one undifferentiated
  "down" — the split is the point of the endpoint.
* No registry coupling (ADR-109 D2 pattern): probes are env-driven and
  build short-lived clients per request. A probe failure can never take
  a route down, and a downed service can never take the kernel down.
* Every probe is timeout-bounded (<= 3 s) so a wedged service can only
  stall its own card, never the dashboard's poll cycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter

_LOG = logging.getLogger(__name__)

_HINDSIGHT_DEFAULT_URL = "http://127.0.0.1:9178"
_QDRANT_DEFAULT_URL = "http://127.0.0.1:6333"
_REDIS_DEFAULT_URL = "redis://127.0.0.1:6379/0"
_PROBE_TIMEOUT_S = 3.0


def _host_port(url: str) -> tuple[str, int | None]:
    """Best-effort host/port extraction; never raises."""
    try:
        p = urlparse(url)
        return p.hostname or "unknown", p.port
    except Exception:  # noqa: BLE001 — probe must never raise
        return "unknown", None


# ---------------------------------------------------------------------------
# Per-service probes. Each returns the card payload shape:
#   {service, healthy, status, ...service-specific fields}
#   status ∈ {connected, unreachable, auth_failed, unconfigured}
# ---------------------------------------------------------------------------


async def _probe_neo4j() -> dict[str, Any]:
    """Bolt probe against the DozerDB lane's Neo4j (KOSMOS_DOZERDB_*).

    Mirrors ``kernel/app.py::_boot_memory``'s dozerdb env reads so the
    card reflects exactly what the memory boot path would connect to.
    Distinguishes the three failure modes the ADR-091-era card could
    not: missing config, bad credentials, and transport failure.
    """
    uri = os.environ.get("KOSMOS_DOZERDB_URI")
    user = os.environ.get("KOSMOS_DOZERDB_USER")
    password = os.environ.get("KOSMOS_DOZERDB_PASSWORD")
    database = os.environ.get("KOSMOS_DOZERDB_DATABASE") or "neo4j"
    if not uri or not user or not password:
        return {
            "service": "neo4j",
            "healthy": False,
            "status": "unconfigured",
            "detail": "KOSMOS_DOZERDB_URI/_USER/_PASSWORD not set",
        }
    host, port = _host_port(uri)
    base = {
        "service": "neo4j",
        "status": "unreachable",
        "healthy": False,
        "uri": uri,
        "host": host,
        "port": port,
        "database_name": database,
    }
    try:
        from neo4j import AsyncGraphDatabase
        from neo4j.exceptions import AuthError, Neo4jError

        driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        try:
            await asyncio.wait_for(
                driver.verify_connectivity(), timeout=_PROBE_TIMEOUT_S
            )
            base.update(status="connected", healthy=True)
            return base
        except AuthError as exc:
            base.update(status="auth_failed", detail=str(exc)[:200])
        except (asyncio.TimeoutError, Neo4jError, OSError) as exc:
            base.update(
                status="unreachable",
                detail=f"{type(exc).__name__}: {exc}"[:200],
            )
        finally:
            await driver.close()
    except ImportError as exc:
        base.update(status="unreachable", detail=f"driver import: {exc}")
    return base


async def _probe_postgres() -> dict[str, Any]:
    """Direct asyncpg ``SELECT 1`` against KOSMOS_POSTGRES_URI.

    Service-level by design: probes the DSN the boot path would use
    (``_boot_relational_memory``), independent of
    ``KOSMOS_RELATIONAL_MEMORY`` mode. Credentials are stripped from the
    reported URL.
    """
    dsn = os.environ.get("KOSMOS_POSTGRES_URI")
    if not dsn:
        return {
            "service": "postgres",
            "healthy": False,
            "status": "unconfigured",
            "detail": "KOSMOS_POSTGRES_URI not set",
        }
    p = urlparse(dsn)
    base: dict[str, Any] = {
        "service": "postgres",
        "status": "unreachable",
        "healthy": False,
        "connected": False,
        "host": p.hostname or "unknown",
        "port": p.port or 5432,
        "database_name": (p.path or "/").lstrip("/") or "postgres",
        # netloc includes the user:pass pair — strip it before reporting.
        "url": f"postgresql://{p.hostname}:{p.port}/{(p.path or '/').lstrip('/')}",
    }
    try:
        import asyncpg

        conn = await asyncio.wait_for(
            asyncpg.connect(dsn=dsn), timeout=_PROBE_TIMEOUT_S
        )
        try:
            await asyncio.wait_for(conn.execute("SELECT 1"), timeout=_PROBE_TIMEOUT_S)
            base.update(status="connected", healthy=True, connected=True)
        finally:
            await conn.close()
    except ImportError as exc:
        base.update(detail=f"driver import: {exc}")
    except (asyncio.TimeoutError, OSError) as exc:
        base.update(detail=f"{type(exc).__name__}: {exc}"[:200])
    except Exception as exc:  # noqa: BLE001 — asyncpg raises many specific types
        # asyncpg.PostgresConnectionError covers auth + transport failure;
        # surface it distinctly when the message says authentication.
        msg = str(exc)[:200]
        if "authentication" in msg.lower():
            base.update(status="auth_failed", detail=msg)
        else:
            base.update(status="unreachable", detail=msg)
    return base


async def _probe_redis() -> dict[str, Any]:
    """PING against KOSMOS_VALKEY_URL (default redis://127.0.0.1:6379/0).

    The card is labeled Redis; the backing service on this host is
    Valkey — same wire protocol, same env var the event-bus adapter reads
    (``adapters/event_bus/valkey/adapter.py``).
    """
    url = os.environ.get("KOSMOS_VALKEY_URL") or _REDIS_DEFAULT_URL
    host, port = _host_port(url)
    base: dict[str, Any] = {
        "service": "redis",
        "status": "unreachable",
        "healthy": False,
        "connected": False,
        "ping_ok": False,
        "host": host,
        "port": port,
    }
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            url, socket_connect_timeout=_PROBE_TIMEOUT_S
        )
        try:
            ping = await asyncio.wait_for(client.ping(), timeout=_PROBE_TIMEOUT_S)
            base.update(
                status="connected",
                healthy=True,
                connected=True,
                ping_ok=bool(ping),
            )
        finally:
            await client.aclose()
    except ImportError as exc:
        base.update(detail=f"driver import: {exc}")
    except (asyncio.TimeoutError, OSError) as exc:
        base.update(detail=f"{type(exc).__name__}: {exc}"[:200])
    except Exception as exc:  # noqa: BLE001 — redis-py exception family
        base.update(detail=f"{type(exc).__name__}: {exc}"[:200])
    return base


async def _probe_hindsight() -> dict[str, Any]:
    """HTTP probe of the standalone Hindsight daemon (default :9178).

    Hindsight is a standalone daemon, not a kernel lane (no
    ``registry.hindsight``) — the endpoint is a pure ``GET /health``
    against ``KOSMOS_HINDSIGHT_URL``.
    """
    base_url = (
        os.environ.get("KOSMOS_HINDSIGHT_URL") or _HINDSIGHT_DEFAULT_URL
    ).rstrip("/")
    host, port = _host_port(base_url)
    base: dict[str, Any] = {
        "service": "hindsight",
        "status": "unreachable",
        "healthy": False,
        "base_url": base_url,
        "host": host,
        "port": port,
    }
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}/health")
            if resp.status_code == 200:
                base.update(status="connected", healthy=True)
            else:
                base.update(detail=f"HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001 — httpx exception family
        base.update(detail=f"{type(exc).__name__}: {exc}"[:200])
    return base


async def _probe_qdrant() -> dict[str, Any]:
    """Health + collection count against KOSMOS_QDRANT_URL (default :6333).

    Uses ``/healthz`` (Qdrant's actual health route — ``/health`` 404s)
    and ``/collections`` for the count the card displays. Same env var
    ``_boot_vector`` reads.
    """
    base_url = (
        os.environ.get("KOSMOS_QDRANT_URL") or _QDRANT_DEFAULT_URL
    ).rstrip("/")
    host, port = _host_port(base_url)
    base: dict[str, Any] = {
        "service": "qdrant",
        "status": "unreachable",
        "healthy": False,
        "base_url": base_url,
        "host": host,
        "port": port,
        "collections": 0,
    }
    api_key = os.environ.get("KOSMOS_QDRANT_API_KEY")
    headers = {"api-key": api_key} if api_key else {}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2.0, headers=headers) as client:
            resp = await client.get(f"{base_url}/healthz")
            if resp.status_code != 200:
                base.update(detail=f"HTTP {resp.status_code} on /healthz")
                return base
            base.update(status="connected", healthy=True)
            try:
                colls = await client.get(f"{base_url}/collections")
                if colls.status_code == 200:
                    payload = colls.json()
                    base["collections"] = len(payload.get("collections") or [])
            except Exception:  # noqa: BLE001 — count is cosmetic
                pass
    except Exception as exc:  # noqa: BLE001 — httpx exception family
        base.update(detail=f"{type(exc).__name__}: {exc}"[:200])
    return base


# ---------------------------------------------------------------------------
# Router (ADR-109 factory pattern — no registry coupling)
# ---------------------------------------------------------------------------


def build_tektos_data_services_router() -> APIRouter:
    """Build the ``/api/tektos/data-services`` router.

    Mounted by ``kernel/app.py`` next to the ADR-109 gateway with the
    same degrade-to-WARN-on-mount-failure pattern.
    """
    router = APIRouter(prefix="/api/tektos/data-services", tags=["tektos"])

    @router.get("/neo4j/status")
    async def neo4j_status() -> dict[str, Any]:
        """Neo4j (DozerDB lane) status — see ``_probe_neo4j``."""
        return await _probe_neo4j()

    @router.get("/postgres/status")
    async def postgres_status() -> dict[str, Any]:
        """Postgres status — see ``_probe_postgres``."""
        return await _probe_postgres()

    @router.get("/redis/status")
    async def redis_status() -> dict[str, Any]:
        """Redis/Valkey status — see ``_probe_redis``."""
        return await _probe_redis()

    @router.get("/hindsight/status")
    async def hindsight_status() -> dict[str, Any]:
        """Hindsight daemon status — see ``_probe_hindsight``."""
        return await _probe_hindsight()

    @router.get("/qdrant/status")
    async def qdrant_status() -> dict[str, Any]:
        """Qdrant status — see ``_probe_qdrant``."""
        return await _probe_qdrant()

    return router
