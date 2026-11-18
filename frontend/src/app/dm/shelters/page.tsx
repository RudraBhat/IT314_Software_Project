"use client";

import { useState } from "react";

import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { useAction } from "@/components/use-action";
import { api, useQuery } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import type { Tone } from "@/components/ui";

type Shelter = {
  shelter_id: string;
  name: string;
  type: "SHELTER" | "RELIEF_CAMP" | "MEDICAL_POST";
  address_text: string;
  district: string | null;
  latitude: number;
  longitude: number;
  total_capacity: number | null;
  current_occupancy: number | null;
  contact_number: string | null;
  status: "OPERATIONAL" | "FULL" | "CLOSED";
  notes: string | null;
  is_simulated: boolean;
  updated_at: string;
};

type Form = {
  name: string;
  type: Shelter["type"];
  address_text: string;
  district: string;
  latitude: string;
  longitude: string;
  total_capacity: string;
  current_occupancy: string;
  contact_number: string;
  status: Shelter["status"];
  notes: string;
  reason: string;
};

const TYPE_LABEL: Record<Shelter["type"], string> = { SHELTER: "Shelter", RELIEF_CAMP: "Relief camp", MEDICAL_POST: "Medical post" };
const STATUS_LABEL: Record<Shelter["status"], string> = { OPERATIONAL: "Open", FULL: "Full", CLOSED: "Closed" };
const STATUS_TONE: Record<Shelter["status"], Tone> = { OPERATIONAL: "low", FULL: "high", CLOSED: "neutral" };

const EMPTY: Form = {
  name: "", type: "SHELTER", address_text: "", district: "", latitude: "", longitude: "",
  total_capacity: "", current_occupancy: "", contact_number: "", status: "OPERATIONAL", notes: "", reason: "",
};

function toForm(s: Shelter): Form {
  return {
    name: s.name, type: s.type, address_text: s.address_text, district: s.district ?? "",
    latitude: String(s.latitude), longitude: String(s.longitude),
    total_capacity: s.total_capacity === null ? "" : String(s.total_capacity),
    current_occupancy: s.current_occupancy === null ? "" : String(s.current_occupancy),
    contact_number: s.contact_number ?? "", status: s.status, notes: s.notes ?? "", reason: "",
  };
}

const int = (v: string) => (v.trim() === "" ? null : Number(v));

/** Why the form cannot be saved yet, or null when it can. Mirrors the server's rules. */
function problem(f: Form): string | null {
  if (f.name.trim().length < 2) return "Enter the shelter's name.";
  if (f.address_text.trim().length < 3) return "Enter an address.";
  const lat = Number(f.latitude), lon = Number(f.longitude);
  if (f.latitude.trim() === "" || !Number.isFinite(lat) || lat < -90 || lat > 90) return "Latitude must be between -90 and 90.";
  if (f.longitude.trim() === "" || !Number.isFinite(lon) || lon < -180 || lon > 180) return "Longitude must be between -180 and 180.";
  const cap = int(f.total_capacity), occ = int(f.current_occupancy);
  if ((cap !== null && (!Number.isInteger(cap) || cap < 0)) || (occ !== null && (!Number.isInteger(occ) || occ < 0))) return "Capacity and occupancy must be whole numbers.";
  if (cap !== null && occ !== null && occ > cap) return "Occupancy cannot be higher than capacity.";
  if (f.contact_number.trim() && !/^[0-9+()\-\s]{5,30}$/.test(f.contact_number.trim())) return "Contact number may only contain digits, spaces, +, - and brackets.";
  if (f.reason.trim().length < 5) return "Give a reason (at least 5 characters) for the audit log.";
  return null;
}

/** Shelters and medical posts shown to citizens. Dispatch and supervisor staff keep them current; closing one hides it. */
export default function SheltersPage() {
  const q = useQuery<{ items: Shelter[] }>("shelters");
  const { run, busy } = useAction(q.reload);
  const [editing, setEditing] = useState<{ id: string | null; form: Form } | null>(null);

  async function save() {
    if (!editing || problem(editing.form)) return;
    const f = editing.form;
    const body = {
      name: f.name.trim(), type: f.type, address_text: f.address_text.trim(), district: f.district.trim() || null,
      latitude: Number(f.latitude), longitude: Number(f.longitude),
      total_capacity: int(f.total_capacity), current_occupancy: int(f.current_occupancy),
      contact_number: f.contact_number.trim() || null, status: f.status, notes: f.notes.trim() || null, reason: f.reason.trim(),
    };
    const done = await run(
      "save",
      () => (editing.id ? api(`shelters/${editing.id}`, { method: "PUT", body }) : api("shelters", { method: "POST", body })),
      editing.id ? "Shelter updated." : "Shelter added. Citizens can see it now.",
    );
    if (done !== undefined) {
      setEditing(null);
      q.reload();
    }
  }

  const set = (changes: Partial<Form>) => setEditing((e) => (e ? { ...e, form: { ...e.form, ...changes } } : e));
  const issue = editing ? problem(editing.form) : null;
  const shelters = q.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Shelters"
        description="Relief shelters, camps and medical posts that citizens see on their dashboard. Keep capacity and status current."
        actions={<Button variant="primary" onClick={() => setEditing({ id: null, form: EMPTY })}>Add shelter</Button>}
      />

      {q.error && <ErrorState message={q.error} onRetry={q.reload} />}
      {q.loading && !q.data && <LoadingRows rows={4} />}
      {q.data && shelters.length === 0 && (
        <Card><EmptyState title="No shelters published yet.">Citizens see an empty list until you add the first one.</EmptyState></Card>
      )}
      {shelters.length > 0 && (
        <Card bodyClassName="p-0">
          <ul className={`divide-y divide-border ${q.loading ? "opacity-60" : ""}`}>
            {shelters.map((s) => (
              <li key={s.shelter_id} className="flex flex-col gap-1.5 px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">{s.name}</span>
                  <Badge tone="neutral">{TYPE_LABEL[s.type]}</Badge>
                  <Badge tone={STATUS_TONE[s.status]}>{STATUS_LABEL[s.status]}</Badge>
                  {s.is_simulated && <Badge tone="info">Sample data</Badge>}
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setEditing({ id: s.shelter_id, form: toForm(s) })} aria-label={`Edit ${s.name}`}>
                    Edit
                  </Button>
                </div>
                <p className="text-xs text-muted">
                  {s.address_text}{s.district ? ` · ${s.district}` : ""}
                  {s.contact_number ? ` · ${s.contact_number}` : ""}
                </p>
                <p className="text-xs text-muted">
                  Occupancy:{" "}
                  <span className="font-medium text-foreground">
                    {s.current_occupancy ?? "—"} / {s.total_capacity ?? "—"}
                  </span>
                  {" · "}Updated {formatDateTime(s.updated_at)}
                </p>
                {s.notes && <p className="text-sm">{s.notes}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.id ? "Edit shelter" : "Add shelter"}
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            <Button variant="primary" busy={busy === "save"} disabled={issue !== null} onClick={save}>
              {editing?.id ? "Save changes" : "Add shelter"}
            </Button>
          </>
        }
      >
        {editing && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name">{(id) => <Input id={id} value={editing.form.name} maxLength={160} onChange={(e) => set({ name: e.target.value })} />}</Field>
            <Field label="Type">
              {(id) => (
                <Select id={id} value={editing.form.type} onChange={(e) => set({ type: e.target.value as Shelter["type"] })}>
                  {(Object.keys(TYPE_LABEL) as Shelter["type"][]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                </Select>
              )}
            </Field>
            <div className="sm:col-span-2">
              <Field label="Address">{(id) => <Input id={id} value={editing.form.address_text} maxLength={300} onChange={(e) => set({ address_text: e.target.value })} />}</Field>
            </div>
            <Field label="District">{(id) => <Input id={id} value={editing.form.district} maxLength={100} onChange={(e) => set({ district: e.target.value })} />}</Field>
            <Field label="Contact number">{(id) => <Input id={id} type="tel" value={editing.form.contact_number} maxLength={30} onChange={(e) => set({ contact_number: e.target.value })} />}</Field>
            <Field label="Latitude" hint="For example 23.0225">{(id) => <Input id={id} inputMode="decimal" value={editing.form.latitude} onChange={(e) => set({ latitude: e.target.value })} />}</Field>
            <Field label="Longitude" hint="For example 72.5714">{(id) => <Input id={id} inputMode="decimal" value={editing.form.longitude} onChange={(e) => set({ longitude: e.target.value })} />}</Field>
            <Field label="Total capacity">{(id) => <Input id={id} inputMode="numeric" value={editing.form.total_capacity} onChange={(e) => set({ total_capacity: e.target.value })} />}</Field>
            <Field label="People staying now">{(id) => <Input id={id} inputMode="numeric" value={editing.form.current_occupancy} onChange={(e) => set({ current_occupancy: e.target.value })} />}</Field>
            <Field label="Status" hint="Closed hides it from citizens.">
              {(id) => (
                <Select id={id} value={editing.form.status} onChange={(e) => set({ status: e.target.value as Shelter["status"] })}>
                  {(Object.keys(STATUS_LABEL) as Shelter["status"][]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                </Select>
              )}
            </Field>
            <div className="sm:col-span-2">
              <Field label="Notes for citizens" hint="Optional, for example food, water or medical care available.">
                {(id) => <Textarea id={id} value={editing.form.notes} maxLength={500} onChange={(e) => set({ notes: e.target.value })} />}
              </Field>
            </div>
            <div className="sm:col-span-2">
              <Field label="Reason (recorded in the audit log)" hint="At least 5 characters.">
                {(id) => <Input id={id} value={editing.form.reason} maxLength={500} onChange={(e) => set({ reason: e.target.value })} />}
              </Field>
            </div>
            <div className="sm:col-span-2">
              {issue ? <Notice tone="neutral">{issue}</Notice> : <Notice tone="info">Citizens see name, address, status, free beds and the contact number.</Notice>}
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
