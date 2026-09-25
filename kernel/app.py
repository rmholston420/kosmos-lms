"""Kosmos kernel FastAPI app (Stage 6.5.9 — GUI enablement kernel additions).

Boot sequence (Stage 6.5.1+6.5.2 baseline preserved; 6.5.3 adds route only):

1. Seven kernel subsystems boot behind per-subsystem try/except:
   ``notification``, ``frontend_contract``, ``resource``, ``event_bus``,
   ``approval``, ``phrouros`` (now real — ADR-059), ``zetesis`` (ADR-058).
2. Resource subsystem is seeded at boot with baseline balances so
   ``/api/resources/balances`` returns real numbers instead of ``null``
   (ADR-059 §D2). Failure is degraded, not fatal.
3. Phrouros mounts once ``event_bus``, ``notification``, ``resource``
   have booted. It composes ``PhrourosEngine`` over the shipped
   ``InMemoryTraceFeedAdapter`` (ports/trace_feed.py) + the four
   ``ports/observability`` detectors + the shared kernel adapters
   (ADR-059 §D1). Failure surfaces under ``registry.errors["phrouros"]``.

Kernel HTTP endpoints (6.5.5):

- ``/api/phrouros/anomalies`` — 200 with real (usually empty) records.
- ``POST /api/zetesis/research`` — SSE endpoint (ADR-060) emitting
  ``started`` + ``completed`` on the happy path; ``started`` + ``error``
  on failure.
- ``GET /api/events/ws`` — WebSocket event-bus bridge (ADR-061); on
  connect sends a ``ready`` frame with the subscribed event-type list,
  then forwards published ``EventEnvelope``s as JSON ``event`` frames.
- ``POST /api/approvals/{approval_id}/approve`` and
  ``POST /api/approvals/{approval_id}/reject`` — approval resolve
  endpoints (ADR-062) over the existing ``ApprovalResolverPort``.
- ``POST /api/tektos/turn`` — drives one ``TektosAgent`` iteration
  (ADR-063) over the kernel-owned ``LLMPort`` + ``MemoryPort``
  adapters; returns the resulting ``TektosStep``.
- ``GET /api/gnosis/query`` — Gnosis retrieval surrogate over
  ``MemoryPort.query_temporal`` (ADR-064). Optional ``as_of`` ISO-8601
  filter, ``limit`` bounded to ``[1, 100]`` (default 20), optional
  ``corpus`` name filter that restricts hits to a manifest provenance.
- ``GET /api/gnosis/corpora`` — manifest of the five landed corpora
  (ADR-064) — ``synthetic-lifeline``, ``humanities-cidoc-sample``,
  ``rigpa-export``, ``superpowers``, ``humanities-bilara`` — augmented
  with live ``fact_count`` and ``last_ingested_at`` from the boot seeder.
- ``GET /api/gnosis/stats`` — top-line dashboard numbers computed from
  the static ``ALL_CORPORA`` tuple (ADR-064).
- ``GET /api/gnosis/event/{event_id}`` — single hit lookup by
  ``event_id`` via ``MemoryPort.query_temporal`` (ADR-064).
- ``GET /api/ollama/status`` — top-bar model-swap indicator; passthrough
  to Ollama ``/api/ps`` returning ``{model, size_vram, size_ram,
  vram_capacity_bytes}`` (ADR-068 D1). VRAM capacity is Colossus-fixed
  at 32 GiB (RTX 5090).
- ``GET /api/praxis/constitution`` — read-only constitution summary
  ``{version, sha256, ratified_at, title, article_count}`` (ADR-068 D2).
- ``GET /api/praxis/apex/policies`` — enumeration of the nine spec §14
  Tier-2 escalation triggers (ADR-068 D3).

Boot env vars (ADR-064):

- ``KOSMOS_GNOSIS_SEED=1`` — ingest ``ALL_CORPORA`` into ``MemoryPort``
  at startup (default off; safe no-op on populated DBs via class-name
  idempotency matching).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import time
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Boot helpers
# ---------------------------------------------------------------------------


class _BootRegistry:
    """Holds live adapters + per-subsystem boot errors."""

    def __init__(self) -> None:
        self.errors: dict[str, str] = {}
        self.frontend_contract: Any = None
        self.resource: Any = None
        self.approval: Any = None
        self.notification: Any = None
        self.thermal_watchdog: Any = None
        self.phrouros: Any = None
        self.event_bus: Any = None
        self.zetesis: Any = None
        self.trace_feed: Any = None
        # Stage 6.5.6 additions (ADR-063).
        self.llm: Any = None
        self.memory: Any = None
        # Stage 8.0 (ADR-102): kernel-owned RelationalMemoryPort — the 5th
        # memory layer, combining the R1 audit ledger and the R2 episodic
        # narrative store. Populated by ``_boot_relational_memory``. Boots
        # into the ``off`` state by default (returns None with no warning);
        # explicit opt-in via ``KOSMOS_RELATIONAL_MEMORY={noop,postgres}``.
        # Downstream call sites MUST tolerate ``None`` (health-check pattern:
        # ``if registry.relational_memory is None: ...``).
        self.relational_memory: Any = None
        # Stage 9.1 (KOSMOS_LMS_INTEGRATION_PLAN_v2): kernel-owned
        # ImmunePort — the Tektos immune adapter with the full 12-detector
        # set (3 ADR-092 seeds + 9 Stage 9.1 completions). Populated by
        # ``_boot_immune``. Boots into the ``off`` state by default (returns
        # None with no warning); explicit opt-in via ``KOSMOS_IMMUNE=on``.
        # Optionally consumes ``registry.event_bus`` (verdict envelopes)
        # and ``registry.relational_memory`` (block records). Downstream
        # call sites MUST tolerate ``None`` (ADR-101 degrade pattern).
        self.immune: Any = None
        # Stage 8.1 (ADR-103): kernel-owned SessionPort — the 24th formal
        # port + FSM substrate for Stages 8.2–8.7 (turn loop, reflection,
        # planner, executor, manager, multi-agent). Populated by
        # ``_boot_session``. Boots into the ``off`` state by default
        # (returns None with no warning); explicit opt-in via
        # ``KOSMOS_SESSION={inmemory,tektos}``. Downstream call sites MUST
        # tolerate ``None`` (ADR-101 degrade pattern).
        self.session: Any = None
        # Stage 8.2 (ADR-104): kernel-owned TektosTurnLoop — the Stage 3.13
        # turn-loop skeleton grown with optional SessionPort + LLMPort +
        # SandboxPort + ResourcePort collaborators. Populated by
        # ``_boot_tektos_turn_loop``. Boots into the ``off`` state by
        # default (returns None with no warning); explicit opt-in via
        # ``KOSMOS_TEKTOS_TURN_LOOP=on``. Downstream call sites MUST
        # tolerate ``None`` (ADR-101 degrade pattern).
        self.tektos_turn_loop: Any = None
        # Stage 8.3 (ADR-105): kernel-owned Tektos reflection + synthesis
        # + experience-replay engines. All three env-gated via
        # ``KOSMOS_TEKTOS_{REFLECTION,SYNTHESIS,EXPERIENCE}={off,on}``
        # (default ``off`` — silent). ``on`` requires
        # ``registry.relational_memory`` non-None; missing → ADR-101
        # degrade to ``None`` with a WARN log. Downstream call sites
        # MUST tolerate ``None`` (ADR-101 degrade pattern).
        self.tektos_reflection: Any = None
        self.tektos_synthesis: Any = None
        self.tektos_experience: Any = None
        # Stage 8.4 (ADR-106): kernel-owned Tektos spec-planner + task-decomposer
        # engines. Env-gated via ``KOSMOS_TEKTOS_{SPEC_PLANNER,DECOMPOSER}={off,on}``
        # (default ``off``). ``on`` requires ``registry.relational_memory``
        # non-None; missing → ADR-101 degrade to ``None`` with a WARN log.
        # Downstream call sites MUST tolerate ``None``.
        self.tektos_spec_planner: Any = None
        self.tektos_decomposer: Any = None
        self.tektos_executor: Any = None
        self.tektos_tool_router: Any = None
        # Stage 8.6 (ADR-108): kernel-owned Tektos S3 Manager engine (VSM
        # variety regulator + guardrail enforcer). Env-gated via
        # ``KOSMOS_TEKTOS_MANAGER={off,on}`` (default ``off``). ``on``
        # requires ``registry.relational_memory`` non-None; optionally
        # consumes ``registry.event_bus`` + ``registry.immune`` +
        # ``registry.observability``. Missing hard requirement → ADR-101
        # degrade to ``None`` with a WARN log. Downstream call sites
        # MUST tolerate ``None``.
        self.tektos_manager: Any = None
        # Stage 8.7 (ADR-114): kernel-owned Tektos multi-agent
        # orchestration engine family (TektosOrchestrator +
        # TektosHierarchicalAgent + TektosLongRunningAgent). Env-gated via
        # ``KOSMOS_TEKTOS_ORCHESTRATOR={off,on}`` (default ``off``). ``on``
        # requires ``registry.relational_memory`` non-None; optionally
        # consumes ``registry.sandbox``, ``registry.llm`` and
        # ``registry.event_bus``. Missing hard requirement → ADR-101
        # degrade to ``None`` with a WARN log. Downstream call sites
        # MUST tolerate ``None``.
        self.tektos_orchestrator: Any = None
        self.tektos_hierarchical: Any = None
        self.tektos_long_running: Any = None
        # Stage 1.6 Phase 0 (ADR-073): kernel-owned EmbeddingsPort. Separate
        # from ``self.llm`` so chat-only backends (e.g. llama-swap) don't
        # have to satisfy an embeddings surface. Populated by ``_boot_embeddings``.
        self.embeddings: Any = None
        # Stage 1.6 Phase 1 (ADR-074 D2): kernel-owned VectorPort. Booted
        # alongside ``self.embeddings`` and passed together into
        # ``_boot_memory`` so the DozerDB adapter can compose them into
        # its semantic memory lane. When ``vector`` is None (env-gated,
        # or Qdrant unreachable) the memory adapter's ``search_semantic``
        # degrades to an empty list; the graph + temporal paths are
        # unaffected.
        self.vector: Any = None
        self.tektos: Any = None
        self.tektos_agent: Any = None
        self.tektos_agent_lock: Any = None
        # Stage 6.5.8 (ADR-065): Tektos UI sub-app + its executor. Mounted at
        # ``/tektos-ui`` independently of ``registry.tektos`` (Option B):
        # the UI only needs ``registry.approval`` + ``registry.memory``, so it
        # stays reachable when the agent is down for triage of stuck plans.
        self.tektos_ui: Any = None
        self.tektos_ui_executor: Any = None
        # Stage 6.5.7 (ADR-064): Gnosis seeder state. ``gnosis_corpus_counts``
        # maps corpus name -> number of facts successfully written this boot
        # (``0`` when the seeder didn't run or write-blocked every fact).
        # ``gnosis_last_seeded_at`` is the UTC ISO timestamp of the last
        # successful seeder run, or ``None`` when the seeder didn't run.
        self.gnosis_corpus_counts: dict[str, int] = {}
        self.gnosis_last_seeded_at: str | None = None
        # Stage 1.5 Wave C (ADR-069): Kernel kill-switch soft-suspend state.
        # ``suspended`` gates mutating routes via middleware; introspection
        # routes (/health, /api/kernel/**, WS) stay reachable in either
        # state. Toggled by POST /api/kernel/kill and POST /api/kernel/resume.
        self.suspended: bool = False
        self.suspended_at: str | None = None
        self.suspend_reason: str | None = None
        # Stage 1.5 Wave D (ADR-070): Zetesis report ring buffer for
        # MEMORY_INTEGRITY graph endpoints. Populated best-effort by an
        # event bus subscriber added on Zetesis mount. Bounded at 100 to
        # cap memory footprint on Colossus's fixed envelope.
        from collections import deque as _deque_reports

        self.zetesis_reports: Any = _deque_reports(maxlen=100)
        # Handle to the Zetesis plugin itself, when mounted. Kept as ``Any``
        # to preserve ADR-007 (no cross-plugin type import in the kernel).
        self.zetesis_plugin: Any = None
        # Stage 1.5 Wave E (ADR-071): Event-bus subscriber wiring for
        # ``zetesis.research.completed``. ``_zetesis_report_queue`` holds
        # the pull-model queue returned by ``EventBusPort.subscribe``;
        # ``_zetesis_drain_task`` is the background asyncio task that
        # forwards drained envelopes into ``self.zetesis_reports``. Both
        # remain ``None`` when subscription failed (best-effort per
        # ADR-058 pattern) and are cleaned up on lifespan shutdown.
        self.zetesis_report_queue: Any = None
        self._zetesis_drain_task: Any = None


registry = _BootRegistry()


def _try(subsystem: str):
    """Decorator: catch bootstrap errors per subsystem."""

    def wrap(fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — deliberate broad catch
            registry.errors[subsystem] = f"{type(exc).__name__}: {exc}"
            return None

    return wrap


# ---------------------------------------------------------------------------
# Resource seed defaults (ADR-059 §D2)
# ---------------------------------------------------------------------------


# Kept in one place so tests and docs can reference them.
# ResourceKind values are enumerated in ports/resource.py: time, money,
# attention, compute, knowledge, energy (six canonical kinds per spec §16).
# Seed values are baselines the operator can adjust with subsequent
# ``replenish()`` calls; they are NOT commitments about real physical
# resources, only presentation defaults so the GUI's resource-meter
# widgets render immediately at boot.
KERNEL_RESOURCE_SEED: dict[str, Decimal] = {
    "time": Decimal("1440"),        # one day of minutes
    "money": Decimal("100.00"),     # $100 discretionary budget
    "attention": Decimal("100"),    # normalized 0-100 pool
    "compute": Decimal("100"),      # normalized capacity pool
    "knowledge": Decimal("1"),      # nominal starting unit; accrues via Zetesis / research (replenish() rejects 0)
    "energy": Decimal("100"),       # normalized human-energy pool
}


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


def _build_llm_adapter():
    """Construct the kernel's LLMPort: FailoverLLMAdapter (ADR-116 D2).

    primary  = LlamaSwapAdapter()   — OpenAI /v1 transport to the shared
                 llama.cpp server (:8090 on Colossus via
                 KOSMOS_LLAMA_SWAP_*; :8080 sidecar defaults otherwise).
    fallback = OllamaAdapter()      — native Ollama protocol (:11434 via
                 KOSMOS_OLLAMA_*; qwen3-vl:4b on Colossus).

    Both adapters read their own env vars when constructor args are
    omitted, so this builder passes no kwargs — one env file configures
    both lanes. Module-level (not a lifespan closure) so the ADR-116 D4
    kernel test can drive it directly with monkeypatched env, no live
    servers, no full-lifespan boot.
    """
    from adapters.llm.failover import FailoverLLMAdapter
    from adapters.llm.llama_swap import LlamaSwapAdapter
    from adapters.llm.ollama.adapter import OllamaAdapter

    return FailoverLLMAdapter(LlamaSwapAdapter(), OllamaAdapter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Notification (no args) ------------------------------------------------
    @_try("notification")
    def _boot_notification():
        from adapters.notification.kernel.adapter import KernelNotificationAdapter

        return KernelNotificationAdapter()

    registry.notification = _boot_notification

    # --- ADR-121 (Stage 11.5): sustained-thermal watchdog -----------------
    # Background sampler (5 s) + the >75°C-for-60s cooldown rule. Env-gated
    # off for CI sandboxes (no GPU); default on. Never blocks boot.
    @_try("thermal_watchdog")
    def _boot_thermal_watchdog():
        import os as _os

        if _os.environ.get("KOSMOS_THERMAL_WATCHDOG", "on").lower() not in ("on", "true", "1"):
            return None
        from kernel.tektos_thermal_watchdog import ThermalWatchdog

        watchdog = ThermalWatchdog(event_bus=registry.event_bus)
        watchdog.start()
        return watchdog

    registry.thermal_watchdog = _boot_thermal_watchdog

    # --- FrontendContract (no required args) ----------------------------------
    @_try("frontend_contract")
    def _boot_frontend():
        from adapters.frontend_contract.kernel.adapter import (
            KernelFrontendContractAdapter,
        )

        return KernelFrontendContractAdapter()

    registry.frontend_contract = _boot_frontend

    # --- Resource (SqliteResourceAdapter needs Storage; use InMemoryStorage) --
    @_try("resource")
    def _boot_resource():
        from adapters.resource.sqlite.adapter import (
            InMemoryStorage,
            SqliteResourceAdapter,
        )

        storage = InMemoryStorage()
        adapter = SqliteResourceAdapter(storage=storage)
        # Stash storage on the adapter so /api/resources/balances can
        # read ResourceBalance rows directly (ResourcePort exposes no
        # get_balance surface — that lives on the Storage protocol).
        adapter._kernel_storage = storage  # type: ignore[attr-defined]
        return adapter

    registry.resource = _boot_resource

    # --- Resource seed (ADR-059 §D2) — best-effort ---------------------------
    if registry.resource is not None:
        try:
            from ports.resource import ResourceKind

            for kind_name, amount in KERNEL_RESOURCE_SEED.items():
                try:
                    kind = ResourceKind(kind_name)
                except ValueError:
                    # Kind not in current ResourceKind enum; skip silently.
                    # Seed table intentionally lists forward-compatible names.
                    continue
                await registry.resource.replenish(kind, amount)
        except Exception as exc:  # noqa: BLE001
            # Resource stays up; seeding is best-effort.
            registry.errors["resource_seed"] = f"{type(exc).__name__}: {exc}"

    # --- EventBus (Valkey; env-driven URL, best-effort) -----------------------
    @_try("event_bus")
    def _boot_event_bus():
        from adapters.event_bus.valkey.adapter import ValkeyEventBusAdapter

        return ValkeyEventBusAdapter()

    registry.event_bus = _boot_event_bus

    # --- Approval (KernelChangeApprovalAdapter, 4 seams) ----------------------
    @_try("approval")
    def _boot_approval():
        from adapters.approval_resolver.praxis.adapter import (
            PraxisApprovalResolverAdapter,
        )
        from plugins.praxis.apex.engine import KernelChangeApprovalAdapter
        from plugins.praxis.apex.scheduler import InProcessScheduler
        from plugins.praxis.apex.storage import InMemoryStorage as PraxisStorage

        if registry.event_bus is None or registry.notification is None:
            raise RuntimeError(
                "approval depends on event_bus + notification; "
                "one of them failed to boot"
            )

        engine = KernelChangeApprovalAdapter(
            storage=PraxisStorage(),
            scheduler=InProcessScheduler(),
            event_bus=registry.event_bus,
            notification=registry.notification,
        )
        return PraxisApprovalResolverAdapter(engine=engine)

    registry.approval = _boot_approval

    # --- Phrouros (ADR-059 §D1 — wire the real engine over InMemoryTraceFeedAdapter) ---
    # Requires event_bus + notification + resource to have booted. If any is
    # missing we surface the reason and continue degraded.
    if (
        registry.event_bus is None
        or registry.notification is None
        or registry.resource is None
    ):
        registry.errors["phrouros"] = (
            "phrouros depends on event_bus + notification + resource; "
            "one of them failed to boot"
        )
    else:
        try:
            # Only LoopDetector ships a real implementation at Stage 6.5.1
            # (per plugins/phrouros/detector.py module docstring). The
            # three skeletons (bus_factor_1, model_swap_slo, stub_degradation)
            # raise DetectorNotImplementedError on detect() and are wired in
            # by their own future stages. UnauthorizedToolDetector requires
            # a curated tool allowlist not yet defined at kernel level and
            # is deferred to the stage that produces one.
            from plugins.phrouros.detectors.loop import LoopDetector
            from plugins.phrouros.engine import PhrourosEngine
            from ports.trace_feed import InMemoryTraceFeedAdapter

            trace_feed = InMemoryTraceFeedAdapter()
            registry.trace_feed = trace_feed

            engine = PhrourosEngine(
                trace_feed=trace_feed,
                detectors=(LoopDetector(),),
                notification_port=registry.notification,
                resource_port=registry.resource,
                event_bus=registry.event_bus,
            )
            await engine.start()
            registry.phrouros = engine
        except Exception as exc:  # noqa: BLE001
            registry.errors["phrouros"] = f"{type(exc).__name__}: {exc}"

    # --- LLM (FailoverLLMAdapter: llama.cpp :8090 primary, Ollama fallback) --
    # Stage 6.5.6 addition (ADR-063), repointed per ADR-116 (2026-09-25):
    # primary = LlamaSwapAdapter (OpenAI /v1 transport) pointed at the shared
    # llama.cpp server — same lane Hermes Agent uses. On Colossus the
    # KOSMOS_LLAMA_SWAP_* env vars select :8090 + qwen3.8-27b-code; without
    # them the adapter defaults to the llama-swap sidecar (:8080), and every
    # call then fails over to Ollama — i.e. the pre-ADR-116 behavior.
    # fallback = OllamaAdapter (native protocol, KOSMOS_OLLAMA_* env; model
    # pinned to qwen3-vl:4b on Colossus since that is the only resident
    # model on :11434). Failure surfaces under ``registry.errors['llm']``
    # and cascades to Tektos boot below. Construction lives in
    # ``_build_llm_adapter`` (module-level, ADR-116 D4 kernel test drives it
    # directly with monkeypatched env).
    @_try("llm")
    def _boot_llm():
        return _build_llm_adapter()

    registry.llm = _boot_llm

    # --- Embeddings (LlamaEmbeddingsAdapter) --------------------------------
    # ADR-124 D1: kernel-owned EmbeddingsPort now points at the llama.cpp
    # embedder (qwen3-embedding-0.6b on :8091, CPU-only by design — keeps
    # the RTX 5090's 32 GB free for the 27B lane on :8090). Served via
    # llama-server's OpenAI-compat ``/v1/embeddings``. 1024-dim.
    # Env overrides: ``KOSMOS_EMBEDDER_BASE_URL`` +
    # ``KOSMOS_EMBEDDER_MODEL``. Failure surfaces under
    # ``registry.errors['embeddings']``.
    # (Supersedes the Stage 1.6 Ollama nomic lane — ADR-073 adapter stays
    # in-tree for the Ollama panel but is no longer the RAG embedder.)
    @_try("embeddings")
    def _boot_embeddings():
        from adapters.embeddings.llama.adapter import LlamaEmbeddingsAdapter

        return LlamaEmbeddingsAdapter()

    registry.embeddings = _boot_embeddings

    # --- Vector (QdrantVectorAdapter) ---------------------------------------
    # Stage 1.6 Phase 1 addition (ADR-074 D2): kernel-owned VectorPort.
    # Env overrides: ``KOSMOS_QDRANT_URL`` (default ``http://127.0.0.1:6333``)
    # and ``KOSMOS_VECTOR_ENABLED`` (default ``"1"``; set to ``"0"`` to
    # skip vector boot entirely — the memory adapter's ``search_semantic``
    # then degrades gracefully to an empty list). Failure surfaces under
    # ``registry.errors['vector']``.
    @_try("vector")
    def _boot_vector():
        import os

        if os.environ.get("KOSMOS_VECTOR_ENABLED", "1") != "1":
            return None
        from adapters.vector.qdrant.adapter import QdrantVectorAdapter
        from adapters.vector.qdrant.real_backend import RealQdrantBackend

        url = os.environ.get(
            "KOSMOS_QDRANT_URL", "http://127.0.0.1:6333"
        )
        api_key = os.environ.get("KOSMOS_QDRANT_API_KEY") or None
        backend = RealQdrantBackend(url=url, api_key=api_key)
        return QdrantVectorAdapter(backend=backend)

    registry.vector = _boot_vector

    # --- Memory (DozerDbMemoryAdapter, env-gated backends) --------------------
    # Stage 6.5.6 addition (ADR-063): kernel-owned MemoryPort shared by
    # Tektos and future plugins.
    #
    # ``KOSMOS_MEMORY_BACKEND`` selects the graph + temporal backends:
    #   ``in_memory`` (default)  — InMemoryGraphBackend + InMemoryTemporalIndex
    #                              + NoOpAmgPolicy. CI/test-safe, no external
    #                              services required.
    #   ``dozerdb``              — DozerDbGraphBackend + InMemoryTemporalIndex
    #                              + AmgGuardPolicy(tiered). Requires
    #                              ``KOSMOS_DOZERDB_URI``, ``_USER``,
    #                              ``_PASSWORD`` (and optional ``_DATABASE``).
    #                              ADR-075 D1: GraphitiTemporalIndex was hard-
    #                              deleted; temporal writes flow through
    #                              ``InMemoryTemporalIndex`` alongside DozerDB
    #                              graph writes until a replacement temporal
    #                              backend is proposed in a future ADR.
    #
    # ``KOSMOS_MEMORY_LEXICAL`` selects the lexical retrieval lane (ADR-101):
    #   unset / ``off`` (default) — no lexical lane; ``search_hybrid`` raises
    #                              ``NotImplementedError`` per ADR-085's
    #                              honesty rule.
    #   ``dozerdb``              — DozerDbLexicalIndex wrapping a Neo4j
    #                              Lucene fulltext index; shares the same
    #                              Bolt endpoint as the graph backend
    #                              (ADR-008 single-canonical-store rule).
    #                              REQUIRES ``KOSMOS_MEMORY_BACKEND=dozerdb``.
    #                              Fails-closed on unhealthy driver (D3):
    #                              falls through to ``lexical=None`` with a
    #                              warning log; ``search_hybrid`` reverts
    #                              to ``NotImplementedError``.
    @_try("memory")
    def _boot_memory():
        import os

        from adapters.memory.dozerdb.adapter import (
            DozerDbMemoryAdapter,
            InMemoryGraphBackend,
            InMemoryTemporalIndex,
            NoOpAmgPolicy,
        )

        backend = os.environ.get("KOSMOS_MEMORY_BACKEND", "in_memory").lower()
        lexical_mode = os.environ.get("KOSMOS_MEMORY_LEXICAL", "off").lower()

        # ADR-101 D2 reject-shape guard: lexical=dozerdb requires
        # backend=dozerdb (shared Bolt endpoint per ADR-008).
        _ALLOWED_LEXICAL = ("off", "dozerdb")
        if lexical_mode not in _ALLOWED_LEXICAL:
            raise RuntimeError(
                "KOSMOS_MEMORY_LEXICAL=%r is not one of %s (ADR-101 D2)."
                % (lexical_mode, _ALLOWED_LEXICAL)
            )
        if lexical_mode == "dozerdb" and backend != "dozerdb":
            raise RuntimeError(
                "KOSMOS_MEMORY_LEXICAL=dozerdb requires "
                "KOSMOS_MEMORY_BACKEND=dozerdb (ADR-101 D2 shared-Bolt-endpoint rule); "
                "got KOSMOS_MEMORY_BACKEND=%r." % backend
            )

        def _maybe_wire_dozerdb_lexical(
            *, uri: str, user: str, password: str, database: str
        ):
            """Construct DozerDbLexicalIndex when opt-in env is set (ADR-101 D1/D3).

            Returns a healthy ``DozerDbLexicalIndex`` or ``None``. Never
            raises — fails closed with a warning log so the caller can
            proceed with ``lexical=None`` (search_hybrid then raises
            ``NotImplementedError`` per ADR-085, unchanged from the
            no-opt-in default).
            """
            if lexical_mode != "dozerdb":
                return None

            import logging as _kosmos_logging

            log = _kosmos_logging.getLogger(__name__)
            try:
                from adapters.memory.dozerdb.dozerdb_lexical_index import (
                    DozerDbLexicalIndex,
                )

                lex = DozerDbLexicalIndex(
                    uri=uri,
                    user=user,
                    password=password,
                    database=database,
                )
            except Exception as _lex_ctor_exc:  # noqa: BLE001 — ADR-101 D3
                log.warning(
                    "kosmos.memory.lexical: construction failed; "
                    "search_hybrid will raise NotImplementedError "
                    "(ADR-101 D3): %s: %s",
                    type(_lex_ctor_exc).__name__,
                    _lex_ctor_exc,
                )
                return None

            if not lex.is_healthy():
                _init_err = getattr(lex, "_init_error", None)
                # DozerDbLexicalIndex.close() is async; _boot_memory runs
                # synchronously inside @_try("memory") so we cannot await
                # here. When is_healthy() is False, _init_error is set
                # BEFORE _driver is assigned (see adapter __init__), so
                # there is no live driver to close — best-effort abandon.
                del lex
                log.warning(
                    "kosmos.memory.lexical: unhealthy at boot; "
                    "search_hybrid will raise NotImplementedError "
                    "(ADR-101 D3); init_error=%r",
                    _init_err,
                )
                return None

            log.info(
                "kosmos.memory.lexical: wired (ADR-101); backend=dozerdb uri=%s database=%s",
                uri,
                database,
            )
            return lex

        if backend == "dozerdb":
            uri = os.environ["KOSMOS_DOZERDB_URI"]
            user = os.environ["KOSMOS_DOZERDB_USER"]
            password = os.environ["KOSMOS_DOZERDB_PASSWORD"]
            database = os.environ.get("KOSMOS_DOZERDB_DATABASE", "neo4j")

            from adapters.memory.dozerdb.amg_policy import AmgGuardPolicy
            from adapters.memory.dozerdb.dozerdb_graph_backend import (
                DozerDbGraphBackend,
            )

            graph = DozerDbGraphBackend(
                uri=uri,
                user=user,
                password=password,
                database=database,
            )
            # ADR-075 D1: GraphitiTemporalIndex hard-deleted; use the
            # in-memory temporal index until a replacement backend lands.
            temporal = InMemoryTemporalIndex()
            amg = AmgGuardPolicy(policy_preset="tiered")
            # ADR-101 D1: opt-in lexical lane sharing the same Bolt endpoint.
            lexical = _maybe_wire_dozerdb_lexical(
                uri=uri, user=user, password=password, database=database
            )
            # ADR-074 D3: pass EmbeddingsPort + VectorPort so the
            # adapter can compose them into its semantic memory lane.
            # Both may be ``None`` — the adapter degrades gracefully.
            return DozerDbMemoryAdapter(
                graph=graph,
                amg=amg,
                temporal=temporal,
                embeddings=registry.embeddings,
                vector=registry.vector,
                lexical=lexical,
            )

        # Default: in-memory (CI / test / cold-start safe).
        # ADR-074 D3: even the in-memory backend receives the semantic
        # lane deps when they've booted, so operators can exercise
        # ``search_semantic`` against Qdrant without spinning DozerDB.
        # ADR-101: lexical stays None on the in-memory branch — we do NOT
        # auto-wire InMemoryLexicalIndex here (would make it too easy to
        # ship a test backend into production; search_hybrid raising
        # NotImplementedError is the intended default-mode signal).
        return DozerDbMemoryAdapter(
            graph=InMemoryGraphBackend(),
            amg=NoOpAmgPolicy(),
            temporal=InMemoryTemporalIndex(),
            embeddings=registry.embeddings,
            vector=registry.vector,
        )

    registry.memory = _boot_memory

    # --- Stage 8.0 RelationalMemoryPort (ADR-102) ---------------------------
    # The 5th memory layer. Two adapters ship: NoOp (aiosqlite in-memory,
    # zero external dep) and Postgres (asyncpg + pgvector, production).
    #
    # Env contract (ADR-102 D6):
    #   KOSMOS_RELATIONAL_MEMORY = off | noop | postgres    (default: off)
    #   KOSMOS_POSTGRES_URI      = postgres://...           (required if postgres)
    #
    # Health failure follows the ADR-101 degrade pattern: unhealthy adapter
    # -> registry.relational_memory stays None with a warning log; the app
    # boots and downstream call sites treat None as "5th layer offline".
    @_try("relational_memory")
    def _boot_relational_memory():
        import logging as _kosmos_logging
        import os

        log = _kosmos_logging.getLogger(__name__)
        mode = os.environ.get("KOSMOS_RELATIONAL_MEMORY", "off").lower().strip()

        _ALLOWED = ("off", "noop", "postgres")
        if mode not in _ALLOWED:
            raise RuntimeError(
                "KOSMOS_RELATIONAL_MEMORY=%r is not one of %s (ADR-102 D6)."
                % (mode, _ALLOWED)
            )

        if mode == "off":
            return None  # silent — this is the default

        if mode == "noop":
            from adapters.relational_memory import NoOpRelationalMemoryAdapter

            adapter = NoOpRelationalMemoryAdapter()
            if not adapter.is_healthy():
                init_err = getattr(adapter, "_init_error", None)
                log.warning(
                    "kosmos.relational_memory: noop unhealthy at boot; "
                    "5th layer offline (ADR-102 D6); init_error=%r",
                    init_err,
                )
                return None
            log.info(
                "kosmos.relational_memory: wired (ADR-102); adapter=noop "
                "backend=aiosqlite:memory"
            )
            return adapter

        # mode == "postgres"
        dsn = os.environ.get("KOSMOS_POSTGRES_URI")
        if not dsn:
            raise RuntimeError(
                "KOSMOS_RELATIONAL_MEMORY=postgres requires KOSMOS_POSTGRES_URI "
                "(ADR-102 D6)."
            )

        from adapters.relational_memory import PostgresRelationalMemoryAdapter

        if PostgresRelationalMemoryAdapter is None:
            log.warning(
                "kosmos.relational_memory: postgres adapter unavailable "
                "(asyncpg not installed); 5th layer offline (ADR-102 D6)"
            )
            return None

        adapter = PostgresRelationalMemoryAdapter(dsn=dsn)
        if not adapter.is_healthy():
            init_err = getattr(adapter, "_init_error", None)
            log.warning(
                "kosmos.relational_memory: postgres unhealthy at boot; "
                "5th layer offline (ADR-102 D6); init_error=%r",
                init_err,
            )
            return None
        log.info(
            "kosmos.relational_memory: wired (ADR-102); adapter=postgres dsn=%s",
            dsn,
        )
        return adapter

    registry.relational_memory = _boot_relational_memory

    # --- Immune boot (Stage 9.1 / ADR-079 + ADR-092 + plan DoD) -------------
    # Env contract: ``KOSMOS_IMMUNE = off | on`` (default ``off``).
    #
    # ``on`` → TektosImmuneAdapter with the full 12-detector set
    # (3 ADR-092 seeds + 9 Stage 9.1 completions). Optionally consumes
    # ``registry.event_bus`` (verdict envelopes) and
    # ``registry.relational_memory`` (block records); both are optional —
    # the adapter publishes/records only when wired (ADR-101 degrade).
    # Unhealthy adapter → registry.immune stays None with a warning;
    # downstream call sites treat None as offline.
    @_try("immune")
    def _boot_immune():
        import logging as _kosmos_logging
        import os

        log = _kosmos_logging.getLogger(__name__)
        mode = os.environ.get("KOSMOS_IMMUNE", "off").lower().strip()

        if mode not in ("off", "on"):
            raise RuntimeError(
                "KOSMOS_IMMUNE=%r is not one of ('off', 'on') (Stage 9.1)."
                % (mode,)
            )

        if mode == "off":
            return None  # silent — the default

        from adapters.immune.tektos.adapter import (
            TektosImmuneAdapter,
            build_seed_detectors,
        )

        detectors = build_seed_detectors()
        adapter = TektosImmuneAdapter(
            # _DetectorAdapter wraps a donor detector and structurally
            # satisfies ports.immune.Detector (name + severity_ceiling +
            # async evaluate) — Pyright can't see the private wrapper
            # across modules, hence the ignore (contract test proves
            # isinstance(adapter, ImmunePort)).
            initial_detectors=detectors,  # type: ignore[arg-type]
            event_bus=registry.event_bus,
            memory=registry.relational_memory,
        )
        if not adapter.is_healthy():
            log.warning(
                "kosmos.immune: adapter unhealthy at boot; ImmunePort "
                "offline (Stage 9.1)"
            )
            return None
        log.info(
            "kosmos.immune: wired (Stage 9.1); detectors=%d event_bus=%s "
            "memory=%s",
            len(detectors),
            "on" if registry.event_bus is not None else "off",
            "on" if registry.relational_memory is not None else "off",
        )
        return adapter

    registry.immune = _boot_immune

    # --- Session boot (Stage 8.1 / ADR-103) ---------------------------------
    # Env contract (ADR-103 D4):
    #   KOSMOS_SESSION = off | inmemory | tektos             (default: off)
    #
    # ``inmemory`` — asyncio-lock-protected in-process adapter. No
    # dependencies beyond the kernel-owned EventBusPort (mirror is
    # optional at construction; the in-memory adapter does not emit
    # events, so bus + memory are not required).
    # ``tektos`` — fidelity port of the tektos-ultima runtime. Requires
    # ``registry.event_bus`` (envelope-first ADR-023); optional mirror
    # to ``registry.relational_memory`` when present.
    #
    # Health failure follows the ADR-101 degrade pattern: unhealthy
    # adapter → registry.session stays None with a warning log; the
    # app boots and downstream call sites treat None as offline.
    @_try("session")
    def _boot_session():
        import logging as _kosmos_logging
        import os

        log = _kosmos_logging.getLogger(__name__)
        mode = os.environ.get("KOSMOS_SESSION", "off").lower().strip()

        _ALLOWED = ("off", "inmemory", "tektos")
        if mode not in _ALLOWED:
            raise RuntimeError(
                "KOSMOS_SESSION=%r is not one of %s (ADR-103 D4)."
                % (mode, _ALLOWED)
            )

        if mode == "off":
            return None  # silent — the default

        if mode == "inmemory":
            from adapters.session import InMemorySessionAdapter

            adapter = InMemorySessionAdapter()
            if not adapter.is_healthy():
                log.warning(
                    "kosmos.session: inmemory unhealthy at boot; "
                    "SessionPort offline (ADR-103 D4)"
                )
                return None
            log.info(
                "kosmos.session: wired (ADR-103); adapter=inmemory"
            )
            return adapter

        # mode == "tektos"
        if registry.event_bus is None:
            log.warning(
                "kosmos.session: tektos adapter requires event_bus but "
                "registry.event_bus is None; SessionPort offline "
                "(ADR-103 D4)"
            )
            return None

        try:
            from adapters.session import TektosSessionAdapter  # type: ignore[attr-defined]
        except ImportError:
            log.warning(
                "kosmos.session: tektos adapter import failed; "
                "SessionPort offline (ADR-103 D4)"
            )
            return None

        adapter = TektosSessionAdapter(
            event_bus=registry.event_bus,
            relational_memory=registry.relational_memory,
        )
        if not adapter.is_healthy():
            log.warning(
                "kosmos.session: tektos unhealthy at boot; "
                "SessionPort offline (ADR-103 D4)"
            )
            return None
        log.info(
            "kosmos.session: wired (ADR-103); adapter=tektos mirror=%s",
            "on" if registry.relational_memory is not None else "off",
        )
        return adapter

    registry.session = _boot_session

    # --- Stage 8.2 (ADR-104) TektosTurnLoop ----------------------------------
    # Grows the Stage 3.13 pre-LLM skeleton with four optional port
    # collaborators (SessionPort / LLMPort / SandboxPort / ResourcePort).
    # Env-gated via ``KOSMOS_TEKTOS_TURN_LOOP={off,on}`` (default ``off``).
    # Required Stage 3.13 collaborators are ``immune`` + ``loop_safety`` +
    # ``thermal``; when any is missing at boot the loop stays ``None``
    # with a warning (ADR-101 degrade pattern). The four Stage 8.2
    # collaborators are wired opportunistically from the registry — each
    # may be ``None`` and the loop tolerates that (ADR-104 D1).
    @_try("tektos_turn_loop")
    def _boot_tektos_turn_loop():
        import logging as _kosmos_logging
        import os

        log = _kosmos_logging.getLogger(__name__)
        mode = (
            os.environ.get("KOSMOS_TEKTOS_TURN_LOOP", "off").lower().strip()
        )

        _ALLOWED = ("off", "on")
        if mode not in _ALLOWED:
            raise RuntimeError(
                "KOSMOS_TEKTOS_TURN_LOOP=%r is not one of %s (ADR-104 D10)."
                % (mode, _ALLOWED)
            )

        if mode == "off":
            return None  # silent — the default

        # ``on`` requires the three Stage 3.13 base collaborators. Pull
        # them from the registry; when the plugin exposes them under a
        # nested handle we fall through to ``None`` and log-degrade.
        immune = getattr(registry, "immune", None)
        loop_safety = getattr(registry, "loop_safety", None)
        thermal = getattr(registry, "thermal", None)

        # Fallback: the tektos plugin often carries these three on itself
        # rather than on the registry root. Probe the plugin handle when
        # the direct registry slots are unset.
        tektos_plugin = getattr(registry, "tektos", None)
        if tektos_plugin is not None:
            immune = immune or getattr(tektos_plugin, "immune", None)
            loop_safety = loop_safety or getattr(
                tektos_plugin, "loop_safety", None
            )
            thermal = thermal or getattr(tektos_plugin, "thermal", None)

        missing = [
            name
            for name, val in (
                ("immune", immune),
                ("loop_safety", loop_safety),
                ("thermal", thermal),
            )
            if val is None
        ]
        if missing:
            log.warning(
                "kosmos.tektos_turn_loop: required collaborators missing %s; "
                "loop offline (ADR-104 D10; ADR-101 degrade pattern)",
                missing,
            )
            return None

        from plugins.tektos.runtime.turn_loop import TektosTurnLoop

        loop = TektosTurnLoop(
            immune=immune,
            loop_safety=loop_safety,
            thermal=thermal,
            event_bus=registry.event_bus,
            session_port=registry.session,
            llm=registry.llm,
            sandbox=getattr(registry, "sandbox", None),
            resource=registry.resource,
        )
        log.info(
            "kosmos.tektos_turn_loop: wired (ADR-104); session=%s llm=%s "
            "sandbox=%s resource=%s",
            "on" if registry.session is not None else "off",
            "on" if registry.llm is not None else "off",
            "on" if getattr(registry, "sandbox", None) is not None else "off",
            "on" if registry.resource is not None else "off",
        )
        # Reflect the wired loop onto the TektosPlugin dataclass slot too
        # (ADR-104 D11) so plugin-side code paths can reach it.
        if tektos_plugin is not None and hasattr(
            tektos_plugin, "turn_loop"
        ):
            try:
                tektos_plugin.turn_loop = loop
            except Exception:  # noqa: BLE001 — frozen dataclass tolerated
                log.debug(
                    "kosmos.tektos_turn_loop: TektosPlugin.turn_loop "
                    "assignment skipped (frozen?)"
                )
        return loop

    registry.tektos_turn_loop = _boot_tektos_turn_loop

    # --- Stage 8.3/8.4 (ADR-105/ADR-106) Tektos engines ---------------------
    # Shared boot helper for the env-gated Stage 8.x Tektos engines:
    #   • Stage 8.3 (ADR-105): reflection / synthesis / experience
    #   • Stage 8.4 (ADR-106): spec_planner / decomposer
    # Each engine persists through ``RelationalMemoryPort.write_narrative``
    # and publishes through ``EventBusPort``. Each boots ``off`` by default;
    # ``on`` requires ``registry.relational_memory`` non-None. Missing
    # collaborator → ADR-101 degrade to ``None`` with a WARN log citing the
    # engine's owning ADR (passed as ``adr_note``).
    def _boot_stage_8_x_engine(
        *,
        env_var: str,
        adr_note: str,
        engine_factory,
        plugin_field: str,
    ):
        import logging as _kl
        import os as _os

        _log = _kl.getLogger(__name__)
        _mode = _os.environ.get(env_var, "off").lower().strip()
        _ALLOWED = ("off", "on")
        if _mode not in _ALLOWED:
            raise RuntimeError(
                "%s=%r is not one of %s (ADR-105 D6 / ADR-106 D6)."
                % (env_var, _mode, _ALLOWED)
            )
        if _mode == "off":
            return None

        rmem = getattr(registry, "relational_memory", None)
        ebus = getattr(registry, "event_bus", None)
        if rmem is None:
            _log.warning(
                "kosmos.%s: RelationalMemoryPort unavailable; engine offline "
                "(%s; ADR-101 degrade pattern)",
                plugin_field,
                adr_note,
            )
            return None

        engine = engine_factory(relational_memory=rmem, event_bus=ebus)
        _log.info(
            "kosmos.%s: wired (%s); event_bus=%s",
            plugin_field,
            adr_note,
            "on" if ebus is not None else "off",
        )

        # Reflect the wired engine onto the TektosPlugin dataclass slot
        # too (ADR-105 D5) so plugin-side code paths can reach it.
        _tp = getattr(registry, "tektos", None)
        if _tp is not None and hasattr(_tp, plugin_field):
            try:
                setattr(_tp, plugin_field, engine)
            except Exception:  # noqa: BLE001 — frozen dataclass tolerated
                _log.debug(
                    "kosmos.%s: TektosPlugin.%s assignment skipped (frozen?)",
                    plugin_field,
                    plugin_field,
                )
        return engine

    @_try("tektos_reflection")
    def _boot_tektos_reflection():
        from plugins.tektos.reflection import ReflectionEngine

        return _boot_stage_8_x_engine(
            env_var="KOSMOS_TEKTOS_REFLECTION",
            adr_note="ADR-105",
            engine_factory=ReflectionEngine,
            plugin_field="reflection",
        )

    @_try("tektos_synthesis")
    def _boot_tektos_synthesis():
        from plugins.tektos.synthesis import SynthesisEngine

        return _boot_stage_8_x_engine(
            env_var="KOSMOS_TEKTOS_SYNTHESIS",
            adr_note="ADR-105",
            engine_factory=SynthesisEngine,
            plugin_field="synthesis",
        )

    @_try("tektos_experience")
    def _boot_tektos_experience():
        from plugins.tektos.experience import ExperienceReplay

        return _boot_stage_8_x_engine(
            env_var="KOSMOS_TEKTOS_EXPERIENCE",
            adr_note="ADR-105",
            engine_factory=ExperienceReplay,
            plugin_field="experience",
        )

    @_try("tektos_spec_planner")
    def _boot_tektos_spec_planner():
        from plugins.tektos.planner import TektosSpecPlanner

        return _boot_stage_8_x_engine(
            env_var="KOSMOS_TEKTOS_SPEC_PLANNER",
            adr_note="ADR-106",
            engine_factory=TektosSpecPlanner,
            plugin_field="spec_planner",
        )

    @_try("tektos_decomposer")
    def _boot_tektos_decomposer():
        from plugins.tektos.decomposer import TaskDecomposer

        return _boot_stage_8_x_engine(
            env_var="KOSMOS_TEKTOS_DECOMPOSER",
            adr_note="ADR-106",
            engine_factory=TaskDecomposer,
            plugin_field="decomposer",
        )

    # --- Stage 8.5 (ADR-107) Tektos executor + tool-router -----------------
    # The tool_router fits the shared _boot_stage_8_x_engine helper directly
    # (relational_memory + event_bus constructor args only). The executor
    # additionally picks up ``registry.sandbox`` when wired, so it uses a
    # bespoke boot function that reuses the same env-gate + degrade + plugin
    # reflection semantics via a thin wrapper around the shared helper.
    @_try("tektos_tool_router")
    def _boot_tektos_tool_router():
        from plugins.tektos.executor import TektosToolRouter

        return _boot_stage_8_x_engine(
            env_var="KOSMOS_TEKTOS_TOOL_ROUTER",
            adr_note="ADR-107",
            engine_factory=TektosToolRouter,
            plugin_field="tool_router",
        )

    @_try("tektos_executor")
    def _boot_tektos_executor():
        import logging as _kl
        import os as _os

        from plugins.tektos.executor import TektosSpecExecutor

        _log = _kl.getLogger(__name__)
        _env = "KOSMOS_TEKTOS_EXECUTOR"
        _mode = _os.environ.get(_env, "off").lower().strip()
        _ALLOWED = ("off", "on")
        if _mode not in _ALLOWED:
            raise RuntimeError(
                "%s=%r is not one of %s (ADR-107 D6)."
                % (_env, _mode, _ALLOWED)
            )
        if _mode == "off":
            return None

        rmem = getattr(registry, "relational_memory", None)
        ebus = getattr(registry, "event_bus", None)
        sbox = getattr(registry, "sandbox", None)
        if rmem is None:
            _log.warning(
                "kosmos.tektos_executor: RelationalMemoryPort unavailable; "
                "engine offline (ADR-107; ADR-101 degrade pattern)"
            )
            return None

        engine = TektosSpecExecutor(
            relational_memory=rmem, event_bus=ebus, sandbox=sbox
        )
        _log.info(
            "kosmos.tektos_executor: wired (ADR-107); event_bus=%s; sandbox=%s",
            "on" if ebus is not None else "off",
            "on" if sbox is not None else "off",
        )

        _tp = getattr(registry, "tektos", None)
        if _tp is not None and hasattr(_tp, "executor"):
            try:
                setattr(_tp, "executor", engine)
            except Exception:  # noqa: BLE001 — frozen dataclass tolerated
                _log.debug(
                    "kosmos.tektos_executor: TektosPlugin.executor assignment "
                    "skipped (frozen?)"
                )
        return engine

    @_try("tektos_manager")
    def _boot_tektos_manager():
        import logging as _kl
        import os as _os

        from plugins.tektos.manager import TektosManager

        _log = _kl.getLogger(__name__)
        _env = "KOSMOS_TEKTOS_MANAGER"
        _mode = _os.environ.get(_env, "off").lower().strip()
        _ALLOWED = ("off", "on")
        if _mode not in _ALLOWED:
            raise RuntimeError(
                "%s=%r is not one of %s (ADR-108 D6)."
                % (_env, _mode, _ALLOWED)
            )
        if _mode == "off":
            return None

        rmem = getattr(registry, "relational_memory", None)
        ebus = getattr(registry, "event_bus", None)
        immune = getattr(registry, "immune", None)
        obs = getattr(registry, "observability", None)
        if rmem is None:
            _log.warning(
                "kosmos.tektos_manager: RelationalMemoryPort unavailable; "
                "engine offline (ADR-108; ADR-101 degrade pattern)"
            )
            return None

        engine = TektosManager(
            relational_memory=rmem,
            event_bus=ebus,
            immune=immune,
            observability=obs,
        )
        _log.info(
            "kosmos.tektos_manager: wired (ADR-108); event_bus=%s; immune=%s; observability=%s",
            "on" if ebus is not None else "off",
            "on" if immune is not None else "off",
            "on" if obs is not None else "off",
        )

        _tp = getattr(registry, "tektos", None)
        if _tp is not None and hasattr(_tp, "manager"):
            try:
                setattr(_tp, "manager", engine)
            except Exception:  # noqa: BLE001 — frozen dataclass tolerated
                _log.debug(
                    "kosmos.tektos_manager: TektosPlugin.manager assignment "
                    "skipped (frozen?)"
                )
        return engine

    @_try("tektos_orchestrator")
    def _boot_tektos_orchestrator():
        import logging as _kl
        import os as _os

        from plugins.tektos.orchestrator import (
            OrchestratorBundle,
            TektosHierarchicalAgent,
            TektosLongRunningAgent,
            TektosOrchestrator,
        )

        _log = _kl.getLogger(__name__)
        _env = "KOSMOS_TEKTOS_ORCHESTRATOR"
        _mode = _os.environ.get(_env, "off").lower().strip()
        _ALLOWED = ("off", "on")
        if _mode not in _ALLOWED:
            raise RuntimeError(
                "%s=%r is not one of %s (ADR-114 D6)."
                % (_env, _mode, _ALLOWED)
            )
        if _mode == "off":
            return None

        rmem = getattr(registry, "relational_memory", None)
        ebus = getattr(registry, "event_bus", None)
        sbox = getattr(registry, "sandbox", None)
        llm = getattr(registry, "llm", None)
        if rmem is None:
            _log.warning(
                "kosmos.tektos_orchestrator: RelationalMemoryPort unavailable; "
                "engine family offline (ADR-114; ADR-101 degrade pattern)"
            )
            return None

        orchestrator = TektosOrchestrator(
            sandbox=sbox,
            relational_memory=rmem,
            event_bus=ebus,
        )
        bundle = OrchestratorBundle(
            orchestrator=orchestrator,
            wired_sandbox=sbox is not None,
            wired_memory=True,
            wired_event_bus=ebus is not None,
        )
        hierarchical = TektosHierarchicalAgent(llm=llm, event_bus=ebus)
        long_running = TektosLongRunningAgent(relational_memory=rmem)
        _log.info(
            "kosmos.tektos_orchestrator: wired (ADR-114); sandbox=%s; llm=%s; event_bus=%s",
            "on" if sbox is not None else "off",
            "on" if llm is not None else "off",
            "on" if ebus is not None else "off",
        )

        _tp = getattr(registry, "tektos", None)
        if _tp is not None:
            for _attr, _value in (
                ("orchestrator", bundle),
                ("hierarchical_agent", hierarchical),
                ("long_running_agent", long_running),
            ):
                if hasattr(_tp, _attr):
                    try:
                        setattr(_tp, _attr, _value)
                    except Exception:  # noqa: BLE001 — frozen dataclass tolerated
                        _log.debug(
                            "kosmos.tektos_orchestrator: TektosPlugin.%s "
                            "assignment skipped (frozen?)",
                            _attr,
                        )
        # Stash the sibling engines on the bundle so the caller (which
        # only sees the registry-slot return value) can reach them.
        registry.tektos_hierarchical = hierarchical
        registry.tektos_long_running = long_running
        return bundle

    registry.tektos_reflection = _boot_tektos_reflection
    registry.tektos_synthesis = _boot_tektos_synthesis
    registry.tektos_experience = _boot_tektos_experience
    registry.tektos_spec_planner = _boot_tektos_spec_planner
    registry.tektos_decomposer = _boot_tektos_decomposer
    registry.tektos_tool_router = _boot_tektos_tool_router
    registry.tektos_executor = _boot_tektos_executor
    registry.tektos_manager = _boot_tektos_manager
    registry.tektos_orchestrator = _boot_tektos_orchestrator

    # --- Gnosis boot seeder (ADR-064) ----------------------------------------
    # Env-gated by ``KOSMOS_GNOSIS_SEED=1``. Iterates ``ALL_CORPORA`` and
    # writes every fact through ``MemoryPort.write_event``. Idempotent
    # (re-runs on a populated DB are no-ops via class-name matching).
    # Best-effort: seeder failures do not block boot; Gnosis routes
    # remain functional against whatever facts the graph already contains.
    if os.environ.get("KOSMOS_GNOSIS_SEED", "0") == "1":
        if registry.memory is None:
            registry.errors["gnosis_seed"] = (
                "skipped: memory subsystem is None"
            )
        else:
            try:
                from adapters.memory.dozerdb.corpora import ALL_CORPORA
                from datetime import datetime as _dt, timezone as _tz

                counts: dict[str, int] = {}
                for corpus in ALL_CORPORA:
                    seeded = 0
                    for fact in corpus.facts:
                        try:
                            await registry.memory.write_event(
                                fact.subject,
                                fact.predicate,
                                fact.object_,
                                provenance=fact.provenance,
                                confidence=fact.confidence,
                                attributes={
                                    **fact.attributes,
                                    "corpus_name": corpus.name,
                                    "corpus_event_id": fact.event_id,
                                    "as_of": fact.as_of.isoformat(),
                                },
                            )
                            seeded += 1
                        except Exception as exc:  # noqa: BLE001
                            # Idempotent by class-name matching
                            # (ADR-007). Anything else is a real error.
                            if type(exc).__name__ in _GNOSIS_SEED_IGNORABLE:
                                continue
                            raise
                    counts[corpus.name] = seeded
                registry.gnosis_corpus_counts = counts
                registry.gnosis_last_seeded_at = _dt.now(_tz.utc).isoformat()
            except Exception as exc:  # noqa: BLE001
                registry.errors["gnosis_seed"] = (
                    f"{type(exc).__name__}: {exc}"
                )

    # --- Zetesis plugin mount (ADR-058) ---------------------------------------
    # Depends on frontend_contract having booted; reuses the same
    # KernelFrontendContractAdapter, event_bus, resource, and notification
    # instances so descriptor registration is visible on /api/kernel/plugins
    # and /api/kernel/routes without duplicate state.
    if registry.frontend_contract is None:
        registry.errors["zetesis"] = (
            "zetesis depends on frontend_contract; it failed to boot"
        )
    else:
        try:
            from plugins.zetesis.adapters.real.factory import (
                build_stage_6_5_zetesis_plugin,
            )

            plugin = build_stage_6_5_zetesis_plugin(
                frontend_contract=registry.frontend_contract,
                event_bus=registry.event_bus,
                resource=registry.resource,
                notification=registry.notification,
                memory=registry.memory,
            )
            await plugin.start()
            registry.zetesis = plugin
            registry.zetesis_plugin = plugin
        except Exception as exc:  # noqa: BLE001
            registry.errors["zetesis"] = f"{type(exc).__name__}: {exc}"

        # Stage 1.5 Wave E (ADR-071 D3): subscribe to
        # ``zetesis.research.completed`` on the event bus and spawn a
        # background task that appends drained payloads into
        # ``registry.zetesis_reports``. Best-effort per ADR-058: any
        # failure lands in ``registry.errors['zetesis_subscriber']`` and
        # keeps the kernel 200 elsewhere. The task is cancelled on
        # lifespan shutdown below.
        if registry.zetesis is not None and registry.event_bus is not None:
            try:
                import asyncio as _asyncio_wave_e

                q = registry.event_bus.subscribe(
                    "zetesis.research.completed", maxsize=100
                )
                registry.zetesis_report_queue = q

                async def _drain_zetesis_reports() -> None:
                    while True:
                        env = await q.get()
                        # Store the payload dict (ADR-071 D4). The event
                        # payload is the authoritative wire format; we do
                        # not reconstruct a ``ResearchReport``.
                        payload = getattr(env, "payload", None)
                        if not isinstance(payload, dict):
                            continue
                        registry.zetesis_reports.append(payload)

                        # ADR-075 D3: fan-out to MemoryPort.write_event so
                        # the report becomes semantically searchable. Best-
                        # effort per ADR-058: subscriber failures land in
                        # ``registry.errors['zetesis_fanout']`` and do not
                        # block the queue. Zero-trust write floor: static
                        # provenance + confidence 1.0 (report came from a
                        # kernel-owned event bus subscription).
                        if registry.memory is None:
                            continue
                        try:
                            report_id = str(
                                payload.get("report_id")
                                or payload.get("id")
                                or getattr(env, "event_id", "")
                                or "unknown"
                            )
                            summary = str(
                                payload.get("summary")
                                or payload.get("answer")
                                or payload.get("question")
                                or ""
                            )
                            if not summary:
                                continue
                            await registry.memory.write_event(
                                subject=f"zetesis.report:{report_id}",
                                predicate="zetesis.research.completed",
                                object=summary,
                                provenance="zetesis.event_bus",
                                confidence=1.0,
                                attributes={
                                    "report_id": report_id,
                                    "kind": "zetesis.report",
                                },
                            )
                        except Exception as exc:  # noqa: BLE001
                            registry.errors["zetesis_fanout"] = (
                                f"{type(exc).__name__}: {exc}"
                            )

                registry._zetesis_drain_task = _asyncio_wave_e.create_task(
                    _drain_zetesis_reports()
                )
            except Exception as exc:  # noqa: BLE001
                registry.errors["zetesis_subscriber"] = (
                    f"{type(exc).__name__}: {exc}"
                )

    # --- Tektos plugin mount + agent singleton (ADR-063) ----------------------
    # Depends on frontend_contract (descriptor registration), llm, memory.
    # Failure of any dependency surfaces under ``registry.errors['tektos']``
    # and returns ``tektos: false`` on ``/health.subsystems`` while keeping
    # the kernel 200 on every other endpoint.
    if (
        registry.frontend_contract is None
        or registry.llm is None
        or registry.memory is None
    ):
        missing = [
            name
            for name, val in (
                ("frontend_contract", registry.frontend_contract),
                ("llm", registry.llm),
                ("memory", registry.memory),
            )
            if val is None
        ]
        registry.errors["tektos"] = (
            f"tektos depends on {missing}; one or more failed to boot"
        )
    else:
        try:
            import asyncio as _asyncio

            from plugins.tektos.agent import TektosAgent
            from plugins.tektos.plugin import TektosPlugin

            tektos_plugin = TektosPlugin(
                frontend_contract_port=registry.frontend_contract,
            )
            await tektos_plugin.start()
            registry.tektos = tektos_plugin
            registry.tektos_agent = TektosAgent(
                llm=registry.llm,
                memory=registry.memory,
            )
            registry.tektos_agent_lock = _asyncio.Lock()
        except Exception as exc:  # noqa: BLE001
            registry.errors["tektos"] = f"{type(exc).__name__}: {exc}"

    # --- Tektos UI sub-app mount (ADR-065, Stage 6.5.8) -----------------------
    # Depends on ``registry.approval`` (ADR-062) + ``registry.memory``
    # (ADR-063) only. Deliberately does NOT depend on ``registry.tektos``
    # (the agent plugin) so the change-approval UI stays reachable during
    # LLM/agent outages — a triage requirement per ADR-065 Option B.
    if registry.approval is None or registry.memory is None:
        missing = [
            name
            for name, val in (
                ("approval", registry.approval),
                ("memory", registry.memory),
            )
            if val is None
        ]
        registry.errors["tektos_ui"] = (
            f"tektos_ui depends on {missing}; one or more failed to boot"
        )
    else:
        try:
            from plugins.tektos.ui.executor import NopExecutor
            from plugins.tektos.ui.server import build_tektos_ui_app

            _tektos_ui_executor = NopExecutor()
            _tektos_ui_app = build_tektos_ui_app(
                approval_resolver=registry.approval,
                memory=registry.memory,
                executor=_tektos_ui_executor,
            )
            registry.tektos_ui = _tektos_ui_app
            registry.tektos_ui_executor = _tektos_ui_executor
            # Guard against duplicate mounts when lifespan is re-entered
            # (TestClient reuses the module-level `app` across many tests).
            if not any(getattr(r, "path", "") == "/tektos-ui" for r in app.routes):
                app.mount("/tektos-ui", _tektos_ui_app)
        except Exception as exc:  # noqa: BLE001
            registry.errors["tektos_ui"] = f"{type(exc).__name__}: {exc}"

    # --- Stage 8.7 (ADR-114 D8) orchestrator router mount -----------------
    # ADR-114 D8: ``build_orchestrator_router(bundle)`` mounts under
    # ``/tektos/api/orchestrator`` with no internal prefix; a missing bundle
    # degrades per-route to 503 (ADR-101 shape) via the factory's
    # ``_guard_bundle()``. The bundle only exists after the boot slots run,
    # so the mount happens here in the lifespan (same pattern as the
    # ``/tektos-ui`` mount above) rather than at import time. Mounted before
    # the static ``/`` mount so the routes resolve first.
    try:
        from plugins.tektos.orchestrator.engine import OrchestratorBundle as _OrchBundle
        from plugins.tektos.orchestrator.api import build_orchestrator_router

        _orch_bundle = getattr(registry, "tektos_orchestrator", None)
        if not isinstance(_orch_bundle, _OrchBundle):
            _orch_bundle = None
        if not any(
            getattr(r, "path", "") == "/tektos/api/orchestrator/stats"
            for r in app.routes
        ):
            app.include_router(
                build_orchestrator_router(
                    _orch_bundle,
                    hierarchical=getattr(registry, "tektos_hierarchical", None),
                    long_running=getattr(registry, "tektos_long_running", None),
                ),
                prefix="/tektos/api/orchestrator",
            )
    except Exception as _orch_router_exc:  # noqa: BLE001
        import logging as _orch_router_logging

        _orch_router_logging.getLogger(__name__).warning(
            "tektos orchestrator router not mounted: %s", _orch_router_exc
        )
        registry.errors["tektos_orchestrator_router"] = (
            f"{type(_orch_router_exc).__name__}: {_orch_router_exc}"
        )

    # --- Stage 1 GUI mount: serve Next.js static export at kernel root "/"
    # (ADR-067). Runs last so `/api/*`, `/health`, `/openapi.json`, `/docs`,
    # `/gnosis-gate`, `/tektos-ui`, `/tektos/api/orchestrator` all resolve
    # first via Starlette's insertion-order routing. Skipped silently if
    # `ui/out` is absent.
    try:
        from pathlib import Path as _KosmosPath
        from fastapi.staticfiles import StaticFiles as _KosmosStaticFiles

        _kosmos_ui_out = _KosmosPath(__file__).resolve().parent.parent / "ui" / "out"
        if _kosmos_ui_out.is_dir() and not any(
            getattr(r, "name", "") == "kosmos-ui" for r in app.routes
        ):
            app.mount(
                "/",
                _KosmosStaticFiles(directory=str(_kosmos_ui_out), html=True),
                name="kosmos-ui",
            )
    except Exception as _kosmos_ui_exc:  # noqa: BLE001
        import logging as _kosmos_logging

        _kosmos_logging.getLogger(__name__).warning(
            "Kosmos UI not mounted at /: %s", _kosmos_ui_exc
        )

    yield

    # ADR-121 (Stage 11.5): stop the sustained-thermal watchdog before
    # anything else so it can't race the event-bus teardown.
    if getattr(registry, "thermal_watchdog", None) is not None:
        try:
            await registry.thermal_watchdog.stop()
        except Exception:  # noqa: BLE001
            pass

    # Shutdown — stop plugins/engines then close the event bus.
    if registry.tektos is not None:
        try:
            await registry.tektos.stop()
        except Exception:  # noqa: BLE001
            pass

    if registry.llm is not None:
        try:
            await registry.llm.close()
        except Exception:  # noqa: BLE001
            pass

    # Stage 1.5 Wave E (ADR-071): cancel the zetesis drain task and
    # unsubscribe before stopping the plugin so no queue.put() happens
    # after we've torn down the ring buffer.
    if registry._zetesis_drain_task is not None:
        try:
            registry._zetesis_drain_task.cancel()
            try:
                await registry._zetesis_drain_task
            except BaseException:  # noqa: BLE001,S110
                # asyncio.CancelledError inherits from BaseException on
                # Python 3.8+. Swallow all shutdown-path exceptions
                # (including cancellation) — this is best-effort teardown.
                pass
        except Exception:  # noqa: BLE001
            pass
    if (
        registry.event_bus is not None
        and registry.zetesis_report_queue is not None
    ):
        try:
            registry.event_bus.unsubscribe(
                "zetesis.research.completed",
                registry.zetesis_report_queue,
            )
        except Exception:  # noqa: BLE001
            pass

    if registry.zetesis is not None:
        try:
            await registry.zetesis.stop()
        except Exception:  # noqa: BLE001
            pass

    if registry.phrouros is not None:
        try:
            await registry.phrouros.stop()
        except Exception:  # noqa: BLE001
            pass

    if registry.trace_feed is not None:
        try:
            await registry.trace_feed.close()
        except Exception:  # noqa: BLE001
            pass

    if registry.event_bus is not None:
        try:
            await registry.event_bus.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Kosmos Kernel", version="6.12.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Tektos-Ultima API gateway (ADR-109, Stage 9.1) + kernel-wide CSP
# ---------------------------------------------------------------------------
# Pure kernel-side proxy to the standalone Tektos API (TEKTOS_ULTIMA_API_URL,
# default http://127.0.0.1:8020). No registry coupling: it degrades to 503
# envelopes per-request, never at boot (ADR-109 D2).
#
# The ADR-091 iframe proxy / postMessage bridge was retired in Stage 9.5
# (ADR-113) once native parity was verified. The frame-ancestors CSP
# middleware survived the retirement as a kernel-wide hardening measure
# (moved into kernel/tektos_ultima_gateway.py).
try:
    from kernel.tektos_ultima_gateway import (
        KosmosCSPMiddleware as _KosmosCSPMiddleware,
        build_tektos_ultima_gateway_router as _build_tektos_ultima_gateway_router,
    )

    app.include_router(_build_tektos_ultima_gateway_router())
    app.add_middleware(_KosmosCSPMiddleware)
except Exception as _tektos_ultima_gateway_exc:  # noqa: BLE001
    import logging as _tektos_ultima_gateway_logging

    _tektos_ultima_gateway_logging.getLogger(__name__).warning(
        "Tektos-Ultima gateway not mounted: %s", _tektos_ultima_gateway_exc
    )
    registry.errors["tektos_ultima_gateway"] = (
        f"{type(_tektos_ultima_gateway_exc).__name__}: "
        f"{_tektos_ultima_gateway_exc}"
    )

# ---------------------------------------------------------------------------
# Tektos-Ultima data-service status endpoints (ADR-117, Stage 11.1)
# ---------------------------------------------------------------------------
# Kernel-native probes for the five data-service dashboard cards (Neo4j,
# Postgres, Redis/Valkey, Hindsight, Qdrant). They probe the services
# directly (env-driven, ADR-109 D2 pattern — no registry coupling),
# replacing the ADR-109 gateway proxy to the retired :8020 standalone
# Tektos API. Always HTTP 200 with a ``healthy`` flag so the card can
# distinguish unreachable / auth_failed / unconfigured.
try:
    from kernel.tektos_data_services import (
        build_tektos_data_services_router as _build_tektos_data_services_router,
    )

    app.include_router(_build_tektos_data_services_router())
except Exception as _tektos_data_services_exc:  # noqa: BLE001
    import logging as _tektos_data_services_logging

    _tektos_data_services_logging.getLogger(__name__).warning(
        "Tektos data-services router not mounted: %s",
        _tektos_data_services_exc,
    )
    registry.errors["tektos_data_services"] = (
        f"{type(_tektos_data_services_exc).__name__}: "
        f"{_tektos_data_services_exc}"
    )


# ---------------------------------------------------------------------------
# Kill-switch middleware — ADR-069 (Stage 1.5 Wave C)
#
# Asymmetric gate: when ``registry.suspended`` is True, allow /health,
# /api/kernel/** (introspection), /api/kernel/resume (the escape hatch),
# WebSocket handshakes, and HEAD/OPTIONS. Everything else under /api/**
# returns 503 with ``{detail: "kernel suspended", suspended_at, reason}``
# so the UI stays observable and can offer resume without waiting on a
# hung mutating call.
# ---------------------------------------------------------------------------


_KILL_SWITCH_ALWAYS_ALLOW_PATHS: frozenset[str] = frozenset({
    "/health",
})
_KILL_SWITCH_ALLOW_PREFIXES: tuple[str, ...] = (
    "/api/kernel/",           # introspection + /kill, /resume, /suspension
    "/api/events/ws",         # WS bridge issues its own frames
    "/api/algedonic/ws",      # legacy alias, if mounted
)


@app.middleware("http")
async def _kill_switch_middleware(request: Request, call_next):
    if not registry.suspended:
        return await call_next(request)

    method = request.method.upper()
    if method in ("HEAD", "OPTIONS"):
        return await call_next(request)

    path = request.url.path

    # Static UI + non-API paths are ALWAYS served — the suspended banner
    # UI must remain reachable so the operator can resume from the browser.
    # We only gate mutating `/api/**` traffic (with kernel introspection
    # + WS handshakes explicitly allow-listed below).
    if not path.startswith("/api/"):
        return await call_next(request)

    if path in _KILL_SWITCH_ALWAYS_ALLOW_PATHS:
        return await call_next(request)
    if any(path.startswith(p) for p in _KILL_SWITCH_ALLOW_PREFIXES):
        return await call_next(request)

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=503,
        content={
            "detail": "kernel suspended",
            "suspended_at": registry.suspended_at,
            "reason": registry.suspend_reason,
        },
    )


# ---------------------------------------------------------------------------
# WebSocket event-bus bridge — ADR-061
# ---------------------------------------------------------------------------


WS_DEFAULT_EVENT_TYPES: tuple[str, ...] = (
    "phrouros.anomaly.detected",     # ADR-034
    "zetesis.research.started",      # ADR-056
    "zetesis.research.completed",    # ADR-056
    "kernel.suspended",              # ADR-069
    "kernel.resumed",                # ADR-069
)

_WS_QUEUE_MAXSIZE: int = 256


# ---------------------------------------------------------------------------
# Health + kernel introspection
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok" if not registry.errors else "degraded",
        "boot_errors": registry.errors,
        "subsystems": {
            "notification": registry.notification is not None,
            "frontend_contract": registry.frontend_contract is not None,
            "resource": registry.resource is not None,
            "event_bus": registry.event_bus is not None,
            "approval": registry.approval is not None,
            "phrouros": registry.phrouros is not None,
            "zetesis": registry.zetesis is not None,
            "llm": registry.llm is not None,
            "memory": registry.memory is not None,
            "tektos": registry.tektos is not None,
            "tektos_ui": registry.tektos_ui is not None,
            "immune": registry.immune is not None,
        },
    }

@app.get("/api/kernel/schema")
async def kernel_schema() -> dict[str, Any]:
    fc = registry.frontend_contract
    if fc is None:
        raise HTTPException(503, detail=registry.errors.get("frontend_contract"))
    schema = await fc.render_kernel_schema()
    return _dataclass_to_dict(schema)


@app.get("/api/kernel/routes")
async def kernel_routes() -> list[dict[str, Any]]:
    fc = registry.frontend_contract
    if fc is None:
        raise HTTPException(503, detail=registry.errors.get("frontend_contract"))
    manifest = await fc.get_route_manifest()
    return [_dataclass_to_dict(r) for r in manifest]


@app.get("/api/kernel/panels")
async def kernel_panels() -> list[dict[str, Any]]:
    fc = registry.frontend_contract
    if fc is None:
        raise HTTPException(503, detail=registry.errors.get("frontend_contract"))
    panels = await fc.get_panel_manifest()
    return [_dataclass_to_dict(p) for p in panels]


@app.get("/api/kernel/plugins")
async def kernel_plugins() -> list[dict[str, Any]]:
    fc = registry.frontend_contract
    if fc is None:
        raise HTTPException(503, detail=registry.errors.get("frontend_contract"))
    plugins = await fc.list_plugins()
    return [_dataclass_to_dict(p) for p in plugins]


@app.get("/api/kernel/design-tokens")
async def kernel_design_tokens() -> dict[str, Any]:
    fc = registry.frontend_contract
    if fc is None:
        raise HTTPException(503, detail=registry.errors.get("frontend_contract"))
    return dict(await fc.get_design_tokens())


# ---------------------------------------------------------------------------
# Kill-switch endpoints — ADR-069 (Stage 1.5 Wave C)
# ---------------------------------------------------------------------------


async def _publish_kernel_event(event_type: str, payload: dict[str, Any]) -> None:
    """Best-effort publish of a kernel lifecycle envelope.

    Failure to publish (event bus down, malformed envelope) never blocks the
    suspend/resume transition itself. Errors are silently swallowed — the
    registry state is the authoritative source of truth; the WS frame is
    an observability nicety.
    """
    bus = registry.event_bus
    if bus is None:
        return
    try:
        from ports.event_envelope import EventEnvelope

        envelope = EventEnvelope(
            event_type=event_type,
            producer_plugin="kernel",
            payload=payload,
        )
        await bus.publish(envelope)
    except Exception:
        # Never let observability failure break the control action.
        pass


@app.post("/api/kernel/kill")
async def kernel_kill(request: Request) -> dict[str, Any]:
    """Soft-suspend the kernel per ADR-069 D1.

    Idempotent. Optional JSON body ``{reason?: str}`` is recorded verbatim.
    Returns ``{status: "suspended", suspended_at, reason}``. On transition
    (running → suspended), publishes a ``kernel.suspended`` envelope.
    """
    from datetime import datetime as _dt, timezone as _tz

    reason: str | None = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            raw = body.get("reason")
            if isinstance(raw, str) and raw.strip():
                reason = raw.strip()
    except Exception:
        # No body / not JSON — acceptable; reason stays None.
        pass

    was_running = not registry.suspended
    registry.suspended = True
    if was_running:
        registry.suspended_at = _dt.now(_tz.utc).isoformat()
        registry.suspend_reason = reason
        await _publish_kernel_event(
            "kernel.suspended",
            {
                "suspended_at": registry.suspended_at,
                "reason": registry.suspend_reason,
            },
        )
    return {
        "status": "suspended",
        "suspended_at": registry.suspended_at,
        "reason": registry.suspend_reason,
    }


@app.post("/api/kernel/resume")
async def kernel_resume() -> dict[str, Any]:
    """Clear kernel suspension per ADR-069 D2.

    Idempotent. Returns ``{status: "running", resumed_at}``. On transition
    (suspended → running), publishes a ``kernel.resumed`` envelope.
    """
    from datetime import datetime as _dt, timezone as _tz

    was_suspended = registry.suspended
    resumed_at = _dt.now(_tz.utc).isoformat()
    registry.suspended = False
    registry.suspended_at = None
    registry.suspend_reason = None
    if was_suspended:
        await _publish_kernel_event(
            "kernel.resumed",
            {"resumed_at": resumed_at},
        )
    return {"status": "running", "resumed_at": resumed_at}


@app.get("/api/kernel/suspension")
async def kernel_suspension_status() -> dict[str, Any]:
    """Read-only suspension state per ADR-069 D3. Never 503."""
    return {
        "suspended": registry.suspended,
        "suspended_at": registry.suspended_at,
        "reason": registry.suspend_reason,
    }


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


@app.get("/api/resources/balances")
async def resource_balances() -> dict[str, Any]:
    rp = registry.resource
    if rp is None:
        raise HTTPException(503, detail=registry.errors.get("resource"))
    from ports.resource import ResourceKind

    storage = getattr(rp, "_kernel_storage", None)
    out: dict[str, Any] = {}
    for kind in ResourceKind:
        bal = None
        if storage is not None and hasattr(storage, "get_balance"):
            try:
                bal = await storage.get_balance(kind)
            except Exception:
                bal = None
        out[kind.value] = (
            _dataclass_to_dict(bal) if bal is not None else None
        )
    return out


# ADR-066 D2 — resource queue passthrough


@app.get("/api/resources/queue")
async def resource_queue(
    kind: str, n: int = 5
) -> list[dict[str, Any]]:
    rp = registry.resource
    if rp is None:
        raise HTTPException(503, detail=registry.errors.get("resource"))
    from ports.resource import ResourceKind as _RK

    try:
        rk = _RK(kind)
    except ValueError as exc:
        valid = [m.value for m in _RK]
        raise HTTPException(
            400, detail=f"unknown kind {kind!r}; valid: {valid}"
        ) from exc
    if not isinstance(n, int) or n < 1 or n > 100:
        raise HTTPException(400, detail="'n' must be an int in [1, 100]")
    try:
        queued = await rp.peek(rk, n)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return [_dataclass_to_dict(q) for q in queued]


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


@app.get("/api/approvals")
async def approvals_list() -> list[dict[str, Any]]:
    ap = registry.approval
    if ap is None:
        raise HTTPException(503, detail=registry.errors.get("approval"))
    pending = await ap.list_pending()
    return [_dataclass_to_dict(r) for r in pending]


@app.get("/api/approvals/{approval_id}")
async def approval_get(approval_id: str) -> dict[str, Any]:
    ap = registry.approval
    if ap is None:
        raise HTTPException(503, detail=registry.errors.get("approval"))
    try:
        record = await ap.get_by_id(approval_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, detail=str(exc)) from exc
    return _dataclass_to_dict(record)


# ADR-062 — approval resolve endpoints


def _resolve_error_status(exc: BaseException) -> int:
    """Map an ``ApprovalResolverPort.resolve`` exception to an HTTP status.

    Class names are matched against Praxis APEX's error hierarchy
    without importing plugin modules from the kernel:

    - ``ApprovalNotFoundError`` → 404
    - ``InvalidTransitionError`` → 409 (already resolved)
    - ``ValueError`` → 400 (reject-without-reason etc.)
    - anything else → 500
    """
    name = type(exc).__name__
    if name == "ApprovalNotFoundError":
        return 404
    if name == "InvalidTransitionError":
        return 409
    if isinstance(exc, ValueError):
        return 400
    return 500


async def _read_optional_json(request: Request) -> dict[str, Any]:
    """Parse an optional JSON body. Empty body → ``{}``. Bad JSON → 400."""
    raw = await request.body()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, detail=f"invalid JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, detail="body must be a JSON object")
    return payload


@app.post("/api/approvals/{approval_id}/approve")
async def approval_approve(
    approval_id: str, request: Request
) -> dict[str, Any]:
    ap = registry.approval
    if ap is None:
        raise HTTPException(503, detail=registry.errors.get("approval"))
    body = await _read_optional_json(request)

    reason = body.get("reason")
    modifications = body.get("modifications")
    resolved_by = body.get("resolved_by", "user")

    if reason is not None and not isinstance(reason, str):
        raise HTTPException(400, detail="reason must be a string")
    if modifications is not None and not isinstance(modifications, dict):
        raise HTTPException(400, detail="modifications must be a JSON object")
    if not isinstance(resolved_by, str) or not resolved_by.strip():
        raise HTTPException(
            400, detail="resolved_by must be a non-empty string"
        )

    try:
        record = await ap.resolve(
            approval_id,
            True,
            reason=reason,
            modifications=modifications,
            resolved_by=resolved_by,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            _resolve_error_status(exc), detail=str(exc)
        ) from exc
    return _dataclass_to_dict(record)


@app.post("/api/approvals/{approval_id}/reject")
async def approval_reject(
    approval_id: str, request: Request
) -> dict[str, Any]:
    ap = registry.approval
    if ap is None:
        raise HTTPException(503, detail=registry.errors.get("approval"))
    body = await _read_optional_json(request)

    reason = body.get("reason")
    resolved_by = body.get("resolved_by", "user")

    if not isinstance(reason, str) or not reason.strip():
        raise HTTPException(
            400,
            detail="reject requires a non-empty 'reason' field",
        )
    if not isinstance(resolved_by, str) or not resolved_by.strip():
        raise HTTPException(
            400, detail="resolved_by must be a non-empty string"
        )

    try:
        record = await ap.resolve(
            approval_id,
            False,
            reason=reason,
            resolved_by=resolved_by,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            _resolve_error_status(exc), detail=str(exc)
        ) from exc
    return _dataclass_to_dict(record)


# ---------------------------------------------------------------------------
# Tektos — ADR-063
# ---------------------------------------------------------------------------


@app.post("/api/tektos/turn")
async def tektos_turn(request: Request) -> dict[str, Any]:
    """Drive one ``TektosAgent`` iteration.

    Body: ``{"content": <non-empty str>}``. Returns the resulting
    ``TektosStep`` as JSON. Serialized across concurrent requests via
    ``registry.tektos_agent_lock`` so a caller never sees
    ``TektosAgentAlreadyRunError`` from an overlapping request.
    """
    agent = registry.tektos_agent
    lock = registry.tektos_agent_lock
    if agent is None or lock is None:
        raise HTTPException(503, detail=registry.errors.get("tektos"))

    body = await _read_optional_json(request)
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(
            400, detail="'content' must be a non-empty string"
        )

    async with lock:
        try:
            agent.send_message(content)
            step = await agent.run()
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            # Bubble upstream adapter errors (Ollama unreachable, memory
            # write failure) as 502; the kernel is up but a dependency
            # failed. Class-name check keeps kernel-plugin decoupled.
            name = type(exc).__name__
            if name in {
                "TektosAgentNotStartedError",
                "TektosAgentAlreadyRunError",
                "TektosInvalidConfidenceError",
            }:
                raise HTTPException(400, detail=str(exc)) from exc
            raise HTTPException(502, detail=f"{name}: {exc}") from exc

    return _dataclass_to_dict(step)


# ---------------------------------------------------------------------------
# Gnosis retrieval surrogate — ADR-064
#
# Three read-only routes projecting the kernel-owned ``MemoryPort``
# retrieval surface as ``/api/gnosis/*``. The Gnosis plugin does not
# exist yet (Phase 3 territory); ADR-051 blessed the surrogate pattern
# at the adapter layer and ADR-064 extends it to an HTTP surface so the
# GUI Gnosis tab can render corpus facts + provenance + timestamps
# against real data ahead of ``plugins/gnosis/`` landing.
# ---------------------------------------------------------------------------

import re as _gnosis_re

_GNOSIS_EVENT_ID_RE = _gnosis_re.compile(r"^[A-Za-z0-9._:\-]+$")

# Static manifest of landed corpora. ADR-051 locates corpus loading at
# the adapter fixtures layer, not at a live registry, so the router
# enumerates them here. Updates require the same-day edit to this
# constant when a new corpus lands under ``adapters/memory/dozerdb/corpora/``.
GNOSIS_CORPORA_MANIFEST: list[dict[str, Any]] = [
    {
        "name": "synthetic-lifeline",
        "provenance_predicate": "synthetic-lifeline-v1",
        "summary": "10 hand-authored R.M. Holston lifeline facts (Stage 4.2 DoD anchor).",
        "stage": "4.2",
    },
    {
        "name": "humanities-cidoc-sample",
        "provenance_predicate": "humanities-cidoc-sample-v1",
        "summary": "5 CIDOC-CRM Buddhist text facts; illustrative not scholarly.",
        "stage": "4.2",
    },
    {
        "name": "rigpa-export",
        "provenance_predicate": "rigpa-export-fixture-v1",
        "summary": "Rigpa-LMS JSONL export (fixtures fallback: 20 events 2024-05→2024-12); env-gated by KOSMOS_RIGPA_EXPORT_PATH.",
        "stage": "4.2",
    },
    {
        "name": "superpowers",
        "provenance_predicate": "superpowers-kb",
        "summary": "github.com/obra/superpowers skills at pinned SHA; MIT.",
        "stage": "4.4",
    },
    {
        "name": "humanities-bilara",
        "provenance_predicate": "humanities-bilara",
        "summary": "github.com/suttacentral/bilara-data translations + Pali roots + actors at pinned SHA; CC0-1.0 + public-domain.",
        "stage": "4.5",
    },
]

# Fast lookup: corpus name -> provenance predicate. Used by the query
# route to translate the ``corpus`` filter into a payload-side match.
_GNOSIS_CORPUS_BY_NAME: dict[str, dict[str, Any]] = {
    c["name"]: c for c in GNOSIS_CORPORA_MANIFEST
}

# Idempotent-write error class names (ADR-007 class-name matching).
# ``MemoryWriteBlocked`` is the AMG guard rejection; the neo4j driver
# raises ``ClientError`` for constraint violations. Anything else
# indicates a real seeder failure and gets recorded.
_GNOSIS_SEED_IGNORABLE = frozenset(
    {
        "MemoryWriteBlocked",
        "ClientError",
        "ConstraintValidationFailed",
    }
)


def _gnosis_hit_to_dict(hit: Any) -> dict[str, Any]:
    """Serialize a ``MemoryHit`` for the wire.

    ``as_of`` becomes ISO-8601 or ``None``. Payload is passed through
    verbatim — the adapter layer already sanitizes nested maps via the
    Stage 6.5.6 backend fix.
    """
    as_of = getattr(hit, "as_of", None)
    return {
        "id": getattr(hit, "id", None),
        "payload": getattr(hit, "payload", None),
        "score": getattr(hit, "score", None),
        "as_of": as_of.isoformat() if as_of is not None else None,
    }


@app.get("/api/gnosis/query")
async def gnosis_query(
    q: str,
    as_of: str | None = None,
    limit: int = 20,
    corpus: str | None = None,
) -> dict[str, Any]:
    """Query the temporal graph via ``MemoryPort.query_temporal``.

    Query params:

    - ``q`` — required, non-empty query text.
    - ``as_of`` — optional ISO-8601 timestamp with timezone; when set,
      hits with ``as_of > cutoff`` are filtered by the temporal index.
    - ``limit`` — bounded to ``[1, 100]``; default 20.
    - ``corpus`` — optional corpus name from the manifest; restricts
      hits to facts whose payload ``provenance`` equals the manifest
      ``provenance_predicate`` for that corpus.
    """
    if registry.memory is None:
        raise HTTPException(503, detail=registry.errors.get("memory"))
    if not isinstance(q, str) or not q.strip():
        raise HTTPException(400, detail="'q' must be a non-empty string")
    if not (1 <= limit <= 100):
        raise HTTPException(400, detail="'limit' must be in [1, 100]")

    provenance_filter: str | None = None
    if corpus is not None:
        entry = _GNOSIS_CORPUS_BY_NAME.get(corpus)
        if entry is None:
            raise HTTPException(
                400,
                detail=(
                    f"unknown 'corpus' {corpus!r}; valid: "
                    f"{sorted(_GNOSIS_CORPUS_BY_NAME.keys())}"
                ),
            )
        provenance_filter = entry["provenance_predicate"]

    parsed_as_of = None
    if as_of is not None:
        try:
            from datetime import datetime as _dt

            parsed_as_of = _dt.fromisoformat(as_of)
        except ValueError as exc:
            raise HTTPException(
                400, detail=f"'as_of' must be ISO-8601: {exc}"
            ) from exc
        if parsed_as_of.tzinfo is None:
            raise HTTPException(
                400, detail="'as_of' must be timezone-aware"
            )

    try:
        # When ``corpus`` is set we widen the raw limit aggressively so
        # post-filtering still returns a full page even when the query
        # text ranks a different corpus higher, then clip.
        raw_limit = (
            min(100, max(limit * 10, 50)) if provenance_filter else limit
        )
        hits = await registry.memory.query_temporal(
            q, as_of=parsed_as_of, limit=raw_limit
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Upstream adapter failure (Graphiti unreachable, Cypher error).
        # Class-name matching preserves ADR-007.
        raise HTTPException(
            502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc

    if provenance_filter is not None:
        filtered = []
        for h in hits:
            payload = getattr(h, "payload", None) or {}
            # Graphiti dedupes entity edges across episodes, so a hit
            # may span multiple source corpora. Match membership in the
            # plural ``provenances`` set surfaced by the adapter; fall
            # back to the singular ``provenance`` field for adapters
            # that only expose one source.
            provenances = payload.get("provenances") or []
            if not isinstance(provenances, (list, tuple, set)):
                provenances = []
            singular = payload.get("provenance")
            if provenance_filter in provenances or singular == provenance_filter:
                filtered.append(h)
                if len(filtered) >= limit:
                    break
        hits = filtered

    return {"hits": [_gnosis_hit_to_dict(h) for h in hits]}


@app.get("/api/gnosis/corpora")
async def gnosis_corpora() -> dict[str, Any]:
    """Return the manifest of landed corpora with live fact counts (ADR-064).

    ``fact_count`` prefers the seeder count for this boot; when the
    seeder didn't run it degrades to the static corpus size.
    ``last_ingested_at`` is the seeder's UTC ISO timestamp or ``None``.
    """
    # Static fallback counts — corpora sizes at build time.
    try:
        from adapters.memory.dozerdb.corpora import ALL_CORPORA

        static_counts = {c.name: len(c.facts) for c in ALL_CORPORA}
    except Exception:  # noqa: BLE001
        static_counts = {}

    seeded = registry.gnosis_corpus_counts
    out: list[dict[str, Any]] = []
    for entry in GNOSIS_CORPORA_MANIFEST:
        row = dict(entry)
        row["fact_count"] = seeded.get(
            entry["name"], static_counts.get(entry["name"], 0)
        )
        row["last_ingested_at"] = registry.gnosis_last_seeded_at
        out.append(row)
    return {"corpora": out}


@app.get("/api/gnosis/stats")
async def gnosis_stats() -> dict[str, Any]:
    """Return top-line Gnosis dashboard numbers (ADR-064).

    Computed from the static ``ALL_CORPORA`` tuple — not a graph query.
    Safe to call even when memory is down.
    """
    try:
        from adapters.memory.dozerdb.corpora import ALL_CORPORA
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            500, detail=f"corpora import failed: {type(exc).__name__}: {exc}"
        ) from exc

    subjects: set[str] = set()
    predicates: set[str] = set()
    earliest = None
    latest = None
    total = 0
    for corpus in ALL_CORPORA:
        for fact in corpus.facts:
            total += 1
            subjects.add(fact.subject)
            predicates.add(fact.predicate)
            if earliest is None or fact.as_of < earliest:
                earliest = fact.as_of
            if latest is None or fact.as_of > latest:
                latest = fact.as_of

    return {
        "total_facts": total,
        "corpora_count": len(ALL_CORPORA),
        "distinct_subjects": len(subjects),
        "distinct_predicates": len(predicates),
        "earliest_as_of": earliest.isoformat() if earliest else None,
        "latest_as_of": latest.isoformat() if latest else None,
        "seeded_this_boot": dict(registry.gnosis_corpus_counts),
        "last_seeded_at": registry.gnosis_last_seeded_at,
    }


@app.get("/api/gnosis/event/{event_id}")
async def gnosis_event(event_id: str) -> dict[str, Any]:
    """Fetch a single memory event by id.

    ``event_id`` must match ``^[A-Za-z0-9._:-]+$``. Returns the hit's
    ``id`` / ``payload`` / ``score`` / ``as_of`` on success, 404 on
    miss, 400 on malformed id.
    """
    if registry.memory is None:
        raise HTTPException(503, detail=registry.errors.get("memory"))
    if not _GNOSIS_EVENT_ID_RE.match(event_id):
        raise HTTPException(400, detail="malformed 'event_id'")

    try:
        hits = await registry.memory.query_temporal(
            f"event_id:{event_id}", limit=1
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc

    for hit in hits:
        if getattr(hit, "id", None) == event_id:
            return _gnosis_hit_to_dict(hit)
    raise HTTPException(404, detail=f"event {event_id!r} not found")


# ---------------------------------------------------------------------------
# Gnosis graph endpoints — ADR-070 (Stage 1.5 Wave D)
#
# Three read-only routes projecting MemoryPort triples + Zetesis provenance
# chains into a node-link graph shape consumable by cytoscape.js. Zero new
# ports, zero plugin coupling; all kernel-owned per ADR-057. Zero-trust
# discipline preserved: ``provenance`` and ``confidence`` are surfaced on
# every node and edge, never fabricated. When Zetesis is absent, endpoints
# degrade gracefully to MemoryPort-only.
# ---------------------------------------------------------------------------

import base64 as _b64
import json as _graph_json

_GRAPH_ID_RE = _gnosis_re.compile(r"^[A-Za-z0-9._:\-]+$")

# CIDOC-CRM predicate prefixes for edge-kind classification. Predicates
# that match are surfaced verbatim; non-CIDOC predicates still pass through
# unchanged (spec says verbatim). Kept as data, not code, so future corpora
# can add kinds without touching this file.
_ZETESIS_EDGE_KIND_CITED_BY = "zetesis_cited_by"
_ZETESIS_EDGE_KIND_EVIDENCES = "zetesis_evidences"
_ZETESIS_NODE_KIND = "zetesis_report"


def _graph_encode_cursor(offset: int) -> str:
    """Encode an opaque pagination cursor.

    Hides the offset-based implementation from clients; keeps the door
    open to swap in keyset pagination without breaking the wire format.
    """
    raw = _graph_json.dumps({"offset": int(offset)}, separators=(",", ":"))
    return _b64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip(
        "="
    )


def _graph_decode_cursor(cursor: str | None) -> int:
    """Decode an opaque pagination cursor to an offset. Missing or
    malformed cursors yield offset 0.
    """
    if not cursor:
        return 0
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = _b64.urlsafe_b64decode(cursor + pad).decode("utf-8")
        parsed = _graph_json.loads(raw)
        off = int(parsed.get("offset", 0))
        return max(0, off)
    except Exception:  # noqa: BLE001
        return 0


def _graph_provenance_matches(payload: dict[str, Any], predicate: str) -> bool:
    """Return True when a MemoryHit payload belongs to the given corpus
    provenance predicate. Mirrors the union-membership logic used by
    ``/api/gnosis/query``.
    """
    provenances = payload.get("provenances") or []
    if not isinstance(provenances, (list, tuple, set)):
        provenances = []
    singular = payload.get("provenance")
    return predicate in provenances or singular == predicate


async def _graph_fetch_memory_facts(
    corpus: str | None, cap: int
) -> list[dict[str, Any]]:
    """Pull raw MemoryPort facts for graph projection.

    ``cap`` bounds the raw pull; the caller is responsible for slicing
    the projected node/edge list per cursor and limit. Uses the same
    ``query_temporal`` bulk-fetch pattern the surrogate already relies on
    (an empty-ish query text returns most-recent-first hits from the
    adapter's default ranker).
    """
    if registry.memory is None:
        return []
    provenance_filter: str | None = None
    if corpus is not None:
        entry = _GNOSIS_CORPUS_BY_NAME.get(corpus)
        if entry is None:
            raise HTTPException(
                400,
                detail=(
                    f"unknown 'corpus' {corpus!r}; valid: "
                    f"{sorted(_GNOSIS_CORPUS_BY_NAME.keys())}"
                ),
            )
        provenance_filter = entry["provenance_predicate"]
    try:
        hits = await registry.memory.query_temporal("*", limit=min(cap, 500))
    except ValueError:
        # An empty-string / wildcard query is not supported by every
        # adapter. Fall back to an empty result; callers still surface
        # the graph with Zetesis-only nodes if any.
        return []
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    out: list[dict[str, Any]] = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        if not isinstance(payload, dict):
            continue
        if provenance_filter is not None and not _graph_provenance_matches(
            payload, provenance_filter
        ):
            continue
        subject = payload.get("subject")
        predicate = payload.get("predicate")
        object_ = payload.get("object") or payload.get("object_")
        if not (
            isinstance(subject, str)
            and isinstance(predicate, str)
            and isinstance(object_, str)
        ):
            continue
        provenance = payload.get("provenance")
        confidence = payload.get("confidence")
        as_of = getattr(hit, "as_of", None)
        out.append(
            {
                "event_id": getattr(hit, "id", None),
                "subject": subject,
                "predicate": predicate,
                "object": object_,
                "provenance": provenance if isinstance(provenance, str) else None,
                "confidence": (
                    float(confidence)
                    if isinstance(confidence, (int, float))
                    else None
                ),
                "as_of": as_of.isoformat() if as_of is not None else None,
            }
        )
    return out


def _graph_zetesis_reports(
    corpus: str | None,
) -> list[dict[str, Any]]:
    """Snapshot the Zetesis ring buffer for graph projection.

    ``corpus`` filter: Zetesis reports have their own synthetic provenance
    predicate (``"zetesis:<trial_id>"``); when a specific MemoryPort corpus
    is filtered we exclude Zetesis unless the caller explicitly asked for
    the Zetesis pseudo-corpus (not yet defined in Wave D — always include
    when ``corpus is None``, always exclude otherwise).
    """
    if corpus is not None:
        return []
    reports = getattr(registry, "zetesis_reports", None)
    if not reports:
        return []
    out: list[dict[str, Any]] = []
    for r in list(reports):
        # Support both ResearchReport dataclasses and plain dict envelopes
        # (event bus subscribers may push either shape).
        trial_id = getattr(r, "trial_id", None) or (
            r.get("trial_id") if isinstance(r, dict) else None
        )
        query = getattr(r, "query", None) or (
            r.get("query") if isinstance(r, dict) else ""
        )
        error = getattr(r, "error", None) if not isinstance(r, dict) else r.get(
            "error"
        )
        citations = getattr(r, "citations", None) or (
            r.get("citations") if isinstance(r, dict) else ()
        )
        memory_event_id = getattr(r, "memory_event_id", None) or (
            r.get("memory_event_id") if isinstance(r, dict) else None
        )
        if not isinstance(trial_id, str) or not trial_id:
            continue
        out.append(
            {
                "trial_id": trial_id,
                "query": query if isinstance(query, str) else "",
                "error": error if isinstance(error, str) else None,
                "citations": tuple(c for c in (citations or ()) if isinstance(c, str)),
                "memory_event_id": (
                    memory_event_id if isinstance(memory_event_id, str) else None
                ),
            }
        )
    return out


def _graph_project_nodes_edges(
    facts: list[dict[str, Any]], reports: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dedupe subjects/objects and materialize typed edges.

    Returns ``(nodes, edges)`` — both lists are stable-sorted for
    deterministic pagination.
    """
    node_index: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def _upsert(label: str, kind: str, prov: str | None, conf: float | None) -> str:
        node_id = f"{kind}:{label}"
        existing = node_index.get(node_id)
        if existing is None:
            node_index[node_id] = {
                "id": node_id,
                "label": label,
                "kind": kind,
                "provenance": prov,
                "confidence": conf,
            }
        return node_id

    for f in facts:
        s_id = _upsert(f["subject"], "subject", f["provenance"], f["confidence"])
        o_id = _upsert(f["object"], "object", f["provenance"], f["confidence"])
        edges.append(
            {
                "id": f"{f['event_id']}" if f.get("event_id") else f"{s_id}--{f['predicate']}--{o_id}",
                "source": s_id,
                "target": o_id,
                "kind": f["predicate"],
                "label": f["predicate"],
                "provenance": f["provenance"],
                "confidence": f["confidence"],
                "as_of": f["as_of"],
            }
        )

    for r in reports:
        conf = 1.0 if r["error"] is None else 0.0
        rprov = f"zetesis:{r['trial_id']}"
        z_id = _upsert(
            r["query"][:80] if r["query"] else r["trial_id"],
            _ZETESIS_NODE_KIND,
            rprov,
            conf,
        )
        # Overwrite id so it's stable across reports with identical query
        # prefixes but different trial_ids.
        node_index[z_id]["id"] = f"zetesis:{r['trial_id']}"
        node_index[f"zetesis:{r['trial_id']}"] = node_index.pop(z_id)
        stable_z_id = f"zetesis:{r['trial_id']}"
        for citation in r["citations"]:
            c_id = _upsert(citation, "object", rprov, conf)
            edges.append(
                {
                    "id": f"{stable_z_id}--cited--{c_id}",
                    "source": stable_z_id,
                    "target": c_id,
                    "kind": _ZETESIS_EDGE_KIND_CITED_BY,
                    "label": _ZETESIS_EDGE_KIND_CITED_BY,
                    "provenance": rprov,
                    "confidence": conf,
                    "as_of": None,
                }
            )
        if r["memory_event_id"]:
            edges.append(
                {
                    "id": f"{stable_z_id}--ev--{r['memory_event_id']}",
                    "source": stable_z_id,
                    "target": f"event:{r['memory_event_id']}",
                    "kind": _ZETESIS_EDGE_KIND_EVIDENCES,
                    "label": _ZETESIS_EDGE_KIND_EVIDENCES,
                    "provenance": rprov,
                    "confidence": conf,
                    "as_of": None,
                }
            )

    nodes = sorted(node_index.values(), key=lambda n: n["id"])
    edges.sort(key=lambda e: e["id"])
    return nodes, edges


def _graph_validate_limit(limit: int) -> int:
    if not (1 <= limit <= 100):
        raise HTTPException(400, detail="'limit' must be in [1, 100]")
    return limit


@app.get("/api/gnosis/graph/nodes")
async def gnosis_graph_nodes(
    corpus: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Paginated node list. See ADR-070 D1.

    When the MemoryPort adapter is not yet booted, degrade gracefully to an
    empty page. This matches the AgentTrace/Governance pattern: a panel that
    always renders on the shell must not 5xx on cold-boot before its
    dependencies are up, or the browser logs a console error.
    """
    if registry.memory is None:
        return {"nodes": [], "next_cursor": None}
    _graph_validate_limit(limit)
    offset = _graph_decode_cursor(cursor)
    facts = await _graph_fetch_memory_facts(corpus, cap=500)
    reports = _graph_zetesis_reports(corpus)
    nodes, _edges = _graph_project_nodes_edges(facts, reports)
    page = nodes[offset : offset + limit]
    next_cursor = (
        _graph_encode_cursor(offset + limit) if offset + limit < len(nodes) else None
    )
    return {"nodes": page, "next_cursor": next_cursor}


@app.get("/api/gnosis/graph/edges")
async def gnosis_graph_edges(
    corpus: str | None = None,
    node_id: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Paginated edge list, optionally filtered to edges incident on a
    specific ``node_id``. See ADR-070 D1.

    Degrades to an empty page when MemoryPort is not booted (see
    ``gnosis_graph_nodes``).
    """
    if registry.memory is None:
        return {"edges": [], "next_cursor": None}
    _graph_validate_limit(limit)
    if node_id is not None and not _GRAPH_ID_RE.match(node_id.split(":", 1)[-1]):
        raise HTTPException(400, detail="malformed 'node_id'")
    offset = _graph_decode_cursor(cursor)
    facts = await _graph_fetch_memory_facts(corpus, cap=500)
    reports = _graph_zetesis_reports(corpus)
    _nodes, edges = _graph_project_nodes_edges(facts, reports)
    if node_id is not None:
        edges = [e for e in edges if e["source"] == node_id or e["target"] == node_id]
    page = edges[offset : offset + limit]
    next_cursor = (
        _graph_encode_cursor(offset + limit) if offset + limit < len(edges) else None
    )
    return {"edges": page, "next_cursor": next_cursor}


@app.get("/api/gnosis/graph/node/{node_id:path}")
async def gnosis_graph_node(node_id: str) -> dict[str, Any]:
    """Single node detail with first 20 neighbor summaries.
    See ADR-070 D1.
    """
    if registry.memory is None:
        raise HTTPException(503, detail=registry.errors.get("memory"))
    # ``node_id`` is a colon-prefixed synthetic id; the payload after the
    # first colon must satisfy the id regex.
    tail = node_id.split(":", 1)[-1] if ":" in node_id else node_id
    if not _GRAPH_ID_RE.match(tail):
        raise HTTPException(400, detail="malformed 'node_id'")
    facts = await _graph_fetch_memory_facts(None, cap=500)
    reports = _graph_zetesis_reports(None)
    nodes, edges = _graph_project_nodes_edges(facts, reports)
    match = next((n for n in nodes if n["id"] == node_id), None)
    if match is None:
        raise HTTPException(404, detail=f"node {node_id!r} not found")
    neighbors = [e for e in edges if e["source"] == node_id or e["target"] == node_id]
    neighbor_summaries = []
    for e in neighbors[:20]:
        other_id = e["target"] if e["source"] == node_id else e["source"]
        other = next((n for n in nodes if n["id"] == other_id), None)
        if other is not None:
            neighbor_summaries.append(
                {
                    "id": other["id"],
                    "label": other["label"],
                    "kind": other["kind"],
                    "via_edge_kind": e["kind"],
                }
            )
    return {
        "node": match,
        "neighbor_count": len(neighbors),
        "neighbors": neighbor_summaries,
    }


# ---------------------------------------------------------------------------
# ADR-071 Stage 1.5 Wave E — Louvain community assignment + annotation write.
# ---------------------------------------------------------------------------


def _compute_louvain_communities(
    facts: list[dict[str, Any]],
    reports: list[dict[str, Any]],
) -> tuple[dict[str, int], float]:
    """Deterministic Louvain community assignment via networkx.

    Builds an undirected weighted graph from the provided facts + reports
    (same projection used by the graph endpoints), runs
    ``networkx.algorithms.community.louvain_communities`` with
    ``seed=42``, and returns ``({node_id: community_id}, modularity)``.
    On empty input returns ``({}, 0.0)``.
    """
    nodes, edges = _graph_project_nodes_edges(facts, reports)
    if not nodes:
        return ({}, 0.0)

    import networkx as _nx
    from networkx.algorithms.community import louvain_communities as _louvain
    from networkx.algorithms.community import modularity as _modularity

    g = _nx.Graph()
    for n in nodes:
        g.add_node(n["id"])
    for e in edges:
        # Skip degenerate self-loops (would confuse modularity computation).
        if e["source"] == e["target"]:
            continue
        g.add_edge(e["source"], e["target"])

    if g.number_of_edges() == 0:
        # Isolated nodes — each is its own singleton community.
        assignments = {n["id"]: idx for idx, n in enumerate(nodes)}
        return (assignments, 0.0)

    communities = _louvain(g, seed=42)
    assignments: dict[str, int] = {}
    for cid, member_set in enumerate(communities):
        for node_id in member_set:
            assignments[str(node_id)] = cid
    try:
        q = float(_modularity(g, communities))
    except Exception:  # noqa: BLE001
        q = 0.0
    return (assignments, q)


@app.get("/api/gnosis/graph/communities")
async def read_gnosis_graph_communities(
    corpus: str | None = None,
) -> dict[str, Any]:
    """Return Louvain community assignments for the current graph.

    ADR-071 D1: deterministic (`seed=42`) server-side community detection.
    Degrades to an empty page (HTTP 200) when ``registry.memory is None``
    to match the Wave D list-endpoint cold-boot behavior (ADR-070 D7).
    """
    from datetime import datetime as _dt, timezone as _tz

    memory = getattr(registry, "memory", None)
    now_iso = _dt.now(_tz.utc).isoformat()

    if memory is None:
        return {
            "algorithm": "louvain",
            "communities": {},
            "modularity": 0.0,
            "corpus": corpus,
            "computed_at": now_iso,
            "node_count": 0,
            "edge_count": 0,
            "degraded": True,
        }

    facts = await _graph_fetch_memory_facts(corpus, cap=500)
    reports = _graph_zetesis_reports(corpus)
    nodes, edges = _graph_project_nodes_edges(facts, reports)
    assignments, modularity = _compute_louvain_communities(facts, reports)

    return {
        "algorithm": "louvain",
        "communities": assignments,
        "modularity": modularity,
        "corpus": corpus,
        "computed_at": now_iso,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "degraded": False,
    }


class _GnosisAnnotationBody(BaseModel):
    """Request body for ``POST /api/gnosis/graph/annotate`` (ADR-071 D2).

    All four required fields must be non-empty strings (or a float in the
    unit interval for ``confidence``). ``node_id`` is the subject the
    annotation attaches to.
    """

    node_id: str = Field(..., min_length=1)
    provenance: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    note: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


@app.post("/api/gnosis/graph/annotate")
async def annotate_gnosis_node(
    body: _GnosisAnnotationBody,
) -> dict[str, Any]:
    """Persist a user annotation as a MemoryPort event.

    ADR-071 D2: wraps ``MemoryPort.write_event(predicate='annotation', ...)``
    with defense-in-depth zero-trust validation. Pydantic checks the
    request layer; the port layer runs ``validate_zero_trust_write``
    again and raises ``ValueError`` on any violation (surfaced as 400).
    """
    from datetime import datetime as _dt, timezone as _tz

    memory = getattr(registry, "memory", None)
    if memory is None:
        raise HTTPException(
            503,
            detail=registry.errors.get("memory") or "memory unavailable",
        )

    try:
        memory_event_id = await memory.write_event(
            subject=body.node_id,
            predicate="annotation",
            object=body.note,
            provenance=body.provenance,
            confidence=body.confidence,
            attributes={
                "annotation_kind": "user",
                "reason": body.reason,
            },
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # AMG block or adapter-level failure. Surface class name so the UI
        # can render a targeted error state.
        raise HTTPException(
            409, detail=f"{type(exc).__name__}: {exc}"
        ) from exc

    return {
        "memory_event_id": str(memory_event_id),
        "written_at": _dt.now(_tz.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Semantic memory search (ADR-075 D2) — thin HTTP wrapper around
# ``MemoryPort.search_semantic``. Kernel-owned per ADR-057 so any
# plugin can hit the same route; degrades to an empty ``hits`` list
# when the semantic lane is not booted (both EmbeddingsPort and
# VectorPort must be present).
# ---------------------------------------------------------------------------


class _MemorySearchSemanticBody(BaseModel):
    """Request body for ``POST /api/memory/search-semantic`` (ADR-075 D2).

    ``query`` is the natural-language search string; ``corpus`` selects
    the logical vector collection (``None`` uses the adapter's default);
    ``limit`` caps returned hits; ``min_score`` filters cosine
    similarity below the given floor.
    """

    query: str = Field(..., min_length=1)
    corpus: str | None = Field(default=None)
    limit: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


@app.post("/api/memory/search-semantic")
async def memory_search_semantic(
    body: _MemorySearchSemanticBody,
) -> dict[str, Any]:
    """Semantic nearest-neighbour retrieval over ``MemoryPort``.

    Wraps ``MemoryPort.search_semantic``. Returns 200 with an empty
    ``hits`` list when the semantic lane is not booted — lets the UI
    render a coherent degraded state instead of a hard 503.
    """
    memory = getattr(registry, "memory", None)
    if memory is None:
        return {
            "hits": [],
            "query": body.query,
            "corpus": body.corpus,
            "degraded": True,
            "reason": registry.errors.get("memory") or "memory unavailable",
        }

    try:
        hits = await memory.search_semantic(
            body.query,
            corpus=body.corpus,
            limit=body.limit,
            min_score=body.min_score,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc

    return {
        "hits": [
            {
                "id": h.id,
                "payload": h.payload,
                "score": h.score,
                "as_of": h.as_of.isoformat() if h.as_of else None,
            }
            for h in hits
        ],
        "query": body.query,
        "corpus": body.corpus,
        "degraded": False,
    }


# ---------------------------------------------------------------------------
# Ollama status (ADR-068 D1) — passthrough to Ollama /api/ps for the top-bar
# model-swap indicator. Hardcoded ``vram_capacity_bytes`` reflects Colossus's
# RTX 5090 (32 GiB). Never fabricates a shape when Ollama is unreachable —
# 502 with class-name preserved on transport failure so the UI can render a
# degraded state instead of a fake reading.
# ---------------------------------------------------------------------------


_COLOSSUS_VRAM_CAPACITY_BYTES: int = 34_359_738_368  # 32 GiB, RTX 5090


@app.get("/api/ollama/status")
async def ollama_status() -> dict[str, Any]:
    """Return the currently-loaded Ollama model + resident VRAM/RAM footprint.

    Passthrough to Ollama ``GET /api/ps``. When no model is loaded (idle
    Ollama), returns ``{model: None, size_vram: 0, size_ram: 0,
    vram_capacity_bytes: <capacity>}``. When Ollama is unreachable, 502.
    """
    if registry.llm is None:
        raise HTTPException(503, detail=registry.errors.get("llm"))

    import httpx

    # ADR-116: registry.llm is a FailoverLLMAdapter — the Ollama lane is its
    # _fallback sub-adapter. Read its base URL; the getattr keeps a
    # pre-ADR-116 OllamaAdapter working (which has _base_url itself).
    ollama_lane = getattr(registry.llm, "_fallback", None) or registry.llm
    base_url = getattr(ollama_lane, "_base_url", "http://127.0.0.1:11434")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}/api/ps")
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc

    models = payload.get("models") or []
    if not models:
        return {
            "model": None,
            "size_vram": 0,
            "size_ram": 0,
            "vram_capacity_bytes": _COLOSSUS_VRAM_CAPACITY_BYTES,
        }
    m = models[0]
    size_vram = int(m.get("size_vram") or 0)
    size_total = int(m.get("size") or 0)
    return {
        "model": m.get("name") or m.get("model"),
        "size_vram": size_vram,
        "size_ram": max(size_total - size_vram, 0),
        "vram_capacity_bytes": _COLOSSUS_VRAM_CAPACITY_BYTES,
    }


# ---------------------------------------------------------------------------
# Active LLM status (ADR-118) — the top-bar model indicator must report the
# LLM the kernel is ACTUALLY routing through (ADR-116 failover lanes), not
# whichever model Ollama happens to have loaded (often just the embedder).
# Envelope: {healthy, backend, lane, model, base_url, vram_used_bytes,
# vram_capacity_bytes, detail}. VRAM is the real GPU reading from
# nvidia-smi when available; None (never fabricated) when it is not.
# ---------------------------------------------------------------------------

_GPU_VRAM_CACHE_TTL_S = 5.0
_gpu_vram_cache: tuple[float, int, int] | None = None  # (ts, used, total)


async def _gpu_vram_bytes() -> tuple[int, int] | None:
    """Real GPU memory (used, total) in bytes via nvidia-smi, 5s cached."""
    global _gpu_vram_cache
    import time

    now = time.monotonic()
    if _gpu_vram_cache and now - _gpu_vram_cache[0] < _GPU_VRAM_CACHE_TTL_S:
        return (_gpu_vram_cache[1], _gpu_vram_cache[2])
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        line = out.decode("utf-8", "replace").strip().splitlines()[0]
        used_mb, total_mb = (int(x) for x in line.split(","))
        MiB = 1024 * 1024
        _gpu_vram_cache = (now, used_mb * MiB, total_mb * MiB)
        return (used_mb * MiB, total_mb * MiB)
    except Exception:  # noqa: BLE001 — GPU reading is best-effort
        return None


@app.get("/api/llm/status")
async def llm_status() -> dict[str, Any]:
    """Report the ACTIVE kernel LLM lane (ADR-116 failover) + real GPU VRAM.

    ``backend`` is the transport actually routing requests: ``llama.cpp``
    (:8090 primary) or ``ollama`` (:11434 fallback, active only after a
    failover pin). ``model`` is that lane's default model — what the user
    should see in the top bar. Always 200 with ``healthy``; 503 only when
    no LLM registry entry exists at all.
    """
    if registry.llm is None:
        return {
            "healthy": False,
            "backend": None,
            "lane": None,
            "model": None,
            "base_url": None,
            "vram_used_bytes": None,
            "vram_capacity_bytes": _COLOSSUS_VRAM_CAPACITY_BYTES,
            "detail": registry.errors.get("llm") or "no LLM adapter",
        }

    # ADR-116: registry.llm is a FailoverLLMAdapter with .active_backend
    # ("primary" | "fallback"), ._primary (LlamaSwapAdapter), ._fallback
    # (Ollama adapter). Fall back to plain-adapter attributes if the
    # failover wrapper is ever removed.
    active = getattr(registry.llm, "active_backend", "primary")
    primary = getattr(registry.llm, "_primary", None)
    fallback = getattr(registry.llm, "_fallback", None)
    if active == "fallback" and fallback is not None:
        lane_adapter, backend, lane = fallback, "ollama", "fallback"
    else:
        lane_adapter, backend, lane = primary or registry.llm, "llama.cpp", "primary"

    model = getattr(lane_adapter, "_default_model", None)
    base_url = getattr(lane_adapter, "_base_url", None)

    vram = await _gpu_vram_bytes()

    # ADR-119: the full lane catalog — the kernel's OWN model list, built
    # from live adapter state (no :8020 proxy). The UI's Models card reads
    # this instead of the retired standalone catalog.
    models: list[dict[str, Any]] = []
    for lane_name, adapter in (
        ("primary", getattr(registry.llm, "_primary", None)),
        ("fallback", getattr(registry.llm, "_fallback", None)),
    ):
        if adapter is None:
            continue
        m = getattr(adapter, "_default_model", None)
        b = getattr(adapter, "_base_url", None)
        models.append(
            {
                "id": m,
                "name": m,
                "lane": lane_name,
                "backend": (
                    "llama.cpp" if lane_name == "primary" else "ollama"
                ),
                "endpoint": b,
                "active": (active == "primary") == (lane_name == "primary"),
                "recommended": lane_name == "primary",
            }
        )

    return {
        "healthy": True,
        "backend": backend,
        "lane": lane,
        "model": model,
        "base_url": base_url,
        "vram_used_bytes": vram[0] if vram else None,
        "vram_capacity_bytes": (
            vram[1] if vram else _COLOSSUS_VRAM_CAPACITY_BYTES
        ),
        "detail": f"{backend} @ {base_url}" if base_url else backend,
        "models": models,
    }


# ---------------------------------------------------------------------------
# Inference status (ADR-120) — kernel-native probe of the ACTIVE LLM lane.
# Replaces the ADR-109 gateway proxy to :8020/api/inference/status. Envelope
# mirrors the old standalone shape so the UI card parses it unchanged:
# {status: active|degraded, model, base_url, health: ok|error,
# llm_available}. The probe is real (≤3 s bound): llama.cpp lane →
# GET /v1/models, Ollama lane → GET /api/version.
# ---------------------------------------------------------------------------


@app.get("/api/inference/status")
async def inference_status() -> dict[str, Any]:
    """Probe the active inference lane and report the kernel's LLM health."""
    base: dict[str, Any] = {
        "status": "degraded",
        "model": None,
        "base_url": None,
        "health": "error",
        "llm_available": False,
    }
    if registry.llm is None:
        return base

    active = getattr(registry.llm, "active_backend", "primary")
    primary = getattr(registry.llm, "_primary", None)
    fallback = getattr(registry.llm, "_fallback", None)
    if active == "fallback" and fallback is not None:
        lane_adapter, probe_path = fallback, "/api/version"
    else:
        lane_adapter, probe_path = (primary or registry.llm), "/v1/models"

    model = getattr(lane_adapter, "_default_model", None)
    base_url = getattr(lane_adapter, "_base_url", None)
    out = {**base, "model": model, "base_url": base_url}
    if not base_url:
        return out

    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}{probe_path}")
            resp.raise_for_status()
        out.update(status="active", health="ok", llm_available=True)
    except Exception:  # noqa: BLE001 — lane down is a degraded reading, not a 500
        pass
    return out


@app.get("/api/thermal/status")
async def thermal_status() -> dict[str, Any]:
    """ADR-121 (Stage 11.5): kernel-native thermal snapshot.

    Replaces the ADR-109 gateway proxy to :8020. Serves the watchdog's
    in-memory snapshot (the :8020-shaped envelope the card already
    parses). If the watchdog is off (CI / env-gated) we degrade to a
    one-shot ``nvidia-smi`` read so the card still shows real temps.
    """
    watchdog = registry.thermal_watchdog
    if watchdog is not None:
        return watchdog.snapshot()
    # Degrade path: no watchdog — one-shot read, no rule enforcement.
    import asyncio as _asyncio

    from kernel.tektos_thermal_watchdog import _read_cpu, _read_gpu

    gpu_temp, gpu_power, gpu_clock = await _asyncio.to_thread(_read_gpu)
    cpu_temp = await _asyncio.to_thread(_read_cpu)
    action = "relax" if (gpu_temp is None or gpu_temp < 75.0) else "hold"
    reason = (
        f"temp {gpu_temp:.0f}°C" if gpu_temp is not None else "no GPU data"
    )
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gpu": {
            "temperature": gpu_temp,
            "power_limit": 400,
            "clock_mhz": gpu_clock,
            "power_draw_w": gpu_power,
            "action": action,
            "reason": reason,
            "cooldown": {
                "active": False,
                "threshold_c": 75.0,
                "sustain_s": 60.0,
                "seconds_over": 0.0,
                "arming": False,
            },
        },
        "cpu": {
            "temperature": cpu_temp,
            "status": "normal" if cpu_temp is None or cpu_temp < 70 else "elevated",
            "action": "CPU within safe operating range",
        },
        "regulation_count": 0,
        "history": [],
    }


# ---------------------------------------------------------------------------
# Immune status (ADR-122, Stage 11.6) — kernel-native, reads the LIVE
# registry.immune (TektosImmuneAdapter, KOSMOS_IMMUNE=on). The old card
# proxied :8020/api/immune/health — a system-health composite (gpu/context/
# loop_safety/inference/threat_level scores) the kernel does not track.
# This serves what the kernel's immune port actually IS: a scan-on-request
# detector registry. Envelope mirrors the :8020 keys (overall, status,
# active_threats, uptime_seconds) so the existing parseCard works; adds a
# `detectors` array + `scans` counter the card can surface. Always 200.
# ---------------------------------------------------------------------------

_KERNEL_BOOT_TS = time.monotonic()  # set at import; uptime of this kernel


@app.get("/api/immune/health")
async def immune_health() -> dict[str, Any]:
    """Kernel-native immune health — the live detector registry."""
    adapter = registry.immune
    now = datetime.now(timezone.utc)

    if adapter is None or not adapter.is_healthy():
        # Adapter not booted (KOSMOS_IMMUNE=off) or unhealthy — report it,
        # never 500. The card renders this as "degraded", not "down".
        return {
            "overall": 0.0,
            "status": "degraded",
            "components": {},
            "active_threats": 0,
            "resolved_threats": 0,
            "uptime_seconds": round(time.monotonic() - _KERNEL_BOOT_TS, 1),
            "detectors": [],
            "detail": "ImmunePort offline (KOSMOS_IMMUNE=off or boot failed)",
            "timestamp": now.isoformat(),
        }

    try:
        infos = await adapter.list_detectors()
    except Exception:  # noqa: BLE001 — list_detectors raising = degraded
        infos = ()

    detectors = [
        {
            "name": d.name,
            "severity_ceiling": (
                d.severity_ceiling.value
                if hasattr(d.severity_ceiling, "value")
                else str(d.severity_ceiling)
            ),
            "description": d.description,
        }
        for d in infos
    ]

    return {
        "overall": 1.0,
        "status": "healthy",
        "components": {},  # kernel port has no per-component scoring
        "active_threats": 0,  # scan-on-request: no persistent threat ledger
        "resolved_threats": 0,
        "uptime_seconds": round(time.monotonic() - _KERNEL_BOOT_TS, 1),
        "detectors": detectors,
        "detail": f"{len(detectors)} detectors registered",
        "timestamp": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Memory status (ADR-123, Stage 11.7) — kernel-native, reads the LIVE
# registry.memory (DozerDbMemoryAdapter, KOSMOS_MEMORY_BACKEND=dozerdb).
# The old card proxied :8020/api/memory/stats — a 4-tier cognitive store
# (working/long_term/procedural + hemisphere balance) the kernel does not
# implement. The kernel's memory port is a graph of MemoryEvent nodes in
# Neo4j. Envelope: {healthy, backend, memory_events, entities, quarantined,
# errors, timestamp}. Counts are real Cypher; a failed count is None (never
# fabricated). Always 200.
# ---------------------------------------------------------------------------


@app.get("/api/memory/stats")
async def memory_stats() -> dict[str, Any]:
    """Kernel-native memory corpus stats — real Neo4j counts."""
    adapter = registry.memory
    now = datetime.now(timezone.utc)

    backend = "none"
    if adapter is not None:
        backend = "dozerdb" if adapter.is_healthy() else "dozerdb (unhealthy)"
        try:
            s = await adapter.stats()
        except Exception as exc:  # noqa: BLE001 — never 500
            return {
                "healthy": False,
                "backend": backend,
                "memory_events": None,
                "entities": None,
                "quarantined": None,
                "errors": [f"stats(): {type(exc).__name__}"],
                "timestamp": now.isoformat(),
            }
    else:
        s = None

    return {
        "healthy": bool(s and s["healthy"]),
        "backend": backend,
        "memory_events": s["memory_events"] if s else None,
        "entities": s["entities"] if s else None,
        "quarantined": s["quarantined"] if s else None,
        "errors": (s or {}).get("errors", []),
        "timestamp": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# RAG status (ADR-124, Stage 11.8) — kernel-native.
# The old card proxied :8020/api/rag/status, whose stats carried a
# top_k/similarity_threshold/query_count the kernel does not track
# (retrieval params are per-query, and the kernel keeps no query ledger).
# The kernel's RAG pipeline is real and live: registry.embeddings
# (ADR-124 D1: llama.cpp qwen3-embedding-0.6b on :8091 — CPU-only by
# design, keeps the RTX 5090's 32 GB free for the 27B lane on :8090)
# + registry.vector (Qdrant). Envelope keeps the
# old card's top-level `status` + `stats.has_embedder/has_retriever` so the
# health logic reads the same way, and replaces the fabricated counters with
# REAL Qdrant collection/point counts. Always 200.
# ---------------------------------------------------------------------------

_RAG_QDRANT_DEFAULT_URL = "http://127.0.0.1:6333"


async def _rag_qdrant_counts() -> dict[str, Any]:
    """Collections + total points against KOSMOS_QDRANT_URL (default :6333).

    Same env contract as the ADR-117 data-services Qdrant probe
    (`/healthz` first, then `/collections`, then per-collection
    `points_count`). A failed probe yields healthy=False with the existing
    counters left at None — never a fabricated number.
    """
    import httpx

    base_url = (
        os.environ.get("KOSMOS_QDRANT_URL") or _RAG_QDRANT_DEFAULT_URL
    ).rstrip("/")
    out: dict[str, Any] = {
        "url": base_url,
        "healthy": False,
        "collections": None,
        "points": None,
        "error": None,
    }
    api_key = os.environ.get("KOSMOS_QDRANT_API_KEY")
    headers = {"api-key": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=2.0, headers=headers) as client:
            resp = await client.get(f"{base_url}/healthz")
            if resp.status_code != 200:
                out["error"] = f"HTTP {resp.status_code} on /healthz"
                return out
            out["healthy"] = True
            colls = await client.get(f"{base_url}/collections")
            if colls.status_code != 200:
                out["error"] = f"HTTP {colls.status_code} on /collections"
                return out
            names = [
                c.get("name")
                for c in (colls.json().get("result", {}).get("collections") or [])
                if isinstance(c, dict) and c.get("name")
            ]
            out["collections"] = len(names)
            total = 0
            for name in names:
                cresp = await client.get(f"{base_url}/collections/{name}")
                if cresp.status_code == 200:
                    total += int(
                        cresp.json().get("result", {}).get("points_count") or 0
                    )
            out["points"] = total
    except Exception as exc:  # noqa: BLE001 — probe MUST NOT raise
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


@app.get("/api/rag/status")
async def rag_status() -> dict[str, Any]:
    """Kernel-native RAG pipeline status — real embedder + vector store."""
    now = datetime.now(timezone.utc)
    errors: list[str] = []

    embedder = registry.embeddings
    vector = registry.vector

    emb_info: dict[str, Any] = {
        "available": embedder is not None,
        "healthy": False,
        "model": None,
        "base_url": None,
    }
    if embedder is not None:
        emb_info["healthy"] = bool(embedder.is_healthy())
        # ADR-124 D1: model/base_url properties on the adapter.
        emb_info["model"] = getattr(embedder, "model", None)
        emb_info["base_url"] = getattr(embedder, "base_url", None)
        if not emb_info["healthy"]:
            errors.append("embedder unhealthy")

    vec_info: dict[str, Any] = {
        "available": vector is not None,
        "healthy": False,
    }
    if vector is not None:
        try:
            vec_info["healthy"] = bool(vector.is_healthy())
        except Exception as exc:  # noqa: BLE001 — never 500
            errors.append(f"vector is_healthy: {type(exc).__name__}")
        if not vec_info["healthy"]:
            errors.append("vector store unhealthy")

    qdrant = await _rag_qdrant_counts()
    if qdrant["error"]:
        errors.append(f"qdrant: {qdrant['error']}")

    has_embedder = emb_info["available"]
    has_retriever = vec_info["available"]
    healthy = (
        has_embedder
        and has_retriever
        and emb_info["healthy"]
        and vec_info["healthy"]
        and qdrant["healthy"]
    )

    return {
        "status": "initialized" if (has_embedder and has_retriever) else "degraded",
        "healthy": healthy,
        "embedder": emb_info,
        "vector": vec_info,
        "stats": {
            "has_embedder": has_embedder,
            "has_retriever": has_retriever,
            "indexed_count": qdrant["points"],
            "collections": qdrant["collections"],
        },
        "errors": errors,
        "timestamp": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# /api/skills/stats — ADR-125 (v2 Stage 11.9, skills family)
#
# The old card proxied :8020/api/skills/stats — the standalone engine's own
# skill manager (24 vendored skills with usage counters) that the kernel has
# no referent for. The kernel's real skills-adjacent surface is the Tektos
# Manager's archetype tracker (ADR-108): it watches Tektos task outcomes and
# flags recurring patterns as *skill candidates* (archetypes at threshold).
# The full donor skill registry (830 LOC) stays deferred per ADR-108 D9 —
# this endpoint reports the tracker live when the manager is wired
# (KOSMOS_TEKTOS_MANAGER=on) and says so honestly when it is not.
# ---------------------------------------------------------------------------


def _skills_archetype_dict(a: Any) -> dict[str, Any]:
    """Serialize one Archetype (duck-typed — plugin internals, ADR-007).

    ``at_threshold`` mirrors the tracker's skill-candidate semantics
    (``should_create_structure``): count hit threshold AND no permanent
    structure exists yet — consistent with ``get_archetypes_at_threshold``.
    """
    count = getattr(a, "occurrence_count", 0) or 0
    thr = getattr(a, "threshold", 0) or 0
    return {
        "category": getattr(a, "category", None),
        "occurrence_count": count,
        "threshold": thr,
        "at_threshold": bool(count >= thr)
        and getattr(a, "permanent_structure_id", None) is None,
        "permanent_structure_id": getattr(a, "permanent_structure_id", None),
        "first_seen": getattr(a, "first_seen", None),
        "last_seen": getattr(a, "last_seen", None),
    }


@app.get("/api/skills/stats")
def skills_stats() -> dict[str, Any]:
    """Tektos skill-candidate status from the Manager archetype tracker.

    Always 200. ``manager.wired: false`` (default — the ADR-108 engine is
    off unless KOSMOS_TEKTOS_MANAGER=on) is a valid degraded state, not an
    error: the skill registry is explicitly deferred (ADR-108 D9), and the
    card says so instead of fabricating a count.
    """
    errors: list[str] = []
    manager = getattr(registry, "tektos_manager", None)
    wired = manager is not None

    archetypes: list[dict[str, Any]] = []
    at_threshold: list[dict[str, Any]] = []
    threshold: int | None = None
    total_events: int | None = None

    if wired:
        try:
            tracker = getattr(manager, "archetypes", None)
            if tracker is not None:
                threshold = getattr(tracker, "threshold", None)
                total_events = len(getattr(tracker, "events", []) or [])
                archetypes = [
                    _skills_archetype_dict(a)
                    for a in tracker.get_active_archetypes()
                ]
                at_threshold = [
                    _skills_archetype_dict(a)
                    for a in tracker.get_archetypes_at_threshold()
                ]
            else:
                errors.append("manager has no archetype tracker")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"tracker query failed: {type(exc).__name__}: {exc}")

    return {
        "status": "initialized" if wired else "degraded",
        "healthy": wired,
        "skills": {
            "registry": "deferred (ADR-108 D9)",
            "wired": wired,
            "archetypes": len(archetypes),
            "at_threshold": len(at_threshold),
            "threshold": threshold,
            "total_events": total_events,
            "archetype_list": archetypes[:20],
        },
        "errors": errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Praxis constitution (ADR-068 D2) — read-only integrity anchor for the
# GOVERNANCE panel. Lazily loads + verifies the constitution on first hit,
# then caches on ``registry.praxis_constitution``. A tamper failure at read
# time surfaces as 502 (never 500, never silently succeed).
# ---------------------------------------------------------------------------


@app.get("/api/praxis/constitution")
def praxis_constitution() -> dict[str, Any]:
    """Return the currently-loaded constitution artifact summary.

    Response: ``{version, sha256, ratified_at, title, article_count}``.
    ``sha256`` is over ``json_text`` (the byte sequence the signature was
    computed against). ``article_count`` = ``len(payload.get('policies', {}))``
    — at Stage 1.5 the genesis constitution ships zero policies; this is
    the honest number, not a placeholder.
    """
    cached = getattr(registry, "praxis_constitution", None)
    if cached is None:
        try:
            import hashlib

            from plugins.praxis.constitution.loader import ConstitutionLoader

            loader = ConstitutionLoader(verify_on_init=True)
            artifact = loader.artifact
            sha256 = hashlib.sha256(
                artifact.json_text.encode("utf-8")
            ).hexdigest()
            payload = artifact.payload
            cached = {
                "version": artifact.version_number,
                "sha256": sha256,
                "ratified_at": payload.get("ratified_at"),
                "title": payload.get("title"),
                "article_count": len(payload.get("policies") or {}),
            }
            registry.praxis_constitution = cached
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                502, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
    return cached


# ---------------------------------------------------------------------------
# Praxis APEX policies (ADR-068 D3) — read-only enumeration of the
# kernel-wide Tier-2 triggers from spec §14 (``plugins.praxis.apex.models
# .Trigger``). All triggers escalate to ``HUMAN_REQUIRED`` per ADR-033.
# This is a static classification surface at Stage 1.5 (matches the fact
# that ``EscalationPolicy`` is a pure classifier with no runtime state);
# when APEX grows plugin-registered policies, this endpoint gains them
# without a UI contract break.
# ---------------------------------------------------------------------------


@app.get("/api/praxis/apex/policies")
def praxis_apex_policies() -> list[dict[str, Any]]:
    """Return the kernel-wide Tier-2 escalation policy set.

    Response: ``list[{policy_id, name, tier, active_since}]`` sorted by
    ``policy_id``. ``active_since`` is the constitution's ``ratified_at``
    (all Tier-2 triggers are constitutional, ratified at genesis).
    """
    from plugins.praxis.apex.models import Trigger

    constitution = praxis_constitution()  # reuses cache; may raise 502
    active_since = constitution.get("ratified_at")
    return sorted(
        (
            {
                "policy_id": t.value,
                "name": t.name.replace("_", " ").title(),
                "tier": "HUMAN_REQUIRED",
                "active_since": active_since,
            }
            for t in Trigger
        ),
        key=lambda p: p["policy_id"],
    )


# ---------------------------------------------------------------------------
# Phrouros anomalies
# ---------------------------------------------------------------------------


@app.get("/api/phrouros/anomalies")
def phrouros_anomalies() -> list[dict[str, Any]]:
    if registry.phrouros is None:
        raise HTTPException(503, detail=registry.errors.get("phrouros"))
    return [_dataclass_to_dict(r) for r in registry.phrouros.list_records()]


# ---------------------------------------------------------------------------
# Zetesis research (SSE) — ADR-060
# ---------------------------------------------------------------------------


_SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _sse_event(event: str, data: Any) -> bytes:
    """Format one SSE frame.

    SSE spec: `event: <name>\n` optional; `data: <payload>\n` required;
    frame terminated by a blank line.
    """
    payload = json.dumps(_dataclass_to_dict(data), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _build_research_config(raw: Any) -> Any:
    """Coerce a client-supplied dict into a ``ZetesisResearchConfig``.

    Applied over the plugin's defaults via ``dataclasses.replace``.
    Unknown keys ignored (forward-compat). Invalid coercion raises
    ``ValueError`` — caller maps to 400.
    """
    from plugins.zetesis.plugin import ZetesisResearchConfig
    from ports.resource import PriorityClass

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("'config' must be a JSON object or omitted")

    valid_fields = {f.name for f in dataclasses.fields(ZetesisResearchConfig)}
    overrides: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in valid_fields:
            continue
        if k == "priority_class" and isinstance(v, str):
            try:
                overrides[k] = PriorityClass[v.upper()]
            except KeyError as exc:
                raise ValueError(
                    f"unknown priority_class {v!r}; "
                    f"valid: {[m.name for m in PriorityClass]}"
                ) from exc
            continue
        if k == "compute_budget":
            try:
                overrides[k] = Decimal(str(v))
            except (InvalidOperation, TypeError) as exc:
                raise ValueError(
                    f"compute_budget must be a number, got {v!r}"
                ) from exc
            continue
        if k in ("fact_anchor_urls", "rubric_lines") and v is not None:
            if not isinstance(v, (list, tuple)):
                raise ValueError(f"{k} must be a list of strings")
            overrides[k] = tuple(str(x) for x in v)
            continue
        overrides[k] = v

    return dataclasses.replace(ZetesisResearchConfig(), **overrides)


@app.post("/api/zetesis/research")
async def zetesis_research(request: Request) -> StreamingResponse:
    if registry.zetesis is None:
        raise HTTPException(503, detail=registry.errors.get("zetesis"))

    # Parse + validate synchronously so validation errors are 400, not
    # mid-stream error events.
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, detail=f"invalid JSON body: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, detail="request body must be a JSON object")
    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(400, detail="'query' must be a non-empty string")
    try:
        config = _build_research_config(body.get("config"))
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    trial_id = (
        getattr(config, "trial_id", "") or ""
    ).strip() or uuid.uuid4().hex
    # Always ensure the config carries the server-issued trial_id so the
    # plugin echoes it back on `ResearchReport.trial_id`.
    if config is None:
        from plugins.zetesis.plugin import ZetesisResearchConfig
        config = ZetesisResearchConfig(trial_id=trial_id)
    elif getattr(config, "trial_id", "") != trial_id:
        config = dataclasses.replace(config, trial_id=trial_id)

    plugin = registry.zetesis

    async def _stream() -> AsyncIterator[bytes]:
        yield _sse_event(
            "started",
            {
                "query": query,
                "trial_id": trial_id,
            },
        )
        try:
            report = await plugin.research(query, config=config)
        except Exception as exc:  # noqa: BLE001
            yield _sse_event(
                "error",
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "trial_id": trial_id,
                },
            )
            return
        yield _sse_event("completed", report)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ---------------------------------------------------------------------------
# Notification SLO health
# ---------------------------------------------------------------------------


@app.get("/api/notifications/health")
@app.get("/api/notifications/slo")  # ADR-066 D4 alias
async def notification_health() -> dict[str, Any]:
    n = registry.notification
    if n is None:
        raise HTTPException(503, detail=registry.errors.get("notification"))
    try:
        slo = await n.check_delivery_slo()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    payload = _dataclass_to_dict(slo)
    if not isinstance(payload, dict):
        return {"report": payload}
    return payload


# ADR-066 D1 — notification ack passthrough


@app.post("/api/notifications/{notification_id}/ack")
async def notification_ack(
    notification_id: str, request: Request
) -> dict[str, Any]:
    n = registry.notification
    if n is None:
        raise HTTPException(503, detail=registry.errors.get("notification"))
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, detail=f"invalid JSON body: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, detail="body must be a JSON object")
    sub = body.get("subscriber_id")
    if not isinstance(sub, str) or not sub.strip():
        raise HTTPException(
            400, detail="'subscriber_id' must be a non-empty string"
        )
    try:
        acked = await n.ack_receipt(notification_id, sub)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return {"acked": bool(acked)}


# ---------------------------------------------------------------------------
# WebSocket route
# ---------------------------------------------------------------------------


def _parse_ws_types(raw: str | None) -> tuple[str, ...]:
    """Parse the ``?types=a,b,c`` query string.

    Whitespace-tolerant. Empty tokens dropped. Duplicates deduplicated
    while preserving first-seen order.
    """
    if raw is None or not raw.strip():
        return WS_DEFAULT_EVENT_TYPES
    seen: dict[str, None] = {}
    for token in raw.split(","):
        t = token.strip()
        if t:
            seen.setdefault(t, None)
    return tuple(seen.keys()) or WS_DEFAULT_EVENT_TYPES


def _envelope_to_wire(envelope: Any) -> dict[str, Any]:
    """Serialize an :class:`EventEnvelope` for a wire frame."""
    return {
        "frame": "event",
        "envelope": _dataclass_to_dict(envelope),
    }


@app.websocket("/api/events/ws")
async def events_ws(ws: WebSocket) -> None:
    if registry.event_bus is None:
        # Close before accepting; matches WS handshake semantics.
        await ws.close(code=1011, reason="event_bus subsystem down")
        return

    types = _parse_ws_types(ws.query_params.get("types"))
    bus = registry.event_bus

    await ws.accept()
    await ws.send_json({"frame": "ready", "subscribed": list(types)})

    # One queue per event type; one forwarder task per queue.
    queues: list[tuple[str, asyncio.Queue[Any]]] = []
    for t in types:
        q = bus.subscribe(t, maxsize=_WS_QUEUE_MAXSIZE)
        queues.append((t, q))

    async def _forward(q: asyncio.Queue[Any]) -> None:
        while True:
            envelope = await q.get()
            await ws.send_json(_envelope_to_wire(envelope))

    forwarders = [asyncio.create_task(_forward(q)) for _, q in queues]

    async def _drain_client() -> None:
        # Consume (and ignore) client-sent frames so a client `close()`
        # surfaces promptly as `WebSocketDisconnect`.
        while True:
            await ws.receive_text()

    drain = asyncio.create_task(_drain_client())

    try:
        # Wait for any task to finish (usually _drain_client on
        # disconnect); an exception in a forwarder also unblocks here.
        done, pending = await asyncio.wait(
            [*forwarders, drain],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        for task in forwarders + [drain]:
            task.cancel()
    except Exception:  # noqa: BLE001
        for task in forwarders + [drain]:
            task.cancel()
    finally:
        for t, q in queues:
            try:
                bus.unsubscribe(t, q)
            except Exception:  # noqa: BLE001
                pass


# ADR-066 D3 — algedonic WebSocket push channel


class _WebSocketAlgedonicSink:
    """Kernel-scoped :class:`ports.notification.Sink` that forwards
    only algedonic-tier records to a single WebSocket client.

    Non-algedonic tiers are soft-dropped (``return True``) so the port
    doesn't record them as SLO breaches. Transport errors from the
    WebSocket surface as ``return False`` per the ``Sink`` contract.
    """

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def deliver(self, record: Any) -> bool:
        # Local import to avoid a top-of-file cycle with the notification
        # port's enum module (kept identical to other route handlers).
        from ports.notification import AlgedonicTier

        tier = getattr(record, "tier", None)
        if tier != AlgedonicTier.ALGEDONIC:
            return True  # soft-drop non-algedonic tiers
        try:
            await self._ws.send_json(
                {
                    "frame": "algedonic",
                    "record": _dataclass_to_dict(record),
                }
            )
        except Exception:  # noqa: BLE001
            return False
        return True

    async def close(self) -> None:
        # WebSocket lifetime is owned by the route handler; nothing to do.
        return None


@app.websocket("/api/algedonic/ws")
async def algedonic_ws(ws: WebSocket) -> None:
    n = registry.notification
    if n is None:
        await ws.close(code=1011, reason="notification subsystem down")
        return

    await ws.accept()
    await ws.send_json({"frame": "ready"})

    sink = _WebSocketAlgedonicSink(ws)
    try:
        n.register_sink(sink)
    except Exception as exc:  # noqa: BLE001
        await ws.close(code=1011, reason=f"sink register failed: {exc}")
        return

    async def _drain_client() -> None:
        # Consume (and ignore) client frames so a client close surfaces
        # promptly as WebSocketDisconnect.
        while True:
            await ws.receive_text()

    drain = asyncio.create_task(_drain_client())
    try:
        await drain
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        drain.cancel()
        try:
            n.unregister_sink(sink)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dataclass_to_dict(obj: Any) -> Any:
    """Best-effort coerce dataclass / mapping / iterable to JSON-safe dict.

    Handles frozen-slotted dataclasses (no `__dict__`), Decimal, datetime,
    enum, and nested containers. Kosmos value objects are almost all
    `@dataclass(frozen=True, slots=True)` so `dataclasses.fields()` is
    the reliable extraction path.
    """
    import dataclasses
    from decimal import Decimal

    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: _dataclass_to_dict(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
    if hasattr(obj, "isoformat"):  # datetime / date
        return obj.isoformat()
    if hasattr(obj, "value") and hasattr(obj, "name"):  # enum
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_dataclass_to_dict(v) for v in obj]
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return {
            k: _dataclass_to_dict(v)
            for k, v in vars(obj).items()
            if not k.startswith("_")
        }
    return obj

# --- KOSMOS_STAGE_1_GNOSIS_GATE_MOUNT (ADR-067) ---
# Stage 1 GUI mount: Gnosis Stage 4.6 gate is a distinct ASGI sub-app; every
# other GUI-required endpoint already lives at /api/* on this kernel app.
# See ADR-067 (Stage 1 GUI · kernel_ui_glue superseded).
try:
    from adapters.memory.dozerdb.gate.server import (
        build_stage_46_gate_app as _kosmos_build_stage_46_gate_app,
    )
    from adapters.memory.dozerdb.corpora import ALL_CORPORA as _KOSMOS_ALL_CORPORA

    if not any(getattr(r, "path", "") == "/gnosis-gate" for r in app.routes):
        app.mount("/gnosis-gate", _kosmos_build_stage_46_gate_app(corpora=_KOSMOS_ALL_CORPORA))
except Exception as _kosmos_gate_exc:  # noqa: BLE001
    import logging as _kosmos_logging

    _kosmos_logging.getLogger(__name__).warning(
        "Kosmos Gnosis gate not mounted at /gnosis-gate: %s", _kosmos_gate_exc
    )
# --- END KOSMOS_STAGE_1_GNOSIS_GATE_MOUNT ---

# --- BEGIN KOSMOS_STAGE_1_UI_MOUNT ---
# Stage 1 GUI mount is performed inside the lifespan (see below), *after*
# all sub-app mounts (`/tektos-ui`, `/gnosis-gate`) so those retain
# first-match priority. Module-scope mounting would prepend the static
# handler and shadow `/tektos-ui/*`. Left as a marker only.
# --- END KOSMOS_STAGE_1_UI_MOUNT ---
