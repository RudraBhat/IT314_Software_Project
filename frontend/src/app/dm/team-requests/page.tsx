"use client";

import Link from "next/link";
import { useState } from "react";

import { useAction } from "@/components/use-action";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, LoadingRows, Textarea } from "@/components/ui";
import { api, useQuery } from "@/lib/api";
import { formatDateTime, label } from "@/lib/format";

import { useStaff } from "../shell";

type TeamRequest = {
  request_id: string;
  dispatch_id: string;
  required_capability: string;
  note: string | null;
  status: string;
  requested_by_name: string;
  created_at: string;
};

type Decision = { id: string; kind: "APPROVE" | "DECLINE" };

/** Queue of additional-team requests raised by field teams. Needs the DISPATCH permission to decide. */
export default function TeamRequestsPage() {
  const { can } = useStaff();
  const dispatcher = can("DISPATCH");
  const q = useQuery<TeamRequest[]>("team-requests", { status: "OPEN" });
  const { run, busy } = useAction(q.reload);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [rationale, setRationale] = useState("");

  async function submit() {
    if (!decision || rationale.trim().length < 3) return;
    const ok = await run(
      "decision",
      () => api(`team-requests/${decision.id}/decision`, { method: "POST", body: { action: decision.kind, rationale: rationale.trim() } }),
      decision.kind === "APPROVE" ? "Request approved" : "Request declined",
    );
    if (ok !== undefined) {
      setDecision(null);
      setRationale("");
      q.reload();
    }
  }

  return (
    <>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold sm:text-2xl">Team requests</h1>
          <p className="mt-1 text-sm text-muted">Additional teams requested by field responders. Approving creates a draft only; you still confirm the dispatch.</p>
        </div>
        <Button onClick={q.reload} busy={q.loading}>Refresh</Button>
      </header>

      {q.error && !q.data && <ErrorState message={q.error} onRetry={q.reload} />}
      {q.loading && !q.data && <LoadingRows rows={3} />}
      {q.data && q.data.length === 0 && <EmptyState title="No open requests">New requests from field teams appear here.</EmptyState>}

      {q.data && q.data.length > 0 && (
        <Card bodyClassName="p-0">
          <ul className="divide-y divide-border text-sm">
            {q.data.map((r) => (
              <li key={r.request_id} className="space-y-2 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="high">{label(r.required_capability)}</Badge>
                    <span className="text-xs text-muted">
                      By <strong className="text-foreground">{r.requested_by_name}</strong> · {formatDateTime(r.created_at)}
                    </span>
                    <Link href={`/dm/dispatches/${r.dispatch_id}`} className="text-xs text-info hover:underline">View dispatch</Link>
                  </div>
                  {dispatcher ? (
                    <div className="flex gap-2">
                      <Button size="sm" variant="primary" onClick={() => { setDecision({ id: r.request_id, kind: "APPROVE" }); setRationale(""); }}>Approve</Button>
                      <Button size="sm" onClick={() => { setDecision({ id: r.request_id, kind: "DECLINE" }); setRationale(""); }}>Decline</Button>
                    </div>
                  ) : (
                    <span className="text-xs text-muted">Requires the dispatch permission</span>
                  )}
                </div>
                {r.note && <p className="rounded bg-surface-muted p-2 text-xs text-muted">{r.note}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Dialog
        open={decision !== null}
        onClose={() => setDecision(null)}
        title={decision?.kind === "APPROVE" ? "Approve team request" : "Decline team request"}
        footer={
          <>
            <Button onClick={() => setDecision(null)}>Cancel</Button>
            <Button variant={decision?.kind === "APPROVE" ? "primary" : "danger"} disabled={rationale.trim().length < 3} busy={busy === "decision"} onClick={submit}>
              Confirm
            </Button>
          </>
        }
      >
        <Field label="Rationale" hint="At least 3 characters.">
          {(id) => <Textarea id={id} rows={3} value={rationale} onChange={(e) => setRationale(e.target.value)} maxLength={2000} />}
        </Field>
      </Dialog>
    </>
  );
}
