import { test, expect } from "@playwright/test";

// Tektos integration Stage 9.5 (ADR-113) — native subsystem panels page.
//
// Drives the real kernel end-to-end (no mocks): the page talks to the
// kernel-native API (Stage 14.1: the ADR-109 gateway proxy to the
// retired :8020 is deleted). All assertions are READ-ONLY — the page
// itself mutates nothing and the spec never clicks a mutation control, so
// it is safe in CI and leaks no state.

const PAGE = "/tektos-ultima/panels";

test.describe("tektos-ultima panels page (Stage 9.5)", () => {
  test("boots on the Status tab with real subsystem rows", async ({ page }) => {
    await page.goto(PAGE);
    await expect(page.getByTestId("tektos-panels-page")).toBeVisible();
    await expect(page.getByTestId("tektos-panels-header")).toContainText(/online|offline/);
    await expect(page.getByTestId("tektos-panels-status")).toBeVisible();
    // The subsystem table lists named subsystems (Nervous System is a
    // core Tektos module present on every install).
    await expect(page.getByTestId("tektos-panels-status")).toContainText("Nervous System", {
      timeout: 15_000,
    });
    // At least one row must render with a status word.
    await expect(page.getByTestId("tektos-panels-status").locator("tbody tr").first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("planner and agents tabs render real data", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-panels-tab-planner").click();
    await expect(page.getByTestId("tektos-panels-planner")).toBeVisible();
    // Planner status returns initialized + stats on every install.
    await expect(page.getByTestId("tektos-panels-planner")).toContainText(/initialized|degraded|error/i, {
      timeout: 15_000,
    });

    await page.getByTestId("tektos-panels-tab-agents").click();
    await expect(page.getByTestId("tektos-panels-agents")).toBeVisible();
    // The orchestrator ships 3 built-in agents.
    const agentRows = page.getByTestId("tektos-panels-agents").locator("tbody tr");
    await expect(agentRows.first()).toBeVisible({ timeout: 15_000 });
    expect(await agentRows.count()).toBeGreaterThanOrEqual(2);
  });

  test("immune and metabolism tabs render subsystem state", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-panels-tab-immune").click();
    await expect(page.getByTestId("tektos-panels-immune")).toBeVisible();
    // Tektos registers a fixed detector set; the tab shows its count.
    await expect(page.getByTestId("tektos-panels-immune")).toContainText("Detectors", {
      timeout: 15_000,
    });

    await page.getByTestId("tektos-panels-tab-metabolism").click();
    await expect(page.getByTestId("tektos-panels-metabolism")).toBeVisible();
    // Metabolism health is one of the fixed enum words (critical when the
    // GPU is saturated — all are valid render states).
    await expect(
      page.getByTestId("tektos-panels-metabolism"),
    ).toContainText(/healthy|normal|warning|critical|degraded/i, {
      timeout: 15_000,
    });
  });

  test("axioms tab lists architecture axioms with category filter", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-panels-tab-axioms").click();
    await expect(page.getByTestId("tektos-panels-axioms")).toBeVisible();
    // Tektos ships the bicameral-architecture axiom on every install.
    await expect(page.getByTestId("tektos-panels-axioms")).toContainText("architecture.bicameral", {
      timeout: 15_000,
    });
    // Category filter buttons exist (architecture category always present).
    await expect(page.getByTestId("tektos-panels-axiom-cat-architecture")).toBeVisible();
    // Clicking a filter narrows the list without crashing.
    await page.getByTestId("tektos-panels-axiom-cat-architecture").click();
    await expect(page.getByTestId("tektos-panels-axioms")).toContainText("architecture.bicameral");
    await page.getByTestId("tektos-panels-axiom-cat-all").click();
    await expect(page.getByTestId("tektos-panels-axioms")).toContainText("architecture.bicameral");
  });

  test("hindsight and knowledge tabs render without error", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-panels-tab-hindsight").click();
    await expect(page.getByTestId("tektos-panels-hindsight")).toBeVisible();
    // The status block shows the bank id and service name.
    await expect(page.getByTestId("tektos-panels-hindsight")).toContainText("hindsight", {
      timeout: 15_000,
    });

    await page.getByTestId("tektos-panels-tab-knowledge").click();
    await expect(page.getByTestId("tektos-panels-knowledge")).toBeVisible();
    // The workspace directory listing resolves the Tektos repo root.
    await expect(page.getByTestId("tektos-panels-knowledge")).toContainText("Workspace", {
      timeout: 15_000,
    });
    // Search box is present (read-only usage: submitting a query is safe —
    // /api/search is a pure GET).
    await expect(page.getByTestId("tektos-panels-search-input")).toBeVisible();
    await page.getByTestId("tektos-panels-search-input").fill("tektos");
    await page.getByTestId("tektos-panels-search-btn").click();
    await expect(page.getByTestId("tektos-panels-knowledge")).toContainText("Results:", {
      timeout: 15_000,
    });
  });

  test("status tab shows the Tektos core /health probe row", async ({ page }) => {
    await page.goto(PAGE);
    await expect(page.getByTestId("tektos-panels-status")).toBeVisible();
    // Stage 14.1 (ADR-109 exit gate): the first row is the kernel-native
    // /health probe — no gateway envelope, detail from /api/llm/status +
    // /api/sessions.
    const coreRow = page.getByTestId("tektos-panels-status").locator("tbody tr").first();
    await expect(coreRow).toContainText("Tektos core", { timeout: 15_000 });
    await expect(coreRow).toContainText(/active sessions/, { timeout: 15_000 });
  });

  test("drill tab: hooks, repoMap, routing, skill search + skill detail", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-panels-tab-drill").click();
    await expect(page.getByTestId("tektos-panels-drill")).toBeVisible();
    // Hooks / RepoMap / routing all render from kernel-native GETs.
    await expect(page.getByTestId("tektos-panels-drill")).toContainText("Event hooks", { timeout: 15_000 });
    await expect(page.getByTestId("tektos-panels-drill")).toContainText("Tool schemas", { timeout: 15_000 });

    // Skill search (pure GET) — the donor SkillManager is a ratified
    // deferral (ADR-108 D9): the kernel has no skill store, so the search
    // surfaces the empty state. Assert the tab degrades honestly, not that
    // donor skill names exist.
    await page.getByTestId("tektos-panels-skill-query").fill("file");
    await page.getByTestId("tektos-panels-skill-search-btn").click();
    await expect(page.getByTestId("tektos-panels-drill")).toContainText("no matches", {
      timeout: 15_000,
    });
  });
});
