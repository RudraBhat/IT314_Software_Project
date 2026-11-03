"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useState, type ReactNode } from "react";

import { AlertsDrawer } from "@/components/dm/AlertsDrawer";
import { ToastProvider, cx } from "@/components/ui";

export type StaffUser = { name: string; email: string; permissions: string[] };

const UserContext = createContext<StaffUser>({ name: "", email: "", permissions: [] });

/** Permission hints for the UI only; the backend enforces every permission itself. */
export function useStaff() {
  const user = useContext(UserContext);
  return { ...user, can: (permission: string) => user.permissions.includes(permission) };
}

const NAV: { href: string; label: string; icon: string; permission?: string }[] = [
  { href: "/dm", label: "Dashboard", icon: "▦" },
  { href: "/dm/incidents", label: "Incidents", icon: "⚑" },
  { href: "/dm/signals", label: "Signals", icon: "⚡" },
  { href: "/", label: "Live map", icon: "◎" },
  { href: "/dm/dispatches", label: "Dispatches", icon: "➜" },
  { href: "/dm/resources", label: "Resources", icon: "▣" },
  { href: "/dm/moderation", label: "Moderation", icon: "◐", permission: "MODERATOR" },
  { href: "/dm/updates", label: "Public updates", icon: "✎" },
  { href: "/dm/content", label: "Safety content", icon: "☰" },
  { href: "/dm/aid", label: "Aid & needs", icon: "◆" },
  { href: "/dm/campaigns", label: "Campaigns", icon: "₹" },
  { href: "/dm/analytics", label: "Analytics", icon: "▤" },
  { href: "/dm/staff", label: "Staff accounts", icon: "👥", permission: "SUPERVISOR" },
];

const PERMISSION_LABEL: Record<string, string> = {
  PUBLISHER: "Publisher",
  MODERATOR: "Moderator",
  CLOSURE: "Closure",
  DISPATCH: "Dispatch",
  SUPERVISOR: "Supervisor",
};

export function DmShell({ user, signOut, children }: { user: StaffUser; signOut: () => Promise<void>; children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const isActive = (href: string) => (href === "/dm" || href === "/" ? pathname === href : pathname.startsWith(href));
  const items = NAV.filter((n) => !n.permission || user.permissions.includes(n.permission));

  const nav = (
    <nav aria-label="Workspace" className="space-y-0.5">
      {items.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          onClick={() => setOpen(false)}
          aria-current={isActive(item.href) ? "page" : undefined}
          className={cx(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
            isActive(item.href) ? "bg-sky-500/15 font-semibold text-sky-300 ring-1 ring-sky-500/40" : "text-muted hover:bg-surface-muted hover:text-foreground",
          )}
        >
          <span aria-hidden className="w-4 text-center">
            {item.icon}
          </span>
          {item.label}
        </Link>
      ))}
    </nav>
  );

  return (
    <UserContext.Provider value={user}>
      <ToastProvider>
        <div className="dm-theme flex h-screen w-full flex-col font-sans">
          {/* Same top banner as the ResQ login page */}
          <header className="z-30 flex h-14 shrink-0 items-center gap-3 border-b border-[#093554] bg-[#0c4a75] px-4 text-white shadow-md sm:px-6">
            <button className="rounded-md p-2 text-sky-100 hover:bg-white/10 lg:hidden" onClick={() => setOpen(true)} aria-label="Open navigation">
              ☰
            </button>
            <Brand />
            <span className="hidden rounded-full border border-sky-300/40 bg-sky-400/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-sky-100 md:inline">
              Disaster Management
            </span>
            <div className="ml-auto flex items-center gap-3">
              <Link href="/" className="hidden items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5 text-xs transition hover:bg-white/20 md:flex">
                <span aria-hidden>←</span> General Dashboard
              </Link>
              <div className="hidden text-right sm:block">
                <p className="text-sm font-semibold leading-tight">{user.name}</p>
                <p className="text-[10px] text-sky-200/80">
                  {user.permissions.length ? user.permissions.map((p) => PERMISSION_LABEL[p] ?? p).join(" · ") : "Disaster Management"}
                </p>
              </div>
              <button onClick={() => setAlertsOpen(true)} className="rounded-full bg-white/10 px-3 py-1.5 text-xs transition hover:bg-white/20">
                <span aria-hidden>🔔</span> Alerts
              </button>
              <form action={signOut}>
                <button className="rounded-full bg-white/10 px-3 py-1.5 text-xs transition hover:bg-white/20">Sign out</button>
              </form>
            </div>
          </header>

          <div className="flex min-h-0 flex-1">
            <aside className="hidden w-56 shrink-0 overflow-y-auto border-r border-border bg-surface p-3 lg:block">{nav}</aside>

            {open && (
              <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
                <button className="absolute inset-0 bg-black/60" aria-label="Close navigation" onClick={() => setOpen(false)} />
                <div className="absolute inset-y-0 left-0 w-64 overflow-y-auto border-r border-border bg-surface p-3 shadow-xl">{nav}</div>
              </div>
            )}

            {/* The ResQ body is fixed-height, so the workspace scrolls inside this pane. */}
            <div className="min-w-0 flex-1 overflow-y-auto">
              <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
            </div>
          </div>
          <AlertsDrawer open={alertsOpen} onClose={() => setAlertsOpen(false)} />
        </div>
      </ToastProvider>
    </UserContext.Provider>
  );
}

function Brand() {
  return (
    <Link href="/dm" className="flex items-center gap-2.5">
      <span className="flex size-8 items-center justify-center rounded-full border border-white bg-sky-400/20 text-lg" aria-hidden>
        🛡️
      </span>
      <span className="leading-tight">
        <span className="flex items-baseline gap-1.5">
          <span className="text-xl font-extrabold">ResQ</span>
          <span className="text-xs font-light text-sky-200">GeoPlatform</span>
        </span>
        <span className="block text-[9px] text-sky-200/80">NDMA Disaster Response Coordination Hub</span>
      </span>
    </Link>
  );
}
