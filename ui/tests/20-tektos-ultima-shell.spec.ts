import { test, expect } from "@playwright/test";

// Tektos integration Stage 9.5 (ADR-113) — the ADR-091 microfrontend
// shell (iframe + postMessage bridge + `/tektos-ultima/frontend` proxy)
// is retired. The native dashboard owns `/tektos-ultima` (real Kosmos
// page driving the Tektos API through the kernel gateway at
// `/api/tektos-ultima/gateway/*`).
//
// Covers:
//   • /tektos-ultima renders the native dashboard (heading, status
//     pill, upstream line, panels link — NO legacy link).
//   • The kernel gateway health probe returns the typed ADR-109
//     envelope ({upstream, reachable, status_code, body?}) — 200 when
//     the Tektos API is up, 503 with `tektos_ultima_unavailable` when
//     down.
//   • The retired legacy route no longer renders an iframe (404).
//   • Every HTML response carries CSP `frame-ancestors 'self'` — the
//     middleware survived ADR-091 retirement as a kernel-wide
//     hardening measure (KosmosCSPMiddleware in the gateway module).

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
  test("dashboard renders heading, status pill, upstream line, panels link (no legacy)", async ({
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
    await expect(page.getByTestId("tektos-ultima-panels-link")).toHaveText(
      "Panels →",
    );
    // ADR-113: the legacy link is gone.
    await expect(page.getByTestId("tektos-ultima-legacy-link")).toHaveCount(0);
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

  test("retired legacy route no longer renders the ADR-089 iframe (ADR-113)", async ({
    request,
  }) => {
    // The static export is gone; the kernel falls through to 404.
    const response = await request.get("/tektos-ultima/legacy/");
    expect(response.status()).toBe(404);
  });
});

test.describe("Tektos-Ultima kernel-wide CSP (ADR-113, survives 091 retirement)", () => {
  test("kernel HTML responses carry CSP frame-ancestors 'self'", async ({
    request,
  }) => {
    const response = await request.get("/");
    const csp = response.headers()["content-security-policy"] ?? "";
    expect(csp).toContain("frame-ancestors 'self'");
  });
});
