"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { API_URL, MFA_COOKIE, REFRESH_COOKIE, SESSION_COOKIE, cookieOptions, homeFor, setSessionCookies } from "@/lib/session";

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
      // Sign-in is several database round trips, which can take a few seconds on a remote database.
      signal: AbortSignal.timeout(20000),
    });
    const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 503, data: { error: { message: "The sign-in service is unreachable. Try again shortly." } } };
  }
}

// Workspaces a role may be sent back to after signing in. Anything else would only bounce.
const ROLE_AREAS: Record<string, string[]> = {
  DISASTER_MGMT: ["/dm"],
  APP_MGMT: ["/admin"],
  FIELD_TEAM: ["/field"],
};
const STAFF_AREAS = ["/dm", "/admin", "/field"];

function inArea(path: string, area: string): boolean {
  return path === area || path.startsWith(`${area}/`) || path.startsWith(`${area}?`);
}

function safeNext(value: FormDataEntryValue | null, role?: string): string {
  const next = typeof value === "string" ? value : "";
  // Only same-site paths; never an absolute or protocol-relative URL. No path (or just the public map)
  // means "take me to my own home", so a citizen lands on their dashboard after signing in.
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\") || next === "/") return homeFor(role);
  // Staff roles only return to their own workspace.
  const allowed = ROLE_AREAS[role ?? ""];
  if (allowed) return allowed.some((area) => inArea(next, area)) ? next : homeFor(role);
  // Citizens never land in a staff area.
  if (STAFF_AREAS.some((area) => inArea(next, area))) return homeFor(role);
  return next;
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
    setSessionCookies(await cookies(), { ...res.data, access_token: token });
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
  if (res.data.role === "DISASTER_MGMT" || res.data.role === "FIELD_TEAM" || res.data.role === "APP_MGMT") {
    setSessionCookies(jar, res.data);
    redirect(safeNext(form.get("next"), res.data.role));
  }
  if (res.data.role === "NORMAL_USER") {
    setSessionCookies(jar, res.data);
    redirect(safeNext(form.get("next"), "NORMAL_USER"));
  }
  await post("/api/v1/auth/logout", {}, res.data.access_token);
  return { step: "password", error: "This account type cannot sign in here." };
}

/** One action drives both steps, so the form always shows the step the server decided. */
export async function authenticate(prev: LoginState, form: FormData): Promise<LoginState> {
  return form.get("intent") === "mfa" ? verifyCode(prev, form) : signIn(form);
}

export async function register(_prev: { error?: string }, form: FormData): Promise<{ error?: string }> {
  const res = await post("/api/v1/auth/register", {
    email: String(form.get("email") ?? "").trim(),
    password: String(form.get("password") ?? ""),
    full_name: String(form.get("full_name") ?? "").trim(),
    phone: String(form.get("phone") ?? "").trim() || null,
  });
  if (!res.ok) return { error: (res.data as ApiError).error?.message ?? "Registration failed." };
  const jar = await cookies();
  setSessionCookies(jar, res.data);
  redirect("/citizen/dashboard");
}

export async function signOut() {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (token) await post("/api/v1/auth/logout", {}, token);
  jar.delete(SESSION_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.delete("drch_session");
  // signed_out marks a deliberate sign-out (Google sign-in never starts on its own).
  redirect("/login?signed_out=1");
}
