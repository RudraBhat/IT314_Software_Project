import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Optimistic redirect only: send visitors without a session cookie to /login.
 * Real authorisation happens in the /dm layout (via /api/v1/me) and in the backend.
 */
export function proxy(request: NextRequest) {
  if (!request.cookies.has(SESSION_COOKIE) && !request.cookies.has("drch_session")) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dm/:path*", "/report/:path*", "/report", "/my-reports/:path*", "/my-reports"],
};
