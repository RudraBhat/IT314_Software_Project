import type { NextRequest } from "next/server";

import { API_URL, sessionToken } from "@/lib/session";

/**
 * Backend-for-frontend proxy for account invitations (/api/v1/auth/invitations[/...]).
 *
 *   GET    /api/invitations               -> list pending invitations the caller manages
 *   POST   /api/invitations               -> invite an account
 *   GET    /api/invitations/teams         -> teams a Field Team invitation can join
 *   POST   /api/invitations/{id}/resend   -> reissue the setup link
 *   DELETE /api/invitations/{id}          -> revoke a pending invitation
 *
 * Used by the DM staff page (supervisors) and the admin area (APP_MGMT). The browser holds only
 * the httpOnly session cookie; the backend decides who may invite which role.
 */

const ALLOWED = [
  { method: "GET", pattern: /^$/ },
  { method: "POST", pattern: /^$/ },
  { method: "GET", pattern: /^teams$/ },
  { method: "POST", pattern: /^[0-9a-f-]{36}\/resend$/i },
  { method: "DELETE", pattern: /^[0-9a-f-]{36}$/i },
];

function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

function error(status: number, code: string, message: string) {
  return Response.json({ error: { code, message, details: null } }, { status });
}

async function forward(request: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  if (request.method !== "GET" && !sameOrigin(request)) {
    return error(403, "CSRF_REJECTED", "Cross-site request rejected");
  }
  const { path = [] } = await ctx.params;
  const subpath = path.join("/");
  if (!ALLOWED.some((rule) => rule.method === request.method && rule.pattern.test(subpath))) {
    return error(404, "NOT_FOUND", "Unknown invitation endpoint");
  }

  const token = await sessionToken();
  if (!token) return error(401, "NOT_AUTHENTICATED", "Your session has ended. Sign in again.");

  const suffix = subpath ? `/${path.map(encodeURIComponent).join("/")}` : "";
  const headers = new Headers({ Authorization: `Bearer ${token}` });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/api/v1/auth/invitations${suffix}`, {
      method: request.method,
      headers,
      body: request.method === "POST" ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    return error(503, "BACKEND_UNAVAILABLE", "The account service is unreachable. Try again shortly.");
  }

  return new Response(upstream.status === 204 ? null : await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
