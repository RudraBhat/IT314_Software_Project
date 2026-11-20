"use client";

import { useState } from "react";
import { RelatedSignalsPanel, type RelatedSignalsResponse } from "@/components/dm/RelatedSignalsPanel";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, LoadingRows, PageHeader, Select, Textarea } from "@/components/ui";
import { api, useQuery } from "@/lib/api";
import { useStaff } from "../shell";

interface SignalItem {
  signal_id: string;
  source: string;
  content_text: string;
  language: string | null;
  ai_label: string | null;
  ai_confidence: number | null;
  ai_details: {
    model?: string | null;
    priority?: string | null;
    uncertainty?: string | null;
    factors?: Array<{ name?: string; detail?: string; weight?: number }>;
  } | null;
  status: "PENDING" | "PROMOTED" | "DISMISSED";
  latitude: number | null;
  longitude: number | null;
  location_text: string | null;
  location_precision: string;
  source_created_at: string | null;
  source_url: string | null;
  is_simulated: boolean;
  created_at: string;
}

const SCENARIO_OPTIONS = [
  { value: "urban_flooding", label: "Urban Flooding" },
  { value: "cyclone", label: "Cyclone / Coastal Flooding" },
  { value: "industrial_fire", label: "Industrial / Building Fire" },
];

export default function SignalsPage() {
  const { can } = useStaff();
  const canPromote = can("PUBLISHER") || can("SUPERVISOR");
  const canDelete = can("SUPERVISOR");

  const [filterStatus, setFilterStatus] = useState<"PENDING" | "PROMOTED" | "DISMISSED">("PENDING");
  const { data: signals, error, reload, loading } = useQuery<SignalItem[]>("signals", {
    status: filterStatus,
    limit: 100,
  });

  // Advisory suggestions are searched server-side across ALL pending signals, not just the rows shown here.
  const related = useQuery<RelatedSignalsResponse>(filterStatus === "PENDING" ? "signals/related" : null, { limit: 50 });
  const relatedCount = new Map<string, number>();
  for (const pair of related.data?.pairs ?? []) {
    for (const id of [pair.signal_a.signal_id, pair.signal_b.signal_id]) relatedCount.set(id, (relatedCount.get(id) ?? 0) + 1);
  }
  const reloadAll = () => {
    reload();
    related.reload();
  };

  // Action Dialog states
  const [promotingSignal, setPromotingSignal] = useState<SignalItem | null>(null);
  const [selectedScenario, setSelectedScenario] = useState<string>("urban_flooding");
  const [promoteBusy, setPromoteBusy] = useState(false);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  const [dismissingSignal, setDismissingSignal] = useState<SignalItem | null>(null);
  const [dismissRationale, setDismissRationale] = useState("");
  const [dismissBusy, setDismissBusy] = useState(false);
  const [dismissError, setDismissError] = useState<string | null>(null);

  const [deletingSignal, setDeletingSignal] = useState<SignalItem | null>(null);
  const [deleteRationale, setDeleteRationale] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleOpenPromote = (sig: SignalItem) => {
    setPromoteError(null);
    const defaultScen =
      sig.ai_label && ["CYCLONE", "INDUSTRIAL_FIRE", "URBAN_FLOODING"].includes(sig.ai_label.toUpperCase())
        ? sig.ai_label.toLowerCase()
        : "urban_flooding";
    setSelectedScenario(defaultScen);
    setPromotingSignal(sig);
  };

  const handlePromote = async () => {
    if (!promotingSignal) return;
    setPromoteBusy(true);
    setPromoteError(null);

    try {
      await api(`signals/${promotingSignal.signal_id}/promote`, {
        method: "POST",
        body: { scenario: selectedScenario },
      });
      setPromotingSignal(null);
      reloadAll();
    } catch (err: unknown) {
      setPromoteError(err instanceof Error ? err.message : "Failed to promote signal");
    } finally {
      setPromoteBusy(false);
    }
  };

  const handleOpenDismiss = (sig: SignalItem) => {
    setDismissError(null);
    setDismissRationale("");
    setDismissingSignal(sig);
  };

  const handleDismiss = async () => {
    if (!dismissingSignal) return;
    if (dismissRationale.trim().length < 3) {
      setDismissError("Please provide a rationale of at least 3 characters.");
      return;
    }
    setDismissBusy(true);
    setDismissError(null);

    try {
      await api(`signals/${dismissingSignal.signal_id}/dismiss`, {
        method: "POST",
        body: { rationale: dismissRationale.trim() },
      });
      setDismissingSignal(null);
      reloadAll();
    } catch (err: unknown) {
      setDismissError(err instanceof Error ? err.message : "Failed to dismiss signal");
    } finally {
      setDismissBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingSignal) return;
    if (deleteRationale.trim().length < 3) {
      setDeleteError("Enter a brief deletion reason (at least 3 characters).");
      return;
    }
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api(`signals/${deletingSignal.signal_id}`, {
        method: "DELETE",
        body: { rationale: deleteRationale.trim() },
      });
      setDeletingSignal(null);
      setDeleteRationale("");
      reloadAll();
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete signal");
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ingested Signals Triage"
        description="External early-warning signals and citizen chatter. Human verification required before public exposure."
        actions={
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-border bg-surface p-1">
              {(["PENDING", "PROMOTED", "DISMISSED"] as const).map((st) => (
                <button
                  key={st}
                  type="button"
                  onClick={() => setFilterStatus(st)}
                  className={`rounded-md px-3 py-1 text-xs font-semibold transition cursor-pointer ${
                    filterStatus === st
                      ? "bg-sky-600 text-white shadow-xs"
                      : "text-muted hover:text-foreground"
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>
            <Button size="sm" onClick={reloadAll} busy={loading}>
              Refresh
            </Button>
          </div>
        }
      />

      {filterStatus === "PENDING" && (
        <RelatedSignalsPanel data={related.data} error={related.error} loading={related.loading} onRetry={related.reload} />
      )}

      {error && !signals && <ErrorState message={error} onRetry={reload} />}

      {loading && !signals && <LoadingRows rows={5} />}

      {signals && signals.length === 0 && (
        <EmptyState title={`No ${filterStatus.toLowerCase()} signals found`}>
          When ingestion workers detect external CAP alerts or feeds, they will be listed here for triage.
        </EmptyState>
      )}

      {signals && signals.length > 0 && (
        <Card bodyClassName="p-0 overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead className="border-b border-border bg-surface-muted/50 text-xs uppercase tracking-wider text-muted">
              <tr>
                <th className="px-4 py-3">Source & Time</th>
                <th className="px-4 py-3">Content</th>
                <th className="px-4 py-3">Advisory Triage</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {signals.map((sig) => (
                <tr key={sig.signal_id} className="hover:bg-surface-muted/30 transition-colors">
                  <td className="px-4 py-3 align-top whitespace-nowrap">
                    <div className="font-semibold text-foreground">{sig.source}</div>
                    <div className="text-xs text-muted">
                      {sig.source_created_at ? "Posted " : "Received "}
                      {new Date(sig.source_created_at ?? sig.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </div>
                    {sig.source_created_at && (
                      <div className="text-[10px] text-muted">
                        Received {new Date(sig.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </div>
                    )}
                    {sig.source_url?.startsWith("https://") && (
                      <a className="mt-1 block text-[11px] text-sky-600 hover:underline" href={sig.source_url} target="_blank" rel="noreferrer">
                        View source
                      </a>
                    )}
                    {sig.is_simulated && (
                      <span className="mt-1 inline-block rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-mono text-amber-700">
                        SIMULATED
                      </span>
                    )}
                    {relatedCount.has(sig.signal_id) && (
                      <div className="mt-1">
                        <Badge tone="ai">Possibly related ×{relatedCount.get(sig.signal_id)}</Badge>
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 align-top max-w-md">
                    <p className="line-clamp-3 text-foreground">{sig.content_text}</p>
                    {sig.language && (
                      <span className="mt-1 inline-block text-[10px] font-mono uppercase text-muted">
                        Lang: {sig.language}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 align-top whitespace-nowrap">
                    {sig.ai_label ? (
                      <div>
                        <Badge tone="info">{sig.ai_label}</Badge>
                        {sig.ai_confidence !== null && (
                          <div className="mt-1 text-[11px] text-muted">
                            Conf: {(sig.ai_confidence * 100).toFixed(0)}%
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs text-muted">—</span>
                    )}
                    {sig.ai_details?.priority && (
                      <div className="mt-1"><Badge tone="high">Priority: {sig.ai_details.priority}</Badge></div>
                    )}
                    {sig.ai_details?.uncertainty && (
                      <p className="mt-1 max-w-48 whitespace-normal text-[11px] text-muted">{sig.ai_details.uncertainty}</p>
                    )}
                  </td>
                  <td className="px-4 py-3 align-top whitespace-nowrap">
                    {sig.location_text && <div className="mb-1 max-w-48 whitespace-normal text-xs text-foreground">{sig.location_text}</div>}
                    {sig.latitude !== null && sig.longitude !== null ? (
                      <div className="font-mono text-xs text-muted">
                        {sig.latitude.toFixed(4)}, {sig.longitude.toFixed(4)}
                      </div>
                    ) : (
                      <span className="text-xs text-critical">Missing GPS</span>
                    )}
                    {sig.location_precision === "DISTRICT_CENTROID" && (
                      <div className="mt-1"><Badge tone="medium">Approximate · excluded from grouping</Badge></div>
                    )}
                  </td>
                  <td className="px-4 py-3 align-top text-right whitespace-nowrap">
                    {sig.status === "PENDING" && canPromote && (
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => handleOpenPromote(sig)}
                          disabled={sig.latitude === null || sig.longitude === null}
                          title={sig.latitude === null ? "Cannot promote without coordinates" : "Promote to Incident"}
                        >
                          Promote
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleOpenDismiss(sig)}
                        >
                          Dismiss
                        </Button>
                      </div>
                    )}
                    {sig.status === "PENDING" && !canPromote && (
                      <span className="text-xs text-muted">Requires Publisher</span>
                    )}
                    {sig.status === "PROMOTED" && (
                      <Badge tone="medium">PROMOTED</Badge>
                    )}
                    {sig.status === "DISMISSED" && (
                      <Badge tone="neutral">DISMISSED</Badge>
                    )}
                    {canDelete && ["BLUESKY", "GNEWS"].includes(sig.source) && sig.status !== "PROMOTED" && (
                      <div className="mt-2 flex justify-end">
                        <Button size="sm" variant="danger" onClick={() => {
                          setDeleteError(null);
                          setDeleteRationale("");
                          setDeletingSignal(sig);
                        }}>
                          Delete source data
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Promote Modal */}
      {promotingSignal && (
        <Dialog
          open={Boolean(promotingSignal)}
          onClose={() => setPromotingSignal(null)}
          title={`Promote Signal to Incident`}
          footer={
            <div className="flex gap-2">
              <Button onClick={() => setPromotingSignal(null)}>Cancel</Button>
              <Button
                variant="primary"
                busy={promoteBusy}
                onClick={handlePromote}
              >
                Confirm Promotion
              </Button>
            </div>
          }
        >
          <div className="space-y-4 text-sm">
            <p className="text-muted">
              Promoting creates a new incident with status <strong>SUBMITTED</strong>. It will <strong>NOT</strong> appear on the public map until verified by a dispatcher.
            </p>
            {promoteError && <p className="text-xs text-critical font-medium">{promoteError}</p>}
            {promotingSignal.location_precision !== "EXACT" && (
              <p className="rounded-md border border-high/30 bg-high/5 p-3 text-xs text-high">
                This signal has an approximate candidate location. Confirm the real incident location before promotion; the centroid is excluded from related-alert grouping.
              </p>
            )}

            <div className="rounded-lg bg-surface-muted p-3 text-xs">
              <span className="font-semibold text-foreground">Content: </span>
              <span className="text-muted">{promotingSignal.content_text}</span>
            </div>

            <Field label="Target Scenario" hint="Disaster category for the newly created incident">
              {(id) => (
                <Select
                  id={id}
                  value={selectedScenario}
                  onChange={(e) => setSelectedScenario(e.target.value)}
                >
                  {SCENARIO_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
        </Dialog>
      )}

      {/* Dismiss Modal */}
      {dismissingSignal && (
        <Dialog
          open={Boolean(dismissingSignal)}
          onClose={() => setDismissingSignal(null)}
          title="Dismiss Signal"
          footer={
            <div className="flex gap-2">
              <Button onClick={() => setDismissingSignal(null)}>Cancel</Button>
              <Button
                variant="danger"
                busy={dismissBusy}
                onClick={handleDismiss}
              >
                Dismiss Signal
              </Button>
            </div>
          }
        >
          <div className="space-y-4 text-sm">
            <p className="text-muted">
              Dismissed signals are archived and will not generate incidents or alerts.
            </p>
            {dismissError && <p className="text-xs text-critical font-medium">{dismissError}</p>}

            <Field label="Dismissal Rationale" hint="Minimum 3 characters explaining why this signal is dismissed.">
              {(id) => (
                <Textarea
                  id={id}
                  rows={3}
                  required
                  value={dismissRationale}
                  onChange={(e) => setDismissRationale(e.target.value)}
                  placeholder="e.g. Out of jurisdiction, duplicate chatter, or test signal..."
                />
              )}
            </Field>
          </div>
        </Dialog>
      )}

      {deletingSignal && (
        <Dialog
          open={Boolean(deletingSignal)}
          onClose={() => setDeletingSignal(null)}
          title="Delete social signal data"
          footer={
            <div className="flex gap-2">
              <Button onClick={() => setDeletingSignal(null)}>Cancel</Button>
              <Button variant="danger" busy={deleteBusy} onClick={handleDelete}>Delete source data</Button>
            </div>
          }
        >
          <div className="space-y-4 text-sm">
            <p className="text-muted">
              This removes the stored post text, source link, and location evidence. A hashed source ID remains to prevent the next poll from reimporting it, and the deletion is recorded in the audit log. Promoted signals remain with their incident record.
            </p>
            {deleteError && <p className="text-xs text-critical font-medium">{deleteError}</p>}
            <Field label="Deletion reason" hint="Do not include the post text or personal information.">
              {(id) => (
                <Textarea
                  id={id}
                  rows={3}
                  required
                  value={deleteRationale}
                  onChange={(e) => setDeleteRationale(e.target.value)}
                  placeholder="e.g. Source deletion request"
                />
              )}
            </Field>
          </div>
        </Dialog>
      )}
    </div>
  );
}
