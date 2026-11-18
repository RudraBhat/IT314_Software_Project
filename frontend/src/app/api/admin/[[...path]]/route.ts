import type { NextRequest } from "next/server";

import { API_URL, sessionToken } from "@/lib/session";

/**
 * Backend-for-frontend proxy for the administrator area (/api/v1/admin/...).
 *
 *   GET  /api/admin/accounts                     -> staff account directory (APP_MGMT with verified MFA)
 *   GET  /api/admin/accounts/export              -> the filtered directory as a CSV download (audited)
 *   POST /api/admin/accounts/{id}/disable|enable -> switch an account off or on, with a reason
 *   POST /api/admin/accounts/{id}/reset-credentials -> clear a person's password and authenticator, email a setup link
 *   POST /api/admin/accounts/{id}/sign-out       -> end every session of an account without disabling it
 *   PUT  /api/admin/accounts/{id}/profile        -> correct a staff member's name or designation, with a reason
 *   PUT  /api/admin/accounts/{id}/permissions  -> replace a Disaster Management account's permissions, with a reason
 *   GET  /api/admin/system                       -> platform health: database, email, authenticator key, invitations
 *   GET  /api/admin/audit                      -> account and security audit entries
 *   POST /api/admin/audit/verify                 -> check the audit hash chain for tampering
 *
 * The browser holds only the httpOnly session cookie; this handler attaches the
 * bearer token server-side and the backend decides who may call each route. Unknown paths are 404.
 */

const ALLOWED = [
  { method: "GET", pattern: /^accounts$/ },
  { method: "GET", pattern: /^accounts\/export$/ },
  { method: "POST", pattern: /^accounts\/[0-9a-f-]{36}\/(disable|enable|reset-credentials|sign-out)$/i },
  { method: "PUT", pattern: /^accounts\/[0-9a-f-]{36}\/(permissions|profile)$/i },
  { method: "GET", pattern: /^system$/ },
  { method: "GET", pattern: /^audit$/ },
  { method: "POST", pattern: /^audit\/verify$/ },
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
    return error(404, "NOT_FOUND", "Unknown administration endpoint");
  }

  const token = await sessionToken();
  if (!token) return error(401, "NOT_AUTHENTICATED", "Your session has ended. Sign in again.");

  const target = new URL(`${API_URL}/api/v1/admin/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "POST" || request.method === "PUT" ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    return error(503, "BACKEND_UNAVAILABLE", "The administration service is unreachable. Try again shortly.");
  }

  return new Response(upstream.status === 204 ? null : await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
