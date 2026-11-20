import { UnifiedSiteHeader } from "../navigation/UnifiedSiteHeader";
import type { ReactNode } from "react";

/** Shared shell for the public (no-login) informational pages. */
export function PublicPage({
  title,
  intro,
  activeHref,
  children,
}: {
  title: string;
  intro: string;
  /** This page's path, so the header highlights it. */
  activeHref?: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <UnifiedSiteHeader activeHref={activeHref} />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-3xl font-bold text-slate-900">{title}</h1>
        <p className="mt-2 text-slate-600">{intro}</p>
        <div className="mt-8 space-y-8">{children}</div>
      </main>
    </div>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold text-slate-900">{title}</h2>
      <div className="space-y-2 text-sm leading-relaxed">{children}</div>
    </section>
  );
}
