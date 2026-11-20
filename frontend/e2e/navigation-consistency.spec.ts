import { test, expect } from "@playwright/test";

/**
 * Issue #172: Navigation bar consistency and layout shift prevention across public and citizen pages.
 * Verifies uniform container max-w-7xl width, standardized brand subtitle,
 * persistent links across routes, and mobile drawer accessibility.
 */

test.describe("Global Navigation Consistency (Issue #172)", () => {
  const routes = [
    { path: "/", name: "Home / Live Map" },
    { path: "/about", name: "About" },
    { path: "/how-to", name: "How to use" },
    { path: "/safety", name: "Safety" },
    { path: "/donate", name: "Donate" },
    { path: "/my-donations", name: "My Donations" },
  ];

  for (const route of routes) {
    test(`header retains standardized max-w-7xl width and branding subtitle on ${route.name} (${route.path})`, async ({ page }) => {
      await page.goto(route.path);
      const header = page.locator("header");
      await expect(header).toBeVisible();

      // Subtitle is uniformly 'Gujarat Emergency Portal'
      await expect(header.getByText("Gujarat Emergency Portal")).toBeVisible();

      // Container uses max-w-7xl to prevent horizontal layout shift
      const container = header.locator("div.max-w-7xl");
      await expect(container).toBeVisible();
    });
  }

  test("persistent navigation links are visible on desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/about");

    const header = page.locator("header");
    await expect(header.getByRole("link", { name: "Map" })).toBeVisible();
    await expect(header.getByRole("link", { name: "Report Incident" })).toBeVisible();
    await expect(header.getByRole("link", { name: "Safety" })).toBeVisible();
    await expect(header.getByRole("link", { name: "How to use" })).toBeVisible();
    await expect(header.getByRole("link", { name: "About" })).toBeVisible();
    await expect(header.getByRole("link", { name: "Donate" })).toBeVisible();
    await expect(header.getByRole("link", { name: "Sign In" })).toBeVisible();
    // My Reports lives on the citizen dashboard (a tab), not in the shared bar.
    await expect(header.getByRole("link", { name: "My Reports" })).toHaveCount(0);
    // The page you are on stays in the bar and is marked as current.
    await expect(header.getByRole("link", { name: "About" })).toHaveAttribute("aria-current", "page");
    await expect(header.getByRole("link", { name: "Safety" })).not.toHaveAttribute("aria-current", "page");
  });

  test("mobile drawer toggles and exposes complete link set on small viewports", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/donate");

    // Hamburger button is visible on mobile
    const toggle = page.getByRole("button", { name: "Toggle menu" });
    await expect(toggle).toBeVisible();

    // Click to open mobile menu
    await toggle.click();

    const mobileNav = page.getByRole("navigation", { name: "Mobile Menu" });
    await expect(mobileNav).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "Live Map" })).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "Report Incident" })).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "My Reports" })).toHaveCount(0);
    await expect(mobileNav.getByRole("link", { name: "Safety Guidelines" })).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "How to use" })).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "About ResQ" })).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "Donate to Relief Fund" })).toHaveAttribute("aria-current", "page");
    await expect(mobileNav.getByRole("link", { name: "Sign In" })).toBeVisible();

    // Click toggle to close
    await toggle.click();
    await expect(mobileNav).not.toBeVisible();
  });
});

