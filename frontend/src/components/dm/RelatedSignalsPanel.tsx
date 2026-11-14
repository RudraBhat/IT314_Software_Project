"use client";

import { Badge, Card, ErrorState, LoadingRows } from "@/components/ui";

export interface RelatedSignal {
  signal_id: string;
  source: string;
  content_text: string;
  received_at: string;
  source_created_at?: string | null;
  match_time_basis?: "source" | "received_fallback";
  latitude: number | null;
  longitude: number | null;
  location_text: string | null;
  location_precision?: string;
  ai_label: string | null;
  is_simulated: boolean;
}

export interface RelatedPair {
  signal_a: RelatedSignal;
  signal_b: RelatedSignal;
  distance_m: number;
  minutes_apart: number;
  label_agreement: "match" | "conflict" | "unknown";
  ranking_score: number;
  reasons: string[];
  warnings: string[];
}

export interface RelatedGroup {
  group_id: string;
  signal_ids: string[];
  size: number;
  centre: { latitude: number; longitude: number };
  max_pairwise_distance_m: number;
  time_range: { start: string; end: string; span_minutes: number };
}

export interface RelatedSignalsResponse {
  note: string;
  rules: { radius_m: number; window_hours: number };
  pairs: RelatedPair[];
  pairs_total: number;
  groups: RelatedGroup[];
  unlocated: Array<RelatedSignal & {
    location_missing: boolean;
    location_approximate: boolean;
    note: string;
  }>;
  unlocated_total: number;
  truncated: boolean;
}

function SignalSummary({ title, signal }: { title: string; signal: RelatedSignal }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-surface-muted/40 p-3">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold uppercase tracking-wider text-muted">{title}</span>
        <span className="font-semibold text-foreground">{signal.source}</span>
        <span className="text-muted">{new Date(signal.source_created_at ?? signal.received_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</span>
        {signal.is_simulated && <Badge tone="medium">SIMULATED</Badge>}
        {signal.match_time_basis === "received_fallback" && <Badge tone="medium">Receipt time fallback</Badge>}
        {signal.ai_label ? <Badge tone="info">{signal.ai_label}</Badge> : <span className="text-muted">No label</span>}
      </div>
      <p className="line-clamp-3 text-sm text-foreground">{signal.content_text}</p>
      <p className="mt-1 font-mono text-[11px] text-muted">
        {signal.location_text ? `${signal.location_text} · ` : ""}
        {signal.latitude !== null && signal.longitude !== null
          ? `${signal.latitude.toFixed(4)}, ${signal.longitude.toFixed(4)}${signal.location_precision === "DISTRICT_CENTROID" ? " (approximate)" : ""}`
          : "Location missing"}
      </p>
    </div>
  );
}

/**
 * Advisory "possibly the same event" suggestions (GET /dm/signals/related).
 * Read-only: promoting or dismissing stays with the dispatcher in the table below.
 */
export function RelatedSignalsPanel({
  data,
  error,
  loading,
  onRetry,
}: {
  data?: RelatedSignalsResponse;
  error: string | null;
  loading: boolean;
  onRetry: () => void;
}) {
  if (error && !data) return <ErrorState message={error} onRetry={onRetry} />;
  if (loading && !data) return <LoadingRows rows={2} />;
  if (!data) return null;

  return (
    <Card
      title="Possibly related alerts"
      subtitle={`Advisory only: pending alerts with precise locations within ${data.rules.radius_m} m and ${data.rules.window_hours} h of each other. A dispatcher decides what, if anything, they mean.`}
      actions={<Badge tone="ai">Heuristic ranking</Badge>}
    >
      <div className="space-y-4">
        <p className="text-xs text-muted">{data.note}</p>

        {data.unlocated_total > 0 && (
          <div className="space-y-2 rounded-lg border border-border bg-surface-muted/30 p-3">
            <p className="text-xs text-critical">
              {data.unlocated_total} pending alert{data.unlocated_total === 1 ? "" : "s"} have no precise point or only an approximate candidate location. They are never grouped by proximity.
            </p>
            <ul className="space-y-2">
              {data.unlocated.slice(0, 10).map((signal) => (
                <li key={signal.signal_id} className="rounded-md border border-border bg-surface p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-foreground">{signal.source}</span>
                    {signal.location_approximate && <Badge tone="medium">Approximate location</Badge>}
                    {signal.location_missing && <Badge tone="high">Missing location</Badge>}
                  </div>
                  <p className="mt-1 line-clamp-2 text-foreground">{signal.content_text}</p>
                  <p className="mt-1 text-muted">{signal.location_text ?? signal.note}</p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {data.pairs.length === 0 && <p className="text-sm text-muted">No related pending alerts found right now.</p>}

        {data.groups.length > 0 && (
          <ul className="flex flex-wrap gap-2 text-xs">
            {data.groups.slice(0, 6).map((g) => (
              <li key={g.group_id} className="rounded-md border border-border px-2 py-1 text-muted">
                <span className="font-semibold text-foreground">{g.group_id}</span> · {g.size} alerts · all within {g.max_pairwise_distance_m} m
                · timestamped over {g.time_range.span_minutes} min
              </li>
            ))}
          </ul>
        )}

        <ul className="space-y-3">
          {data.pairs.map((p) => (
            <li key={`${p.signal_a.signal_id}-${p.signal_b.signal_id}`} className="rounded-lg border border-border p-3">
              <div className="grid gap-3 md:grid-cols-2">
                <SignalSummary title="Original" signal={p.signal_a} />
                <SignalSummary title="Possibly related" signal={p.signal_b} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <Badge tone="neutral">Ranking hint {p.ranking_score.toFixed(0)}/100 · not a probability</Badge>
                <Badge tone={p.label_agreement === "conflict" ? "high" : "neutral"}>
                  Labels: {p.label_agreement === "match" ? "same" : p.label_agreement === "conflict" ? "differ" : "unknown"}
                </Badge>
                <span className="text-muted">{p.reasons.join(" · ")}</span>
              </div>
              {p.warnings.length > 0 && <p className="mt-1 text-xs text-high">{p.warnings.join(" · ")}</p>}
            </li>
          ))}
        </ul>

        {(data.truncated || data.pairs_total > data.pairs.length) && (
          <p className="text-xs text-muted">
            Showing the {data.pairs.length} highest-ranked of {data.pairs_total} suggestions
            {data.truncated ? " (candidate search was capped; there may be more)" : ""}.
          </p>
        )}
      </div>
    </Card>
  );
}
