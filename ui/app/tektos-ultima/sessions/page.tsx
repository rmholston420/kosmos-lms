"use client";

/**
 * /tektos-ultima/sessions — session list + live chat (Tektos integration
 * Stage 9.3, ADR-111).
 *
 * Drives the standalone Tektos API (:8020) through the kernel gateway
 * (ADR-109 D1):
 *
 *   GET  /api/sessions                          — active session list (polled 10 s)
 *   POST /api/sessions                          — create session
 *   GET  /api/sessions/{id}/replay              — full event history (chat seed)
 *   POST /api/prompt/sse                        — OpenAI chat-completion SSE stream
 *   POST /api/sessions/{id}/interrupt           — interrupt in-flight turn
 *   POST /api/sessions/{id}/model               — switch model mid-session
 *   POST /api/sessions/{id}/fork                — fork into a new session
 *   POST /api/sessions/{id}/archive             — archive session
 *   GET  /api/models                            — model picker data
 *
 * Known limitation (donor protocol): user prompts are NOT persisted as
 * replay events — replay carries assistant/tool/system envelopes only.
 * So a re-opened session shows its assistant history, and user prompts
 * are re-shown for the lifetime of this tab. After a Tektos restart,
 * prompts are lost from this view (archived sessions still expose them
 * via /api/archive/sessions/{id}/messages, which is out of scope here).
 */

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";

const GATEWAY = "/api/tektos-ultima/gateway";
// ADR-131 (Stage 11.15): session *lifecycle* (list/create/get/fork/
// archive/interrupt/rename) is now kernel-native — same origin, no proxy.
// ADR-132 (Stage 11.16): models, model-switch and replay also kernel-native.
// Only conversation (prompt/sse) stays on the gateway until slice G lands.
const KERNEL = "";
const POLL_MS = 10_000;
const FRAME_HEIGHT = "calc(100vh - var(--top-bar-h, 48px))";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionInfo {
  id: string;
  model: string;
  cwd: string;
  status: string;
  title: string;
  tag: string;
  root_session_id: string | null;
  created_at: number;
  updated_at: number;
  is_active: boolean;
  is_failed: boolean;
  is_archived: boolean;
}

interface ModelInfo {
  id: string;
  name: string;
  role: string;
  description: string;
  recommended: boolean;
}

interface ToolRow {
  name: string;
  status?: string;
  output?: string;
  input?: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  reasoning?: string;
  tools: ToolRow[];
  done: boolean;
  stopReason?: string;
}

interface SystemNote {
  kind: "info" | "warn" | "error";
  text: string;
}

interface Conversation {
  messages: ChatMessage[];
  notes: SystemNote[];
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

// created_at/updated_at in the donor API are not always wall-clock epochs
// (session_manager mixes clocks) — only render when they plausibly are.
function fmtTime(t: unknown): string {
  if (typeof t !== "number" || !Number.isFinite(t) || t < 1e9) return "";
  return new Date(t * 1000).toLocaleString();
}

// ---------------------------------------------------------------------------
// Replay → conversation
// ---------------------------------------------------------------------------

/**
 * Fold a replay event list into a conversation. Assistant deltas and
 * reasoning stream into the current assistant message; a completed event
 * closes it. Tool events attach as compact rows on the current message.
 */
function replayToConversation(events: unknown): Conversation {
  const conv: Conversation = { messages: [], notes: [] };
  if (!Array.isArray(events)) return conv;
  // ref-object so the closure and the loop share one un-narrowed binding
  // (a plain `let current` gets stuck narrowed to `null` at loop-use sites)
  const cur: { msg: ChatMessage | null } = { msg: null };
  const ensureAssistant = (): ChatMessage => {
    if (!cur.msg) {
      cur.msg = { role: "assistant", text: "", tools: [], done: false };
      conv.messages.push(cur.msg);
    }
    return cur.msg;
  };
  for (const ev of events) {
    if (!isObj(ev)) continue;
    const type = String(ev.type ?? "");
    const p = isObj(ev.payload) ? ev.payload : {};
    switch (type) {
      case "assistant.delta": {
        const msg = ensureAssistant();
        msg.text += String(p.text ?? "");
        break;
      }
      case "assistant.reasoning": {
        const msg = ensureAssistant();
        msg.reasoning = (msg.reasoning ?? "") + String(p.text ?? "");
        break;
      }
      case "assistant.completed": {
        if (cur.msg) {
          cur.msg.done = true;
          cur.msg.stopReason = String(p.stop_reason ?? "end_turn");
        }
        break;
      }
      case "tool.started": {
        const msg = ensureAssistant();
        msg.tools.push({
          name: String(p.tool_name ?? "tool"),
          input: p.tool_input ? safeJson(p.tool_input) : undefined,
        });
        break;
      }
      case "tool.completed": {
        const msg = ensureAssistant();
        const row = [...msg.tools].reverse().find((t) => !t.status);
        if (row) {
          row.status = String(p.status ?? "done");
          row.output = typeof p.output === "string" ? p.output.slice(0, 2000) : undefined;
        }
        break;
      }
      case "session.interrupted": {
        if (cur.msg) cur.msg.done = true;
        conv.notes.push({ kind: "warn", text: "Session interrupted" });
        break;
      }
      case "session.failed": {
        if (cur.msg) cur.msg.done = true;
        conv.notes.push({ kind: "error", text: String(p.error ?? "Session failed") });
        break;
      }
      case "system.message": {
        conv.notes.push({ kind: "info", text: String(p.message ?? "") });
        break;
      }
      case "resource.warning":
      case "loop_safety.warning":
      case "self_improvement.tick": {
        const d = isObj(p.details) ? p.details : null;
        const msg = String(p.message ?? type);
        conv.notes.push({ kind: "warn", text: msg + (d && d.message ? ` — ${String(d.message)}` : "") });
        break;
      }
      default:
        break; // session.created/updated, plan.*, artifact.* — not chat content
    }
  }
  return conv;
}

function safeJson(v: unknown): string {
  try {
    return JSON.stringify(v).slice(0, 300);
  } catch {
    return String(v).slice(0, 300);
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TektosSessionsPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [convs, setConvs] = useState<Record<string, Conversation>>({});
  const [loadingConv, setLoadingConv] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const [newModel, setNewModel] = useState("");
  const [newCwd, setNewCwd] = useState("");
  const [creating, setCreating] = useState(false);
  const [upstreamDown, setUpstreamDown] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inFlightList = useRef(false);

  const selectedSession = useMemo(
    () => sessions.find((s) => s.id === selected) ?? null,
    [sessions, selected],
  );
  const conv = selected ? convs[selected] : undefined;

  // --- session list poll ---------------------------------------------------
  const refreshList = useCallback(async () => {
    if (inFlightList.current) return;
    inFlightList.current = true;
    try {
      const r = await fetch(`${KERNEL}/api/sessions`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body: unknown = await r.json();
      if (Array.isArray(body)) {
        setSessions(body.filter(isObj).map((s) => s as unknown as SessionInfo));
        setUpstreamDown(false);
      }
      setLastUpdated(new Date());
    } catch {
      setUpstreamDown(true);
    } finally {
      inFlightList.current = false;
    }
  }, []);

  useEffect(() => {
    void refreshList();
    const t = setInterval(() => void refreshList(), POLL_MS);
    return () => clearInterval(t);
  }, [refreshList]);

  // --- models --------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${KERNEL}/api/models`, { cache: "no-store" });
        if (!r.ok) return;
        const body: unknown = await r.json();
        if (Array.isArray(body)) {
          const list = body.filter(isObj).map((m) => m as unknown as ModelInfo);
          setModels(list);
          const rec = list.find((m) => m.recommended) ?? list[0];
          if (rec) setNewModel(rec.id);
        }
      } catch {
        /* model picker degrades to empty select */
      }
    })();
  }, []);

  // --- conversation load (replay) ------------------------------------------
  const loadConv = useCallback(async (id: string) => {
    setLoadingConv(true);
    try {
      const r = await fetch(`${KERNEL}/api/sessions/${id}/replay`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const events: unknown = await r.json();
      setConvs((prev) => {
        if (prev[id]) return prev; // already loaded — keep in-tab state
        return { ...prev, [id]: replayToConversation(events) };
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingConv(false);
    }
  }, []);

  // --- create --------------------------------------------------------------
  const createSession = useCallback(async () => {
    if (!newModel) return;
    setCreating(true);
    setError(null);
    try {
      const r = await fetch(`${KERNEL}/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: newModel, cwd: newCwd.trim() || ".", permission_mode: "auto" }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text().catch(() => "")}`.slice(0, 160));
      const s = (await r.json()) as SessionInfo;
      await refreshList();
      setSelected(s.id);
      void loadConv(s.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }, [newModel, newCwd, refreshList, loadConv]);

  // --- send (SSE) ------------------------------------------------------------
  const send = useCallback(async () => {
    const prompt = input.trim();
    if (!prompt || !selected || streaming) return;
    const id = selected;
    setInput("");
    setError(null);
    setConvs((prev) => {
      const c = prev[id] ?? { messages: [], notes: [] };
      return {
        ...prev,
        [id]: {
          ...c,
          messages: [...c.messages, { role: "user", text: prompt, tools: [], done: true }],
        },
      };
    });
    setConvs((prev) => {
      const c = prev[id] ?? { messages: [], notes: [] };
      const assistant: ChatMessage = { role: "assistant", text: "", tools: [], done: false };
      return { ...prev, [id]: { ...c, messages: [...c.messages, assistant] } };
    });
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const append = (fn: (m: ChatMessage) => void) =>
      setConvs((prev) => {
        const c = prev[id];
        if (!c) return prev;
        const msgs = [...c.messages];
        const idx = msgs.length - 1;
        const last = msgs[idx];
        if (!last || last.role !== "assistant") return prev;
        const copy: ChatMessage = { ...last, tools: [...last.tools] };
        fn(copy);
        msgs[idx] = copy;
        return { ...prev, [id]: { ...c, messages: msgs } };
      });
    try {
      const r = await fetch(`${GATEWAY}/api/prompt/sse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, session_id: id }),
        signal: ctrl.signal,
      });
      if (!r.ok || !r.body) {
        const detail = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status}: ${detail}`.slice(0, 200));
      }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 1);
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (data === "[DONE]") continue;
          try {
            const chunk = JSON.parse(data) as {
              choices?: Array<{ delta?: { content?: string; role?: string }; finish_reason?: string | null }>;
            };
            const choice = chunk.choices?.[0];
            if (choice?.delta?.content) {
              const piece = choice.delta.content;
              append((m) => {
                m.text += piece;
              });
            }
            if (choice?.finish_reason) {
              const reason = choice.finish_reason;
              append((m) => {
                m.done = true;
                m.stopReason = reason;
              });
            }
          } catch {
            /* partial/non-JSON line — ignore */
          }
        }
      }
      append((m) => {
        m.done = true;
        m.stopReason = m.stopReason ?? "stream_end";
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        append((m) => {
          m.done = true;
          m.stopReason = "interrupted";
        });
      } else {
        setError(e instanceof Error ? e.message : String(e));
        append((m) => {
          m.done = true;
          m.stopReason = "error";
        });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      void refreshList();
    }
  }, [input, selected, streaming, refreshList]);

  // --- actions ---------------------------------------------------------------
  const interrupt = useCallback(async () => {
    if (!selected) return;
    abortRef.current?.abort();
    try {
      await fetch(`${KERNEL}/api/sessions/${selected}/interrupt`, { method: "POST" });
    } catch {
      /* best effort */
    }
    void refreshList();
  }, [selected, refreshList]);

  const switchModel = useCallback(
    async (model: string) => {
      if (!selected || !model) return;
      try {
        const r = await fetch(`${KERNEL}/api/sessions/${selected}/model`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        void refreshList();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [selected, refreshList],
  );

  const fork = useCallback(async () => {
    if (!selected) return;
    try {
      const r = await fetch(`${KERNEL}/api/sessions/${selected}/fork`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const s = (await r.json()) as SessionInfo;
      await refreshList();
      setSelected(s.id);
      void loadConv(s.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selected, refreshList, loadConv]);

  const archive = useCallback(async () => {
    if (!selected) return;
    try {
      const r = await fetch(`${KERNEL}/api/sessions/${selected}/archive`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text().catch(() => "")}`.slice(0, 160));
      setSelected(null);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selected, refreshList]);

  // --- auto-scroll -------------------------------------------------------------
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [conv?.messages, streaming]);

  // ---------------------------------------------------------------------------
  const sessionStatusColor = (s: SessionInfo): string => {
    if (s.is_failed || s.status === "failed") return "var(--color-amitabha, #e07070)";
    if (s.status === "interrupted") return "var(--color-ratnasambhava, #e0b050)";
    if (s.status === "archived") return "var(--color-text-dim, #888)";
    return "var(--color-amoghasiddhi, #6ad08a)";
  };

  const sessionLabel = (s: SessionInfo): string =>
    s.title || s.tag || (s.root_session_id ? "fork" : "session");

  return (
    <main
      data-testid="tektos-sessions-page"
      style={{ display: "flex", flexDirection: "column", height: FRAME_HEIGHT, padding: 0 }}
    >
      <header
        data-testid="tektos-sessions-header"
        style={{
          padding: "var(--space-2, 8px) var(--space-3, 12px)",
          borderBottom: "1px solid var(--color-border-soft, #333)",
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "var(--font-lg, 1.125rem)" }}>Tektos Sessions</h1>
        <span
          data-testid="tektos-sessions-count"
          style={{
            fontSize: "var(--font-sm, 0.8125rem)",
            color: upstreamDown ? "var(--color-amitabha, #e07070)" : "var(--color-amoghasiddhi, #6ad08a)",
            fontWeight: 600,
          }}
        >
          {upstreamDown ? "● upstream offline" : `● ${sessions.length} session${sessions.length === 1 ? "" : "s"}`}
        </span>
        {lastUpdated && (
          <span style={{ fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>
            updated {lastUpdated.toLocaleTimeString()}
          </span>
        )}
        <Link
          href="/tektos-ultima"
          style={{ marginLeft: "auto", fontSize: "var(--font-sm, 0.8125rem)", color: "var(--color-akshobhya, #6a9eff)" }}
        >
          ← Dashboard
        </Link>
      </header>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* ------------------------------------------------ session list */}
        <aside
          data-testid="tektos-sessions-list"
          style={{
            width: "320px",
            flexShrink: 0,
            overflow: "hidden",
            borderRight: "1px solid var(--color-border-soft, #2a2a2a)",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div
            style={{
              padding: "10px 12px",
              borderBottom: "1px solid var(--color-border-soft, #2a2a2a)",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <select
                data-testid="tektos-sessions-new-model"
                value={newModel}
                onChange={(e) => setNewModel(e.target.value)}
                aria-label="Model for new session"
                style={{ ...selectStyle, flex: 1, minWidth: 0, width: "auto" }}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.recommended ? " (rec)" : ""}
                  </option>
                ))}
              </select>
              <button
                data-testid="tektos-sessions-new-btn"
                onClick={() => void createSession()}
                disabled={creating || !newModel}
                style={{ ...btnStyle, flexShrink: 0 }}
              >
                {creating ? "…" : "New"}
              </button>
            </div>
            <input
              data-testid="tektos-sessions-new-cwd"
              value={newCwd}
              onChange={(e) => setNewCwd(e.target.value)}
              placeholder="cwd (default: .)"
              aria-label="Working directory"
              style={inputStyle}
            />
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            {sessions.length === 0 && !upstreamDown && (
              <div
                data-testid="tektos-sessions-empty"
                style={{ padding: 16, color: "var(--color-text-dim, #888)", fontSize: "var(--font-sm, 0.8125rem)" }}
              >
                No active sessions. Create one to start.
              </div>
            )}
            {sessions.map((s) => {
              const active = s.id === selected;
              return (
                <button
                  key={s.id}
                  data-testid={`tektos-session-item-${s.id.slice(0, 8)}`}
                  onClick={() => {
                    setSelected(s.id);
                    if (!convs[s.id]) void loadConv(s.id);
                  }}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    padding: "10px 12px",
                    background: active ? "var(--color-surface, #1a1a1a)" : "transparent",
                    border: "none",
                    borderBottom: "1px solid var(--color-border-soft, #222)",
                    cursor: "pointer",
                    color: "var(--color-text, #eee)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: sessionStatusColor(s),
                        flexShrink: 0,
                      }}
                    />
                    <span
                      style={{
                        fontWeight: 600,
                        fontSize: "var(--font-sm, 0.8125rem)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {sessionLabel(s)}
                    </span>
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: "var(--font-xs, 0.75rem)",
                        color: "var(--color-text-dim, #888)",
                        flexShrink: 0,
                      }}
                    >
                      {s.status}
                    </span>
                  </div>
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: "var(--font-xs, 0.75rem)",
                      color: "var(--color-text-dim, #888)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {s.model} · {s.cwd}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* ------------------------------------------------ chat pane */}
        <section
          data-testid="tektos-sessions-chat"
          style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
        >
          {!selectedSession ? (
            <div
              data-testid="tektos-sessions-no-selection"
              style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-dim, #888)" }}
            >
              Select a session or create a new one.
            </div>
          ) : (
            <>
              <div
                data-testid="tektos-sessions-chat-header"
                style={{
                  padding: "8px 12px",
                  borderBottom: "1px solid var(--color-border-soft, #2a2a2a)",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  flexWrap: "wrap",
                }}
              >
                <select
                  data-testid="tektos-sessions-model-select"
                  value={selectedSession.model}
                  onChange={(e) => void switchModel(e.target.value)}
                  disabled={streaming}
                  aria-label="Switch model"
                  style={{ ...selectStyle, width: "auto", maxWidth: 220 }}
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
                <span
                  style={{
                    fontSize: "var(--font-xs, 0.75rem)",
                    color: "var(--color-text-dim, #888)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    maxWidth: 240,
                  }}
                  title={selectedSession.cwd}
                >
                  {selectedSession.cwd}
                </span>
                <span
                  data-testid="tektos-sessions-status"
                  style={{
                    fontSize: "var(--font-xs, 0.75rem)",
                    fontWeight: 600,
                    color: sessionStatusColor(selectedSession),
                  }}
                >
                  {streaming ? "streaming" : selectedSession.status}
                </span>
                <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                  <button
                    data-testid="tektos-sessions-interrupt-btn"
                    onClick={() => void interrupt()}
                    disabled={!streaming}
                    style={btnStyle}
                  >
                    Interrupt
                  </button>
                  <button data-testid="tektos-sessions-fork-btn" onClick={() => void fork()} style={btnStyle}>
                    Fork
                  </button>
                  <button
                    data-testid="tektos-sessions-archive-btn"
                    onClick={() => void archive()}
                    disabled={streaming}
                    style={btnStyle}
                  >
                    Archive
                  </button>
                </div>
              </div>

              {error && (
                <div
                  data-testid="tektos-sessions-error"
                  role="alert"
                  style={{
                    margin: "8px 12px 0",
                    padding: "6px 10px",
                    borderRadius: "var(--radius-md, 6px)",
                    border: "1px solid var(--color-amitabha, #c66)",
                    color: "var(--color-amitabha, #e07070)",
                    fontSize: "var(--font-sm, 0.8125rem)",
                  }}
                >
                  {error}
                </div>
              )}

              <div ref={scrollRef} data-testid="tektos-sessions-messages" style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
                {loadingConv && (
                  <div style={{ color: "var(--color-text-dim, #888)", fontSize: "var(--font-sm, 0.8125rem)" }}>Loading history…</div>
                )}
                {!conv && !loadingConv && (
                  <div style={{ color: "var(--color-text-dim, #888)", fontSize: "var(--font-sm, 0.8125rem)" }}>
                    No history yet — send a prompt.
                  </div>
                )}
                {conv?.notes.map((n, i) => (
                  <div
                    key={`note-${i}`}
                    style={{
                      fontSize: "var(--font-xs, 0.75rem)",
                      color:
                        n.kind === "error"
                          ? "var(--color-amitabha, #e07070)"
                          : n.kind === "warn"
                            ? "var(--color-ratnasambhava, #e0b050)"
                            : "var(--color-text-dim, #888)",
                      padding: "2px 0",
                    }}
                  >
                    ⚠ {n.text}
                  </div>
                ))}
                {conv?.messages.map((m, i) => (
                  <div key={i} style={{ marginBottom: 12 }}>
                    {m.role === "user" ? (
                      <div
                        data-testid="tektos-msg-user"
                        style={{
                          background: "var(--color-surface, #1a1a1a)",
                          border: "1px solid var(--color-border-soft, #2a2a2a)",
                          borderRadius: "var(--radius-md, 6px)",
                          padding: "8px 12px",
                          fontSize: "var(--font-sm, 0.875rem)",
                          whiteSpace: "pre-wrap",
                          maxWidth: "80%",
                          marginLeft: "auto",
                          textAlign: "right",
                          color: "var(--color-text, #eee)",
                        }}
                      >
                        {m.text}
                      </div>
                    ) : (
                      <div
                        data-testid="tektos-msg-assistant"
                        style={{
                          fontSize: "var(--font-sm, 0.875rem)",
                          color: "var(--color-text, #eee)",
                          whiteSpace: "pre-wrap",
                        }}
                      >
                        {m.tools.map((t, ti) => (
                          <div
                            key={ti}
                            data-testid="tektos-msg-tool"
                            style={{
                              margin: "6px 0",
                              padding: "4px 10px",
                              border: "1px solid var(--color-border-soft, #2a2a2a)",
                              borderRadius: "var(--radius-md, 6px)",
                              fontSize: "var(--font-xs, 0.75rem)",
                              color: "var(--color-text-soft, #bbb)",
                            }}
                          >
                            <span style={{ fontWeight: 600 }}>⚙ {t.name}</span>
                            {t.input ? <span> {t.input}</span> : null}
                            {t.status ? (
                              <span style={{ color: t.status === "success" ? "var(--color-amoghasiddhi, #6ad08a)" : "var(--color-ratnasambhava, #e0b050)" }}>
                                {" "}· {t.status}
                              </span>
                            ) : null}
                            {t.output ? (
                              <div style={{ color: "var(--color-text-dim, #888)", whiteSpace: "pre-wrap" }}>{t.output}</div>
                            ) : null}
                          </div>
                        ))}
                        {m.reasoning ? (
                          <details style={{ margin: "6px 0" }}>
                            <summary style={{ cursor: "pointer", fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)" }}>
                              reasoning
                            </summary>
                            <div style={{ whiteSpace: "pre-wrap", fontSize: "var(--font-xs, 0.75rem)", color: "var(--color-text-dim, #888)", padding: "4px 0 0 8px" }}>
                              {m.reasoning}
                            </div>
                          </details>
                        ) : null}
                        {m.text ? <span>{m.text}</span> : null}
                        {!m.done && streaming && <span style={{ opacity: 0.6 }}>▍</span>}
                        {m.done && m.stopReason ? (
                          <div style={{ fontSize: "var(--font-xs, 0.7rem)", color: "var(--color-text-dim, #666)", marginTop: 2 }}>
                            {m.stopReason}
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div
                style={{
                  padding: "10px 12px",
                  borderTop: "1px solid var(--color-border-soft, #2a2a2a)",
                  display: "flex",
                  gap: 8,
                }}
              >
                <textarea
                  data-testid="tektos-sessions-input"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder="Prompt (Enter to send, Shift+Enter for newline)"
                  rows={2}
                  style={{ ...inputStyle, flex: 1, resize: "vertical", fontFamily: "inherit" }}
                />
                <button
                  data-testid="tektos-sessions-send-btn"
                  onClick={() => void send()}
                  disabled={streaming || !input.trim()}
                  style={{ ...btnStyle, alignSelf: "flex-end" }}
                >
                  Send
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const selectStyle: CSSProperties = {
  background: "var(--color-surface, #111)",
  color: "var(--color-text, #eee)",
  border: "1px solid var(--color-border-soft, #333)",
  borderRadius: "var(--radius-md, 6px)",
  padding: "6px 8px",
  fontSize: "var(--font-sm, 0.8125rem)",
};

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
