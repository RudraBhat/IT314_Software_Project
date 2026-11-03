"use client";

import { useState } from "react";

import { AiBadge, PriorityBadge } from "@/components/badges";
import { useAction } from "@/components/use-action";
import { Badge, Button, Card, Dialog, ErrorState, Field, LoadingRows, Notice, Select, Textarea } from "@/components/ui";
import { ApiError, api, useQuery } from "@/lib/api";
import { PRIORITIES, SCENARIOS, formatDateTime, label, scenarioLabel } from "@/lib/format";

import type { IncidentDetail } from "./types";

type Rec = {
  recommendation_id: string;
  model_name: string;
  status: "GENERATED" | "LOW_CONFIDENCE" | "UNAVAILABLE" | "UNSAFE_OUTPUT";
  suggested_scenario: string | null;
  suggested_priority: string | null;
  confidence: string | null;
  uncertainty_note: string | null;
  factors: { items?: { name: string; detail?: string | null; weight?: number | null }[]; raw_scenario?: string } | null;
  human_action: string | null;
  human_rationale: string | null;
  decided_at: string | null;
  decided_by_name: string | null;
  created_at: string;
  out_of_scope: boolean;
};

const statusText: Record<Rec["status"], string> = {
  GENERATED: "Suggestion",
  LOW_CONFIDENCE: "Low confidence",
  UNAVAILABLE: "AI unavailable",
  UNSAFE_OUTPUT: "Output discarded",
};

export function AiPanel({ incident, reload }: { incident: IncidentDetail; reload: () => void }) {
  const recs = useQuery<{ items: Rec[] }>(`incidents/${incident.incident_id}/ai-recommendations`);
  const { run, busy } = useAction(reload);
  const [notice, setNotice] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<Rec | null>(null);

  async function requestTriage() {
    setNotice(null);
    try {
      await api(`incidents/${incident.incident_id}/ai-triage`, { method: "POST" });
    } catch (e) {
      // 503 means no AI service; the attempt is recorded and manual triage continues.
      if (e instanceof ApiError && e.code === "AI_UNAVAILABLE") setNotice(e.message);
      else setNotice(e instanceof Error ? e.message : "AI request failed.");
    }
    recs.reload();
  }

  return (
    <Card
      title={<span className="flex items-center gap-2">AI triage <AiBadge /></span>}
      subtitle="AI suggestion, not verified. A person makes every decision."
      actions={
        incident.allowed_actions.ai_triage && (
          <Button size="sm" busy={busy === "ai"} onClick={() => run("ai", requestTriage)}>
            Request suggestion
          </Button>
        )
      }
    >
      {notice && <div className="mb-3"><Notice tone="medium">{notice}</Notice></div>}
      {recs.error && <ErrorState message={recs.error} onRetry={recs.reload} />}
      {recs.loading && !recs.data && <LoadingRows rows={2} />}
      {recs.data && recs.data.items.length === 0 && (
        <p className="text-sm text-muted">No AI suggestions yet. Manual triage is always available.</p>
      )}
      <ul className="space-y-3">
        {recs.data?.items.map((r) => (
          <li key={r.recommendation_id} className="rounded-lg border border-ai/25 bg-ai-soft/40 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral">Not verified</Badge>
              <Badge tone={r.status === "GENERATED" ? "ai" : r.status === "LOW_CONFIDENCE" ? "medium" : "neutral"}>{statusText[r.status]}</Badge>
              {r.out_of_scope && <Badge tone="critical">Out of scope</Badge>}
              <span className="text-xs text-muted">{r.model_name} · {formatDateTime(r.created_at)}</span>
            </div>
            {(r.suggested_scenario || r.suggested_priority) && (
              <dl className="mt-2 grid grid-cols-2 gap-2">
                <div>
                  <dt className="text-xs text-muted">Suggested scenario</dt>
                  <dd>{r.suggested_scenario ? scenarioLabel[r.suggested_scenario] : <span className="text-muted">—</span>}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Suggested priority</dt>
                  <dd>{r.suggested_priority ? <PriorityBadge priority={r.suggested_priority} /> : "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Confidence</dt>
                  <dd className="tabular-nums">{r.confidence !== null ? `${Math.round(Number(r.confidence) * 100)}%` : "—"}</dd>
                </div>
              </dl>
            )}
            {r.out_of_scope && r.factors?.raw_scenario && (
              <p className="mt-2 text-xs">AI suggested “{r.factors.raw_scenario}”, which is not a supported scenario. Triage manually.</p>
            )}
            {r.uncertainty_note && <p className="mt-2 text-xs text-muted">{r.uncertainty_note}</p>}
            {!!r.factors?.items?.length && (
              <ul className="mt-2 list-disc pl-5 text-xs">
                {r.factors.items.map((f, i) => (
                  <li key={i}>
                    {f.name}
                    {f.detail ? ` — ${f.detail}` : ""}
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3 border-t border-ai/20 pt-2">
              {r.human_action ? (
                <p className="text-xs">
                  <strong>Human decision: {label(r.human_action)}</strong> by {r.decided_by_name ?? "staff"} · {formatDateTime(r.decided_at)}
                  {r.human_rationale && <span className="block text-muted">{r.human_rationale}</span>}
                </p>
              ) : r.status === "GENERATED" || r.status === "LOW_CONFIDENCE" ? (
                incident.status !== "CLOSED" && <Button size="sm" onClick={() => setDeciding(r)}>Accept, modify or reject…</Button>
              ) : (
                <p className="text-xs text-muted">Nothing to decide. Continue with manual triage.</p>
              )}
            </div>
          </li>
        ))}
      </ul>
      {deciding && (
        <DecisionDialog
          rec={deciding}
          incident={incident}
          onClose={() => setDeciding(null)}
          onDone={() => {
            setDeciding(null);
            recs.reload();
            reload();
          }}
        />
      )}
    </Card>
  );
}

function DecisionDialog({ rec, incident, onClose, onDone }: { rec: Rec; incident: IncidentDetail; onClose: () => void; onDone: () => void }) {
  const { run, busy } = useAction();
  const [action, setAction] = useState<"ACCEPTED" | "MODIFIED" | "REJECTED">("ACCEPTED");
  const [rationale, setRationale] = useState("");
  const [scenario, setScenario] = useState(rec.suggested_scenario ?? "");
  const [priority, setPriority] = useState(rec.suggested_priority ?? "");
  const [apply, setApply] = useState(false);
  const canApply = action !== "REJECTED" && !(action === "ACCEPTED" && rec.out_of_scope);

  async function submit() {
    const ok = await run(
      "decide",
      () =>
        api(`incidents/${incident.incident_id}/ai-recommendations/${rec.recommendation_id}/decision`, {
          method: "POST",
          body: {
            action,
            rationale,
            final_scenario: action === "MODIFIED" && scenario ? scenario : undefined,
            final_priority: action === "MODIFIED" && priority ? priority : undefined,
            apply_to_incident: canApply && apply,
            version: canApply && apply ? incident.version : undefined,
          },
        }),
      apply && canApply ? "Decision recorded and applied to the incident" : "Decision recorded",
    );
    if (ok !== undefined) onDone();
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Decide on AI suggestion"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={rationale.trim().length < 3} busy={busy === "decide"} onClick={submit}>
            Record decision
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        <fieldset className="space-y-2">
          <legend className="mb-1 text-xs font-medium text-muted">Your decision</legend>
          {(["ACCEPTED", "MODIFIED", "REJECTED"] as const).map((x) => (
            <label key={x} className="flex items-center gap-2">
              <input type="radio" name="ai-action" checked={action === x} onChange={() => setAction(x)} />
              {label(x)}
            </label>
          ))}
        </fieldset>
        {action === "MODIFIED" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Final scenario">
              {(id) => (
                <Select id={id} value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  <option value="">Keep suggestion</option>
                  {SCENARIOS.map((s) => <option key={s} value={s}>{scenarioLabel[s]}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Final priority">
              {(id) => (
                <Select id={id} value={priority} onChange={(e) => setPriority(e.target.value)}>
                  <option value="">Keep suggestion</option>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
                </Select>
              )}
            </Field>
          </div>
        )}
        <Field label="Rationale" hint="Required. Stored separately from the AI output.">
          {(id) => <Textarea id={id} value={rationale} onChange={(e) => setRationale(e.target.value)} maxLength={2000} />}
        </Field>
        {canApply && (
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={apply} onChange={(e) => setApply(e.target.checked)} />
            <span>
              Also apply the final scenario and priority to the incident.
              <span className="block text-xs text-muted">This does not verify, reject or dispatch the incident.</span>
            </span>
          </label>
        )}
      </div>
    </Dialog>
  );
}
