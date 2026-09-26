"use client";

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
 *            /api/toolRouter/status /api/vision/status /api/voice/state
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

import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";

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
      g<Record<string, unknown>>("/api/toolRouter/status"),
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
      pick(tr, "Tool Router"),
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
// Tab: Agents (multi-agent orchestrator)
// ---------------------------------------------------------------------------

function AgentsTab() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [agents, setAgents] = useState<Record<string, unknown>[]>([]);

  const load = useCallback(async () => {
    // ADR-141 T1: re-pointed from the ADR-109 gateway (:8020/api/multi-agent-
    // orchestrator/*) to the kernel-native /tektos/api/orchestrator routes
    // (ADR-114 mount, ADR-141 donor-fidelity /status + /agents port).
    const [s, a] = await Promise.all([
      g<Record<string, unknown>>("/tektos/api/orchestrator/status", ""),
      g<unknown[]>("/tektos/api/orchestrator/agents", ""),
    ]);
    setStatus(s);
    setAgents(asList(a) as Record<string, unknown>[]);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15_000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div data-testid="tektos-panels-agents">
      <div style={{ ...panelStyle, display: "flex", gap: 18, flexWrap: "wrap" }}>
        <Metric label="Orchestrator" value={<HealthValue value={str(status?.["status"]) || "—"} />} />
      </div>

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
