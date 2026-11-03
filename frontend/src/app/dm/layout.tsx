import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { signOut } from "@/app/login/actions";
import { currentUser } from "@/lib/session";

import { DmShell } from "./shell";

export const metadata: Metadata = { title: "Operations · ResQ" };

export default async function DmLayout({ children }: LayoutProps<"/dm">) {
  const user = await currentUser();
  if (!user) redirect("/login?next=/dm");

  if (user.role !== "DISASTER_MGMT" || !user.mfa_verified) {
    return (
      <main className="dm-theme flex h-screen items-center justify-center px-4">
        <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center">
          <p className="text-sm font-semibold text-critical">403 · Not authorised</p>
          <h1 className="mt-2 text-lg font-semibold">This workspace is for Disaster Management staff</h1>
          <p className="mt-2 text-sm text-muted">Your account does not have access to operational tools.</p>
          <form action={signOut} className="mt-5">
            <button className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface-muted">Sign out</button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <DmShell user={{ name: user.full_name, email: user.email, permissions: user.permissions }} signOut={signOut}>
      {children}
    </DmShell>
  );
}
