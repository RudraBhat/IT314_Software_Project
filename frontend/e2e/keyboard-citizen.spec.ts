import { expect, test, type Page } from "@playwright/test";

/**
 * S3-03 (Janvi): the citizen screens work with the keyboard alone.
 * - The report form's radio groups follow the ARIA radio pattern: one tab stop, arrow keys move and select.
 * - A reply to an information request can be typed and sent without a mouse.
 * The citizen BFF is mocked, so this runs without a backend.
 */

const INCIDENT_ID = "6f2d4c1e-8b1a-4d3e-9c55-0a7b9e2f1d44";
const QUESTION = "Is the water still rising near the school?";

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

function needsInformation(status = "NEEDS_INFORMATION") {
  return {
    incident_id: INCIDENT_ID,
    incident_ref: "INC-2026-000188",
    scenario: "urban_flooding",
    status,
    district: "Surat",
    description: "Water entering ground-floor homes near the school.",
    address_text: "Adajan, Surat",
    landmark: null,
    people_affected: 6,
    submitted_at: "2026-11-14T09:00:00Z",
    latitude: 21.1959,
    longitude: 72.7933,
    timeline: [
      { status: "SUBMITTED", timestamp: "2026-11-14T09:00:00Z", message: null },
      { status: "NEEDS_INFORMATION", timestamp: "2026-11-14T09:04:00Z", message: QUESTION },
    ],
  };
}

test("report form radio groups use one tab stop and arrow keys", async ({ page, baseURL }) => {
  await signedInCitizen(page, baseURL);
  await page.goto("/report");

  const scenarios = page.getByRole("radiogroup", { name: "Disaster Scenario" });
  const radios = scenarios.getByRole("radio");
  await expect(radios).toHaveCount(3);

  // Exactly one radio is in the tab order (roving tabindex).
  const tabStops = scenarios.locator('[role="radio"][tabindex="0"]');
  await expect(tabStops).toHaveCount(1);

  const ids = await radios.evaluateAll((els) => els.map((el) => el.getAttribute("data-radio-id")));
  const checkedId = () => scenarios.getByRole("radio", { checked: true }).getAttribute("data-radio-id");
  const start = await checkedId();
  await scenarios.getByRole("radio", { checked: true }).focus();

  await page.keyboard.press("ArrowRight");
  expect(await checkedId()).toBe(ids[(ids.indexOf(start) + 1) % ids.length]);
  await expect(scenarios.getByRole("radio", { checked: true })).toBeFocused();
  await expect(tabStops).toHaveCount(1);

  // Wrapping: two more steps right go round to the starting choice; Left then moves to the one before it.
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  expect(await checkedId()).toBe(start);
  await page.keyboard.press("ArrowLeft");
  expect(await checkedId()).toBe(ids[(ids.indexOf(start) - 1 + ids.length) % ids.length]);
  await expect(scenarios.getByRole("radio", { checked: true })).toBeFocused();

  const urgency = page.getByRole("radiogroup", { name: "Urgency Level" });
  const urgencyChecked = () => urgency.getByRole("radio", { checked: true }).getAttribute("data-radio-id");
  const before = await urgencyChecked();
  await urgency.getByRole("radio", { checked: true }).focus();
  await page.keyboard.press("ArrowDown");
  expect(await urgencyChecked()).not.toBe(before);
  await expect(urgency.getByRole("radio", { checked: true })).toBeFocused();
});

test("a reply to an information request can be sent with the keyboard only", async ({ page, baseURL }) => {
  await signedInCitizen(page, baseURL);
  let current = needsInformation();
  let sentBody: unknown = null;
  await page.route("**/api/citizen/me/incidents", (route) =>
    route.fulfill({ json: { items: [current], page: 1, limit: 25, total: 1, pages: 1 } }),
  );
  await page.route(`**/api/citizen/me/incidents/${INCIDENT_ID}/information-response`, async (route) => {
    sentBody = route.request().postDataJSON();
    current = needsInformation("SUBMITTED");
    await route.fulfill({ status: 201, json: { incident_id: INCIDENT_ID, status: "SUBMITTED" } });
  });

  await page.goto("/my-reports");
  const form = page.getByRole("region", { name: "Reply to the information request" });
  await expect(form.getByText(QUESTION)).toBeVisible();

  const reply = form.getByLabel("Your reply to the dispatcher");
  await reply.focus();
  await page.keyboard.type("Yes, about knee deep now");

  const send = form.getByRole("button", { name: "Send reply" });
  // Tab moves forward until the send button has focus; no mouse is used.
  for (let i = 0; i < 5 && !(await send.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(send).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByRole("status").filter({ hasText: "Your reply was sent" })).toBeVisible();
  expect(sentBody).toEqual({ message: "Yes, about knee deep now" });
});
