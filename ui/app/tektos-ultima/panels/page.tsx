"use client";

import "@xterm/xterm/css/xterm.css";

/**
 * /tektos-ultima/panels — Tektos subsystem status panels (Tektos integration
 * Stage 9.5, ADR-113).
 *
 * Read-only companion to /tektos-ultima/ops: where ops exposes the
 * day-to-day control surface (db, memory, skills, tools, logs, telemetry,
 * repair), panels covers the remaining subsystems that only had a home in
 * the standalone :5556 SPA — planner, context, immune, dreamtime, metabolism,
 * multi-agent, self-improvement, schema, hindsight, axioms, knowledge and
 * configuration. Tabs whose families have a kernel referent are
 * kernel-native (same origin): logs (ADR-129), directory (ADR-130),
 * immune (ADR-133), hindsight (ADR-134); the rest still drive the
 * standalone Tektos API (:8020) through the kernel gateway (ADR-109).
 * All GET-only (the page mutates nothing, so CI can run it against a
 * live upstream safely).
 *
 * Tab -> endpoints:
 *   status   /api/nervous-system/status /api/observability/status /api/mcp/status
 *            /api/embedder/status /api/evaluation/status /api/ragRetriever/status
 *            /api/tools /api/vision/status /api/voice/state
 *            /api/inference/metrics /api/thermal/health
 *   planner  /api/planner/status /api/planner/templates /api/planner/language-games
 *   context  /api/context/status /api/contextCurator/status
 *   immune   (kernel-native, ADR-133) /api/immune/detectors /api/immune/threats
 *            /api/immune/responses /api/immune/memory /api/immune/memory/entries
 *   dreamtime /api/dreamtime/summary /api/dreamtime/history
 *   metabolism /api/metabolism /api/metabolism/context /api/metabolism/history
 *   agents   (kernel-native, ADR-141 T1) /tektos/api/orchestrator/status /tektos/api/orchestrator/agents
 *   selfimp  /api/self_improvement/status /api/self_improvement/metrics
 *            /api/self_improvement/report /api/self_improvement/experiences
 *   schema   /api/schema /api/schema/patterns /api/skills/dedup/groups
 *   hindsight (kernel-native, ADR-134) /api/hindsight/status /api/hindsight/experiences
 *   axioms   /api/axioms
 *   knowledge /api/search /api/directory_list /api/archive/sessions
 *            /api/archive/sessions/{session_id}
 *   config   /api/config /api/keys /api/schedule
 *   systems  /api/hooks /api/repoMap/status /api/routing/decide
 *            /api/state/{session_id}
 *
 * All upstream bodies are null-guarded (`Array.isArray` / `isObj`) per the
 * Stage 9.2–9.4 convention — a shape change degrades one tab, never the page.
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import "@xterm/xterm/css/xterm.css";

// Stage 14.1 (ADR-109 exit gate): the ADR-109 gateway proxy is deleted —
// all call sites are kernel-native (base: "").
const FRAME_HEIGHT = "calc(100vh - var(--top-bar-h, 48px))";

type TabId =
  | "status"
  | "planner"
  | "context"
  | "immune"
  | "dreamtime"
  | "metabolism"
  | "agents"
  | "selfimp"
  | "schema"
  | "skills"
  | "actions"
  | "terminal"
  | "hindsight"
  | "axioms"
  | "knowledge"
  | "config"
  | "drill";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "status", label: "Status" },
  { id: "planner", label: "Planner" },
  { id: "context", label: "Context" },
  { id: "immune", label: "Immune" },
  { id: "dreamtime", label: "Dreamtime" },
  { id: "metabolism", label: "Metabolism" },
  { id: "agents", label: "Agents" },
  { id: "selfimp", label: "Self-Improvement" },
  { id: "schema", label: "Schema" },
  { id: "skills", label: "Skills" },
  { id: "actions", label: "Actions" },
  { id: "terminal", label: "Terminal" },
  { id: "hindsight", label: "Hindsight" },
  { id: "axioms", label: "Axioms" },
  { id: "knowledge", label: "Knowledge" },
  { id: "config", label: "Config" },
  { id: "drill", label: "Hooks & Drill-down" },
];

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function healthTone(h: string): string {
  const l = h.toLowerCase();
  if (["critical", "error", "red", "degraded", "down", "unhealthy"].some((w) => l.includes(w)))
    return "var(--color-amitabha, #e07070)";
  if (["warning", "warn", "amber", "busy"].some((w) => l.includes(w))) return "#e0c060";
  if (["normal", "ok", "healthy", "ready", "green", "idle", "running", "active", "enabled"].some((w) => l.includes(w)))
    return "var(--color-amoghasiddhi, #6ad08a)";
  return "var(--color-text, #eee)";
}

function HealthValue({ value }: { value: string }) {
  return <span style={{ color: healthTone(value), fontWeight: 700 }}>{value}</span>;
}

function Metric({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>{label}</div>
      <div style={{ fontSize: "var(--font-md, 0.9375rem)", fontWeight: 600, color: tone }}>{value}</div>
    </div>
  );
}

function Th({ children }: { children?: ReactNode }) {
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

function Td({ children, mono = false, colSpan }: { children: ReactNode; mono?: boolean; colSpan?: number }) {
  return (
    <td
      colSpan={colSpan}
      style={{
        padding: "5px 10px",
        borderBottom: "1px solid var(--color-border-soft, #262626)",
        fontSize: "var(--font-sm, 0.8125rem)",
        fontFamily: mono ? "var(--font-mono, ui-monospace, monospace)" : undefined,
        maxWidth: 480,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </td>
  );
}

function JsonPre({ data, label, maxH = 260 }: { data: unknown; label: string; maxH?: number }) {
  return (
    <div style={panelStyle}>
      <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>{label}</h2>
      <pre
        style={{
          margin: 0,
          maxHeight: maxH,
          overflow: "auto",
          fontSize: "var(--font-xs, 0.75rem)",
          fontFamily: "var(--font-mono, ui-monospace, monospace)",
          whiteSpace: "pre-wrap",
        }}
      >
        {data === null ? "unavailable" : JSON.stringify(data, null, 1)}
      </pre>
    </div>
  );
}

function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>{children}</div>
  );
}

async function g<T = unknown>(path: string, base: string = ""): Promise<T | null> {
  try {
    const r = await fetch(`${base}${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

function asList(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  if (isObj(v)) {
    for (const key of ["items", "entries", "list"]) {
      if (Array.isArray(v[key])) return v[key] as unknown[];
    }
  }
  return [];
}

// Control-surface request (Stage 14.12 exposure fix). Unlike `g`, returns
// the HTTP status so callers can surface the ADR-114 503 degrade shape
// instead of collapsing it into `null`. `method` defaults to POST.
async function api<T = unknown>(
  path: string,
  body?: unknown,
  method: "GET" | "POST" | "PUT" | "DELETE" = "POST"
): Promise<{ ok: boolean; status: number; data: T | null }> {
  try {
    const r = await fetch(path, {
      method,
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = (await r.json().catch(() => null)) as T | null;
    return { ok: r.ok, status: r.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  }
}

function degradeNote(detail: unknown): string {
  const d = isObj(detail) ? detail["detail"] : detail;
  return typeof d === "string" && d ? d : "endpoint unavailable";
}

// ---------------------------------------------------------------------------
// Tab: Status (subsystem health overview)
// ---------------------------------------------------------------------------

type Subsystem = { key: string; name: string; status: string; detail?: string };

function StatusTab() {
  const [rows, setRows] = useState<Subsystem[]>([]);
  const [inf, setInf] = useState<Record<string, unknown> | null>(null);
  const [thermal, setThermal] = useState<Record<string, unknown> | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [llmst, setLlmst] = useState<Record<string, unknown> | null>(null);
  const [sesss, setSesss] = useState<unknown>(null);

  const load = useCallback(async () => {
    const [nerv, obs, mcp, emb, ev, rag, tr, vis, voice, infm, therm, hp, llmStatus, sessions] = await Promise.all([
      g<Record<string, unknown>>("/api/nervous-system/status"),
      g<Record<string, unknown>>("/api/observability/status"),
      g<Record<string, unknown>>("/api/mcp/status"),
      g<Record<string, unknown>>("/api/embedder/status"),
      g<Record<string, unknown>>("/api/evaluation/status"),
      g<Record<string, unknown>>("/api/ragRetriever/status"),
      g<Record<string, unknown>>("/api/tools"),
      g<Record<string, unknown>>("/api/vision/status"),
      g<Record<string, unknown>>("/api/voice/state"),
      g<Record<string, unknown>>("/api/inference/metrics"),
      g<Record<string, unknown>>("/api/thermal/health"),
      g<Record<string, unknown>>("/health"),
      g<Record<string, unknown>>("/api/llm/status"),
      g<Array<Record<string, unknown>>>("/api/sessions"),
    ]);
    const pick = (o: Record<string, unknown> | null, name: string, detail?: unknown): Subsystem => ({
      key: name.toLowerCase().replace(/[^a-z]+/g, "_"),
      name,
      status: o ? str(o["status"]) || str(o["health"]) || "n/a" : "offline",
      detail: detail !== undefined ? String(detail) : o ? str(o["model"]) || str(o["url"]) || str(o["db_path"]) || "" : "",
    });
    const voiceDetail = voice
      ? `${voice["is_listening"] ? "listening" : "idle"}${voice["is_speaking"] ? " · speaking" : ""}`
      : "";
    setRows([
      pick(nerv, "Nervous System"),
      pick(obs, "Observability"),
      mcp ? { key: "mcp", name: "MCP", status: mcp["connected"] ? "connected" : "disconnected", detail: `${mcp["imported_count"] ?? 0} tools` } : { key: "mcp", name: "MCP", status: "offline" },
      pick(emb, "Embedder"),
      ev ? { key: "evaluation", name: "Evaluation", status: str(ev["status"]) || "n/a", detail: `${ev["total_evaluations"] ?? 0} evals` } : { key: "evaluation", name: "Evaluation", status: "offline" },
      pick(rag, "RAG Retriever"),
      tr ? {
        key: "tool_router",
        name: "Tool Router",
        status: tr["healthy"] ? "healthy" : str(tr["status"]) || "unhealthy",
        detail: isObj(tr["tools"]) ? `${String((tr["tools"] as Record<string, unknown>)["known_tools"] ?? 0)} tools · routing-only` : "",
      } : { key: "tool_router", name: "Tool Router", status: "offline" },
      vis ? { key: "vision", name: "Vision", status: vis["healthy"] ? "healthy" : str(vis["ok"]) ? "ok" : "unhealthy", detail: str(vis["model"]) } : { key: "vision", name: "Vision", status: "offline" },
      voice ? { key: "voice", name: "Voice", status: voiceDetail || "idle", detail: str(voice["last_transcript"]).slice(0, 40) } : { key: "voice", name: "Voice", status: "offline" },
    ]);
    setInf(infm);
    setThermal(therm);
    // Stage 14.1 (ADR-109 exit gate): kernel-native /health — no more
    // {upstream, reachable, body} gateway envelope.
    setHealth(hp);
    setLlmst(llmStatus);
    setSesss(sessions);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const score = thermal && typeof thermal["health_score"] === "number" ? Math.round(thermal["health_score"] as number) : null;

  return (
    <div data-testid="tektos-panels-status">
      <div style={panelStyle}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <Th>Subsystem</Th>
              <Th>Status</Th>
              <Th>Detail</Th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <Td mono>Tektos core</Td>
              <Td>
                <HealthValue value={health && str(health["status"]) === "ok" ? "ok" : "offline"} />
              </Td>
              <Td>
                {health
                  ? `${str(llmst?.["model"]) || "no LLM"} · ${Array.isArray(sesss) ? sesss.length : 0} active sessions`
                  : "unreachable"}
              </Td>
            </tr>
            {rows.map((r) => (
              <tr key={r.key}>
                <Td mono>{r.name}</Td>
                <Td>
                  <HealthValue value={r.status} />
                </Td>
                <Td>{r.detail || "—"}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ ...panelStyle, display: "flex", gap: 20, flexWrap: "wrap" }}>
        {inf ? (
          <>
            <Metric label="Tokens total" value={String(inf["total_tokens"] ?? "—")} />
            <Metric label="Throughput" value={inf["tokens_per_second"] !== undefined ? `${(inf["tokens_per_second"] as number).toFixed(1)} tok/s` : "—"} />
            <Metric label="Cache hit" value={inf["cache_hit_rate"] !== undefined ? `${(inf["cache_hit_rate"] as number).toFixed(0)}%` : "—"} />
            <Metric label="Prompt latency" value={inf["avg_prompt_latency"] !== undefined ? `${(inf["avg_prompt_latency"] as number).toFixed(0)} ms` : "—"} />
            <Metric label="Generation latency" value={inf["avg_generation_latency"] !== undefined ? `${(inf["avg_generation_latency"] as number).toFixed(0)} ms` : "—"} />
          </>
        ) : (
          <EmptyNote>inference metrics unavailable</EmptyNote>
        )}
        <Metric label="Thermal score" value={score !== null ? `${score}` : "—"} tone={score !== null && score < 50 ? "#e0c060" : undefined} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Planner
// ---------------------------------------------------------------------------

function PlannerTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [templates, setTemplates] = useState<unknown[]>([]);
  const [games, setGames] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [s, t, lg] = await Promise.all([
      g<Record<string, unknown>>("/api/planner/status"),
      g<Record<string, unknown>>("/api/planner/templates"),
      g<Record<string, unknown>>("/api/planner/language-games"),
    ]);
    setStatus(s);
    setTemplates(asList(t?.["templates"]));
    setGames(asList(lg?.["language_games"]));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const stats = status && isObj(status["stats"]) ? (status["stats"] as Record<string, unknown>) : null;

  return (
    <div data-testid="tektos-panels-planner">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Status" value={<HealthValue value={str(status?.["status"]) || "—"} />} />
        {stats
          ? Object.entries(stats)
              .slice(0, 8)
              .map(([k, v]) => <Metric key={k} label={k} value={String(v)} />)
          : null}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Templates ({templates.length})</h2>
        {templates.length === 0 ? (
          <EmptyNote>no templates</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Goal</Th>
              </tr>
            </thead>
            <tbody>
              {(templates as Array<Record<string, unknown>>).slice(0, 30).map((t, i) => (
                <tr key={str(t["name"]) || i}>
                  <Td mono>{str(t["name"]) || "—"}</Td>
                  <Td>{str(t["goal"]) || str(t["description"]) || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Language Games ({games.length})</h2>
        {games.length === 0 ? (
          <EmptyNote>no language games</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Game</Th>
                <Th>Purpose</Th>
              </tr>
            </thead>
            <tbody>
              {(games as Array<Record<string, unknown>>).slice(0, 30).map((t, i) => (
                <tr key={str(t["name"]) || i}>
                  <Td mono>{str(t["name"]) || "—"}</Td>
                  <Td>{str(t["purpose"]) || str(t["description"]) || "—"}</Td>
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
// Tab: Context
// ---------------------------------------------------------------------------

function ContextTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [curator, setCurator] = useState<Record<string, unknown> | null>(null);

  const load = useCallback(async () => {
    const [s, c] = await Promise.all([
      g<Record<string, unknown>>("/api/context/status"),
      g<Record<string, unknown>>("/api/contextCurator/status"),
    ]);
    setStatus(s);
    setCurator(c);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const budget = status && isObj(status["context_budget"]) ? (status["context_budget"] as Record<string, unknown>) : null;
  const pct = budget && typeof budget["pct"] === "number" ? (budget["pct"] as number) : null;

  return (
    <div data-testid="tektos-panels-context">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Status" value={<HealthValue value={str(status?.["status"]) || "—"} />} />
        <Metric label="Overall health" value={<HealthValue value={str(status?.["overall_health"]) || "—"} />} />
        {pct !== null ? <Metric label="Budget used" value={`${pct.toFixed(1)} %`} tone={pct > 90 ? "var(--color-amitabha, #e07070)" : pct > 80 ? "#e0c060" : undefined} /> : null}
        {budget && typeof budget["current_tokens"] === "number" ? (
          <Metric label="Tokens" value={`${Math.round(budget["current_tokens"] as number)} / ${Math.round((budget["max_tokens"] ?? 0) as number)}`} />
        ) : null}
      </div>

      {budget && typeof budget["alert_level"] === "string" && (
        <div style={{ marginBottom: 14, fontSize: "var(--font-sm, 0.8125rem)" }}>
          alert level: <HealthValue value={str(budget["alert_level"])} />
          {str(budget["recommended_action"]) ? <> · action: {str(budget["recommended_action"])}</> : null}
        </div>
      )}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Curator</h2>
        {curator ? (
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            <Metric label="Status" value={<HealthValue value={str(curator["status"]) || "—"} />} />
            {isObj(curator["stats"])
              ? Object.entries(curator["stats"] as Record<string, unknown>)
                  .slice(0, 8)
                  .map(([k, v]) => <Metric key={k} label={k} value={String(v)} />)
              : null}
          </div>
        ) : (
          <EmptyNote>curator unavailable</EmptyNote>
        )}
      </div>

      {status && (isObj(status["gpu"]) || isObj(status["system"])) && (
        <JsonPre data={{ gpu: status["gpu"], system: status["system"] }} label="GPU / system snapshot" maxH={180} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Immune
// ---------------------------------------------------------------------------

function ImmuneTab() {
  const [detectors, setDetectors] = useState<unknown[]>([]);
  const [threats, setThreats] = useState<unknown[]>([]);
  const [responses, setResponses] = useState<unknown[]>([]);
  const [memory, setMemory] = useState<Record<string, unknown> | null>(null);
  const [entries, setEntries] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [d, th, r, m, e] = await Promise.all([
      g<Record<string, unknown>>("/api/immune/detectors", ""),
      g<Record<string, unknown>>("/api/immune/threats", ""),
      g<Record<string, unknown>>("/api/immune/responses", ""),
      g<Record<string, unknown>>("/api/immune/memory", ""),
      g<Record<string, unknown>>("/api/immune/memory/entries", ""),
    ]);
    setDetectors(asList(d?.["detectors"]));
    setThreats(asList(th?.["threats"]));
    setResponses(asList(r?.["responses"]));
    setMemory(m);
    setEntries(asList(e?.["response_history"] ?? e?.["entries"] ?? e?.["memory"]));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div data-testid="tektos-panels-immune">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Detectors" value={String(detectors.length)} />
        <Metric label="Threats" value={String(threats.length)} tone={threats.length ? "var(--color-amitabha, #e07070)" : undefined} />
        <Metric label="Responses" value={String(responses.length)} />
        {memory ? (
          <>
            <Metric label="Observed" value={String(memory["total_threats_observed"] ?? "—")} />
            <Metric label="Active" value={String(memory["active_threats"] ?? "—")} tone={Number(memory["active_threats"]) > 0 ? "#e0c060" : undefined} />
            <Metric label="Resolved" value={String(memory["resolved_threats"] ?? "—")} />
            <Metric label="Uptime" value={memory["uptime_hours"] !== undefined ? `${(memory["uptime_hours"] as number).toFixed(1)} h` : "—"} />
          </>
        ) : null}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Detectors ({detectors.length})</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {(detectors as Array<Record<string, unknown> | string>).map((d, i) => {
            const name = typeof d === "string" ? d : str(d["name"]) || str(d["id"]) || `#${i}`;
            const enabled = typeof d === "object" ? (d["enabled"] ?? true) : true;
            return (
              <span
                key={i}
                style={{
                  fontSize: "var(--font-xs, 0.75rem)",
                  fontFamily: "var(--font-mono, ui-monospace, monospace)",
                  border: "1px solid var(--color-border-soft, #333)",
                  borderRadius: 4,
                  padding: "3px 8px",
                  opacity: enabled ? 1 : 0.5,
                }}
              >
                {name}
              </span>
            );
          })}
          {detectors.length === 0 && <EmptyNote>no detectors</EmptyNote>}
        </div>
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Threats ({threats.length})</h2>
        {threats.length === 0 ? (
          <EmptyNote>no threats recorded</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Detector</Th>
                <Th>Severity</Th>
                <Th>Description</Th>
              </tr>
            </thead>
            <tbody>
              {(threats as Array<Record<string, unknown>>).slice(0, 50).map((t, i) => (
                <tr key={i}>
                  <Td mono>{str(t["timestamp"]).slice(11, 19) || "—"}</Td>
                  <Td>{str(t["detector"]) || "—"}</Td>
                  <Td>
                    <HealthValue value={str(t["severity"]) || "—"} />
                  </Td>
                  <Td>{str(t["description"]) || str(t["detail"]) || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {responses.length > 0 && (
        <JsonPre data={responses.slice(0, 20)} label={`Responses (last ${Math.min(responses.length, 20)})`} maxH={200} />
      )}
      {entries.length > 0 && (
        <JsonPre data={entries.slice(0, 20)} label={`Memory entries (last ${Math.min(entries.length, 20)})`} maxH={200} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Dreamtime
// ---------------------------------------------------------------------------

function DreamtimeTab() {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [dreams, setDreams] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [s, h] = await Promise.all([
      g<Record<string, unknown>>("/api/dreamtime/summary"),
      g<Record<string, unknown>>("/api/dreamtime/history"),
    ]);
    setSummary(s);
    setDreams(asList(h?.["dreams"]));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  const recent = (summary?.["recent_dreams"] as unknown[]) ?? [];

  return (
    <div data-testid="tektos-panels-dreamtime">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="State" value={<HealthValue value={str(summary?.["state"]) || "—"} />} />
        <Metric label="Total dreams" value={String(summary?.["total_dreams"] ?? "—")} />
        <Metric label="Total insights" value={String(summary?.["total_insights"] ?? "—")} />
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>History ({dreams.length})</h2>
        {dreams.length === 0 ? (
          <EmptyNote>no dreams recorded yet</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Insights</Th>
                <Th>Duration</Th>
                <Th>Topic</Th>
              </tr>
            </thead>
            <tbody>
              {(dreams as Array<Record<string, unknown>>).slice(0, 30).map((d, i) => (
                <tr key={str(d["id"]) || i}>
                  <Td mono>{str(d["timestamp"]) || str(d["started_at"]).slice(0, 19) || "—"}</Td>
                  <Td>{String(d["insights_found"] ?? d["insights"] ?? "—")}</Td>
                  <Td>{d["duration_seconds"] !== undefined ? `${(d["duration_seconds"] as number).toFixed(0)} s` : "—"}</Td>
                  <Td>{str(d["topic"]) || str(d["summary"]).slice(0, 60) || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {recent.length > 0 && <JsonPre data={recent} label="Recent dreams (summary)" maxH={180} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Metabolism
// ---------------------------------------------------------------------------

function MetabolismTab() {
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null);
  const [ctx, setCtx] = useState<Record<string, unknown> | null>(null);
  const [history, setHistory] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [m, c, h] = await Promise.all([
      g<Record<string, unknown>>("/api/metabolism"),
      g<Record<string, unknown>>("/api/metabolism/context"),
      g<unknown[] | Record<string, unknown>>("/api/metabolism/history"),
    ]);
    setMeta(m);
    setCtx(c);
    setHistory(asList(h));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 10_000);
    return () => clearInterval(t);
  }, [load]);

  const gpu = meta && isObj(meta["gpu"]) ? (meta["gpu"] as Record<string, unknown>) : null;
  const sys = meta && isObj(meta["system"]) ? (meta["system"] as Record<string, unknown>) : null;

  return (
    <div data-testid="tektos-panels-metabolism">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Health" value={<HealthValue value={str(meta?.["overall_health"]) || "—"} />} />
        <Metric label="Latency" value={meta && typeof meta["inference_latency_ms"] === "number" ? `${(meta["inference_latency_ms"] as number).toFixed(0)} ms` : "—"} />
        <Metric label="Throughput" value={meta && typeof meta["tokens_per_second"] === "number" ? `${(meta["tokens_per_second"] as number).toFixed(1)} tok/s` : "—"} />
        <Metric label="Sessions" value={String(meta?.["active_sessions"] ?? "—")} />
        <Metric label="Tool calls" value={String(meta?.["total_tool_calls"] ?? "—")} />
        {ctx && typeof ctx["token_pct"] === "number" ? <Metric label="Context" value={`${(ctx["token_pct"] as number).toFixed(1)} %`} /> : null}
      </div>

      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        {gpu ? (
          <>
            <Metric label="GPU temp" value={gpu["temperature"] !== undefined ? `${(gpu["temperature"] as number).toFixed(0)} °C` : "—"} />
            <Metric label="GPU util" value={gpu["utilization"] !== undefined ? `${(gpu["utilization"] as number).toFixed(0)} %` : "—"} />
            <Metric label="VRAM" value={gpu["vram_pct"] !== undefined ? `${(gpu["vram_pct"] as number).toFixed(0)} %` : "—"} />
            <Metric label="Power" value={gpu["power_draw_w"] !== undefined ? `${(gpu["power_draw_w"] as number).toFixed(0)} W` : "—"} />
          </>
        ) : (
          <EmptyNote>gpu sample unavailable</EmptyNote>
        )}
        {sys ? (
          <>
            <Metric label="CPU" value={sys["cpu_percent"] !== undefined ? `${(sys["cpu_percent"] as number).toFixed(0)} %` : "—"} />
            <Metric label="RAM" value={sys["memory_pct"] !== undefined ? `${(sys["memory_pct"] as number).toFixed(0)} %` : "—"} />
            <Metric label="Disk" value={sys["disk_pct"] !== undefined ? `${(sys["disk_pct"] as number).toFixed(0)} %` : "—"} />
          </>
        ) : null}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Assessment history ({history.length})</h2>
        {history.length === 0 ? (
          <EmptyNote>no assessments recorded</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Health</Th>
                <Th>Latency</Th>
                <Th>tok/s</Th>
              </tr>
            </thead>
            <tbody>
              {(history as Array<Record<string, unknown>>).slice(0, 50).map((h, i) => (
                <tr key={i}>
                  <Td mono>{str(h["timestamp"]).slice(11, 19) || "—"}</Td>
                  <Td>
                    <HealthValue value={str(h["overall_health"]) || "—"} />
                  </Td>
                  <Td>{h["inference_latency_ms"] !== undefined ? `${(h["inference_latency_ms"] as number).toFixed(0)} ms` : "—"}</Td>
                  <Td>{h["tokens_per_second"] !== undefined ? (h["tokens_per_second"] as number).toFixed(1) : "—"}</Td>
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
// Tab: Skills (lifecycle control surface)
// ---------------------------------------------------------------------------
// Stage 14.12 exposure fix. The kernel's full 16-route skill registry
// (donor main.py:2479-2860, ADR-108 D9 discharge) was live but unreachable
// from the UI — only /api/skills/stats + /search + /{id} were consumed.
// This tab exposes the lifecycle surface: list, create, toggle, prune,
// dedup, improve, maintenance, select, execute. Degrades honestly when the
// skill manager is unwired ("Skill manager not initialized" at 200).

function SkillsLifecycleTab() {
  const [skills, setSkills] = useState<Record<string, unknown>[]>([]);
  const [showInactive, setShowInactive] = useState(false);
  const [category, setCategory] = useState("");
  const [feedback, setFeedback] = useState<string>("");
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);

  // Create form
  const [cName, setCName] = useState("");
  const [cDesc, setCDesc] = useState("");
  const [cCategory, setCCategory] = useState("");
  const [cTriggers, setCTriggers] = useState("");

  // Maintenance / select form
  const [selContext, setSelContext] = useState("");
  const [dedupThreshold, setDedupThreshold] = useState(0.6);
  const [selected, setSelected] = useState<Record<string, unknown>[]>([]);
  const [selectedRan, setSelectedRan] = useState(false);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ active_only: String(!showInactive) });
    if (category.trim()) params.set("category", category.trim());
    const r = await g<{ skills?: unknown[] }>(`/api/skills?${params.toString()}`);
    setSkills(asList(r?.["skills"]) as Record<string, unknown>[]);
  }, [showInactive, category]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (label: string, path: string, body?: unknown, method: "GET" | "POST" | "PUT" | "DELETE" = "POST") => {
    setFeedback(`${label}: running…`);
    const r = await api<Record<string, unknown>>(path, body, method);
    if (r.ok) {
      setFeedback(`${label}: ok (${r.status})${isObj(r.data) && r.data["error"] ? ` — ${r.data["error"]}` : ""}`);
      void load();
    } else {
      setFeedback(`${label}: ${r.status} ${degradeNote(r.data)}`);
    }
  };

  return (
    <div data-testid="tektos-panels-skills-lifecycle">
      <div style={{ ...panelStyle, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
        <Metric label="Skills" value={String(skills.length)} />
        <label style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}>
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> include disabled
        </label>
        <input style={{ ...inputStyle, width: 160 }} placeholder="category filter" value={category}
          onChange={(e) => setCategory(e.target.value)} />
        <button style={btnStyle} onClick={() => void run("list", `/api/skills?active_only=${!showInactive}`, undefined, "GET")}>
          Refresh
        </button>
      </div>

      {feedback && <EmptyNote>{feedback}</EmptyNote>}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Skills ({skills.length})</h2>
        {skills.length === 0 ? (
          <EmptyNote>no skills (registry empty or manager unwired)</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Category</Th>
                <Th>Enabled</Th>
                <Th>Uses</Th>
                <Th>Success</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {skills.map((s, i) => {
                const id = str(s["id"]);
                return (
                  <tr key={id || i}>
                    <Td mono>{str(s["name"]).slice(0, 40)}</Td>
                    <Td>{str(s["category"]) || "—"}</Td>
                    <Td>
                      <HealthValue value={String(s["enabled"]) === "true" ? "on" : "off"} />
                    </Td>
                    <Td>{String(s["usage_count"] ?? 0)}</Td>
                    <Td>{s["success_rate"] !== undefined ? `${(s["success_rate"] as number).toFixed(2)}` : "—"}</Td>
                    <Td>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        <button style={{ ...btnStyle, padding: "2px 6px", fontSize: "var(--font-xs, 0.7rem)" }}
                          onClick={() => {
                            if (detail && str(detail["id"]) === id) { setDetail(null); return; }
                            void api<Record<string, unknown>>(`/api/skills/${encodeURIComponent(id)}`, undefined, "GET")
                              .then((r) => setDetail(r.data));
                          }}>{detail && str(detail["id"]) === id ? "Hide" : "View"}</button>
                        <button style={{ ...btnStyle, padding: "2px 6px", fontSize: "var(--font-xs, 0.7rem)" }}
                          onClick={() => void run("toggle", `/api/skills/${encodeURIComponent(id)}/toggle`)}>Toggle</button>
                        <button style={{ ...btnStyle, padding: "2px 6px", fontSize: "var(--font-xs, 0.7rem)" }}
                          onClick={() => void run("execute", `/api/skills/${encodeURIComponent(id)}/execute`, { context: {} })}>Exec</button>
                        <button style={{ ...btnStyle, padding: "2px 6px", fontSize: "var(--font-xs, 0.7rem)" }}
                          onClick={() => void run("improve", `/api/skills/${encodeURIComponent(id)}/improve/from-execution`)}>Improve</button>
                        <button style={{ ...btnStyle, padding: "2px 6px", fontSize: "var(--font-xs, 0.7rem)", background: "var(--color-amitabha, #e07070)" }}
                          onClick={() => { if (confirm(`Delete skill "${str(s["name"])}"?`)) void run("delete", `/api/skills/${encodeURIComponent(id)}`, undefined, "DELETE"); }}>Del</button>
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {detail && (
          <JsonPre data={detail} label={`Skill: ${str(detail["name"])}`} maxH={220} />
        )}
      </div>

      {/* Maintenance batch actions */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Maintenance</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button style={btnStyle} onClick={() => void run("prune", "/api/skills/prune")}>Prune inactive</button>
          <input style={{ ...inputStyle, width: 70 }} type="number" step="0.05" min="0" max="1" value={dedupThreshold}
            onChange={(e) => setDedupThreshold(Number(e.target.value) || 0)} title="similarity threshold" />
          <button style={btnStyle} onClick={() => void run("dedup", `/api/skills/dedup?threshold=${dedupThreshold}`)}>Dedup</button>
          <button style={btnStyle} onClick={() => void run("maintenance", "/api/skills/maintenance")}>Full maintenance</button>
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 200 }} placeholder='select context JSON, e.g. {"task":"fix tests"}' value={selContext}
            onChange={(e) => setSelContext(e.target.value)} />
          <button style={btnStyle}
            onClick={() => {
              let ctx: Record<string, unknown> = {};
              try { ctx = selContext.trim() ? JSON.parse(selContext) : {}; } catch { setFeedback("select: invalid JSON context"); return; }
              setSelectedRan(true);
              void api<Record<string, unknown>>("/api/skills/select", { context: ctx, max_skills: 5 })
                .then((r) => {
                  if (r.ok && isObj(r.data)) {
                    const matched = asList(r.data["selected"]) as Record<string, unknown>[];
                    setSelected(matched);
                    setFeedback(`select: ok (${matched.length} matched)`);
                  } else setFeedback(`select: ${r.status} ${degradeNote(r.data)}`);
                });
            }}>
            Select for context
          </button>
        </div>
        {selectedRan && selected.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10 }}>
            <thead>
              <tr><Th>Name</Th><Th>Category</Th><Th>Score</Th><Th>Reason</Th></tr>
            </thead>
            <tbody>
              {selected.map((m, i) => (
                <tr key={str(m["id"]) || i}>
                  <Td mono>{str(m["name"])}</Td>
                  <Td>{str(m["category"])}</Td>
                  <Td>{String(m["score"])}</Td>
                  <Td mono>{str(m["reason"]).slice(0, 50)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create skill */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Create skill</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, width: 180 }} placeholder="name" value={cName} onChange={(e) => setCName(e.target.value)} />
          <input style={{ ...inputStyle, flex: 1, minWidth: 180 }} placeholder="description" value={cDesc} onChange={(e) => setCDesc(e.target.value)} />
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, width: 140 }} placeholder="category" value={cCategory} onChange={(e) => setCCategory(e.target.value)} />
          <input style={{ ...inputStyle, flex: 1, minWidth: 180 }} placeholder="trigger conditions (comma-separated)" value={cTriggers} onChange={(e) => setCTriggers(e.target.value)} />
          <button style={btnStyle} disabled={!cName.trim() || !cDesc.trim()}
            onClick={() => {
              const trig = cTriggers.split(",").map((s) => s.trim()).filter(Boolean);
              void run("create", "/api/skills", {
                name: cName.trim(),
                description: cDesc.trim(),
                trigger_conditions: trig,
                steps: [],
                category: cCategory.trim(),
              });
              setCName(""); setCDesc(""); setCCategory(""); setCTriggers("");
            }}>
            Create
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Agents (multi-agent orchestrator)
// ---------------------------------------------------------------------------

function AgentsTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [agents, setAgents] = useState<Record<string, unknown>[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [recent, setRecent] = useState<Record<string, unknown>[]>([]);
  const [tasks, setTasks] = useState<Record<string, unknown>[]>([]);
  const [hierRecent, setHierRecent] = useState<Record<string, unknown>[]>([]);
  const [lrStatus, setLrStatus] = useState<Record<string, unknown> | null>(null);
  const [feedback, setFeedback] = useState<string>("");

  // Control-surface form state
  const [taskDesc, setTaskDesc] = useState("");
  const [taskPriority, setTaskPriority] = useState(0);
  const [assignTaskId, setAssignTaskId] = useState("");
  const [assignAgentId, setAssignAgentId] = useState("");
  const [parallelIds, setParallelIds] = useState("");
  const [hierRole, setHierRole] = useState("planner");
  const [hierDesc, setHierDesc] = useState("");
  const [planIds, setPlanIds] = useState("");
  const [lrNextAction, setLrNextAction] = useState("");

  const load = useCallback(async () => {
    // ADR-141 T1: re-pointed from the ADR-109 gateway (:8020/api/multi-agent-
    // orchestrator/*) to the kernel-native /tektos/api/orchestrator routes
    // (ADR-114 mount, ADR-141 donor-fidelity /status + /agents port).
    // Stage 14.12: extended to the full orchestrator surface (task board,
    // batches, hierarchical + long-running) — the routes exist on the live
    // kernel; unwired engines degrade to the ADR-114 503 shape.
    const [s, a, st, rc, tk, hr, ls] = await Promise.all([
      g<Record<string, unknown>>("/tektos/api/orchestrator/status", ""),
      g<unknown[]>("/tektos/api/orchestrator/agents", ""),
      g<Record<string, unknown>>("/tektos/api/orchestrator/stats", ""),
      g<{ batches?: unknown[] }>("/tektos/api/orchestrator/recent", ""),
      g<unknown[]>("/tektos/api/orchestrator/tasks", ""),
      g<{ results?: unknown[] }>("/tektos/api/orchestrator/hierarchical/recent", ""),
      g<Record<string, unknown>>("/tektos/api/orchestrator/long-running/status", ""),
    ]);
    setStatus(s);
    setAgents(asList(a) as Record<string, unknown>[]);
    setStats(st);
    setRecent(asList(rc?.["batches"]) as Record<string, unknown>[]);
    setTasks(asList(tk) as Record<string, unknown>[]);
    setHierRecent(asList(hr?.["results"]) as Record<string, unknown>[]);
    setLrStatus(ls);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  const run = async (label: string, path: string, body?: unknown, method: "GET" | "POST" | "PUT" | "DELETE" = "POST") => {
    setFeedback(`${label}: running…`);
    const r = await api<Record<string, unknown>>(path, body, method);
    if (r.ok) {
      setFeedback(`${label}: ok (${r.status})`);
      void load();
    } else {
      setFeedback(`${label}: ${r.status} ${degradeNote(r.data)}`);
    }
  };

  const taskStats = stats && isObj(stats["tasks"]) ? (stats["tasks"] as Record<string, unknown>) : null;
  const unwired = status === null || str(status["status"]) !== "initialized";

  return (
    <div data-testid="tektos-panels-agents">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Orchestrator" value={<HealthValue value={str(status?.["status"]) || "—"} />} />
        {taskStats && (
          <>
            <Metric label="Tasks" value={String(taskStats["total_tasks"] ?? "—")} />
            <Metric label="Pending" value={String(taskStats["pending"] ?? "—")} />
            <Metric label="Running" value={String(taskStats["running"] ?? "—")} />
            <Metric label="Completed" value={String(taskStats["completed"] ?? "—")} />
            <Metric label="Failed" value={String(taskStats["failed"] ?? "—")} />
          </>
        )}
      </div>

      {feedback && <EmptyNote>{feedback}</EmptyNote>}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Agents ({agents.length})</h2>
        {agents.length === 0 ? (
          <EmptyNote>no agents reported</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Agent</Th>
                <Th>Role</Th>
                <Th>Status</Th>
                <Th>Active tasks</Th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a, i) => (
                <tr key={str(a["id"]) || i}>
                  <Td mono>{str(a["name"]) || str(a["id"]) || "—"}</Td>
                  <Td>{str(a["role"]) || "—"}</Td>
                  <Td>
                    <HealthValue value={str(a["status"]) || "—"} />
                  </Td>
                  <Td>{String(a["active_tasks"] ?? 0)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Stage 14.12: task board + control surface (create / assign /
          execute / parallel). Renders the ADR-114 degrade honestly when
          the engine family is unwired. */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Task board ({tasks.length})</h2>
        {tasks.length === 0 ? (
          <EmptyNote>
            {unwired ? "no tasks (orchestrator unwired — controls will report the ADR-114 degrade)" : "no tasks — create one below"}
          </EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>ID</Th>
                <Th>Description</Th>
                <Th>Status</Th>
                <Th>Assigned</Th>
                <Th>Pri</Th>
                <Th>Error</Th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t, i) => (
                <tr key={str(t["task_id"]) || i}>
                  <Td mono>{str(t["task_id"])}</Td>
                  <Td>{str(t["description"]).slice(0, 80)}</Td>
                  <Td><HealthValue value={str(t["status"]) || "—"} /></Td>
                  <Td mono>{str(t["assigned_agent"]) || "—"}</Td>
                  <Td>{String(t["priority"] ?? 0)}</Td>
                  <Td mono>{str(t["error"]).slice(0, 40) || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={inputStyle} placeholder="task description" value={taskDesc}
            onChange={(e) => setTaskDesc(e.target.value)} />
          <input style={{ ...inputStyle, width: 64 }} type="number" min={0} value={taskPriority}
            onChange={(e) => setTaskPriority(Number(e.target.value) || 0)} title="priority (higher = more important)" />
          <button style={btnStyle} disabled={!taskDesc.trim()}
            onClick={() => { void run("create task", "/tektos/api/orchestrator/tasks", { description: taskDesc.trim(), priority: taskPriority, dependencies: [] }); setTaskDesc(""); }}>
            Create
          </button>
        </div>

        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={inputStyle} placeholder="task_id" value={assignTaskId}
            onChange={(e) => setAssignTaskId(e.target.value)} />
          <input style={inputStyle} placeholder="agent_id" value={assignAgentId}
            onChange={(e) => setAssignAgentId(e.target.value)} />
          <button style={btnStyle} disabled={!assignTaskId.trim() || !assignAgentId.trim()}
            onClick={() => void run("assign", `/tektos/api/orchestrator/tasks/${encodeURIComponent(assignTaskId.trim())}/assign`, { task_id: assignTaskId.trim(), agent_id: assignAgentId.trim() })}>
            Assign
          </button>
          <button style={btnStyle} disabled={!assignTaskId.trim()}
            onClick={() => void run("execute", `/tektos/api/orchestrator/tasks/${encodeURIComponent(assignTaskId.trim())}/execute`)}>
            Execute
          </button>
        </div>

        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 240 }} placeholder="parallel task ids (comma-separated)" value={parallelIds}
            onChange={(e) => setParallelIds(e.target.value)} />
          <button style={btnStyle}
            disabled={!parallelIds.trim()}
            onClick={() => {
              const ids = parallelIds.split(",").map((s) => s.trim()).filter(Boolean);
              void run("parallel", "/tektos/api/orchestrator/parallel", { task_ids: ids });
            }}>
            Run parallel
          </button>
        </div>
      </div>

      {/* Stage 14.12: recent parallel batches (GET /recent). */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Recent batches ({recent.length})</h2>
        {recent.length === 0 ? (
          <EmptyNote>no batches recorded</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr><Th>When</Th><Th>Completed</Th><Th>Failed</Th><Th>Duration</Th><Th>Utilisation</Th></tr>
            </thead>
            <tbody>
              {recent.slice(0, 10).map((b, i) => (
                <tr key={str(b["id"]) || i}>
                  <Td mono>{str(b["when"]).slice(11, 19) || "—"}</Td>
                  <Td>{String(b["tasks_completed"] ?? 0)}</Td>
                  <Td>{String(b["tasks_failed"] ?? 0)}</Td>
                  <Td>{b["total_duration_seconds"] !== undefined ? `${(b["total_duration_seconds"] as number).toFixed(1)} s` : "—"}</Td>
                  <Td>{b["agent_utilization"] !== undefined ? `${((b["agent_utilization"] as number) * 100).toFixed(0)} %` : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Stage 14.12: hierarchical planner controls (POST /hierarchical/tasks,
          POST /hierarchical/plan, GET /hierarchical/recent). */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Hierarchical planner</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, width: 120 }} placeholder="role" value={hierRole}
            onChange={(e) => setHierRole(e.target.value)} />
          <input style={{ ...inputStyle, flex: 1, minWidth: 200 }} placeholder="description" value={hierDesc}
            onChange={(e) => setHierDesc(e.target.value)} />
          <button style={btnStyle} disabled={!hierRole.trim() || !hierDesc.trim()}
            onClick={() => { void run("hierarchical task", "/tektos/api/orchestrator/hierarchical/tasks", { role: hierRole.trim(), description: hierDesc.trim(), dependencies: [] }); setHierDesc(""); }}>
            Create
          </button>
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 240 }} placeholder="plan task ids (comma-separated)" value={planIds}
            onChange={(e) => setPlanIds(e.target.value)} />
          <button style={btnStyle} disabled={!planIds.trim()}
            onClick={() => {
              const ids = planIds.split(",").map((s) => s.trim()).filter(Boolean);
              void run("plan", "/tektos/api/orchestrator/hierarchical/plan", { task_ids: ids });
            }}>
            Execute plan
          </button>
        </div>
        {hierRecent.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12 }}>
            <thead>
              <tr><Th>Task</Th><Th>Role</Th><Th>Success</Th><Th>Error</Th></tr>
            </thead>
            <tbody>
              {hierRecent.slice(0, 10).map((r, i) => (
                <tr key={str(r["task_id"]) || i}>
                  <Td mono>{str(r["task_id"])}</Td>
                  <Td>{str(r["role"])}</Td>
                  <Td><HealthValue value={String(r["success"]) === "true" ? "ok" : "failed"} /></Td>
                  <Td mono>{str(r["error"]).slice(0, 40) || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Stage 14.12: long-running executor (status / heartbeat / checkpoint). */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Long-running executor</h2>
        {lrStatus ? (
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
            <Metric label="Session" value={str(lrStatus["session_id"]).slice(0, 24) || "—"} />
            <Metric label="State" value={<HealthValue value={str(lrStatus["state"]) || "—"} />} />
            <Metric label="Progress" value={lrStatus["progress_percent"] !== undefined ? `${lrStatus["progress_percent"]} %` : "—"} />
            <Metric label="Checkpoints" value={String(lrStatus["checkpoint_count"] ?? "—")} />
            <button style={btnStyle} onClick={() => void run("heartbeat", "/tektos/api/orchestrator/long-running/heartbeat")}>
              Heartbeat
            </button>
          </div>
        ) : (
          <EmptyNote>long-running agent unwired (ADR-114 degrade)</EmptyNote>
        )}
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 240 }} placeholder="next action (optional)" value={lrNextAction}
            onChange={(e) => setLrNextAction(e.target.value)} />
          <button style={btnStyle}
            onClick={() => void run("checkpoint", "/tektos/api/orchestrator/long-running/checkpoint", { session_id: "", next_action: lrNextAction.trim() })}>
            Checkpoint
          </button>
        </div>
      </div>

      {/* ADR-141 T1: status fields are booleans (donor-fidelity port) — render
          the wiring flags as a compact table instead of an object dump. */}
      {status && ("hierarchical_agent" in status) && (
        <div style={panelStyle}>
          <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Executor wiring</h2>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr><Th>Executor</Th><Th>Wired</Th></tr>
            </thead>
            <tbody>
              {(["hierarchical_agent", "long_running_agent", "coding_executor"] as const).map((k) => (
                <tr key={k}>
                  <Td mono>{k.replace(/_/g, " ")}</Td>
                  <Td>{String(status[k]) === "true" ? "yes" : "no"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Self-Improvement
// ---------------------------------------------------------------------------

function SelfImpTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [experiences, setExperiences] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [s, m, r, e] = await Promise.all([
      g<Record<string, unknown>>("/api/self_improvement/status"),
      g<Record<string, unknown>>("/api/self_improvement/metrics"),
      g<Record<string, unknown>>("/api/self_improvement/report"),
      g<Record<string, unknown>>("/api/self_improvement/experiences"),
    ]);
    setStatus(s);
    setMetrics(m);
    setReport(r);
    setExperiences(asList(e?.["experiences"]));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div data-testid="tektos-panels-selfimp">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Enabled" value={String(status?.["enabled"] ?? "—")} />
        <Metric label="Orchestrator" value={<HealthValue value={str(status?.["orchestrator_ready"]) === "true" ? "ready" : str(status?.["orchestrator_ready"]) || "—"} />} />
        <Metric label="Pending" value={String(status?.["pending"] ?? "—")} />
        <Metric label="Interval" value={status && typeof status["interval_seconds"] === "number" ? `${status["interval_seconds"] as number} s` : "—"} />
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Metrics</h2>
        {metrics ? (
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            <Metric label="Tasks" value={String(metrics["total_tasks"] ?? "—")} />
            <Metric label="Improvements" value={String(metrics["total_improvements"] ?? "—")} />
            <Metric label="Velocity" value={metrics["learning_velocity"] !== undefined ? (metrics["learning_velocity"] as number).toFixed(3) : "—"} />
            {typeof metrics["best_model_for_coding"] === "string" && metrics["best_model_for_coding"] ? (
              <Metric label="Best model" value={str(metrics["best_model_for_coding"]).slice(0, 32)} />
            ) : null}
          </div>
        ) : (
          <EmptyNote>metrics unavailable</EmptyNote>
        )}
        {metrics && Array.isArray(metrics["model_rankings"]) && (metrics["model_rankings"] as unknown[]).length > 0 && (
          <pre style={{ margin: "10px 0 0", maxHeight: 160, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}>
            {JSON.stringify(metrics["model_rankings"], null, 1)}
          </pre>
        )}
      </div>

      {report && report["report"] !== undefined && (
        <JsonPre data={report["report"]} label="Latest report" maxH={200} />
      )}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Experiences ({experiences.length})</h2>
        {experiences.length === 0 ? (
          <EmptyNote>no experiences recorded</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Task</Th>
                <Th>Outcome</Th>
              </tr>
            </thead>
            <tbody>
              {(experiences as Array<Record<string, unknown>>).slice(0, 30).map((e, i) => (
                <tr key={str(e["id"]) || i}>
                  <Td mono>{str(e["timestamp"]).slice(0, 19).replace("T", " ") || "—"}</Td>
                  <Td>{str(e["task"]) || str(e["description"]).slice(0, 80) || "—"}</Td>
                  <Td>{str(e["outcome"]) || str(e["result"]) || "—"}</Td>
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
// Tab: Schema (evolution + patterns + skill dedup)
// ---------------------------------------------------------------------------

function SchemaTab() {
  const [schema, setSchema] = useState<Record<string, unknown> | null>(null);
  const [patterns, setPatterns] = useState<Record<string, unknown> | null>(null);
  const [groups, setGroups] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [s, p, d] = await Promise.all([
      g<Record<string, unknown>>("/api/schema"),
      g<Record<string, unknown>>("/api/schema/patterns"),
      g<Record<string, unknown>>("/api/skills/dedup/groups"),
    ]);
    setSchema(s);
    setPatterns(p);
    setGroups(asList(d?.["groups"]));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  const evolution = schema && Array.isArray(schema["evolution_history"]) ? (schema["evolution_history"] as unknown[]) : [];

  return (
    <div data-testid="tektos-panels-schema">
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>
          Schema version {str(schema?.["version"]) || "—"} · {evolution.length} evolution events
        </h2>
        {schema ? (
          <pre
            style={{ margin: 0, maxHeight: 280, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}
          >
            {JSON.stringify(schema["schema"] ?? schema, null, 1)}
          </pre>
        ) : (
          <EmptyNote>schema unavailable</EmptyNote>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Evolution history ({evolution.length})</h2>
        {evolution.length === 0 ? (
          <EmptyNote>no schema evolution recorded</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Change</Th>
                <Th>Reason</Th>
              </tr>
            </thead>
            <tbody>
              {(evolution as Array<Record<string, unknown>>).slice(-30).reverse().map((e, i) => (
                <tr key={i}>
                  <Td mono>{str(e["timestamp"]).slice(0, 19).replace("T", " ") || "—"}</Td>
                  <Td>{str(e["change"]) || str(e["action"]) || "—"}</Td>
                  <Td>{str(e["reason"]) || str(e["description"]) || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <JsonPre data={patterns} label="Table patterns" maxH={160} />

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Skill dedup groups ({groups.length})</h2>
        {groups.length === 0 ? (
          <EmptyNote>no duplicate-skill groups</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Group</Th>
                <Th>Skills</Th>
              </tr>
            </thead>
            <tbody>
              {(groups as Array<Record<string, unknown>>).slice(0, 30).map((gr, i) => (
                <tr key={i}>
                  <Td mono>{str(gr["name"]) || str(gr["pattern"]) || `#${i}`}</Td>
                  <Td>{Array.isArray(gr["skills"]) ? (gr["skills"] as unknown[]).length : String(gr["count"] ?? "—")}</Td>
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
// Tab: Hindsight
// ---------------------------------------------------------------------------

function HindsightTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [experiences, setExperiences] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [s, e] = await Promise.all([
      g<Record<string, unknown>>("/api/hindsight/status", ""),
      g<unknown[] | Record<string, unknown>>("/api/hindsight/experiences", ""),
    ]);
    setStatus(s);
    setExperiences(asList(e));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div data-testid="tektos-panels-hindsight">
      <div style={panelStyle}>
        {status ? (
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            {Object.entries(status)
              .slice(0, 10)
              .map(([k, v]) => (
                <Metric key={k} label={k} value={isObj(v) ? JSON.stringify(v) : String(v)} tone={typeof v === "string" ? healthTone(v) : undefined} />
              ))}
          </div>
        ) : (
          <EmptyNote>hindsight status unavailable</EmptyNote>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Stored experiences ({experiences.length})</h2>
        {experiences.length === 0 ? (
          <EmptyNote>bank is empty — experiences are retained as sessions complete</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Kind</Th>
                <Th>Content</Th>
              </tr>
            </thead>
            <tbody>
              {(experiences as Array<Record<string, unknown>>).slice(0, 50).map((e, i) => (
                <tr key={str(e["id"]) || i}>
                  <Td mono>{str(e["timestamp"] || e["created_at"]).slice(0, 19).replace("T", " ") || "—"}</Td>
                  <Td>{str(e["kind"]) || str(e["type"]) || "—"}</Td>
                  <Td>{str(e["content"]) || str(e["text"]).slice(0, 100) || "—"}</Td>
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
// Tab: Actions (capability action surface)
// ---------------------------------------------------------------------------
// Stage 14.12 exposure fix. Six kernel capability surfaces were live on the
// backend but had no UI: Vision (analyze/analyze-url), Voice (stt/tts),
// Hindsight (retain/recall/reflect), Dreamtime (run), Planner (plan), and
// Delegate (subagent spawn). Status-only tabs left the action legs
// unreachable. This tab drives them all; each degrades honestly when its
// substrate is unwired (503 detail or the donor 200 {"error": ...}).
//
// Vision + Voice use raw fetch (base64/multipart bodies, audio stream
// responses) rather than the JSON `api` helper.

function ActionsTab() {
  const [busy, setBusy] = useState<string>("");
  const [out, setOut] = useState<Record<string, unknown | null>>({});
  const [msg, setMsg] = useState<string>("");

  // Vision
  const [vUrl, setVUrl] = useState("");
  const [vPrompt, setVPrompt] = useState("Describe what you see in this image in detail.");
  const [vFile, setVFile] = useState<File | null>(null);

  // Voice
  const [ttsText, setTtsText] = useState("");
  const [sttFile, setSttFile] = useState<File | null>(null);
  const [ttsAudio, setTtsAudio] = useState<string | null>(null);

  // Hindsight
  const [retainContent, setRetainContent] = useState("");
  const [retainContext, setRetainContext] = useState("");
  const [recallQuery, setRecallQuery] = useState("");
  const [reflectQ, setReflectQ] = useState("");

  // Dreamtime
  const [dreamFocus, setDreamFocus] = useState("");
  const [dreamMax, setDreamMax] = useState(20);

  // Planner
  const [planPrompt, setPlanPrompt] = useState("");

  // Delegate
  const [delGoal, setDelGoal] = useState("");
  const [delContext, setDelContext] = useState("");

  const session_id = "ui-actions";

  const runJson = async (key: string, label: string, path: string, body: unknown, method: "GET" | "POST" | "PUT" | "DELETE" = "POST") => {
    setBusy(key);
    setMsg(`${label}: running…`);
    const r = await api<Record<string, unknown>>(path, body, method);
    setBusy("");
    if (r.ok) {
      setOut((o) => ({ ...o, [key]: r.data }));
      setMsg(`${label}: ok (${r.status})`);
    } else {
      setMsg(`${label}: ${r.status} ${degradeNote(r.data)}`);
    }
  };

  const analyzeUrl = () => {
    if (!vUrl.trim()) { setMsg("vision: image URL required"); return; }
    setBusy("vision");
    setMsg("vision/analyze-url: running…");
    fetch("/api/vision/analyze-url", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, image_url: vUrl.trim(), prompt: vPrompt }),
    })
      .then(async (r) => ({ status: r.status, data: await r.json().catch(() => null) }))
      .then((r) => {
        setBusy("");
        if (r.status === 200 && isObj(r.data)) {
          setOut((o) => ({ ...o, vision: r.data }));
          setMsg(`vision: ok — ${String((r.data as Record<string, unknown>)["model"] ?? "model")}`);
        } else setMsg(`vision: ${r.status} ${degradeNote(r.data)}`);
      })
      .catch((e) => { setBusy(""); setMsg(`vision: error ${e}`); });
  };

  const analyzeFile = () => {
    if (!vFile) { setMsg("vision: choose an image file"); return; }
    setBusy("vision");
    setMsg("vision/analyze: encoding…");
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = String(reader.result).split(",")[1] ?? "";
      setMsg("vision/analyze: running…");
      fetch("/api/vision/analyze", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id, image_base64: b64, prompt: vPrompt }),
      })
        .then(async (r) => ({ status: r.status, data: await r.json().catch(() => null) }))
        .then((r) => {
          setBusy("");
          if (r.status === 200 && isObj(r.data)) {
            setOut((o) => ({ ...o, vision: r.data }));
            setMsg("vision: ok");
          } else setMsg(`vision: ${r.status} ${degradeNote(r.data)}`);
        })
        .catch((e) => { setBusy(""); setMsg(`vision: error ${e}`); });
    };
    reader.readAsDataURL(vFile);
  };

  const doTts = () => {
    if (!ttsText.trim()) { setMsg("voice/tts: text required"); return; }
    setBusy("voice");
    setMsg("voice/tts: synthesizing…");
    fetch("/api/voice/tts", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: ttsText }),
    })
      .then(async (r) => {
        if (!r.ok) { const t = await r.text().catch(() => ""); throw new Error(`${r.status} ${t.slice(0, 120)}`); }
        const blob = await r.blob();
        return URL.createObjectURL(blob);
      })
      .then((url) => { setTtsAudio(url); setMsg("voice/tts: ok — audio ready"); })
      .catch((e) => setMsg(`voice/tts: ${e.message}`))
      .finally(() => setBusy(""));
  };

  const doStt = () => {
    if (!sttFile) { setMsg("voice/stt: choose an audio file (wav/mp3)"); return; }
    setBusy("voice");
    setMsg("voice/stt: transcribing…");
    const form = new FormData();
    form.append("audio", sttFile);
    fetch("/api/voice/stt", { method: "POST", cache: "no-store", body: form })
      .then(async (r) => ({ status: r.status, data: await r.json().catch(() => null) }))
      .then((r) => {
        setBusy("");
        if (r.status === 200 && isObj(r.data)) {
          setOut((o) => ({ ...o, voice_stt: r.data }));
          setMsg(`voice/stt: ok — "${String((r.data as Record<string, unknown>)["text"] ?? "").slice(0, 60)}"`);
        } else setMsg(`voice/stt: ${r.status} ${degradeNote(r.data)}`);
      })
      .catch((e) => { setBusy(""); setMsg(`voice/stt: error ${e}`); });
  };

  return (
    <div data-testid="tektos-panels-actions">
      {msg && <EmptyNote>{msg}</EmptyNote>}

      {/* Vision */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>👁️ Vision</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 180 }} placeholder="image URL" value={vUrl} onChange={(e) => setVUrl(e.target.value)} />
          <input style={{ ...inputStyle, flex: 1, minWidth: 180 }} placeholder="prompt" value={vPrompt} onChange={(e) => setVPrompt(e.target.value)} />
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button style={btnStyle} disabled={busy === "vision"} onClick={analyzeUrl}>Analyze URL</button>
          <input type="file" accept="image/*" onChange={(e) => setVFile(e.target.files?.[0] ?? null)} />
          <button style={btnStyle} disabled={busy === "vision"} onClick={analyzeFile}>Analyze File</button>
        </div>
        {out["vision"] ? <JsonPre data={out["vision"]} label="vision result" maxH={220} /> : null}
      </div>

      {/* Voice */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>🎙️ Voice</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 180 }} placeholder="text to speak (TTS)" value={ttsText} onChange={(e) => setTtsText(e.target.value)} />
          <button style={btnStyle} disabled={busy === "voice"} onClick={doTts}>Synthesize</button>
        </div>
        {ttsAudio && <audio controls src={ttsAudio} style={{ marginTop: 8, width: "100%", maxWidth: 420 }} />}
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input type="file" accept="audio/*" onChange={(e) => setSttFile(e.target.files?.[0] ?? null)} />
          <button style={btnStyle} disabled={busy === "voice"} onClick={doStt}>Transcribe (STT)</button>
        </div>
        {out["voice_stt"] ? <JsonPre data={out["voice_stt"]} label="voice stt result" maxH={160} /> : null}
      </div>

      {/* Hindsight */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>🔮 Hindsight</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 160 }} placeholder="fact to retain" value={retainContent} onChange={(e) => setRetainContent(e.target.value)} />
          <input style={{ ...inputStyle, width: 140 }} placeholder="context" value={retainContext} onChange={(e) => setRetainContext(e.target.value)} />
          <button style={btnStyle} disabled={busy === "retain" || !retainContent.trim()}
            onClick={() => void runJson("retain", "retain", "/api/hindsight/retain", { content: retainContent.trim(), context: retainContext.trim() })}>
            Retain
          </button>
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 160 }} placeholder="recall query" value={recallQuery} onChange={(e) => setRecallQuery(e.target.value)} />
          <button style={btnStyle} disabled={busy === "recall" || !recallQuery.trim()}
            onClick={() => void runJson("recall", "recall", "/api/hindsight/recall", { query: recallQuery.trim(), limit: 5 })}>
            Recall
          </button>
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 160 }} placeholder="reflect question" value={reflectQ} onChange={(e) => setReflectQ(e.target.value)} />
          <button style={btnStyle} disabled={busy === "reflect" || !reflectQ.trim()}
            onClick={() => void runJson("reflect", "reflect", "/api/hindsight/reflect", { question: reflectQ.trim() })}>
            Reflect
          </button>
        </div>
        {out["retain"] ? <JsonPre data={out["retain"]} label="retain" maxH={120} /> : null}
        {out["recall"] ? <JsonPre data={out["recall"]} label="recall" maxH={200} /> : null}
        {out["reflect"] ? <JsonPre data={out["reflect"]} label="reflect" maxH={200} /> : null}
      </div>

      {/* Dreamtime + Planner */}
      <div style={{ ...panelStyle, display: "flex", gap: 24, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>🌙 Dreamtime</h2>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input style={{ ...inputStyle, flex: 1, minWidth: 120 }} placeholder="focus area" value={dreamFocus} onChange={(e) => setDreamFocus(e.target.value)} />
            <input style={{ ...inputStyle, width: 70 }} type="number" min="1" max="200" value={dreamMax} onChange={(e) => setDreamMax(Number(e.target.value) || 20)} title="max memories" />
            <button style={btnStyle} disabled={busy === "dream"}
              onClick={() => void runJson("dream", "dreamtime/run", "/api/dreamtime/run", { focus_area: dreamFocus.trim(), max_memories: dreamMax })}>
              Run
            </button>
          </div>
          {out["dream"] ? <JsonPre data={out["dream"]} label="dreamtime" maxH={200} /> : null}
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>📋 Planner</h2>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input style={{ ...inputStyle, flex: 1, minWidth: 140 }} placeholder="natural-language goal to plan" value={planPrompt} onChange={(e) => setPlanPrompt(e.target.value)} />
            <button style={btnStyle} disabled={busy === "plan" || !planPrompt.trim()}
              onClick={() => void runJson("plan", "planner/plan", "/api/planner/plan", { prompt: planPrompt.trim() })}>
              Plan
            </button>
          </div>
          {out["plan"] ? <JsonPre data={out["plan"]} label="plan (BuildSpec)" maxH={260} /> : null}
        </div>
      </div>

      {/* Delegate */}
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>🤖 Delegate subagent</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input style={{ ...inputStyle, flex: 1, minWidth: 200 }} placeholder="subtask goal" value={delGoal} onChange={(e) => setDelGoal(e.target.value)} />
          <input style={{ ...inputStyle, flex: 1, minWidth: 160 }} placeholder="context (optional)" value={delContext} onChange={(e) => setDelContext(e.target.value)} />
          <button style={btnStyle} disabled={busy === "delegate" || !delGoal.trim()}
            onClick={() => void runJson("delegate", "delegate", "/api/delegate", { goal: delGoal.trim(), context: delContext.trim() })}>
            Delegate
          </button>
        </div>
        <EmptyNote>Delegate spawns a fresh sub-session and awaits its full turn — this can take minutes. The turn loop must be online (KOSMOS_TEKTOS_TURN_LOOP=on).</EmptyNote>
        {out["delegate"] ? <JsonPre data={out["delegate"]} label="delegate" maxH={140} /> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Terminal (live PTY over WebSocket)
// ---------------------------------------------------------------------------
// Stage 14.12 exposure fix — the kernel's `/ws/pty` endpoint (Stage 14.9,
// ADR-138-era port of donor main.py:5862) was live and tested but had zero
// UI consumers. This tab drives it with xterm.js:
//   client → { type: "input", data } / { type: "resize", cols, rows }
//   server → { type: "output", data } / { type: "exit", code }
// The xterm theme mirrors the app's dark palette; fit addon resizes the
// PTY on container changes. On disconnect the shell is gone server-side —
// "Reconnect" spawns a fresh login shell.
//
// SSR/SSG note: xterm.js references `self` at module-eval time, which breaks
// the static-export prerender of this page. So it is lazy-imported inside the
// effect (client-only) and the xterm.css side effect is injected via a
// <link> at runtime instead of a top-level `import ...css`.

type XTermLib = {
  Terminal: new (opts: Record<string, unknown>) => {
    open(el: HTMLElement): void;
    write(s: string): void;
    focus(): void;
    dispose(): void;
    cols: number;
    rows: number;
    onData(cb: (d: string) => void): { dispose(): void };
    onResize(cb: (r: { cols: number; rows: number }) => void): { dispose(): void };
    loadAddon(a: unknown): void;
  };
  FitAddon: new () => { fit(): void; dispose(): void };
};

function TerminalTab() {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<InstanceType<XTermLib["Terminal"]> | null>(null);
  const fitRef = useRef<{ fit(): void } | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [state, setState] = useState<"idle" | "connecting" | "live" | "exited" | "error">("idle");
  const [exitCode, setExitCode] = useState<number | null>(null);

  // keep a ref of state for the onclose closure (avoids stale-capture)
  const stateRef = useRef(state);
  stateRef.current = state;

  const connect = useCallback(async () => {
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return;
    const host = hostRef.current;
    if (!host) return;
    setState("connecting");
    setExitCode(null);

    // Client-only lazy load — keeps the xterm module (which references `self`
    // at eval time) off the SSG prerender path.
    const [{ Terminal: XTerm }, { FitAddon }] = await Promise.all([
      import("@xterm/xterm"),
      import("@xterm/addon-fit"),
    ]);

    const term = new XTerm({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace",
      theme: {
        background: "#0d1117",
        foreground: "#e6edf3",
        cursor: "#58a6ff",
        cursorAccent: "#0d1117",
        selectionBackground: "#1f6feb55",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    fit.fit();
    term.focus();
    termRef.current = term;
    fitRef.current = fit;

    const proto = typeof window !== "undefined" ? window.location.protocol : "https:";
    const ws = new WebSocket(`${proto === "https:" ? "wss" : "ws"}://${window.location.host}/ws/pty`);
    wsRef.current = ws;

    ws.onopen = () => {
      setState("live");
      try {
        fit.fit();
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      } catch { /* fit may throw before layout settles */ }
    };
    ws.onmessage = (ev) => {
      let msg: { type: string; data?: string; code?: number };
      try { msg = JSON.parse(String(ev.data)); } catch { return; }
      if (msg.type === "output" && typeof msg.data === "string") {
        term.write(msg.data);
      } else if (msg.type === "exit") {
        term.write(`\r\n\x1b[90m[shell exited with code ${msg.code ?? 0}]\x1b[0m\r\n`);
        setState("exited");
        setExitCode(msg.code ?? null);
      }
    };
    ws.onclose = () => {
      if (stateRef.current !== "exited") setState("error");
    };
    ws.onerror = () => setState("error");

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "input", data }));
    });
    term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", cols, rows }));
    });
  }, []);

  useEffect(() => {
    void connect();
    const el = hostRef.current;
    const ro = el ? new ResizeObserver(() => { try { fitRef.current?.fit(); } catch { /* ignore */ } }) : null;
    if (el && ro) ro.observe(el);
    return () => {
      ro?.disconnect();
      wsRef.current?.close();
      wsRef.current = null;
      termRef.current?.dispose();
      termRef.current = null;
      setState("idle");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div data-testid="tektos-panels-terminal">
      <div style={{ ...panelStyle, padding: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderBottom: "1px solid var(--border, #21262d)" }}>
          <span style={{ fontSize: "var(--font-sm, 0.8125rem)" }}>
            {state === "live" && <span style={{ color: "var(--color-accent, #58a6ff)" }}>● live shell</span>}
            {state === "connecting" && <span style={{ color: "#8b949e" }}>○ connecting…</span>}
            {state === "exited" && <span style={{ color: "#8b949e" }}>○ shell exited{exitCode != null ? ` (code ${exitCode})` : ""}</span>}
            {state === "error" && <span style={{ color: "#f85149" }}>● connection error</span>}
            {state === "idle" && <span style={{ color: "#8b949e" }}>○ idle</span>}
          </span>
          <div style={{ flex: 1 }} />
          <button style={btnStyle} onClick={connect}>Reconnect</button>
        </div>
        <div ref={hostRef} style={{ height: 420, padding: 6, background: "#0d1117" }} />
      </div>
      <EmptyNote>Live PTY over <code>/ws/pty</code> (kernel Stage 14.9, donor main.py:5862 port) — a real login shell
        on the host. Input/resize frames are JSON; output is utf-8. When the shell exits the server closes the
        socket; use Reconnect for a fresh one.</EmptyNote>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Axioms
// ---------------------------------------------------------------------------

function AxiomsTab() {
  const [axioms, setAxioms] = useState<Record<string, unknown>[]>([]);
  const [filter, setFilter] = useState("all");
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(async () => {
    const a = await g<unknown[] | Record<string, unknown>>("/api/axioms");
    setAxioms(asList(a) as Record<string, unknown>[]);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 60_000);
    return () => clearInterval(t);
  }, [load]);

  const categories = Array.from(new Set(axioms.map((a) => str(a["category"])).filter(Boolean))).sort();
  const visible = axioms.filter((a) => filter === "all" || str(a["category"]) === filter);

  return (
    <div data-testid="tektos-panels-axioms">
      <div style={{ ...panelStyle, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: "var(--font-sm, 0.8125rem)" }}>
          {visible.length}/{axioms.length} axioms
        </span>
        <span style={{ flex: 1 }} />
        {["all", ...categories].map((c) => (
          <button
            key={c}
            data-testid={`tektos-panels-axiom-cat-${c}`}
            style={{ ...btnStyle, padding: "4px 10px", opacity: filter === c ? 1 : 0.6 }}
            onClick={() => setFilter(c)}
          >
            {c}
          </button>
        ))}
      </div>

      <div style={panelStyle}>
        {visible.length === 0 ? (
          <EmptyNote>no axioms</EmptyNote>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {visible.slice(0, 60).map((a, i) => {
              const hasNotes = Boolean(str(a["notes"]) || ((a["tags"] as unknown[] | undefined)?.length ?? 0));
              return (
              <div
                key={str(a["id"]) || i}
                style={{ border: "1px solid var(--color-border-soft, #2a2a2a)", borderRadius: 6, padding: "8px 12px" }}
              >
                <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                  <span style={{ fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-akshobhya, #6a9eff)" }}>
                    {str(a["id"]) || "—"}
                  </span>
                  <HealthValue value={str(a["status"]) || "—"} />
                  <span style={{ flex: 1 }} />
                  <span style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>{str(a["date"]) || ""}</span>
                </div>
                <div style={{ fontSize: "var(--font-sm, 0.8125rem)", marginTop: 4 }}>{str(a["content"]) || "—"}</div>
                {hasNotes ? (
                  <>
                    {expanded === i && (
                      <pre style={{ margin: "8px 0 0", maxHeight: 200, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}>
                        {str(a["notes"]) || JSON.stringify(a["tags"], null, 1)}
                      </pre>
                    )}
                    <button
                      style={{ ...btnStyle, padding: "3px 10px", marginTop: 8 }}
                      onClick={() => setExpanded(expanded === i ? null : i)}
                    >
                      {expanded === i ? "collapse" : "notes"}
                    </button>
                  </>
                ) : null}
              </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Knowledge (search + directory)
// ---------------------------------------------------------------------------

function KnowledgeTab() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ sessions?: unknown; events?: unknown } | null>(null);
  const [searched, setSearched] = useState(false);

  const [dir, setDir] = useState<Record<string, unknown> | null>(null);

  const loadDir = useCallback(async () => {
    const d = await g<Record<string, unknown>>("/api/directory_list", "");
    setDir(d);
  }, []);

  useEffect(() => {
    void loadDir();
  }, [loadDir]);

  const runSearch = async () => {
    setSearched(true);
    const q = encodeURIComponent(query.trim() || " ");
    const r = await g<{ sessions?: unknown; events?: unknown }>(`/api/search?query=${q}`);
    setResults(r);
  };

  const entries = dir ? asList(dir["entries"]) : [];

  return (
    <div data-testid="tektos-panels-knowledge">
      <div style={{ ...panelStyle, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          data-testid="tektos-panels-search-input"
          style={{ ...inputStyle, flex: 1, minWidth: 220, maxWidth: 520 }}
          placeholder="search sessions & events…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void runSearch();
          }}
        />
        <button data-testid="tektos-panels-search-btn" style={btnStyle} onClick={() => void runSearch()}>
          Search
        </button>
      </div>

      {searched && results && (
        <div style={panelStyle}>
          <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>
            Results: {asList(results["sessions"]).length} sessions · {asList(results["events"]).length} events
          </h2>
          {asList(results["sessions"]).length === 0 && asList(results["events"]).length === 0 ? (
            <EmptyNote>no matches</EmptyNote>
          ) : (
            <JsonPre data={{ sessions: asList(results["sessions"]).slice(0, 10), events: asList(results["events"]).slice(0, 10) }} label="" maxH={280} />
          )}
        </div>
      )}

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>
          Workspace {dir ? `${str(dir["path"]) || "."} (${entries.length} entries)` : "(loading…)"}
        </h2>
        {entries.length === 0 ? (
          <EmptyNote>no entries</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Type</Th>
                <Th>Size</Th>
              </tr>
            </thead>
            <tbody>
              {(entries as Array<Record<string, unknown>>).slice(0, 40).map((e, i) => (
                <tr key={str(e["name"]) || i}>
                  <Td mono>{str(e["name"]) || "—"}</Td>
                  <Td>{e["is_dir"] ? "dir" : "file"}</Td>
                  <Td>{typeof e["size"] === "number" ? `${(e["size"] as number) / 1024 > 1 ? ((e["size"] as number) / 1024).toFixed(1) + " KB" : (e["size"] as number) + " B"}` : "—"}</Td>
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
// Tab: Config
// ---------------------------------------------------------------------------

function ConfigTab() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [keys, setKeys] = useState<Record<string, unknown> | null>(null);
  const [schedule, setSchedule] = useState<unknown[]>([]);

  const load = useCallback(async () => {
    const [c, k, s] = await Promise.all([
      g<Record<string, unknown>>("/api/config"),
      g<Record<string, unknown>>("/api/keys"),
      g<unknown[] | Record<string, unknown>>("/api/schedule"),
    ]);
    setConfig(c);
    setKeys(k);
    setSchedule(asList(s));
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 60_000);
    return () => clearInterval(t);
  }, [load]);

  const keyNames = keys && Array.isArray(keys["keys"]) ? (keys["keys"] as unknown[]) : [];

  return (
    <div data-testid="tektos-panels-config">
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>API keys ({keyNames.length})</h2>
        {keyNames.length === 0 ? (
          <EmptyNote>no API keys configured</EmptyNote>
        ) : (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {keyNames.map((k, i) => {
              const name = typeof k === "string" ? k : str((k as Record<string, unknown>)["name"]);
              return (
                <span
                  key={i}
                  style={{
                    fontSize: "var(--font-xs, 0.75rem)",
                    fontFamily: "var(--font-mono, ui-monospace, monospace)",
                    border: "1px solid var(--color-border-soft, #333)",
                    borderRadius: 4,
                    padding: "3px 8px",
                  }}
                >
                  {name || `key-${i}`}
                </span>
              );
            })}
          </div>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Scheduled jobs ({schedule.length})</h2>
        {schedule.length === 0 ? (
          <EmptyNote>no scheduled jobs</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Job</Th>
                <Th>When</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {(schedule as Array<Record<string, unknown>>).slice(0, 30).map((j, i) => (
                <tr key={str(j["id"]) || i}>
                  <Td mono>{str(j["name"]) || str(j["id"]) || "—"}</Td>
                  <Td>{str(j["schedule"]) || str(j["cron"]) || "—"}</Td>
                  <Td>
                    <HealthValue value={str(j["status"]) || "—"} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Runtime config</h2>
        <pre
          data-testid="tektos-panels-config-body"
          style={{ margin: 0, maxHeight: 320, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}
        >
          {config === null ? "loading…" : JSON.stringify(config["config"] ?? config, null, 1)}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Hooks & Drill-down (hooks, repoMap, routing, tools schema,
// skills search, db table drill, archive sessions, session/state drill)
// ---------------------------------------------------------------------------

function DrillTab() {
  const [hooks, setHooks] = useState<Record<string, unknown>[]>([]);
  const [repo, setRepo] = useState<Record<string, unknown> | null>(null);
  const [routing, setRouting] = useState<Record<string, unknown> | null>(null);
  const [toolSchemas, setToolSchemas] = useState<Record<string, unknown>[]>([]);
  const [skillQuery, setSkillQuery] = useState("");
  const [skillHits, setSkillHits] = useState<Record<string, unknown>[]>([]);
  const [skillSearched, setSkillSearched] = useState(false);
  const [skillDetail, setSkillDetail] = useState<Record<string, unknown> | null>(null);
  const [skillDetailId, setSkillDetailId] = useState("");
  const [tableName, setTableName] = useState("events");
  const [tableSample, setTableSample] = useState<Record<string, unknown> | null>(null);
  const [tableAnalyze, setTableAnalyze] = useState<Record<string, unknown> | null>(null);
  const [archive, setArchive] = useState<Record<string, unknown>[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [sessionDetail, setSessionDetail] = useState<unknown>(null);
  const [sessionEvents, setSessionEvents] = useState<unknown>(null);
  const [sessionState, setSessionState] = useState<unknown>(null);
  const [drilled, setDrilled] = useState(false);

  const load = useCallback(async () => {
    const [h, r, rt, ts, ar] = await Promise.all([
      g<Record<string, unknown>>("/api/hooks"),
      g<Record<string, unknown>>("/api/repoMap/status"),
      g<Record<string, unknown>>("/api/routing/decide"),
      g<Record<string, unknown>>("/api/tools/schema"),
      g<unknown[] | Record<string, unknown>>("/api/archive/sessions"),
    ]);
    setHooks(asList(h?.["hooks"]) as Record<string, unknown>[]);
    setRepo(r);
    setRouting(rt);
    setToolSchemas(asList(ts?.["tools"]) as Record<string, unknown>[]);
    setArchive(asList(ar) as Record<string, unknown>[]);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  const runSkillSearch = async () => {
    setSkillSearched(true);
    const q = encodeURIComponent(skillQuery.trim() || " ");
    const r = await g<Record<string, unknown>>(`/api/skills/search?query=${q}`);
    setSkillHits(asList(r?.["skills"]) as Record<string, unknown>[]);
  };

  const runSkillDetail = async (id: string) => {
    setSkillDetailId(id);
    const r = await g<Record<string, unknown>>(`/api/skills/${encodeURIComponent(id)}`);
    setSkillDetail(r);
  };

  const runTableDrill = async () => {
    const name = tableName.trim() || "events";
    const [s, a] = await Promise.all([
      g<Record<string, unknown>>(`/api/db/tables/${encodeURIComponent(name)}/sample?limit=20`),
      g<Record<string, unknown>>(`/api/db/tables/${encodeURIComponent(name)}/analyze`),
    ]);
    setTableSample(s);
    setTableAnalyze(a);
  };

  const runSessionDrill = async () => {
    const id = sessionId.trim();
    if (!id) return;
    setDrilled(true);
    const [d, e, st] = await Promise.all([
      g(`/api/sessions/${encodeURIComponent(id)}`, ""),
      g(`/api/sessions/${encodeURIComponent(id)}/events?limit=50`, ""),
      g(`/api/state/${encodeURIComponent(id)}`, ""),
    ]);
    setSessionDetail(d);
    setSessionEvents(e);
    setSessionState(st);
  };

  const stats = repo && isObj(repo["stats"]) ? (repo["stats"] as Record<string, unknown>) : null;

  return (
    <div data-testid="tektos-panels-drill">
      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Event hooks ({hooks.length})</h2>
        {hooks.length === 0 ? (
          <EmptyNote>no hooks registered</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>Event</Th>
                <Th>Handlers</Th>
              </tr>
            </thead>
            <tbody>
              {hooks.map((h, i) => (
                <tr key={str(h["event_type"]) || i}>
                  <Td mono>{str(h["event_type"]) || "—"}</Td>
                  <Td mono>{Array.isArray(h["handlers"]) ? (h["handlers"] as unknown[]).join(", ") : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="RepoMap" value={<HealthValue value={str(repo?.["status"]) || "—"} />} />
        {stats ? (
          <>
            <Metric label="Entries" value={String(stats["total_entries"] ?? "—")} />
            <Metric label="Files" value={String(stats["files"] ?? "—")} />
            <Metric label="Dirs" value={String(stats["directories"] ?? "—")} />
          </>
        ) : null}
        <span style={{ flex: 1 }} />
        {routing ? (
          <>
            <Metric label="Routing" value={str(routing["recommended_model"]) || "—"} />
            <Metric label="Category" value={str(routing["category"]) || "—"} />
            <Metric label="Confidence" value={routing["confidence"] !== undefined ? Number(routing["confidence"]).toFixed(2) : "—"} />
          </>
        ) : null}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Tool schemas ({toolSchemas.length})</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {toolSchemas.map((t, i) => (
            <span
              key={str(t["name"]) || i}
              style={{
                fontSize: "var(--font-xs, 0.75rem)",
                fontFamily: "var(--font-mono, ui-monospace, monospace)",
                border: "1px solid var(--color-border-soft, #333)",
                borderRadius: 4,
                padding: "3px 8px",
              }}
            >
              {str(t["name"]) || `tool-${i}`}
            </span>
          ))}
          {toolSchemas.length === 0 && <EmptyNote>no tool schemas</EmptyNote>}
        </div>
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Skill search</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            data-testid="tektos-panels-skill-query"
            style={{ ...inputStyle, flex: 1, minWidth: 180, maxWidth: 380 }}
            placeholder="search skills by name/description…"
            value={skillQuery}
            onChange={(e) => setSkillQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSkillSearch();
            }}
          />
          <button data-testid="tektos-panels-skill-search-btn" style={btnStyle} onClick={() => void runSkillSearch()}>
            Search
          </button>
        </div>
        {skillSearched && (
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10 }}>
            <thead>
              <tr>
                <Th>Matched</Th>
                <Th>Name</Th>
                <Th>Category</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {skillHits.length === 0 ? (
                <tr>
                  <Td colSpan={4}>no matches</Td>
                </tr>
              ) : (
                skillHits.slice(0, 20).map((s, i) => (
                  <tr key={str(s["id"]) || i}>
                    <Td>{typeof s["score"] === "number" ? (s["score"] as number).toFixed(3) : "—"}</Td>
                    <Td mono>{str(s["name"]) || "—"}</Td>
                    <Td>{str(s["category"]) || "—"}</Td>
                    <Td>
                      <button
                        data-testid={`tektos-panels-skill-view-${i}`}
                        style={{ ...btnStyle, padding: "2px 8px", fontSize: "var(--font-xs, 0.75rem)" }}
                        onClick={() => void runSkillDetail(str(s["id"]))}
                      >
                        {skillDetailId === str(s["id"]) ? "loading…" : "View"}
                      </button>
                    </Td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
        {skillDetail && (
          <JsonPre data={skillDetail} label={`Skill: ${str(skillDetail["name"])}`} maxH={220} />
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Table drill-down (sample + column stats)</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            data-testid="tektos-panels-table-name"
            style={{ ...inputStyle, width: 220, maxWidth: "40vw" }}
            placeholder="table name"
            value={tableName}
            onChange={(e) => setTableName(e.target.value)}
          />
          <button data-testid="tektos-panels-table-drill-btn" style={btnStyle} onClick={() => void runTableDrill()}>
            Drill
          </button>
        </div>
        {tableSample && (
          <pre style={{ margin: "10px 0 0", maxHeight: 220, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}>
            {`rows: ${String(tableSample["count"] ?? tableSample["data"] ? (tableSample["data"] as unknown[])?.length ?? "—" : "—")}`}
            {"\n"}
            {JSON.stringify(tableSample["data"] ?? tableSample, null, 1).slice(0, 4000)}
          </pre>
        )}
        {tableAnalyze && (
          <pre style={{ margin: "10px 0 0", maxHeight: 220, overflow: "auto", fontSize: "var(--font-xs, 0.75rem)", fontFamily: "var(--font-mono, ui-monospace, monospace)", whiteSpace: "pre-wrap" }}>
            {JSON.stringify(tableAnalyze, null, 1).slice(0, 4000)}
          </pre>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Archived sessions ({archive.length})</h2>
        {archive.length === 0 ? (
          <EmptyNote>no archived sessions</EmptyNote>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>ID</Th>
                <Th>Title</Th>
                <Th>Archived</Th>
              </tr>
            </thead>
            <tbody>
              {archive.slice(0, 30).map((a, i) => (
                <tr key={str(a["id"]) || i}>
                  <Td mono>{str(a["id"]).slice(0, 8) || "—"}</Td>
                  <Td>{str(a["title"]) || str(a["summary"]).slice(0, 80) || "—"}</Td>
                  <Td mono>{str(a["archived_at"] || a["timestamp"]).slice(0, 19).replace("T", " ") || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={panelStyle}>
        <h2 style={{ margin: "0 0 10px", fontSize: "var(--font-md, 0.9375rem)" }}>Session / state drill-down</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            data-testid="tektos-panels-session-id"
            style={{ ...inputStyle, flex: 1, minWidth: 220, maxWidth: 480 }}
            placeholder="session id (from /tektos-ultima/sessions)"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
          />
          <button
            data-testid="tektos-panels-session-drill-btn"
            style={btnStyle}
            disabled={!sessionId.trim()}
            onClick={() => void runSessionDrill()}
          >
            Drill
          </button>
        </div>
        {drilled && (
          <>
            <JsonPre data={sessionDetail} label="Session detail" maxH={180} />
            <JsonPre data={sessionEvents} label="Recent events" maxH={180} />
            <JsonPre data={sessionState} label="State snapshot" maxH={180} />
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TektosUltimaPanelsPage() {
  const [tab, setTab] = useState<TabId>("status");
  const [upstreamDown, setUpstreamDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const probe = async () => {
      // Stage 14.1 (ADR-109 exit gate): kernel-native /health.
      const h = await g("/health", "");
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
    <main data-testid="tektos-panels-page" style={{ display: "flex", flexDirection: "column", height: FRAME_HEIGHT, padding: 0 }}>
      <header
        data-testid="tektos-panels-header"
        style={{
          padding: "var(--space-2, 8px) var(--space-3, 12px)",
          borderBottom: "1px solid var(--color-border-soft, #333)",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <h1 style={{ margin: 0, fontSize: "var(--font-lg, 1.125rem)" }}>Tektos Panels</h1>
        <span style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>read-only subsystem status</span>
        <span
          style={{
            fontSize: "var(--font-sm, 0.8125rem)",
            fontWeight: 600,
            color: upstreamDown ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)",
          }}
        >
          ● {upstreamDown ? "upstream offline" : "online"}
        </span>
        <span style={{ flex: 1 }} />
        <Link href="/tektos-ultima/ops" style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}>
          Ops →
        </Link>
        <Link href="/tektos-ultima" style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}>
          ← Dashboard
        </Link>
      </header>

      <nav
        data-testid="tektos-panels-tabs"
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
            data-testid={`tektos-panels-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "8px 14px",
              fontSize: "var(--font-sm, 0.8125rem)",
              whiteSpace: "nowrap",
              color: tab === t.id ? "var(--color-text, #eee)" : "var(--color-text-dim, #888)",
              borderBottom: tab === t.id ? "2px solid var(--color-akshobhya, #6a9eff)" : "2px solid transparent",
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <section style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "var(--space-3, 12px)" }}>
        {tab === "status" && <StatusTab />}
        {tab === "planner" && <PlannerTab />}
        {tab === "context" && <ContextTab />}
        {tab === "immune" && <ImmuneTab />}
        {tab === "dreamtime" && <DreamtimeTab />}
        {tab === "metabolism" && <MetabolismTab />}
        {tab === "agents" && <AgentsTab />}
        {tab === "skills" && <SkillsLifecycleTab />}
        {tab === "actions" && <ActionsTab />}
        {tab === "terminal" && <TerminalTab />}
        {tab === "selfimp" && <SelfImpTab />}
        {tab === "schema" && <SchemaTab />}
        {tab === "hindsight" && <HindsightTab />}
        {tab === "axioms" && <AxiomsTab />}
        {tab === "knowledge" && <KnowledgeTab />}
        {tab === "config" && <ConfigTab />}
        {tab === "drill" && <DrillTab />}
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
