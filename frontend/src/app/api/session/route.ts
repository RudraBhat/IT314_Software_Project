import { cookies } from "next/headers";
import { API_URL, currentUser, cookieOptions, SESSION_COOKIE } from "@/lib/session";

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/**
 * Session verification & cookie establishment endpoint.
 *
 * GET: Returns whether the browser holds a valid staff or citizen session.
 * POST: Allows authenticated client flows to set the httpOnly session cookie.
 * DELETE: Clears the session cookies for logout.
 */
export async function GET() {
  const user = await currentUser();
  const dm = user !== null && user.role === "DISASTER_MGMT" && user.mfa_verified;
  const citizen = user !== null && user.role === "NORMAL_USER";
  return Response.json(
    {
      authenticated: user !== null,
      dm,
      citizen,
      role: user?.role ?? null,
      name: user ? user.full_name : null,
    },
    { headers: { "cache-control": "no-store" } }
  );
}

export async function POST(request: Request) {
  if (!sameOrigin(request)) {
    return Response.json({ error: { code: "CSRF_REJECTED", message: "Cross-site request rejected" } }, { status: 403 });
  }
  try {
    const body = await request.json().catch(() => ({}));
    const token = body?.token;
    if (!token || typeof token !== "string") {
      return Response.json(
        { error: { code: "INVALID_TOKEN", message: "Token is required" } },
        { status: 400 }
      );
    }

    // Only accept a token the backend recognises.
    const check = await fetch(`${API_URL}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    }).catch(() => null);
    if (!check || !check.ok) {
      return Response.json({ error: { code: "INVALID_TOKEN", message: "Token was not accepted" } }, { status: 401 });
    }

    const expiresIn = Number(body?.expiresIn) || 86400;
    const jar = await cookies();
    jar.set(SESSION_COOKIE, token, cookieOptions(expiresIn));
    jar.set("drch_session", "1", cookieOptions(expiresIn));

    return Response.json({ ok: true });
  } catch {
    return Response.json(
      { error: { code: "SESSION_ERROR", message: "Failed to establish session" } },
      { status: 500 }
    );
  }
}

export async function DELETE(request: Request) {
  if (!sameOrigin(request)) {
    return Response.json({ error: { code: "CSRF_REJECTED", message: "Cross-site request rejected" } }, { status: 403 });
  }
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  jar.delete("drch_session");
  return Response.json({ ok: true });
}
