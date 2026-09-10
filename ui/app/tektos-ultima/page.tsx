"use client";

/**
 * /tektos-ultima — Kosmos shell host for the absorbed Tektos-Ultima
 * autonomous coding-agent frontend (ADR-091).
 *
 * This route is DISTINCT from `/tektos` (ADR-065 approval list). Both
 * coexist per the ADR-091 decision to preserve the approval-list route
 * unchanged.
 *
 * The page renders exactly one `PanelKind.IFRAME` panel per ADR-089:
 *   • `src = "/tektos-ultima/frontend/"` — same-origin via the kernel
 *     Starlette reverse proxy (see `kernel/tektos_ultima_bridge.py`).
 *   • `sandbox = DEFAULT_IFRAME_SANDBOX` (allow-same-origin,
 *     allow-scripts, allow-forms) — the minimum set for a React
 *     microfrontend that needs `fetch`, `localStorage`, and embedded
 *     forms.
 *   • `title` for a11y.
 *
 * The panel descriptor mirrors what a Stage 3.13 `FrontendContractPort`
 * adapter would emit for this iframe; wiring that adapter through the
 * kernel schema is deferred until the upstream Tektos-Ultima frontend
 * code drop lands under `plugins/tektos/frontend/`.
 */

import { useRef } from "react";
import TektosUltimaBridge from "../../components/TektosUltimaBridge";

// Mirrors ports/frontend_contract.py::DEFAULT_IFRAME_SANDBOX (ADR-089).
// Kept as a stringly-typed constant here because the Python port lives
// server-side and the shell renders an HTML iframe attribute directly.
const DEFAULT_IFRAME_SANDBOX = "allow-same-origin allow-scripts allow-forms";

// Same-origin path served by the kernel reverse proxy. Trailing slash
// triggers the upstream Next.js root index (avoids one 308 redirect on
// first paint).
const TEKTOS_ULTIMA_FRONTEND_SRC = "/tektos-ultima/frontend/";

export default function TektosUltimaPage() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  return (
    <main
      data-testid="tektos-ultima-page"
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
          data-testid="tektos-ultima-heading"
          style={{ margin: 0, fontSize: "var(--font-lg, 1.125rem)" }}
        >
          Tektos-Ultima
        </h1>
        <p
          data-testid="tektos-ultima-subtitle"
          style={{
            margin: "var(--space-1, 4px) 0 0",
            fontSize: "var(--font-sm, 0.875rem)",
            color: "var(--color-muted, #888)",
          }}
        >
          Autonomous coding agent — microfrontend hosted via ADR-091 iframe
          contract.
        </p>
      </header>

      <iframe
        ref={iframeRef}
        data-testid="tektos-ultima-iframe"
        title="Tektos-Ultima autonomous coding agent"
        src={TEKTOS_ULTIMA_FRONTEND_SRC}
        sandbox={DEFAULT_IFRAME_SANDBOX}
        // `loading="lazy"` is safe because the panel is above-the-fold
        // only when the user navigates to this route; if the shell later
        // pre-warms the frame, flip to "eager".
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
