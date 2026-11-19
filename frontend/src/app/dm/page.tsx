"use client";

import Link from "next/link";

import { StatusBadge } from "@/components/badges";
import { BarList } from "@/components/charts";
import { ScenarioWalkthrough } from "@/components/dm/ScenarioWalkthrough";
import { Button, Card, EmptyState, ErrorState, PageHeader, Skeleton, cx } from "@/components/ui";
import { useStaff } from "./shell";
import { useQuery } from "@/lib/api";
import { formatDateTime, formatNumber, label, scenarioLabel, timeAgo } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

export default function DashboardPage() {
  const { data, error, loading, reload } = useQuery<Dashboard>("dashboard");

  return (
    <>
      <PageHeader
        title="Operations dashboard"
        description={
          data ? (
            <>
              Live from the operations database · updated {formatDateTime(data.generated_at)}
              {data.data_fresh_as_of && <> · latest incident change {timeAgo(data.data_fresh_as_of)}</>}
            </>
          ) : (
            "Live counts, queues and pending actions."
          )
        }
        actions={
          <Button onClick={reload} busy={loading && !!data}>
            Refresh
          </Button>
        }
      />
      {error && <ErrorState message={error} onRetry={reload} />}
      {!data && loading && <DashboardSkeleton />}
      {data && <DashboardBody d={data} />}
    </>
  );
}

function Stat({ label: name, value, tone, href, note }: { label: string; value: number; tone?: string; href?: string; note?: string }) {
  const body = (
    <>
      <p className="text-xs font-medium text-muted">{name}</p>
      <p className={cx("mt-1.5 text-2xl font-semibold tabular-nums sm:text-3xl", tone)}>{formatNumber(value)}</p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </>
  );
  const cls = "block rounded-xl border border-border bg-surface p-4 transition-colors";
  return href ? (
    <Link href={href} className={cx(cls, "hover:border-foreground/20")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function DashboardBody({ d }: { d: Dashboard }) {
  const urgent = [
    d.dispatches.overdue > 0 && {
      text: `${d.dispatches.overdue} dispatch${d.dispatches.overdue === 1 ? "" : "es"} unacknowledged for over ${d.dispatches.ack_timeout_minutes} min`,
      href: "/dm/dispatches?overdue=1",
    },
    d.incidents.critical_open > 0 && { text: `${d.incidents.critical_open} critical incident(s) open`, href: "/dm/incidents?priority=CRITICAL" },
    d.moderation.pending > 0 && {
      text: `${d.moderation.pending} evidence item(s) awaiting moderation${d.moderation.oldest ? `, oldest ${timeAgo(d.moderation.oldest)}` : ""}`,
      href: "/dm/moderation",
    },
    d.aid.awaiting_verification > 0 && { text: `${d.aid.awaiting_verification} aid contribution(s) awaiting verification`, href: "/dm/aid" },
  ].filter(Boolean) as { text: string; href: string }[];

  return (
    <div className="space-y-6">
      {urgent.length > 0 && (
        <section aria-label="Pending actions" className="rounded-xl border border-high/30 bg-high-soft p-4">
          <h2 className="text-sm font-semibold text-high">Needs attention</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {urgent.map((u) => (
              <li key={u.text}>
                <Link href={u.href} className="underline-offset-2 hover:underline">
                  {u.text} →
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4" aria-label="Key figures">
        <Stat label="Total incidents" value={d.incidents.total} href="/dm/incidents" />
        <Stat label="Pending verification" value={d.incidents.pending_verification} tone="text-info" href="/dm/incidents?status=SUBMITTED&status=NEEDS_INFORMATION" note={`${d.incidents.needs_information} awaiting reporter`} />
        <Stat label="Critical / high open" value={d.incidents.critical_open + d.incidents.high_open} tone="text-critical" href="/dm/incidents?priority=CRITICAL&priority=HIGH" note={`${d.incidents.critical_open} critical · ${d.incidents.high_open} high`} />
        <Stat label="Verified & active" value={d.incidents.verified_active} href="/dm/incidents?status=VERIFIED&status=DISPATCHED" note={`${d.incidents.unprioritised_open} open without priority`} />
        <Stat label="Active dispatches" value={d.dispatches.active} href="/dm/dispatches" note={`${d.dispatches.awaiting_ack} awaiting acknowledgement`} />
        <Stat label="Overdue dispatches" value={d.dispatches.overdue} tone={d.dispatches.overdue ? "text-critical" : undefined} href="/dm/dispatches?overdue=1" />
        <Stat label="Available resources" value={d.resources.available} tone="text-low" href="/dm/resources" note={`of ${d.resources.total} tracked`} />
        <Stat label="Open aid needs" value={d.aid.open_needs} href="/dm/aid" />
      </section>

      <YourFocus d={d} />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Verification queue" subtitle="Oldest unverified reports first, by reported urgency" className="lg:col-span-2"
          actions={<Link href="/dm/incidents?status=SUBMITTED&status=NEEDS_INFORMATION" className="text-sm text-info hover:underline">View all</Link>}
          bodyClassName="p-0">
          {d.verification_queue.length === 0 ? (
            <div className="p-5"><EmptyState title="No reports are waiting for verification." /></div>
          ) : (
            <ul className="divide-y divide-border">
              {d.verification_queue.map((i) => (
                <li key={i.incident_id}>
                  <Link href={`/dm/incidents/${i.incident_id}`} className="flex flex-col gap-1 px-5 py-3 hover:bg-surface-muted sm:flex-row sm:items-center sm:gap-4">
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-xs text-muted">{i.incident_ref}</p>
                      <p className="truncate text-sm font-medium">
                        {scenarioLabel[i.scenario]} · {i.address_text ?? "Location by coordinates"}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                      {i.reported_urgency && <span>Reported {label(i.reported_urgency).toLowerCase()}</span>}
                      <StatusBadge status={i.status} />
                      <span className="tabular-nums">{timeAgo(i.submitted_at)}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Incidents by scenario" subtitle="Open of total">
          <BarList
            emptyText="No incidents recorded yet."
            rows={["cyclone", "industrial_fire", "urban_flooding"].map((s) => {
              const row = d.by_scenario.find((r) => r.scenario === s);
              return { label: scenarioLabel[s], value: row?.open ?? 0, hint: `of ${row?.total ?? 0}` };
            })}
          />
          <table className="sr-only">
            <caption>Incidents by scenario</caption>
            <thead><tr><th>Scenario</th><th>Open</th><th>Total</th></tr></thead>
            <tbody>
              {d.by_scenario.map((r) => (
                <tr key={r.scenario}><td>{scenarioLabel[r.scenario]}</td><td>{r.open}</td><td>{r.total}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Recent activity" subtitle="Latest recorded status changes" className="lg:col-span-2" bodyClassName="p-0">
          {d.recent_activity.length === 0 ? (
            <div className="p-5"><EmptyState title="No status changes recorded yet." /></div>
          ) : (
            <ol className="divide-y divide-border">
              {d.recent_activity.map((a) => (
                <li key={a.history_id} className="flex flex-col gap-1 px-5 py-3 text-sm sm:flex-row sm:items-start sm:gap-4">
                  <span className="w-28 shrink-0 text-xs text-muted tabular-nums">{timeAgo(a.changed_at)}</span>
                  <div className="min-w-0 flex-1">
                    <p>
                      <Link href={`/dm/incidents/${a.incident_id}`} className="font-mono text-xs text-info hover:underline">{a.incident_ref}</Link>{" "}
                      {a.from_status && <><StatusBadge status={a.from_status} /> → </>}
                      <StatusBadge status={a.to_status} />
                    </p>
                    {a.reason && <p className="mt-1 line-clamp-2 text-xs text-muted">{a.reason}</p>}
                  </div>
                  <span className="text-xs text-muted">{a.changed_by_name ?? "System"}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Resources by type" subtitle="Available now / tracked">
          <BarList
            barClass="bg-low"
            emptyText="No resources registered yet."
            rows={d.resources.by_type.map((r) => ({ label: label(r.type), value: r.available, hint: `of ${r.total}` }))}
          />
        </Card>
      </div>
    </div>
  );
}

/** Queues that matter for the permissions this account holds. The backend still enforces each action. */
function YourFocus({ d }: { d: Dashboard }) {
  const { can } = useStaff();
  const items = [
    can("DISPATCH") && { text: "Dispatches awaiting acknowledgement", value: d.dispatches.awaiting_ack, href: "/dm/dispatches" },
    can("MODERATOR") && { text: "Evidence awaiting moderation", value: d.moderation.pending, href: "/dm/moderation" },
    can("CLOSURE") && { text: "Verified incidents still active", value: d.incidents.verified_active, href: "/dm/incidents?status=VERIFIED&status=DISPATCHED" },
    can("PUBLISHER") && { text: "Safety content and public updates", value: null, href: "/dm/updates" },
    can("SUPERVISOR") && { text: "Staff accounts", value: null, href: "/dm/staff" },
  ].filter(Boolean) as { text: string; value: number | null; href: string }[];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Your focus" subtitle="Based on your permissions">
        {items.length === 0 ? (
          <EmptyState title="Your account has the standard officer permissions.">Verification is the main queue for you.</EmptyState>
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((i) => (
              <li key={i.text} className="flex justify-between gap-3">
                <Link href={i.href} className="text-info hover:underline">{i.text}</Link>
                {i.value !== null && <span className="tabular-nums font-medium">{formatNumber(i.value)}</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <ScenarioWalkthrough />
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading dashboard">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Skeleton className="h-72 lg:col-span-2" />
        <Skeleton className="h-72" />
      </div>
    </div>
  );
}
