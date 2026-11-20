"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useState, type ReactNode } from "react";

import { HeaderAccount, SiteHeader } from "@/components/Brand";
import { AlertsDrawer } from "@/components/dm/AlertsDrawer";
import { HeaderRoleMenu } from "@/components/staff/PermissionChips";
import { ToastProvider, cx } from "@/components/ui";

export type StaffUser = { name: string; email: string; permissions: string[] };

const UserContext = createContext<StaffUser>({ name: "", email: "", permissions: [] });

/** Permission hints for the UI only; the backend enforces every permission itself. */
export function useStaff() {
  const user = useContext(UserContext);
  return { ...user, can: (permission: string) => user.permissions.includes(permission) };
}

type NavItem = { href: string; label: string; icon: string; permission?: string | string[] };

/**
 * Sidebar sections, each with its own colour so related pages are easy to find at a glance. Class names
 * are written out in full so Tailwind keeps them.
 */
const SECTIONS: { title: string; chip: string; active: string; items: NavItem[] }[] = [
  {
    title: "Operations",
    chip: "bg-sky-100 text-sky-700",
    active: "bg-sky-50 text-sky-800 ring-sky-200",
    items: [
      { href: "/dm", label: "Dashboard", icon: "▦" },
      { href: "/dm/live-map", label: "Live map", icon: "◎" },
      { href: "/dm/incidents", label: "Incidents", icon: "⚑" },
      { href: "/dm/signals", label: "Signals", icon: "⚡" },
      { href: "/dm/ingestion", label: "Ingestion health", icon: "◷", permission: ["DISPATCH", "SUPERVISOR"] },
    ],
  },
  {
    title: "Response",
    chip: "bg-orange-100 text-orange-700",
    active: "bg-orange-50 text-orange-800 ring-orange-200",
    items: [
      { href: "/dm/dispatches", label: "Dispatches", icon: "➜" },
      { href: "/dm/team-requests", label: "Team requests", icon: "✚" },
      { href: "/dm/resources", label: "Resources", icon: "▣" },
      { href: "/dm/agencies", label: "Agencies", icon: "☎" },
      { href: "/dm/shelters", label: "Shelters", icon: "⌂", permission: ["DISPATCH", "SUPERVISOR"] },
      { href: "/dm/aid", label: "Aid & needs", icon: "◆" },
    ],
  },
  {
    title: "Public",
    chip: "bg-emerald-100 text-emerald-700",
    active: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    items: [
      { href: "/dm/updates", label: "Public updates", icon: "✎" },
      { href: "/dm/content", label: "Safety content", icon: "☰" },
      { href: "/dm/moderation", label: "Moderation", icon: "◐", permission: "MODERATOR" },
      { href: "/dm/campaigns", label: "Campaigns", icon: "₹" },
    ],
  },
  {
    title: "Insights & team",
    chip: "bg-violet-100 text-violet-700",
    active: "bg-violet-50 text-violet-800 ring-violet-200",
    items: [
      { href: "/dm/analytics", label: "Analytics", icon: "▤" },
      { href: "/dm/staff", label: "Staff accounts", icon: "👥", permission: "SUPERVISOR" },
    ],
  },
];

/** Pages that fill the whole workspace pane (no page padding), such as the live map. */
const FULL_BLEED = ["/dm/live-map"];

export function DmShell({ user, signOut, children }: { user: StaffUser; signOut: () => Promise<void>; children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const isActive = (href: string) => (href === "/dm" ? pathname === href : pathname.startsWith(href));
  const allowed = (n: NavItem) =>
    !n.permission ||
    (Array.isArray(n.permission)
      ? n.permission.some((permission) => user.permissions.includes(permission))
      : user.permissions.includes(n.permission));
  const fullBleed = FULL_BLEED.includes(pathname);

  const nav = (
    <nav aria-label="Workspace" className="space-y-4">
      {SECTIONS.map((section) => {
        const items = section.items.filter(allowed);
        if (!items.length) return null;
        return (
          <div key={section.title}>
            <p className="mb-1 px-3 text-[10px] font-bold uppercase tracking-wider text-muted">{section.title}</p>
            <div className="space-y-0.5">
              {items.map((item) => {
                const active = isActive(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm transition-colors",
                      active ? cx("font-semibold ring-1", section.active) : "text-foreground/80 hover:bg-surface-muted hover:text-foreground",
                    )}
                  >
                    <span aria-hidden className={cx("flex size-7 shrink-0 items-center justify-center rounded-md text-xs", section.chip)}>
                      {item.icon}
                    </span>
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        );
      })}
    </nav>
  );

  return (
    <UserContext.Provider value={user}>
      <ToastProvider>
        <div className="dm-theme app-screen flex flex-col font-sans">
          {/* Same navigation bar as every other ResQ area */}
          <SiteHeader
            subtitle="Disaster Management"
            brandHref="/dm"
            maxWidth="max-w-none"
            sticky={false}
            layer="z-30"
            leading={
              <button
                className="rounded-md p-2 text-sky-100 hover:bg-white/10 lg:hidden"
                onClick={() => setOpen(true)}
                aria-label="Open navigation"
              >
                ☰
              </button>
            }
          >
            <button
              onClick={() => setAlertsOpen(true)}
              className="cursor-pointer rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/20"
            >
              <span aria-hidden>🔔</span>
              <span className="hidden sm:inline"> Alerts</span>
            </button>
            <span aria-hidden className="mx-1 hidden h-6 w-px bg-white/20 sm:block" />
            <HeaderAccount
              name={user.name}
              detail={<HeaderRoleMenu permissions={user.permissions} />}
              signOut={signOut}
            />
          </SiteHeader>

          <div className="flex min-h-0 flex-1 overflow-hidden">
            <aside className="hidden w-60 shrink-0 overflow-y-auto overscroll-contain border-r border-border bg-surface p-3 lg:block">{nav}</aside>

            {open && (
              <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
                <button className="absolute inset-0 bg-slate-900/40" aria-label="Close navigation" onClick={() => setOpen(false)} />
                <div className="absolute inset-y-0 left-0 w-64 overflow-y-auto overscroll-contain border-r border-border bg-surface p-3 shadow-xl">{nav}</div>
              </div>
            )}

            {/* The ResQ body is fixed-height, so only the workspace scrolls inside this pane. */}
            {fullBleed ? (
              <div className="relative isolate min-w-0 flex-1">{children}</div>
            ) : (
              <div className="min-w-0 flex-1 overflow-y-auto overscroll-contain">
                <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
              </div>
            )}
          </div>
          <AlertsDrawer open={alertsOpen} onClose={() => setAlertsOpen(false)} />
        </div>
      </ToastProvider>
    </UserContext.Provider>
  );
}
