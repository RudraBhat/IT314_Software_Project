import type { Metadata } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { SiteHeader } from "@/components/Brand";
import { signOut } from "@/app/login/actions";
import { currentUser, homeFor } from "@/lib/session";

export const metadata: Metadata = { title: "Field Operations · ResQ" };

export default async function FieldLayout({ children }: { children: ReactNode }) {
  const user = await currentUser();
  if (!user) redirect("/login?next=/field");

  // Other roles go to their own home; nothing field-specific is rendered for them.
  if (user.role !== "FIELD_TEAM") redirect(homeFor(user.role));
  if (!user.mfa_verified) {
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
      <SiteHeader subtitle={`Field Ops · ${user.full_name}`} brandHref="/field" maxWidth="max-w-4xl">
        <form action={signOut}>
          <button className="min-h-11 cursor-pointer rounded-lg bg-white/10 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300">
            Sign out
          </button>
        </form>
      </SiteHeader>
      <main className="mx-auto max-w-4xl p-4 sm:p-6">{children}</main>
    </div>
  );
}
