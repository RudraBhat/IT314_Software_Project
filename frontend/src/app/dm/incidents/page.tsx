"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PriorityBadge, StatusBadge } from "@/components/badges";
import { Button, Card, EmptyState, ErrorState, Field, Input, LoadingRows, PageHeader, Pagination, Select } from "@/components/ui";
import { useQuery } from "@/lib/api";
import { INCIDENT_STATUSES, PRIORITIES, SCENARIOS, formatNumber, label, scenarioLabel, timeAgo } from "@/lib/format";
import type { IncidentRow, Paged } from "@/lib/types";

export default function IncidentsPage() {
  return (
    <Suspense fallback={<LoadingRows />}>
      <Incidents />
    </Suspense>
  );
}

function Incidents() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [q, setQ] = useState(params.get("q") ?? "");

  const query = {
    scenario: params.get("scenario") ?? undefined,
    status: params.getAll("status"),
    priority: params.getAll("priority"),
    from: params.get("from") ?? undefined,
    to: params.get("to") ?? undefined,
    q: params.get("q") ?? undefined,
    withdrawal_requested: params.get("withdrawal_requested") === "true" ? true : undefined,
    sort: params.get("sort") ?? "newest",
    page: Number(params.get("page") ?? 1),
    limit: 25,
  };
  const { data, error, loading, reload } = useQuery<Paged<IncidentRow>>("incidents", query);

  function update(changes: Record<string, string | string[] | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key);
      if (Array.isArray(value)) value.forEach((v) => next.append(key, v));
      else if (value) next.set(key, value);
    }
    if (!("page" in changes)) next.delete("page");
    router.replace(`${pathname}?${next.toString()}`);
  }

  const activeFilters = ["scenario", "status", "priority", "from", "to", "q", "withdrawal_requested"].some((k) => params.has(k));

  return (
    <>
      <PageHeader title="Incidents" description="Server-side filtered queue of every reported incident." />

      <Card className="mb-6" bodyClassName="p-4">
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6"
          onSubmit={(e) => {
            e.preventDefault();
            update({ q: q.trim() || null });
          }}
        >
          <div className="sm:col-span-2">
            <Field label="Search reference or location">
              {(id) => <Input id={id} value={q} onChange={(e) => setQ(e.target.value)} placeholder="INC-… or street, landmark" maxLength={100} />}
            </Field>
          </div>
          <Field label="Scenario">
            {(id) => (
              <Select id={id} value={query.scenario ?? ""} onChange={(e) => update({ scenario: e.target.value || null })}>
                <option value="">All scenarios</option>
                {SCENARIOS.map((s) => <option key={s} value={s}>{scenarioLabel[s]}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Status">
            {(id) => (
              <Select id={id} value={query.status[0] ?? ""} onChange={(e) => update({ status: e.target.value ? [e.target.value] : null })}>
                <option value="">{query.status.length > 1 ? `${query.status.length} selected` : "Any status"}</option>
                {INCIDENT_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Priority">
            {(id) => (
              <Select id={id} value={query.priority.length === 1 ? query.priority[0] : ""} onChange={(e) => update({ priority: e.target.value ? [e.target.value] : null })}>
                <option value="">{query.priority.length > 1 ? query.priority.map(label).join(" + ") : "Any priority"}</option>
                {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
                <option value="UNASSIGNED">Unassigned</option>
              </Select>
            )}
          </Field>
          <Field label="Sort">
            {(id) => (
              <Select id={id} value={query.sort} onChange={(e) => update({ sort: e.target.value })}>
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
                <option value="priority">Priority</option>
                <option value="updated">Recently updated</option>
              </Select>
            )}
          </Field>
          <Field label="Reported from">
            {(id) => <Input id={id} type="date" value={query.from ?? ""} onChange={(e) => update({ from: e.target.value || null })} />}
          </Field>
          <Field label="Reported to">
            {(id) => <Input id={id} type="date" value={query.to ?? ""} onChange={(e) => update({ to: e.target.value || null })} />}
          </Field>
          <div className="flex items-end sm:col-span-2">
            <label className="flex items-center gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                checked={query.withdrawal_requested === true}
                onChange={(e) => update({ withdrawal_requested: e.target.checked ? "true" : null })}
              />
              Reporter asked to withdraw
            </label>
          </div>
          <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-2">
            <Button type="submit" variant="primary">Search</Button>
            {activeFilters && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setQ("");
                  router.replace(pathname);
                }}
              >
                Clear filters
              </Button>
            )}
          </div>
        </form>
      </Card>

      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingRows rows={8} />}
      {data && (
        <Card bodyClassName="p-0">
          {data.items.length === 0 ? (
            <div className="p-5">
              <EmptyState title={activeFilters ? "No incidents match these filters." : "No incidents have been reported yet."}>
                {activeFilters ? "Clear or change the filters to see more." : "Reports submitted by the public will appear here."}
              </EmptyState>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="border-b border-border text-left text-xs text-muted">
                  <tr>
                    <th scope="col" className="px-5 py-3 font-medium">Incident</th>
                    <th scope="col" className="px-3 py-3 font-medium">Status</th>
                    <th scope="col" className="px-3 py-3 font-medium">Priority</th>
                    <th scope="col" className="px-3 py-3 font-medium">Location</th>
                    <th scope="col" className="px-3 py-3 text-right font-medium">Affected</th>
                    <th scope="col" className="px-5 py-3 text-right font-medium">Reported</th>
                  </tr>
                </thead>
                <tbody className={loading ? "opacity-60" : undefined}>
                  {data.items.map((i) => (
                    <tr key={i.incident_id} className="border-b border-border last:border-0 hover:bg-surface-muted">
                      <td className="px-5 py-3">
                        <Link href={`/dm/incidents/${i.incident_id}`} className="font-mono text-xs text-info hover:underline">
                          {i.incident_ref}
                        </Link>
                        <p className="mt-0.5">{scenarioLabel[i.scenario]}</p>
                        <p className="text-xs text-muted">
                          {i.evidence_count} evidence · {i.active_dispatches} active dispatch{i.active_dispatches === 1 ? "" : "es"}
                          {i.canonical_incident_id && " · linked duplicate"}
                        </p>
                        {i.withdrawal_requested && <p className="mt-0.5 text-xs font-medium text-high">Reporter asked to withdraw</p>}
                      </td>
                      <td className="px-3 py-3"><StatusBadge status={i.status} /></td>
                      <td className="px-3 py-3"><PriorityBadge priority={i.verified_priority} /></td>
                      <td className="max-w-56 px-3 py-3">
                        <p className="truncate">{i.address_text ?? "—"}</p>
                        {i.latitude === null && <p className="text-xs text-medium">No coordinates</p>}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">{formatNumber(i.people_affected)}</td>
                      <td className="px-5 py-3 text-right text-xs text-muted tabular-nums">{timeAgo(i.submitted_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="border-t border-border px-5 py-3">
            <Pagination page={data.page} pages={data.pages} total={data.total} onPage={(p) => update({ page: String(p) })} />
          </div>
        </Card>
      )}
    </>
  );
}
