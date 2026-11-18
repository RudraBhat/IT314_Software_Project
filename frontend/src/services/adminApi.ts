/**
 * Administrator client (talks to the /api/admin BFF; see app/api/admin).
 * Errors are thrown as the shared ApiError so screens show the server's message.
 */

import { ApiError } from "@/lib/api";

import type { InvitableRole } from "./invitationsApi";

export type AccountStatus = "ACTIVE" | "PENDING_SETUP" | "DISABLED" | "LOCKED" | "PENDING_VERIFICATION";

export type StaffAccount = {
  user_id: string;
  email: string;
  full_name: string;
  role: InvitableRole;
  designation: string | null;
  status: AccountStatus;
  mfa_enabled: boolean;
  last_login_at: string | null;
  is_locked: boolean;
  permissions: string[];
  team_name: string | null;
  /** Devices currently signed in (sessions that can still renew). */
  active_sessions: number;
  created_at: string;
  is_you: boolean;
};

export type AccountSummary = {
  total: number;
  by_role: Partial<Record<InvitableRole, number>>;
  by_status: Partial<Record<AccountStatus, number>>;
};

export type AccountsPage = {
  items: StaffAccount[];
  page: number;
  limit: number;
  total: number;
  pages: number;
  summary: AccountSummary;
};

export type AccountQuery = { q?: string; role?: InvitableRole | ""; status?: AccountStatus | ""; page?: number };

async function request<T>(path: string, init?: { method: "POST" | "PUT"; body: unknown }): Promise<T> {
  const res = await fetch(`/api/admin/${path}`, {
    method: init?.method ?? "GET",
    headers: init ? { "content-type": "application/json" } : undefined,
    body: init ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  const payload = await res.json().catch(() => null);
  if (!res.ok) {
    const err = payload?.error;
    throw new ApiError(
      typeof err?.message === "string" ? err.message : `Request failed (${res.status}).`,
      res.status,
      typeof err?.code === "string" ? err.code : "REQUEST_FAILED",
      err?.details ?? null,
    );
  }
  return payload as T;
}

export async function listAccounts(query: AccountQuery): Promise<AccountsPage> {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.role) params.set("role", query.role);
  if (query.status) params.set("status", query.status);
  params.set("page", String(query.page ?? 1));
  params.set("limit", "15");
  return request<AccountsPage>(`accounts?${params.toString()}`);
}

/** Download the directory, with the same filters as the list, as a CSV file (the export is audited). */
export async function exportAccounts(query: AccountQuery): Promise<{ blob: Blob; filename: string }> {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.role) params.set("role", query.role);
  if (query.status) params.set("status", query.status);
  const res = await fetch(`/api/admin/accounts/export?${params.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new ApiError(
      typeof payload?.error?.message === "string" ? payload.error.message : `Export failed (${res.status}).`,
      res.status,
      typeof payload?.error?.code === "string" ? payload.error.code : "REQUEST_FAILED",
      null,
    );
  }
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  return { blob: await res.blob(), filename: `staff-accounts-${stamp}.csv` };
}

export type StatusChangeResult = { user_id: string; status: AccountStatus };

/** Switch a staff account off. The reason is required and audited; sessions end at once. */
export const disableAccount = (userId: string, reason: string) =>
  request<StatusChangeResult>(`accounts/${encodeURIComponent(userId)}/disable`, { method: "POST", body: { reason } });

/** Switch a disabled account back on (an unfinished invitation returns to awaiting setup). */
export const enableAccount = (userId: string, reason: string) =>
  request<StatusChangeResult>(`accounts/${encodeURIComponent(userId)}/enable`, { method: "POST", body: { reason } });

export type PermissionResult = { user_id: string; permissions: string[] };

/** Replace a Disaster Management account's permissions. Applies at once; the reason is audited. */
export const setPermissions = (userId: string, permissions: string[], reason: string) =>
  request<PermissionResult>(`accounts/${encodeURIComponent(userId)}/permissions`, { method: "PUT", body: { permissions, reason } });

export type AuditResult = "SUCCESS" | "FAILURE" | "DENIED";

export type AuditPerson = { user_id?: string | null; role: string | null; name: string | null; email: string | null };

export type AuditEntry = {
  audit_id: number;
  occurred_at: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  result: AuditResult;
  rationale: string | null;
  actor: AuditPerson | null;
  target: AuditPerson | null;
  ip: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
};

export type AuditPage = {
  items: AuditEntry[];
  page: number;
  limit: number;
  total: number;
  pages: number;
  facets: { actions: string[] };
};

export type AuditQuery = {
  q?: string;
  action?: string;
  result?: AuditResult | "";
  /** Only entries made by or about this account. */
  user_id?: string;
  from?: string;
  to?: string;
  page?: number;
};

export async function listAudit(query: AuditQuery): Promise<AuditPage> {
  const params = new URLSearchParams();
  if (query.user_id) params.set("user_id", query.user_id);
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.action) params.set("action", query.action);
  if (query.result) params.set("result", query.result);
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  params.set("page", String(query.page ?? 1));
  params.set("limit", "20");
  return request<AuditPage>(`audit?${params.toString()}`);
}

export type AuditVerification = {
  valid: boolean;
  records: number | null;
  mismatches: number | null;
  message: string;
  verified_at: string;
};

export type SystemStatus = {
  database: { status: string; latency_ms: number };
  version: string;
  email: { configured: boolean; simulated: boolean };
  mfa_key_valid: boolean;
  accounts: { invitations_open: number; invitations_expired: number; locked: number; active_without_mfa: number };
  audit: { last_entry_at: string | null; last_verified_at: string | null; last_verification_ok: boolean | null };
  checked_at: string;
};

/** Platform health for administrators: booleans, counts and timestamps only. */
export const getSystemStatus = () => request<SystemStatus>("system");

/** Check the audit log's hash chain. The check is itself recorded in the log. */
export const verifyAudit = () => request<AuditVerification>("audit/verify", { method: "POST", body: {} });

export type BulkAction = "disable" | "sign-out";
export type BulkOutcome = { user_id: string; ok: boolean; code: string | null; message: string | null };
export type BulkResult = { action: BulkAction; done: number; skipped: number; results: BulkOutcome[] };

/** Disable or sign out several accounts. Each is handled on its own; the result lists every outcome. */
export const bulkChange = (action: BulkAction, userIds: string[], reason: string) =>
  request<BulkResult>("accounts/bulk", { method: "POST", body: { action, user_ids: userIds, reason } });

export type ProfileResult = { user_id: string; full_name: string; designation: string | null };

/** Correct a staff member's name or designation. The email address cannot be changed. Reason is audited. */
export const updateProfile = (userId: string, details: { full_name: string; designation: string | null }, reason: string) =>
  request<ProfileResult>(`accounts/${encodeURIComponent(userId)}/profile`, { method: "PUT", body: { ...details, reason } });

/** End every session of an active account (it stays usable and the person signs in again). Reason is audited. */
export const signOutAccount = (userId: string, reason: string) =>
  request<StatusChangeResult & { signed_out: boolean }>(`accounts/${encodeURIComponent(userId)}/sign-out`, { method: "POST", body: { reason } });

export type ResetResult = { user_id: string; status: AccountStatus; invitation_expires_at: string; email_configured: boolean };

/** Clear a person's password and authenticator and email them a one-time setup link. Reason is audited. */
export const resetCredentials = (userId: string, reason: string) =>
  request<ResetResult>(`accounts/${encodeURIComponent(userId)}/reset-credentials`, { method: "POST", body: { reason } });
