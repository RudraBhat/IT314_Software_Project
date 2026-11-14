import { test, expect } from "@playwright/test";

test.describe("End-to-End Urban Flooding Scenario (Sprint 3)", () => {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  test("urban flooding incident lifecycle and negative boundary verification", async ({ request }) => {
    // 1. Citizen registration
    const citizenEmail = `citizen.flood.${Date.now()}@example.in`;
    const regRes = await request.post(`${apiUrl}/api/v1/auth/register`, {
      data: {
        email: citizenEmail,
        password: "StrongPassword123!",
        full_name: "Pooja Shah",
      },
    });
    expect(regRes.status()).toBe(201);
    const citizenToken = (await regRes.json()).access_token;
    const citizenHeaders = { Authorization: `Bearer ${citizenToken}` };

    // Negative check: Out of bounds (Mumbai) coordinates refused
    const mumbaiCoordRes = await request.post(`${apiUrl}/api/v1/incidents`, {
      headers: { ...citizenHeaders, "Idempotency-Key": `flood-outside-${Date.now()}` },
      data: {
        scenario: "urban_flooding",
        description: "Severe waterlogging in Dadar, Mumbai",
        latitude: 19.0178,
        longitude: 72.8478,
      },
    });
    expect(mumbaiCoordRes.status()).toBe(422);
    expect((await mumbaiCoordRes.json()).error.code).toBe("OUTSIDE_GUJARAT");

    // Negative check: Citizen accessing the DM incident list
    const triageRes = await request.get(`${apiUrl}/api/v1/dm/incidents`, {
      headers: citizenHeaders,
    });
    expect(triageRes.status()).toBe(403);

    // 2. Submit valid Urban Flooding incident inside Gujarat (Ahmedabad Ashram Road)
    const ahmedabadLat = 23.0225;
    const ahmedabadLon = 72.5714;
    const submitRes = await request.post(`${apiUrl}/api/v1/incidents`, {
      headers: { ...citizenHeaders, "Idempotency-Key": `flood-submit-${Date.now()}` },
      data: {
        scenario: "urban_flooding",
        description: "Underpass submerged under 5 feet of flood water after cloudburst.",
        latitude: ahmedabadLat,
        longitude: ahmedabadLon,
        address_text: "Ashram Road Underpass, Ahmedabad, Gujarat",
      },
    });
    expect(submitRes.status()).toBe(201);
    const incident = await submitRes.json();
    const incidentId = incident.incident_id;
    expect(incident.incident_ref).toBeTruthy();

    // Negative check: Unverified incident omitted from public list
    const publicList = await (await request.get(`${apiUrl}/api/v1/public/incidents`)).json();
    expect(publicList.some((i: { reference: string }) => i.reference === incident.incident_ref)).toBe(false);

    // Verify incident appears in citizen's personal list
    const myReports = await (await request.get(`${apiUrl}/api/v1/me/incidents`, { headers: citizenHeaders })).json();
    expect(myReports.items.some((i: { incident_id: string }) => i.incident_id === incidentId)).toBe(true);
  });
});
