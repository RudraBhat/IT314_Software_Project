import type { NextRequest } from "next/server";

import { API_URL, sessionToken } from "@/lib/session";

/**
 * Backend-for-frontend proxy for citizen endpoints (/api/citizen/*).
 *
 *   /api/citizen/incidents[/...]   -> /api/v1/incidents[/...]
 *   /api/citizen/me/...            -> /api/v1/me/...
 *   /api/citizen/donations[/...]   -> /api/v1/donations[/...]   (guests may donate without a session)
 *
 * The browser only holds an httpOnly session cookie; this handler attaches the bearer token
 * server-side. The backend verifies the token and the role - this layer trusts nothing and sends
 * no identity headers. Unknown paths are 404, not forwarded.
 */

const FORWARDED_HEADERS = ["content-type", "idempotency-key", "x-filename"];
const ALLOWED_ROOTS = new Set(["incidents", "me", "donations"]);

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

type RouteContext = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, ctx: RouteContext) {
  if (request.method !== "GET" && request.method !== "HEAD" && !sameOrigin(request)) {
    return error(403, "CSRF_REJECTED", "Cross-site request rejected");
  }
  const { path } = await ctx.params;
  const root = path[0];
  if (!ALLOWED_ROOTS.has(root)) return error(404, "NOT_FOUND", "Unknown citizen endpoint");

  const token = await sessionToken();
  if (!token && root !== "donations") return error(401, "NOT_AUTHENTICATED", "Your session has ended. Sign in again.");

  const target = new URL(`${API_URL}/api/v1/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    // JSON passes as text; evidence photos must stay binary or they are corrupted.
    const contentType = request.headers.get("content-type") ?? "";
    const isText = contentType === "" || contentType.includes("json") || contentType.startsWith("text/");
    const body = ["GET", "HEAD"].includes(request.method)
      ? undefined
      : isText
        ? await request.text()
        : await request.arrayBuffer();
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
    // Bytes, not text: photo attachments are binary and must pass through unchanged.
    const responseHeaders: Record<string, string> = {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    };
    for (const name of ["x-content-type-options", "cache-control"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders[name] = value;
    }
    return new Response(upstream.status === 204 ? null : await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return error(503, "BACKEND_UNAVAILABLE", "The citizen service is unreachable. Try again shortly.");
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
