"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { AuthShell } from "@/components/auth/AuthShell";

import { StaffSignIn } from "./staff-sign-in";

function LoginCard() {
  const next = useSearchParams().get("next") ?? undefined;
  return (
    <div className="space-y-6 rounded-2xl bg-white p-6 shadow-lg sm:p-8">
      <div className="text-center">
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Sign in</h1>
        <p className="mt-1 text-base font-medium text-slate-700">साइन इन · સાઇન ઇન</p>
        <p className="mt-3 text-base text-slate-600">
          For citizens, field teams and dispatch staff. Use the email and password you registered with.
        </p>
      </div>

      <StaffSignIn next={next} />

      <div className="space-y-3 border-t border-slate-200 pt-5 text-center">
        <div className="flex justify-center gap-4 text-sm text-slate-600">
          <Link href="/forgot-password" className="font-semibold text-sky-800 underline hover:text-sky-900">
            Forgot password?
          </Link>
          <span>•</span>
          <Link href="/setup-account" className="font-semibold text-sky-800 underline hover:text-sky-900">
            Staff invitation setup
          </Link>
        </div>
        <p className="text-base text-slate-700">New here? Citizens can create a free account.</p>
        <Link
          href="/signup"
          className="flex min-h-14 w-full items-center justify-center rounded-xl border-2 border-sky-700 px-2 text-center text-lg font-bold text-sky-800 hover:bg-sky-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
        >
          Create account · खाता बनाएं · ખાતું બનાવો
        </Link>
      </div>

      <p className="rounded-xl bg-slate-50 p-4 text-center text-sm text-slate-600">
        Can&apos;t sign in right now? You can still view the{" "}
        <Link href="/" className="font-semibold text-sky-800 underline">live public map</Link> and read the{" "}
        <Link href="/safety" className="font-semibold text-sky-800 underline">safety guidance</Link> without an account.
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <AuthShell>
      <Suspense fallback={<p className="text-center text-base text-slate-600">Loading…</p>}>
        <LoginCard />
      </Suspense>
    </AuthShell>
  );
}
