"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PriorityBadge, StatusBadge } from "@/components/badges";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingRows, Notice, PageHeader, Pagination, cx } from "@/components/ui";
import { useAction } from "@/components/use-action";
import { downloadCsv, useQuery } from "@/lib/api";
import { label, scenarioLabel, timeAgo } from "@/lib/format";
import type { Dispatch, Paged } from "@/lib/types";

const VIEWS = [
  { key: "active", label: "Active" },
  { key: "overdue", label: "Overdue" },
  { key: "all", label: "All" },
] as const;

export default function DispatchesPage() {
  return (
    <Suspense fallback={<LoadingRows />}>
      <Dispatches />
    </Suspense>
  );
}

function Dispatches() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const view = params.get("overdue") ? "overdue" : (params.get("view") ?? "active");
  const page = Number(params.get("page") ?? 1);
  const { run, busy } = useAction();
  const [cut, setCut] = useState(false);
  const { data, error, loading, reload } = useQuery<Paged<Dispatch> & { ack_timeout_minutes: number }>("dispatches", {
    active: view === "active" || undefined,
    overdue: view === "overdue" || undefined,
    page,
    limit: 25,
  });

  return (
    <>
      <PageHeader
        title="Dispatches"
        description={
          data
            ? `Unacknowledged orders escalate to supervisors after ${data.ack_timeout_minutes} minutes.`
            : "Dispatch orders and their recorded confirmations."
        }
        actions={
          <div className="flex gap-2">
            <Button
              onClick={async () => {
                const done = await run(
                  "export",
                  () => downloadCsv("dispatches/export", { active: view === "active" || undefined, overdue: view === "overdue" || undefined }, "dispatches.csv"),
                  "Export downloaded.",
                );
                if (done) setCut(done.truncated);
              }}
              busy={busy === "export"}
              disabled={!data || data.total === 0}
              title="Download the dispatches in this view as CSV. It is recorded in the audit log."
            >
              Export CSV
            </Button>
            <Button onClick={reload} busy={loading && !!data}>Refresh</Button>
          </div>
        }
      />
      {cut && (
        <div className="mb-4">
          <Notice tone="high">The export stopped at 5,000 dispatches. Switch to a narrower view to get the rest.</Notice>
        </div>
      )}
      <div className="mb-4 flex gap-1 rounded-lg border border-border bg-surface p-1 text-sm" role="tablist" aria-label="Dispatch view">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            role="tab"
            aria-selected={view === v.key}
            onClick={() => router.replace(`${pathname}?view=${v.key}`)}
            className={cx("flex-1 rounded-md px-3 py-1.5", view === v.key ? "bg-surface-muted font-medium" : "text-muted hover:text-foreground")}
          >
            {v.label}
          </button>
        ))}
      </div>
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingRows rows={6} />}
      {data && (
        <Card bodyClassName="p-0">
          {data.items.length === 0 ? (
            <div className="p-5">
              <EmptyState title={view === "overdue" ? "No overdue dispatches." : view === "active" ? "No active dispatches." : "No dispatches yet."}>
                Dispatches are created from a verified incident.
              </EmptyState>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {data.items.map((d) => (
                <li key={d.dispatch_id}>
                  <Link href={`/dm/dispatches/${d.dispatch_id}`} className="flex flex-col gap-2 px-5 py-3 hover:bg-surface-muted sm:flex-row sm:items-center sm:gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-info">{d.dispatch_ref}</span>
                        <StatusBadge status={d.status} />
                        <PriorityBadge priority={d.priority} />
                        {d.overdue && <Badge tone="critical">Overdue</Badge>}
                        {d.escalated && <Badge tone="critical">Escalated</Badge>}
                      </div>
                      <p className="mt-1 truncate text-sm">
                        {d.agency_name} · {d.incident_ref} ({d.scenario ? (scenarioLabel[d.scenario] ?? d.scenario) : "General"})
                      </p>
                    </div>
                    <p className="text-xs text-muted">
                      {d.acknowledged_at ? `Acknowledged ${timeAgo(d.acknowledged_at)}` : `${label(d.status)} ${timeAgo(d.created_at)}`}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <div className="border-t border-border px-5 py-3">
            <Pagination page={data.page} pages={data.pages} total={data.total} onPage={(p) => router.replace(`${pathname}?view=${view}&page=${p}`)} />
          </div>
        </Card>
      )}
    </>
  );
}
