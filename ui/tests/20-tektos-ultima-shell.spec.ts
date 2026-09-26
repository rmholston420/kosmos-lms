import { test, expect } from "@playwright/test";

// Tektos integration Stage 9.5 (ADR-113) — the ADR-091 microfrontend
// shell (iframe + postMessage bridge + `/tektos-ultima/frontend` proxy)
// is retired. The native dashboard owns `/tektos-ultima` (real Kosmos
// page, Stage 14.1: fully kernel-native — the ADR-109 gateway proxy was
// deleted with the retired :8020).
//
// Covers:
//   • /tektos-ultima renders the native dashboard (heading, status
//     pill, upstream line, panels link — NO legacy link).
//   • The kernel-native /health endpoint returns {status:"ok"} — the
//     ADR-109 gateway envelope test is retired with the module.
//   • The retired legacy route no longer renders an iframe (404).
//   • Every HTML response carries CSP `frame-ancestors 'self'` — the
//     middleware survived ADR-091 + ADR-109 retirement as a kernel-wide
//     hardening measure (kernel/csp.py).

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

  test("kernel-native /health returns {status: 'ok'} (ADR-109 module deleted)", async ({
    request,
  }) => {
    const response = await request.get("/health");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.status).toBe("ok");
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
