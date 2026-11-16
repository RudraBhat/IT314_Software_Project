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

async function request<T>(path: string, init?: { method: string; body: unknown }): Promise<T> {
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

export type StatusChangeResult = { user_id: string; status: AccountStatus };

/** Switch a staff account off. The reason is required and audited; sessions end at once. */
export const disableAccount = (userId: string, reason: string) =>
  request<StatusChangeResult>(`accounts/${encodeURIComponent(userId)}/disable`, { method: "POST", body: { reason } });

/** Switch a disabled account back on (an unfinished invitation returns to awaiting setup). */
export const enableAccount = (userId: string, reason: string) =>
  request<StatusChangeResult>(`accounts/${encodeURIComponent(userId)}/enable`, { method: "POST", body: { reason } });
