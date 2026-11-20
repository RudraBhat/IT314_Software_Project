"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { PriorityBadge, StatusBadge } from "@/components/badges";
import { useAction } from "@/components/use-action";
import { Badge, Button, Card, Dialog, EmptyState, Field, Input, Notice, Select, Textarea, cx } from "@/components/ui";
import { api, newIdempotencyKey, useQuery } from "@/lib/api";
import { AGENCY_TYPES, AGENCY_TYPE_ICON, AGENCY_TYPE_LABEL, PRIORITIES, RESOURCE_ICON, formatDateTime, label, timeAgo } from "@/lib/format";
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

type Recommendation = {
  resource_id: string;
  team_name: string;
  agency: string | null;
  distance_km: number | null;
  capability_match: string[];
  secondary_match?: string[];
  rank: number;
  reasons: string;
  score?: number;
  matched_count?: number;
  is_fallback?: boolean;
};

/** Small numbered heading for each part of the dispatch form. */
function StepTitle({ n, children, aside }: { n: number; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <span className="flex size-6 items-center justify-center rounded-full bg-[#0c4a75] text-xs font-bold text-white">{n}</span>
        {children}
      </h3>
      {aside}
    </div>
  );
}

function CreateDispatch({ incident, onClose, onDone }: { incident: IncidentDetail; onClose: () => void; onDone: () => void }) {
  const agencies = useQuery<{ items: Agency[] }>("agency-contacts");
  const resources = useQuery<Paged<Resource>>("resources", { available_only: true, limit: 100 });
  const recommendations = useQuery<{
    recommendations: Recommendation[];
    unavailable?: boolean;
    unavailable_reason?: string | null;
  }>(`incidents/${incident.incident_id}/team-recommendations`);
  // A failed request or a failed spatial query both mean "no advice": the dispatcher allocates manually.
  const recommendationsUnavailable = Boolean(recommendations.error || recommendations.data?.unavailable);
  const { run, busy } = useAction();
  const [agencyId, setAgencyId] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [allResources, setAllResources] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [priority, setPriority] = useState(incident.verified_priority ?? "");
  const [lines, setLines] = useState<Record<string, string>>({});
  // One key per dialog: a retry after a network failure cannot create a second order.
  const idempotencyKey = useMemo(() => newIdempotencyKey(), []);

  const activeAgencies = useMemo(() => (agencies.data?.items ?? []).filter((a) => a.is_active), [agencies.data]);
  const agencyById = useMemo(() => new Map(activeAgencies.map((a) => [a.agency_id, a])), [activeAgencies]);
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const a of activeAgencies) counts[a.agency_type ?? "OTHER"] = (counts[a.agency_type ?? "OTHER"] ?? 0) + 1;
    return counts;
  }, [activeAgencies]);
  const shownAgencies = typeFilter === "ALL" ? activeAgencies : activeAgencies.filter((a) => (a.agency_type ?? "OTHER") === typeFilter);
  const chosenAgency = agencyById.get(agencyId);

  // Resources follow the chosen agency by default; "all agencies" lets a dispatcher send mutual aid.
  const availableResources = resources.data?.items ?? [];
  const shownResources = availableResources.filter((r) => {
    if (agencyId && !allResources) return r.agency_id === agencyId;
    if (typeFilter !== "ALL" && !allResources) return (agencyById.get(r.agency_id ?? "")?.agency_type ?? "OTHER") === typeFilter;
    return true;
  });

  const quantity = (id: string) => Number(lines[id] ?? 0) || 0;
  const setQuantity = (id: string, value: number, max: number) =>
    setLines((l) => ({ ...l, [id]: String(Math.max(0, Math.min(max, value))) }));
  const chosen = Object.entries(lines).filter(([, q]) => Number(q) > 0);
  const overBooked = chosen.some(([id, q]) => {
    const r = availableResources.find((x) => x.resource_id === id);
    return r ? Number(q) > Number(r.quantity_available) : false;
  });
  const missing = [
    !agencyId && "choose the receiving agency",
    chosen.length === 0 && "add at least one resource",
    instructions.trim().length < 5 && "write instructions (5+ characters)",
  ].filter(Boolean) as string[];
  const valid = missing.length === 0 && !overBooked;

  function pickAgency(id: string) {
    setAgencyId(id);
    setAllResources(false);
  }

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
            resources: chosen.map(([resource_id, q]) => ({ resource_id, quantity: Number(q) })),
          },
        }),
      "Dispatch order created. Contact the agency, then record their response on the dispatch page.",
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
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted">
            {valid
              ? `${chosen.length} resource${chosen.length === 1 ? "" : "s"} to ${chosenAgency?.name ?? "the agency"}`
              : overBooked
                ? "A quantity is more than what is available."
                : `To continue: ${missing.join(", ")}.`}
          </p>
          <div className="flex gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!valid} busy={busy === "create"} onClick={submit}>
              Create dispatch order
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        {/* Receiving agency, filtered by type */}
        <section>
          <StepTitle n={1}>Receiving agency</StepTitle>
          <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Agency type">
            {["ALL", ...AGENCY_TYPES, ...(typeCounts.OTHER ? ["OTHER"] : [])].map((t) => {
              const count = t === "ALL" ? activeAgencies.length : typeCounts[t] ?? 0;
              if (t !== "ALL" && count === 0) return null;
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTypeFilter(t)}
                  aria-pressed={typeFilter === t}
                  className={cx(
                    "rounded-full border px-3 py-1 text-xs font-semibold transition",
                    typeFilter === t ? "border-[#0c4a75] bg-[#0c4a75] text-white" : "border-border bg-surface text-foreground/80 hover:bg-surface-muted",
                  )}
                >
                  {t === "ALL" ? "All" : `${AGENCY_TYPE_ICON[t] ?? "🏢"} ${AGENCY_TYPE_LABEL[t] ?? "Other"}`}
                  <span className="ml-1 opacity-70">{count}</span>
                </button>
              );
            })}
          </div>
          {agencies.loading && !agencies.data && <p className="text-xs text-muted">Loading agencies…</p>}
          {agencies.error && <Notice tone="critical">{agencies.error}</Notice>}
          <div className="grid max-h-56 gap-2 overflow-y-auto sm:grid-cols-2">
            {shownAgencies.map((a) => {
              const selected = agencyId === a.agency_id;
              return (
                <button
                  key={a.agency_id}
                  type="button"
                  onClick={() => pickAgency(a.agency_id)}
                  aria-pressed={selected}
                  className={cx(
                    "flex items-start gap-3 rounded-xl border p-3 text-left transition",
                    selected ? "border-sky-500 bg-sky-50 ring-2 ring-sky-200" : "border-border bg-surface hover:border-sky-300 hover:bg-surface-muted",
                  )}
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-lg" aria-hidden>
                    {AGENCY_TYPE_ICON[a.agency_type ?? ""] ?? "🏢"}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-foreground">{a.name}</span>
                    <span className="block text-xs text-muted">
                      {AGENCY_TYPE_LABEL[a.agency_type ?? ""] ?? "Agency"}
                      {a.contact_phone ? ` · ${a.contact_phone}` : ""}
                    </span>
                  </span>
                  {selected && <span className="text-sm font-bold text-sky-700" aria-hidden>✓</span>}
                </button>
              );
            })}
            {agencies.data && shownAgencies.length === 0 && <p className="text-xs text-muted">No active agencies of this type.</p>}
          </div>
        </section>

        {/* Suggested teams (advisory) */}
        {recommendationsUnavailable && (
          <Notice tone="high">
            Recommendations unavailable — assign teams manually.
            {recommendations.data?.unavailable_reason ? ` ${recommendations.data.unavailable_reason}` : ""}
          </Notice>
        )}
        {!recommendationsUnavailable && recommendations.data && recommendations.data.recommendations.length > 0 && (
          <section className="rounded-xl border border-sky-200 bg-sky-50/60 p-3.5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-sky-800">Suggested teams</span>
              <span className="text-[11px] italic text-muted">Advisory — you confirm the dispatch</span>
            </div>
            <ul className="space-y-2">
              {recommendations.data.recommendations.map((rec) => {
                const available = availableResources.find((r) => r.resource_id === rec.resource_id);
                const isSelected = quantity(rec.resource_id) > 0;
                return (
                  <li key={rec.resource_id} className="flex items-center gap-3 rounded-lg bg-surface p-2.5 text-xs ring-1 ring-border">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-foreground">{rec.team_name}</span>
                        {rec.distance_km !== null && <Badge tone="info">{rec.distance_km.toFixed(1)} km</Badge>}
                        {rec.agency && <span className="text-muted">{rec.agency}</span>}
                        {rec.is_fallback && <Badge tone="medium">Offline roster — not live availability</Badge>}
                      </div>
                      <p className="mt-0.5 truncate text-muted">{rec.reasons}</p>
                    </div>
                    <Button
                      size="sm"
                      variant={isSelected ? "secondary" : "primary"}
                      onClick={() => {
                        setLines((l) => ({ ...l, [rec.resource_id]: l[rec.resource_id] && Number(l[rec.resource_id]) > 0 ? l[rec.resource_id] : "1" }));
                        if (!agencyId && available?.agency_id) pickAgency(available.agency_id);
                      }}
                      disabled={!available || Number(available.quantity_available) <= 0}
                    >
                      {isSelected ? "✓ Added" : "Add"}
                    </Button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* Resources */}
        <section>
          <StepTitle
            n={2}
            aside={
              (agencyId || typeFilter !== "ALL") && (
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  <input type="checkbox" checked={allResources} onChange={(e) => setAllResources(e.target.checked)} className="size-4 accent-sky-600" />
                  Show every agency&apos;s resources
                </label>
              )
            }
          >
            Resources to send
            <span className="text-xs font-normal text-muted">
              {agencyId && !allResources ? `from ${chosenAgency?.name ?? "this agency"}` : "available now"}
            </span>
          </StepTitle>
          {resources.error && <Notice tone="critical">{resources.error}</Notice>}
          {resources.loading && !resources.data && <p className="text-xs text-muted">Loading resources…</p>}
          {resources.data && shownResources.length === 0 && (
            <EmptyState title="No available resources here.">
              {agencyId && !allResources ? "Tick “Show every agency’s resources” to send mutual aid, or free some up on the Resources page." : "Add or free up resources on the Resources page first."}
            </EmptyState>
          )}
          {shownResources.length > 0 && (
            <ul className="max-h-72 space-y-2 overflow-y-auto">
              {shownResources.map((r) => {
                const max = Number(r.quantity_available);
                const q = quantity(r.resource_id);
                return (
                  <li
                    key={r.resource_id}
                    className={cx(
                      "flex items-center gap-3 rounded-xl border p-3 transition",
                      q > 0 ? "border-sky-400 bg-sky-50/70" : "border-border bg-surface",
                    )}
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-lg" aria-hidden>
                      {RESOURCE_ICON[r.type] ?? "📦"}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-foreground">{r.name}</p>
                      <p className="truncate text-xs text-muted">
                        {label(r.type)} · {r.agency_name ?? "No agency"}
                      </p>
                    </div>
                    <Badge tone={max > 0 ? "low" : "neutral"}>{max} available</Badge>
                    {/* Fixed-width stepper so the row never squeezes the name */}
                    <div className="flex shrink-0 items-center overflow-hidden rounded-lg border border-border bg-surface">
                      <button
                        type="button"
                        className="h-9 w-9 text-lg font-semibold text-muted hover:bg-surface-muted disabled:opacity-40"
                        onClick={() => setQuantity(r.resource_id, q - 1, max)}
                        disabled={q <= 0}
                        aria-label={`One less ${r.name}`}
                      >
                        −
                      </button>
                      <input
                        aria-label={`Quantity of ${r.name}`}
                        type="number"
                        inputMode="numeric"
                        min={0}
                        max={max}
                        value={lines[r.resource_id] ?? ""}
                        placeholder="0"
                        onChange={(e) => setLines((l) => ({ ...l, [r.resource_id]: e.target.value }))}
                        className="h-9 w-12 border-x border-border bg-transparent text-center text-sm [appearance:textfield] focus:outline-none [&::-webkit-inner-spin-button]:appearance-none"
                      />
                      <button
                        type="button"
                        className="h-9 w-9 text-lg font-semibold text-muted hover:bg-surface-muted disabled:opacity-40"
                        onClick={() => setQuantity(r.resource_id, q + 1, max)}
                        disabled={q >= max}
                        aria-label={`One more ${r.name}`}
                      >
                        +
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {overBooked && <p className="mt-2 text-xs text-critical">A quantity exceeds what is available.</p>}
        </section>

        {/* Priority and instructions */}
        <section>
          <StepTitle n={3}>Orders</StepTitle>
          <div className="grid gap-3 sm:grid-cols-[180px_1fr]">
            <Field label="Priority" hint="Defaults to the incident's.">
              {(id) => (
                <Select id={id} value={priority} onChange={(e) => setPriority(e.target.value)}>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Operational instructions" hint="What the team should do, where to report and any hazards.">
              {(id) => <Textarea id={id} rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={4000} />}
            </Field>
          </div>
        </section>

        <Notice tone="info">
          <strong>How the agency&apos;s response is recorded:</strong> agencies have no ResQ accounts. After you create the order it
          shows as <strong>Requested</strong>; contact the agency by phone or radio, then open the dispatch and use{" "}
          <strong>Record an event</strong> to log their acknowledgement, en route, progress and completion (who confirmed, and over
          which channel). Field teams with their own ResQ responder account update the order themselves from the Field app.
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
