"use client";

import { useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui";
import { api, useQuery } from "@/lib/api";

interface SourceHealth {
  source: string;
  status: "SUCCESS" | "FAILED" | "RUNNING" | "PREVIEW" | string;
  items_fetched: number;
  items_stored: number;
  started_at: string;
  finished_at: string | null;
  runs_24h: number;
  successes_24h: number;
  failures_24h: number;
  last_error: string | null;
  last_error_at: string | null;
}

interface IngestionHealth {
  sources: SourceHealth[];
  history_available: boolean;
}

interface PollResult {
  source: string;
  status: string;
  items_fetched: number;
  items_stored: number;
  message: string | null;
}

const statusTone = (status: string) => status === "FAILED" ? "critical" : status === "SUCCESS" ? "low" : "info";

export default function IngestionHealthPage() {
  const { data, error, reload, loading } = useQuery<IngestionHealth>("ingestion/health", {});
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [pollSummary, setPollSummary] = useState<string | null>(null);

  const pollNow = async () => {
    setPolling(true);
    setPollError(null);
    setPollSummary(null);
    try {
      const results = await api<PollResult[]>("ingestion/poll", { method: "POST" });
      setPollSummary(results.map((r) => `${r.source}: ${r.status} (${r.items_stored}/${r.items_fetched})`).join(" · "));
      await reload();
    } catch (err) {
      setPollError(err instanceof Error ? err.message : "The poll could not be started.");
    } finally {
      setPolling(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ingestion health"
        description="Recent official alert and simulated replay runs. Polling never publishes an incident; dispatch review is still required."
        actions={<Button onClick={pollNow} busy={polling}>Poll now</Button>}
      />
      {pollSummary && <p role="status" className="rounded-lg border border-border bg-surface p-3 text-sm text-foreground">{pollSummary}</p>}
      {pollError && <ErrorState message={pollError} onRetry={pollNow} />}
      {error && !data && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingRows rows={4} />}
      {data && !data.history_available && <EmptyState title="Run history is unavailable">Connect the backend to its database to see ingestion health.</EmptyState>}
      {data?.history_available && data.sources.length === 0 && <EmptyState title="No ingestion runs yet">The scheduler records each source the first time it polls. You can also start a poll now.</EmptyState>}
      {data?.history_available && data.sources.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-2">
          {data.sources.map((source) => (
            <Card key={source.source}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-foreground">{source.source}</h2>
                  <p className="mt-1 text-xs text-muted">Last run {source.started_at ? new Date(source.started_at).toLocaleString() : "unknown"}</p>
                </div>
                <Badge tone={statusTone(source.status)}>{source.status}</Badge>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-xs text-muted">Fetched / stored</dt><dd className="mt-1 font-medium">{source.items_fetched} / {source.items_stored}</dd></div>
                <div><dt className="text-xs text-muted">Runs in 24 hours</dt><dd className="mt-1 font-medium">{source.runs_24h} <span className="text-xs text-muted">({source.successes_24h} ok, {source.failures_24h} failed)</span></dd></div>
              </dl>
              {source.last_error && <div className="mt-4 rounded-md border border-critical/30 bg-critical/5 p-3 text-xs"><p className="font-semibold text-critical">Last error</p><p className="mt-1 break-words text-foreground">{source.last_error}</p></div>}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
