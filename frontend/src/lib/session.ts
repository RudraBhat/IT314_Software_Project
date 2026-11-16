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

export async function currentUser(): Promise<CurrentUser | null> {
  const token = await sessionToken();
  if (!token) return null;

  try {
    let response = await fetch(`${API_URL}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });

    if (response.status === 404) {
      response = await fetch(`${API_URL}/api/v1/me`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
    }

    if (!response.ok) return null;

    const user: unknown = await response.json();
    return isCurrentUser(user) ? user : null;
  } catch {
    return null;
  }
}
