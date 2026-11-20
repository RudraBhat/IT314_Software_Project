"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

/** What the browser may know about the signed-in person (from GET /api/session; no tokens). */
export interface SessionInfo {
  authenticated: boolean;
  dm?: boolean;
  citizen?: boolean;
  role: string | null;
  name: string | null;
  email?: string | null;
}

export const SIGNED_OUT: SessionInfo = { authenticated: false, dm: false, citizen: false, role: null, name: null, email: null };

type SessionState = {
  /** null until the first check answers. */
  session: SessionInfo | null;
  /** True only before the first answer; later checks run silently and keep showing the last value. */
  loading: boolean;
  /** Re-check now (for example after signing in). */
  refresh: () => void;
  /** Show the signed-out state at once, before the sign-out request finishes. */
  markSignedOut: () => void;
  /** Ask the provider to start checking; called by useSession(). */
  subscribe: () => void;
};

const SessionContext = createContext<SessionState | null>(null);

/**
 * One session check shared by every page under the root layout. The provider stays mounted across
 * client-side navigation, so the header keeps the signed-in name and Sign Out button instead of
 * re-fetching and flickering on each page. It re-checks quietly on every route change, which picks
 * up sign-in and sign-out redirects, and only starts once a component asks for the session.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [wanted, setWanted] = useState(false);
  const known = useRef<SessionInfo | null>(null);
  const requestId = useRef(0);

  const check = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const res = await fetch("/api/session", { cache: "no-store" });
      if (id !== requestId.current) return; // a newer check started; let it decide
      if (res.ok) {
        const data: SessionInfo = await res.json();
        known.current = data;
        setSession(data);
        return;
      }
      // 503 means "backend slow, try again": keep the last known state rather than signing the person out.
      if (!known.current) setSession(SIGNED_OUT);
    } catch {
      if (id === requestId.current && !known.current) setSession(SIGNED_OUT);
    }
  }, []);

  // Check once a component asks, then again quietly after every navigation.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- check() only sets state after the fetch resolves
    if (wanted) void check();
  }, [wanted, pathname, check]);

  const subscribe = useCallback(() => setWanted(true), []);

  const value = useMemo<SessionState>(
    () => ({
      session,
      loading: session === null,
      refresh: () => void check(),
      markSignedOut: () => {
        requestId.current++; // drop any check still in flight
        known.current = SIGNED_OUT;
        setSession(SIGNED_OUT);
      },
      subscribe,
    }),
    [session, check, subscribe],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** The shared session; any component can read it without starting its own request. */
export function useSession(): Omit<SessionState, "subscribe"> {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider> (the root layout provides it)");
  const { subscribe, ...rest } = ctx;
  useEffect(() => subscribe(), [subscribe]);
  return rest;
}
