"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, PageHeader, Textarea, type Tone } from "@/components/ui";

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
};

type DialogType = "reject" | "delay" | "backup" | "complete";

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

export default function FieldPage() {
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [activeDialog, setActiveDialog] = useState<ActiveDialog>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [dialogInput, setDialogInput] = useState({ text: "", secondary: "" });

  const loadAssignments = useCallback(async () => {
    try {
      const res = await fetch("/api/field/assignments", { cache: "no-store" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error?.message ?? `Server responded with ${res.status}`);
      }
      const data = await res.json();
      setAssignments(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load field assignments");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    const init = async () => {
      try {
        const res = await fetch("/api/field/assignments", { cache: "no-store" });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data?.error?.message ?? `Server responded with ${res.status}`);
        }
        const data = await res.json();
        if (!ignore) {
          setAssignments(Array.isArray(data) ? data : []);
          setError(null);
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
    init();
    return () => {
      ignore = true;
    };
  }, []);

  const handleSimpleAction = async (dispatchId: string, url: string, body?: unknown) => {
    setBusyId(dispatchId);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: body ? JSON.stringify(body) : "{}",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error?.message ?? "Action failed");
      }
      await loadAssignments();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleDialogSubmit = async () => {
    if (!activeDialog) return;
    setDialogError(null);
    const { type, dispatch } = activeDialog;

    try {
      if (type === "reject") {
        if (dialogInput.text.trim().length < 3) {
          setDialogError("Rejection reason must be at least 3 characters.");
          return;
        }
        await handleSimpleAction(
          dispatch.dispatch_id,
          `/api/field/dispatches/${dispatch.dispatch_id}/rejection`,
          { reason: dialogInput.text.trim() }
        );
      } else if (type === "delay") {
        await handleSimpleAction(
          dispatch.dispatch_id,
          `/api/field/dispatches/${dispatch.dispatch_id}/progress`,
          { status: "DELAYED", note: dialogInput.text.trim() || undefined }
        );
      } else if (type === "backup") {
        if (dialogInput.text.trim().length < 2) {
          setDialogError("Required capability must be at least 2 characters.");
          return;
        }
        await handleSimpleAction(
          dispatch.dispatch_id,
          `/api/field/dispatches/${dispatch.dispatch_id}/team-requests`,
          {
            required_capability: dialogInput.text.trim(),
            note: dialogInput.secondary.trim() || undefined,
          }
        );
      } else if (type === "complete") {
        if (dialogInput.text.trim().length < 3) {
          setDialogError("Completion summary must be at least 3 characters.");
          return;
        }
        await handleSimpleAction(
          dispatch.dispatch_id,
          `/api/field/dispatches/${dispatch.dispatch_id}/completion`,
          { summary: dialogInput.text.trim() }
        );
      }
      setActiveDialog(null);
      setDialogInput({ text: "", secondary: "" });
    } catch (err: unknown) {
      setDialogError(err instanceof Error ? err.message : "Failed to submit");
    }
  };

  const openDialog = (type: DialogType, dispatch: Assignment) => {
    setDialogError(null);
    setDialogInput({ text: "", secondary: "" });
    setActiveDialog({ type, dispatch });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Active Assignments"
        description="Your team's active dispatches in the field. Glove-friendly controls."
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

      {loading && <LoadingRows rows={3} />}

      {error && <ErrorState message={error} onRetry={loadAssignments} />}

      {!loading && !error && assignments.length === 0 && (
        <EmptyState title="No active field dispatches">
          You are not currently assigned to any active dispatches. When the DM dispatcher assigns an order to your team, it will appear here.
        </EmptyState>
      )}

      {!loading && assignments.length > 0 && (
        <div className="space-y-6">
          {assignments.map((item) => {
            const isBusy = busyId === item.dispatch_id;
            return (
              <Card
                key={item.dispatch_id}
                title={
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-bold text-foreground sm:text-lg">{item.dispatch_ref}</span>
                    <Badge tone={priorityTone[item.priority] || "neutral"}>{item.priority}</Badge>
                    <Badge tone="info">{item.scenario.toUpperCase()}</Badge>
                    <span className="rounded bg-surface-muted px-2 py-0.5 text-xs font-mono font-medium text-muted">
                      {item.status}
                    </span>
                  </div>
                }
                subtitle={`Incident: ${item.incident_ref} · Dispatched ${new Date(item.dispatched_at).toLocaleTimeString()}`}
                className="overflow-hidden border-2 border-border shadow-md"
              >
                <div className="space-y-4">
                  {/* Incident details */}
                  <div className="rounded-lg bg-surface-muted/50 p-4">
                    <div className="text-xs font-semibold uppercase tracking-wider text-muted">Target Location</div>
                    <p className="mt-1 text-base font-medium text-foreground">{item.address_text}</p>
                    {item.landmark && <p className="text-xs text-muted">Landmark: {item.landmark}</p>}
                    <p className="mt-1 font-mono text-xs text-muted">GPS: {item.latitude.toFixed(4)}, {item.longitude.toFixed(4)}</p>
                  </div>

                  {item.instructions && (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-amber-500">Dispatcher Instructions</div>
                      <p className="mt-1 text-sm text-foreground">{item.instructions}</p>
                    </div>
                  )}

                  {/* Glove-friendly action controls */}
                  <div className="border-t border-border pt-4">
                    <div className="text-xs font-semibold uppercase tracking-wider text-muted mb-3">Available Actions</div>
                    <div className="flex flex-wrap gap-3">
                      {item.status === "REQUESTED" && (
                        <>
                          <Button
                            variant="primary"
                            className="min-h-12 flex-1 min-w-[140px] text-base font-semibold"
                            busy={isBusy}
                            onClick={() =>
                              handleSimpleAction(
                                item.dispatch_id,
                                `/api/field/dispatches/${item.dispatch_id}/acknowledgement`
                              )
                            }
                          >
                            Acknowledge
                          </Button>
                          <Button
                            variant="danger"
                            className="min-h-12 flex-1 min-w-[140px] text-base font-semibold"
                            disabled={isBusy}
                            onClick={() => openDialog("reject", item)}
                          >
                            Reject
                          </Button>
                        </>
                      )}

                      {item.status === "ACKNOWLEDGED" && (
                        <Button
                          variant="primary"
                          className="min-h-12 w-full text-base font-semibold bg-emerald-600 hover:bg-emerald-500"
                          busy={isBusy}
                          onClick={() =>
                            handleSimpleAction(
                              item.dispatch_id,
                              `/api/field/dispatches/${item.dispatch_id}/progress`,
                              { status: "EN_ROUTE" }
                            )
                          }
                        >
                          En Route
                        </Button>
                      )}

                      {item.status === "DISPATCHED" && (
                        <>
                          <Button
                            variant="primary"
                            className="min-h-12 flex-1 min-w-[130px] text-sm sm:text-base font-semibold bg-blue-600 hover:bg-blue-500"
                            busy={isBusy}
                            onClick={() =>
                              handleSimpleAction(
                                item.dispatch_id,
                                `/api/field/dispatches/${item.dispatch_id}/progress`,
                                { status: "ON_SCENE" }
                              )
                            }
                          >
                            On Scene
                          </Button>
                          <Button
                            variant="secondary"
                            className="min-h-12 flex-1 min-w-[130px] text-sm sm:text-base font-semibold"
                            disabled={isBusy}
                            onClick={() => openDialog("delay", item)}
                          >
                            Delayed
                          </Button>
                          <Button
                            variant="secondary"
                            className="min-h-12 flex-1 min-w-[140px] text-sm sm:text-base font-semibold"
                            disabled={isBusy}
                            onClick={() => openDialog("backup", item)}
                          >
                            Request Backup
                          </Button>
                          <Button
                            variant="primary"
                            className="min-h-12 flex-1 min-w-[140px] text-sm sm:text-base font-semibold bg-emerald-600 hover:bg-emerald-500"
                            disabled={isBusy}
                            onClick={() => openDialog("complete", item)}
                          >
                            Complete
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
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
              : `Complete Dispatch ${activeDialog.dispatch.dispatch_ref}`
          }
          footer={
            <div className="flex gap-2">
              <Button
                variant="ghost"
                className="min-h-10 px-4 text-sm"
                onClick={() => setActiveDialog(null)}
              >
                Cancel
              </Button>
              <Button
                variant={activeDialog.type === "reject" ? "danger" : "primary"}
                className="min-h-10 px-5 text-sm font-semibold"
                busy={busyId === activeDialog.dispatch.dispatch_id}
                onClick={handleDialogSubmit}
              >
                Submit
              </Button>
            </div>
          }
        >
          <div className="space-y-4">
            {dialogError && <p className="text-xs text-critical font-medium">{dialogError}</p>}

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

            {activeDialog.type === "complete" && (
              <Field label="Mission Summary" hint="Minimum 3 characters detailing the outcome of the dispatch.">
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
            )}
          </div>
        </Dialog>
      )}
    </div>
  );
}
