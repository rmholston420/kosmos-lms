"use client";

/**
 * /tektos-ultima/legacy — preserved ADR-091 microfrontend iframe page.
 *
 * The native dashboard (Stage 9.2, ADR-109) now lives at `/tektos-ultima`.
 * The standalone Tektos frontend (:5556) remains reachable here through
 * the kernel reverse proxy until Stage 9.5 parity verification, when the
 * bridge router + CSP middleware retire (ADR-091 D-deferral).
 *
 * The page renders exactly one `PanelKind.IFRAME` panel per ADR-089:
 *   • `src = "/tektos-ultima/frontend/"` — same-origin via the kernel
 *     Starlette reverse proxy (see `kernel/tektos_ultima_bridge.py`).
 *   • `sandbox = DEFAULT_IFRAME_SANDBOX` (allow-same-origin,
 *     allow-scripts, allow-forms) — the minimum set for a React
 *     microfrontend that needs `fetch`, `localStorage`, and embedded
 *     forms.
 *   • `title` for a11y.
 */

import { useRef } from "react";
import TektosUltimaBridge from "../../../components/TektosUltimaBridge";

// Mirrors ports/frontend_contract.py::DEFAULT_IFRAME_SANDBOX (ADR-089).
// Kept as a stringly-typed constant here because the Python port lives
// server-side and the shell renders an HTML iframe attribute directly.
const DEFAULT_IFRAME_SANDBOX = "allow-same-origin allow-scripts allow-forms";

// Same-origin path served by the kernel reverse proxy. Trailing slash
// triggers the upstream Next.js root index (avoids one 308 redirect on
// first paint).
const TEKTOS_ULTIMA_FRONTEND_SRC = "/tektos-ultima/frontend/";

export default function TektosUltimaLegacyPage() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  return (
    <main
      data-testid="tektos-ultima-legacy-page"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "calc(100vh - var(--top-bar-h, 48px))",
        padding: 0,
      }}
    >
      <header
        style={{
          padding: "var(--space-2, 8px) var(--space-3, 12px)",
          borderBottom: "1px solid var(--color-border, #333)",
        }}
      >
        <h1
          data-testid="tektos-ultima-legacy-heading"
          style={{ margin: 0, fontSize: "var(--font-lg, 1.125rem)" }}
        >
          Tektos-Ultima (legacy)
        </h1>
        <p
          data-testid="tektos-ultima-legacy-subtitle"
          style={{
            margin: "var(--space-1, 4px) 0 0",
            fontSize: "var(--font-sm, 0.875rem)",
            color: "var(--color-muted, #888)",
          }}
        >
          Standalone Tektos frontend — microfrontend hosted via ADR-091
          iframe contract. Superseded by the native dashboard; retires in
          Stage 9.5.
        </p>
      </header>

      <iframe
        ref={iframeRef}
        data-testid="tektos-ultima-legacy-iframe"
        title="Tektos-Ultima autonomous coding agent (legacy)"
        src={TEKTOS_ULTIMA_FRONTEND_SRC}
        sandbox={DEFAULT_IFRAME_SANDBOX}
        loading="lazy"
        style={{
          border: "none",
          flex: 1,
          width: "100%",
          background: "var(--color-surface, #111)",
        }}
      />
      <TektosUltimaBridge iframeRef={iframeRef} />
    </main>
  );
}
