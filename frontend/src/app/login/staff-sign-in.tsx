"use client";

import { useActionState, useState, type ReactNode } from "react";

import { ErrorBox, Spinner, authButton, authInput, authLabel } from "@/components/auth/AuthShell";
import { useAuthLanguage } from "@/components/auth/AuthLanguage";

import { authenticate, type LoginState } from "./actions";

/** Turn a terse server message into something a stressed person can act on. */
function friendly(message: string, copy: ReturnType<typeof useAuthLanguage>["copy"]): { message: string; hint?: string } {
  const m = message.toLowerCase();
  if (m.includes("unreachable") || m.includes("network") || m.includes("fetch")) {
    return { message: copy.networkError, hint: copy.networkHint };
  }
  if (m.includes("locked") || m.includes("too many")) {
    return { message, hint: copy.lockedHint };
  }
  if (m.includes("sign-in failed") || m.includes("invalid") || m.includes("incorrect")) {
    return { message: copy.incorrectCredentials, hint: copy.incorrectCredentialsHint };
  }
  return { message };
}

/**
 * Sign-in for every account type. The backend decides whether a second step (authenticator
 * code) is needed: citizens never see it, staff always do.
 *
 * `firstStepExtras` (Google sign-in, forgot password, create account) shows only with the email and
 * password form; the code step offers just "Use a different account".
 */
export function StaffSignIn({ next, firstStepExtras }: { next?: string; firstStepExtras?: ReactNode }) {
  const [state, action, pending] = useActionState<LoginState, FormData>(authenticate, { step: "password" });
  const [showPassword, setShowPassword] = useState(false);
  const { copy } = useAuthLanguage();
  const err = state.error ? friendly(state.error, copy) : null;

  if (state.step === "mfa") {
    return (
      <form action={action} className="space-y-5">
        <input type="hidden" name="intent" value="mfa" />
        <input type="hidden" name="next" value={next ?? ""} />
        <div className="rounded-xl border-2 border-sky-200 bg-sky-50 p-4 text-base text-sky-950">
          <p className="font-semibold">{copy.mfaStep}</p>
          <p className="mt-1">
            {copy.mfaInstruction(state.email ?? "")}
          </p>
        </div>
        <div>
          <label htmlFor="staff-code" className={authLabel}>{copy.codeLabel}</label>
          <input
            id="staff-code"
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            required
            autoFocus
            placeholder="000000"
            className={`${authInput} text-center font-mono text-3xl tracking-[0.5em]`}
          />
          <p className="mt-2 text-sm text-slate-600">{copy.codeHelp}</p>
        </div>
        {err && <ErrorBox message={err.message} hint={err.hint} />}
        <button type="submit" className={authButton} disabled={pending}>
          {pending ? (
            <>
              <Spinner /> {copy.verifying}
            </>
          ) : (
            copy.verifyAndContinue
          )}
        </button>
        <a href="/login" className="block text-center text-base font-semibold text-sky-800 underline">
          {copy.useDifferentAccount}
        </a>
      </form>
    );
  }

  return (
    <>
      <form action={action} className="space-y-5">
        <input type="hidden" name="intent" value="password" />
        <input type="hidden" name="next" value={next ?? ""} />
        <div>
          <label htmlFor="staff-email" className={authLabel}>{copy.email}</label>
          <input
            id="staff-email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            autoFocus
            defaultValue={state.email}
            placeholder="name@example.com"
            className={authInput}
          />
        </div>
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label htmlFor="staff-password" className="text-base font-semibold text-slate-800">{copy.password}</label>
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-pressed={showPassword}
              className="min-h-11 cursor-pointer rounded-lg px-3 text-base font-semibold text-sky-800 hover:bg-sky-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
            >
              {showPassword ? copy.hide : copy.show}
            </button>
          </div>
          <input
            id="staff-password"
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            required
            placeholder={copy.yourPassword}
            className={authInput}
          />
        </div>
        {err && <ErrorBox message={err.message} hint={err.hint} />}
        <button type="submit" className={authButton} disabled={pending}>
          {pending ? (
            <>
              <Spinner /> {copy.signingIn}
            </>
          ) : (
            copy.signInArrow
          )}
        </button>
        <p className="text-center text-sm text-slate-600">{copy.staffMfaNote}</p>
      </form>
      {firstStepExtras}
    </>
  );
}
