import Link from "next/link";
import type { ReactNode } from "react";

/** Shared shell for the public (no-login) informational pages. */
export function PublicPage({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-[#0c4a75] text-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-4">
          <Link href="/" className="text-lg font-black tracking-tight">
            ResQ <span className="text-xs font-medium text-sky-200">Gujarat Emergency Portal</span>
          </Link>
          <nav className="flex gap-4 text-sm font-semibold" aria-label="Public pages">
            <Link href="/" className="hover:underline">Map</Link>
            <Link href="/about" className="hover:underline">About</Link>
            <Link href="/how-to" className="hover:underline">How to use</Link>
          </nav>
        </div>
      </header>
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
