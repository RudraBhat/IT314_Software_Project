import { test, expect } from "@playwright/test";

test.describe("End-to-End Industrial Fire Scenario (Sprint 3)", () => {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  test("industrial fire incident lifecycle and negative isolation checks", async ({ request }) => {
    // 1. Citizen registration
    const citizenEmail = `citizen.fire.${Date.now()}@example.in`;
    const regRes = await request.post(`${apiUrl}/api/v1/auth/register`, {
      data: {
        email: citizenEmail,
        password: "StrongPassword123!",
        full_name: "Vikram Mehta",
      },
    });
    expect(regRes.status()).toBe(201);
    const citizenToken = (await regRes.json()).access_token;
    const citizenHeaders = { Authorization: `Bearer ${citizenToken}` };

    // Negative check: Foreign coordinates (Delhi) refused
    const foreignCoordRes = await request.post(`${apiUrl}/api/v1/incidents`, {
      headers: citizenHeaders,
      data: {
        scenario: "industrial_fire",
        description: "Chemical refinery fire in Okhla, Delhi",
        latitude: 28.5355,
        longitude: 77.2638,
        idempotency_key: `delhi-fire-${Date.now()}`,
      },
    });
    expect(foreignCoordRes.status()).toBe(422);
    expect((await foreignCoordRes.json()).error.code).toBe("OUTSIDE_GUJARAT");

    // Negative check: Citizen accessing DM resources
    const dmRes = await request.get(`${apiUrl}/api/v1/dm/signals`, {
      headers: citizenHeaders,
    });
    expect(dmRes.status()).toBe(403);

    // 2. Submit valid Industrial Fire incident inside Gujarat (Dahej PCPIR)
    const dahejLat = 21.7100;
    const dahejLon = 72.5800;
    const submitRes = await request.post(`${apiUrl}/api/v1/incidents`, {
      headers: citizenHeaders,
      data: {
        scenario: "industrial_fire",
        description: "Major boiler explosion and toxic chemical blaze in Dahej chemical park.",
        latitude: dahejLat,
        longitude: dahejLon,
        address_text: "Dahej SEZ, Bharuch District, Gujarat",
        idempotency_key: `fire-inc-${Date.now()}`,
      },
    });
    expect(submitRes.status()).toBe(201);
    const incident = await submitRes.json();
    const incidentId = incident.incident_id;
    expect(incident.scenario).toBe("industrial_fire");

    // Negative check: unverified incident is omitted from public feed
    const publicList = await (await request.get(`${apiUrl}/api/v1/public/incidents`)).json();
    expect(publicList.some((i: { incident_id: string }) => i.incident_id === incidentId)).toBe(false);

    // Citizen tracks report
    const myIncident = await (await request.get(`${apiUrl}/api/v1/me/incidents/${incidentId}`, { headers: citizenHeaders })).json();
    expect(myIncident.incident_id).toBe(incidentId);
    expect(myIncident.status).toBe("SUBMITTED");
  });
});
