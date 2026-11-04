"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { PriorityBadge, StatusBadge } from "@/components/badges";
import { useAction } from "@/components/use-action";
import { Button, Card, Dialog, EmptyState, Field, Input, Notice, Select, Textarea } from "@/components/ui";
import { api, newIdempotencyKey, useQuery } from "@/lib/api";
import { PRIORITIES, formatDateTime, label, timeAgo } from "@/lib/format";
import type { Agency, Paged, Resource } from "@/lib/types";

import { useStaff } from "../../shell";
import type { IncidentDetail } from "./types";

export function DispatchPanel({ incident, reload }: { incident: IncidentDetail; reload: () => void }) {
  const { can } = useStaff();
  const [creating, setCreating] = useState(false);
  const canDispatch = incident.allowed_actions.dispatch;

  return (
    <Card
      title="Dispatches"
      subtitle="States advance only when an acknowledgement or report is recorded."
      actions={
        canDispatch ? (
          <Button size="sm" variant="primary" onClick={() => setCreating(true)}>New dispatch…</Button>
        ) : incident.status === "VERIFIED" || incident.status === "DISPATCHED" ? (
          !can("DISPATCH") && <span className="text-xs text-muted">Requires the dispatch permission</span>
        ) : (
          <span className="text-xs text-muted">Available after verification</span>
        )
      }
      bodyClassName="p-0"
    >
      {incident.dispatches.length === 0 ? (
        <div className="p-5"><EmptyState title="No dispatches for this incident." /></div>
      ) : (
        <ul className="divide-y divide-border">
          {incident.dispatches.map((d) => (
            <li key={d.dispatch_id}>
              <Link href={`/dm/dispatches/${d.dispatch_id}`} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm hover:bg-surface-muted">
                <span className="font-mono text-xs text-info">{d.dispatch_ref}</span>
                <StatusBadge status={d.status} />
                <PriorityBadge priority={d.priority} />
                <span className="min-w-0 flex-1 truncate">{d.agency_name}</span>
                <span className="text-xs text-muted">
                  {d.acknowledged_at ? `Ack ${timeAgo(d.acknowledged_at)} by ${d.acknowledged_by}` : `Requested ${timeAgo(d.created_at)}`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {creating && (
        <CreateDispatch
          incident={incident}
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            reload();
          }}
        />
      )}
    </Card>
  );
}

function CreateDispatch({ incident, onClose, onDone }: { incident: IncidentDetail; onClose: () => void; onDone: () => void }) {
  const agencies = useQuery<{ items: Agency[] }>("agency-contacts");
  const resources = useQuery<Paged<Resource>>("resources", { available_only: true, limit: 100 });
  const recommendations = useQuery<{
    recommendations: Array<{
      resource_id: string;
      team_name: string;
      agency: string | null;
      distance_km: number | null;
      capability_match: string[];
      rank: number;
      reasons: string;
    }>;
  }>(`incidents/${incident.incident_id}/team-recommendations`);
  const { run, busy } = useAction();
  const [agencyId, setAgencyId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [priority, setPriority] = useState(incident.verified_priority ?? "");
  const [lines, setLines] = useState<Record<string, string>>({});
  // One key per dialog: a retry after a network failure cannot create a second order.
  const idempotencyKey = useMemo(() => newIdempotencyKey(), []);

  const chosen = Object.entries(lines).filter(([, q]) => Number(q) > 0);
  const overBooked = chosen.some(([id, q]) => {
    const r = resources.data?.items.find((x) => x.resource_id === id);
    return r ? Number(q) > Number(r.quantity_available) : false;
  });
  const valid = agencyId && instructions.trim().length >= 5 && chosen.length > 0 && !overBooked;

  async function submit() {
    const ok = await run(
      "create",
      () =>
        api("incidents/" + incident.incident_id + "/dispatches", {
          method: "POST",
          idempotencyKey,
          body: {
            receiving_agency_id: agencyId,
            instructions,
            priority: priority || undefined,
            resources: chosen.map(([resource_id, quantity]) => ({ resource_id, quantity: Number(quantity) })),
          },
        }),
      "Dispatch order created and queued. Relay it to the agency and record their acknowledgement.",
    );
    if (ok !== undefined) onDone();
  }

  return (
    <Dialog
      open
      wide
      onClose={onClose}
      title={`Dispatch for ${incident.incident_ref}`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!valid} busy={busy === "create"} onClick={submit}>
            Create dispatch order
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Receiving agency">
            {(id) => (
              <Select id={id} value={agencyId} onChange={(e) => setAgencyId(e.target.value)}>
                <option value="">{agencies.loading ? "Loading…" : "Select agency"}</option>
                {agencies.data?.items.filter((a) => a.is_active).map((a) => (
                  <option key={a.agency_id} value={a.agency_id}>{a.name}{a.contact_phone ? ` (${a.contact_phone})` : ""}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Priority" hint="Defaults to the incident's priority.">
            {(id) => (
              <Select id={id} value={priority} onChange={(e) => setPriority(e.target.value)}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
              </Select>
            )}
          </Field>
        </div>
        <Field label="Operational instructions">
          {(id) => <Textarea id={id} rows={4} value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={4000} />}
        </Field>

        {/* Suggested Teams (AI / Rule Recommendation) */}
        {recommendations.data?.recommendations && recommendations.data.recommendations.length > 0 && (
          <div className="rounded-xl border border-sky-500/30 bg-sky-500/5 p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-sky-400 uppercase tracking-wider">Suggested teams</span>
              <span className="text-[11px] text-muted italic">Advisory — you confirm the dispatch</span>
            </div>
            <ul className="divide-y divide-border/60 text-xs">
              {recommendations.data.recommendations.map((rec) => {
                const resourceAvailable = resources.data?.items.find((r) => r.resource_id === rec.resource_id);
                const isSelected = Number(lines[rec.resource_id] ?? 0) > 0;
                return (
                  <li key={rec.resource_id} className="flex items-center justify-between py-2 gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-foreground">{rec.team_name}</span>
                        {rec.distance_km !== null && (
                          <span className="text-[10px] font-mono text-muted">{rec.distance_km.toFixed(1)} km</span>
                        )}
                        {rec.agency && <span className="text-[10px] text-muted">({rec.agency})</span>}
                      </div>
                      <p className="text-[11px] text-muted truncate">{rec.reasons}</p>
                    </div>
                    <Button
                      size="sm"
                      variant={isSelected ? "secondary" : "primary"}
                      onClick={() => {
                        setLines((l) => ({ ...l, [rec.resource_id]: "1" }));
                        if (!agencyId && resourceAvailable?.agency_id) {
                          setAgencyId(resourceAvailable.agency_id);
                        }
                      }}
                      disabled={!resourceAvailable || Number(resourceAvailable.quantity_available) <= 0}
                    >
                      {isSelected ? "Selected" : "Add to dispatch"}
                    </Button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <div>
          <p className="mb-2 text-xs font-medium text-muted">Resources to assign (available now)</p>
          {resources.error && <Notice tone="critical">{resources.error}</Notice>}
          {resources.data && resources.data.items.length === 0 && (
            <EmptyState title="No resources are available.">Add or free up resources on the Resources page first.</EmptyState>
          )}
          <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-lg border border-border">
            {resources.data?.items.map((r) => (
              <li key={r.resource_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{r.name}</p>
                  <p className="text-xs text-muted">{label(r.type)} · {r.agency_name ?? "No agency"} · {Number(r.quantity_available)} available</p>
                </div>
                <Input
                  aria-label={`Quantity of ${r.name}`}
                  type="number"
                  min={0}
                  max={Number(r.quantity_available)}
                  step="any"
                  className="w-24"
                  value={lines[r.resource_id] ?? ""}
                  onChange={(e) => setLines((l) => ({ ...l, [r.resource_id]: e.target.value }))}
                  placeholder="0"
                />
              </li>
            ))}
          </ul>
          {overBooked && <p className="mt-2 text-xs text-critical">A quantity exceeds what is available.</p>}
        </div>
        <Notice tone="info">
          No messaging integration is configured. The order is queued for the agency; it shows as <strong>Requested</strong> until
          you record their acknowledgement.
        </Notice>
      </div>
    </Dialog>
  );
}

export function MessagesPanel({ incident, reload }: { incident: IncidentDetail; reload: () => void }) {
  const [composing, setComposing] = useState(false);
  return (
    <Card
      title="Agency messages"
      subtitle="Agencies have no accounts; staff record their responses."
      actions={incident.allowed_actions.message_agencies && <Button size="sm" onClick={() => setComposing(true)}>New message…</Button>}
      bodyClassName="p-0"
    >
      {incident.agency_messages.length === 0 ? (
        <div className="p-5"><EmptyState title="No agency messages yet." /></div>
      ) : (
        <ul className="divide-y divide-border">
          {incident.agency_messages.map((m) => (
            <MessageRow key={m.message_id} m={m} reload={reload} />
          ))}
        </ul>
      )}
      {composing && <Compose incident={incident} onClose={() => setComposing(false)} onDone={() => { setComposing(false); reload(); }} />}
    </Card>
  );
}

function MessageRow({ m, reload }: { m: IncidentDetail["agency_messages"][number]; reload: () => void }) {
  const { run, busy } = useAction();
  const [outcome, setOutcome] = useState<"ACKNOWLEDGED" | "FAILED" | null>(null);
  const [note, setNote] = useState("");
  const open = !["ACKNOWLEDGED", "FAILED"].includes(m.status);

  async function record() {
    const ok = await run("evt", () => api(`agency-messages/${m.message_id}/events`, { method: "POST", body: { outcome, note } }), "Response recorded");
    if (ok !== undefined) {
      setOutcome(null);
      reload();
    }
  }

  return (
    <li className="px-5 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{m.agency_name}</span>
        <StatusBadge status={m.status} />
        <span className="text-xs text-muted">{formatDateTime(m.created_at)} · {m.sender_name}</span>
      </div>
      {m.subject && <p className="mt-1 font-medium">{m.subject}</p>}
      <p className="mt-0.5 whitespace-pre-wrap text-muted">{m.body}</p>
      {open && (
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={() => setOutcome("ACKNOWLEDGED")}>Record acknowledgement…</Button>
          <Button size="sm" variant="ghost" onClick={() => setOutcome("FAILED")}>Record failure…</Button>
        </div>
      )}
      <Dialog
        open={outcome !== null}
        onClose={() => setOutcome(null)}
        title={outcome === "FAILED" ? "Record delivery failure" : "Record acknowledgement"}
        footer={
          <>
            <Button onClick={() => setOutcome(null)}>Cancel</Button>
            <Button variant="primary" disabled={note.trim().length < 3} busy={busy === "evt"} onClick={record}>Save</Button>
          </>
        }
      >
        <Field label={outcome === "FAILED" ? "What failed" : "Who confirmed, and how"} hint="Stored with your name as the recorder.">
          {(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />}
        </Field>
      </Dialog>
    </li>
  );
}

function Compose({ incident, onClose, onDone }: { incident: IncidentDetail; onClose: () => void; onDone: () => void }) {
  const agencies = useQuery<{ items: Agency[] }>("agency-contacts");
  const { run, busy } = useAction();
  const [selected, setSelected] = useState<string[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  async function send() {
    const ok = await run(
      "send",
      () => api(`incidents/${incident.incident_id}/agency-messages`, { method: "POST", body: { recipient_agency_ids: selected, subject, body } }),
      "Message queued for the selected agencies",
    );
    if (ok !== undefined) onDone();
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Message agencies"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!selected.length || subject.trim().length < 3 || body.trim().length < 3} busy={busy === "send"} onClick={send}>
            Queue message
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-muted">Recipients</legend>
          <div className="space-y-1">
            {agencies.data?.items.filter((a) => a.is_active).map((a) => (
              <label key={a.agency_id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(a.agency_id)}
                  onChange={(e) => setSelected((s) => (e.target.checked ? [...s, a.agency_id] : s.filter((x) => x !== a.agency_id)))}
                />
                {a.name}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Subject">{(id) => <Input id={id} value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} />}</Field>
        <Field label="Message">{(id) => <Textarea id={id} rows={4} value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} />}</Field>
      </div>
    </Dialog>
  );
}
