import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { signOut } from "@/app/login/actions";
import { currentUser, homeFor } from "@/lib/session";

import { DmShell } from "./shell";

export const metadata: Metadata = { title: "Workspace · ResQ" };

/**
 * The one staff workspace, shared by Disaster Management (DISASTER_MGMT) and Application Management
 * (APP_MGMT). Nothing staff-specific is sent to anyone else: visitors without a session go to /login
 * and signed-in people of another role go to their own home. Which sections each role sees is decided
 * in the shell, and the backend enforces every route regardless.
 */
export default async function DmLayout({ children }: LayoutProps<"/dm">) {
  const user = await currentUser();
  if (!user) redirect("/login?next=/dm");
  if (user.role !== "DISASTER_MGMT" && user.role !== "APP_MGMT") redirect(homeFor(user.role));

  if (!user.mfa_verified) {
    return (
      <main className="dm-theme flex min-h-screen items-center justify-center px-4">
        <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center">
          <p className="text-sm font-semibold text-critical">403 · Not authorised</p>
          <h1 className="mt-2 text-lg font-semibold">Verify your authenticator code</h1>
          <p className="mt-2 text-sm text-muted">This workspace needs a session signed in with multi-factor authentication.</p>
          <form action={signOut} className="mt-5">
            <button className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface-muted">Sign out</button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <DmShell
      user={{ name: user.full_name, email: user.email, role: user.role, permissions: user.permissions }}
      signOut={signOut}
    >
      {children}
    </DmShell>
  );
}
