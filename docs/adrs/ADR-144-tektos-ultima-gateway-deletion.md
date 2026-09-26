# ADR-144 — ADR-109 gateway module deletion (Stage 14.1)

**Status:** Ratified
**Lock-in phase:** Stage 14.1 (main.py retirement exit gate, first gate step)
**Supersedes:** ADR-109 (module + contract test) · ADR-113 D3 CSP-home clause (re-homed to `kernel/csp.py`)

## Context

ADR-141's Stage 11 exit gate (main.py deletion) requires, among its gate
conditions: (e) the page-level `/health` upstream probe and "upstream down"
banner removed, and (f) **the ADR-109 gateway module deleted and :8020
retired**. By Stage 14.1 every consumer of the ADR-109 bridge
(`/api/tektos-ultima/gateway/*`) has a kernel-native referent:

- Dashboard cards — Stages 11.1–11.23 (ADR-117…ADR-139) re-pointed each card
  to kernel-native endpoints (`base: ""`).
- Sessions — `646174a` (Stage 14.0) re-pointed the session page's state and
  archive calls kernel-direct.
- Ops page — ADR-137/138/139 + ADR-142 R8: all 7 tabs kernel-native.
- Panels page — ADR-141 Stage 13.x: all 14 tabs kernel-native.

The bridge existed only to proxy to :8020 while the engine was being ported.
With the engine port complete (ADR-141 T-bucket EMPTY: 131 P / 23 D / 0 T =
154), the gateway is dead infrastructure: its `/health` probe points at a
standalone API that is scheduled for retirement, and the transparent proxy
routes no surviving UI traffic.

One subtlety found during deletion: `KosmosCSPMiddleware` (the ADR-089
`frame-ancestors 'self'` hardening, raw-ASGI send-wrapping, streaming-safe)
lived *inside* `kernel/tektos_ultima_gateway.py` per ADR-113 D3. It is
kernel-wide hardening, not gateway functionality — deleting the module would
have silently removed it. It was extracted first.

## Decision

### D1 — Extract the CSP middleware, then delete

`KosmosCSPMiddleware` moved byte-identical to **`kernel/csp.py`**;
`kernel/app.py` imports it from there and mounts it kernel-wide (mount order
and behaviour unchanged — ADR-089). Only after this extraction was
`kernel/tektos_ultima_gateway.py` deleted.

### D2 — Delete the module and its contract test

`git rm kernel/tektos_ultima_gateway.py` and
`tests/kernel/test_stage_9_1_tektos_ultimate_gateway.py` (the ADR-109 D6
contract suite tested the proxy itself — the proxy no longer exists).

### D3 — UI goes fully kernel-native (no GATEWAY constant)

`ui/app/tektos-ultima/{page,ops/page,panels/page}.tsx`:

- `GATEWAY` const deleted; the `g()`/`act()` fetch helpers default to `base:
  ""` (same-origin kernel).
- Dashboard `fetchHealth()` now reads kernel `/health` (boot-truth) +
  `/api/llm/status` + `/api/sessions`; the "upstream down" banner reads
  "Tektos kernel is not reachable".
- Ops/panels page-level probes → kernel `/health`.
- Panels "Tektos core" status row → kernel-native fields: status from
  `/health` (`status === "ok"`), LLM model from `/api/llm/status`, active
  session count from `/api/sessions` length. The donor's `protocol_version`
  had no kernel referent and is dropped from the row (the kernel `/health`
  exposes the 12-subsystem boot-truth instead).

### D4 — Specs assert kernel-native reality

- `ui/tests/20-tektos-ultima-shell.spec.ts`: the ADR-109 typed-envelope test
  is replaced by a kernel `/health` → `{status: "ok"}` assertion; the legacy
  CSP test now verifies the middleware from `kernel/csp.py`.
- `ui/tests/21-tektos-ultima-sessions.spec.ts`: seeding/archive helpers call
  kernel-direct `/api/sessions` paths.
- `ui/tests/22-tektos-ultima-ops.spec.ts`: 4 tests that still asserted
  **donor-era data** (Stage-9.4 text left behind when ADR-136/137/138
  re-pointed the tabs in ancestors of the Stage 14.0 baseline — pre-existing
  spec debt, not a Stage 14.1 regression) now assert the kernel-native
  reality: DB tab → "Kernel persistence lanes" wired table (ADR-137); skills
  tab → ADR-125 stats surface with the ADR-108 D9 registry deferral note;
  tools tab → 13-tool ADR-107 D1 capability table; telemetry tab → ADR-138
  °C sample + "kernel-native (ADR-138)" footer.
- `ui/tests/23-tektos-ultima-panels.spec.ts`: the Tektos-core row assertion
  now reads "active sessions"; the drill tab's skill-search portion asserts
  the honest empty state (`no matches`) — `/api/skills/search` is a ratified
  ADR-108 D9 deferral (donor SkillManager 830 LOC, no kernel referent), so
  the spec documents the deferral instead of asserting donor skill names.

### D5 — :8020 remains running (this slice)

Stage 14.1 deletes the **proxy**, not the upstream. The standalone Tektos
backend on :8020 keeps running until the main.py deletion step itself; no
systemd unit was touched. ADR-141 gate condition (f) reads "deleted and
:8020 is retired" — the module half is now complete; the :8020 retirement
happens at the main.py deletion commit (with the donor tree), per ADR-141's
consequence that the donor tree stays read-only until the full gate passes.

## Consequences

- `GET /api/tektos-ultima/gateway/*` now 404s (verified live).
- The CSP middleware survives at its documented ADR-089 purpose, now in a
  module whose name matches its job (`kernel/csp.py`).
- All three Tektos UI pages are 100% kernel-native; no UI code references
  the retired :8020 (grep-verified).
- Kernel suite green (828 passed, exit 0); `tsc --noEmit` clean; `next build`
  clean; Playwright: 20/20 green across specs 20–23.
- ADR-141 gate: conditions (e) and (f)-module complete; remaining gate work:
  ADR-140 WS decision at the main.py deletion commit + :8020/donor retirement.

## Live verification (2026-09-26, :8000)

- `GET /api/tektos-ultima/gateway/health` → 404 (route gone)
- `GET /health` → 200 `{status: "ok"}`
- `GET /tektos-ultima/`, `/ops/`, `/panels/` → 200; CSP header
  `frame-ancestors 'self'` present
- Kernel full suite: 828 passed, 0 failed
- Playwright specs 20–23: 20/20
