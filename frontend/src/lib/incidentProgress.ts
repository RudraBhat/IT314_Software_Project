/**
 * What the citizen's progress bar should show for a report.
 *
 * The bar has four stages: Submitted, Verified, Dispatched, Resolved. A report that was rejected, or closed
 * without ever being resolved, did not travel that path, so it gets a plain explanation instead of a bar
 * that would imply it did. The decision looks at the report's history, not only its current status.
 */

const STAGE_OF: Record<string, number> = {
  SUBMITTED: 1,
  NEEDS_INFORMATION: 1,
  VERIFIED: 2,
  DISPATCHED: 3,
  RESOLVED: 4,
};

export type IncidentProgress =
  | { kind: "steps"; step: number }
  | { kind: "ended"; note: string };

export function incidentProgress(status: string, timeline: ReadonlyArray<{ status: string }>): IncidentProgress {
  const current = status.toUpperCase();
  if (current === "REJECTED") {
    return { kind: "ended", note: "The response team did not accept this report. The reason is in the updates below." };
  }
  if (current === "CLOSED") {
    const wasResolved = timeline.some((entry) => entry.status.toUpperCase() === "RESOLVED");
    return wasResolved
      ? { kind: "steps", step: 4 }
      : { kind: "ended", note: "This report was closed without being marked resolved. The closing note is in the updates below." };
  }
  return { kind: "steps", step: STAGE_OF[current] ?? 1 };
}
