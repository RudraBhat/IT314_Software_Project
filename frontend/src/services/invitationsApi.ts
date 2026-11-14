/**
 * Account invitation client (talks to the /api/invitations BFF; see app/api/invitations).
 * Errors are thrown as the shared ApiError so useAction shows the server's message.
 */

import { ApiError } from "@/lib/api";

export type InvitableRole = "DISASTER_MGMT" | "FIELD_TEAM" | "APP_MGMT";

export const ROLE_LABEL: Record<InvitableRole, string> = {
  DISASTER_MGMT: "Disaster Management staff",
  FIELD_TEAM: "Field Team responder",
  APP_MGMT: "Application administrator",
};

export type PendingInvitation = {
  user_id: string;
  email: string;
  full_name: string;
  role: InvitableRole;
  permissions: string[];
  team_name: string | null;
  invited_by_name: string | null;
  invitation_expires_at: string | null;
  expired: boolean;
  created_at: string;
};

export type InvitationTeam = { resource_id: string; name: string; agency_name: string | null; status: string };

export type InvitePayload = {
  email: string;
  full_name: string;
  role: InvitableRole;
  phone?: string;
  designation?: string;
  permissions?: string[];
  team_resource_id?: string;
  callsign?: string;
  is_leader?: boolean;
};

async function request<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`/api/invitations${path}`, {
    method: init.method ?? "GET",
    headers: init.body === undefined ? undefined : { "content-type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
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

export const listInvitations = () => request<{ items: PendingInvitation[] }>("");
export const listInvitationTeams = () => request<{ items: InvitationTeam[] }>("/teams");
export const inviteAccount = (body: InvitePayload) =>
  request<{ user_id: string; email: string; status: string; message: string }>("", { method: "POST", body });
export const resendInvitation = (userId: string) =>
  request<{ message: string }>(`/${encodeURIComponent(userId)}/resend`, { method: "POST" });
export const revokeInvitation = (userId: string) =>
  request<void>(`/${encodeURIComponent(userId)}`, { method: "DELETE" });
