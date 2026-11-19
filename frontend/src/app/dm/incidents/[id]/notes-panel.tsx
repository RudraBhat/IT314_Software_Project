"use client";

import { useState } from "react";

import { Button, Card, EmptyState, ErrorState, LoadingRows, Textarea } from "@/components/ui";
import { useAction } from "@/components/use-action";
import { api, useQuery } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/format";

type Note = { note_id: string; body: string; created_at: string; author_name: string; mine: boolean };

const MAX = 1000;

/**
 * A shared log for the dispatch team on this incident, so the next shift can pick up where the last one
 * stopped. Notes are never shown to the reporter and cannot be edited or deleted; a correction is a new note.
 */
export function NotesPanel({ incidentId, closed }: { incidentId: string; closed: boolean }) {
  const notes = useQuery<{ items: Note[] }>(`incidents/${incidentId}/notes`);
  const { run, busy } = useAction();
  const [text, setText] = useState("");
  const trimmed = text.trim();

  async function add() {
    if (!trimmed) return;
    const saved = await run("note", () => api(`incidents/${incidentId}/notes`, { method: "POST", body: { body: trimmed } }), "Note added.");
    if (saved !== undefined) {
      setText("");
      notes.reload();
    }
  }

  const items = notes.data?.items ?? [];

  return (
    <Card
      title="Internal notes"
      subtitle={`For the dispatch team only; the reporter never sees these. Notes cannot be edited or deleted.${closed ? " You can still add notes after closure." : ""}`}
    >
      <div className="space-y-2">
        <label className="block">
          <span className="sr-only">Add a note for the next shift</span>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={MAX}
            placeholder="What should the next shift know? For example who was called and what was agreed."
          />
        </label>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted">{text.length} / {MAX}</span>
          <Button size="sm" variant="primary" onClick={add} busy={busy === "note"} disabled={!trimmed}>Add note</Button>
        </div>
      </div>

      <div className="mt-4">
        {notes.error && !notes.data && <ErrorState message={notes.error} onRetry={notes.reload} />}
        {notes.loading && !notes.data && <LoadingRows rows={2} />}
        {notes.data && items.length === 0 && <EmptyState title="No notes yet." />}
        {items.length > 0 && (
          <ul className={`divide-y divide-border ${notes.loading ? "opacity-60" : ""}`}>
            {items.map((n) => (
              <li key={n.note_id} className="py-3">
                <p className="whitespace-pre-wrap text-sm">{n.body}</p>
                <p className="mt-1 text-xs text-muted" title={formatDateTime(n.created_at)}>
                  {n.mine ? "You" : n.author_name} · {timeAgo(n.created_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
