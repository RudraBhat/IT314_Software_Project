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
  withdrawal_requested?: boolean;
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
  withdrawal_requested?: boolean;
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
    withdrawal_requested: i.withdrawal_requested ?? false,
  };
}

/**
 * Submit a report. The Idempotency-Key is required by the backend (422 IDEMPOTENCY_KEY_REQUIRED
 * otherwise): keep ONE key per form session and reuse it on retries, so a resubmission after a
 * network failure returns the same incident instead of creating a duplicate.
 */
export async function createReport(payload: IncidentReportPayload, options: ApiOptions & { idempotencyKey: string }) {
  return apiFetch<CreatedIncident>("/api/citizen/incidents", options, { method: "POST", body: JSON.stringify(payload) });
}

// ── Evidence photos (issue #68) ────────────────────────────────

export interface EvidencePolicy {
  enabled: boolean;
  max_bytes: number;
  allowed_types: string[];
}

export interface UploadedEvidence {
  evidence_id: string;
  file_name: string;
  sha256: string;
  moderation_state: "PENDING";
}

export async function fetchEvidencePolicy(): Promise<ApiResult<EvidencePolicy>> {
  return apiFetch<EvidencePolicy>("/api/citizen/incidents/evidence-policy");
}

/** Attach a photo to the caller's own report. The file is sent as the raw body, not JSON. */
export async function uploadEvidence(incidentId: string, file: File): Promise<ApiResult<UploadedEvidence>> {
  try {
    const res = await fetch(`/api/citizen/incidents/${encodeURIComponent(incidentId)}/evidence`, {
      method: "POST",
      headers: { "Content-Type": file.type, "X-Filename": encodeURIComponent(file.name) },
      body: file,
      credentials: "same-origin",
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { data: null, error: body?.error?.message || `Upload failed (${res.status})`, isBackend: true };
    }
    return { data: body as UploadedEvidence, error: null, isBackend: true };
  } catch (err) {
    return { data: null, error: err instanceof Error ? err.message : "Service unreachable", isBackend: false };
  }
}

export async function fetchMyReports(): Promise<ApiResult<ReportData[]>> {
  const res = await apiFetch<{ items: MyIncident[] }>("/api/citizen/me/incidents");
  return { ...res, data: res.data ? res.data.items.map(toReport) : null };
}

export async function fetchReportById(reportId: string): Promise<ApiResult<ReportData>> {
  const res = await apiFetch<MyIncident>(`/api/citizen/me/incidents/${encodeURIComponent(reportId)}`);
  return { ...res, data: res.data ? toReport(res.data) : null };
}

/**
 * Citizen response to a dispatcher information request (S2-13): text, a corrected location, or both.
 * POST /api/v1/me/incidents/{id}/information-response via the BFF proxy. The incident returns to SUBMITTED.
 */
export async function replyToInformationRequest(
  incidentId: string,
  message?: string,
  location?: { latitude: number; longitude: number }
): Promise<ApiResult<{ incident_id: string; status: string }>> {
  return apiFetch<{ incident_id: string; status: string }>(
    `/api/citizen/me/incidents/${encodeURIComponent(incidentId)}/information-response`,
    undefined,
    {
      method: "POST",
      body: JSON.stringify({ ...(message ? { message } : {}), ...(location ?? {}) }),
    }
  );
}

/** Ask the dispatchers to withdraw a report. Only records the request; a dispatcher decides. */
export async function requestWithdrawal(incidentId: string, reason?: string): Promise<ApiResult<{ incident_id: string; status: string; withdrawal_requested: boolean }>> {
  return apiFetch(`/api/citizen/me/incidents/${encodeURIComponent(incidentId)}/withdrawal-request`, undefined, {
    method: "POST",
    body: JSON.stringify(reason?.trim() ? { reason: reason.trim() } : {}),
  });
}

// ── Photo attachments (NU-FR-05) ───────────────────────────────

export interface AttachmentData {
  evidence_id: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  uploaded_at: string;
}

/** Client-side limits; the server enforces its own (5 MB, 5 photos, JPEG/PNG/WebP). 4 MB stays under the hosting proxy body limit. */
export const ATTACHMENT_LIMITS = { maxBytes: 4 * 1024 * 1024, maxFiles: 5, types: ["image/jpeg", "image/png", "image/webp"] };

export function attachmentUrl(incidentId: string, evidenceId: string): string {
  return `/api/citizen/me/incidents/${encodeURIComponent(incidentId)}/attachments/${encodeURIComponent(evidenceId)}`;
}

export async function uploadAttachment(incidentId: string, file: File): Promise<ApiResult<AttachmentData>> {
  return apiFetch<AttachmentData>(
    `/api/citizen/me/incidents/${encodeURIComponent(incidentId)}/attachments`,
    undefined,
    { method: "POST", body: file, headers: { "Content-Type": file.type, "X-Filename": encodeURIComponent(file.name) } }
  );
}

export async function fetchAttachments(incidentId: string): Promise<ApiResult<{ items: AttachmentData[]; max_attachments: number }>> {
  return apiFetch(`/api/citizen/me/incidents/${encodeURIComponent(incidentId)}/attachments`);
}

export async function removeAttachment(incidentId: string, evidenceId: string): Promise<ApiResult<{ evidence_id: string; status: string }>> {
  return apiFetch(attachmentUrl(incidentId, evidenceId), undefined, { method: "DELETE" });
}

// ── Account (profile, password) ────────────────────────────────

export interface ProfileData {
  user_id: string;
  email: string;
  full_name: string;
  phone: string | null;
  preferred_language: "en" | "hi" | "gu";
  alerts: { in_app: boolean; email: boolean; sms: boolean };
  created_at: string;
  /** False for a Google sign-in account that never set a password. */
  has_password: boolean;
}

export interface ProfileUpdate {
  full_name?: string;
  phone?: string;
  preferred_language?: "en" | "hi" | "gu";
  email_alerts?: boolean;
  sms_alerts?: boolean;
}

export async function fetchProfile(): Promise<ApiResult<ProfileData>> {
  return apiFetch<ProfileData>("/api/citizen/me/profile");
}

export async function updateProfile(update: ProfileUpdate): Promise<ApiResult<ProfileData>> {
  return apiFetch<ProfileData>("/api/citizen/me/profile", undefined, { method: "PATCH", body: JSON.stringify(update) });
}

/** On success every session ends (the server bumps the token version); the caller signs the user out. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<ApiResult<{ changed: boolean; sign_in_required: boolean }>> {
  return apiFetch("/api/citizen/me/password", undefined, {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

/** Erase personal details and end every session. Refused while a report is still open. */
export async function deleteAccount(password: string): Promise<ApiResult<{ deleted: boolean; sign_in_required: boolean }>> {
  return apiFetch("/api/citizen/me/account/deletion", undefined, { method: "POST", body: JSON.stringify({ password }) });
}

export async function markAllNotificationsRead(): Promise<ApiResult<{ marked_read: number }>> {
  return apiFetch("/api/citizen/me/notifications/read-all", undefined, { method: "POST" });
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
  latitude: number | null;
  longitude: number | null;
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
  lat: number | null;
  lon: number | null;
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
      lat: a.latitude,
      lon: a.longitude,
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
