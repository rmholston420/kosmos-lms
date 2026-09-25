"use client";

/**
 * /tektos-ultima/ops — Tektos subsystem operations page (Tektos integration
 * Stage 9.4, ADR-112).
 *
 * Seven tabs driving the standalone Tektos API (:8020) through the kernel
 * gateway (ADR-109 D1), all same-origin:
 *
 *   db        GET  /api/db · /api/db/backups · /api/db/schema
 *             POST /api/db/backup · /api/db/restore · /api/db/optimize
 *             GET  /api/db/analyze
 *   memory    (kernel-native, ADR-135) GET /api/memory · /api/memory/stats
 *             POST /api/memory/decay → honest degrade (no kernel referent:
 *             kernel memory is a MemoryEvent graph, tier decay is Tektos
 *             plugin policy — landing later)
 *   skills    GET  /api/skills · /api/skills/stats
 *             POST /api/skills/{id}/toggle
 *   tools     GET  /api/tools
 *             POST /api/tools/{name}/enable · /api/tools/{name}/disable
 *   logs      GET  /api/logs (polled 10 s)
 *   telemetry GET  /api/telemetry (polled 5 s)
 *   repair    GET  /api/self_repair/status · /api/self_repair/history
 *             POST /api/self_repair/repair
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

function fmtBytes(b: unknown): string {
  const n = num(b);
  if (n === null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
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

async function act(path: string, body?: unknown): Promise<{ ok: boolean; error?: string; data?: unknown }> {
  try {
    const r = await fetch(`${GATEWAY}${path}`, {
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
// ---------------------------------------------------------------------------

type BackupInfo = { path?: string; size_bytes?: number; created_at?: string; name?: string };

function DbTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [schema, setSchema] = useState<unknown>(null);
  const [analyze, setAnalyze] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [restorePath, setRestorePath] = useState("");
  const [compress, setCompress] = useState(true);

  const load = useCallback(async () => {
    const [s, b, sc, a] = await Promise.all([
      g<Record<string, unknown>>("/api/db"),
      g<{ backups?: unknown } | unknown[]>("/api/db/backups"),
      g("/api/db/schema"),
      g("/api/db/analyze"),
    ]);
    setStatus(s);
    if (Array.isArray(b)) setBackups(b as BackupInfo[]);
    else if (isObj(b) && Array.isArray(b["backups"])) setBackups(b["backups"] as BackupInfo[]);
    else setBackups([]);
    setSchema(sc);
    setAnalyze(a);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const run = async (label: string, fn: () => Promise<{ ok: boolean; error?: string; data?: unknown }>) => {
    setBusy(true);
    setMsg(null);
    const r = await fn();
    setBusy(false);
    if (r.ok) {
      setMsg(`${label}: ok`);
      void load();
    } else {
      setMsg(`${label} failed: ${r.error ?? "unknown error"}`);
    }
  };

  const tables = isObj(status) ? num(status["table_count"]) ?? (Array.isArray(status["tables"]) ? (status["tables"] as unknown[]).length : null) : null;
  const size = isObj(status) ? num(status["size_bytes"]) ?? num(status["database_size"]) ?? num(status["size"]) : null;
  const journal = isObj(status) ? str(status["journal_mode"]) || str(status["journalMode"]) || "" : "";
  const foreignKeys = isObj(status) ? status["foreign_keys_enabled"] ?? status["fk_enabled"] ?? null : null;

  return (
    <div data-testid="tektos-ops-db">
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", ...panelStyle }}>
        <Metric label="Size" value={size !== null ? fmtBytes(size) : "—"} />
        <Metric label="Tables" value={tables !== null ? String(tables) : "—"} />
        <Metric label="Journal" value={journal || "—"} />
        {foreignKeys !== null && (
          <Metric label="Foreign keys" value={String(foreignKeys)} />
        )}
      </div>

      <div style={{ ...panelStyle, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button
          data-testid="tektos-ops-db-backup-btn"
          style={btnStyle}
          disabled={busy}
          onClick={() => void run("backup", () => act("/api/db/backup", { compress }))}
        >
          Backup
        </button>
        <label style={{ fontSize: "var(--font-sm, 0.8125rem)", display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={compress} onChange={(e) => setCompress(e.target.checked)} />
          gzip
        </label>
        <button
          style={btnStyle}
          disabled={busy}
          onClick={() => void run("optimize", () => act("/api/db/optimize"))}
        >
          Optimize
        </button>
        <span style={{ flex: 1 }} />
        <input
          data-testid="tektos-ops-db-restore-input"
          style={{ ...inputStyle, width: 320, maxWidth: "60vw" }}
          placeholder="backup file path"
          value={restorePath}
          onChange={(e) => setRestorePath(e.target.value)}
        />
        <button
          style={btnStyle}
          disabled={busy || !restorePath.trim()}
          onClick={() => {
            if (!window.confirm(`Restore DB from ${restorePath.trim()}? Current data will be replaced.`)) return;
            void run("restore", () => act("/api/db/restore", { backup_path: restorePath.trim(), verify: true }));
          }}
        >
          Restore
        </button>
      </div>

      {msg && (
        <div
          data-testid="tektos-ops-db-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginBottom: 14, color: msg.includes("failed") ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)" }}
        >
          {msg}
        </div>
      )}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Backups ({backups.length})</h2>
        {backups.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            no backups yet — run Backup
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Path</Th>
                <Th>Size</Th>
                <Th>Created</Th>
              </tr>
            </thead>
            <tbody>
              {backups.map((b, i) => (
                <tr key={b.path ?? i}>
                  <Td mono>{b.path || b.name || "—"}</Td>
                  <Td>{fmtBytes(b.size_bytes)}</Td>
                  <Td>{b.created_at ? String(b.created_at).slice(0, 19).replace("T", " ") : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Schema</h2>
        <pre
          data-testid="tektos-ops-db-schema"
          style={{ margin: 0, maxHeight: 240, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}
        >
          {schema === null ? "loading…" : JSON.stringify(schema, null, 1)}
        </pre>
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Integrity / Analyze</h2>
        <pre
          data-testid="tektos-ops-db-analyze"
          style={{ margin: 0, maxHeight: 160, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}
        >
          {analyze === null ? "n/a" : JSON.stringify(analyze, null, 1)}
        </pre>
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

  return (
    <div data-testid="tektos-ops-memory">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
        {statsObj
          ? Object.entries(statsObj)
              .slice(0, 10)
              .map(([k, v]) => <Metric key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />)
          : <span style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>stats unavailable</span>}
        <span style={{ flex: 1 }} />
        {/* ADR-135 honest degrade: the donor's tier decay has no kernel
            referent — the kernel memory is a MemoryEvent graph (no tiers,
            no decay value function). Tier/decay policy lands later as
            Tektos plugin policy against registry.memory. */}
        <button
          data-testid="tektos-ops-memory-decay-btn"
          style={{ ...btnStyle, opacity: 0.45, cursor: "not-allowed" }}
          disabled
          title="Kernel-native memory has no tier decay (arrives with Tektos plugin policy)"
          onClick={() => {
            setMsg("decay unavailable: kernel memory is a MemoryEvent graph — no tier decay (Tektos plugin policy, coming)");
          }}
        >
          Decay (kernel: n/a)
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

type SkillInfo = {
  id?: string;
  name?: string;
  category?: string;
  description?: string;
  enabled?: boolean;
  version?: string;
};

function SkillsTab() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [stats, setStats] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [s, st] = await Promise.all([
      g<{ skills?: unknown } | unknown[]>("/api/skills"),
      g("/api/skills/stats"),
    ]);
    if (Array.isArray(s)) setSkills(s as SkillInfo[]);
    else if (isObj(s) && Array.isArray(s["skills"])) setSkills(s["skills"] as SkillInfo[]);
    else setSkills([]);
    setStats(st);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const toggle = async (s: SkillInfo) => {
    if (!s.id) return;
    setBusy(true);
    setMsg(null);
    const r = await act(`/api/skills/${encodeURIComponent(s.id)}/toggle`);
    setBusy(false);
    setMsg(r.ok ? `toggled ${s.name ?? s.id}` : `toggle failed: ${r.error ?? "unknown"}`);
    void load();
  };

  return (
    <div data-testid="tektos-ops-skills">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        {isObj(stats)
          ? Object.entries(stats)
              .slice(0, 8)
              .map(([k, v]) => <Metric key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />)
          : <Metric label="Skills" value={String(skills.length)} />}
      </div>

      {msg && (
        <div
          data-testid="tektos-ops-skills-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginBottom: 14, color: msg.includes("failed") ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)" }}
        >
          {msg}
        </div>
      )}

      <div style={panelStyle}>
        {skills.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            no skills registered
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Category</Th>
                <Th>Version</Th>
                <Th>Description</Th>
                <Th>Enabled</Th>
              </tr>
            </thead>
            <tbody>
              {skills.map((s) => (
                <tr key={s.id ?? s.name}>
                  <Td mono>{s.name ?? "—"}</Td>
                  <Td>{s.category ?? "—"}</Td>
                  <Td>{s.version ?? "—"}</Td>
                  <Td style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as CSSProperties}>
                    {s.description ?? "—"}
                  </Td>
                  <Td>
                    <button
                      data-testid={`tektos-ops-skill-toggle-${s.id ?? s.name}`}
                      style={{ ...btnStyle, padding: "3px 8px" }}
                      disabled={busy}
                      onClick={() => void toggle(s)}
                    >
                      {s.enabled ? "on" : "off"}
                    </button>
                  </Td>
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

type ToolInfo = { name?: string; description?: string; enabled?: boolean };

function ToolsTab() {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const t = await g<{ tools?: unknown } | unknown[]>("/api/tools");
    if (Array.isArray(t)) setTools(t as ToolInfo[]);
    else if (isObj(t) && Array.isArray(t["tools"])) setTools(t["tools"] as ToolInfo[]);
    else setTools([]);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const setEnabled = async (tool: ToolInfo, enabled: boolean) => {
    if (!tool.name) return;
    setBusy(true);
    setMsg(null);
    const r = await act(`/api/tools/${encodeURIComponent(tool.name)}/${enabled ? "enable" : "disable"}`);
    setBusy(false);
    setMsg(r.ok ? `${enabled ? "enabled" : "disabled"} ${tool.name}` : `failed: ${r.error ?? "unknown"}`);
    void load();
  };

  return (
    <div data-testid="tektos-ops-tools">
      <div style={panelStyle}>
        {tools.length === 0 ? (
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
            no tools registered
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Description</Th>
                <Th>Enabled</Th>
              </tr>
            </thead>
            <tbody>
              {tools.map((t) => (
                <tr key={t.name}>
                  <Td mono>{t.name ?? "—"}</Td>
                  <Td>{t.description ?? "—"}</Td>
                  <Td>
                    <button
                      data-testid={`tektos-ops-tool-toggle-${t.name}`}
                      style={{ ...btnStyle, padding: "3px 8px" }}
                      disabled={busy}
                      onClick={() => void setEnabled(t, !(t.enabled ?? true))}
                    >
                      {t.enabled ?? true ? "on" : "off"}
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {msg && (
        <div
          data-testid="tektos-ops-tools-msg"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", marginTop: 10, color: msg.includes("failed") ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)" }}
        >
          {msg}
        </div>
      )}
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

type TelemetrySample = {
  timestamp?: string;
  temperature_gpu?: number;
  power_draw?: number;
  power_limit?: number;
  utilization?: number;
  memory?: { used_mb?: number; total_mb?: number };
  thermal_zone?: string;
  power_state?: string;
  clocks?: { graphics_mhz?: number; memory_mhz?: number };
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
    const t = await g<TelemetrySample>("/api/telemetry");
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

  const temps = hist.map((h) => h.temperature_gpu ?? 0).filter((v) => v > 0);
  const util = hist.map((h) => h.utilization ?? 0).filter((v) => v > 0);
  const power = hist.map((h) => h.power_draw ?? 0).filter((v) => v > 0);
  const vram = hist.map((h) => h.memory?.used_mb ?? 0).filter((v) => v > 0);

  const zone = tel?.thermal_zone ?? "";
  const zoneColor =
    zone === "RED" ? "var(--color-amitabha, #e07070)" : zone === "AMBER" ? "#e0c060" : "var(--color-amoghasiddhi, #6ad08a)";

  return (
    <div data-testid="tektos-ops-telemetry">
      <div style={{ ...panelStyle, display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center" }}>
        <div>
          <Metric label="GPU temp" value={tel?.temperature_gpu !== undefined ? `${tel.temperature_gpu.toFixed(0)} °C` : "—"} />
          <Sparkline values={temps} stroke="#e07070" />
        </div>
        <div>
          <Metric label="Utilization" value={tel?.utilization !== undefined ? `${tel.utilization.toFixed(0)} %` : "—"} />
          <Sparkline values={util} />
        </div>
        <div>
          <Metric label="Power" value={tel?.power_draw !== undefined ? `${tel.power_draw.toFixed(0)} / ${tel.power_limit?.toFixed(0) ?? "?"} W` : "—"} />
          <Sparkline values={power} stroke="#e0c060" />
        </div>
        <div>
          <Metric
            label="VRAM"
            value={tel?.memory?.used_mb !== undefined ? `${(tel.memory.used_mb / 1024).toFixed(1)} / ${((tel.memory.total_mb ?? 0) / 1024).toFixed(1)} GiB` : "—"}
          />
          <Sparkline values={vram} stroke="#6ad08a" />
        </div>
        <div>
          <Metric label="Thermal zone" value={zone || "—"} />
          <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: zoneColor, fontWeight: 700 }}>{zone || "—"}</div>
        </div>
        <div>
          <Metric label="Power state" value={tel?.power_state ?? "—"} />
          <Metric label="Cores" value={tel?.clocks?.graphics_mhz ? `${tel.clocks.graphics_mhz} MHz` : "—"} />
        </div>
      </div>
      <div style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>
        {tel?.timestamp ? `sample ${tel.timestamp.slice(11, 19)} · ` : ""}history: last {Math.min(hist.length, TEL_HISTORY)} samples @ {TEL_POLL_MS / 1000}s
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

function RepairTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [history, setHistory] = useState<RepairEvent[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const [s, h] = await Promise.all([
      g<Record<string, unknown> | null>("/api/self_repair/status"),
      g<{ history?: unknown } | unknown[]>("/api/self_repair/history"),
    ]);
    setStatus(s);
    if (Array.isArray(h)) setHistory(h as RepairEvent[]);
    else if (isObj(h) && Array.isArray(h["history"])) setHistory(h["history"] as RepairEvent[]);
    else setHistory([]);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const repair = async () => {
    setBusy(true);
    setMsg(null);
    const r = await act("/api/self_repair/repair", { note: note.trim() || undefined });
    setBusy(false);
    setMsg(r.ok ? "repair triggered" : `repair failed: ${r.error ?? "unknown"}`);
    void load();
  };

  const enabled = status?.["enabled"] ?? null;
  const armed = status?.["armed"] ?? null;

  return (
    <div data-testid="tektos-ops-repair">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
        {enabled !== null && <Metric label="Enabled" value={String(enabled)} />}
        {armed !== null && <Metric label="Armed" value={String(armed)} />}
        <Metric label="Events" value={String(history.length)} />
        {status && (
          <Metric
            label="Last check"
            value={str(status["last_check"]) ? str(status["last_check"]).slice(0, 19).replace("T", " ") : "—"}
          />
        )}
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
                  <Td mono>{str(e["timestamp"]).slice(11, 19) || "—"}</Td>
                  <Td>{str(e["event"]) || str(e["description"]) || "—"}</Td>
                  <Td>{str(e["detector"]) || "—"}</Td>
                  <Td>
                    <span style={{ color: str(e["severity"]) === "CRITICAL" || str(e["severity"]) === "HIGH" ? "var(--color-amitabha, #e07070)" : undefined }}>
                      {str(e["severity"]) || "—"}
                    </span>
                  </Td>
                  <Td>{str(e["response"]) || str(e["action"]) || "—"}</Td>
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
