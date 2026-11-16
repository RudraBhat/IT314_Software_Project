import type { NextRequest } from "next/server";

import { API_URL, sessionToken } from "@/lib/session";

/**
 * Backend-for-frontend proxy for the administrator area (/api/v1/admin/...).
 *
 *   GET /api/admin/accounts   -> staff account directory (APP_MGMT with verified MFA)
 *
 * Read-only for now. The browser holds only the httpOnly session cookie; this handler attaches the
 * bearer token server-side and the backend decides who may call each route. Unknown paths are 404.
 */

const ALLOWED = [{ method: "GET", pattern: /^accounts$/ }];

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

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: { Authorization: `Bearer ${token}` },
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
