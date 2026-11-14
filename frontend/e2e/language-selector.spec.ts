import { expect, test } from "@playwright/test";

/**
 * Issue #95: sign-in and sign-up show one language at a time, chosen with a searchable,
 * keyboard-operable selector; the choice persists across navigation and refresh.
 */

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("e2e-language-reset")) {
      localStorage.removeItem("resq-auth-language");
      sessionStorage.setItem("e2e-language-reset", "1");
    }
  });
});

test("defaults to English with no inline translations", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in");
  await expect(page.getByRole("button", { name: /Language English/ })).toBeVisible();
  await expect(page.getByText(/[ऀ-ॿ઀-૿]/)).toHaveCount(0);
});

test("keyboard search selects Gujarati and it persists across pages and refresh", async ({ page }) => {
  await page.goto("/login");
  const trigger = page.getByRole("button", { name: /Language English/ });
  await trigger.focus();
  await page.keyboard.press("ArrowDown");

  const search = page.getByRole("combobox", { name: "Search languages" });
  await expect(search).toBeFocused();
  await search.fill("guj");
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.keyboard.press("Enter");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("સાઇન ઇન કરો");
  await expect(page.getByRole("button", { name: /ભાષા ગુજરાતી/ })).toBeFocused();
  await expect(page.locator("html")).toHaveAttribute("lang", "gu");
  await expect(page.getByText("Sign in", { exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: "ખાતું બનાવો" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("તમારું ખાતું બનાવો");

  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("તમારું ખાતું બનાવો");
});

test("search matches native names, Escape closes and no match is announced", async ({ page }) => {
  await page.goto("/signup");
  await page.getByRole("button", { name: /Language/ }).click();
  const search = page.getByRole("combobox", { name: "Search languages" });

  await search.fill("हिन्दी");
  await expect(page.getByRole("option", { name: /हिन्दी/ })).toBeVisible();

  await search.fill("klingon");
  await expect(page.getByRole("option")).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "No language matches your search." })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(search).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Language English/ })).toBeFocused();
});

test("works with touch on a phone-sized screen", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 375, height: 740 }, hasTouch: true });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByRole("button", { name: /Language/ }).tap();
  await page.getByRole("option", { name: /हिन्दी/ }).tap();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("साइन इन करें");
  await context.close();
});
