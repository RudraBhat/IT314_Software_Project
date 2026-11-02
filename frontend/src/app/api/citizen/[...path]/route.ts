import type { NextRequest } from "next/server";

import { API_URL, sessionToken } from "@/lib/session";

/**
 * Backend-for-frontend proxy for citizen endpoints (/api/citizen/*).
 *
 * Security:
 * - The browser only holds an httpOnly session cookie (drch_session / session_token).
 * - This handler attaches the verified bearer token server-side.
 * - Rejects cross-site writes (CSRF protection alongside SameSite=Lax).
 * - No client identity header (X-User-Id / X-User-Role) is trusted from the browser.
 */

const FORWARDED_HEADERS = ["content-type", "idempotency-key", "x-idempotency-key"];

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

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

async function forward(request: NextRequest, ctx: RouteContext) {
  if (request.method !== "GET" && request.method !== "HEAD" && !sameOrigin(request)) {
    return error(403, "CSRF_REJECTED", "Cross-site request rejected");
  }
  const token = await sessionToken();
  if (!token) return error(401, "NOT_AUTHENTICATED", "Your session has ended. Sign in again.");

  const { path } = await ctx.params;
  const pathSegments = path.map(encodeURIComponent);

  let targetUrl: string;
  if (pathSegments[0] === "incidents") {
    targetUrl = `${API_URL}/api/v1/incidents${pathSegments.length > 1 ? "/" + pathSegments.slice(1).join("/") : ""}`;
  } else if (pathSegments[0] === "me") {
    targetUrl = `${API_URL}/api/v1/me${pathSegments.length > 1 ? "/" + pathSegments.slice(1).join("/") : ""}`;
  } else if (pathSegments[0] === "reports") {
    targetUrl = `${API_URL}/api/citizen/reports${pathSegments.length > 1 ? "/" + pathSegments.slice(1).join("/") : ""}`;
  } else {
    targetUrl = `${API_URL}/api/v1/citizen/${pathSegments.join("/")}`;
  }

  const target = new URL(targetUrl);
  target.search = request.nextUrl.search;

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  // Server-side fallback identity for legacy SQLite stand-in during transition
  try {
    const parts = token.split(".");
    if (parts.length === 3) {
      const payload = JSON.parse(Buffer.from(parts[1], "base64").toString("utf-8"));
      if (payload.sub) {
        headers.set("X-User-Id", payload.sub);
        headers.set("X-User-Role", payload.role || "NORMAL_USER");
      }
    }
  } catch {
    // Ignore payload decode errors
  }

  const bodyText = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: bodyText,
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });

    // Fallback if /api/v1/incidents or /api/v1/me is not yet online
    if (upstream.status === 404 && (pathSegments[0] === "incidents" || pathSegments[0] === "me")) {
      let fallbackUrl: string | null = null;
      if (pathSegments[0] === "incidents") {
        fallbackUrl = `${API_URL}/api/citizen/reports`;
      } else if (pathSegments[0] === "me" && pathSegments[1] === "incidents") {
        fallbackUrl = `${API_URL}/api/citizen/reports${pathSegments.length > 2 ? "/" + pathSegments.slice(2).join("/") : ""}`;
      }
      if (fallbackUrl) {
        const fallbackTarget = new URL(fallbackUrl);
        fallbackTarget.search = request.nextUrl.search;
        upstream = await fetch(fallbackTarget, {
          method: request.method,
          headers,
          body: bodyText,
          cache: "no-store",
          signal: AbortSignal.timeout(20000),
        });
      }
    }
  } catch {
    return error(503, "BACKEND_UNAVAILABLE", "The citizen service is unreachable. Try again shortly.");
  }

  const body = upstream.status === 204 ? null : await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
