"use server";

/**
 * Account flows that run before a session exists: password reset, invitation setup and Google
 * sign-in (docs/api_contracts.md section 2).
 *
 * These are Next.js server actions (backend-for-frontend), like app/login/actions.ts: the browser
 * only ever talks to its own origin and the server calls the backend at API_URL. That keeps the
 * flows working when the frontend and backend are on different hosts (Vercel + Render), needs no
 * browser CORS access to the backend, and lets the session cookie be set httpOnly on the server.
 * Server actions are POST-only and Next.js checks their Origin, so they are same-origin by design.
 */

import { cookies } from "next/headers";

import { API_URL, SESSION_COOKIE, cookieOptions } from "@/lib/session";

import type { UserProfile } from "../types/resq";

type BackendResult = { ok: boolean; status: number; data: Record<string, any> };

const UNREACHABLE = "The authentication service is unreachable. Try again shortly.";

/** Not exported: an exported helper in a "use server" file would itself become a public action. */
async function callBackend(
  path: string,
  init: { method?: "GET" | "POST"; body?: unknown; timeoutMs?: number } = {},
): Promise<BackendResult> {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: init.method ?? "POST",
      headers: init.body === undefined ? undefined : { "content-type": "application/json" },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
      signal: AbortSignal.timeout(init.timeoutMs ?? 10000),
    });
    const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 503, data: { error: { code: "BACKEND_UNAVAILABLE", message: UNREACHABLE } } };
  }
}

function errorText(result: BackendResult, fallback: string): string {
  const message = result.data?.error?.message;
  return typeof message === "string" && message ? message : fallback;
}

async function startSession(accessToken: string, expiresIn: unknown): Promise<void> {
  const maxAge = Number(expiresIn) || 3600;
  const jar = await cookies();
  jar.set(SESSION_COOKIE, accessToken, cookieOptions(maxAge));
  jar.set("drch_session", "1", cookieOptions(maxAge));
}

export interface AuthApiResponse {
  success: boolean;
  message?: string;
  user?: UserProfile;
  error?: string;
  isOffline?: boolean;
}

// ── Password reset ──────────────────────────────────────────────────────

/** Request a password reset link. The backend answers the same way for unknown emails. */
export async function requestPasswordReset(
  email: string,
): Promise<{ success: boolean; message: string; error?: string }> {
  const res = await callBackend("/api/v1/auth/forgot-password", { body: { email: email.trim().toLowerCase() } });
  if (!res.ok) {
    const message = errorText(res, "Failed to process password reset request.");
    return { success: false, message, error: message };
  }
  return {
    success: true,
    message: res.data.message || "If this email is registered and active, a password reset link has been sent.",
  };
}

/** Check a reset token before showing the new-password form. */
export async function verifyResetToken(token: string): Promise<{ valid: boolean; error?: string }> {
  const res = await callBackend(`/api/v1/auth/reset-password/verify?token=${encodeURIComponent(token.trim())}`, {
    method: "GET",
  });
  return res.ok ? { valid: true } : { valid: false, error: errorText(res, "Invalid or expired password reset link.") };
}

/** Set the new password with a valid reset token. */
export async function submitResetPassword(
  token: string,
  newPassword: string,
): Promise<{ success: boolean; message?: string; error?: string }> {
  const res = await callBackend("/api/v1/auth/reset-password", {
    body: { token: token.trim(), new_password: newPassword },
  });
  if (!res.ok) return { success: false, error: errorText(res, "Failed to reset password.") };
  return { success: true, message: res.data.message || "Password has been reset successfully." };
}

// ── Invitation setup ────────────────────────────────────────────────────

/** Check an invitation token before showing the account setup form. */
export async function verifyInvitationToken(token: string): Promise<{
  valid: boolean;
  email?: string;
  full_name?: string;
  role?: string;
  requires_mfa?: boolean;
  error?: string;
}> {
  const res = await callBackend(`/api/v1/auth/invitation/verify?token=${encodeURIComponent(token.trim())}`, {
    method: "GET",
  });
  if (!res.ok) return { valid: false, error: errorText(res, "Invalid or expired invitation token.") };
  return {
    valid: true,
    email: res.data.email,
    full_name: res.data.full_name,
    role: res.data.role,
    requires_mfa: res.data.requires_mfa,
  };
}

/** Accept the invitation and set the chosen password; staff roles then enrol TOTP. */
export async function acceptInvitation(
  token: string,
  password: string,
): Promise<{
  success: boolean;
  mfa_required: boolean;
  mfa_setup_token?: string;
  mfa_secret?: string;
  mfa_uri?: string;
  message?: string;
  error?: string;
}> {
  const res = await callBackend("/api/v1/auth/invitation/accept", { body: { token: token.trim(), password } });
  if (!res.ok) return { success: false, mfa_required: false, error: errorText(res, "Failed to set up account.") };
  return {
    success: true,
    mfa_required: Boolean(res.data.mfa_required),
    mfa_setup_token: res.data.mfa_setup_token,
    mfa_secret: res.data.mfa_secret,
    mfa_uri: res.data.mfa_uri,
    message: res.data.message,
  };
}

/** Complete TOTP enrolment; on success the httpOnly session cookie is set server-side. */
export async function verifyTotpSetup(mfaSetupToken: string, code: string): Promise<AuthApiResponse> {
  const res = await callBackend("/api/v1/auth/invitation/verify-totp", {
    body: { mfa_setup_token: mfaSetupToken, code: code.trim() },
  });
  if (!res.ok) {
    return { success: false, isOffline: res.status === 503, error: errorText(res, "Invalid authenticator code.") };
  }
  const token = res.data.access_token || res.data.token;
  if (token) await startSession(token, res.data.expires_in);
  return {
    success: true,
    user: {
      id: res.data.user?.id || res.data.user_id || "",
      name: res.data.user?.name || res.data.full_name || "Staff Member",
      email: res.data.user?.email || res.data.email || "",
      phone: res.data.user?.phone || "",
      role: res.data.user?.role || res.data.role || "DISASTER_MGMT",
      agency: "Disaster Management Authority",
    },
    message: "Account verified and activated successfully.",
  };
}

// ── Google sign-in (citizens only) ──────────────────────────────────────

/** Exchange a Google Identity Services credential for a citizen session. Staff accounts are refused. */
export async function backendGoogleLogin(
  credential: string,
): Promise<AuthApiResponse & { mfa_required?: boolean }> {
  const res = await callBackend("/api/v1/auth/google", { body: { credential }, timeoutMs: 15000 });
  if (!res.ok) {
    return { success: false, isOffline: res.status === 503, error: errorText(res, "Google authentication failed.") };
  }
  if (res.data.mfa_required) {
    // The MFA challenge token stays on the server; the user finishes on the password sign-in form.
    return {
      success: false,
      mfa_required: true,
      message: res.data.message || "Multi-factor authentication is required. Sign in with your password.",
    };
  }
  const token = res.data.access_token || res.data.token;
  if (!token) return { success: false, error: "Authentication response missing access token." };
  await startSession(token, res.data.expires_in);

  const isCitizen = (res.data.user?.role ?? res.data.role) === "NORMAL_USER";
  return {
    success: true,
    user: {
      id: res.data.user?.id || res.data.user_id || "",
      name: res.data.user?.name || res.data.full_name || "Citizen",
      email: res.data.user?.email || res.data.email || "",
      phone: res.data.user?.phone || "",
      role: isCitizen ? "Public / Citizen" : res.data.user?.role || "Public / Citizen",
      agency: isCitizen ? "Public Resident / Citizen" : "Disaster Response Staff",
    },
    message: res.data.message,
  };
}
