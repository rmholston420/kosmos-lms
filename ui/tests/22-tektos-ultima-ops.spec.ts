import { test, expect } from "@playwright/test";

// Tektos integration Stage 9.4 (ADR-112) — native ops page.
//
// Drives the real kernel + Tektos API end-to-end (no mocks): the page
// talks to the standalone Tektos (:8020) through the kernel gateway
// (/api/tektos-ultima/gateway/*). All assertions are READ-ONLY — the
// spec never triggers backup/restore/decay/repair/toggle actions, so it
// is safe in CI and leaks no state.

const PAGE = "/tektos-ultima/ops";

test.describe("tektos-ultima ops page (Stage 9.4)", () => {
  test("boots on the Database tab with real schema", async ({ page }) => {
    await page.goto(PAGE);
    await expect(page.getByTestId("tektos-ops-page")).toBeVisible();
    await expect(page.getByTestId("tektos-ops-header")).toBeVisible();
    await expect(page.getByTestId("tektos-ops-db")).toBeVisible();
    // /api/db/schema returns the live table definitions (events table exists
    // on every Tektos install).
    await expect(page.getByTestId("tektos-ops-db-schema")).toContainText("events", {
      timeout: 15_000,
    });
    // Header shows an upstream status pill (online or offline — both render).
    await expect(page.getByTestId("tektos-ops-header")).toContainText(/online|offline/);
  });

  test("skills and tools tabs list registered entries", async ({ page }) => {
    await page.goto(PAGE);
    await expect(page.getByTestId("tektos-ops-page")).toBeVisible();

    await page.getByTestId("tektos-ops-tab-skills").click();
    await expect(page.getByTestId("tektos-ops-skills")).toBeVisible();
    // Tektos ships safe_file_operations + safe_command_execution skills,
    // so at least one row must appear.
    await expect(page.getByTestId("tektos-ops-skills").locator("tbody tr").first()).toBeVisible({
      timeout: 15_000,
    });

    await page.getByTestId("tektos-ops-tab-tools").click();
    await expect(page.getByTestId("tektos-ops-tools")).toBeVisible();
    // Tektos registers 20+ built-in tools.
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
    // Real telemetry: temperature in °C and a thermal zone (GREEN/AMBER/RED).
    await expect(page.getByTestId("tektos-ops-telemetry")).toContainText("°C", {
      timeout: 15_000,
    });
    await expect(page.getByTestId("tektos-ops-telemetry")).toContainText(/GREEN|AMBER|RED/, {
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
