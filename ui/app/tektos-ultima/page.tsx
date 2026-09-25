"use client";

/**
 * /tektos-ultima — native Tektos-Ultima dashboard (Tektos integration
 * Stage 9.2, ADR-109).
 *
 * Replaces the ADR-091 single-iframe page with a real Kosmos page that
 * drives the standalone Tektos API (:8020) through the kernel gateway
 * (`/api/tektos-ultima/gateway/*`, ADR-109 D1). The legacy microfrontend
 * is preserved at `/tektos-ultima/legacy` until Stage 9.5 parity
 * verification retires it (ADR-091 surface unchanged until then).
 *
 * The page renders a subsystem status grid — one card per Tektos
 * subsystem — polled every 10 s. Every card degrades independently:
 * a failed endpoint marks that card `degraded` without affecting the
 * rest of the grid, mirroring the ADR-101 soft-fail spirit.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

const GATEWAY = "/api/tektos-ultima/gateway";
const POLL_MS = 10_000;
const FRAME_HEIGHT = "calc(100vh - var(--top-bar-h, 48px))";

type CardStatus = "healthy" | "degraded" | "down" | "pending";

const STATUS_COLOR: Record<CardStatus, string> = {
  healthy: "var(--color-amoghasiddhi)",
  degraded: "var(--color-ratnasambhava)",
  down: "var(--color-amitabha)",
  pending: "var(--color-text-dim)",
};

const STATUS_LABEL: Record<CardStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  down: "Down",
  pending: "…",
};

/** One subsystem card: endpoint + display rules. */
interface Subsystem {
  id: string;
  title: string;
  icon: string;
  endpoint: string;
}

const SUBSYSTEMS: Subsystem[] = [
  { id: "immune", title: "Immune System", icon: "🛡️", endpoint: "/api/immune/health" },
  { id: "thermal", title: "Thermal", icon: "🌡️", endpoint: "/api/thermal/status" },
  { id: "inference", title: "Inference", icon: "🧠", endpoint: "/api/inference/status" },
  { id: "memory", title: "Memory", icon: "🧩", endpoint: "/api/memory/stats" },
  { id: "rag", title: "RAG", icon: "📚", endpoint: "/api/rag/status" },
  { id: "skills", title: "Skills", icon: "⚡", endpoint: "/api/skills/stats" },
  { id: "tools", title: "Tools", icon: "🔧", endpoint: "/api/tools" },
  { id: "models", title: "Models", icon: "🎛️", endpoint: "/api/models" },
  { id: "plugins", title: "Plugins", icon: "🧩", endpoint: "/api/plugins" },
  { id: "neo4j", title: "Neo4j", icon: "🌐", endpoint: "/api/neo4j/status" },
  { id: "postgres", title: "Postgres", icon: "🐘", endpoint: "/api/postgres/status" },
  { id: "redis", title: "Redis", icon: "⚡", endpoint: "/api/redis/status" },
  { id: "hindsight", title: "Hindsight", icon: "🔮", endpoint: "/api/hindsight/status" },
  { id: "self_repair", title: "Self-Repair", icon: "🔁", endpoint: "/api/self_repair/status" },
];

interface CardData {
  status: CardStatus;
  lines: string[];
  detail?: string;
}

interface DashboardState {
  upstream: string | null;
  reachable: boolean;
  activeSessions: number | null;
  llmModel: string | null;
  cards: Record<string, CardData>;
}

const INITIAL_STATE: DashboardState = {
  upstream: null,
  reachable: false,
  activeSessions: null,
  llmModel: null,
  cards: Object.fromEntries(SUBSYSTEMS.map((s) => [s.id, { status: "pending", lines: [""] }])),
};

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

/**
 * Per-subsystem display rules. `lines` = up to two headline values;
 * `detail` = one muted sub-line. Status is derived from the same
 * fields so the pill never contradicts the numbers.
 */
function parseCard(sub: Subsystem, data: unknown): CardData {
  const o = isObj(data) ? data : null;
  switch (sub.id) {
    case "immune": {
      const status = str(o?.status);
      const healthy = status === "healthy" || num(o?.overall) === 1;
      const threats = num(o?.active_threats) ?? 0;
      const uptime = Math.round((num(o?.uptime_seconds) ?? 0) / 3600);
      return {
        status: healthy && threats === 0 ? "healthy" : "degraded",
        lines: [status ?? "unknown", `${threats} active threats`],
        detail: `overall ${o?.overall ?? "?"} · ${uptime} h uptime`,
      };
    }
    case "thermal": {
      const gpu = isObj(o?.gpu) ? o.gpu : null;
      const cpu = isObj(o?.cpu) ? o.cpu : null;
      const temp = num(gpu?.temperature);
      const action = str(gpu?.action);
      const healthy = action === "relax" || action === "hold";
      return {
        status: healthy ? "healthy" : "degraded",
        lines: [
          temp !== null ? `${temp.toFixed(0)}°C GPU` : "no GPU data",
          `${num(cpu?.temperature) ?? "?"}°C CPU · ${action ?? "?"}`,
        ],
        detail: str(gpu?.reason) ?? undefined,
      };
    }
    case "inference": {
      const ok = o?.llm_available === true && (o?.health === "ok" || o?.status === "active");
      return {
        status: ok ? "healthy" : "degraded",
        lines: [str(o?.model) ?? "no model", str(o?.base_url) ?? ""],
        detail: `health ${str(o?.health) ?? "?"} · ${str(o?.status) ?? "?"}`,
      };
    }
    case "memory": {
      const longTerm = num(o?.long_term_count) ?? 0;
      const working = num(o?.working_count) ?? 0;
      const procedural = num(o?.procedural_count) ?? 0;
      const balance = isObj(o?.summary) && isObj(o.summary.hemisphere_balance) ? o.summary.hemisphere_balance : null;
      const left = num(balance?.left) ?? 0;
      const right = num(balance?.right) ?? 0;
      return {
        status: longTerm > 0 ? "healthy" : "degraded",
        lines: [`${longTerm.toLocaleString()} long-term`, `${working} working · ${procedural} procedural`],
        detail: `hemispheres L ${left.toLocaleString()} / R ${right.toLocaleString()}`,
      };
    }
    case "rag": {
      const stats = isObj(o?.stats) ? o.stats : null;
      const indexed = num(stats?.indexed_count) ?? 0;
      const embedder = stats?.has_embedder === true;
      const retriever = stats?.has_retriever === true;
      const ok = o?.status === "initialized" && embedder && retriever;
      return {
        status: ok ? "healthy" : "degraded",
        lines: [`${indexed.toLocaleString()} indexed`, `top-k ${num(stats?.top_k) ?? "?"}`],
        detail: `embedder ${embedder ? "on" : "off"} · retriever ${retriever ? "on" : "off"}`,
      };
    }
    case "skills": {
      const total = num(o?.total_skills) ?? 0;
      const active = num(o?.active_skills) ?? 0;
      const top = Array.isArray(o?.top_skills) && isObj(o.top_skills[0]) ? o.top_skills[0] : null;
      return {
        status: total > 0 && active === total ? "healthy" : "degraded",
        lines: [`${active}/${total} active`, str(top?.name) ?? "no usage yet"],
        detail: `${Array.isArray(o?.categories) ? (o.categories as unknown[]).length : 0} categories`,
      };
    }
    case "tools": {
      if (!Array.isArray(data)) break;
      const tools = data as unknown[];
      const enabled = tools.filter((t) => isObj(t) && t.enabled === true).length;
      const names = tools.filter((t) => isObj(t) && t.enabled === true).slice(0, 3).map((t) => str(isObj(t) ? t.name : null) ?? "?");
      return {
        status: enabled > 0 ? "healthy" : "down",
        lines: [`${enabled}/${tools.length} enabled`, names.join(" · ") || "none enabled"],
        detail: tools.length > 3 ? `+${tools.length - 3} more` : undefined,
      };
    }
    case "models": {
      if (!Array.isArray(data)) break;
      const models = data as Array<Record<string, unknown> | null>;
      const rec = models.find((m) => isObj(m) && m.recommended === true) ?? null;
      const first = models[0];
      return {
        status: models.length > 0 ? "healthy" : "down",
        lines: [`${models.length} available`, str(rec?.id) ?? str(isObj(first) ? first.id : null) ?? ""],
        detail: str(rec?.role) ?? "no recommended",
      };
    }
    case "plugins": {
      const count = num(o?.count) ?? 0;
      const names = Array.isArray(o?.plugins) ? (o.plugins as unknown[]).slice(0, 4).map((p) => str(isObj(p) ? (p as Record<string, unknown>).name : null) ?? "?") : [];
      return {
        status: count > 0 ? "healthy" : "degraded",
        lines: [`${count} loaded`, names.join(" · ") || "none"],
      };
    }
    case "neo4j":
    case "hindsight": {
      const status = str(o?.status);
      const healthy = o?.healthy === true && status === "connected";
      return {
        status: healthy ? "healthy" : "down",
        lines: [status ?? "unknown", str(o?.base_url ?? o?.uri) ?? "unconfigured"],
        detail: str(o?.error) ?? undefined,
      };
    }
    case "postgres": {
      const connected = o?.connected === true;
      const status = str(o?.status);
      return {
        status: connected ? "healthy" : "down",
        lines: [status ?? "unknown", `${str(o?.host) ?? "?"}:${num(o?.port) ?? "?"}/${str(o?.database_name) ?? "?"}`],
        detail: str(o?.error) ?? undefined,
      };
    }
    case "redis": {
      const ok = o?.ping_ok === true && o?.connected === true;
      return {
        status: ok ? "healthy" : "down",
        lines: [str(o?.status) ?? "unknown", `${str(o?.host) ?? "?"}:${num(o?.port) ?? "?"}`],
        detail: str(o?.error) ?? undefined,
      };
    }
    case "self_repair": {
      const running = o?.running === true;
      const repairs = num(o?.completed_repairs) ?? 0;
      const strategies = num(o?.strategies_registered) ?? 0;
      return {
        status: running ? "healthy" : "down",
        lines: [running ? "watching" : "not running", `${repairs} repairs · ${strategies} strategies`],
        detail: running ? `${Math.round((num(o?.uptime_seconds) ?? 0) / 3600)} h uptime` : undefined,
      };
    }
    default:
      return { status: "pending", lines: [""] };
  }
  return { status: "down", lines: ["unexpected shape"], detail: undefined };
}

/**
 * Gateway reachability check. GET /health through the kernel gateway:
 * 200 → upstream reachable (body carries the Tektos health JSON);
 * 503/502 → kernel reachable but Tektos down (ADR-109 typed envelope);
 * any other failure → kernel itself unreachable.
 */
async function fetchHealth(): Promise<{ reachable: boolean; upstream: string | null; body: unknown }> {
  let res: Response;
  try {
    res = await fetch(`${GATEWAY}/health`, { cache: "no-store" });
  } catch {
    return { reachable: false, upstream: null, body: null };
  }
  if (!res.ok) return { reachable: false, upstream: null, body: null };
  let json: unknown = null;
  try {
    json = await res.json();
  } catch {
    /* non-JSON upstream health — still reachable */
  }
  const o = isObj(json) ? json : null;
  return {
    reachable: o?.reachable === true,
    upstream: str(o?.upstream),
    body: isObj(o?.body) ? o.body : null,
  };
}

async function fetchJson(endpoint: string): Promise<{ ok: boolean; data: unknown }> {
  try {
    const res = await fetch(`${GATEWAY}${endpoint}`, { cache: "no-store" });
    if (!res.ok) return { ok: false, data: null };
    return { ok: true, data: await res.json() };
  } catch {
    return { ok: false, data: null };
  }
}

export default function TektosUltimaDashboard() {
  const [state, setState] = useState<DashboardState>(INITIAL_STATE);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const [health, ...results] = await Promise.all([
        fetchHealth(),
        ...SUBSYSTEMS.map((s) => fetchJson(s.endpoint)),
      ]);
      const healthBody = isObj(health.body) ? health.body : null;
      const cards: Record<string, CardData> = {};
      SUBSYSTEMS.forEach((s, i) => {
        const r = results[i];
        cards[s.id] = r.ok ? parseCard(s, r.data) : { status: "degraded", lines: ["unreachable"], detail: "gateway request failed" };
      });
      setState({
        upstream: health.upstream ?? "http://127.0.0.1:8020",
        reachable: health.reachable,
        activeSessions: num(healthBody?.active_sessions),
        llmModel: str(healthBody?.llm_model),
        cards,
      });
      setLastUpdated(new Date());
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const healthyCount = Object.values(state.cards).filter((c) => c.status === "healthy").length;

  return (
    <main
      data-testid="tektos-ultima-page"
      style={{ display: "flex", flexDirection: "column", height: FRAME_HEIGHT, padding: 0 }}
    >
      <header
        data-testid="tektos-ultima-header"
        style={{
          padding: "var(--space-2, 8px) var(--space-3, 12px)",
          borderBottom: "1px solid var(--color-border-soft, #333)",
          display: "flex",
          alignItems: "baseline",
          gap: "12px",
          flexWrap: "wrap",
        }}
      >
        <h1 data-testid="tektos-ultima-heading" style={{ margin: 0, fontSize: "var(--font-lg, 1.125rem)" }}>
          Tektos-Ultima
        </h1>
        <span
          data-testid="tektos-ultima-status-pill"
          style={{
            fontSize: "var(--font-sm, 0.8125rem)",
            color: state.reachable ? STATUS_COLOR.healthy : STATUS_COLOR.down,
            fontWeight: 600,
          }}
        >
          {state.reachable
            ? `● online · ${healthyCount}/${SUBSYSTEMS.length} subsystems healthy`
            : "● offline"}
        </span>
        <span
          data-testid="tektos-ultima-upstream"
          style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-text-dim, #888)" }}
        >
          {state.upstream ?? "…"}
          {state.llmModel ? ` · ${state.llmModel}` : ""}
          {state.activeSessions !== null ? ` · ${state.activeSessions} session${state.activeSessions === 1 ? "" : "s"}` : ""}
        </span>
        {lastUpdated && (
          <span style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>
            updated {lastUpdated.toLocaleTimeString()}
          </span>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: "14px" }}>
          <Link
            data-testid="tektos-ultima-sessions-link"
            href="/tektos-ultima/sessions"
            style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}
          >
            Sessions →
          </Link>
          <Link
            data-testid="tektos-ultima-legacy-link"
            href="/tektos-ultima/legacy"
            style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}
          >
            Legacy UI →
          </Link>
        </div>
      </header>

      {!state.reachable && (
        <div
          data-testid="tektos-ultima-offline-banner"
          role="alert"
          style={{
            margin: "12px 12px 0",
            padding: "8px 12px",
            borderRadius: "var(--radius-md, 6px)",
            border: "1px solid var(--color-amitabha, #c66)",
            color: "var(--color-amitabha, #c66)",
            fontSize: "var(--font-sm, 0.8125rem)",
          }}
        >
          Tektos API ({state.upstream ?? "upstream"}) is not reachable through the kernel gateway.
          Cards below show the last known state.
        </div>
      )}

      <section
        aria-label="Tektos subsystem status"
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "var(--space-3, 12px)",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
          gap: "12px",
          alignContent: "start",
        }}
      >
        {SUBSYSTEMS.map((s) => {
          const card = state.cards[s.id];
          return (
            <article
              key={s.id}
              data-testid={`tektos-ultima-card-${s.id}`}
              style={{
                background: "var(--color-surface, #1a1a1a)",
                border: "1px solid var(--color-border-soft, #2a2a2a)",
                borderRadius: "var(--radius-md, 6px)",
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "6px",
                minHeight: "108px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span aria-hidden>{s.icon}</span>
                <span style={{ fontWeight: 600, fontSize: "var(--font-sm, 0.875rem)" }}>{s.title}</span>
                <span
                  data-testid={`tektos-ultima-card-status-${s.id}`}
                  style={{
                    marginLeft: "auto",
                    fontSize: "var(--font-xs, 0.75rem)",
                    fontWeight: 600,
                    color: STATUS_COLOR[card.status],
                  }}
                >
                  {STATUS_LABEL[card.status]}
                </span>
              </div>
              {card.lines.map((line, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: i === 0 ? "var(--font-md, 1rem)" : "var(--font-sm, 0.8125rem)",
                    color: i === 0 ? "var(--color-text, #eee)" : "var(--color-text-soft, #bbb)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {line}
                </div>
              ))}
              {card.detail && (
                <div
                  style={{
                    fontSize: "var(--font-xs, 0.75rem)",
                    color: "var(--color-text-dim, #888)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {card.detail}
                </div>
              )}
            </article>
          );
        })}
      </section>
    </main>
  );
}
