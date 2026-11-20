"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge, Button, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, PageHeader, Textarea, cx, type Tone } from "@/components/ui";
import { SCENARIO_ICON } from "@/lib/format";

type Assignment = {
  dispatch_id: string;
  dispatch_ref: string;
  status: "REQUESTED" | "ACKNOWLEDGED" | "DISPATCHED";
  incident_ref: string;
  scenario: string;
  priority: string;
  address_text: string;
  landmark: string | null;
  latitude: number;
  longitude: number;
  instructions: string | null;
  dispatched_at: string;
  district?: string | null;
  acknowledged_at?: string | null;
  /** Still unacknowledged past the response window. */
  overdue?: boolean;
  /** Latest milestone the team reported: EN_ROUTE, ON_SCENE, UPDATE or DELAYED. */
  last_progress?: string | null;
  last_progress_note?: string | null;
  last_progress_at?: string | null;
  /** When the team first reported arriving on scene. */
  on_scene_at?: string | null;
};

type DialogType = "reject" | "delay" | "backup" | "complete" | "update";

type ActiveDialog = {
  type: DialogType;
  dispatch: Assignment;
} | null;

const priorityTone: Record<string, Tone> = {
  CRITICAL: "critical",
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
};

const PRIORITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

/** Left edge colour of an assignment card, by priority. */
const PRIORITY_EDGE: Record<string, string> = {
  CRITICAL: "border-l-red-500",
  HIGH: "border-l-orange-500",
  MEDIUM: "border-l-amber-400",
  LOW: "border-l-emerald-500",
};

/**
 * Where an assignment is in its lifecycle, as the responder sees it:
 * order received -> acknowledged -> en route (dispatch status DISPATCHED) -> on scene (an ON_SCENE progress
 * report) -> completed (the order leaves this list).
 */
const STEPS = ["New order", "Acknowledged", "En route", "On scene"] as const;

function stepOf(item: Assignment): number {
  if (item.status === "REQUESTED") return 0;
  if (item.status === "ACKNOWLEDGED") return 1;
  return item.on_scene_at ? 3 : 2;
}

const PROGRESS_LABEL: Record<string, string> = {
  EN_ROUTE: "En route",
  ON_SCENE: "On scene",
  UPDATE: "Situation update",
  DELAYED: "Delayed",
};

function clock(value: string) {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** The device's position for an on-scene report, or nothing if location is off or slow. Never a guess. */
function currentPosition(): Promise<{ latitude: number; longitude: number } | null> {
  if (typeof navigator === "undefined" || !navigator.geolocation) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 6000 },
    );
  });
}

function words(value: string) {
  return value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

function StatusSteps({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Assignment progress">
      {STEPS.map((step, index) => {
        const done = index < current;
        const here = index === current;
        return (
          <li key={step} className="flex flex-1 items-center gap-2" aria-current={here ? "step" : undefined}>
            <span
              className={cx(
                "flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
                done ? "bg-emerald-600 text-white" : here ? "bg-sky-600 text-white ring-4 ring-sky-100" : "bg-surface-muted text-muted",
              )}
            >
              {done ? "✓" : index + 1}
            </span>
            <span className={cx("whitespace-nowrap text-xs", here ? "font-semibold text-foreground" : "text-muted")}>{step}</span>
            {index < STEPS.length - 1 && <span aria-hidden className={cx("h-0.5 flex-1 rounded", done ? "bg-emerald-500" : "bg-border")} />}
          </li>
        );
      })}
    </ol>
  );
}

export default function FieldPage() {
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [activeDialog, setActiveDialog] = useState<ActiveDialog>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ dispatchRef: string; message: string } | null>(null);
  const [dialogInput, setDialogInput] = useState({ text: "", secondary: "", third: "" });
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);

  // Most urgent first, then oldest order first.
  const sorted = useMemo(
    () =>
      [...assignments].sort(
        (a, b) =>
          (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9) ||
          new Date(a.dispatched_at).getTime() - new Date(b.dispatched_at).getTime(),
      ),
    [assignments],
  );
  const counts = useMemo(
    () => ({
      newOrders: assignments.filter((a) => a.status === "REQUESTED").length,
      acknowledged: assignments.filter((a) => a.status === "ACKNOWLEDGED").length,
      underWay: assignments.filter((a) => a.status === "DISPATCHED" && !a.on_scene_at).length,
      onScene: assignments.filter((a) => a.status === "DISPATCHED" && a.on_scene_at).length,
    }),
    [assignments],
  );

  const loadAssignments = useCallback(async () => {
    try {
      const res = await fetch("/api/field/assignments?active=true", { cache: "no-store" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error?.message ?? `Server responded with ${res.status}`);
      }
      const data = await res.json();
      setAssignments(Array.isArray(data) ? data : []);
      setError(null);
      setRefreshedAt(new Date());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load field assignments");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load and auto-refresh every 15 seconds (SRS Requirement S2-04)
  useEffect(() => {
    let ignore = false;
    const fetchAssignments = async () => {
      try {
        const res = await fetch("/api/field/assignments?active=true", { cache: "no-store" });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data?.error?.message ?? `Server responded with ${res.status}`);
        }
        const data = await res.json();
        if (!ignore) {
          setAssignments(Array.isArray(data) ? data : []);
          setError(null);
          setRefreshedAt(new Date());
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load field assignments");
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    fetchAssignments();
    const interval = setInterval(fetchAssignments, 15000);
    return () => {
      ignore = true;
      clearInterval(interval);
    };
  }, []);

  /** POST a field action. Returns null on success, or the error message to show the responder. */
  const postAction = async (dispatchId: string, url: string, body?: unknown): Promise<string | null> => {
    setBusyId(dispatchId);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: body ? JSON.stringify(body) : "{}",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        return data?.error?.message ?? `Action failed (${res.status}).`;
      }
      await loadAssignments();
      return null;
    } catch {
      return "Could not reach the server. Check your connection and try again.";
    } finally {
      setBusyId(null);
    }
  };

  // Card buttons: a failure stays on screen (not a blocking alert) until dismissed or retried.
  const handleSimpleAction = async (dispatch: Assignment, url: string, body?: unknown) => {
    setActionError(null);
    const failure = await postAction(dispatch.dispatch_id, url, body);
    if (failure) setActionError({ dispatchRef: dispatch.dispatch_ref, message: failure });
  };

  // Arrival: attach the device position when the responder allows it, so dispatch sees where the team is.
  const reportOnScene = async (dispatch: Assignment) => {
    setActionError(null);
    setBusyId(dispatch.dispatch_id);
    const position = await currentPosition();
    const failure = await postAction(dispatch.dispatch_id, `/api/field/dispatches/${dispatch.dispatch_id}/progress`, {
      status: "ON_SCENE",
      note: position ? "Arrived on scene (device location attached)" : "Arrived on scene",
      ...(position ?? {}),
    });
    if (failure) setActionError({ dispatchRef: dispatch.dispatch_ref, message: failure });
  };

  const handleDialogSubmit = async () => {
    if (!activeDialog) return;
    setDialogError(null);
    const { type, dispatch } = activeDialog;
    const base = `/api/field/dispatches/${dispatch.dispatch_id}`;
    const text = dialogInput.text.trim();

    let request: { url: string; body: unknown };
    if (type === "reject") {
      if (text.length < 3) return setDialogError("Rejection reason must be at least 3 characters.");
      request = { url: `${base}/rejection`, body: { reason: text } };
    } else if (type === "delay") {
      request = { url: `${base}/progress`, body: { status: "DELAYED", note: text || undefined } };
    } else if (type === "update") {
      if (text.length < 3) return setDialogError("Describe the situation in at least 3 characters.");
      request = { url: `${base}/progress`, body: { status: "UPDATE", note: text } };
    } else if (type === "backup") {
      if (text.length < 2) return setDialogError("Required capability must be at least 2 characters.");
      request = {
        url: `${base}/team-requests`,
        body: { required_capability: text, note: dialogInput.secondary.trim() || undefined },
      };
    } else {
      if (text.length < 5) return setDialogError("Completion summary must be at least 5 characters.");
      const count = (value: string) => (value.trim() === "" ? undefined : Number(value));
      const evacuated = count(dialogInput.secondary);
      const treated = count(dialogInput.third);
      if ([evacuated, treated].some((n) => n !== undefined && (!Number.isInteger(n) || n < 0))) {
        return setDialogError("People counts must be whole numbers (0 or more).");
      }
      request = {
        url: `${base}/completion`,
        body: { summary: text, civilians_evacuated: evacuated, civilians_treated: treated },
      };
    }

    // Keep the dialog (and what the responder typed) open when the server refuses the action.
    const failure = await postAction(dispatch.dispatch_id, request.url, request.body);
    if (failure) return setDialogError(failure);
    setActiveDialog(null);
    setDialogInput({ text: "", secondary: "", third: "" });
  };

  const openDialog = (type: DialogType, dispatch: Assignment) => {
    setDialogError(null);
    setDialogInput({ text: "", secondary: "", third: "" });
    setActiveDialog({ type, dispatch });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Active Assignments"
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>Your team&apos;s active dispatches, most urgent first.</span>
            <span aria-live="polite" className="inline-flex items-center gap-1.5 text-xs text-muted">
              <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
              Updates every 15s{refreshedAt ? ` · last ${refreshedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}
            </span>
          </span>
        }
        actions={
          <Button
            size="md"
            variant="secondary"
            onClick={loadAssignments}
            busy={loading}
            className="min-h-12 px-5 text-sm font-semibold"
          >
            Refresh
          </Button>
        }
      />

      {/* At-a-glance counts */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "New orders", value: counts.newOrders, tone: "bg-sky-50 text-sky-800 border-sky-200" },
          { label: "Acknowledged", value: counts.acknowledged, tone: "bg-amber-50 text-amber-800 border-amber-200" },
          { label: "En route", value: counts.underWay, tone: "bg-violet-50 text-violet-800 border-violet-200" },
          { label: "On scene", value: counts.onScene, tone: "bg-emerald-50 text-emerald-800 border-emerald-200" },
        ].map((stat) => (
          <div key={stat.label} className={cx("rounded-xl border px-4 py-3", stat.tone)}>
            <div className="text-2xl font-extrabold tabular-nums">{stat.value}</div>
            <div className="text-xs font-semibold">{stat.label}</div>
          </div>
        ))}
      </div>

      {loading && <LoadingRows rows={3} />}

      {error && <ErrorState message={error} onRetry={loadAssignments} />}

      {actionError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-critical/30 bg-critical-soft px-4 py-3 text-sm text-critical">
          <span>
            <strong>{actionError.dispatchRef}:</strong> {actionError.message}
          </span>
          <Button size="sm" onClick={() => setActionError(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {!loading && !error && assignments.length === 0 && (
        <EmptyState title="No active field dispatches">
          You are not currently assigned to any active dispatches. When the DM dispatcher assigns an order to your team, it will appear here.
        </EmptyState>
      )}

      {!loading && sorted.length > 0 && (
        <div className="space-y-5">
          {sorted.map((item) => {
            const isBusy = busyId === item.dispatch_id;
            // OpenStreetMap, the same map provider the rest of ResQ uses; the responder picks the start point there.
            const directions = `https://www.openstreetmap.org/directions?route=%3B${item.latitude}%2C${item.longitude}`;
            return (
              <article
                key={item.dispatch_id}
                className={cx(
                  "overflow-hidden rounded-2xl border border-l-4 border-border bg-surface shadow-sm",
                  PRIORITY_EDGE[item.priority] ?? "border-l-slate-300",
                )}
              >
                <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3 sm:px-5">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span aria-hidden className="text-lg">{SCENARIO_ICON[item.scenario] ?? "⚑"}</span>
                      <h2 className="text-base font-bold text-foreground sm:text-lg">{item.dispatch_ref}</h2>
                      <Badge tone={priorityTone[item.priority] || "neutral"}>{item.priority}</Badge>
                      <Badge tone="info">{words(item.scenario)}</Badge>
                      {item.overdue && <Badge tone="critical">Overdue: acknowledge now</Badge>}
                    </div>
                    <p className="mt-0.5 text-xs text-muted">
                      Incident {item.incident_ref}{item.district ? ` · ${item.district}` : ""} · ordered {clock(item.dispatched_at)}
                    </p>
                  </div>
                  <div className="w-full sm:w-80">
                    <StatusSteps current={stepOf(item)} />
                  </div>
                </header>

                <div className="space-y-4 p-4 sm:p-5">
                  <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-start">
                    <div className="rounded-xl bg-surface-muted p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-muted">Target location</div>
                      <p className="mt-1 text-base font-medium text-foreground">{item.address_text}</p>
                      {item.landmark && <p className="text-sm text-muted">Landmark: {item.landmark}</p>}
                      <p className="mt-1 font-mono text-xs text-muted">GPS {item.latitude.toFixed(4)}, {item.longitude.toFixed(4)}</p>
                    </div>
                    <a
                      href={directions}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex min-h-12 items-center justify-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-5 text-sm font-semibold text-sky-800 transition hover:bg-sky-100"
                    >
                      <span aria-hidden>🧭</span> Navigate
                    </a>
                  </div>

                  {item.instructions && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-amber-800">Dispatcher instructions</div>
                      <p className="mt-1 text-sm text-foreground">{item.instructions}</p>
                    </div>
                  )}

                  {item.last_progress && item.last_progress_at && (
                    <p className="rounded-xl border border-border bg-surface-muted px-4 py-2.5 text-sm text-foreground">
                      <span className="font-semibold">Last report: {PROGRESS_LABEL[item.last_progress] ?? words(item.last_progress)}</span>
                      <span className="text-muted"> · {clock(item.last_progress_at)}</span>
                      {item.last_progress_note && <span className="block text-muted">{item.last_progress_note}</span>}
                    </p>
                  )}

                  {/* Glove-friendly action controls: the next step is the big button, the rest sit beside it. */}
                  <div className="border-t border-border pt-4">
                    <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">Next step</div>
                    {item.status === "REQUESTED" && (
                      <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
                        <Button
                          variant="primary"
                          className="min-h-14 text-base font-semibold"
                          busy={isBusy}
                          onClick={() => handleSimpleAction(item, `/api/field/dispatches/${item.dispatch_id}/acknowledgement`)}
                        >
                          ✓ Acknowledge order
                        </Button>
                        <Button
                          variant="danger"
                          className="min-h-14 text-base font-semibold"
                          disabled={isBusy}
                          onClick={() => openDialog("reject", item)}
                        >
                          Reject
                        </Button>
                      </div>
                    )}

                    {item.status === "ACKNOWLEDGED" && (
                      <Button
                        variant="primary"
                        className="min-h-14 w-full bg-emerald-600 text-base font-semibold hover:bg-emerald-500"
                        busy={isBusy}
                        onClick={() => handleSimpleAction(item, `/api/field/dispatches/${item.dispatch_id}/progress`, { status: "EN_ROUTE" })}
                      >
                        🚑 Set off: en route
                      </Button>
                    )}

                    {item.status === "DISPATCHED" && !item.on_scene_at && (
                      <div className="space-y-3">
                        <Button
                          variant="primary"
                          className="min-h-14 w-full text-base font-semibold"
                          busy={isBusy}
                          onClick={() => reportOnScene(item)}
                        >
                          📍 Arrived on scene
                        </Button>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <Button className="min-h-12 text-sm font-semibold" disabled={isBusy} onClick={() => openDialog("delay", item)}>
                            ⏱ Report a delay
                          </Button>
                          <Button className="min-h-12 text-sm font-semibold" disabled={isBusy} onClick={() => openDialog("backup", item)}>
                            ✚ Request backup
                          </Button>
                        </div>
                      </div>
                    )}

                    {item.status === "DISPATCHED" && item.on_scene_at && (
                      <div className="space-y-3">
                        <p className="text-sm text-muted">
                          On scene since {clock(item.on_scene_at)}. Keep dispatch informed, then close the order when the work is done.
                        </p>
                        <Button
                          variant="primary"
                          className="min-h-14 w-full bg-emerald-600 text-base font-semibold hover:bg-emerald-500"
                          disabled={isBusy}
                          onClick={() => openDialog("complete", item)}
                        >
                          ✓ Complete mission
                        </Button>
                        <div className="grid gap-3 sm:grid-cols-3">
                          <Button className="min-h-12 text-sm font-semibold" disabled={isBusy} onClick={() => openDialog("update", item)}>
                            📝 Situation update
                          </Button>
                          <Button className="min-h-12 text-sm font-semibold" disabled={isBusy} onClick={() => openDialog("delay", item)}>
                            ⏱ Report a delay
                          </Button>
                          <Button className="min-h-12 text-sm font-semibold" disabled={isBusy} onClick={() => openDialog("backup", item)}>
                            ✚ Request backup
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {/* Action Dialogs */}
      {activeDialog && (
        <Dialog
          open={Boolean(activeDialog)}
          onClose={() => setActiveDialog(null)}
          title={
            activeDialog.type === "reject"
              ? `Reject Dispatch ${activeDialog.dispatch.dispatch_ref}`
              : activeDialog.type === "delay"
              ? `Report Delay for ${activeDialog.dispatch.dispatch_ref}`
              : activeDialog.type === "backup"
              ? `Request Backup for ${activeDialog.dispatch.dispatch_ref}`
              : activeDialog.type === "update"
              ? `Situation Update for ${activeDialog.dispatch.dispatch_ref}`
              : `Complete Dispatch ${activeDialog.dispatch.dispatch_ref}`
          }
          footer={
            <div className="flex gap-2">
              <Button
                variant="ghost"
                className="min-h-11 px-4 text-sm font-medium"
                onClick={() => setActiveDialog(null)}
              >
                Cancel
              </Button>
              <Button
                variant={activeDialog.type === "reject" ? "danger" : "primary"}
                className="min-h-11 px-5 text-sm font-semibold"
                busy={busyId === activeDialog.dispatch.dispatch_id}
                onClick={handleDialogSubmit}
              >
                Submit
              </Button>
            </div>
          }
        >
          <div className="space-y-4">
            {dialogError && <p role="alert" className="text-xs text-critical font-medium">{dialogError}</p>}

            {activeDialog.type === "reject" && (
              <Field label="Rejection Reason" hint="Minimum 3 characters explaining why the team cannot respond.">
                {(id) => (
                  <Textarea
                    id={id}
                    required
                    value={dialogInput.text}
                    onChange={(e) => setDialogInput((prev) => ({ ...prev, text: e.target.value }))}
                    placeholder="e.g. Unit currently immobilized due to mechanical failure..."
                    rows={4}
                    className="min-h-[100px] text-base"
                  />
                )}
              </Field>
            )}

            {activeDialog.type === "delay" && (
              <Field label="Delay Note" hint="Describe the situation causing the delay.">
                {(id) => (
                  <Textarea
                    id={id}
                    value={dialogInput.text}
                    onChange={(e) => setDialogInput((prev) => ({ ...prev, text: e.target.value }))}
                    placeholder="e.g. Road blocked by fallen trees on Highway 8..."
                    rows={4}
                    className="min-h-[100px] text-base"
                  />
                )}
              </Field>
            )}

            {activeDialog.type === "backup" && (
              <>
                <Field label="Required Capability" hint="e.g. AMBULANCE, RESCUE_BOAT, HAZMAT, PUMP">
                  {(id) => (
                    <Input
                      id={id}
                      required
                      value={dialogInput.text}
                      onChange={(e) => setDialogInput((prev) => ({ ...prev, text: e.target.value }))}
                      placeholder="e.g. RESCUE_BOAT"
                      className="h-12 text-base font-mono"
                    />
                  )}
                </Field>
                <Field label="Additional Note (Optional)" hint="Provide context for the DM dispatcher.">
                  {(id) => (
                    <Textarea
                      id={id}
                      value={dialogInput.secondary}
                      onChange={(e) => setDialogInput((prev) => ({ ...prev, secondary: e.target.value }))}
                      placeholder="e.g. Flood water level rising rapidly; need 2 boats for stranded families..."
                      rows={3}
                      className="min-h-[80px] text-base"
                    />
                  )}
                </Field>
              </>
            )}

            {activeDialog.type === "update" && (
              <Field label="What is happening on scene?" hint="Dispatch sees this on the order straight away.">
                {(id) => (
                  <Textarea
                    id={id}
                    required
                    value={dialogInput.text}
                    onChange={(e) => setDialogInput((prev) => ({ ...prev, text: e.target.value }))}
                    placeholder="e.g. Water level falling; 12 residents moved to the school shelter, 6 still waiting."
                    rows={4}
                    className="min-h-[100px] text-base"
                  />
                )}
              </Field>
            )}

            {activeDialog.type === "complete" && (
              <>
                <Field label="Mission Summary" hint="At least 5 characters on the outcome of the dispatch.">
                  {(id) => (
                    <Textarea
                      id={id}
                      required
                      value={dialogInput.text}
                      onChange={(e) => setDialogInput((prev) => ({ ...prev, text: e.target.value }))}
                      placeholder="e.g. Extricated 4 casualties, transferred to primary health center. Area secured."
                      rows={4}
                      className="min-h-[100px] text-base"
                    />
                  )}
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="People evacuated" hint="Optional">
                    {(id) => (
                      <Input
                        id={id}
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={dialogInput.secondary}
                        onChange={(e) => setDialogInput((prev) => ({ ...prev, secondary: e.target.value }))}
                        className="h-12 text-base"
                      />
                    )}
                  </Field>
                  <Field label="People treated" hint="Optional">
                    {(id) => (
                      <Input
                        id={id}
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={dialogInput.third}
                        onChange={(e) => setDialogInput((prev) => ({ ...prev, third: e.target.value }))}
                        className="h-12 text-base"
                      />
                    )}
                  </Field>
                </div>
              </>
            )}
          </div>
        </Dialog>
      )}
    </div>
  );
}
