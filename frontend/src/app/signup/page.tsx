"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { AuthShell, ErrorBox, Spinner, authButton, authInput, authLabel } from "@/components/auth/AuthShell";

import { register } from "../login/actions";

const RULES: { label: string; ok: (p: string) => boolean }[] = [
  { label: "At least 8 characters", ok: (p) => p.length >= 8 },
  { label: "At least one number", ok: (p) => /\d/.test(p) },
  { label: "At least one symbol (for example ! @ # ?)", ok: (p) => /[^A-Za-z0-9]/.test(p) },
];

export default function SignupPage() {
  const [state, formAction, isPending] = useActionState(register, {});
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const allOk = RULES.every((r) => r.ok(password));

  return (
    <AuthShell>
      <div className="space-y-6 rounded-2xl bg-white p-6 shadow-lg sm:p-8">
        <div className="text-center">
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Create your account</h1>
          <p className="mt-1 text-base font-medium text-slate-700">खाता बनाएं · ખાતું બનાવો</p>
          <p className="mt-3 text-base text-slate-600">Free. It lets you report an incident and follow what happens next.</p>
        </div>

        <p className="rounded-xl bg-sky-50 p-4 text-sm text-sky-950">
          Citizen accounts only. Staff and field-team accounts are issued by your administrator –{" "}
          <Link href="/login" className="font-semibold underline">sign in here</Link>.
        </p>

        {state?.error && <ErrorBox message={state.error} hint="Check the details below and try again." />}

        <form action={formAction} className="space-y-5">
          <div>
            <label htmlFor="signup-name" className={authLabel}>
              Full name <span className="text-red-700" aria-hidden>*</span>
            </label>
            <input id="signup-name" name="full_name" type="text" required autoComplete="name" autoFocus placeholder="Ramesh Patel" className={authInput} />
          </div>
          <div>
            <label htmlFor="signup-phone" className={authLabel}>
              Phone number <span className="font-normal text-slate-500">(optional, helps responders reach you)</span>
            </label>
            <input id="signup-phone" name="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" className={authInput} />
          </div>
          <div>
            <label htmlFor="signup-email" className={authLabel}>
              Email <span className="text-red-700" aria-hidden>*</span>
            </label>
            <input
              id="signup-email"
              name="email"
              type="email"
              inputMode="email"
              required
              autoComplete="email"
              autoCapitalize="none"
              spellCheck={false}
              placeholder="name@example.com"
              className={authInput}
            />
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label htmlFor="signup-password" className="text-base font-semibold text-slate-800">
                Password <span className="text-red-700" aria-hidden>*</span>
              </label>
              <button
                type="button"
                onClick={() => setShow((v) => !v)}
                aria-pressed={show}
                className="min-h-11 cursor-pointer rounded-lg px-3 text-base font-semibold text-sky-800 hover:bg-sky-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
              >
                {show ? "Hide" : "Show"}
              </button>
            </div>
            <input
              id="signup-password"
              name="password"
              type={show ? "text" : "password"}
              required
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby="pw-rules"
              placeholder="Choose a password"
              className={authInput}
            />
            <ul id="pw-rules" className="mt-2 space-y-1 text-sm">
              {RULES.map((r) => {
                const ok = r.ok(password);
                return (
                  <li key={r.label} className={ok ? "font-semibold text-green-800" : "text-slate-600"}>
                    <span aria-hidden>{ok ? "✔" : "○"}</span> {r.label}
                    <span className="sr-only">{ok ? " – done" : " – not yet"}</span>
                  </li>
                );
              })}
            </ul>
          </div>
          <button type="submit" disabled={isPending || !allOk} className={authButton}>
            {isPending ? (
              <>
                <Spinner /> Creating account…
              </>
            ) : (
              "Create account →"
            )}
          </button>
        </form>

        <div className="border-t border-slate-200 pt-5 text-center text-base text-slate-700">
          Already have an account?{" "}
          <Link href="/login" className="font-bold text-sky-800 underline">Sign in</Link>
        </div>
      </div>
    </AuthShell>
  );
}
