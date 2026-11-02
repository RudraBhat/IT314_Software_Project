import type { NextRequest } from "next/server";

import { API_URL, sessionToken } from "@/lib/session";

/**
 * Backend-for-frontend proxy for /api/v1/field/*.
 *
 * The browser only ever holds an httpOnly session cookie; this handler
 * attaches the bearer token server-side. Authorization is still enforced by
 * the backend on every request - this layer adds no permissions of its own.
 */

const FORWARDED_HEADERS = ["content-type", "idempotency-key"];

function sameOrigin(request: NextRequest): boolean {
  // Cookie-authenticated writes must come from this site (CSRF defence alongside SameSite=Lax).
  // Compare against the host the request arrived on; behind a platform proxy that is X-Forwarded-Host.
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

async function forward(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  if (request.method !== "GET" && !sameOrigin(request)) {
    return error(403, "CSRF_REJECTED", "Cross-site request rejected");
  }
  const token = await sessionToken();
  if (!token) return error(401, "NOT_AUTHENTICATED", "Your session has ended. Sign in again.");

  const { path } = await ctx.params;
  const target = new URL(`${API_URL}/api/v1/field/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    return error(503, "BACKEND_UNAVAILABLE", "The field responder service is unreachable. Try again shortly.");
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
