import { test, expect } from "@playwright/test";

// Tektos integration Stage 9.2 (ADR-109) — the ADR-091 microfrontend
// shell moved to /tektos-ultima/legacy; the native dashboard now owns
// /tektos-ultima (real Kosmos page driving the Tektos API through the
// kernel gateway at /api/tektos-ultima/gateway/*).
//
// Covers:
//   • /tektos-ultima renders the native dashboard (heading, status
//     pill, upstream line, 14 subsystem cards, legacy link).
//   • The kernel gateway health probe returns the typed ADR-109
//     envelope ({upstream, reachable, status_code, body?}) — 200 when
//     the Tektos API is up, 503 with `tektos_ultima_unavailable` when
//     down.
//   • /tektos-ultima/legacy renders the preserved ADR-091 iframe with
//     the ADR-089 sandbox attribute and same-origin src.
//   • The bridge endpoint accepts a valid tektos.* envelope and returns
//     202 + event_id; rejects non-tektos.* namespaces with 400.
//   • Every HTML response carries CSP `frame-ancestors 'self'` per
//     KosmosIframeCSPMiddleware (retires in Stage 9.5).

const DEFAULT_IFRAME_SANDBOX = "allow-same-origin allow-scripts allow-forms";
const FRONTEND_PATH = "/tektos-ultima/frontend/";
const BRIDGE_PATH = "/api/tektos-ultima/bridge";
const GATEWAY_HEALTH = "/api/tektos-ultima/gateway/health";
const CARD_IDS = [
  "immune",
  "thermal",
  "inference",
  "memory",
  "rag",
  "skills",
  "tools",
  "models",
  "plugins",
  "neo4j",
  "postgres",
  "redis",
  "hindsight",
  "self_repair",
];

test.describe("Tektos-Ultima native dashboard (Stage 9.2, ADR-109)", () => {
  test("dashboard renders heading, status pill, upstream line, legacy link", async ({
    page,
  }) => {
    await page.goto("/tektos-ultima/");

    await expect(page.getByTestId("tektos-ultima-page")).toBeVisible();
    await expect(page.getByTestId("tektos-ultima-heading")).toHaveText(
      "Tektos-Ultima",
    );
    await expect(page.getByTestId("tektos-ultima-status-pill")).toBeVisible();
    await expect(page.getByTestId("tektos-ultima-upstream")).toContainText(
      ":",
    );
    await expect(page.getByTestId("tektos-ultima-legacy-link")).toHaveText(
      "Legacy UI →",
    );
  });

  test("dashboard renders one card per subsystem, each with a status", async ({
    page,
  }) => {
    await page.goto("/tektos-ultima/");

    for (const id of CARD_IDS) {
      const card = page.getByTestId(`tektos-ultima-card-${id}`);
      await expect(card, `card ${id}`).toBeVisible();
      await expect(
        page.getByTestId(`tektos-ultima-card-status-${id}`),
        `status ${id}`,
      ).toBeVisible();
    }
  });

  test("gateway health probe returns the ADR-109 typed envelope", async ({
    request,
  }) => {
    const response = await request.get(GATEWAY_HEALTH);
    const status = response.status();
    if (status === 200) {
      const body = await response.json();
      expect(typeof body.upstream).toBe("string");
      expect(body.reachable).toBe(true);
      expect(body.status_code).toBe(200);
    } else {
      // CI / no standalone Tektos API: the gateway MUST surface the
      // typed degrade envelope, never a raw connection error.
      expect(status).toBe(503);
      const body = await response.json();
      expect(body.error).toBe("tektos_ultima_unavailable");
      expect(typeof body.upstream).toBe("string");
    }
  });

  test("legacy iframe page preserves the ADR-089 sandbox contract", async ({
    page,
  }) => {
    await page.goto("/tektos-ultima/legacy/");

    await expect(page.getByTestId("tektos-ultima-legacy-page")).toBeVisible();
    const iframe = page.getByTestId("tektos-ultima-legacy-iframe");
    await expect(iframe).toBeAttached();
    await expect(iframe).toHaveAttribute("src", FRONTEND_PATH);
    await expect(iframe).toHaveAttribute("sandbox", DEFAULT_IFRAME_SANDBOX);
  });
});

test.describe("Tektos-Ultima bridge + CSP (ADR-091, unchanged until 9.5)", () => {
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
    expect(typeof body.event_id).toBe("string");
    expect(body.event_id.length).toBeGreaterThanOrEqual(32);
  });

  test("bridge rejects non-tektos.* namespace with 400", async ({
    request,
  }) => {
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
    const response = await request.get("/");
    const csp = response.headers()["content-security-policy"] ?? "";
    expect(csp).toContain("frame-ancestors 'self'");
  });
});
