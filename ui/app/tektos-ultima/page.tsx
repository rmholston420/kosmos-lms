"use client";

/**
 * /tektos-ultima — native Tektos-Ultima dashboard (Tektos integration
 * Stage 9.2, ADR-109).
 *
 * Replaces the ADR-091 single-iframe page with a real Kosmos page that
 * drives the standalone Tektos API (:8020) through the kernel gateway
 * (`/api/tektos-ultima/gateway/*`, ADR-109 D1). The ADR-091 legacy
 * microfrontend (iframe + postMessage bridge + `/tektos-ultima/frontend`
 * proxy) was retired in Stage 9.5 (ADR-113) after native parity
 * verification; its `frame-ancestors` CSP middleware survives
 * kernel-wide.
 *
 * The page renders a subsystem status grid — one card per Tektos
 * subsystem — polled every 10 s. Every card degrades independently:
 * a failed endpoint marks that card `degraded` without affecting the
 * rest of the grid, mirroring the ADR-101 soft-fail spirit.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

const GATEWAY = "/api/tektos-ultima/gateway";
/** ADR-117 (Stage 11.1): data-service cards hit kernel-native probes
 * directly instead of the ADR-109 gateway proxy to the retired :8020. */
const DATA_SERVICES = "/api/tektos/data-services";
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

/** One subsystem card: endpoint + display rules. `base` defaults to the
 * ADR-109 gateway; ADR-117 data-service cards point at the kernel-native
 * probes instead. */
interface Subsystem {
  id: string;
  title: string;
  icon: string;
  endpoint: string;
  base?: string;
}

const SUBSYSTEMS: Subsystem[] = [
  { id: "immune", title: "Immune System", icon: "🛡️", endpoint: "/api/immune/health", base: "" },
  { id: "thermal", title: "Thermal", icon: "🌡️", endpoint: "/api/thermal/status", base: "" },
  { id: "inference", title: "Inference", icon: "🧠", endpoint: "/api/inference/status", base: "" },
  { id: "memory", title: "Memory", icon: "🧩", endpoint: "/api/memory/stats", base: "" },
  { id: "rag", title: "RAG", icon: "📚", endpoint: "/api/rag/status", base: "" },
  { id: "skills", title: "Skills", icon: "⚡", endpoint: "/api/skills/stats", base: "" },
  { id: "tools", title: "Tools", icon: "🔧", endpoint: "/api/tools", base: "" },
  { id: "models", title: "Models", icon: "🎛️", endpoint: "/api/llm/status" },
  { id: "plugins", title: "Plugins", icon: "🧩", endpoint: "/api/plugins", base: "" },
  { id: "neo4j", title: "Neo4j", icon: "🌐", endpoint: "/neo4j/status", base: DATA_SERVICES },
  { id: "postgres", title: "Postgres", icon: "🐘", endpoint: "/postgres/status", base: DATA_SERVICES },
  { id: "redis", title: "Redis", icon: "⚡", endpoint: "/redis/status", base: DATA_SERVICES },
  { id: "hindsight", title: "Hindsight", icon: "🔮", endpoint: "/hindsight/status", base: DATA_SERVICES },
  { id: "qdrant", title: "Qdrant", icon: "📐", endpoint: "/qdrant/status", base: DATA_SERVICES },
  { id: "self_repair", title: "Self-Repair", icon: "🔁", endpoint: "/api/self_repair/status", base: "" },
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
      const dets: Array<{ name: string }> = Array.isArray(o?.detectors)
        ? (o.detectors as Array<{ name: string }>).slice(0, 4)
        : [];
      const detLine =
        dets.length > 0
          ? `${dets.length} detectors · ${dets.map((d) => d.name).join(", ")}`
          : "0 detectors";
      return {
        status: healthy && threats === 0 ? "healthy" : "degraded",
        lines: [status ?? "unknown", `${threats} active threats`, detLine],
        detail: `overall ${o?.overall ?? "?"} · ${uptime} h uptime`,
      };
    }
    case "thermal": {
      const gpu = isObj(o?.gpu) ? o.gpu : null;
      const cpu = isObj(o?.cpu) ? o.cpu : null;
      const cd = isObj(gpu?.cooldown) ? gpu.cooldown : null;
      const temp = num(gpu?.temperature);
      const action = str(gpu?.action);
      const healthy = action === "relax" || action === "hold";
      const lines: string[] = [
        temp !== null ? `${temp.toFixed(0)}°C GPU` : "no GPU data",
        `${num(cpu?.temperature) ?? "?"}°C CPU · ${action ?? "?"}`,
      ];
      // ADR-121 cooldown line: only when armed/active so the card stays
      // quiet at <75°C.
      if (cd && ((cd.active as boolean) || (cd.arming as boolean))) {
        const over = num(cd?.seconds_over) ?? 0;
        const thr = num(cd?.threshold_c) ?? 75;
        const sustain = num(cd?.sustain_s) ?? 60;
        lines.push(
          cd.active
            ? `❄ cooldown · ${over.toFixed(0)}s ≥ ${thr.toFixed(0)}°C`
            : `❄ arming ${over.toFixed(0)}/${sustain.toFixed(0)}s at ≥${thr.toFixed(0)}°C`,
        );
      }
      return {
        status: healthy ? "healthy" : "degraded",
        lines,
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
      const healthy = o?.healthy === true;
      const backend = str(o?.backend) ?? "none";
      const events = num(o?.memory_events);
      const ents = num(o?.entities);
      const quar = num(o?.quarantined) ?? 0;
      const errs = Array.isArray(o?.errors) ? (o.errors as string[]).join("; ") : "";
      const line = events === null ? "count unavailable" : `${events.toLocaleString()} memory events`;
      const sub = ents === null ? "" : `${ents.toLocaleString()} entities · ${quar} quarantined`;
      return {
        status: healthy && events !== null ? "healthy" : "degraded",
        lines: [line, sub].filter(Boolean),
        detail: errs || `backend: ${backend}`,
      };
    }
    case "rag": {
      // ADR-124 (Stage 11.8): kernel-native — /api/rag/status carries the
      // live embedder (llama.cpp qwen3-embedding on :8091, CPU) + Qdrant
      // vector store. `stats.indexed_count` is the REAL Qdrant point count;
      // top-k/similarity_threshold/query_count were fabricated by :8020 and
      // are gone. Nulls (None) mean "probe unavailable" — never 0.
      const stats = isObj(o?.stats) ? o.stats : null;
      const emb = isObj(o?.embedder) ? o.embedder : null;
      const vec = isObj(o?.vector) ? o.vector : null;
      const indexed = num(stats?.indexed_count);
      const colls = num(stats?.collections);
      const model = str(emb?.model) ?? "?";
      const ok = o?.healthy === true;
      return {
        status: ok ? "healthy" : "degraded",
        lines: [
          indexed !== null ? `${indexed.toLocaleString()} points` : "index unavailable",
          `embedder ${model}${colls !== null ? ` · ${colls} coll` : ""}`,
        ],
        detail: Array.isArray(o?.errors) && (o.errors as unknown[]).length > 0
          ? (o.errors as Array<unknown>).map((e) => str(e)).filter(Boolean).join(" · ")
          : `qwen :8091 (CPU) · vector ${vec?.healthy === true ? "up" : "down"}`,
      };
    }
    case "skills": {
      // ADR-125 (Stage 11.9): kernel-native — the old card proxied :8020's
      // standalone skill manager (24 vendored skills) which the kernel has no
      // referent for. The kernel's real skills-adjacent surface is the Tektos
      // Manager archetype tracker (ADR-108): recurring task patterns flagged
      // as skill candidates at threshold. Full skill registry deferred.
      const sk = isObj(o?.skills) ? (o.skills as Record<string, unknown>) : null;
      const wired = sk?.wired === true;
      const archetypes = num(sk?.archetypes) ?? 0;
      const atThreshold = num(sk?.at_threshold) ?? 0;
      const threshold = num(sk?.threshold);
      const events = num(sk?.total_events);
      const list = Array.isArray(sk?.archetype_list)
        ? (sk.archetype_list as Array<Record<string, unknown>>)
        : [];
      const top = list.find((a) => isObj(a) && a.at_threshold === true)
        ?? list[0] ?? null;
      const errs = Array.isArray(o?.errors) ? (o.errors as unknown[]) : [];
      return {
        status: wired ? "healthy" : "degraded",
        lines: [
          `${archetypes} archetypes · ${atThreshold} at threshold`,
          wired
            ? str(top?.category) ?? "no patterns yet (fills as Tektos runs)"
            : "manager offline (KOSMOS_TEKTOS_MANAGER=off)",
        ],
        detail: wired
          ? `threshold ${threshold ?? "?"} · ${events ?? "?"} events · registry deferred (ADR-108 D9)`
          : str(errs[0]) ?? "skill registry deferred (ADR-108 D9)",
      };
    }
    case "tools": {
      // ADR-126 (Stage 11.10): kernel-native — the old card proxied :8020's
      // executable TektosToolRegistry (11 descriptors + live call counters).
      // The kernel never boots that registry; its real tools surface is the
      // Tektos Tool Router (ADR-107): the static capability table + a
      // routing-only engine. Execution (approval gateway + sandbox) stays on
      // the standalone engine — the card says so honestly.
      const t = isObj(o?.tools) ? (o.tools as Record<string, unknown>) : null;
      const wired = t?.wired === true;
      const known = num(t?.known_tools) ?? 0;
      const cats = isObj(t?.categories) ? (t.categories as Record<string, unknown>) : {};
      const catStr = Object.entries(cats)
        .map(([k, v]) => `${k} ${num(v) ?? 0}`)
        .join(" · ");
      const buffered = num(t?.routes_buffered);
      const errs = Array.isArray(o?.errors) ? (o.errors as unknown[]) : [];
      return {
        status: wired ? "healthy" : "degraded",
        lines: [
          `${known} known tools · routing-only`,
          wired ? catStr || "no capability table" : "router offline (KOSMOS_TEKTOS_TOOL_ROUTER=off)",
        ],
        detail: wired
          ? `router live · ${buffered ?? 0} routes buffered · execution on standalone registry (ADR-107 D9)`
          : str(errs[0]) ?? "capability table only · execution deferred (ADR-107 D9)",
      };
    }
    case "models": {
      // ADR-119 (Stage 11.3): kernel-native — /api/llm/status carries the
      // lane catalog in `models` (primary llama.cpp / fallback Ollama).
      const models = Array.isArray(o?.models)
        ? (o.models as Array<Record<string, unknown> | null>)
        : [];
      const rec = models.find((m) => isObj(m) && m.active === true)
        ?? models.find((m) => isObj(m) && m.recommended === true) ?? null;
      const first = models[0];
      return {
        status: models.length > 0 ? "healthy" : "down",
        lines: [
          `${models.length} lanes`,
          str(rec?.id) ?? str(isObj(first) ? first.id : null) ?? "—",
        ],
        detail: str(rec?.backend) ?? "no model",
      };
    }
    case "plugins": {
      // ADR-127 (Stage 11.11): kernel-native — the old card proxied :8020's
      // functional search plugins (searxng/ddg/farfalle/tavily), which have
      // no kernel referent. Two corrections: the kernel's plugins/ packages
      // are SUBSYSTEMS (wired components), and the kernel's real plugin
      // mechanism is the frontend_contract descriptor registry. Tektos's
      // functional search providers remain on the standalone engine.
      const subs = isObj(o?.subsystems) ? (o.subsystems as Record<string, unknown>) : {};
      const wiredSubs = Object.values(subs).filter((v) => v === true).length;
      const totalSubs = Object.keys(subs).length;
      const up = isObj(o?.ui_plugins) ? (o.ui_plugins as Record<string, unknown>) : null;
      const uiCount = num(up?.count) ?? 0;
      const uiList = Array.isArray(up?.plugins) ? (up.plugins as Array<Record<string, unknown>>) : [];
      const uiNames = uiList.slice(0, 4).map((p) => str(p?.name) ?? "?");
      const errs = Array.isArray(o?.errors) ? (o.errors as unknown[]) : [];
      return {
        status: o?.healthy === true ? "healthy" : "degraded",
        lines: [
          `${wiredSubs}/${totalSubs} subsystems · ${uiCount} ui plugins`,
          uiNames.join(" · ") || (o?.healthy === true ? "no descriptor plugins" : str(errs[0]) ?? "contract offline"),
        ],
        detail: o?.healthy === true
          ? "functional registry pending · Tektos search providers on :8020"
          : "frontend contract failed to boot",
      };
    }
    case "neo4j":
    case "hindsight":
    case "qdrant": {
      // ADR-117 kernel-native probe: `healthy` is authoritative; `status`
      // distinguishes unreachable / auth_failed / unconfigured.
      const healthy = o?.healthy === true;
      const status = str(o?.status);
      const target =
        str(o?.uri ?? o?.base_url) ??
        `${str(o?.host) ?? "?"}:${num(o?.port) ?? "?"}`;
      const lines = [status ?? "unknown", target];
      if (o?.service === "qdrant") {
        lines.push(`${num(o?.collections) ?? 0} collections`);
      }
      return {
        status: healthy ? "healthy" : "down",
        lines: lines.slice(0, 2),
        detail:
          str(o?.detail) ??
          (o?.service === "qdrant" ? `${num(o?.collections) ?? 0} collections` : undefined),
      };
    }
    case "postgres": {
      const healthy = o?.healthy === true;
      const status = str(o?.status);
      return {
        status: healthy ? "healthy" : "down",
        lines: [status ?? "unknown", `${str(o?.host) ?? "?"}:${num(o?.port) ?? "?"}/${str(o?.database_name) ?? "?"}`],
        detail: str(o?.detail) ?? undefined,
      };
    }
    case "redis": {
      const healthy = o?.healthy === true;
      return {
        status: healthy ? "healthy" : "down",
        lines: [str(o?.status) ?? "unknown", `${str(o?.host) ?? "?"}:${num(o?.port) ?? "?"}`],
        detail: str(o?.detail) ?? undefined,
      };
    }
    case "self_repair": {
      // ADR-128 (Stage 11.12): kernel-native — the old card proxied :8020's
      // *executing* repair daemon (uptime, completed_repairs, effectiveness).
      // The kernel's surface is the propose-only SelfRepairProposer (ADR-095 D2):
      // HUMAN_REQUIRED approval, no execution. Strategies are static data.
      const p = isObj(o?.proposer) ? (o.proposer as Record<string, unknown>) : {};
      const wired = p.wired === true;
      const s = isObj(o?.strategies) ? (o.strategies as Record<string, unknown>) : {};
      const strategies = num(s.strategies_registered) ?? 0;
      const cats = isObj(s.categories) ? (s.categories as Record<string, unknown>) : {};
      const catLine = Object.entries(cats)
        .map(([c, n]) => `${c} ${num(n) ?? 0}`)
        .join(" · ");
      return {
        status: wired ? "healthy" : "degraded",
        lines: [
          wired ? "proposer live · HUMAN_REQUIRED" : "proposer offline",
          `${strategies} strategies · ${catLine || "catalog unavailable"}`,
        ],
        detail: "propose-only (ADR-095 D2) · execution on standalone repair engine (:8020)",
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

async function fetchJson(sub: Subsystem): Promise<{ ok: boolean; data: unknown }> {
  try {
    const res = await fetch(`${sub.base ?? GATEWAY}${sub.endpoint}`, { cache: "no-store" });
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
        ...SUBSYSTEMS.map((s) => fetchJson(s)),
      ]);
      const healthBody = isObj(health.body) ? health.body : null;
      const cards: Record<string, CardData> = {};
      SUBSYSTEMS.forEach((s, i) => {
        const r = results[i];
        cards[s.id] = r.ok
          ? parseCard(s, r.data)
          : { status: "down", lines: ["unreachable"], detail: "request failed" };
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
            data-testid="tektos-ultima-ops-link"
            href="/tektos-ultima/ops"
            style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}
          >
            Ops →
          </Link>
          <Link
            data-testid="tektos-ultima-panels-link"
            href="/tektos-ultima/panels"
            style={{ fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}
          >
            Panels →
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
