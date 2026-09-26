import { test, expect } from "@playwright/test";

// Tektos integration Stage 9.3 (ADR-111) — native sessions + chat page.
//
// Drives the real kernel end-to-end (no mocks): the page talks to the
// kernel-native session API (Stage 14.1: the ADR-109 gateway proxy to
// the retired :8020 is deleted). The one live prompt is a minimal
// "reply PONG" turn on the primary model — it exercises the full
// create → SSE stream → render path against the real LLM.
//
// Cleanup: every session this spec creates is archived before it ends,
// so runs never leak state into the Tektos session list.

const PAGE = "/tektos-ultima/sessions";
// archiveAllSessions runs in Node context (not the browser) — absolute URL.
const BASE = process.env.KOSMOS_BASE_URL ?? "http://127.0.0.1:8000";
const ITEMS = "[data-testid^='tektos-session-item-']";

async function archiveAllSessions() {
  const res = await fetch(`${BASE}/api/sessions`);
  if (!res.ok) return;
  const sessions = (await res.json()) as Array<{ id: string; is_archived?: boolean }>;
  for (const s of sessions) {
    if (s.is_archived) continue;
    await fetch(`${BASE}/api/sessions/${s.id}/archive`, {
      method: "POST",
    });
  }
}

test.describe.configure({ mode: "serial" });

test.afterEach(async () => {
  // No leaked state between runs or into the Tektos session list.
  await archiveAllSessions();
});

test("boots into an empty or seeded list", async ({ page }) => {
  await page.goto(PAGE);
  await expect(page.getByTestId("tektos-sessions-page")).toBeVisible();
  // Either the empty state or session items — both valid.
  await expect(
    page.locator(`${ITEMS}, [data-testid='tektos-sessions-empty']`).first(),
  ).toBeVisible({ timeout: 15_000 });

  // Header count pill reflects upstream state.
  await expect(page.getByTestId("tektos-sessions-count")).toBeVisible();
});

test("create → prompt → streamed PONG → render", async ({ page }) => {
  await page.goto(PAGE);
  await expect(page.getByTestId("tektos-sessions-page")).toBeVisible();

  const before = await page.locator(ITEMS).count();
  await page.getByTestId("tektos-sessions-new-btn").click();
  await expect(page.locator(ITEMS)).toHaveCount(before + 1, { timeout: 15_000 });
  // New session is selected automatically after create.
  await expect(page.getByTestId("tektos-sessions-chat-header")).toBeVisible();

  await page.getByTestId("tektos-sessions-input").fill("Reply with exactly: PONG");
  await page.getByTestId("tektos-sessions-send-btn").click();

  // Streaming flag comes and goes; the assistant message completes with
  // stop_reason end_turn (rendered as its sub-line).
  await expect(page.getByTestId("tektos-msg-assistant")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("tektos-sessions-status")).not.toHaveText("streaming", {
    timeout: 120_000,
  });
  const text = await page.getByTestId("tektos-msg-assistant").last().textContent();
  expect(text).toContain("PONG");
});

test("model switch, fork, and archive update the list", async ({ page }) => {
  await page.goto(PAGE);
  await expect(page.getByTestId("tektos-sessions-page")).toBeVisible();

  const before = await page.locator(ITEMS).count();
  await page.getByTestId("tektos-sessions-new-btn").click();
  await expect(page.locator(ITEMS)).toHaveCount(before + 1, { timeout: 15_000 });
  await expect(page.getByTestId("tektos-sessions-chat-header")).toBeVisible();

  // Model switch: pick the recommended model (session was created on it,
  // so the value is unchanged, but the endpoint path is exercised).
  const modelSelect = page.getByTestId("tektos-sessions-model-select");
  await expect(modelSelect).toBeVisible();
  const recommended = (await modelSelect.locator("option").allTextContents()).find((t) =>
    t.includes("(rec)"),
  );
  if (recommended) {
    await modelSelect.selectOption({ label: recommended.trim() });
  }

  // Fork adds one session and moves selection to it.
  await page.getByTestId("tektos-sessions-fork-btn").click();
  await expect(page.locator(ITEMS)).toHaveCount(before + 2, { timeout: 15_000 });

  // Archive removes the fork and clears selection.
  await page.getByTestId("tektos-sessions-archive-btn").click();
  await expect(page.locator(ITEMS)).toHaveCount(before + 1, { timeout: 15_000 });
  await expect(page.getByTestId("tektos-sessions-no-selection")).toBeVisible();
});
