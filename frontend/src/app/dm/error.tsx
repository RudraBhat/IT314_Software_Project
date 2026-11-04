"use client";

import Link from "next/link";

import { ErrorState } from "@/components/ui";

/** Workspace error boundary: keeps the dispatcher shell and offers a retry. */
export default function DmError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="space-y-3">
      <ErrorState message={`This page failed to load. ${error.digest ? `Reference: ${error.digest}` : ""}`.trim()} onRetry={reset} />
      <Link href="/dm" className="inline-block text-sm text-info hover:underline">Back to dashboard</Link>
    </div>
  );
}
