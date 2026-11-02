import type { Metadata } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { signOut } from "@/app/login/actions";
import { currentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Field Operations · DRCH" };

export default async function FieldLayout({ children }: { children: ReactNode }) {
  const user = await currentUser();
  if (!user) redirect("/login?next=/field");

  if (user.role !== "FIELD_TEAM" || !user.mfa_verified) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center">
          <p className="text-sm font-semibold text-critical">403 · Not authorized</p>
          <h1 className="mt-2 text-lg font-semibold">This workspace is for Field Team Responders</h1>
          <p className="mt-2 text-sm text-muted">Your account does not have field responder permissions or MFA verification.</p>
          <form action={signOut} className="mt-5">
            <button className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface-muted">Sign out</button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-surface/90 backdrop-blur px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="flex size-3 rounded-full bg-emerald-500 animate-pulse" aria-hidden="true" />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-emerald-500">Field Responder</span>
                <span className="text-xs text-muted">| {user.full_name}</span>
              </div>
              <h1 className="text-base font-semibold leading-none sm:text-lg">DRCH Field Ops</h1>
            </div>
          </div>
          <form action={signOut}>
            <button className="min-h-10 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-surface-muted transition-colors">
              Sign out
            </button>
          </form>
        </div>
      </header>
      <main className="mx-auto max-w-4xl p-4 sm:p-6">{children}</main>
    </div>
  );
}
