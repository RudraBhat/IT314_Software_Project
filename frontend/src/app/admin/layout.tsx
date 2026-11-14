import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { Brand } from "@/components/Brand";
import { ToastProvider } from "@/components/ui";
import { signOut } from "@/app/login/actions";
import { currentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Administration · ResQ" };

/**
 * Application Management (APP_MGMT) area: account invitations only (issue #100).
 * Administrators have no operational access; the backend enforces that on every route.
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  if (!user) redirect("/login?next=/admin");

  if (user.role !== "APP_MGMT" || !user.mfa_verified) {
    return (
      <main className="dm-theme flex min-h-screen items-center justify-center px-4">
        <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center">
          <p className="text-sm font-semibold text-critical">403 · Not authorised</p>
          <h1 className="mt-2 text-lg font-semibold">This area is for application administrators</h1>
          <p className="mt-2 text-sm text-muted">Your account cannot manage platform accounts.</p>
          <form action={signOut} className="mt-5">
            <button className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface-muted">Sign out</button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <ToastProvider>
      <div className="dm-theme app-screen flex flex-col font-sans">
        <header className="z-30 flex h-14 shrink-0 items-center gap-3 border-b border-[#093554] bg-[#0c4a75] px-4 text-white shadow-md sm:px-6">
          <Brand href="/admin" subtitle="Administration" size="sm" />
          <span className="hidden rounded-full border border-sky-300/40 bg-sky-400/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-sky-100 md:inline">
            Application Management
          </span>
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-semibold leading-tight">{user.full_name}</p>
              <p className="text-[10px] text-sky-200/80">{user.email}</p>
            </div>
            <form action={signOut}>
              <button className="rounded-full bg-white/10 px-3 py-1.5 text-xs transition hover:bg-white/20">Sign out</button>
            </form>
          </div>
        </header>
        <div className="min-w-0 flex-1 overflow-y-auto">
          <main className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
