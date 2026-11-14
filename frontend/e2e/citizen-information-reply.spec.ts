import { expect, test, type Page } from "@playwright/test";

/**
 * Issue #99: a citizen can answer a NEEDS_INFORMATION request from My Reports.
 * The citizen BFF is mocked, so this runs without a backend.
 */

const INCIDENT_ID = "3c0b05b3-3a1e-450e-a226-bcfe69d0d939";
const QUESTION = "Which landmark is nearest to the flooded street?";

function incident(status: string, extraTimeline: object[] = []) {
  return {
    incident_id: INCIDENT_ID,
    incident_ref: "INC-2026-000104",
    scenario: "urban_flooding",
    status,
    district: "Ahmedabad",
    description: "Severe waterlogging on the main market road, water entered shops.",
    address_text: "Near Usmanpura Underpass",
    landmark: null,
    people_affected: 15,
    submitted_at: "2026-11-12T10:00:00Z",
    latitude: 23.0225,
    longitude: 72.5714,
    timeline: [
      { status: "SUBMITTED", timestamp: "2026-11-12T10:00:00Z", message: null },
      { status: "NEEDS_INFORMATION", timestamp: "2026-11-12T10:05:00Z", message: QUESTION },
      ...extraTimeline,
    ],
  };
}

async function signedInCitizen(page: Page, baseURL: string | undefined) {
  const url = baseURL ?? "http://localhost:3000";
  await page.context().addCookies([
    { name: "session_token", value: "e2e-citizen", url },
    { name: "drch_session", value: "1", url },
  ]);
  await page.route("**/api/session", (route) =>
    route.fulfill({ json: { authenticated: true, dm: false, citizen: true, role: "NORMAL_USER", name: "Citizen" } }),
  );
}

test("citizen sees the dispatcher's question, replies, and the report returns to verification", async ({ page, baseURL }) => {
  await signedInCitizen(page, baseURL);
  let current = incident("NEEDS_INFORMATION");
  let sentBody: unknown = null;

  await page.route("**/api/citizen/me/incidents", (route) =>
    route.fulfill({ json: { items: [current], page: 1, limit: 25, total: 1, pages: 1 } }),
  );
  await page.route(`**/api/citizen/me/incidents/${INCIDENT_ID}/information-response`, async (route) => {
    sentBody = route.request().postDataJSON();
    current = incident("SUBMITTED", [
      { status: "SUBMITTED", timestamp: "2026-11-12T10:10:00Z", message: "Reporter reply: Near the temple gate" },
    ]);
    await route.fulfill({ status: 201, json: { incident_id: INCIDENT_ID, status: "SUBMITTED" } });
  });

  await page.goto("/my-reports");
  const form = page.getByRole("region", { name: "Reply to the information request" });
  await expect(form.getByText(QUESTION)).toBeVisible();

  const reply = form.getByLabel("Your reply to the dispatcher");
  const send = form.getByRole("button", { name: "Send reply" });
  await reply.fill("ok");
  await expect(send).toBeDisabled();

  await reply.fill("Near the temple gate");
  await send.click();

  await expect(page.getByRole("status").filter({ hasText: "Your reply was sent" })).toBeVisible();
  expect(sentBody).toEqual({ message: "Near the temple gate" });
  await expect(page.getByText("Awaiting Verification").first()).toBeVisible();
});

test("a backend refusal is shown inline and the form stays usable", async ({ page, baseURL }) => {
  await signedInCitizen(page, baseURL);
  await page.route("**/api/citizen/me/incidents", (route) =>
    route.fulfill({ json: { items: [incident("NEEDS_INFORMATION")], page: 1, limit: 25, total: 1, pages: 1 } }),
  );
  await page.route(`**/api/citizen/me/incidents/${INCIDENT_ID}/information-response`, (route) =>
    route.fulfill({
      status: 409,
      json: { error: { code: "NOT_AWAITING_INFORMATION", message: "No information has been requested for this report", details: null } },
    }),
  );

  await page.goto("/my-reports");
  const form = page.getByRole("region", { name: "Reply to the information request" });
  await form.getByLabel("Your reply to the dispatcher").fill("Near the temple gate");
  await form.getByRole("button", { name: "Send reply" }).click();

  await expect(form.getByRole("alert")).toHaveText("No information has been requested for this report");
  await expect(form.getByRole("button", { name: "Send reply" })).toBeEnabled();
});
