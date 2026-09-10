import { test, expect } from "@playwright/test";

// Stage 2 microfrontend shell integration (ADR-091).
//
// Covers:
//   • /tektos-ultima renders the Kosmos shell page with iframe + heading.
//   • The iframe carries the ADR-089 DEFAULT_IFRAME_SANDBOX attribute and
//     the same-origin /tektos-ultima/frontend/ src (kernel reverse proxy).
//   • The reverse proxy responds 502 with the documented diagnostic when
//     no upstream Tektos-Ultima dev server is running (CI baseline).
//   • The bridge endpoint accepts a valid tektos.* envelope and returns
//     202 + event_id.
//   • The bridge endpoint rejects a non-tektos.* namespace with 400.
//   • Every HTML response carries CSP `frame-ancestors 'self'` per
//     KosmosIframeCSPMiddleware.

const DEFAULT_IFRAME_SANDBOX = "allow-same-origin allow-scripts allow-forms";
const FRONTEND_PATH = "/tektos-ultima/frontend/";
const BRIDGE_PATH = "/api/tektos-ultima/bridge";

test.describe("Tektos-Ultima microfrontend shell (ADR-091)", () => {
  test("shell page renders iframe + heading with ADR-089 sandbox", async ({
    page,
  }) => {
    await page.goto("/tektos-ultima/");

    await expect(page.getByTestId("tektos-ultima-page")).toBeVisible();
    await expect(page.getByTestId("tektos-ultima-heading")).toHaveText(
      "Tektos-Ultima",
    );

    const iframe = page.getByTestId("tektos-ultima-iframe");
    await expect(iframe).toBeAttached();
    await expect(iframe).toHaveAttribute("src", FRONTEND_PATH);
    await expect(iframe).toHaveAttribute("sandbox", DEFAULT_IFRAME_SANDBOX);
    await expect(iframe).toHaveAttribute(
      "title",
      "Tektos-Ultima autonomous coding agent",
    );
  });

  test("reverse proxy returns 502 with diagnostic when upstream absent", async ({
    request,
  }) => {
    // CI does not run a Tektos-Ultima dev server on :5556; the proxy
    // MUST surface a machine-parseable diagnostic rather than a raw
    // connection error.
    const response = await request.get(`${FRONTEND_PATH}`);
    expect(response.status()).toBe(502);
    const body = await response.json();
    expect(body.error).toBe("tektos_ultima_upstream_unreachable");
    expect(typeof body.upstream).toBe("string");
    expect(body.hint).toContain("KOSMOS_TEKTOS_ULTIMA_UPSTREAM");
  });

  test("bridge accepts valid tektos.* envelope and returns 202", async ({
    request,
  }) => {
    const response = await request.post(BRIDGE_PATH, {
      data: {
        kind: "tektos.agent.turn.started",
        payload: { turn: 1, note: "playwright bridge round-trip" },
      },
    });
    expect(response.status()).toBe(202);
    const body = await response.json();
    expect(body.status).toBe("accepted");
    expect(body.event_type).toBe("tektos.agent.turn.started");
    // event_id is a uuid4; length + shape is sufficient for a smoke test.
    expect(typeof body.event_id).toBe("string");
    expect(body.event_id.length).toBeGreaterThanOrEqual(32);
  });

  test("bridge rejects non-tektos.* namespace with 400", async ({
    request,
  }) => {
    // ADR-091 forbids the iframe from originating any namespace it does
    // not own (thermal.*, immune.*, etc. are server-side only).
    const response = await request.post(BRIDGE_PATH, {
      data: {
        kind: "thermal.red",
        payload: { celsius: 90 },
      },
      failOnStatusCode: false,
    });
    expect(response.status()).toBe(400);
  });

  test("bridge rejects missing kind with 400", async ({ request }) => {
    const response = await request.post(BRIDGE_PATH, {
      data: { payload: { foo: "bar" } },
      failOnStatusCode: false,
    });
    expect(response.status()).toBe(400);
  });

  test("kernel HTML responses carry CSP frame-ancestors 'self'", async ({
    request,
  }) => {
    // Hit the static-export root; middleware runs uniformly on every
    // HTTP response, so any HTML route proves the CSP directive is on.
    const response = await request.get("/");
    const csp = response.headers()["content-security-policy"] ?? "";
    expect(csp).toContain("frame-ancestors 'self'");
  });
});
