"use client";

/**
 * TektosUltimaBridge — client-side postMessage bridge (ADR-091).
 *
 * Mounts a `window.addEventListener("message", ...)` handler that forwards
 * `tektos.*` envelopes from the same-origin `/tektos-ultima/frontend`
 * iframe to the kernel bridge at `POST /api/tektos-ultima/bridge`.
 *
 * Origin/source validation (both required, per ADR-091):
 *   1. `event.source === iframeRef.current?.contentWindow` — the message
 *      MUST come from the specific iframe we mounted, not some other
 *      window in the same tab.
 *   2. `event.origin === window.location.origin` — the reverse proxy
 *      guarantees the iframe runs on the Kosmos origin; any other
 *      origin implies a rehost attempt and is dropped.
 *
 * Namespace validation:
 *   3. `data.kind` MUST match `/^tektos\./` — the shell relays only the
 *      one namespace ADR-086 delegates to the iframe. Other namespaces
 *      (`immune.*`, `thermal.*`, ...) are server-owned and cannot be
 *      forged from the iframe.
 *
 * All rejected messages are silently dropped; a warning is logged in
 * dev builds (`process.env.NODE_ENV !== "production"`) so bridge
 * misuse surfaces during development without polluting production
 * consoles.
 */

import { useEffect, type RefObject } from "react";

type IframeRef = RefObject<HTMLIFrameElement | null>;

interface TektosUltimaBridgeProps {
  iframeRef: IframeRef;
}

interface BridgeEnvelope {
  kind: string;
  payload?: Record<string, unknown>;
}

const TEKTOS_KIND_PATTERN = /^tektos\./;
const BRIDGE_URL = "/api/tektos-ultima/bridge";

function isBridgeEnvelope(value: unknown): value is BridgeEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  if (typeof record.kind !== "string" || record.kind.length === 0) return false;
  if (
    "payload" in record &&
    record.payload !== undefined &&
    (typeof record.payload !== "object" || record.payload === null)
  ) {
    return false;
  }
  return true;
}

function devWarn(message: string): void {
  if (
    typeof process !== "undefined" &&
    process.env &&
    process.env.NODE_ENV !== "production"
  ) {
    // eslint-disable-next-line no-console
    console.warn(`[TektosUltimaBridge] ${message}`);
  }
}

export default function TektosUltimaBridge({
  iframeRef,
}: TektosUltimaBridgeProps): null {
  useEffect(() => {
    // Same-origin baseline; recomputed once here rather than on every
    // message so the closure below is cheap.
    const kosmosOrigin =
      typeof window !== "undefined" ? window.location.origin : "";

    async function forward(envelope: BridgeEnvelope): Promise<void> {
      try {
        await fetch(BRIDGE_URL, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            kind: envelope.kind,
            payload: envelope.payload ?? {},
          }),
          // Bridge is best-effort per ADR-091; keep the request
          // credential-less so it survives future CSRF hardening.
          credentials: "omit",
        });
      } catch (err) {
        devWarn(`bridge POST failed: ${String(err)}`);
      }
    }

    function onMessage(event: MessageEvent): void {
      // 1. Source check — must be the specific iframe we mounted.
      const iframeWindow = iframeRef.current?.contentWindow ?? null;
      if (iframeWindow === null || event.source !== iframeWindow) {
        // Silent drop — messages from other windows (extensions, other
        // iframes) are expected background noise.
        return;
      }

      // 2. Origin check — must match Kosmos origin (same-origin proxy).
      if (event.origin !== kosmosOrigin) {
        devWarn(`rejected message with foreign origin ${event.origin}`);
        return;
      }

      // 3. Shape check.
      if (!isBridgeEnvelope(event.data)) {
        devWarn("rejected message with malformed envelope");
        return;
      }

      // 4. Namespace check — bridge only relays `tektos.*` per ADR-086.
      if (!TEKTOS_KIND_PATTERN.test(event.data.kind)) {
        devWarn(
          `rejected non-tektos namespace ${event.data.kind}; ` +
            "other reserved namespaces originate server-side",
        );
        return;
      }

      // Fire and forget; response body is not consumed.
      void forward(event.data);
    }

    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [iframeRef]);

  return null;
}
