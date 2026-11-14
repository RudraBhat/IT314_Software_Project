"use client";

import Link from "next/link";
import { SiteHeader, NavLink } from "@/components/Brand";
import { useSyncExternalStore, type ReactNode } from "react";

import { AuthLanguageProvider, useAuthLanguage } from "./AuthLanguage";

/** Shared styles so every sign-in / sign-up control is large, high-contrast and thumb-friendly. */
export const authInput =
  "w-full min-h-14 rounded-xl border-2 border-slate-300 bg-white px-4 text-lg text-slate-900 placeholder-slate-400 " +
  "focus:border-sky-600 focus:outline-none focus:ring-4 focus:ring-sky-200";
export const authLabel = "mb-1.5 block text-base font-semibold text-slate-800";
export const authButton =
  "flex min-h-14 w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-sky-700 px-4 text-lg font-bold text-white " +
  "shadow-md transition hover:bg-sky-800 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300 disabled:cursor-wait disabled:opacity-70";

const EMERGENCY_NUMBERS = [
  { number: "112", labelIndex: 0 },
  { number: "108", labelIndex: 1 },
  { number: "101", labelIndex: 2 },
  { number: "1070", labelIndex: 3 },
] as const;

function subscribe(cb: () => void) {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => {
    window.removeEventListener("online", cb);
    window.removeEventListener("offline", cb);
  };
}

function useOnline() {
  return useSyncExternalStore(
    subscribe,
    () => navigator.onLine,
    () => true,
  );
}

export function Spinner() {
  return <span aria-hidden className="h-5 w-5 animate-spin rounded-full border-2 border-white/40 border-t-white" />;
}

export function ErrorBox({ message, hint }: { message: string; hint?: string }) {
  return (
    <div role="alert" className="rounded-xl border-2 border-red-300 bg-red-50 p-4 text-base text-red-900">
      <p className="font-semibold">⚠️ {message}</p>
      {hint && <p className="mt-1 text-sm text-red-800">{hint}</p>}
    </div>
  );
}

/**
 * Page frame for sign-in and sign-up. The page scrolls with the document, so the form stays
 * reachable on small phones and when the keyboard is open.
 * It also provides the selected language, so every auth page shows one language at a time and
 * the choice carries over between pages (issue #95).
 */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <AuthLanguageProvider>
      <AuthFrame>{children}</AuthFrame>
    </AuthLanguageProvider>
  );
}

function AuthFrame({ children }: { children: ReactNode }) {
  const online = useOnline();
  const { copy } = useAuthLanguage();
  return (
    <div className="min-h-dvh bg-slate-100 font-sans text-slate-900">
      <a
        href="#auth-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        {copy.skipToForm}
      </a>

      <section aria-label={copy.emergencySection} className="bg-red-700 text-white">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-center gap-x-3 gap-y-2 px-3 py-3">
          <p className="w-full text-center text-sm font-semibold sm:w-auto">
            {copy.emergencyMessage}
          </p>
          {EMERGENCY_NUMBERS.map(({ number, labelIndex }) => {
            const label = copy.emergencyLabels[labelIndex];
            return (
              <a
                key={number}
                href={`tel:${number}`}
                aria-label={copy.callNumber(number, label)}
                className="flex min-h-12 min-w-[5.5rem] flex-col items-center justify-center rounded-lg bg-white px-3 text-red-800 shadow hover:bg-red-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-red-300"
              >
                <span className="text-xl font-extrabold leading-none">{number}</span>
                <span className="text-[11px] font-semibold leading-tight">{label}</span>
              </a>
            );
          })}
        </div>
      </section>

      {!online && (
        <div role="status" className="bg-amber-100 px-4 py-3 text-center text-base font-semibold text-amber-900">
          {copy.offlineMessage}
        </div>
      )}

      <SiteHeader subtitle="Gujarat Emergency Portal" maxWidth="max-w-3xl">
        <NavLink href="/">{copy.liveMap}</NavLink>
      </SiteHeader>

      <main id="auth-main" className="mx-auto w-full max-w-lg px-4 py-6 sm:py-10">
        {children}
      </main>

      <footer className="px-4 pb-8 text-center text-sm text-slate-600">
        <Link href="/how-to" className="underline">{copy.howTo}</Link> · <Link href="/safety" className="underline">{copy.safetyGuidance}</Link> ·{" "}
        <Link href="/about" className="underline">{copy.about}</Link>
        <p className="mt-2 text-xs text-slate-500">{copy.footer}</p>
      </footer>
    </div>
  );
}
