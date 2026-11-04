"use client";

import { useActionState, useState } from "react";

import { ErrorBox, Spinner, authButton, authInput, authLabel } from "@/components/auth/AuthShell";

import { authenticate, type LoginState } from "./actions";

/** Turn a terse server message into something a stressed person can act on. */
function friendly(message: string): { message: string; hint?: string } {
  const m = message.toLowerCase();
  if (m.includes("unreachable") || m.includes("network") || m.includes("fetch")) {
    return { message: "We could not reach the service.", hint: "Check your internet connection and try again in a moment." };
  }
  if (m.includes("locked") || m.includes("too many")) {
    return { message, hint: "Wait a few minutes before trying again, or ask your team lead for help." };
  }
  if (m.includes("sign-in failed") || m.includes("invalid") || m.includes("incorrect")) {
    return { message: "That email or password is not correct.", hint: "Check for spaces or capital letters. Use “Show” to see what you typed." };
  }
  return { message };
}

/**
 * Sign-in for every account type. The backend decides whether a second step (authenticator
 * code) is needed: citizens never see it, staff always do.
 */
export function StaffSignIn({ next }: { next?: string }) {
  const [state, action, pending] = useActionState<LoginState, FormData>(authenticate, { step: "password" });
  const [showPassword, setShowPassword] = useState(false);
  const err = state.error ? friendly(state.error) : null;

  if (state.step === "mfa") {
    return (
      <form action={action} className="space-y-5">
        <input type="hidden" name="intent" value="mfa" />
        <input type="hidden" name="next" value={next ?? ""} />
        <div className="rounded-xl border-2 border-sky-200 bg-sky-50 p-4 text-base text-sky-950">
          <p className="font-semibold">One more step</p>
          <p className="mt-1">
            Open your authenticator app and enter the 6-digit code for <strong className="break-all">{state.email}</strong>.
          </p>
        </div>
        <div>
          <label htmlFor="staff-code" className={authLabel}>6-digit code · 6 अंकों का कोड · 6 અંકનો કોડ</label>
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
          <p className="mt-2 text-sm text-slate-600">The code changes every 30 seconds. If it fails, wait for the next one.</p>
        </div>
        {err && <ErrorBox message={err.message} hint={err.hint} />}
        <button type="submit" className={authButton} disabled={pending}>
          {pending ? (
            <>
              <Spinner /> Verifying…
            </>
          ) : (
            "Verify and continue →"
          )}
        </button>
        <a href="/login" className="block text-center text-base font-semibold text-sky-800 underline">
          Use a different account
        </a>
      </form>
    );
  }

  return (
    <form action={action} className="space-y-5">
      <input type="hidden" name="intent" value="password" />
      <input type="hidden" name="next" value={next ?? ""} />
      <div>
        <label htmlFor="staff-email" className={authLabel}>Email · ईमेल · ઇમેઇલ</label>
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
          <label htmlFor="staff-password" className="text-base font-semibold text-slate-800">Password · पासवर्ड · પાસવર્ડ</label>
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            aria-pressed={showPassword}
            className="min-h-11 cursor-pointer rounded-lg px-3 text-base font-semibold text-sky-800 hover:bg-sky-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
          >
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>
        <input
          id="staff-password"
          name="password"
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
          required
          placeholder="Your password"
          className={authInput}
        />
      </div>
      {err && <ErrorBox message={err.message} hint={err.hint} />}
      <button type="submit" className={authButton} disabled={pending}>
        {pending ? (
          <>
            <Spinner /> Signing in…
          </>
        ) : (
          "Sign in →"
        )}
      </button>
      <p className="text-center text-sm text-slate-600">Dispatch and field staff will be asked for an authenticator code next.</p>
    </form>
  );
}
