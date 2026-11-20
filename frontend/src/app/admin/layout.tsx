import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { HeaderAccount, HeaderChip, SiteHeader } from "@/components/Brand";
import { AdminNav } from "@/components/staff/AdminNav";
import { ToastProvider } from "@/components/ui";
import { signOut } from "@/app/login/actions";
import { currentUser, homeFor } from "@/lib/session";

export const metadata: Metadata = { title: "Administration · ResQ" };

/**
 * Application Management (APP_MGMT) area: the staff account directory, account invitations, disabling accounts and
 * the audit log (issue #100).
 * Administrators have no operational access; the backend enforces that on every route.
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  if (!user) redirect("/login?next=/admin");
  // Other roles go to their own home; nothing administrative is rendered for them.
  if (user.role !== "APP_MGMT") redirect(homeFor(user.role));

  if (!user.mfa_verified) {
    return (
      <main className="dm-theme flex min-h-screen items-center justify-center px-4">
        <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center">
          <p className="text-sm font-semibold text-critical">403 · Not authorised</p>
          <h1 className="mt-2 text-lg font-semibold">Verify your authenticator code</h1>
          <p className="mt-2 text-sm text-muted">This area needs a session signed in with multi-factor authentication.</p>
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
        <SiteHeader
          subtitle="Administration"
          brandHref="/admin"
          maxWidth="max-w-none"
          sticky={false}
          layer="z-30"
          badge={<HeaderChip>Application Management</HeaderChip>}
        >
          <AdminNav />
          <span aria-hidden className="mx-1 hidden h-6 w-px bg-white/20 sm:block" />
          <HeaderAccount name={user.full_name} detail={user.email} signOut={signOut} />
        </SiteHeader>
        <div className="min-w-0 flex-1 overflow-y-auto overscroll-contain">
          <main className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
