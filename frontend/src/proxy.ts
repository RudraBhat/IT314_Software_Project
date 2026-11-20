import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { API_URL, REFRESH_COOKIE, SESSION_COOKIE, cookieOptions, setSessionCookies } from "@/lib/session";

type Refreshed = { kind: "ok"; tokens: Record<string, unknown> } | { kind: "ended" } | { kind: "unavailable" };

/** Trade the refresh cookie for new tokens. "ended" means the backend refused it for good. */
async function refresh(refreshToken: string): Promise<Refreshed> {
  try {
    const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (res.ok) return { kind: "ok", tokens: await res.json() };
    return res.status === 401 ? { kind: "ended" } : { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}

/**
 * Keeps a signed-in user signed in. The access cookie is short-lived; when it has lapsed but the
 * refresh cookie is still valid this swaps in new cookies before the page or API route runs, so the
 * request carries a fresh token. The session ends only at the idle or absolute limit set by the
 * backend. Visitors with no session at all are sent to /login (optimistic redirect only: real
 * authorisation happens in the /dm layout via /api/v1/me and in the backend).
 */
export async function proxy(request: NextRequest) {
  const isApi = request.nextUrl.pathname.startsWith("/api/");
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  const pending: { name: string; value: string; options: ReturnType<typeof cookieOptions> }[] = [];
  let sessionEnded = false;

  if (!request.cookies.has(SESSION_COOKIE) && refreshToken) {
    const result = await refresh(refreshToken);
    if (result.kind === "ok") {
      setSessionCookies(
        { set: (name, value, options) => void pending.push({ name, value, options }) },
        result.tokens,
      );
      for (const { name, value } of pending) request.cookies.set(name, value);
    } else if (result.kind === "ended") {
      sessionEnded = true;
    }
  }

  const signedIn = request.cookies.has(SESSION_COOKIE);
  const response =
    signedIn || isApi
      ? NextResponse.next({ request })
      : NextResponse.redirect(loginUrl(request));

  for (const { name, value, options } of pending) response.cookies.set(name, value, options);
  if (sessionEnded) {
    response.cookies.delete(REFRESH_COOKIE);
    response.cookies.delete("drch_session");
  }
  return response;
}

function loginUrl(request: NextRequest): URL {
  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname);
  return login;
}

export const config = {
  matcher: [
    "/admin/:path*", "/admin", "/dm/:path*", "/dm", "/field/:path*", "/field", "/citizen/:path*", "/report/:path*",
    "/report", "/my-reports/:path*", "/my-reports", "/account/:path*", "/account", "/dashboard",
    // Server-side proxies and the session probe: refreshed here, never redirected.
    "/api/dm/:path*", "/api/field/:path*", "/api/citizen/:path*", "/api/invitations/:path*", "/api/session",
  ],
};
