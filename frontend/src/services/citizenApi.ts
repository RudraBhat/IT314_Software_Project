/**
 * ResQ AI — Citizen API Service
 * Handles communication via the Next.js citizen BFF proxy (/api/citizen/*).
 *
 * Security:
 * - Never transmits client-supplied identity headers (X-User-Id / X-User-Role).
 * - Relies on the verified session cookie (drch_session / session_token) attached by the proxy.
 * - Supports Idempotency-Key headers for reliable reporting.
 * - LocalStorage fallback is strictly gated behind NEXT_PUBLIC_DEMO_MODE.
 */

const IS_DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export interface ApiOptions {
  userId?: string;
  userRole?: string;
  idempotencyKey?: string;
}

export interface ApiResult<T> {
  data: T | null;
  error: string | null;
  isBackend: boolean;
}

async function apiFetch<T>(
  path: string,
  options?: ApiOptions,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> || {}),
    };

    if (options?.idempotencyKey) {
      headers["Idempotency-Key"] = options.idempotencyKey;
    }

    // Call the BFF proxy route in Next.js (or direct relative path)
    const res = await fetch(path, {
      ...init,
      headers,
      credentials: "same-origin",
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const message =
        body?.error?.message ||
        body?.detail ||
        `Server error (${res.status})`;
      return {
        data: null,
        error: message,
        isBackend: true,
      };
    }

    const data = (await res.json()) as T;
    return { data, error: null, isBackend: true };
  } catch (err) {
    if (IS_DEMO_MODE) {
      return {
        data: null,
        error: "Backend unavailable — demo mode active.",
        isBackend: false,
      };
    }
    return {
      data: null,
      error: err instanceof Error ? err.message : "Service unreachable",
      isBackend: false,
    };
  }
}

// ── Report Types ───────────────────────────────────────────────

export interface IncidentReportPayload {
  scenario: string;
  description: string;
  reported_urgency?: string;
  people_affected?: number;
  location_source?: string;
  latitude: number;
  longitude: number;
  address_text?: string;
  landmark?: string;
}

export interface ReportPayload {
  category: string;
  description: string;
  location_name: string;
  lat: number;
  lon: number;
  affected_people_count: number;
  urgent_needs: string[];
  reporter_name: string;
  reporter_phone: string;
}

export interface TimelineEntry {
  status: string;
  timestamp: string;
}

export interface ReportData {
  id: string;
  category: string;
  description: string;
  location_name: string;
  lat: number;
  lon: number;
  affected_people_count: number;
  urgent_needs: string[];
  verification_status: string;
  submitted_at: string;
  linked_incident_id: string | null;
  source: string;
  incident_ref?: string;
  status?: string;
  timeline?: TimelineEntry[];
}

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
  affected_people_estimate: number;
  reference?: string;
  scenario?: string;
  district?: string;
  status?: string;
  verified_priority?: string;
  verified_at?: string;
  latitude?: number;
  longitude?: number;
}

export interface PublicAlert {
  id: string;
  type: string;
  severity: string;
  title: string;
  description: string;
  timestamp: string;
  related_incident_id: string | null;
  alert_id?: string;
  source?: string;
  event_type?: string;
  area_text?: string;
  is_fallback?: boolean;
}

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

// ── Citizen Report Endpoints (authenticated via proxy) ───────────

export async function createReport(
  reportOrOptions: ReportPayload | IncidentReportPayload | ApiOptions,
  optionsOrReport?: ApiOptions | ReportPayload | IncidentReportPayload,
) {
  let report: ReportPayload | IncidentReportPayload;
  let options: ApiOptions = {};

  if (optionsOrReport) {
    if ("scenario" in (optionsOrReport as object) || "category" in (optionsOrReport as object)) {
      options = reportOrOptions as ApiOptions;
      report = optionsOrReport as ReportPayload | IncidentReportPayload;
    } else {
      report = reportOrOptions as ReportPayload | IncidentReportPayload;
      options = optionsOrReport as ApiOptions;
    }
  } else {
    report = reportOrOptions as ReportPayload | IncidentReportPayload;
  }

  return apiFetch<ReportData>("/api/citizen/reports", options, {
    method: "POST",
    body: JSON.stringify(report),
  });
}

export async function fetchMyReports(options?: ApiOptions) {
  return apiFetch<ReportData[]>("/api/citizen/reports", options);
}

export async function fetchReportById(
  reportIdOrOptions: string | ApiOptions,
  optionalId?: string,
) {
  const reportId = typeof reportIdOrOptions === "string" ? reportIdOrOptions : (optionalId ?? "");
  const options = typeof reportIdOrOptions === "object" ? reportIdOrOptions : undefined;
  return apiFetch<ReportData>(`/api/citizen/reports/${reportId}`, options);
}

// ── Public Endpoints (no auth required) ────────────────────────

export async function fetchPublicIncidents() {
  const primary = await apiFetch<PublicIncident[]>("/api/v1/public/incidents");
  if (primary.data || !primary.error) {
    return primary;
  }
  return apiFetch<PublicIncident[]>("/api/public/incidents");
}

export async function fetchPublicAlerts() {
  return apiFetch<PublicAlert[]>("/api/v1/public/alerts");
}

export async function fetchShelters() {
  return apiFetch<ShelterData[]>("/api/public/shelters");
}
