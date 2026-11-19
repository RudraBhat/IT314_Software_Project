import { API_URL } from "./config";

export { API_URL };
export const MFA_COOKIE = "mfa_token";
export const SESSION_COOKIE = "session_token";
export const REFRESH_COOKIE = "refresh_token";

export function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

/** Sign-in or refresh response fields that start or extend a session. */
export type SessionTokens = {
  access_token?: unknown;
  expires_in?: unknown;
  refresh_token?: unknown;
  refresh_expires_in?: unknown;
};

type CookieWriter = { set(name: string, value: string, options: ReturnType<typeof cookieOptions>): unknown };

// The access cookie lapses a little before the token does, so a request never carries a token
// the backend is about to refuse; the proxy refreshes it first.
const ACCESS_COOKIE_MARGIN_SECONDS = 30;

/** Write the access, session-marker and refresh cookies from a sign-in or refresh response. */
export function setSessionCookies(jar: CookieWriter, data: SessionTokens): void {
  const expiresIn = Number(data.expires_in) || 900;
  const accessAge = Math.max(expiresIn - ACCESS_COOKIE_MARGIN_SECONDS, 1);
  const refreshAge = Number(data.refresh_expires_in) || 0;
  jar.set(SESSION_COOKIE, String(data.access_token), cookieOptions(accessAge));
  // Outlives the access cookie, so the marker alone does not mean the access token is still valid.
  jar.set("drch_session", "1", cookieOptions(refreshAge || accessAge));
  if (typeof data.refresh_token === "string" && refreshAge > 0) {
    jar.set(REFRESH_COOKIE, data.refresh_token, cookieOptions(refreshAge));
  }
}

export { homeFor } from "./roles";

export type CurrentUser = {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  permissions: string[];
  mfa_verified: boolean;
};

function isCurrentUser(value: unknown): value is CurrentUser {
  if (typeof value !== "object" || value === null) return false;

  const user = value as Record<string, unknown>;
  return (
    typeof user.user_id === "string" &&
    typeof user.email === "string" &&
    typeof user.full_name === "string" &&
    typeof user.role === "string" &&
    Array.isArray(user.permissions) &&
    user.permissions.every((permission) => typeof permission === "string") &&
    typeof user.mfa_verified === "boolean"
  );
}

export async function sessionToken(): Promise<string | null> {
  const { cookies } = await import("next/headers");
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

/** The backend could not be asked (slow, down or erroring). That is not the same as being signed out. */
export class SessionUnavailableError extends Error {
  constructor() {
    super("The sign-in service did not answer. Try again in a moment.");
    this.name = "SessionUnavailableError";
  }
}

// A slow database must not look like a sign-out, so wait longer and retry once before giving up.
const ME_TIMEOUT_MS = 15000;
const ME_ATTEMPTS = 2;

function fetchMe(path: string, token: string): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
    signal: AbortSignal.timeout(ME_TIMEOUT_MS),
  });
}

/**
 * The signed-in user, or null when there is no session or the backend refused the token (401/403).
 * Throws SessionUnavailableError when the backend could not be reached or kept erroring, so a slow
 * moment never sends a signed-in person to the login page.
 */
export async function currentUser(): Promise<CurrentUser | null> {
  const token = await sessionToken();
  if (!token) return null;

  let response: Response | null = null;
  for (let attempt = 0; attempt < ME_ATTEMPTS; attempt++) {
    try {
      response = await fetchMe("/api/v1/auth/me", token);
      if (response.status === 404) response = await fetchMe("/api/v1/me", token);
      if (response.status < 500) break;
    } catch {
      response = null;
    }
  }
  if (response === null || response.status >= 500) throw new SessionUnavailableError();
  if (!response.ok) return null;

  const user: unknown = await response.json().catch(() => null);
  return isCurrentUser(user) ? user : null;
}
