"use client";

import { useEffect, useState } from "react";

import { Badge, Button, EmptyState, ErrorState, LoadingRows, cx, type Tone } from "@/components/ui";
import { timeAgo } from "@/lib/format";
import { fetchPublicAlerts, type PublicAlert } from "@/services/citizenApi";

const SEVERITY_TONE: Record<string, Tone> = { EXTREME: "critical", SEVERE: "high", MODERATE: "medium", MINOR: "low", CRITICAL: "critical", HIGH: "high", MEDIUM: "medium", LOW: "low" };
const SEEN_KEY = "drch.alerts.seen";

function readSeen(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

/** Early warnings and external alerts (GET /public/alerts) with unread / simulated filters. */
export function AlertsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [alerts, setAlerts] = useState<PublicAlert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "unread" | "simulated">("all");
  const [seen, setSeen] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load when the drawer opens
    setSeen(readSeen());
    fetchPublicAlerts().then((res) => {
      if (cancelled) return;
      if (res.data) { setAlerts(res.data); setError(null); }
      else setError(res.error ?? "Alerts could not be loaded.");
    });
    return () => { cancelled = true; };
  }, [open]);

  function markSeen(ids: string[]) {
    const next = new Set([...seen, ...ids]);
    setSeen(next);
    try { localStorage.setItem(SEEN_KEY, JSON.stringify([...next])); } catch { /* storage unavailable: unread state is per-visit only */ }
  }

  if (!open) return null;
  const shown = (alerts ?? []).filter((a) => filter === "all" || (filter === "unread" ? !seen.has(a.id) : a.is_fallback));
  const unread = (alerts ?? []).filter((a) => !seen.has(a.id));

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Alerts">
      <button className="absolute inset-0 bg-black/60" aria-label="Close alerts" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-border bg-surface shadow-xl">
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-base font-semibold">Alerts</h2>
          <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
        </header>
        <div className="flex items-center gap-2 border-b border-border px-5 py-2 text-xs">
          {(["all", "unread", "simulated"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={cx("rounded-full px-3 py-1", filter === f ? "bg-sky-500/15 font-semibold text-sky-300" : "text-muted hover:bg-surface-muted")}>
              {f === "all" ? "All" : f === "unread" ? `Unread (${unread.length})` : "Simulated"}
            </button>
          ))}
          <Button size="sm" variant="ghost" className="ml-auto" disabled={unread.length === 0} onClick={() => markSeen(unread.map((a) => a.id))}>Mark all read</Button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {error && <ErrorState message={error} />}
          {!alerts && !error && <LoadingRows rows={4} />}
          {alerts && shown.length === 0 && <EmptyState title="No alerts to show." />}
          <ul className="space-y-3">
            {shown.map((a) => (
              <li key={a.id} className={cx("rounded-lg border border-border p-3", !seen.has(a.id) && "border-l-4 border-l-sky-500")}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={SEVERITY_TONE[a.severity.toUpperCase()] ?? "neutral"}>{a.severity}</Badge>
                  {a.is_fallback && <Badge tone="info">Simulated feed</Badge>}
                  <span className="ml-auto text-xs text-muted">{a.timestamp ? timeAgo(a.timestamp) : ""}</span>
                </div>
                <p className="mt-2 text-sm font-medium capitalize">{a.title}</p>
                <p className="mt-0.5 text-xs text-muted">Source: {a.source}</p>
                {!seen.has(a.id) && <Button size="sm" variant="ghost" className="mt-2" onClick={() => markSeen([a.id])}>Mark read</Button>}
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
