"use client";

import { useState } from "react";

import { BarList, ColumnSeries } from "@/components/charts";
import { Button, Card, ErrorState, Field, Input, LoadingRows, PageHeader, Select } from "@/components/ui";
import { useQuery } from "@/lib/api";
import { SCENARIOS, formatDateTime, formatDuration, formatMoney, formatNumber, label, scenarioLabel, timeAgo } from "@/lib/format";

type Analytics = {
  generated_at: string;
  data_fresh_as_of: string | null;
  incidents: {
    by_scenario_status: { scenario: string; status: string; n: number }[];
    by_priority: { priority: string; n: number }[];
    per_day: { day: string; n: number }[];
    timings: { verified: number; median_seconds_to_verify: number | null; closed: number; median_seconds_to_close: number | null };
  };
  dispatches: { status: string; priority: string; n: number; avg_ack_seconds: number | null }[];
  ai_recommendations: { status: string; human_action: string; in_scope: number; out_of_scope: number }[];
  donations: { confirmed: string; pending: string; failed: string };
  aid: { status: string; contributions: number }[];
  resources: { type: string; status: string; n: number }[];
  definitions: Record<string, string>;
};

const PRIORITY_BAR: Record<string, string> = { CRITICAL: "bg-critical", HIGH: "bg-high", MEDIUM: "bg-medium", LOW: "bg-low", UNASSIGNED: "bg-muted" };

function sum<T>(rows: T[], pick: (r: T) => number) {
  return rows.reduce((n, r) => n + pick(r), 0);
}

/** Aggregated figures only (no reporter data); opens in any spreadsheet. */
function exportCsv(d: Analytics) {
  const rows: (string | number)[][] = [["section", "key", "detail", "value"]];
  d.incidents.by_scenario_status.forEach((r) => rows.push(["incidents", r.scenario, r.status, r.n]));
  d.incidents.by_priority.forEach((r) => rows.push(["priority", r.priority, "", r.n]));
  d.incidents.per_day.forEach((r) => rows.push(["per_day", r.day, "", r.n]));
  d.dispatches.forEach((r) => rows.push(["dispatches", r.status, r.priority, r.n]));
  d.resources.forEach((r) => rows.push(["resources", r.type, r.status, r.n]));
  const cell = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
  const blob = new Blob([rows.map((r) => r.map(cell).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `drch-analytics-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function AnalyticsPage() {
  const [scenario, setScenario] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const { data, error, loading, reload } = useQuery<Analytics>("analytics", { scenario: scenario || undefined, from: from || undefined, to: to || undefined });

  return (
    <>
      <PageHeader
        title="Analytics"
        description={data ? `Generated ${formatDateTime(data.generated_at)}${data.data_fresh_as_of ? ` · latest incident change ${timeAgo(data.data_fresh_as_of)}` : ""}` : "Operational and contribution analytics"}
        actions={
          <>
            {data && <Button onClick={() => exportCsv(data)}>Export CSV</Button>}
            <Button onClick={reload} busy={loading && !!data}>Refresh</Button>
          </>
        }
      />
      <div className="mb-6 flex flex-wrap items-end gap-3">
        <Field label="Scenario">
          {(id) => (
            <Select id={id} value={scenario} onChange={(e) => setScenario(e.target.value)} className="w-48">
              <option value="">All scenarios</option>
              {SCENARIOS.map((s) => <option key={s} value={s}>{scenarioLabel[s]}</option>)}
            </Select>
          )}
        </Field>
        <Field label="From">{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
        <Field label="To">{(id) => <Input id={id} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
        {(scenario || from || to) && <Button variant="ghost" onClick={() => { setScenario(""); setFrom(""); setTo(""); }}>Clear</Button>}
      </div>
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingRows rows={6} />}
      {data && <Body d={data} />}
    </>
  );
}

function Body({ d }: { d: Analytics }) {
  const total = sum(d.incidents.by_scenario_status, (r) => r.n);
  const byScenario = SCENARIOS.map((s) => ({
    label: scenarioLabel[s],
    value: sum(d.incidents.by_scenario_status.filter((r) => r.scenario === s), (r) => r.n),
  }));
  const statuses = [...new Set(d.incidents.by_scenario_status.map((r) => r.status))];
  const outOfScope = sum(d.ai_recommendations, (r) => r.out_of_scope);
  const inScope = sum(d.ai_recommendations, (r) => r.in_scope);
  const ack = d.dispatches.filter((r) => r.avg_ack_seconds !== null);
  const ackWeighted = ack.length ? sum(ack, (r) => (r.avg_ack_seconds ?? 0) * r.n) / sum(ack, (r) => r.n) : null;

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="Headline figures">
        {[
          ["Incidents in range", formatNumber(total)],
          ["Median time to verify", formatDuration(d.incidents.timings.median_seconds_to_verify)],
          ["Median time to close", formatDuration(d.incidents.timings.median_seconds_to_close)],
          ["Avg. dispatch acknowledgement", formatDuration(ackWeighted)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-xl border border-border bg-surface p-4">
            <p className="text-xs font-medium text-muted">{k}</p>
            <p className="mt-1.5 text-2xl font-semibold tabular-nums">{v}</p>
          </div>
        ))}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Incidents per day" subtitle="By submission date">
          <ColumnSeries points={d.incidents.per_day.map((p) => ({ label: p.day, value: p.n }))} />
        </Card>
        <Card title="By human-assigned priority" subtitle={d.definitions.UNASSIGNED}>
          <BarList rows={d.incidents.by_priority.map((p) => ({ label: label(p.priority), value: p.n, barClass: PRIORITY_BAR[p.priority] }))} />
        </Card>
      </div>

      <Card title="Incidents by scenario and status" subtitle={`${formatNumber(total)} incidents`}>
        <div className="grid gap-6 lg:grid-cols-3">
          <BarList rows={byScenario} />
          <div className="overflow-x-auto lg:col-span-2">
            <table className="w-full min-w-[480px] text-sm">
              <caption className="sr-only">Incident counts by scenario and status</caption>
              <thead className="text-left text-xs text-muted">
                <tr><th scope="col" className="py-2 pr-3 font-medium">Scenario</th>{statuses.map((s) => <th key={s} scope="col" className="px-2 py-2 text-right font-medium">{label(s)}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-border">
                {SCENARIOS.map((sc) => (
                  <tr key={sc}>
                    <th scope="row" className="py-2 pr-3 text-left font-normal">{scenarioLabel[sc]}</th>
                    {statuses.map((st) => <td key={st} className="px-2 py-2 text-right tabular-nums">{formatNumber(d.incidents.by_scenario_status.find((r) => r.scenario === sc && r.status === st)?.n ?? 0)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Dispatch outcomes" subtitle={d.definitions.avg_ack_seconds}>
          <BarList
            barClass="bg-high"
            emptyText="No dispatches in range."
            rows={["REQUESTED", "ACKNOWLEDGED", "DISPATCHED", "COMPLETED", "REJECTED", "FAILED"].map((s) => ({
              label: label(s),
              value: sum(d.dispatches.filter((r) => r.status === s), (r) => r.n),
            })).filter((r) => r.value > 0)}
          />
        </Card>
        <Card title="AI recommendations" subtitle={d.definitions.out_of_scope}>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-xs text-muted">In scope</dt><dd className="text-xl font-semibold tabular-nums">{formatNumber(inScope)}</dd></div>
            <div><dt className="text-xs text-muted">Out of scope (counted separately)</dt><dd className="text-xl font-semibold tabular-nums">{formatNumber(outOfScope)}</dd></div>
          </dl>
          <table className="mt-4 w-full text-sm">
            <caption className="sr-only">AI recommendations by status and human decision</caption>
            <thead className="text-left text-xs text-muted"><tr><th scope="col" className="py-1 font-medium">AI status</th><th scope="col" className="py-1 font-medium">Human decision</th><th scope="col" className="py-1 text-right font-medium">Count</th></tr></thead>
            <tbody className="divide-y divide-border">
              {d.ai_recommendations.map((r) => (
                <tr key={`${r.status}-${r.human_action}`}><td className="py-1.5">{label(r.status)}</td><td>{label(r.human_action)}</td><td className="text-right tabular-nums">{r.in_scope + r.out_of_scope}</td></tr>
              ))}
              {d.ai_recommendations.length === 0 && <tr><td colSpan={3} className="py-2 text-muted">No AI recommendations recorded.</td></tr>}
            </tbody>
          </table>
        </Card>
      </div>

      <Card title="Contributions & resources" subtitle={d.definitions.scope}>
        <div className="grid gap-6 md:grid-cols-3">
          <div>
            <p className="mb-2 text-xs font-medium text-muted">Donations</p>
            <dl className="space-y-1 text-sm">
              <div className="flex justify-between"><dt>Confirmed</dt><dd className="tabular-nums font-medium">{formatMoney(d.donations.confirmed)}</dd></div>
              <div className="flex justify-between"><dt>Pending</dt><dd className="tabular-nums">{formatMoney(d.donations.pending)}</dd></div>
              <div className="flex justify-between"><dt>Failed</dt><dd className="tabular-nums text-muted">{formatMoney(d.donations.failed)}</dd></div>
            </dl>
            <p className="mt-2 text-xs text-muted">{d.definitions.donations}</p>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-muted">Physical aid contributions</p>
            <BarList barClass="bg-low" emptyText="No aid registered." rows={d.aid.map((a) => ({ label: label(a.status), value: Number(a.contributions) }))} />
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-muted">Resources by status</p>
            <BarList barClass="bg-info" emptyText="No resources." rows={[...new Set(d.resources.map((r) => r.status))].map((s) => ({ label: label(s), value: sum(d.resources.filter((r) => r.status === s), (r) => r.n) }))} />
          </div>
        </div>
      </Card>
    </div>
  );
}
