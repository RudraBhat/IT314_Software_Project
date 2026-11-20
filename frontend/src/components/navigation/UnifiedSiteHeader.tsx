"use client";

import React, { useState, type ReactNode } from "react";
import Link from "next/link";
import { SiteHeader, NavLink, HEADER_CONTROL } from "../Brand";
import { signOut } from "@/app/login/actions";
import { useSession, type SessionInfo } from "@/components/auth/SessionProvider";

export type { SessionInfo };

interface UnifiedSiteHeaderProps {
  activeHref?: string;
  badge?: ReactNode;
  children?: ReactNode;
  /** Normally omitted: the header reads the shared session. Pass one only to override it. */
  session?: SessionInfo | null;
}

/**
 * Unified global navigation bar for all public and citizen pages (Fixes #172).
 * Ensures uniform max-w-7xl container width, persistent link set,
 * consistent branding subtitle ('Gujarat Emergency Portal'), and identical mobile drawer.
 *
 * The session comes from the root SessionProvider, so the signed-in name and Sign Out button stay
 * in place when moving between pages. Before the very first check answers, a fixed-width placeholder
 * holds their space so nothing jumps.
 */
export function UnifiedSiteHeader({
  activeHref,
  badge,
  children,
  session: propSession,
}: UnifiedSiteHeaderProps) {
  const shared = useSession();
  const [menuOpen, setMenuOpen] = useState(false);

  const session = propSession !== undefined ? propSession : shared.session;
  const loading = propSession === undefined && shared.loading;
  // Reporting and My Reports are citizen flows; staff and responders work from their own areas.
  const isStaff = !!session?.authenticated && !!session.role && session.role !== "NORMAL_USER";

  async function handleSignOut() {
    shared.markSignedOut();
    setMenuOpen(false);
    await signOut();
  }

  const signInHref = activeHref && activeHref !== "/" ? `/login?next=${encodeURIComponent(activeHref)}` : "/login";

  return (
    <>
      <SiteHeader subtitle="Gujarat Emergency Portal" maxWidth="max-w-7xl" badge={badge}>
        {/* Page-specific custom leading actions (e.g. Active Alerts button, refresh timers) */}
        {children}

        {/* Standard Unified Links Set */}
        <NavLink href="/" hideBelow={activeHref === "/" ? undefined : "sm"}>
          Map
        </NavLink>
        {!isStaff && (
          <NavLink href="/report" variant="primary">
            Report<span className="hidden sm:inline"> Incident</span>
          </NavLink>
        )}
        {session?.authenticated && (
          <NavLink href="/dashboard" hideBelow="lg">
            Dashboard
          </NavLink>
        )}
        {!isStaff && (
          <NavLink href="/my-reports" hideBelow="lg">
            My Reports
          </NavLink>
        )}
        <NavLink href="/safety" hideBelow="lg">
          Safety
        </NavLink>
        <NavLink href="/how-to" hideBelow="lg">
          How to use
        </NavLink>
        <NavLink href="/about" hideBelow="lg">
          About
        </NavLink>
        <NavLink href="/donate" hideBelow="lg" variant="success">
          Donate
        </NavLink>

        {/* Desktop Auth / Profile Controls with Return Redirect */}
        {loading ? (
          <span
            className="hidden h-9 w-40 animate-pulse rounded-lg bg-white/10 sm:inline-block"
            role="status"
            aria-label="Checking sign-in"
          />
        ) : session?.authenticated ? (
          <div className="hidden items-center gap-2 border-l border-sky-800 pl-2 sm:flex">
            <Link
              href="/dashboard"
              className={`${HEADER_CONTROL} inline-flex max-w-[140px] truncate text-sky-200 underline hover:text-white`}
            >
              {session.name || "My Account"}
            </Link>
            <button
              onClick={handleSignOut}
              className={`${HEADER_CONTROL} inline-flex cursor-pointer bg-white/10 text-white hover:bg-white/20`}
            >
              Sign Out
            </button>
          </div>
        ) : (
          <Link href={signInHref} className={`${HEADER_CONTROL} inline-flex bg-sky-500 font-bold text-slate-950 hover:bg-sky-400`}>
            Sign In
          </Link>
        )}

        {/* Unified Mobile Hamburger Toggle */}
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className={`${HEADER_CONTROL} inline-flex w-9 cursor-pointer justify-center bg-white/10 text-sm text-white hover:bg-white/20 lg:hidden`}
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
        >
          <span aria-hidden className="select-none">{menuOpen ? "✕" : "☰"}</span>
        </button>
      </SiteHeader>

      {/* Unified Mobile Drawer (Same complete link set on every page) */}
      {menuOpen && (
        <nav
          className="sticky inset-x-0 top-14 z-[999] flex flex-col gap-1 border-b border-[#093554] bg-[#0c4a75] p-3 text-sm text-white shadow-xl lg:hidden"
          aria-label="Mobile Menu"
        >
          {[
            ["/", "Live Map"],
            ...(isStaff ? [] : [["/report", "Report Incident"]]),
            ...(session?.authenticated ? [["/dashboard", "Dashboard"]] : []),
            ...(isStaff ? [] : [["/my-reports", "My Reports"]]),
            ["/safety", "Safety Guidelines"],
            ["/how-to", "How to use"],
            ["/about", "About ResQ"],
            ["/donate", "Donate to Relief Fund"],
          ].map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={`rounded-lg px-3 py-2 font-semibold hover:bg-white/10 ${
                activeHref === href ? "bg-white/20 text-sky-200" : ""
              }`}
              onClick={() => setMenuOpen(false)}
            >
              {label}
            </Link>
          ))}
          {session?.authenticated ? (
            <button
              onClick={handleSignOut}
              className="rounded-lg px-3 py-2 text-left font-semibold hover:bg-white/10 cursor-pointer"
            >
              Sign Out
            </button>
          ) : (
            <Link
              href={signInHref}
              className="rounded-lg px-3 py-2 font-semibold hover:bg-white/10"
              onClick={() => setMenuOpen(false)}
            >
              Sign In
            </Link>
          )}
        </nav>
      )}
    </>
  );
}
