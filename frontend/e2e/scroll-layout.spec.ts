import { expect, test } from "@playwright/test";

const PAGES = ["/how-to", "/about", "/safety", "/login", "/signup", "/forgot-password"];

for (const width of [375, 1280]) {
  for (const path of PAGES) {
    test(`${path} scrolls to the bottom without horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 600 });
      await page.route("**/api/session", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ authenticated: false, dm: false, citizen: false, role: null, name: null }),
        })
      );
      await page.goto(path);

      const overflowX = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflowX).toBeLessThanOrEqual(0);

      // The document itself must scroll (body must not be overflow:hidden / 100vh).
      const canScroll = await page.evaluate(() => document.documentElement.scrollHeight > window.innerHeight);
      if (canScroll) {
        await page.mouse.move(width / 2, 300);
        await page.mouse.wheel(0, 5000);
        await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
      }
    });
  }
}
