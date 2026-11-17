"use client";

import React, { useState, useEffect, type ReactNode } from "react";
import Link from "next/link";
import { SiteHeader, NavLink } from "../Brand";
import { signOut } from "@/app/login/actions";

export interface SessionInfo {
  authenticated: boolean;
  dm: boolean;
  citizen: boolean;
  role: string | null;
  name: string | null;
}

interface UnifiedSiteHeaderProps {
  activeHref?: string;
  badge?: ReactNode;
  children?: ReactNode;
  session?: SessionInfo | null;
}

/**
 * Unified global navigation bar for all public and citizen pages (Fixes #172).
 * Ensures uniform max-w-7xl container width, persistent link set,
 * consistent branding subtitle ('Gujarat Emergency Portal'), and identical mobile drawer.
 */
export function UnifiedSiteHeader({
  activeHref,
  badge,
  children,
  session: propSession,
}: UnifiedSiteHeaderProps) {
  const [fetchedSession, setFetchedSession] = useState<SessionInfo | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (propSession !== undefined) return;
    let isCancelled = false;
    fetch("/api/session", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!isCancelled && data) setFetchedSession(data);
      })
      .catch(() => {
        if (!isCancelled) {
          setFetchedSession({ authenticated: false, dm: false, citizen: false, role: null, name: null });
        }
      });
    return () => {
      isCancelled = true;
    };
  }, [propSession]);

  const session = propSession !== undefined ? propSession : fetchedSession;

  return (
    <>
      <SiteHeader subtitle="Gujarat Emergency Portal" maxWidth="max-w-7xl" badge={badge}>
        {/* Page-specific custom leading actions (e.g. Active Alerts button, refresh timers) */}
        {children}

        {/* Standard Unified Links Set */}
        <NavLink href="/" hideBelow={activeHref === "/" ? undefined : "sm"}>
          Map
        </NavLink>
        <NavLink href="/report" variant="primary">
          Report<span className="hidden sm:inline"> Incident</span>
        </NavLink>
        <NavLink href="/my-reports" hideBelow="lg">
          My Reports
        </NavLink>
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

        {/* Standard Auth / Profile Controls */}
        {session?.authenticated ? (
          <div className="hidden items-center gap-2 border-l border-sky-800 pl-2 sm:flex">
            <Link
              href="/dashboard"
              className="max-w-[120px] truncate text-xs font-semibold text-sky-200 underline hover:text-white"
            >
              {session.name || "My Account"}
            </Link>
            <button
              onClick={async () => {
                await signOut();
              }}
              className="rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-white/20 cursor-pointer"
            >
              Sign Out
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-bold text-slate-950 transition hover:bg-sky-400"
          >
            Sign In
          </Link>
        )}

        {/* Unified Mobile Hamburger Toggle */}
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="rounded-lg bg-white/10 px-2.5 py-1.5 text-sm text-white hover:bg-white/20 lg:hidden cursor-pointer"
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
        >
          {menuOpen ? "✕" : "☰"}
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
            ["/report", "Report Incident"],
            ["/my-reports", "My Reports"],
            ...(session?.authenticated ? [["/dashboard", "Dashboard"]] : []),
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
              onClick={async () => {
                await signOut();
              }}
              className="rounded-lg px-3 py-2 text-left font-semibold hover:bg-white/10 cursor-pointer"
            >
              Sign Out
            </button>
          ) : (
            <Link
              href="/login"
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
