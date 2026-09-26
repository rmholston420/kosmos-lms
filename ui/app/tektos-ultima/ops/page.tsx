"use client";

/**
 * /tektos-ultima/ops — Tektos subsystem operations page (Tektos integration
 * Stage 9.4, ADR-112).
 *
 * Seven tabs: db/memory/skills/tools/logs/telemetry/self-repair are all
 * kernel-native (same-origin kernel endpoints, ADR-129/135/136/137/138);
 * the self-repair ADR-139 gateway split is CLOSED by ADR-141 R7 — the
 * executing daemon (kernel.reliability, ADR-142) now serves status,
 * history AND the repair trigger:
 *
 *   db        (kernel-native, ADR-137) GET /api/db — persistence lane
 *             booted state (postgres/dozerdb/qdrant/valkey, registry
 *             only); donor's tektos.db SQLite controls retired with
 *             main.py deletion (stores are systemd-managed infra)
 *   memory    (kernel-native, ADR-135) GET /api/memory · /api/memory/stats
 *             POST /api/memory/decay — kernel-native (ADR-141 T6: 3-tier
 *             cognitive store, KOSMOS_TEKTOS_MEMORY=on; degraded → honest
 *             n/a message) · DELETE /api/memory/{tier}/{entry_id}
 *             (route-level donor parity; the entries table above stays the
 *             graph referent per ADR-135)
 *   skills    (kernel-native, ADR-136) GET /api/skills/stats — Tektos Manager
 *             archetype tracker (skill candidates); registry list + toggles
 *             deferred (ADR-108 D9), not ported
 *   tools     (kernel-native, ADR-136) GET /api/tools — ADR-107 capability
 *             table + routing-only Tool Router; enable/disable stay on the
 *             standalone Tektos registry (ADR-126 D9)
 *   logs      GET  /api/logs (polled 10 s)
 *   telemetry (kernel-native, ADR-138) GET /api/telemetry (polled 5 s) —
 *             donor {gpu, system} envelope re-implemented in
 *             kernel.tektos_telemetry (nvidia-smi + /proc)
 *   repair    (kernel-native, ADR-141 R7) GET /api/self_repair/status
 *             (executing daemon + propose-only proposer) ·
 *             GET /api/self_repair/history ·
 *             POST /api/self_repair/repair — all same-origin kernel
 *
 * Every upstream body is null-guarded (`Array.isArray` / `isObj`) per the
 * Stage 9.2/9.3 convention — a shape change degrades one tab, never the
 * page. Destructive actions (restore, decay, repair) require confirm().
 */

import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";

const GATEWAY = "/api/tektos-ultima/gateway";
const FRAME_HEIGHT = "calc(100vh - var(--top-bar-h, 48px))";

type TabId = "db" | "memory" | "skills" | "tools" | "logs" | "telemetry" | "repair";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "db", label: "Database" },
  { id: "memory", label: "Memory" },
  { id: "skills", label: "Skills" },
  { id: "tools", label: "Tools" },
  { id: "logs", label: "Logs" },
  { id: "telemetry", label: "Telemetry" },
  { id: "repair", label: "Self-Repair" },
];

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

async function g<T = unknown>(path: string, base: string = GATEWAY): Promise<T | null> {
  try {
    const r = await fetch(`${base}${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

async function act(path: string, body?: unknown, base: string = GATEWAY): Promise<{ ok: boolean; error?: string; data?: unknown }> {
  try {
    const r = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? "{}" : JSON.stringify(body),
    });
    let data: unknown = null;
    try {
      data = await r.json();
    } catch {
      /* non-JSON body */
    }
    if (!r.ok) {
      const detail = isObj(data) ? str(data["detail"]) || str(data["error"]) : "";
      return { ok: false, error: `HTTP ${r.status}${detail ? `: ${detail}` : ""}`, data };
    }
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "request failed" };
  }
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      style={{
        fontSize: "var(--font-sm, 0.8125rem)",
        fontWeight: 600,
        color: ok ? "var(--color-amoghasiddhi, #6ad08a)" : "var(--color-amitabha, #e07070)",
      }}
    >
      {ok ? "● " : "● "}{label}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>{label}</div>
      <div style={{ fontSize: "var(--font-md, 0.9375rem)", fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function Th({ children }: { children: ReactNode }) {
  return (
    <th
      style={{
        textAlign: "left",
        padding: "6px 10px",
        borderBottom: "1px solid var(--color-border-soft, #333)",
        fontSize: "var(--font-xs, 0.75rem)",
        color: "var(--color-text-dim, #888)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </th>
  );
}

function Td({ children, mono = false, style }: { children: ReactNode; mono?: boolean; style?: CSSProperties }) {
  return (
    <td
      style={{
        padding: "5px 10px",
        borderBottom: "1px solid var(--color-border-soft, #262626)",
        fontSize: "var(--font-sm, 0.8125rem)",
        fontFamily: mono ? "var(--font-mono, ui-monospace, monospace)" : undefined,
        ...style,
      }}
    >
      {children}
    </td>
  );
}

// ---------------------------------------------------------------------------
// Tab: Database
//
// ADR-137 (Stage 11.21): kernel-native GET /api/db (base ""). Reports
// which of the kernel's four persistence lanes booted — postgres /
// dozerdb / qdrant / valkey — from registry booted state only. The
// donor's 7 :8020 calls (stats/backups/schema/analyze +
// backup/optimize/restore) managed the standalone engine's OWN
// tektos.db SQLite file; that file dies with main.py, and those
// controls have no kernel referent (stores are systemd-managed infra;
// per-store health/counts/backups are ops-level), so they are removed —
// not disabled.
// ---------------------------------------------------------------------------

type DbStoreRow = {
  store?: string;
  wired?: boolean;
  boot_error?: string | null;
  management?: string;
};

function DbTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [stores, setStores] = useState<DbStoreRow[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const s = await g<Record<string, unknown> | null>("/api/db", "");
    if (!isObj(s)) {
      setStatus(null);
      setStores([]);
      setMsg("data layer status unavailable (kernel /api/db)");
      return;
    }
    setStatus(s);
    setStores(Array.isArray(s["stores"]) ? (s["stores"] as DbStoreRow[]) : []);
    setMsg(null);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const healthy = isObj(status) ? status["healthy"] === true : null;
  const note = isObj(status) ? str(status["note"]) || "" : "";
  const wiredCount = stores.filter((s) => s.wired === true).length;

  return (
    <div data-testid="tektos-ops-db">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="status" value={isObj(status) ? String(status["status"] ?? "—") : "—"} />
        <span style={healthy === false ? { color: "var(--color-amitabha, #e07070)" } : undefined}>
          <Metric
            label="healthy"
            value={healthy === null ? "—" : String(healthy)}
          />
        </span>
        <Metric label="stores" value={stores.length ? `${wiredCount}/${stores.length} wired` : "—"} />
      </div>

      {msg && (
        <div
          data-testid="tektos-ops-db-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginBottom: 14, color: "var(--color-amitabha, #e07070)" }}
        >
          {msg}
        </div>
      )}

      <div style={panelStyle}>
        <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)", marginBottom: 10 }}>
          Kernel persistence lanes (booted state from the kernel registry — no store is contacted):
        </div>
        {stores.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            no data
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Store</Th>
                <Th>Wired</Th>
                <Th>Boot error</Th>
                <Th>Management</Th>
              </tr>
            </thead>
            <tbody>
              {stores.map((s, i) => (
                <tr key={s.store ?? i}>
                  <Td mono>{s.store ?? "—"}</Td>
                  <Td>
                    {s.wired === false ? (
                      <span style={{ color: "var(--color-amitabha, #e07070)" }}>degraded</span>
                    ) : (
                      "wired"
                    )}
                  </Td>
                  <Td mono>{s.boot_error || "—"}</Td>
                  <Td>{s.management ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {note && (
          <div style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)", marginTop: 10 }}>
            {note}
          </div>
        )}
        <div style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)", marginTop: 10 }}>
          The donor&apos;s tektos.db SQLite controls (backup/optimize/restore, backups list, schema,
          analyze) are retired with main.py deletion — those stores are systemd-managed
          infrastructure and their backups are ops-level, not card-level (ADR-137).
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Memory
// ---------------------------------------------------------------------------

function MemoryTab() {
  const [mem, setMem] = useState<unknown>(null);
  const [stats, setStats] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [m, s] = await Promise.all([g("/api/memory", ""), g("/api/memory/stats", "")]);
    setMem(m);
    setStats(s);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const entries = Array.isArray(mem) ? mem : isObj(mem) && Array.isArray(mem["entries"]) ? mem["entries"] : [];
  const statsObj = isObj(stats) ? stats : null;

  const [decaying, setDecaying] = useState(false);
  const runDecay = async () => {
    if (decaying) return;
    setDecaying(true);
    try {
      if (!window.confirm("Run decay on all cognitive-memory tiers? (expired working entries are removed)")) return;
      const res = await act("/api/memory/decay", {}, "");
      if (res.ok && isObj(res.data) && str(res.data["error"])) {
        setMsg(`decay unavailable: ${str(res.data["error"])} (KOSMOS_TEKTOS_MEMORY=on required)`);
      } else if (res.ok && isObj(res.data)) {
        const d = res.data as Record<string, unknown>;
        setMsg(`decay complete — removed: working=${str(d["working"])} long_term=${str(d["long_term"])} procedural=${str(d["procedural"])}`);
      } else {
        setMsg(`decay failed: ${res.error ?? "unknown error"}`);
      }
    } finally {
      setDecaying(false);
    }
  };

  return (
    <div data-testid="tektos-ops-memory">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
        {statsObj
          ? Object.entries(statsObj)
              .slice(0, 10)
              .map(([k, v]) => <Metric key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />)
          : <span style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>stats unavailable</span>}
        <span style={{ flex: 1 }} />
        {/* ADR-141 T6: donor's tier decay is now kernel-native — POST
            /api/memory/decay against the 3-tier cognitive store
            (KOSMOS_TEKTOS_MEMORY=on). The degraded response
            {"error": "Memory persistence not initialized"} renders as
            an honest n/a message, donor shape at 200. */}
        <button
          data-testid="tektos-ops-memory-decay-btn"
          style={{ ...btnStyle, opacity: decaying ? 0.6 : 1 }}
          disabled={decaying}
          title="Manual decay of the cognitive-memory tiers (expired working entries removed)"
          onClick={() => { void runDecay(); }}
        >
          {decaying ? "Decaying…" : "Decay (cognitive tiers)"}
        </button>
      </div>

      {msg && (
        <div
          data-testid="tektos-ops-memory-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginBottom: 14, color: msg.includes("failed") ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)" }}
        >
          {msg}
        </div>
      )}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Entries ({entries.length})</h2>
        {entries.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            no entries returned by /api/memory
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>ID</Th>
                <Th>Kind</Th>
                <Th>Content</Th>
                <Th>Score</Th>
              </tr>
            </thead>
            <tbody>
              {(entries as Array<Record<string, unknown>>).slice(0, 100).map((e, i) => (
                <tr key={str(e["id"]) || i}>
                  <Td mono>{str(e["id"]).slice(0, 8) || "—"}</Td>
                  <Td>{str(e["kind"]) || str(e["type"]) || "—"}</Td>
                  <Td>{str(e["content"]) || str(e["text"]) || "—"}</Td>
                  <Td>{e["score"] !== undefined ? String(e["score"]) : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Skills
// ---------------------------------------------------------------------------
// ADR-136 (Stage 11.20): kernel-native. The old tab proxied :8020 —
// the standalone engine's 24-skill registry (list + per-skill toggle).
// The kernel has NO skill registry (deferred, ADR-108 D9): its real
// skills surface is the Tektos Manager archetype tracker
// (KOSMOS_TEKTOS_MANAGER=on), which flags recurring task patterns as
// skill *candidates*. The tab renders what the kernel actually has
// (GET /api/skills/stats, ADR-125) and says so honestly — no fake
// registry list, no toggle (toggles would mutate a store that does
// not exist in the kernel).

type ArchetypeRow = {
  category?: string | null;
  occurrence_count?: number;
  threshold?: number | null;
  at_threshold?: boolean;
  permanent_structure_id?: string | null;
  first_seen?: string | null;
  last_seen?: string | null;
};

function SkillsTab() {
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [archetypes, setArchetypes] = useState<ArchetypeRow[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const st = await g<Record<string, unknown> | null>("/api/skills/stats", "");
    if (!isObj(st)) {
      setStats(null);
      setArchetypes([]);
      setMsg("skills stats unavailable (kernel /api/skills/stats)");
      return;
    }
    setStats(st);
    const inner = st["skills"];
    if (isObj(inner) && Array.isArray(inner["archetype_list"])) {
      setArchetypes(inner["archetype_list"] as ArchetypeRow[]);
    } else {
      setArchetypes([]);
    }
    if (Array.isArray(st["errors"]) && st["errors"].length > 0) {
      setMsg(`skills: ${(st["errors"] as string[]).join("; ")}`);
    } else {
      setMsg(null);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const inner = isObj(stats) && isObj(stats["skills"]) ? stats["skills"] : null;
  const wired = inner ? Boolean(inner["wired"]) : false;

  return (
    <div data-testid="tektos-ops-skills">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        {isObj(stats) ? (
          <>
            <Metric label="status" value={String(stats["status"] ?? "—")} />
            <Metric label="healthy" value={String(stats["healthy"] ?? "—")} />
            <Metric
              label="archetypes"
              value={inner ? String(inner["archetypes"] ?? 0) : "—"}
            />
            <Metric
              label="at_threshold"
              value={inner ? String(inner["at_threshold"] ?? 0) : "—"}
            />
            <Metric
              label="threshold"
              value={inner && inner["threshold"] != null ? String(inner["threshold"]) : "—"}
            />
            <Metric
              label="events"
              value={inner && inner["total_events"] != null ? String(inner["total_events"]) : "—"}
            />
          </>
        ) : (
          <Metric label="Skills" value="stats unavailable" />
        )}
      </div>

      {msg && (
        <div
          data-testid="tektos-ops-skills-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginBottom: 14, color: msg.includes("unavailable") || msg.includes("failed") ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)" }}
        >
          {msg}
        </div>
      )}

      {!wired && (
        <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)", marginBottom: 14 }}>
          kernel skill-candidate tracker not wired (KOSMOS_TEKTOS_MANAGER=off) — degraded state, not an error.
          The donor&apos;s 24-skill registry (list + toggles) is deferred (ADR-108 D9) and not ported to the kernel.
        </div>
      )}

      <div style={panelStyle}>
        <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)", marginBottom: 10 }}>
          Skill candidates (recurring task patterns at the tracker threshold):
        </div>
        {archetypes.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            no archetype candidates tracked
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Category</Th>
                <Th>Count</Th>
                <Th>Threshold</Th>
                <Th>Candidate</Th>
                <Th>Last seen</Th>
              </tr>
            </thead>
            <tbody>
              {archetypes.map((a, i) => (
                <tr key={a.category ?? i}>
                  <Td mono>{a.category ?? "—"}</Td>
                  <Td>{String(a.occurrence_count ?? 0)}</Td>
                  <Td>{a.threshold != null ? String(a.threshold) : "—"}</Td>
                  <Td>{a.at_threshold ? "yes" : "no"}</Td>
                  <Td mono>{a.last_seen ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Tools
// ---------------------------------------------------------------------------

type ToolCategoryCount = Record<string, number>;

function ToolsTab() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const t = await g<Record<string, unknown> | null>("/api/tools", "");
    if (!isObj(t)) {
      setData(null);
      setMsg("tools surface unavailable (kernel /api/tools)");
      return;
    }
    setData(t);
    if (Array.isArray(t["errors"]) && t["errors"].length > 0) {
      setMsg(`tools: ${(t["errors"] as string[]).join("; ")}`);
    } else {
      setMsg(null);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const inner = isObj(data) && isObj(data["tools"]) ? data["tools"] : null;
  const wired = inner ? Boolean(inner["wired"]) : false;
  const names: string[] =
    inner && Array.isArray(inner["known_tool_names"])
      ? (inner["known_tool_names"] as string[])
      : [];
  const categories = inner && isObj(inner["categories"])
    ? (inner["categories"] as ToolCategoryCount)
    : {};

  return (
    <div data-testid="tektos-ops-tools">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        {isObj(data) ? (
          <>
            <Metric label="status" value={String(data["status"] ?? "—")} />
            <Metric label="healthy" value={String(data["healthy"] ?? "—")} />
            <Metric label="known_tools" value={inner ? String(inner["known_tools"] ?? 0) : "—"} />
            <Metric
              label="categories"
              value={inner ? String(Object.keys(categories).length) : "—"}
            />
            <Metric
              label="routes_buffered"
              value={wired && inner && inner["routes_buffered"] != null ? String(inner["routes_buffered"]) : "—"}
            />
            <Metric label="router" value={inner ? String(inner["router"] ?? "—") : "—"} />
          </>
        ) : (
          <Metric label="Tools" value="surface unavailable" />
        )}
      </div>

      {msg && (
        <div
          data-testid="tektos-ops-tools-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginTop: 10, color: msg.includes("unavailable") || msg.includes("failed") ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)" }}
        >
          {msg}
        </div>
      )}

      {!wired && (
        <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)", marginBottom: 14 }}>
          kernel Tool Router not wired (KOSMOS_TEKTOS_TOOL_ROUTER=off) — degraded state, not an error.
          Execution (approval gateway + sandbox) stays on the standalone Tektos registry (ADR-126 D9).
        </div>
      )}

      <div style={panelStyle}>
        <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)", marginBottom: 10 }}>
          Capability table (static, ADR-107 D1) — the kernel&apos;s known tools by category:
        </div>
        {names.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            capability table unavailable
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Tool</Th>
              </tr>
            </thead>
            <tbody>
              {names.map((n) => (
                <tr key={n}>
                  <Td mono>{n}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Logs
// ---------------------------------------------------------------------------

type LogEntry = { timestamp?: string; level?: string; logger?: string; message?: string };

const LOG_POLL_MS = 10_000;
const LOG_LIMIT = 200;

function LogsTab() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [level, setLevel] = useState<"ALL" | "WARNING" | "ERROR">("ALL");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    // ADR-129 (Stage 11.13): kernel-native — the old call proxied :8020's
    // standalone-engine logs (tektos.thermal/self_repair/llm_client).
    // base "" → relative fetch against the kernel origin (same convention
    // as the main dashboard cards); the {logs:[...]} shape is unchanged.
    const l = await g<unknown>("/api/logs", "");
    if (Array.isArray(l)) setLogs(l as LogEntry[]);
    else if (isObj(l) && Array.isArray(l["logs"])) setLogs(l["logs"] as LogEntry[]);
    else setLogs([]);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), LOG_POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const visible = logs.filter((e) => {
    if (level !== "ALL" && e.level !== level) return false;
    if (query && !`${e.logger ?? ""} ${e.message ?? ""}`.toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });

  return (
    <div data-testid="tektos-ops-logs" style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <div style={{ ...panelStyle, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: "var(--font-sm, 0.8125rem)" }}>{visible.length}/{logs.length} lines</span>
        <span style={{ flex: 1 }} />
        {(["ALL", "WARNING", "ERROR"] as const).map((lv) => (
          <button
            key={lv}
            data-testid={`tektos-ops-logs-level-${lv}`}
            style={{ ...btnStyle, padding: "4px 10px", opacity: level === lv ? 1 : 0.6 }}
            onClick={() => setLevel(lv)}
          >
            {lv}
          </button>
        ))}
        <input
          data-testid="tektos-ops-logs-filter"
          style={{ ...inputStyle, width: 220, maxWidth: "40vw" }}
          placeholder="filter…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <pre
        data-testid="tektos-ops-logs-body"
        style={{
          flex: 1,
          minHeight: 200,
          margin: 0,
          overflow: "auto",
          border: "1px solid var(--color-border-soft, #2a2a2a)",
          borderRadius: "var(--radius-md, 6px)",
          padding: 10,
          fontSize: "var(--font-xs, 0.75rem)",
          fontFamily: "var(--font-mono, ui-monospace, monospace)",
          whiteSpace: "pre-wrap",
          lineHeight: 1.5,
        }}
      >
        {visible.length === 0
          ? "no log lines"
          : visible
              .slice(-LOG_LIMIT)
              .map((e, i) => (
                <div
                  key={i}
                  style={{
                    color:
                      e.level === "ERROR"
                        ? "var(--color-amitabha, #e07070)"
                        : e.level === "WARNING"
                          ? "#e0c060"
                          : undefined,
                  }}
                >
                  {str(e["timestamp"]).slice(11, 23) || "—"} {str(e["level"]).padEnd(7)} {str(e["logger"]).padEnd(24)} {str(e["message"])}
                </div>
              ))}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Telemetry
// ---------------------------------------------------------------------------

// ADR-138 (Stage 11.22): kernel-native GET /api/telemetry (base "") —
// the donor's canonical {gpu, system, timestamp} envelope re-implemented
// in kernel.tektos_telemetry (nvidia-smi + /proc, separate sampler from
// the ADR-121 watchdog that serves /api/thermal/status). The old flat
// shape (temperature_gpu/thermal_zone/power_state) matched nothing any
// backend served, so this tab rendered all "—" before the split.
type TelGpu = {
  temperature?: number;
  utilization?: number;
  memory_used?: number; // MiB (raw nvidia-smi, donor fidelity)
  memory_total?: number; // MiB (raw nvidia-smi, donor fidelity)
  power_draw?: number; // W
  power_limit?: number; // W
  fan_speed?: number; // %
  clocks_graphics?: number; // MHz
  clocks_memory?: number; // MHz
  memory_utilization?: number; // %
};
type TelSystem = {
  cpu_util?: number;
  mem_used_gb?: number;
  mem_total_gb?: number;
  mem_percent?: number;
  disk_used_gb?: number;
  disk_total_gb?: number;
  disk_percent?: number;
};
type TelemetrySample = {
  timestamp?: number; // epoch seconds
  gpu?: TelGpu;
  system?: TelSystem;
};

const TEL_POLL_MS = 5_000;
const TEL_HISTORY = 120; // 10 min at 5 s

function Sparkline({ values, width = 220, height = 36, stroke = "#6a9eff" }: { values: number[]; width?: number; height?: number; stroke?: string }) {
  if (values.length < 2) return <span style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>collecting…</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * width},${height - ((v - min) / span) * (height - 4) - 2}`).join(" ");
  return (
    <svg width={width} height={height} aria-hidden>
      <polyline points={pts} fill="none" stroke={stroke} strokeWidth={1.5} />
    </svg>
  );
}

function TelemetryTab() {
  const [tel, setTel] = useState<TelemetrySample | null>(null);
  const [hist, setHist] = useState<TelemetrySample[]>([]);

  const load = useCallback(async () => {
    const t = await g<TelemetrySample>("/api/telemetry", "");
    if (isObj(t)) {
      setTel(t as TelemetrySample);
      setHist((h) => [...h.slice(-(TEL_HISTORY - 1)), t as TelemetrySample]);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), TEL_POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const gpu = tel?.gpu;
  const sys = tel?.system;
  const temps = hist.map((h) => h.gpu?.temperature ?? 0).filter((v) => v > 0);
  const util = hist.map((h) => h.gpu?.utilization ?? 0).filter((v) => v > 0);
  const power = hist.map((h) => h.gpu?.power_draw ?? 0).filter((v) => v > 0);
  const vram = hist.map((h) => h.gpu?.memory_used ?? 0).filter((v) => v > 0);

  const gbytes = (b?: number): string =>
    b === undefined ? "—" : `${(b / 1024 ** 3).toFixed(1)} GiB`;

  const clockStr =
    gpu?.clocks_graphics !== undefined
      ? `${gpu.clocks_graphics} / ${gpu.clocks_memory ?? 0} MHz`
      : "—";
  const fanStr = gpu?.fan_speed !== undefined ? `${gpu.fan_speed} %` : "—";
  const memUtilStr =
    gpu?.memory_utilization !== undefined
      ? `${gpu.memory_utilization.toFixed(0)} %`
      : "—";

  return (
    <div data-testid="tektos-ops-telemetry">
      <div style={{ ...panelStyle, display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center" }}>
        <div>
          <Metric label="GPU temp" value={gpu?.temperature !== undefined && gpu.temperature > 0 ? `${gpu.temperature.toFixed(0)} °C` : "—"} />
          <Sparkline values={temps} stroke="#e07070" />
        </div>
        <div>
          <Metric label="Utilization" value={gpu?.utilization !== undefined && gpu.utilization > 0 ? `${gpu.utilization.toFixed(0)} %` : "—"} />
          <Sparkline values={util} />
        </div>
        <div>
          <Metric label="Power" value={gpu?.power_draw !== undefined && gpu.power_draw > 0 ? `${gpu.power_draw.toFixed(0)} / ${gpu.power_limit ?? 0} W` : "—"} />
          <Sparkline values={power} stroke="#e0c060" />
        </div>
        <div>
          <Metric
            label="VRAM"
            value={gpu?.memory_used !== undefined && gpu.memory_used > 0 ? `${gbytes(gpu.memory_used)} / ${gbytes(gpu.memory_total)}` : "—"}
          />
          <Sparkline values={vram} stroke="#6ad08a" />
        </div>
        <div>
          <Metric label="GPU mem util" value={memUtilStr} />
          <Metric label="Fan" value={fanStr} />
        </div>
        <div>
          <Metric label="Clocks (gfx/mem)" value={clockStr} />
          <Metric label="CPU" value={sys?.cpu_util !== undefined ? `${sys.cpu_util.toFixed(1)} %` : "—"} />
        </div>
        <div>
          <Metric label="RAM" value={sys?.mem_used_gb !== undefined ? `${sys.mem_used_gb.toFixed(1)} / ${sys.mem_total_gb ?? 0} GiB` : "—"} />
          <Metric label="Disk" value={sys?.disk_used_gb !== undefined ? `${sys.disk_used_gb.toFixed(0)} / ${sys.disk_total_gb ?? 0} GiB` : "—"} />
        </div>
      </div>
      <div style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>
        {tel?.timestamp
          ? `sample ${new Date(tel.timestamp * 1000).toISOString().slice(11, 19)} · `
          : ""}
        history: last {Math.min(hist.length, TEL_HISTORY)} samples @ {TEL_POLL_MS / 1000}s ·
        kernel-native (ADR-138) — separate sampler from the dashboard
        thermal card (/api/thermal/status, ADR-121)
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Self-Repair
// ---------------------------------------------------------------------------

type RepairEvent = {
  timestamp?: string;
  event?: string;
  severity?: string;
  detector?: string;
  description?: string;
  action?: string;
  response?: string;
};

// Normalized history row (kernel-native engine records, ADR-141 R7).
type RepairRow = {
  time: string;
  event: string;
  detector: string;
  severity: string;
  response: string;
  status: string;
};

const _SEV_LABEL: Record<string, string> = {
  "0": "LOW",
  "1": "MEDIUM",
  "2": "HIGH",
  "3": "CRITICAL",
};

function repairRow(e: Record<string, unknown>): RepairRow {
  // Engine RepairRecord (kernel-native, ADR-141 R7): created_at epoch-seconds.
  if (typeof e["created_at"] === "number") {
    const degradation = str(e["degradation_applied"]);
    const parts = [
      str(e["strategy_used"]),
      degradation && degradation !== "none" ? `degraded:${degradation}` : "",
      str(e["error"]) ? `error:${str(e["error"]).slice(0, 60)}` : "",
    ].filter(Boolean);
    return {
      time: new Date(e["created_at"] * 1000).toLocaleTimeString(),
      event: str(e["description"]) || str(e["threat_category"]) || "—",
      detector: str(e["threat_category"]) || "—",
      severity: _SEV_LABEL[str(e["threat_severity"])] || str(e["threat_severity"]) || "—",
      response: parts.join(" → ") || "—",
      status: str(e["status"]),
    };
  }
  // Legacy immune-style event shape (tolerated, never produced by the kernel now).
  const ev = e as unknown as RepairEvent;
  return {
    time: str(ev.timestamp).slice(11, 19),
    event: str(ev.event) || str(ev.description),
    detector: str(ev.detector),
    severity: str(ev.severity),
    response: str(ev.response) || str(ev.action),
    status: "",
  };
}

function RepairTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [history, setHistory] = useState<RepairRow[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    // FULLY KERNEL-NATIVE (ADR-141 R7, ADR-142): the executing daemon
    // (kernel.reliability) serves status AND history; the ADR-139 gateway
    // split is closed. base "" = same-origin kernel.
    const [s, h] = await Promise.all([
      g<Record<string, unknown> | null>("/api/self_repair/status", ""),
      g<{ history?: unknown } | unknown[]>("/api/self_repair/history", ""),
    ]);
    setStatus(s);
    let raw: unknown[] = [];
    if (Array.isArray(h)) raw = h;
    else if (isObj(h) && Array.isArray(h["history"])) raw = h["history"] as unknown[];
    setHistory(raw.filter(isObj).map((x) => repairRow(x as Record<string, unknown>)));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const repair = async () => {
    setBusy(true);
    setMsg(null);
    const r = await act("/api/self_repair/repair", { note: note.trim() || undefined }, "");
    setBusy(false);
    setMsg(r.ok ? "repair triggered" : `repair failed: ${r.error ?? "unknown"}`);
    void load();
  };

  // ADR-141 R7 / ADR-142 kernel envelope: engine (the executing daemon),
  // proposer (ADR-095, propose-only), strategies (static 19-label catalog).
  const engine = isObj(status?.["engine"]) ? (status!["engine"] as Record<string, unknown>) : null;
  const proposer = isObj(status?.["proposer"]) ? (status!["proposer"] as Record<string, unknown>) : null;
  const strategies = isObj(status?.["strategies"]) ? (status!["strategies"] as Record<string, unknown>) : null;
  const engineRunning = engine?.["running"] ?? null;
  const engineWired = engine?.["wired"] ?? null;
  const totalRepairs = engine?.["total_repairs"] ?? null;
  const completedRepairs = engine?.["completed_repairs"] ?? null;
  const failedRepairs = engine?.["failed_repairs"] ?? null;
  const registered = strategies?.["strategies_registered"] ?? null;

  return (
    <div data-testid="tektos-ops-repair">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
        <Metric label="Engine" value={engineWired === null ? "—" : engineWired ? (engineRunning ? "running" : "stopped") : "not wired"} />
        <Metric label="Repairs" value={totalRepairs === null ? "—" : `${String(totalRepairs)} (${str(completedRepairs)}✓)`} />
        <Metric label="Failed" value={str(failedRepairs)} />
        <Metric label="Strategies" value={registered === null ? "—" : String(registered)} />
        <Metric label="History" value={String(history.length)} />
      </div>

      <div style={{ fontSize: "var(--font-sm, 0.8125rem)", margin: "0 0 14px", color: "var(--color-text-dim, #888)" }}>
        Executing daemon (kernel.reliability, ADR-142): diagnose → repair → verify → learn against
        Tektos threat-model strategies and healing workflows. The repair trigger and history below
        are served by the kernel directly — the standalone :8020 engine is retired. The ADR-095
        propose-only proposer runs alongside for self-modification proposals.
      </div>

      <div style={{ ...panelStyle, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          data-testid="tektos-ops-repair-note"
          style={{ ...inputStyle, flex: 1, minWidth: 200, maxWidth: 480 }}
          placeholder="optional note describing the suspected issue"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button
          data-testid="tektos-ops-repair-btn"
          style={btnStyle}
          disabled={busy}
          onClick={() => {
            if (!window.confirm("Trigger a self-repair cycle? The repair engine will diagnose and act on detected threats.")) return;
            void repair();
          }}
        >
          {busy ? "Running…" : "Run repair"}
        </button>
      </div>

      {msg && (
        <div
          data-testid="tektos-ops-repair-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginBottom: 14, color: msg.includes("failed") ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)" }}
        >
          {msg}
        </div>
      )}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>History ({history.length})</h2>
        {history.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            no repair events recorded
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Event</Th>
                <Th>Detector</Th>
                <Th>Severity</Th>
                <Th>Response</Th>
              </tr>
            </thead>
            <tbody>
              {history.slice(0, 50).map((e, i) => (
                <tr key={i}>
                  <Td mono>{e.time || "—"}</Td>
                  <Td>{e.event || "—"}</Td>
                  <Td>{e.detector || "—"}</Td>
                  <Td>
                    <span style={{ color: e.severity === "CRITICAL" || e.severity === "HIGH" ? "var(--color-amitabha, #e07070)" : undefined }}>
                      {e.severity || "—"}
                    </span>
                  </Td>
                  <Td>{e.response || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TektosUltimaOpsPage() {
  const [tab, setTab] = useState<TabId>("db");
  const [upstreamDown, setUpstreamDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const probe = async () => {
      const h = await g("/health");
      if (!alive) return;
      setUpstreamDown(!(isObj(h) && Object.keys(h).length > 0));
    };
    void probe();
    const t = setInterval(() => void probe(), 15_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <main
      data-testid="tektos-ops-page"
      style={{ display: "flex", flexDirection: "column", height: FRAME_HEIGHT, padding: 0 }}
    >
      <header
        data-testid="tektos-ops-header"
        style={{
          padding: "var(--space-2, 8px) var(--space-3, 12px)",
          borderBottom: "1px solid var(--color-border-soft, #333)",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <h1 style={{ margin: 0, fontSize: "var(--font-lg, 1.125rem)" }}>Tektos Ops</h1>
        <StatusPill ok={!upstreamDown} label={upstreamDown ? "upstream offline" : "online"} />
        <Link
          href="/tektos-ultima"
          style={{ marginLeft: "auto", fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}
        >
          ← Dashboard
        </Link>
      </header>

      <nav
        data-testid="tektos-ops-tabs"
        style={{
          display: "flex",
          gap: 2,
          padding: "0 var(--space-3, 12px)",
          borderBottom: "1px solid var(--color-border-soft, #333)",
          overflowX: "auto",
        }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            data-testid={`tektos-ops-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "8px 14px",
              fontSize: "var(--font-sm, 0.8125rem)",
              color: tab === t.id ? "var(--color-text, #eee)" : "var(--color-text-dim, #888)",
              borderBottom: tab === t.id ? "2px solid var(--color-akshobhya, #6a9eff)" : "2px solid transparent",
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <section style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "var(--space-3, 12px)" }}>
        {tab === "db" && <DbTab />}
        {tab === "memory" && <MemoryTab />}
        {tab === "skills" && <SkillsTab />}
        {tab === "tools" && <ToolsTab />}
        {tab === "logs" && <LogsTab />}
        {tab === "telemetry" && <TelemetryTab />}
        {tab === "repair" && <RepairTab />}
      </section>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const inputStyle: CSSProperties = {
  background: "var(--color-surface, #111)",
  color: "var(--color-text, #eee)",
  border: "1px solid var(--color-border-soft, #333)",
  borderRadius: "var(--radius-md, 6px)",
  padding: "6px 10px",
  fontSize: "var(--font-sm, 0.8125rem)",
};

const btnStyle: CSSProperties = {
  background: "var(--color-surface, #1a1a1a)",
  color: "var(--color-text, #eee)",
  border: "1px solid var(--color-border-soft, #444)",
  borderRadius: "var(--radius-md, 6px)",
  padding: "6px 12px",
  fontSize: "var(--font-sm, 0.8125rem)",
  cursor: "pointer",
};

const panelStyle: CSSProperties = {
  border: "1px solid var(--color-border-soft, #2a2a2a)",
  borderRadius: "var(--radius-md, 6px)",
  padding: 14,
  marginBottom: 14,
};
