# ADR-129: kernel-native `/api/logs` — the kernel's own log ring buffer

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.13 (endpoint split, logs family)
- **Supersedes:** none

## Context

The ops-page **Logs** tab (`ui/app/tektos-ultima/ops/page.tsx`, polled every
10 s) proxied `:8020/api/logs` — the **standalone** Tektos engine's own
records: `tektos.thermal.*`, `tektos.self_repair.health_monitor`,
`tektos.runtime.llm_client`, plus `httpx` request noise. A flat array of
`{timestamp, level, logger, message}`.

The kernel has **no equivalent**: it logs to stdlib `logging` (module loggers
`kernel.app`, `plugins.*`, `adapters.*`), emitted to stdout only — **nothing
was captured in memory**, so there was no kernel referent for the tab.

## Decision

### D1 — bounded, thread-safe log ring (always on, no env gate)
`_KosmosLogRing(logging.Handler)` on the **process root logger** (kernel
loggers are module names and propagate there; a `kosmos`-namespace logger
would have captured nothing). `deque(maxlen=500)`, `threading.Lock`,
`level=INFO` so DEBUG chatter cannot fill the ring. Library noise
(`uvicorn`, `httpx`, `httpcore`, `multipart`, `watchfiles`) is dropped
per-name in `emit()` so the ring shows kernel-owned records, not framework
chatter. Shared kernel infrastructure — no new dependency, no gate (a log
viewer that is off by default would be useless).

The install also lifts the root level to INFO when it is higher (the
process root defaults to WARNING, which would silently drop the kernel's
own INFO records before they reach the ring **and** stdout).

### D2 — `GET /api/logs` (always 200)
```json
{
  "logs": [ { "timestamp": "…", "level": "INFO",
               "logger": "kernel.app", "message": "…" }, … ],
  "count": 6, "max_records": 500,
  "level_histogram": { "INFO": 6 },
  "timestamp": "…"
}
```
`logs` is oldest-first (display order = emission order). The element schema
is **identical** to `:8020/api/logs`, so the tab renders it unchanged.

### D3 — tab re-point (drop-in)
The LogsTab already accepts `{logs: [...]}` (it also tolerates a bare
array). The only UI change is the fetch `base` → `""` (kernel-native,
relative fetch against the kernel origin — the same convention as the main
dashboard cards). The `g()` helper gained an optional `base` parameter
(default `GATEWAY`, so every other ops tab is untouched).

### D4 — credential redaction (found during live verification)
Live verification exposed that `_boot_relational_memory` logged the full
Postgres **DSN with password** at boot — previously stdout-only, now also
reachable over HTTP via the ring. Fixed at the source: `_redact_dsn()`
masks the password (`scheme://user:***@host/db`) before the log line is
emitted. No other kernel log line carries credentials (verified by grep +
live scan of the ring for `user:pass@` patterns).

## Consequences

- The ops Logs tab now shows the **kernel's own** records (boot wiring,
  thermal watchdog, immune/manager boot) instead of the standalone engine's.
- A bounded in-memory view of kernel logs is available for debugging without
  tailing the stdout file; 500 records is enough to see a boot sequence +
  recent activity.
- The DSN redaction closes a credential-leak vector that the ring would
  otherwise have widened (stdout → HTTP).
