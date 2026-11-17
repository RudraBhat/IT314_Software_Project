"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/badges";
import { useAction } from "@/components/use-action";
import { Button, Card, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, useQuery } from "@/lib/api";
import { SCENARIOS, formatDateTime, formatMoney, formatNumber, scenarioLabel } from "@/lib/format";

type Oversight = {
  campaigns: {
    campaign_id: string;
    title: string;
    status: string;
    scenario: string | null;
    currency: string;
    target_amount: string | null;
    confirmed_amount: string;
    pending_amount: string;
    failed_amount: string;
    confirmed_count: number;
    pending_count: number;
    failed_count: number;
  }[];
  totals: { confirmed_amount: string; pending_amount: string; failed_amount: string };
  oldest_pending_at: string | null;
  failed_by_reason?: Record<string, { count: number; amount: string | number }>;
  pending_timeout_minutes?: number;
  is_sandbox?: boolean;
  definitions: Record<string, string>;
};

type Campaign = { campaign_id: string; title: string; purpose: string; scenario: string | null; status: string };

export default function CampaignsPage() {
  const { data, error, loading, reload } = useQuery<Oversight>("oversight/donations");
  const campaigns = useQuery<{ items: Campaign[] }>("campaigns");
  const { run, busy } = useAction();
  const [creating, setCreating] = useState(false);
  const [closing, setClosing] = useState<Campaign | null>(null);
  const [reason, setReason] = useState("");
  const refresh = () => { reload(); campaigns.reload(); };

  async function setStatus(c: Campaign, status: "ACTIVE" | "PAUSED") {
    const ok = await run(c.campaign_id, () => api(`campaigns/${c.campaign_id}`, { method: "PATCH", body: { status } }), status === "ACTIVE" ? "Campaign active" : "Campaign paused");
    if (ok !== undefined) refresh();
  }
  async function close() {
    if (!closing) return;
    const ok = await run("close", () => api(`campaigns/${closing.campaign_id}/closure`, { method: "POST", body: { reason } }), "Campaign closed to new donations");
    if (ok !== undefined) { setClosing(null); setReason(""); refresh(); }
  }

  return (
    <>
      <PageHeader title="Campaigns & donations" description="Campaign management and donation oversight. Payment states come only from the payment gateway and are read-only here."
        actions={<Button variant="primary" onClick={() => setCreating(true)}>New campaign</Button>} />
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingRows rows={3} />}
      {data && (
        <>
          {data.is_sandbox && (
            <div className="mb-4">
              <Notice tone="medium">
                ⚠️ SANDBOX payment gateway active: all campaigns and donation records are test simulations and no real money moved.
              </Notice>
            </div>
          )}
          <section className="mb-6 grid gap-4 sm:grid-cols-3" aria-label="Donation totals">
            {([["Confirmed", data.totals.confirmed_amount, "text-low", data.definitions.confirmed], ["Pending", data.totals.pending_amount, "text-medium", data.definitions.pending], ["Failed", data.totals.failed_amount, "text-muted", data.definitions.failed]] as const).map(([name, value, tone, def]) => (
              <div key={name} className="rounded-xl border border-border bg-surface p-4">
                <p className="text-xs font-medium text-muted">{name}</p>
                <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{formatMoney(value)}</p>
                <p className="mt-1 text-xs text-muted">{def}</p>
              </div>
            ))}
          </section>
          {data.failed_by_reason && Object.keys(data.failed_by_reason).length > 0 && (
            <div className="mb-6 rounded-xl border border-border bg-surface p-4 text-xs" aria-label="Failed donations breakdown">
              <p className="font-semibold text-muted uppercase tracking-wider mb-2">Failed Donations Breakdown</p>
              <div className="grid gap-2 sm:grid-cols-4">
                {Object.entries(data.failed_by_reason).map(([reason, stats]) => (
                  <div key={reason} className="rounded-lg border border-border/60 bg-surface-muted/50 p-2.5">
                    <p className="text-[11px] font-medium text-muted">
                      {reason === "ABANDONED"
                        ? "Abandoned / Cancelled"
                        : reason === "GATEWAY_DECLINED"
                        ? "Gateway Declined"
                        : reason === "EXPIRED"
                        ? "Expired Unpaid"
                        : "Other / Unclassified"}
                    </p>
                    <p className="mt-1 text-sm font-semibold tabular-nums text-foreground">
                      {formatMoney(stats.amount)} <span className="text-xs font-normal text-muted">({stats.count})</span>
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.oldest_pending_at && (
            <div className="mb-6">
              <Notice tone="medium">
                Oldest pending payment since {formatDateTime(data.oldest_pending_at)}; awaiting gateway reconciliation{data.pending_timeout_minutes ? ` (unpaid orders expire after ${data.pending_timeout_minutes} minutes)` : ""}.
              </Notice>
            </div>
          )}
        </>
      )}
      {campaigns.data && campaigns.data.items.length === 0 && <EmptyState title="No campaigns yet." />}
      <div className="grid gap-4 md:grid-cols-2">
        {campaigns.data?.items.map((c) => {
          const s = data?.campaigns.find((x) => x.campaign_id === c.campaign_id);
          const target = s?.target_amount ? Number(s.target_amount) : null;
          const confirmed = Number(s?.confirmed_amount ?? 0);
          return (
            <Card key={c.campaign_id} title={c.title} subtitle={c.scenario ? scenarioLabel[c.scenario] : "No scenario"} actions={<StatusBadge status={c.status} />}>
              <p className="text-sm text-muted">{c.purpose}</p>
              {s && (
                <div className="mt-3 text-sm">
                  {target && (
                    <div className="mb-2 h-2 rounded bg-surface-muted" aria-hidden><div className="h-2 rounded bg-low" style={{ width: `${Math.min(100, (confirmed / target) * 100)}%` }} /></div>
                  )}
                  <p><strong className="tabular-nums">{formatMoney(confirmed, s.currency)}</strong> confirmed ({formatNumber(s.confirmed_count)}){target && ` of ${formatMoney(target, s.currency)}`}</p>
                  <p className="text-xs text-muted">{formatMoney(s.pending_amount, s.currency)} pending ({s.pending_count}) · {formatMoney(s.failed_amount, s.currency)} failed ({s.failed_count})</p>
                </div>
              )}
              {c.status !== "CLOSED" && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {c.status !== "ACTIVE" && <Button size="sm" busy={busy === c.campaign_id} onClick={() => setStatus(c, "ACTIVE")}>Activate</Button>}
                  {c.status === "ACTIVE" && <Button size="sm" busy={busy === c.campaign_id} onClick={() => setStatus(c, "PAUSED")}>Pause</Button>}
                  <Button size="sm" variant="ghost" onClick={() => setClosing(c)}>Close…</Button>
                </div>
              )}
            </Card>
          );
        })}
      </div>
      {creating && <CampaignForm onClose={() => setCreating(false)} onDone={() => { setCreating(false); refresh(); }} />}
      <Dialog open={closing !== null} onClose={() => setClosing(null)} title={`Close “${closing?.title}”?`}
        footer={<><Button onClick={() => setClosing(null)}>Cancel</Button><Button variant="danger" disabled={reason.trim().length < 3} busy={busy === "close"} onClick={close}>Close campaign</Button></>}>
        <p className="mb-3 text-sm">The campaign stops accepting new donations. Existing records are kept.</p>
        <Field label="Reason">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      </Dialog>
    </>
  );
}

function CampaignForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ title: "", purpose: "", scenario: "", target: "", activate: false });
  const valid = f.title.trim().length >= 5 && f.purpose.trim().length >= 10 && f.scenario;
  async function save() {
    const ok = await run("save", () => api("campaigns", { method: "POST", body: { title: f.title, purpose: f.purpose, scenario: f.scenario, target_amount: f.target ? Number(f.target) : undefined, activate: f.activate } }), "Campaign created");
    if (ok !== undefined) onDone();
  }
  return (
    <Dialog open onClose={onClose} title="New donation campaign" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid} busy={busy === "save"} onClick={save}>Create</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2"><Field label="Title">{(id) => <Input id={id} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} maxLength={200} />}</Field></div>
        <Field label="Scenario">
          {(id) => (
            <Select id={id} value={f.scenario} onChange={(e) => setF({ ...f, scenario: e.target.value })}>
              <option value="">Select scenario</option>
              {SCENARIOS.map((s) => <option key={s} value={s}>{scenarioLabel[s]}</option>)}
            </Select>
          )}
        </Field>
        <Field label="Target (INR, optional)">{(id) => <Input id={id} type="number" min={0} value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} />}</Field>
        <div className="sm:col-span-2"><Field label="Purpose">{(id) => <Textarea id={id} value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} maxLength={4000} />}</Field></div>
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={f.activate} onChange={(e) => setF({ ...f, activate: e.target.checked })} /> Activate immediately</label>
      </div>
    </Dialog>
  );
}
