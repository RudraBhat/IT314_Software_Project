import type { NextRequest } from "next/server";

import { API_URL, sessionToken } from "@/lib/session";

/**
 * Backend-for-frontend proxy for /api/v1/dm/*.
 *
 * The browser only ever holds an httpOnly session cookie; this handler
 * attaches the bearer token server-side. Authorization is still enforced by
 * the backend on every request - this layer adds no permissions of its own.
 */

const FORWARDED_HEADERS = ["content-type", "idempotency-key", "x-filename"];

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

async function forward(request: NextRequest, ctx: RouteContext<"/api/dm/[...path]">) {
  if (request.method !== "GET" && !sameOrigin(request)) {
    return error(403, "CSRF_REJECTED", "Cross-site request rejected");
  }
  const token = await sessionToken();
  if (!token) return error(401, "NOT_AUTHENTICATED", "Your session has ended. Sign in again.");

  const { path } = await ctx.params;
  const target = new URL(`${API_URL}/api/v1/dm/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  let upstream: Response;
  try {
    // JSON and form text pass as text; everything else (photos, multipart) must stay binary or it is corrupted.
    const contentType = request.headers.get("content-type") ?? "";
    const isText = contentType === "" || contentType.includes("json") || contentType.startsWith("text/");
    const body = ["GET", "HEAD"].includes(request.method)
      ? undefined
      : isText
        ? await request.text()
        : await request.arrayBuffer();
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
    });
  } catch {
    return error(503, "BACKEND_UNAVAILABLE", "The operations service is unreachable. Try again shortly.");
  }

  // Bytes, not text: evidence photos for moderators are binary and must pass through unchanged.
  const responseHeaders: Record<string, string> = {
    "content-type": upstream.headers.get("content-type") ?? "application/json",
  };
  // content-disposition and x-export-truncated let a CSV export keep its file name and report a cut-off.
  for (const name of ["x-content-type-options", "cache-control", "content-security-policy", "content-disposition", "x-export-truncated"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders[name] = value;
  }
  const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
  return new Response(body, { status: upstream.status, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
