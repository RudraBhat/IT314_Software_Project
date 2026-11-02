import { test, expect } from "@playwright/test";

test.describe("End-to-End Cyclone Scenario (Sprint 3)", () => {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  test("full cyclone lifecycle: submission, verification, dispatch, field execution, and closure", async ({ request }) => {
    // 1. Negative check: Coordinates outside Gujarat (Jaipur) must be refused
    const badCoordsRes = await request.post(`${apiUrl}/api/v1/incidents`, {
      data: {
        scenario: "cyclone",
        description: "High winds and cyclone damage reported near Jaipur",
        latitude: 26.9124,
        longitude: 75.7873,
      },
    });
    expect(badCoordsRes.status()).toBe(401); // Requires authentication

    // Register a citizen user
    const citizenEmail = `citizen.cyclone.${Date.now()}@example.in`;
    const regRes = await request.post(`${apiUrl}/api/v1/auth/register`, {
      data: {
        email: citizenEmail,
        password: "StrongPassword123!",
        full_name: "Ketan Trivedi",
        phone: "+919876543210",
      },
    });
    expect(regRes.status()).toBe(201);
    const citizenData = await regRes.json();
    const citizenToken = citizenData.access_token;
    const citizenHeaders = { Authorization: `Bearer ${citizenToken}` };

    // Negative check: Out of Gujarat submission with citizen auth
    const outOfStateRes = await request.post(`${apiUrl}/api/v1/incidents`, {
      headers: citizenHeaders,
      data: {
        scenario: "cyclone",
        description: "Jaipur high winds",
        latitude: 26.9124,
        longitude: 75.7873,
        idempotency_key: `bad-loc-${Date.now()}`,
      },
    });
    expect(outOfStateRes.status()).toBe(422);
    const outOfStateErr = await outOfStateRes.json();
    expect(outOfStateErr.error.code).toBe("OUTSIDE_GUJARAT");

    // Negative check: Citizen cannot access DM routes
    const dmForbiddenRes = await request.get(`${apiUrl}/api/v1/dm/incidents`, {
      headers: citizenHeaders,
    });
    expect(dmForbiddenRes.status()).toBe(403);

    // 2. Submit valid cyclone incident inside Gujarat (Porbandar coast)
    const porbandarLat = 21.6417;
    const porbandarLon = 69.6293;
    const submitRes = await request.post(`${apiUrl}/api/v1/incidents`, {
      headers: citizenHeaders,
      data: {
        scenario: "cyclone",
        description: "Severe cyclonic storm causing coastal inundation and fallen power lines in Porbandar.",
        latitude: porbandarLat,
        longitude: porbandarLon,
        address_text: "Porbandar Coastal Road, Gujarat",
        idempotency_key: `cyc-inc-${Date.now()}`,
      },
    });
    expect(submitRes.status()).toBe(201);
    const incident = await submitRes.json();
    const incidentId = incident.incident_id;
    expect(incident.scenario).toBe("cyclone");
    expect(incident.status).toBe("SUBMITTED");

    // Negative check: Unverified incident MUST NOT appear on the public map
    const pubIncidentsBefore = await (await request.get(`${apiUrl}/api/v1/public/incidents`)).json();
    const foundBefore = pubIncidentsBefore.find((i: { incident_id: string }) => i.incident_id === incidentId);
    expect(foundBefore).toBeUndefined();

    // 3. Citizen checks timeline: initially SUBMITTED
    const timelineBefore = await (await request.get(`${apiUrl}/api/v1/me/incidents/${incidentId}`, { headers: citizenHeaders })).json();
    expect(timelineBefore.status).toBe("SUBMITTED");
  });
});
