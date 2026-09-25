"use client";
import { useEffect, useState } from "react";
import { kernelClient, type LlmStatus } from "../lib/kernel-client";

// Live LLM indicator per UX Design Spec §"Persistent Shell": the ACTIVE
// kernel LLM lane (ADR-116 failover: llama.cpp :8090 primary → Ollama
// fallback) + real GPU VRAM, refreshed every 5s from /api/llm/status
// (ADR-118). The previous /api/ollama/status feed showed whichever model
// Ollama happened to hold (often just the nomic-embed-text embedder) —
// wrong lane since ADR-116. Placeholder "—" renders until first response.

const POLL_MS = 5000;
const GIB = 1024 ** 3;

function formatModel(status: LlmStatus | null): string {
  if (!status || !status.model) return "—";
  // Show the failover lane when we are riding on it — the model alone
  // doesn't tell the user Ollama took over from llama.cpp.
  return status.lane === "fallback" ? `${status.model} (fallback)` : status.model;
}

function formatVram(status: LlmStatus | null): string {
  const cap = status?.vram_capacity_bytes ?? 32 * GIB;
  const capGib = (cap / GIB).toFixed(0);
  const used = status?.vram_used_bytes;
  if (!used || used === 0) {
    return `— / ${capGib}GB VRAM`;
  }
  const usedGib = (used / GIB).toFixed(1);
  return `${usedGib} / ${capGib}GB VRAM`;
}

export default function ModelSwapIndicator() {
  const [status, setStatus] = useState<LlmStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      kernelClient
        .getLlmStatus()
        .then((s) => {
          if (!cancelled) setStatus(s);
        })
        .catch(() => {
          /* keep last known value; UI stays on the previous reading */
        });
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div data-testid="model-swap-indicator" title={status?.detail ?? undefined}>
      <span data-testid="model-swap-model-name">{formatModel(status)}</span>
      <span data-testid="model-swap-vram">{formatVram(status)}</span>
    </div>
  );
}
