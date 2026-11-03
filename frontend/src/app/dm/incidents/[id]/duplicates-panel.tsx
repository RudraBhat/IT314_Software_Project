"use client";

import Link from "next/link";
import { useState } from "react";

import { StatusBadge } from "@/components/badges";
import { useAction } from "@/components/use-action";
import { Button, Card, Dialog, ErrorState, Field, LoadingRows, Textarea } from "@/components/ui";
import { api, useQuery } from "@/lib/api";
import { timeAgo } from "@/lib/format";

import type { IncidentDetail } from "./types";

type Candidate = {
  incident_id: string;
  incident_ref: string;
  status: string;
  address_text: string | null;
  submitted_at: string;
  description_excerpt: string;
  rationale: string;
  /** Present when the backend scores candidates (text similarity v2). */
  score?: number | null;
  method?: string | null;
};

type Action = "LINK" | "MERGE" | "DISMISS";

const actionHelp: Record<Action, string> = {
  LINK: "Record the candidate as a duplicate of this incident. Both stay in their own workflow.",
  MERGE: "Link it and reject the unverified candidate as a duplicate. Nothing is deleted.",
  DISMISS: "Not a duplicate. It will no longer be suggested for this incident.",
};

export function DuplicatesPanel({ incident, reload }: { incident: IncidentDetail; reload: () => void }) {
  const isDuplicate = !!incident.canonical_incident_id;
  const q = useQuery<{ candidates: Candidate[]; rules: { radius_m: number; window_hours: number; note: string } }>(
    isDuplicate || incident.status === "CLOSED" ? null : `incidents/${incident.incident_id}/duplicates`,
  );
  const { run, busy } = useAction(reload);
  const [pending, setPending] = useState<{ c: Candidate; action: Action } | null>(null);
  const [rationale, setRationale] = useState("");

  async function decide() {
    if (!pending) return;
    const ok = await run(
      "dup",
      () =>
        api(`incidents/${incident.incident_id}/duplicates/${pending.c.incident_id}/decision`, {
          method: "POST",
          body: { action: pending.action, rationale },
        }),
      `${pending.c.incident_ref}: ${pending.action.toLowerCase()} recorded`,
    );
    if (ok !== undefined) {
      setPending(null);
      setRationale("");
      q.reload();
      reload();
    }
  }

  return (
    <Card title="Duplicates" subtitle={q.data ? `Same scenario within ${q.data.rules.radius_m} m and ${q.data.rules.window_hours} h. A person decides every link.` : "Possible duplicate reports"}>
      {isDuplicate && (
        <p className="text-sm">
          Linked as a duplicate of{" "}
          <Link href={`/dm/incidents/${incident.canonical_incident_id}`} className="font-mono text-info hover:underline">
            {incident.canonical_incident_ref}
          </Link>
          .
        </p>
      )}
      {incident.linked_duplicates.length > 0 && (
        <div className="mb-4">
          <p className="mb-1 text-xs font-medium text-muted">Linked duplicates</p>
          <ul className="space-y-1 text-sm">
            {incident.linked_duplicates.map((d) => (
              <li key={d.incident_id} className="flex items-center gap-2">
                <Link href={`/dm/incidents/${d.incident_id}`} className="font-mono text-xs text-info hover:underline">{d.incident_ref}</Link>
                <StatusBadge status={d.status} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {q.error && <ErrorState message={q.error} onRetry={q.reload} />}
      {q.loading && !q.data && <LoadingRows rows={2} />}
      {q.data && q.data.candidates.length === 0 && <p className="text-sm text-muted">No likely duplicates found.</p>}
      <ul className="space-y-3">
        {q.data?.candidates.map((c) => (
          <li key={c.incident_id} className="rounded-lg border border-border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Link href={`/dm/incidents/${c.incident_id}`} className="font-mono text-xs text-info hover:underline">{c.incident_ref}</Link>
              <StatusBadge status={c.status} />
              <span className="text-xs text-muted">{timeAgo(c.submitted_at)}</span>
            </div>
            {typeof c.score === "number" && (
              <p className="mt-1 text-xs">
                Match score <strong className="tabular-nums">{Math.round(c.score * 100)}%</strong>
                {c.method && <span className="text-muted"> · {c.method}</span>}
              </p>
            )}
            <p className="mt-1 text-xs text-muted">Why: {c.rationale}</p>
            <p className="mt-1 line-clamp-2">{c.description_excerpt}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setPending({ c, action: "LINK" })}>Link</Button>
              {["SUBMITTED", "NEEDS_INFORMATION"].includes(c.status) && (
                <Button size="sm" onClick={() => setPending({ c, action: "MERGE" })}>Merge</Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setPending({ c, action: "DISMISS" })}>Not a duplicate</Button>
            </div>
          </li>
        ))}
      </ul>
      <Dialog
        open={pending !== null}
        onClose={() => setPending(null)}
        title={pending ? `${pending.action === "DISMISS" ? "Dismiss" : pending.action === "LINK" ? "Link" : "Merge"} ${pending.c.incident_ref}` : ""}
        footer={
          <>
            <Button onClick={() => setPending(null)}>Cancel</Button>
            <Button variant="primary" disabled={rationale.trim().length < 3} busy={busy === "dup"} onClick={decide}>Confirm</Button>
          </>
        }
      >
        {pending && (
          <div className="space-y-3">
            <p className="text-sm text-muted">{actionHelp[pending.action]}</p>
            <Field label="Rationale">
              {(id) => <Textarea id={id} value={rationale} onChange={(e) => setRationale(e.target.value)} maxLength={2000} />}
            </Field>
          </div>
        )}
      </Dialog>
    </Card>
  );
}
