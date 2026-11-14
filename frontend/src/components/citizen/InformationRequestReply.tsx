"use client";

import { useId, useState } from "react";

import { replyToInformationRequest, type ReportData, type TimelineEntry } from "@/services/citizenApi";

/** Same limits as the backend (InformationReply: 3..2000 characters). */
export const REPLY_MIN_LENGTH = 3;
export const REPLY_MAX_LENGTH = 2000;

/** The dispatcher's most recent question, taken from the report timeline. */
export function latestInformationRequest(timeline: TimelineEntry[]): string | null {
  for (let i = timeline.length - 1; i >= 0; i -= 1) {
    const entry = timeline[i];
    if (entry.status === "NEEDS_INFORMATION" && entry.message) return entry.message;
  }
  return null;
}

const THEMES = {
  dark: {
    box: "border-orange-700/60 bg-orange-950/40 text-orange-200",
    heading: "text-orange-300",
    question: "border-orange-800/70 bg-slate-950/60 text-orange-100",
    input: "bg-slate-900 border-orange-800/80 text-white placeholder-slate-400",
    meta: "text-orange-200/80",
    error: "text-red-400",
    success: "text-emerald-400",
  },
  light: {
    box: "border-orange-300 bg-orange-50 text-orange-900",
    heading: "text-orange-700",
    question: "border-orange-200 bg-white text-slate-800",
    input: "bg-white border-orange-300 text-slate-900 placeholder-slate-400",
    meta: "text-orange-800/80",
    error: "text-red-600",
    success: "text-emerald-700",
  },
} as const;

type Props = {
  report: ReportData;
  /** Called after the backend accepted the reply (the report is then SUBMITTED again). */
  onReplied: () => void;
  theme?: keyof typeof THEMES;
  /** Extra classes for the outer box (spacing inside the parent card). */
  className?: string;
};

/**
 * Lets a citizen answer a dispatcher's NEEDS_INFORMATION request (issue #99).
 * POST /api/v1/me/incidents/{id}/information returns the report to SUBMITTED, so it goes back into
 * the verification queue. Backend errors (for example NOT_AWAITING_INFORMATION) are shown inline.
 */
export function InformationRequestReply({ report, onReplied, theme = "dark", className = "" }: Props) {
  const styles = THEMES[theme];
  const inputId = useId();
  const counterId = useId();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  if (sent) {
    return (
      <div role="status" aria-live="polite" className={`rounded-xl border p-4 text-xs font-semibold ${styles.box} ${styles.success} ${className}`}>
        ✓ Your reply was sent. The report is back in the verification queue.
      </div>
    );
  }
  if (report.status !== "NEEDS_INFORMATION") return null;

  const question = latestInformationRequest(report.timeline);
  const length = text.trim().length;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const message = text.trim();
    if (message.length < REPLY_MIN_LENGTH) {
      setError(`Write at least ${REPLY_MIN_LENGTH} characters.`);
      return;
    }
    if (message.length > REPLY_MAX_LENGTH) {
      setError(`Keep the reply under ${REPLY_MAX_LENGTH} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    const res = await replyToInformationRequest(report.id, message);
    setBusy(false);
    if (res.error) {
      setError(res.error);
      return;
    }
    setSent(true);
    setText("");
    onReplied();
  }

  return (
    <section aria-label="Reply to the information request" className={`rounded-xl border p-4 ${styles.box} ${className}`}>
      <p className={`mb-2 flex items-center gap-2 text-xs font-bold ${styles.heading}`}>
        <span aria-hidden="true">⚠️</span>
        The response team needs more information
      </p>
      {question ? (
        <blockquote className={`mb-3 rounded-lg border px-3 py-2 text-xs ${styles.question}`}>
          <span className="sr-only">Dispatcher asked: </span>
          {question}
        </blockquote>
      ) : (
        <p className={`mb-3 text-xs ${styles.meta}`}>
          Add details such as nearby landmarks, how many people are affected, or what has changed.
        </p>
      )}
      <form onSubmit={submit} className="space-y-2" noValidate>
        <label htmlFor={inputId} className="sr-only">
          Your reply to the dispatcher
        </label>
        <textarea
          id={inputId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={REPLY_MAX_LENGTH}
          rows={3}
          aria-describedby={counterId}
          aria-invalid={error ? true : undefined}
          placeholder="Your reply to the dispatcher…"
          className={`w-full min-h-[72px] rounded-lg border p-2.5 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 ${styles.input}`}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span id={counterId} className={`text-[11px] ${styles.meta}`}>
            {length}/{REPLY_MAX_LENGTH} characters (minimum {REPLY_MIN_LENGTH})
          </span>
          <button
            type="submit"
            disabled={busy || length < REPLY_MIN_LENGTH}
            className="min-h-[44px] cursor-pointer rounded-lg bg-orange-600 px-4 py-1.5 text-xs font-semibold text-white shadow transition hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
          >
            {busy ? "Sending…" : "Send reply"}
          </button>
        </div>
        {error && (
          <p role="alert" className={`text-[11px] font-medium ${styles.error}`}>
            {error}
          </p>
        )}
      </form>
    </section>
  );
}
