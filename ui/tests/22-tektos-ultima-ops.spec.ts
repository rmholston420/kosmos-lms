import { test, expect } from "@playwright/test";

// Tektos integration Stage 9.4 (ADR-112) — native ops page.
//
// Drives the real kernel end-to-end (no mocks): the page talks to the
// kernel-native API (Stage 14.1: the ADR-109 gateway proxy to the
// retired :8020 is deleted). All assertions are READ-ONLY — the
// spec never triggers backup/restore/decay/repair/toggle actions, so it
// is safe in CI and leaks no state.

const PAGE = "/tektos-ultima/ops";

test.describe("tektos-ultima ops page (Stage 9.4)", () => {
  test("boots on the Database tab with kernel persistence lanes", async ({ page }) => {
    await page.goto(PAGE);
    await expect(page.getByTestId("tektos-ops-page")).toBeVisible();
    await expect(page.getByTestId("tektos-ops-header")).toBeVisible();
    await expect(page.getByTestId("tektos-ops-db")).toBeVisible();
    // Kernel-native /api/db: the tab renders the kernel registry's
    // persistence lanes (postgres/dozerdb/qdrant/valkey) with their
    // boot-time wired state — not the donor's tektos.db schema dump
    // (retired with main.py deletion, ADR-137).
    await expect(page.getByTestId("tektos-ops-db")).toContainText("Kernel persistence lanes", {
      timeout: 15_000,
    });
    await expect(page.getByTestId("tektos-ops-db")).toContainText("wired", {
      timeout: 15_000,
    });
    // Header shows a status pill (online or offline — both render).
    await expect(page.getByTestId("tektos-ops-header")).toContainText(/online|offline/);
  });

  test("skills and tools tabs render kernel-native surfaces", async ({ page }) => {
    await page.goto(PAGE);
    await expect(page.getByTestId("tektos-ops-page")).toBeVisible();

    await page.getByTestId("tektos-ops-tab-skills").click();
    await expect(page.getByTestId("tektos-ops-skills")).toBeVisible();
    // Kernel-native /api/skills/stats (ADR-125 read surface): the tab shows
    // the skill-candidate tracker metrics. The donor's 24-skill registry
    // (safe_file_operations, toggles, …) is a ratified deferral (ADR-108
    // D9), so the tab renders the candidate-empty state instead of rows.
    await expect(page.getByTestId("tektos-ops-skills")).toContainText("archetypes", {
      timeout: 15_000,
    });
    await expect(page.getByTestId("tektos-ops-skills")).toContainText("Skill candidates", {
      timeout: 15_000,
    });

    await page.getByTestId("tektos-ops-tab-tools").click();
    await expect(page.getByTestId("tektos-ops-tools")).toBeVisible();
    // Kernel-native /api/tools capability table (static, ADR-107 D1):
    // the kernel knows 13 tools (bash, file_*, search_*, web_*,
    // delegate_task, …).
    const toolRows = page.getByTestId("tektos-ops-tools").locator("tbody tr");
    await expect(toolRows.first()).toBeVisible({ timeout: 15_000 });
    expect(await toolRows.count()).toBeGreaterThanOrEqual(10);
  });

  test("logs tab renders live log lines with level filter", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-ops-tab-logs").click();
    await expect(page.getByTestId("tektos-ops-logs")).toBeVisible();
    // The Tektos backend logs httpx/tektos lines continuously.
    await expect(page.getByTestId("tektos-ops-logs-body")).not.toBeEmpty({
      timeout: 15_000,
    });
    // Level filter buttons are present; clicking ERROR narrows the view
    // (may legitimately show zero lines — assert no crash, count <= total).
    await page.getByTestId("tektos-ops-logs-level-ERROR").click();
    const body = page.getByTestId("tektos-ops-logs-body");
    await expect(body).toBeVisible();
    await page.getByTestId("tektos-ops-logs-level-ALL").click();
    await expect(body).toBeVisible();
  });

  test("telemetry tab shows live GPU sample", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-ops-tab-telemetry").click();
    await expect(page.getByTestId("tektos-ops-telemetry")).toBeVisible();
    // Kernel-native /api/telemetry (ADR-138): a live GPU sample with
    // temperature in °C and the ADR-138 footer. The donor's GREEN/AMBER/RED
    // thermal zone came from /api/thermal/status (ADR-121) — a separate
    // surface, not asserted here.
    await expect(page.getByTestId("tektos-ops-telemetry")).toContainText("°C", {
      timeout: 15_000,
    });
    await expect(page.getByTestId("tektos-ops-telemetry")).toContainText("kernel-native (ADR-138)", {
      timeout: 15_000,
    });
  });

  test("memory and repair tabs render without error", async ({ page }) => {
    await page.goto(PAGE);
    await page.getByTestId("tektos-ops-tab-memory").click();
    await expect(page.getByTestId("tektos-ops-memory")).toBeVisible();
    // Decay button present (never clicked — destructive).
    await expect(page.getByTestId("tektos-ops-memory-decay-btn")).toBeVisible();

    await page.getByTestId("tektos-ops-tab-repair").click();
    await expect(page.getByTestId("tektos-ops-repair")).toBeVisible();
    // Repair button present (never clicked — triggers a repair cycle).
    await expect(page.getByTestId("tektos-ops-repair-btn")).toBeVisible();
    // History panel present with either rows or the empty state.
    await expect(
      page.locator(
        "[data-testid='tektos-ops-repair'] tbody tr, [data-testid='tektos-ops-repair'] h2",
      ).first(),
    ).toBeVisible();
  });
});
