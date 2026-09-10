# Kosmos Known Issues

Running open list of unresolved bugs and blockers. Editable — but when resolved, move the entry into `DEBUG_LOG.md` as a closed diagnosis (with fix) and delete from here.

Use the `kosmos-log-maintenance` Perplexity Computer skill.

---

<!-- Example (delete when adding real entries)

### 2026-07-31 — llama-swap warm-swap intermittently exceeds 2s SLO

- **Blocks:** Stage 1.7 lock-in gate for ADR-009
- **Symptom:** ~1 in 20 swaps take 2.4–3.1s; expected < 2s
- **Attempted fixes:** raised llama-swap process priority (no effect); pinned to CPU cores 0–3 (partial improvement)
- **Next investigation:** check VRAM fragmentation between swaps; measure PCIe bandwidth headroom
- **Related DEBUG_LOG search terms:** "warm-swap", "llama-swap", "SLO"

-->

### 2026-07-30 — Pier 0.3.0 real-tier trajectory not written

- **Blocks:** no blockers (Stage-3 gate green via fake pier shim; real tier is env-gated `KOSMOS_STAGE_39_REAL_DEEPSWE=1` / `KOSMOS_STAGE_38_REAL_PIER=1`)
- **Symptom:** With real `datacurve-pier==0.3.0` installed, `pier run -p <task> --agent nop --env <env> --jobs-dir <dir>` exits `returncode=0` with empty stderr but writes no `trajectory.json`. `test_real_deepswe_first_task_runs_through_pier_on_colossus` fails; `test_real_pier_smoke_fixture_runs_on_colossus` skips (skip-inside-catch) with pier internal Traceback pointing at `pier/cli/jobs.py:773 in start`.
- **Attempted fixes:**
  - Renamed harness `--jobs-root` → `--jobs-dir` to match pier 0.3.0 CLI surface (fixed CLI-level flag rejection; unblocked fake-shim tests). Real tier still fails deeper inside pier itself.
- **Next investigation:**
  - Read `.venv/lib/python3.14/site-packages/pier/cli/jobs.py:773` and surrounding `start` implementation to see what config/schema pier 0.3.0 expects (JobConfig via `-c`?).
  - Try `pier run --config <yaml>` route with a minimal `JobConfig` YAML instead of raw flags — pier 0.3.0's help text hints `-c` is the "more granular" path.
  - Alternatively, investigate whether earlier pier version (0.2.x?) matched the original `--jobs-root` + trajectory-writing contract this harness was written against.
- **Related DEBUG_LOG search terms:** `pier`, `trajectory.json`, `PierTrialFailure`, `datacurve-pier`, `--jobs-dir`


### 2026-07-30 — ADR-010 ODR shim 6 (rubric_critique) + shim 7 (cove) silent no-ops

- **Blocks:** no blockers — Stage 6.3.8 structural finalize (shim 9) covers the coverage/overreach gap these shims were originally meant to fix. Rating floor of 5.67/6 achieved without them running.
- **Symptom:** Colossus 3-trial 6.3.8 run (2026-07-30) recorded `rubric_critique outcome=no_fenced_output` and `cove outcome=insufficient_claims claims_found=0` on every trial. Both shims run the LLM call but their post-processors extract zero usable output, so both shim bodies no-op silently. Behavior appears to predate 6.3.7 (was already occurring, just noticed after 6.3.8 fixed the leak class that was dominating attention).
- **Attempted fixes:** none yet.
- **Next investigation:**
  1. **rubric_critique** — `extract_rewritten_report` expects a fenced markdown block; the model is likely returning either an unfenced rewrite or a differently-fenced block. Log the raw LLM output on one trial, inspect the exact delimiters returned, and either (a) reconcile the parser to accept the observed shape, or (b) tighten the prompt to emit the exact expected fence. 10-line fix if it's a format mismatch; larger if the model is refusing the critique task entirely.
  2. **cove** — `cove.extract_claims` scans the report body for numbered or otherwise-structured claim sentences. If `current_report` at that point is loose bulleted markdown, the extractor finds no candidates. Confirm by logging the input `current_report` shape at the cove call site; if bullet-based, extend `extract_claims` to accept `- ` bullets as claim boundaries.
- **Related DEBUG_LOG search terms:** `rubric_critique`, `no_fenced_output`, `cove`, `insufficient_claims`, `extract_rewritten_report`, `extract_claims`.
- **Deferred to:** Stage 6.4.x or later. Not blocking the ADR-010 head-to-head (Stage 6.3.9 → head-to-head).

### 2026-07-30 — ADR-010 head-to-head re-comparison deferred (AREX-Turbo vs. tuned ODR)

- **Blocks:** no blockers. Stage 6.3 (proper) (Zetesis kernel wiring) proceeds with ODR-post-6.3.9 per ADR-055.
- **Symptom:** AREX-Turbo contender at `ops/benchmarks/adr_010/harness/arex.py` was rated 0/3 at Stage 6.2 (context-ceiling exhaustion before `<finish>`, aggregate 0.0/18). Stage 6.3.x tuning arc (structural-finalize shim, allow-list gate, rationale-preservation, label normalization) applied to ODR only. AREX has not been re-rated under the tuned finalize surface, so the ADR-055 ratification of ODR-post-6.3.9 as Zetesis's research inner loop is not a strict "tuned-vs-tuned" head-to-head result — it is a Stage-6.2-result-plus-Stage-6.3.x-tuning-arc-on-the-winner ratification.
- **Attempted fixes:** none. Deferred as a scoping decision at Stage 6.4 (2026-07-30 21:54 EDT) to unblock Zetesis Stage 6.3 (proper) wiring.
- **Next investigation:** when the re-comparison runs:
  1. Wire `enable_structural_finalize=True` into `run_arex_trial(...)` in `ops/benchmarks/adr_010/harness/arex.py` — the flag currently only threads into `run_odr_trial(...)` at `runner.py:401-402`. Adapt what gets fed into `build_structural_finalize_prompt(...)` to AREX's terminal state (XML tool-call trajectory ending in a `finish` message, vs. ODR's LangChain-graph deep-research report). Estimated 30-60 min.
  2. Also verify AREX-Turbo's context-ceiling issue is addressable (the Stage 6.2 failure was `BadRequestError 400 max context length` at 32k on 2/3 trials plus a thermal-blank on the 65k-context re-run). If the ceiling is still load-bearing, structural-finalize won't help — the loop never reaches the finalize turn. See ADR-010 §"HEAD-TO-HEAD RESULT (2026-07-30)" for the full failure trace.
  3. Rerun the 3-trial fixture on Colossus per contender with a **consistent rater discipline** (Stage 6.3.9 showed rater drift of 0.34 rubric-points between user-rater and agent-rater on the same fixture — see ADR-054 status amendment). Pre-declare which rater will do the pass and use them for both contenders in the same sitting.
  4. If AREX-Turbo wins under tuned parity, Zetesis's `LLMPort` binding can be swapped without any port-contract change (ADR-052 Q3=A skeleton was designed for this — inner-loop-agnostic port surface).
- **Related DEBUG_LOG search terms:** "AREX", "arex-turbo", "max context length", "context-ceiling", "structural_finalize", "ADR-010", "head-to-head", "Zetesis inner loop", "run_arex_trial", "run_odr_trial".
- **Candidate revisit stage:** post-Phase-6 (Zetesis exit-gate landed, next phase started). Not blocking Stage 6.3 (proper) (Zetesis kernel wiring), Stage 6.4 (Stage-6 exit gate), or any downstream stage. See `ADR-055-stage-6-4-odr-tuned-ratification.md` §Rationale point 3 for cost-of-delay analysis.

### 2026-08-01 — Next.js 16.0.0 CVE-2025-66478 (SSRF via image optimization)

- **Blocks:** no blockers for Stage 1 (image optimization is disabled via `images.unoptimized: true` in `ui/next.config.js` because `output: "export"` requires it). Revisit before enabling any server-side image transform.
- **Symptom:** CVE-2025-66478 in Next.js 16.0.0 image-optimization SSRF; also `baseline-browser-mapping` prints "data over two months old" warnings on every build.
- **Attempted fixes:** none — deferred to Stage 2.
- **Next investigation:** bump `next` to the latest 16.x patch and `baseline-browser-mapping` to latest at Stage 2 kickoff; re-run pytest + Playwright.
- **Related DEBUG_LOG search terms:** `next.js 16`, `CVE-2025-66478`, `baseline-browser-mapping`.

### 2026-08-01 — Deferred: `PhrourosEngine.list_all()` port (ADR-034 amendment)

- **Blocks:** no blockers for Stage 1 (UI Phrouros anomalies panel currently reads via `/api/phrouros/anomalies` which returns an empty list until a Phrouros engine is booted).
- **Symptom:** `PhrourosPort` has no `list_all()` — the UI would benefit from a bulk query rather than per-anomaly polling.
- **Attempted fixes:** none — held for ADR amendment.
- **Next investigation:** decide at Stage 2 whether `list_all(limit, since)` belongs on `PhrourosPort` (amend ADR-034) or is a UI-only aggregate.
- **Related DEBUG_LOG search terms:** `Phrouros`, `anomalies`, `list_all`.

### 2026-08-01 — Deferred: `ResourcePort.get_balance()` port (ADR-029 amendment)

- **Blocks:** no blockers for Stage 1 — the UI uses `/api/resources/balances` which returns the full dict, and the six `ResourceKind` panels have a per-kind entry (nullable) per ADR-066 D2.
- **Symptom:** `ResourcePort` exposes only the aggregate dict; a per-kind `get_balance(kind)` would let unowned-port panels lazy-load without pulling all six.
- **Attempted fixes:** none — held for ADR amendment.
- **Next investigation:** at Stage 2 decide whether the per-kind accessor lives on `ResourcePort` (amend ADR-029) or the aggregate is the only sanctioned API.
- **Related DEBUG_LOG search terms:** `ResourcePort`, `get_balance`, `resource balances`.

### 2026-08-01 — GraphitiTemporalIndex init fails validation on KosmosGraphitiEmbedder

- **Blocks:** no active work — semantic memory path (ADR-074 D3) works because it wires the EmbeddingsPort directly, bypassing Graphiti. This only affects the deprecated Graphiti temporal-index code path.
- **Symptom:** kernel logs at UI request time print repeatedly:
  ```
  GraphitiTemporalIndex init failed: ValidationError: 1 validation error for GraphitiClients
  embedder
    Input should be an instance of EmbedderClient
    input_type=KosmosGraphitiEmbedder
  ```
- **Attempted fixes:** none yet — surfaced by Stage 1.6 Phase 1 verify runs
- **Next investigation:** `adapters/memory/dozerdb/kosmos_graphiti_embedder.py` (or wherever `KosmosGraphitiEmbedder` is defined) needs to subclass `graphiti_core.embedder.EmbedderClient` or the constructor wiring in `graphiti_temporal_index.py` should adapt to a duck-typed protocol. Also consider: ADR-073 marked GraphitiTemporalIndex path as deprecated — the correct fix may be to delete it entirely (hard-delete deferred per ADR-073 §Consequences).
- **Related DEBUG_LOG search terms:** "GraphitiTemporalIndex", "EmbedderClient", "KosmosGraphitiEmbedder", "GraphitiClients validation"

### 2026-09-10 — Stage 3.12 exit-gate end-to-end test fails on Cloud

- **Blocks:** no blockers (Stage 3.12 already ratified; failure is Colossus-only expectation drift, not a regression)
- **Symptom:** `plugins/tektos/tests/test_stage_3_12_exit_gate.py::test_tektos_refactors_real_kosmos_file_end_to_end_passes_ruff_bandit_pytest_build_sequence_3_12_dod` FAILS in Cloud sandbox
- **Attempted fixes:** confirmed pre-existing at commit 52a7020 via `git stash` — this test was already failing before Stage 8.0 and Stage 8.1 landed; unchanged by either
- **Next investigation:** either mark the test `@pytest.mark.colossus_only` (matching the Stage 4.6 live-tier pattern) or capture a Cloud-safe fixture snapshot; do NOT re-diagnose without running the Colossus tier first
- **Related DEBUG_LOG search terms:** "3_12", "exit_gate", "refactor", "ruff bandit pytest"
