"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { API_URL, MFA_COOKIE, SESSION_COOKIE, cookieOptions } from "@/lib/session";

export type LoginState = { step: "password" | "mfa"; error?: string; email?: string };

type ApiError = { error?: { code?: string; message?: string } };

async function post(path: string, body: unknown, token?: string) {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 503, data: { error: { message: "The sign-in service is unreachable. Try again shortly." } } };
  }
}

function safeNext(value: FormDataEntryValue | null, role?: string): string {
  const next = typeof value === "string" ? value : "";
  // Only same-site workspace paths; never an absolute or protocol-relative URL.
  if (next.startsWith("/") && !next.startsWith("//")) {
    if (next.startsWith("/dm") && role === "NORMAL_USER") {
      return "/citizen/dashboard";
    }
    return next;
  }
  if (role === "NORMAL_USER") return "/citizen/dashboard";
  if (role === "FIELD_TEAM") return "/field";
  return "/dm";
}

async function signIn(form: FormData): Promise<LoginState> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!email || !password) return { step: "password", error: "Enter your email and password.", email };

  const res = await post("/api/v1/auth/login", { email, password });
  if (!res.ok) {
    return { step: "password", error: (res.data as ApiError).error?.message ?? "Sign-in failed.", email };
  }
  if (!res.data.mfa_required) {
    // Citizens authenticate without MFA (SRS s.15.3)
    const token = res.data.access_token || res.data.token;
    if (!token) {
      return { step: "password", error: "Authentication response missing access token.", email };
    }
    const expiresIn = Number(res.data.expires_in) || 86400;
    const jar = await cookies();
    jar.set(SESSION_COOKIE, token, cookieOptions(expiresIn));
    jar.set("drch_session", "1", cookieOptions(expiresIn));
    const role = res.data.role || res.data.user?.role || "NORMAL_USER";
    redirect(safeNext(form.get("next"), role));
  }
  (await cookies()).set(MFA_COOKIE, res.data.mfa_token, cookieOptions(300));
  return { step: "mfa", email };
}

async function verifyCode(prev: LoginState, form: FormData): Promise<LoginState> {
  const jar = await cookies();
  const mfaToken = jar.get(MFA_COOKIE)?.value;
  if (!mfaToken) return { step: "password", error: "The sign-in step expired. Start again." };
  const code = String(form.get("code") ?? "").replace(/\s/g, "");
  if (!/^\d{6}$/.test(code)) return { step: "mfa", error: "Enter the 6-digit code from your authenticator app.", email: prev.email };

  const res = await post("/api/v1/auth/mfa/verify", { mfa_token: mfaToken, code });
  if (!res.ok) {
    const err = (res.data as ApiError).error;
    const expired = err?.code === "MFA_CHALLENGE_INVALID" || err?.code === "INVALID_CREDENTIALS";
    if (expired) jar.delete(MFA_COOKIE);
    return { step: expired ? "password" : "mfa", error: err?.message ?? "Verification failed.", email: prev.email };
  }
  jar.delete(MFA_COOKIE);
  if (res.data.role !== "DISASTER_MGMT") {
    if (res.data.role === "NORMAL_USER") {
      const expiresIn = Number(res.data.expires_in) || 86400;
      jar.set(SESSION_COOKIE, res.data.access_token, cookieOptions(expiresIn));
      jar.set("drch_session", "1", cookieOptions(expiresIn));
      redirect(safeNext(form.get("next"), "NORMAL_USER"));
    }
    await post("/api/v1/auth/logout", {}, res.data.access_token);
    return { step: "password", error: "This workspace is for Disaster Management staff." };
  }
  jar.set(SESSION_COOKIE, res.data.access_token, cookieOptions(res.data.expires_in));
  jar.set("drch_session", "1", cookieOptions(res.data.expires_in));
  redirect(safeNext(form.get("next"), res.data.role));
}

/** One action drives both steps, so the form always shows the step the server decided. */
export async function authenticate(prev: LoginState, form: FormData): Promise<LoginState> {
  return form.get("intent") === "mfa" ? verifyCode(prev, form) : signIn(form);
}

export async function signOut() {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (token) await post("/api/v1/auth/logout", {}, token);
  jar.delete(SESSION_COOKIE);
  jar.delete("drch_session");
  redirect("/login");
}
