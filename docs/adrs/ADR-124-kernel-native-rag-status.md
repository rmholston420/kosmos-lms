# ADR-124: kernel-native `/api/rag/status` + llama.cpp RAG embedder (Qdrant 768→1024 migration)

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.8 (endpoint split, RAG family)
- **Supersedes:** none (removes the ADR-109 gateway proxy for the RAG card; the Ollama nomic embeddings lane of ADR-073 stays in-tree but is no longer the RAG embedder)

## Context

The RAG card fetched `/api/rag/status` through the ADR-109 gateway proxy to
the retired `:8020` engine. Its envelope
(`indexed_count`, `query_count`, `top_k`, `similarity_threshold`,
`has_embedder`, `has_retriever`) was a fabrication surface: the kernel keeps
no query ledger and retrieval params are per-query, so the counters and
thresholds had no kernel referent.

Two further facts reframed the fix into a real pipeline change:

1. **User directive (2026-09-25):** the RAG embedder must be the llama.cpp
   qwen embedder on `:8091` (`qwen3-embedding-0.6b`), and the embedder must
   run **CPU-only, never on the GPU** (the RTX 5090's 32 GB is reserved for
   the 27B inference lane on `:8090`). The `llama-embedder-8091` systemd
   service already satisfies this (`build-cpu` binary, `--device none
   --cache-ram 0`) — verified, not changed.
2. **Dimension mismatch:** `qwen3-embedding-0.6b` emits **1024-dim**
   vectors (verified live against `:8091/v1/embeddings`); both live Qdrant
   collections (`rigpa_gnosis` 64 pts, `kosmos-memory-default` 4 pts) were
   **768-dim** (nomic/bge era). Qdrant hard-rejects upserts into a
   dimension-mismatched collection, so simply re-pointing the embedder
   would have silently broken the semantic write path on next restart.
   A migration was required.

## Decision

### D1 — new `LlamaEmbeddingsAdapter` + `registry.embeddings` re-point

New adapter `adapters/embeddings/llama/adapter.py` (OpenAI-compat
`/v1/embeddings` over httpx, batch-capable, lazy client). Env contract:
`KOSMOS_EMBEDDER_BASE_URL` (default `http://127.0.0.1:8091`),
`KOSMOS_EMBEDDER_MODEL` (default `qwen3-embedding-0.6b`). Accepts root or
pre-suffixed `/v1` base URLs. Exposes `model` / `base_url` properties,
`is_healthy()` (GET `/health`, never raises — ADR-023 rule 5), `embed()`,
`dimensions()` (measured from a live probe, cached).

`kernel/app.py::_boot_embeddings` now returns
`LlamaEmbeddingsAdapter()`, replacing the `OllamaEmbeddingsAdapter` boot.
The Ollama adapter remains in-tree (its contract suite is unchanged).

Live-verified: healthy, `dimensions()==1024`, single + batch embed
against the running `:8091` server.

### D2 — Qdrant 768→1024 re-embedding (data migration, one-shot)

Per user style: live over mocks. Backups of both collections (full
vectors + payloads, 68 points) were written to scratch **before** any
mutation. The running Qdrant build exposes no collection-rename endpoint
(POST/PUT `/collections/{name}/rename` → 404; the client library lacks the
method), so the migration used the portable path: delete → recreate at
1024-dim COSINE → re-embed from the backup payloads → upsert.

Text sources match the adapters' write paths exactly:
`rigpa_gnosis` embeds `payload["text"]` (donor Rigpa upserter shape);
`kosmos-memory-default` embeds `_payload_to_embed_text(payload)`
(subject|predicate|object + citation + attrs). Payloads gained
`embedding_model_id: qwen3-embedding-0.6b` and `embedding_dims: 1024`.

Result (verified via Qdrant REST after migration): `rigpa_gnosis`
dim=1024 points=64; `kosmos-memory-default` dim=1024 points=4. A live
cosine query ("Buddhist Tantra") returned semantically correct Rigpa
claims (Kuzu mirror test, Mahamudra) at 0.46/0.45.

### D3 — kernel-native `GET /api/rag/status`

Always-200 envelope:

```json
{"status": "initialized", "healthy": true,
 "embedder": {"available": true, "healthy": true,
              "model": "qwen3-embedding-0.6b",
              "base_url": "http://127.0.0.1:8091"},
 "vector": {"available": true, "healthy": true},
 "stats": {"has_embedder": true, "has_retriever": true,
           "indexed_count": 68, "collections": 2},
 "errors": [], "timestamp": "..."}
```

`indexed_count` and `collections` come from a real Qdrant REST probe
(`KOSMOS_QDRANT_URL`, `/healthz` → `/collections` → per-collection
`points_count`) — the same env contract as the ADR-117 data-services
probe. The fabricated `:8020` counters (`query_count`, `top_k`,
`similarity_threshold`) are **gone, not defaulted** (D5). A probe failure
leaves the counters `None` and records the error — never a fabricated
number. `registry.embeddings is None` or `registry.vector is None` →
`status: "degraded"`. Every failure path degrades; the endpoint never
500s.

### D4 — card re-point + parseCard rewrite

`ui/app/tektos-ultima/page.tsx`: RAG card `base: ""` (kernel-native).
parseCard "rag" renders the real shape: point count (or "index
unavailable" when the probe is down — null, never `0`), embedder model +
collection count, and either the real `errors[]` or the honest lane
description `qwen :8091 (CPU) · vector up/down`.

### D5 — honest metrics rule

The kernel has no RAG query ledger and retrieval params are per-query.
Any envelope field without a kernel referent is omitted (or `None`),
never back-filled with a plausible constant. This generalizes the
ADR-122 `components: {}` rule to the RAG family.

### D6 — bug fix: `RealQdrantBackend.is_healthy()` event-loop binding

The first live verification of `/api/rag/status` returned
`vector.healthy: false` although Qdrant was up and the same endpoint's
own REST probe reported it healthy. Root cause (reproduced in a minimal
script): the old sync probe ran `self._client.get_collections()` — an
`AsyncQdrantClient` — on a freshly spawned event loop. The client's HTTP
pool binds to the **first loop it touches** (the kernel's main loop at
boot); every subsequent probe on a different loop fails with "coroutine
was never awaited" → permanent false negative. Standalone scripts
succeeded (fresh process, single loop), which is why the bug survived to
a live endpoint.

Fix: the probe is now a plain synchronous HTTP GET on `/healthz` via
urllib — loop-free by construction (same endpoint the ADR-117 probe
uses). Verified: the exact failure repro (client bound to a running loop)
now returns healthy; `RuntimeWarning: coroutine never awaited` is gone;
vector contract suite + full kernel suite pass.

## Consequences

- The RAG write path is live and dimension-consistent: kernel embeds go
  out to `:8091` (CPU), land in 1024-dim Qdrant, and the 64-point Rigpa
  knowledge index is searchable end-to-end (smoke query above).
- GPU VRAM budget unchanged: embedder on CPU, 27B lane owns the 5090.
- `:8020` is now bypassed for every card family except
  skills/tools/plugins (the remaining Stage 11 slices).

## Verification

- 8/8 tests: `tests/kernel/test_stage_11_8_adr_124_rag_status.py`
  (llama adapter live tests against `:8091` — skip-clean when down —
  + envelope tests with faked registry and an unreachable/stubbed
  Qdrant).
- Full regression: kernel suite + vector contract + embeddings suites
  green (1 optional live-Ollama tier skipped by env).
- Live: `GET /api/rag/status` → `healthy: true`, real 68/2 counts.
- UI: `tsc --noEmit` clean (one pre-existing Playwright-spec error in an
  untouched file), `next build` succeeds.
