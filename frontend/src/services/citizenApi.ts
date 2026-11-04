/**
 * ResQ citizen API client (talks to the Next.js BFF at /api/citizen/* and the public API).
 *
 * Security: never sends identity headers; the BFF attaches the verified session token server-side.
 * There is NO offline/demo fallback here: when the backend fails the caller receives `error` and
 * must show an error state - never invented data.
 *
 * Contracts: docs/api_contracts.md sections 1, 2.3 and 2.4.
 */

export interface ApiOptions {
  idempotencyKey?: string;
}

export interface ApiResult<T> {
  data: T | null;
  error: string | null;
  isBackend: boolean;
}

async function apiFetch<T>(path: string, options?: ApiOptions, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...((init?.headers as Record<string, string>) || {}),
    };
    if (options?.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

    const res = await fetch(path, { ...init, headers, credentials: "same-origin", cache: "no-store" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { data: null, error: body?.error?.message || body?.detail || `Server error (${res.status})`, isBackend: true };
    }
    return { data: (await res.json()) as T, error: null, isBackend: true };
  } catch (err) {
    return { data: null, error: err instanceof Error ? err.message : "Service unreachable", isBackend: false };
  }
}

// ── Reporting (authenticated) ──────────────────────────────────

export type Scenario = "cyclone" | "industrial_fire" | "urban_flooding";

export interface IncidentReportPayload {
  scenario: Scenario;
  description: string;
  reported_urgency?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  people_affected?: number;
  location_source?: "GPS" | "MAP_PIN" | "MANUAL";
  latitude: number;
  longitude: number;
  address_text?: string;
  landmark?: string;
  details?: Record<string, unknown>;
}

export interface CreatedIncident {
  incident_id: string;
  incident_ref: string;
  status: string;
  district: string | null;
  created_at: string;
}

export interface TimelineEntry {
  status: string;
  timestamp: string;
  message?: string | null;
}

/** View model used by the citizen screens (built from GET /api/v1/me/incidents). */
export interface ReportData {
  id: string;
  incident_ref: string;
  category: string;
  description: string;
  location_name: string;
  lat: number;
  lon: number;
  affected_people_count: number;
  urgent_needs: string[];
  verification_status: string;
  status: string;
  submitted_at: string;
  linked_incident_id: string | null;
  source: string;
  timeline: TimelineEntry[];
}

interface MyIncident {
  incident_id: string;
  incident_ref: string;
  scenario: Scenario;
  status: string;
  district: string | null;
  description: string;
  address_text: string | null;
  landmark: string | null;
  people_affected: number | null;
  submitted_at: string;
  latitude: number | null;
  longitude: number | null;
  timeline: TimelineEntry[];
}

export const SCENARIO_LABEL: Record<Scenario, string> = {
  urban_flooding: "Flood / Urban Flood",
  cyclone: "Cyclone / Coastal Flooding",
  industrial_fire: "Major Urban / Building Fire",
};

export const CATEGORY_TO_SCENARIO: Record<string, Scenario> = {
  "Flood / Urban Flood": "urban_flooding",
  "Cyclone / Coastal Flooding": "cyclone",
  "Major Urban / Building Fire": "industrial_fire",
};

function toReport(i: MyIncident): ReportData {
  return {
    id: i.incident_id,
    incident_ref: i.incident_ref,
    category: SCENARIO_LABEL[i.scenario] ?? i.scenario,
    description: i.description,
    location_name: i.address_text || i.landmark || i.district || "Gujarat",
    lat: i.latitude ?? 0,
    lon: i.longitude ?? 0,
    affected_people_count: i.people_affected ?? 0,
    urgent_needs: [],
    verification_status: i.status,
    status: i.status,
    submitted_at: i.submitted_at,
    linked_incident_id: null,
    source: "CITIZEN_APP",
    timeline: i.timeline ?? [],
  };
}

export async function createReport(payload: IncidentReportPayload, options?: ApiOptions) {
  return apiFetch<CreatedIncident>("/api/citizen/incidents", options, { method: "POST", body: JSON.stringify(payload) });
}

export async function fetchMyReports(): Promise<ApiResult<ReportData[]>> {
  const res = await apiFetch<{ items: MyIncident[] }>("/api/citizen/me/incidents");
  return { ...res, data: res.data ? res.data.items.map(toReport) : null };
}

export async function fetchReportById(reportId: string): Promise<ApiResult<ReportData>> {
  const res = await apiFetch<MyIncident>(`/api/citizen/me/incidents/${encodeURIComponent(reportId)}`);
  return { ...res, data: res.data ? toReport(res.data) : null };
}

// ── Public endpoints (no auth) ─────────────────────────────────

/** Contract: GET /api/v1/public/incidents */
interface PublicIncidentDto {
  reference: string;
  scenario: Scenario;
  district: string | null;
  status: string;
  verified_priority: string | null;
  verified_at: string | null;
  latitude: number;
  longitude: number;
  is_simulated?: boolean;
}

/** View model used by the citizen map (derived from the public contract; no invented fields). */
export interface PublicIncident {
  id: string;
  category: string;
  title: string;
  lat: number;
  lon: number;
  location_name: string;
  severity: string;
  lifecycle_status: string;
  detected_at: string;
  scenario: Scenario;
  district: string | null;
}

export async function fetchPublicIncidents(): Promise<ApiResult<PublicIncident[]>> {
  const res = await apiFetch<PublicIncidentDto[]>("/api/v1/public/incidents");
  if (!res.data) return { ...res, data: null };
  return {
    ...res,
    data: res.data.map((i) => ({
      id: i.reference,
      category: SCENARIO_LABEL[i.scenario] ?? i.scenario,
      title: `${SCENARIO_LABEL[i.scenario] ?? i.scenario}${i.district ? ` — ${i.district}` : ""}`,
      lat: i.latitude,
      lon: i.longitude,
      location_name: i.district ?? "Gujarat",
      severity: i.verified_priority ?? "UNASSIGNED",
      lifecycle_status: i.status,
      detected_at: i.verified_at ?? "",
      scenario: i.scenario,
      district: i.district,
    })),
  };
}

/** Contract: GET /api/v1/public/alerts */
interface PublicAlertDto {
  alert_id: string;
  source: string;
  event_type: string;
  severity: string;
  area_text: string | null;
  is_fallback: boolean;
  effective_at: string | null;
  expires_at: string | null;
}

export interface PublicAlert {
  id: string;
  type: string;
  severity: string;
  title: string;
  description: string;
  timestamp: string;
  related_incident_id: string | null;
  source: string;
  is_fallback: boolean;
}

export async function fetchPublicAlerts(): Promise<ApiResult<PublicAlert[]>> {
  const res = await apiFetch<PublicAlertDto[]>("/api/v1/public/alerts");
  if (!res.data) return { ...res, data: null };
  return {
    ...res,
    data: res.data.map((a) => ({
      id: a.alert_id,
      type: a.event_type,
      severity: a.severity,
      title: `${a.event_type.replace(/_/g, " ")} alert${a.area_text ? ` — ${a.area_text}` : ""}`,
      description: a.area_text ?? "",
      timestamp: a.effective_at ?? "",
      related_incident_id: null,
      source: a.source,
      is_fallback: a.is_fallback,
    })),
  };
}

// ── Shelters: there is no shelter API in the approved scope yet ──

export interface ShelterData {
  id: string;
  name: string;
  type: string;
  lat: number;
  lon: number;
  address: string;
  total_capacity: number | null;
  current_occupancy: number | null;
  available_beds: number | null;
  contact_number: string;
  status: string;
  notes: string | null;
}

/** No backend source exists, so this is honestly empty rather than filled with sample data. */
export async function fetchShelters(): Promise<ApiResult<ShelterData[]>> {
  return { data: [], error: null, isBackend: true };
}

// ── Campaigns and Donations ─────────────────────────────────────

export interface PublicCampaign {
  campaign_id: string;
  title: string;
  purpose: string;
  scenario: string | null;
  target_amount: number | null;
  currency: string;
  status: string;
}

export async function fetchPublicCampaigns(): Promise<ApiResult<PublicCampaign[]>> {
  return apiFetch<PublicCampaign[]>("/api/v1/public/campaigns");
}

// ── Citizen Notifications ───────────────────────────────────────

export interface InAppNotification {
  notification_id: string;
  event_code: string;
  title: string;
  body: string;
  related_id: string | null;
  created_at: string;
  read_at: string | null;
}

export async function fetchMyNotifications(): Promise<ApiResult<{ items: InAppNotification[]; total: number }>> {
  return apiFetch<{ items: InAppNotification[]; total: number }>("/api/citizen/me/notifications");
}

export async function markNotificationRead(id: string): Promise<ApiResult<{ notification_id: string; read_at: string }>> {
  return apiFetch<{ notification_id: string; read_at: string }>(`/api/citizen/me/notifications/${encodeURIComponent(id)}/read`, undefined, { method: "POST" });
}
