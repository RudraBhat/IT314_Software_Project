"use client";

import React, { useState, type ReactNode } from "react";
import Link from "next/link";
import { SiteHeader, NavLink, NavDivider, HeaderAccount, HEADER_CONTROL } from "../Brand";
import { signOut } from "@/app/login/actions";
import { useSession, type SessionInfo } from "@/components/auth/SessionProvider";
import { homeFor } from "@/lib/roles";
import { NotificationBell } from "@/components/citizen/NotificationBell";

export type { SessionInfo };

interface UnifiedSiteHeaderProps {
  activeHref?: string;
  badge?: ReactNode;
  children?: ReactNode;
  /** Normally omitted: the header reads the shared session. Pass one only to override it. */
  session?: SessionInfo | null;
}

const ROLE_LABEL: Record<string, string> = {
  NORMAL_USER: "Citizen",
  DISASTER_MGMT: "Disaster Management",
  FIELD_TEAM: "Field Team",
  APP_MGMT: "Administration",
};

/**
 * Unified global navigation bar for all public and citizen pages (Fixes #172).
 *
 * Links are grouped left to right: where you work (Map when signed out, Dashboard when signed in),
 * information pages (Safety, How to use, About), then actions (Donate, Report Incident), then the
 * account. The page you are on stays in place and is highlighted rather than hidden.
 *
 * The session comes from the root SessionProvider, so the signed-in name and Sign out button stay
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
  const signedIn = !!session?.authenticated;
  // Reporting is a citizen flow; staff and responders work from their own areas.
  const isStaff = signedIn && !!session?.role && session.role !== "NORMAL_USER";
  const home = signedIn ? homeFor(session?.role) : "/";
  const isActive = (href: string) => activeHref === href;

  async function handleSignOut() {
    shared.markSignedOut();
    setMenuOpen(false);
    await signOut();
  }

  const signInHref = activeHref && activeHref !== "/" ? `/login?next=${encodeURIComponent(activeHref)}` : "/login";

  // Signed-in people work from their dashboard (it has its own map), so the bar offers that instead of the public map.
  const workLink: [string, string] = signedIn ? [home, "Dashboard"] : ["/", "Map"];
  const infoLinks: [string, string][] = [
    ["/safety", "Safety"],
    ["/how-to", "How to use"],
    ["/about", "About"],
  ];
  const mobileLinks: [string, string][] = [
    signedIn ? workLink : ["/", "Live Map"],
    ...(isStaff ? [] : [["/report", "Report Incident"] as [string, string]]),
    ["/safety", "Safety Guidelines"],
    ["/how-to", "How to use"],
    ["/about", "About ResQ"],
    ["/donate", "Donate to Relief Fund"],
  ];

  return (
    <>
      <SiteHeader subtitle="Gujarat Emergency Portal" maxWidth="max-w-7xl" badge={badge} brandHref={home}>
        <nav aria-label="Main" className="flex min-w-0 items-center gap-2">
          <NavLink href={workLink[0]} hideBelow="sm" active={isActive(workLink[0])}>
            {workLink[1]}
          </NavLink>
          <NavDivider />
          {infoLinks.map(([href, label]) => (
            <NavLink key={href} href={href} hideBelow="lg" active={isActive(href)}>
              {label}
            </NavLink>
          ))}
          <NavDivider />
          <NavLink href="/donate" hideBelow="lg" variant="success" active={isActive("/donate")}>
            Donate
          </NavLink>
          {!isStaff && (
            <NavLink href="/report" variant="primary" active={isActive("/report")}>
              Report<span className="hidden sm:inline"> Incident</span>
            </NavLink>
          )}
        </nav>

        {/* Page-specific controls sit beside the account. */}
        {children}

        {/* Citizens keep their notification bell on every page, not only on the dashboard. */}
        {signedIn && session?.role === "NORMAL_USER" && <NotificationBell />}

        {loading ? (
          <span
            className="hidden h-9 w-40 animate-pulse rounded-lg bg-white/10 sm:inline-block"
            role="status"
            aria-label="Checking sign-in"
          />
        ) : signedIn ? (
          <div className="hidden border-l border-white/20 pl-3 sm:block">
            <HeaderAccount
              name={session?.name || "My Account"}
              detail={session?.email || ROLE_LABEL[session?.role ?? ""]}
              signOut={handleSignOut}
            />
          </div>
        ) : (
          <Link href={signInHref} className={`${HEADER_CONTROL} inline-flex bg-sky-500 font-bold text-slate-950 hover:bg-sky-400`}>
            Sign In
          </Link>
        )}

        <button
          onClick={() => setMenuOpen((v) => !v)}
          className={`${HEADER_CONTROL} inline-flex w-9 cursor-pointer justify-center bg-white/10 text-sm text-white hover:bg-white/20 lg:hidden`}
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
        >
          <span aria-hidden className="select-none">{menuOpen ? "✕" : "☰"}</span>
        </button>
      </SiteHeader>

      {menuOpen && (
        <nav
          className="sticky inset-x-0 top-14 z-[999] flex flex-col gap-1 border-b border-[#093554] bg-[#0c4a75] p-3 text-sm text-white shadow-xl lg:hidden"
          aria-label="Mobile Menu"
        >
          {signedIn && (
            <div className="mb-1 border-b border-white/15 px-3 pb-2">
              <p className="font-semibold">{session?.name || "My Account"}</p>
              <p className="text-xs text-sky-200/80">{session?.email || ROLE_LABEL[session?.role ?? ""]}</p>
            </div>
          )}
          {mobileLinks.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? "page" : undefined}
              className={`rounded-lg px-3 py-2 font-semibold hover:bg-white/10 ${isActive(href) ? "bg-white text-[#0c4a75] hover:bg-white" : ""}`}
              onClick={() => setMenuOpen(false)}
            >
              {label}
            </Link>
          ))}
          {signedIn ? (
            <button
              onClick={handleSignOut}
              className="cursor-pointer rounded-lg px-3 py-2 text-left font-semibold hover:bg-white/10"
            >
              Sign out
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
