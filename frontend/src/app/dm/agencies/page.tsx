"use client";

import { useState } from "react";

import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, Notice, PageHeader, Select } from "@/components/ui";
import { useAction } from "@/components/use-action";
import { api, useQuery } from "@/lib/api";
import { AGENCY_TYPES, AGENCY_TYPE_ICON, AGENCY_TYPE_LABEL, formatDateTime } from "@/lib/format";
import type { Agency } from "@/lib/types";

import { useStaff } from "../shell";

const TYPES = AGENCY_TYPES;
const TYPE_LABEL = AGENCY_TYPE_LABEL;

type Form = { name: string; agency_type: string; contact_email: string; contact_phone: string; is_active: boolean; reason: string };

const EMPTY: Form = { name: "", agency_type: "FIRE", contact_email: "", contact_phone: "", is_active: true, reason: "" };

function toForm(a: Agency): Form {
  return {
    name: a.name,
    agency_type: a.agency_type ?? "FIRE",
    contact_email: a.contact_email ?? "",
    contact_phone: a.contact_phone ?? "",
    is_active: a.is_active,
    reason: "",
  };
}

/** Why the form cannot be saved yet, or null when it can. Mirrors the server's rules. */
function problem(f: Form): string | null {
  if (f.name.trim().length < 2) return "Enter the agency's name.";
  const email = f.contact_email.trim();
  const phone = f.contact_phone.trim();
  if (!email && !phone) return "Give an email address or a phone number so the agency can be reached.";
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) return "That email address does not look right.";
  if (phone && !/^[0-9+()\-\s]{3,20}$/.test(phone)) return "A phone number may only contain digits, spaces, +, - and brackets (3 to 20 characters).";
  if (f.reason.trim().length < 5) return "Give a reason (at least 5 characters) for the audit log.";
  return null;
}

/**
 * The agencies that dispatch messages are addressed to. Every dispatch staff member can read the directory;
 * only a supervisor can add, edit or deactivate an agency. An agency is never deleted: deactivating one stops
 * new dispatches to it but keeps the history, and is refused while dispatches to it are still active.
 */
export default function AgenciesPage() {
  const { can } = useStaff();
  const canEdit = can("SUPERVISOR");
  const q = useQuery<{ items: Agency[] }>("agency-contacts");
  const { run, busy } = useAction(q.reload);
  const [editing, setEditing] = useState<{ id: string | null; form: Form } | null>(null);

  async function save() {
    if (!editing || problem(editing.form)) return;
    const f = editing.form;
    const body = {
      name: f.name.trim(),
      agency_type: f.agency_type,
      contact_email: f.contact_email.trim() || null,
      contact_phone: f.contact_phone.trim() || null,
      is_active: f.is_active,
      reason: f.reason.trim(),
    };
    const done = await run(
      "save",
      () => (editing.id ? api(`agencies/${editing.id}`, { method: "PUT", body }) : api("agencies", { method: "POST", body })),
      editing.id ? "Agency updated." : "Agency added.",
    );
    if (done !== undefined) {
      setEditing(null);
      q.reload();
    }
  }

  const set = (changes: Partial<Form>) => setEditing((e) => (e ? { ...e, form: { ...e.form, ...changes } } : e));
  const issue = editing ? problem(editing.form) : null;
  const agencies = q.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Agencies"
        description="The agencies dispatch messages are addressed to. Supervisors keep their contacts current."
        actions={canEdit ? <Button variant="primary" onClick={() => setEditing({ id: null, form: EMPTY })}>Add agency</Button> : undefined}
      />
      {!canEdit && (
        <div className="mb-4">
          <Notice tone="info">You can see every agency here. Adding or changing one needs the supervisor permission.</Notice>
        </div>
      )}

      {q.error && <ErrorState message={q.error} onRetry={q.reload} />}
      {q.loading && !q.data && <LoadingRows rows={5} />}
      {q.data && agencies.length === 0 && <Card><EmptyState title="No agencies yet." /></Card>}
      {/* Grouped by agency type, so the right service is easy to find when dispatching. */}
      {agencies.length > 0 && (
        <div className={`space-y-5 ${q.loading ? "opacity-60" : ""}`}>
          {[...TYPES, "OTHER"].map((type) => {
            const group = agencies.filter((a) =>
              (TYPES as readonly string[]).includes(a.agency_type ?? "") ? a.agency_type === type : type === "OTHER",
            );
            if (!group.length) return null;
            return (
              <Card
                key={type}
                title={`${AGENCY_TYPE_ICON[type] ?? "🏢"} ${TYPE_LABEL[type] ?? "Other"}`}
                subtitle={`${group.length} agenc${group.length === 1 ? "y" : "ies"} · ${group.filter((a) => a.is_active).length} active`}
                bodyClassName="p-0"
              >
                <ul className="divide-y divide-border">
                  {group.map((a) => (
                    <li key={a.agency_id} className="flex flex-col gap-1 px-5 py-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">{a.name}</span>
                        <Badge tone={a.is_active ? "low" : "neutral"}>{a.is_active ? "Active" : "Inactive"}</Badge>
                        {canEdit && (
                          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setEditing({ id: a.agency_id, form: toForm(a) })} aria-label={`Edit ${a.name}`}>
                            Edit
                          </Button>
                        )}
                      </div>
                      <p className="text-xs text-muted">
                        {a.contact_phone ?? "No phone"} · {a.contact_email ?? "No email"}
                        {a.updated_at ? ` · Updated ${formatDateTime(a.updated_at)}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.id ? "Edit agency" : "Add agency"}
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            <Button variant="primary" busy={busy === "save"} disabled={issue !== null} onClick={save}>
              {editing?.id ? "Save changes" : "Add agency"}
            </Button>
          </>
        }
      >
        {editing && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Field label="Name">{(id) => <Input id={id} value={editing.form.name} maxLength={200} onChange={(e) => set({ name: e.target.value })} />}</Field>
            </div>
            <Field label="Type">
              {(id) => (
                <Select id={id} value={editing.form.agency_type} onChange={(e) => set({ agency_type: e.target.value })}>
                  {TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                </Select>
              )}
            </Field>
            {editing.id ? (
              <Field label="Status" hint="Inactive stops new dispatches to this agency.">
                {(id) => (
                  <Select id={id} value={editing.form.is_active ? "active" : "inactive"} onChange={(e) => set({ is_active: e.target.value === "active" })}>
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                  </Select>
                )}
              </Field>
            ) : (
              <div />
            )}
            <Field label="Contact email">{(id) => <Input id={id} type="email" value={editing.form.contact_email} maxLength={254} onChange={(e) => set({ contact_email: e.target.value })} />}</Field>
            <Field label="Contact phone">{(id) => <Input id={id} type="tel" value={editing.form.contact_phone} maxLength={20} onChange={(e) => set({ contact_phone: e.target.value })} />}</Field>
            <div className="sm:col-span-2">
              <Field label="Reason (recorded in the audit log)" hint="At least 5 characters.">
                {(id) => <Input id={id} value={editing.form.reason} maxLength={500} onChange={(e) => set({ reason: e.target.value })} />}
              </Field>
            </div>
            <div className="sm:col-span-2">
              {issue ? <Notice tone="neutral">{issue}</Notice> : <Notice tone="info">Dispatch messages for this agency go to this email address and phone number.</Notice>}
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
