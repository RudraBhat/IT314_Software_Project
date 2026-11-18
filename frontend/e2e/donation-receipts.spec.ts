import { expect, test, type Page } from "@playwright/test";

/**
 * S3-11: Citizen donation receipts view (/my-donations).
 * Fully mocked with page.route so it runs without a live backend.
 */

async function signedInCitizen(page: Page, baseURL: string | undefined) {
  const url = baseURL ?? "http://localhost:3000";
  await page.context().addCookies([
    { name: "session_token", value: "e2e-citizen-donations", url },
    { name: "drch_session", value: "1", url },
  ]);
  await page.route("**/api/session", (route) =>
    route.fulfill({
      json: { authenticated: true, dm: false, citizen: true, role: "NORMAL_USER", name: "Citizen Donor" },
    }),
  );
}

test("empty state is displayed when the citizen has made no donations", async ({ page, baseURL }) => {
  await signedInCitizen(page, baseURL);

  await page.route("**/api/citizen/me/donations*", (route) =>
    route.fulfill({
      json: { items: [], page: 1, limit: 25, total: 0, pages: 0 },
    }),
  );

  await page.goto("/my-donations");

  await expect(page.getByText("No donations yet.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Support Disaster Relief" })).toBeVisible();
});

test("confirmed donation displays the receipt number, amount, and print action", async ({ page, baseURL }) => {
  await signedInCitizen(page, baseURL);

  const confirmedDonation = {
    donation_id: "c6a992bc-7f66-4112-9c17-48f0291e0a21",
    campaign_id: "5b597401-4475-47fe-bbba-c361952e85a3",
    campaign_title: "Cyclone Emergency Medical Relief",
    amount: "5000.00",
    currency: "INR",
    status: "CONFIRMED",
    failure_reason: null,
    is_anonymous: false,
    receipt_no: "RCP-2026-00088",
    receipt_issued_at: "2026-11-15T02:30:00Z",
    created_at: "2026-11-15T02:20:00Z",
    confirmed_at: "2026-11-15T02:30:00Z",
    is_sandbox: true,
  };

  await page.route("**/api/citizen/me/donations*", (route) =>
    route.fulfill({
      json: { items: [confirmedDonation], page: 1, limit: 25, total: 1, pages: 1 },
    }),
  );

  await page.goto("/my-donations");

  await expect(page.getByText("Cyclone Emergency Medical Relief")).toBeVisible();
  await expect(page.getByText("RCP-2026-00088")).toBeVisible();
  await expect(page.getByRole("button", { name: /Print \/ Save Receipt/i })).toBeVisible();
  await expect(page.getByText("Confirmed").first()).toBeVisible();
});

test("failed donations show donor-friendly explanations for each failure reason", async ({ page, baseURL }) => {
  await signedInCitizen(page, baseURL);

  const failedDonations = [
    {
      donation_id: "f1-abandoned",
      campaign_id: "camp-01",
      campaign_title: "Flood Relief Fund",
      amount: "1000.00",
      currency: "INR",
      status: "FAILED",
      failure_reason: "ABANDONED",
      is_anonymous: false,
      receipt_no: null,
      receipt_issued_at: null,
      created_at: "2026-11-15T01:00:00Z",
      confirmed_at: null,
      is_sandbox: true,
    },
    {
      donation_id: "f2-declined",
      campaign_id: "camp-02",
      campaign_title: "Industrial Fire Victims Aid",
      amount: "2500.00",
      currency: "INR",
      status: "FAILED",
      failure_reason: "GATEWAY_DECLINED",
      is_anonymous: false,
      receipt_no: null,
      receipt_issued_at: null,
      created_at: "2026-11-15T01:10:00Z",
      confirmed_at: null,
      is_sandbox: true,
    },
    {
      donation_id: "f3-expired",
      campaign_id: "camp-03",
      campaign_title: "Coastal Cyclone Shelter Supplies",
      amount: "1500.00",
      currency: "INR",
      status: "FAILED",
      failure_reason: "EXPIRED",
      is_anonymous: false,
      receipt_no: null,
      receipt_issued_at: null,
      created_at: "2026-11-15T00:30:00Z",
      confirmed_at: null,
      is_sandbox: true,
    },
  ];

  await page.route("**/api/citizen/me/donations*", (route) =>
    route.fulfill({
      json: { items: failedDonations, page: 1, limit: 25, total: 3, pages: 1 },
    }),
  );

  await page.goto("/my-donations");

  await expect(page.getByText("You cancelled this donation")).toBeVisible();
  await expect(page.getByText("Your payment was declined")).toBeVisible();
  await expect(page.getByText("This donation expired before payment")).toBeVisible();
});
