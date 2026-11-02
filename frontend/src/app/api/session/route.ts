import { cookies } from "next/headers";
import { currentUser, cookieOptions, SESSION_COOKIE } from "@/lib/session";

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
  try {
    const body = await request.json().catch(() => ({}));
    const token = body?.token;
    if (!token || typeof token !== "string") {
      return Response.json(
        { error: { code: "INVALID_TOKEN", message: "Token is required" } },
        { status: 400 }
      );
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

export async function DELETE() {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  jar.delete("drch_session");
  return Response.json({ ok: true });
}
