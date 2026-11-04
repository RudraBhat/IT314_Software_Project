"use client";

import Link from "next/link";

/** Root error boundary: a readable message and a retry instead of a blank screen. */
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main role="alert" className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 px-4 text-center text-slate-800">
      <h1 className="text-2xl font-bold">Something went wrong</h1>
      <p className="max-w-md text-sm text-slate-600">
        The page could not be displayed. You can try again, or return to the map.
        {error.digest ? ` (Reference: ${error.digest})` : ""}
      </p>
      <div className="flex gap-3">
        <button onClick={reset} className="rounded-lg bg-sky-700 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
          Try again
        </button>
        <Link href="/" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold hover:bg-white focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
          Back to map
        </Link>
      </div>
      <p className="text-xs text-slate-500">In an emergency call 112.</p>
    </main>
  );
}
