import { API_URL } from "./config";

export { API_URL };
export const MFA_COOKIE = "mfa_token";
export const SESSION_COOKIE = "session_token";

export function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
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
