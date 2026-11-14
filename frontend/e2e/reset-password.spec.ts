import { expect, test } from "@playwright/test";

/**
 * Issue #98 smoke check: the password reset page talks only to its own origin (server actions),
 * never to the backend on `<host>:8000`, so it works when the backend is on a different host.
 */
test("reset-password page validates the token through the BFF, not the backend port", async ({ page, baseURL }) => {
  const origin = new URL(baseURL ?? "http://localhost:3000").origin;
  const offOrigin: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    const isPageAsset = url.origin === origin || url.protocol === "data:";
    if (!isPageAsset && url.port === "8000") offOrigin.push(request.url());
  });

  await page.goto("/reset-password?token=not-a-real-reset-token");

  await expect(page.getByText(/invalid|expired/i).first()).toBeVisible({ timeout: 15000 });
  expect(offOrigin).toEqual([]);
});

test("reset-password page without a token explains what to do", async ({ page }) => {
  await page.goto("/reset-password");
  await expect(page.getByText(/missing password reset token/i)).toBeVisible();
});
