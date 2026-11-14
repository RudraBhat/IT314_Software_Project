"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { useAuthLanguage } from "@/components/auth/AuthLanguage";
import { AuthShell, ErrorBox, Spinner, authButton, authInput, authLabel } from "@/components/auth/AuthShell";
import { LanguageSelector } from "@/components/auth/LanguageSelector";
import { GoogleSignInButton } from "@/components/GoogleSignInButton";

import { register } from "../login/actions";

/** Password checks, in the same order as copy.passwordRules. */
const RULES: ((p: string) => boolean)[] = [
  (p) => p.length >= 8,
  (p) => /\d/.test(p),
  (p) => /[^\p{L}\p{N}_\s]/u.test(p),
];

export default function SignupPage() {
  return (
    <AuthShell>
      <SignupCard />
    </AuthShell>
  );
}

function SignupCard() {
  const { copy } = useAuthLanguage();
  const [state, formAction, isPending] = useActionState(register, {});
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const allOk = RULES.every((ok) => ok(password));

  return (
    <div className="space-y-6 rounded-2xl bg-white p-6 shadow-lg sm:p-8">
      <LanguageSelector />
      <div className="text-center">
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">{copy.createYourAccount}</h1>
        <p className="mt-3 text-base text-slate-600">{copy.signupDescription}</p>
      </div>

      <p className="rounded-xl bg-sky-50 p-4 text-sm text-sky-950">
        {copy.citizenOnlyNote}{" "}
        <Link href="/login" className="font-semibold underline">{copy.signInHere}</Link>.
      </p>

      {state?.error && <ErrorBox message={state.error} hint={copy.checkDetails} />}

      <form action={formAction} className="space-y-5">
        <div>
          <label htmlFor="signup-name" className={authLabel}>
            {copy.fullName} <span className="text-red-700" aria-hidden>*</span>
          </label>
          <input id="signup-name" name="full_name" type="text" required autoComplete="name" autoFocus placeholder="Ramesh Patel" className={authInput} />
        </div>
        <div>
          <label htmlFor="signup-phone" className={authLabel}>
            {copy.phoneNumber} <span className="font-normal text-slate-500">{copy.phoneHelp}</span>
          </label>
          <input id="signup-phone" name="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" className={authInput} />
        </div>
        <div>
          <label htmlFor="signup-email" className={authLabel}>
            {copy.email} <span className="text-red-700" aria-hidden>*</span>
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
              {copy.password} <span className="text-red-700" aria-hidden>*</span>
            </label>
            <button
              type="button"
              onClick={() => setShow((v) => !v)}
              aria-pressed={show}
              className="min-h-11 cursor-pointer rounded-lg px-3 text-base font-semibold text-sky-800 hover:bg-sky-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
            >
              {show ? copy.hide : copy.show}
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
            placeholder={copy.choosePassword}
            className={authInput}
          />
          <ul id="pw-rules" className="mt-2 space-y-1 text-sm">
            {RULES.map((check, index) => {
              const ok = check(password);
              return (
                <li key={index} className={ok ? "font-semibold text-green-800" : "text-slate-600"}>
                  <span aria-hidden>{ok ? "✔" : "○"}</span> {copy.passwordRules[index]}
                  <span className="sr-only"> – {ok ? copy.ruleDone : copy.ruleNotYet}</span>
                </li>
              );
            })}
          </ul>
        </div>
        <button type="submit" disabled={isPending || !allOk} className={authButton}>
          {isPending ? (
            <>
              <Spinner /> {copy.creatingAccount}
            </>
          ) : (
            copy.createAccountArrow
          )}
        </button>
      </form>

      <GoogleSignInButton mode="signup" />

      <div className="border-t border-slate-200 pt-5 text-center text-base text-slate-700">
        {copy.alreadyHaveAccount}{" "}
        <Link href="/login" className="font-bold text-sky-800 underline">{copy.signIn}</Link>
      </div>
    </div>
  );
}
