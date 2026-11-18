"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { PriorityBadge, StatusBadge } from "@/components/badges";
import { Badge, Button, Card, ErrorState, KeyValue, LoadingRows, Notice } from "@/components/ui";
import { useQuery } from "@/lib/api";
import { formatDateTime, formatNumber, label, scenarioLabel } from "@/lib/format";

import { AiPanel } from "./ai-panel";
import { DecisionPanel } from "./decision-panel";
import { DispatchPanel, MessagesPanel } from "./dispatch-panel";
import { DuplicatesPanel } from "./duplicates-panel";
import { NotesPanel } from "./notes-panel";
import type { IncidentDetail } from "./types";

const moderationLabel: Record<string, string> = {
  PENDING: "Pending moderation",
  FAILED: "Pending moderation",
  CLEAN: "Approved",
  QUARANTINED: "Quarantined",
  REJECTED: "Removed",
};

export default function IncidentPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useQuery<IncidentDetail>(`incidents/${id}`);

  if (error && !data) {
    return (
      <>
        <BackLink />
        <ErrorState message={error} onRetry={reload} />
      </>
    );
  }
  if (!data) {
    return (
      <>
        <BackLink />
        <LoadingRows rows={6} />
      </>
    );
  }

  const i = data;
  return (
    <>
      <BackLink />
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-sm text-muted">{i.incident_ref}</p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight sm:text-2xl">
            {scenarioLabel[i.scenario]} · {i.address_text ?? "Location by coordinates"}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={i.status} />
            <PriorityBadge priority={i.verified_priority} />
            {i.canonical_incident_id && <Badge tone="medium">Linked duplicate</Badge>}
            {i.withdrawal_requested && <Badge tone="high">Withdrawal requested</Badge>}
            <span className="text-xs text-muted">Version {i.version} · updated {formatDateTime(i.updated_at)}</span>
          </div>
        </div>
        <Button onClick={reload} busy={loading}>Refresh</Button>
      </header>

      {i.withdrawal_requested && (
        <div className="mb-6">
          <Notice tone="high">
            The reporter asked to withdraw this report (see the history below). Nothing has changed: reject it if it is a false alarm or duplicate, or carry on if it still needs a response.
          </Notice>
        </div>
      )}

      {i.status === "CLOSED" && (
        <div className="mb-6">
          <Notice tone="neutral">Closed {formatDateTime(i.closed_at)}. This record is read-only until reopened.</Notice>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Card title="Report">
            <p className="whitespace-pre-wrap text-sm">{i.description}</p>
            <div className="mt-4">
              <KeyValue
                items={[
                  ["Reported urgency", i.reported_urgency ? label(i.reported_urgency) : null],
                  ["People affected", formatNumber(i.people_affected)],
                  ["Submitted", formatDateTime(i.submitted_at)],
                  ["Verified", i.verified_at ? `${formatDateTime(i.verified_at)} by ${i.verified_by_name ?? "staff"}` : null],
                  ["Priority rationale", i.priority_rationale],
                  ...Object.entries(i.details ?? {}).map(([k, v]) => [label(k), typeof v === "object" ? JSON.stringify(v) : String(v)] as [string, string]),
                ]}
              />
            </div>
          </Card>

          <div className="grid gap-6 md:grid-cols-2">
            <Card title="Reporter" subtitle="Visible to authorised staff only">
              <KeyValue items={[["Name", i.reporter.full_name], ["Phone", i.reporter.phone], ["Email", i.reporter.email]]} />
            </Card>
            <Card title="Location">
              <KeyValue
                items={[
                  ["Address", i.address_text],
                  ["Landmark", i.landmark],
                  [
                    "Coordinates",
                    i.latitude !== null && i.longitude !== null ? (
                      <Link href={`/?incident=${i.incident_id}`} className="text-info hover:underline">
                        {Number(i.latitude).toFixed(5)}, {Number(i.longitude).toFixed(5)}
                      </Link>
                    ) : (
                      <span className="text-medium">Not provided</span>
                    ),
                  ],
                  ["Source", `${label(i.location_source)}${i.accuracy_m ? ` · ±${Number(i.accuracy_m)} m` : ""}`],
                ]}
              />
            </Card>
          </div>

          <Card title="Evidence" subtitle="Files are never shown here before moderation approves them.">
            {i.evidence.length === 0 ? (
              <p className="text-sm text-muted">No evidence uploaded.</p>
            ) : (
              <ul className="divide-y divide-border text-sm">
                {i.evidence.map((e) => (
                  <li key={e.evidence_id} className="flex flex-wrap items-center gap-2 py-2">
                    <span className="min-w-0 flex-1 truncate">{e.file_name}</span>
                    <span className="text-xs text-muted">{e.mime_type} · {Math.ceil(e.size_bytes / 1024)} KB</span>
                    <Badge tone={e.scan_state === "CLEAN" ? "low" : e.scan_state === "QUARANTINED" ? "critical" : "medium"}>
                      {moderationLabel[e.scan_state] ?? e.scan_state}
                    </Badge>
                    {e.scan_state === "CLEAN" && (
                      // Opened on request only, never loaded automatically: each view is audited.
                      <a
                        href={`/api/dm/incidents/${i.incident_id}/evidence/${e.evidence_id}/content`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-medium text-info hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
                        aria-label={`View photo ${e.file_name}`}
                      >
                        View photo
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-muted">Approved photos open in a new tab; each view is recorded in the audit log.</p>
          </Card>

          <DispatchPanel incident={i} reload={reload} />
          <MessagesPanel incident={i} reload={reload} />
          <NotesPanel incidentId={i.incident_id} closed={i.status === "CLOSED"} />

          <Card title="Status history">
            <ol className="space-y-3">
              {i.history.length === 0 && <li className="text-sm text-muted">Submitted {formatDateTime(i.submitted_at)}. No staff decisions yet.</li>}
              {i.history.map((h) => (
                <li key={h.history_id} className="text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    {h.from_status && <><StatusBadge status={h.from_status} /><span aria-hidden>→</span></>}
                    <StatusBadge status={h.to_status} />
                    <span className="text-xs text-muted">{formatDateTime(h.changed_at)} · {h.changed_by_name ?? "System"}</span>
                  </div>
                  {h.reason && <p className="mt-1 whitespace-pre-wrap text-muted">{h.reason}</p>}
                </li>
              ))}
            </ol>
          </Card>

          <Card title="Audit trail" subtitle="Append-only record of every action on this incident">
            <details>
              <summary className="cursor-pointer text-sm text-info">Show {i.audit_trail.length} entries</summary>
              <ul className="mt-3 divide-y divide-border text-sm">
                {i.audit_trail.map((a) => (
                  <li key={a.audit_id} className="py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{label(a.action)}</span>
                      {a.result !== "SUCCESS" && <Badge tone="critical">{label(a.result)}</Badge>}
                      <span className="text-xs text-muted">{formatDateTime(a.occurred_at)} · {a.actor_name}</span>
                    </div>
                    {a.rationale && <p className="mt-0.5 text-xs text-muted">{a.rationale}</p>}
                  </li>
                ))}
              </ul>
            </details>
          </Card>
        </div>

        <div className="min-w-0 space-y-6">
          <DecisionPanel incident={i} reload={reload} />
          <AiPanel incident={i} reload={reload} />
          <DuplicatesPanel incident={i} reload={reload} />
        </div>
      </div>
    </>
  );
}

function BackLink() {
  return (
    <Link href="/dm/incidents" className="mb-4 inline-block text-sm text-muted hover:text-foreground">
      ← All incidents
    </Link>
  );
}
