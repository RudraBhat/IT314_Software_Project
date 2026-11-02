"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { PriorityBadge, StatusBadge } from "@/components/badges";
import { useAction } from "@/components/use-action";
import { Badge, Button, Card, Dialog, ErrorState, Field, Input, KeyValue, LoadingRows, Notice, Select, Textarea } from "@/components/ui";
import { api, useQuery } from "@/lib/api";
import { formatDateTime, label, scenarioLabel } from "@/lib/format";
import type { Dispatch } from "@/lib/types";

import { useStaff } from "../../shell";

type Detail = Dispatch & {
  assignments: { assignment_id: string; resource_name: string; type: string; quantity: string; assigned_at: string; released_at: string | null }[];
  events: { audit_id: number; occurred_at: string; action: string; result: string; rationale: string | null; recorded_by: string; after_state: Record<string, unknown> | null }[];
  messages: { message_id: string; subject: string | null; status: string; created_at: string; agency_name: string }[];
};

type EventKind = "acknowledgement" | "rejection" | "en_route" | "progress" | "completion" | "failure" | "escalation";

const CHANNELS = ["PHONE", "RADIO", "EMAIL", "IN_PERSON", "OTHER"];

const EVENT_COPY: Record<EventKind, { title: string; who?: string; text: string; danger?: boolean }> = {
  acknowledgement: { title: "Record agency acknowledgement", who: "Who at the agency confirmed receipt", text: "Note (optional)" },
  rejection: { title: "Record agency rejection", who: "Who reported the rejection", text: "Reason given", danger: true },
  en_route: { title: "Record resources en route", who: "Reported by", text: "Note (optional)" },
  progress: { title: "Record progress update", who: "Reported by", text: "Update" },
  completion: { title: "Record completion", who: "Who confirmed completion", text: "Note (optional)" },
  failure: { title: "Mark dispatch failed", text: "What failed", danger: true },
  escalation: { title: "Escalate to supervisors", text: "Reason for escalation", danger: true },
};

export default function DispatchPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useStaff();
  const { data, error, reload, loading } = useQuery<Detail>(`dispatches/${id}`);
  const teamRequests = useQuery<
    Array<{
      request_id: string;
      required_capability: string;
      note: string | null;
      status: string;
      requested_by_name: string;
      created_at: string;
    }>
  >("team-requests", { dispatch_id: id, status: "OPEN" });
  const { run, busy } = useAction(reload);
  const [kind, setKind] = useState<EventKind | null>(null);
  const [who, setWho] = useState("");
  const [channel, setChannel] = useState("PHONE");
  const [text, setText] = useState("");
  const [decisionReq, setDecisionReq] = useState<{ id: string; decision: "APPROVED" | "DECLINED" } | null>(null);
  const [decisionRationale, setDecisionRationale] = useState("");

  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <LoadingRows rows={6} />;
  const d = data;
  const s = d.status;
  const dispatcher = can("DISPATCH");

  function open(k: EventKind) {
    setWho("");
    setText("");
    setChannel("PHONE");
    setKind(k);
  }

  const textRequired = kind === "rejection" || kind === "failure" || kind === "escalation" || kind === "progress";
  const valid = kind !== null && (!EVENT_COPY[kind].who || who.trim().length >= 2) && (!textRequired || text.trim().length >= 3);

  async function submit() {
    if (!kind) return;
    const url = `dispatches/${d.dispatch_id}`;
    const note = text.trim() || undefined;
    const calls: Record<EventKind, () => Promise<unknown>> = {
      acknowledgement: () => api(`${url}/acknowledgement`, { method: "POST", body: { acknowledged_by: who, channel, note } }),
      rejection: () => api(`${url}/rejection`, { method: "POST", body: { reason: text, reported_by: who, channel } }),
      en_route: () => api(`${url}/progress`, { method: "POST", body: { event: "EN_ROUTE", reported_by: who, channel, note } }),
      progress: () => api(`${url}/progress`, { method: "POST", body: { event: "UPDATE", reported_by: who, channel, note } }),
      completion: () => api(`${url}/completion`, { method: "POST", body: { confirmed_by: who, channel, note } }),
      failure: () => api(`${url}/failure`, { method: "POST", body: { reason: text } }),
      escalation: () => api(`${url}/escalation`, { method: "POST", body: { reason: text } }),
    };
    const ok = await run(kind, calls[kind], `${EVENT_COPY[kind].title.replace(/^Record |^Mark /, "")}: saved`);
    if (ok !== undefined) {
      setKind(null);
      reload();
    }
  }

  async function submitDecision() {
    if (!decisionReq || decisionRationale.trim().length < 3) return;
    const ok = await run(
      "decision",
      () =>
        api(`team-requests/${decisionReq.id}/decision`, {
          method: "POST",
          body: { decision: decisionReq.decision, rationale: decisionRationale.trim() },
        }),
      `Team request ${decisionReq.decision.toLowerCase()}`,
    );
    if (ok !== undefined) {
      setDecisionReq(null);
      setDecisionRationale("");
      teamRequests.reload();
      reload();
    }
  }

  return (
    <>
      <Link href="/dm/dispatches" className="mb-4 inline-block text-sm text-muted hover:text-foreground">← All dispatches</Link>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-muted">{d.dispatch_ref}</p>
          <h1 className="mt-1 text-xl font-semibold sm:text-2xl">{d.agency_name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={s} />
            <PriorityBadge priority={d.priority} />
            {d.overdue && <Badge tone="critical">Overdue</Badge>}
            {d.escalated && <Badge tone="critical">Escalated</Badge>}
          </div>
        </div>
        <Button onClick={reload} busy={loading}>Refresh</Button>
      </header>

      {s === "REQUESTED" && (
        <div className="mb-6">
          <Notice tone="medium">Waiting for acknowledgement. Nothing is confirmed until you record the agency’s response.</Notice>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Card title="Order">
            <KeyValue
              items={[
                ["Incident", <Link key="i" href={`/dm/incidents/${d.incident_id}`} className="font-mono text-info hover:underline">{d.incident_ref}</Link>],
                ["Scenario", d.scenario ? (scenarioLabel[d.scenario] ?? d.scenario) : "—"],
                ["Created", `${formatDateTime(d.created_at)} by ${d.created_by_name}`],
                ["Acknowledged", d.acknowledged_at ? `${formatDateTime(d.acknowledged_at)} · ${d.acknowledged_by}` : null],
              ]}
            />
            {d.instructions && <p className="mt-4 whitespace-pre-wrap rounded-lg bg-surface-muted p-3 text-sm">{d.instructions}</p>}
          </Card>
          <Card title="Assigned resources" bodyClassName="p-0">
            <ul className="divide-y divide-border text-sm">
              {d.assignments.map((a) => (
                <li key={a.assignment_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  <span className="min-w-0 flex-1 font-medium">{a.resource_name}</span>
                  <span className="text-xs text-muted">{label(a.type)} × {Number(a.quantity)}</span>
                  {a.released_at ? <Badge>Released {formatDateTime(a.released_at)}</Badge> : <Badge tone="high">Assigned</Badge>}
                </li>
              ))}
            </ul>
          </Card>

          {/* Open Team Requests from Field Responders */}
          {teamRequests.data && teamRequests.data.length > 0 && (
            <Card
              title="Backup Team Requests"
              subtitle="Requested by responders on-scene. Advisory: approving does not automatically dispatch."
              bodyClassName="p-0"
            >
              <ul className="divide-y divide-border text-sm">
                {teamRequests.data.map((req) => (
                  <li key={req.request_id} className="p-4 space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Badge tone="high">{req.required_capability}</Badge>
                        <span className="text-xs text-muted">
                          Requested by <strong className="text-foreground">{req.requested_by_name}</strong> · {formatDateTime(req.created_at)}
                        </span>
                      </div>
                      {dispatcher && (
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="primary"
                            onClick={() => {
                              setDecisionReq({ id: req.request_id, decision: "APPROVED" });
                              setDecisionRationale("Approved backup team");
                            }}
                          >
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              setDecisionReq({ id: req.request_id, decision: "DECLINED" });
                              setDecisionRationale("Declined backup request");
                            }}
                          >
                            Decline
                          </Button>
                        </div>
                      )}
                    </div>
                    {req.note && <p className="text-xs text-muted bg-surface-muted p-2 rounded">{req.note}</p>}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card title="Event history" subtitle="Every state change with the person or integration that recorded it">
            <ol className="space-y-3 text-sm">
              {d.events.map((e) => (
                <li key={e.audit_id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{label(e.action.replace(/^DISPATCH_/, ""))}</span>
                    {e.result !== "SUCCESS" && <Badge tone="critical">Conflict flagged</Badge>}
                    <span className="text-xs text-muted">{formatDateTime(e.occurred_at)} · recorded by {e.recorded_by}</span>
                  </div>
                  {e.rationale && <p className="mt-0.5 text-muted">{e.rationale}</p>}
                </li>
              ))}
            </ol>
          </Card>
        </div>
        <div className="space-y-6">
          <Card title="Record an event" subtitle={dispatcher ? "From the agency or the field team" : "Requires the dispatch permission"}>
            <div className="grid gap-2">
              {s === "REQUESTED" && <Button variant="primary" disabled={!dispatcher} onClick={() => open("acknowledgement")}>Acknowledged…</Button>}
              {s === "ACKNOWLEDGED" && <Button variant="primary" disabled={!dispatcher} onClick={() => open("en_route")}>Resources en route…</Button>}
              {s === "DISPATCHED" && <Button variant="primary" disabled={!dispatcher} onClick={() => open("completion")}>Completed…</Button>}
              {(s === "ACKNOWLEDGED" || s === "DISPATCHED") && <Button disabled={!dispatcher} onClick={() => open("progress")}>Progress update…</Button>}
              {(s === "REQUESTED" || s === "ACKNOWLEDGED") && <Button variant="danger" disabled={!dispatcher} onClick={() => open("rejection")}>Agency rejected…</Button>}
              {["REQUESTED", "ACKNOWLEDGED", "DISPATCHED"].includes(s) && <Button disabled={!dispatcher} onClick={() => open("failure")}>Mark failed…</Button>}
              {s === "REQUESTED" && can("SUPERVISOR") && <Button onClick={() => open("escalation")}>Escalate…</Button>}
              {["COMPLETED", "REJECTED", "FAILED"].includes(s) && <p className="text-sm text-muted">This dispatch is {label(s).toLowerCase()}. Resources were released.</p>}
            </div>
          </Card>
          <Card title="Messages" bodyClassName="p-0">
            <ul className="divide-y divide-border text-sm">
              {d.messages.map((m) => (
                <li key={m.message_id} className="px-5 py-3">
                  <p className="font-medium">{m.subject}</p>
                  <div className="mt-1 flex items-center gap-2"><StatusBadge status={m.status} /><span className="text-xs text-muted">{formatDateTime(m.created_at)}</span></div>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <Dialog
        open={kind !== null}
        onClose={() => setKind(null)}
        title={kind ? EVENT_COPY[kind].title : ""}
        footer={
          <>
            <Button onClick={() => setKind(null)}>Cancel</Button>
            <Button variant={kind && EVENT_COPY[kind].danger ? "danger" : "primary"} disabled={!valid} busy={busy === kind} onClick={submit}>Save</Button>
          </>
        }
      >
        {kind && (
          <div className="space-y-4">
            {EVENT_COPY[kind].who && (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={EVENT_COPY[kind].who!}>{(fid) => <Input id={fid} value={who} onChange={(e) => setWho(e.target.value)} maxLength={150} />}</Field>
                <Field label="Received via">
                  {(fid) => (
                    <Select id={fid} value={channel} onChange={(e) => setChannel(e.target.value)}>
                      {CHANNELS.map((c) => <option key={c} value={c}>{label(c)}</option>)}
                    </Select>
                  )}
                </Field>
              </div>
            )}
            <Field label={EVENT_COPY[kind].text}>{(fid) => <Textarea id={fid} value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} />}</Field>
            <p className="text-xs text-muted">Saved with your name as the recorder.</p>
          </div>
        )}
      </Dialog>

      <Dialog
        open={decisionReq !== null}
        onClose={() => setDecisionReq(null)}
        title={decisionReq?.decision === "APPROVED" ? "Approve Backup Team Request" : "Decline Backup Team Request"}
        footer={
          <>
            <Button onClick={() => setDecisionReq(null)}>Cancel</Button>
            <Button
              variant={decisionReq?.decision === "APPROVED" ? "primary" : "danger"}
              disabled={decisionRationale.trim().length < 3}
              busy={busy === "decision"}
              onClick={submitDecision}
            >
              Confirm Decision
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-xs text-muted">
            Approving indicates authorization for extra resources. You must still create a dispatch order to reserve and assign them.
          </p>
          <Field label="Decision Rationale" hint="Minimum 3 characters explaining your decision.">
            {(fid) => (
              <Textarea
                id={fid}
                rows={3}
                value={decisionRationale}
                onChange={(e) => setDecisionRationale(e.target.value)}
                placeholder="Rationale..."
                maxLength={2000}
              />
            )}
          </Field>
        </div>
      </Dialog>
    </>
  );
}
