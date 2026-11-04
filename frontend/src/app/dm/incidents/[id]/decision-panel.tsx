"use client";

import { useState } from "react";

import { useAction } from "@/components/use-action";
import { Button, Card, Dialog, Field, Notice, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { PRIORITIES, label } from "@/lib/format";

import { useStaff } from "../../shell";
import type { IncidentDetail } from "./types";

type Mode = null | "verify" | "info" | "priority" | "resolve" | "close" | "reopen";

const MIN = 3;

export function DecisionPanel({ incident, reload }: { incident: IncidentDetail; reload: () => void }) {
  const { can } = useStaff();
  const { run, busy } = useAction(reload);
  const [mode, setMode] = useState<Mode>(null);
  const [decision, setDecision] = useState<"VERIFIED" | "REJECTED" | "NEEDS_INFORMATION">("VERIFIED");
  const [priority, setPriority] = useState(incident.verified_priority ?? "");
  const [text, setText] = useState("");
  const [summary, setSummary] = useState("");
  const [override, setOverride] = useState(false);
  const [overrideText, setOverrideText] = useState("");
  const a = incident.allowed_actions;
  const deps = incident.open_dependencies;
  const hasDeps = deps.dispatches.length + deps.allocations.length > 0;
  const base = `incidents/${incident.incident_id}`;
  // A field team reported completion and nothing is still in flight: prompt the dispatcher to confirm resolution.
  const completed = incident.dispatches.filter((d) => d.status === "COMPLETED");
  const awaitingResolution = a.resolve && !hasDeps && completed.length > 0;

  function open(next: Mode) {
    setText("");
    setSummary("");
    setOverride(false);
    setOverrideText("");
    setPriority(incident.verified_priority ?? "");
    setDecision("VERIFIED");
    setMode(next);
  }

  async function submit() {
    const version = incident.version;
    const calls: Record<Exclude<Mode, null>, [() => Promise<unknown>, string]> = {
      verify: [
        () =>
          api(`${base}/verification`, {
            method: "POST",
            body: { decision, rationale: text, version, priority: decision === "VERIFIED" && priority ? priority : undefined },
          }),
        `Decision recorded: ${label(decision)}`,
      ],
      info: [() => api(`${base}/information-requests`, { method: "POST", body: { question: text, version } }), "Information requested from the reporter"],
      priority: [() => api(`${base}/priority`, { method: "PUT", body: { priority, rationale: text, version } }), `Priority set to ${label(priority)}`],
      resolve: [() => api(`${base}/resolution`, { method: "POST", body: { rationale: text, version } }), "Incident marked resolved"],
      close: [
        () =>
          api(`${base}/closure`, {
            method: "POST",
            body: { reason: text, version, public_summary: summary || undefined, override, override_rationale: override ? overrideText : undefined },
          }),
        "Incident closed",
      ],
      reopen: [() => api(`${base}/reopen`, { method: "POST", body: { reason: text, version } }), "Incident reopened"],
    };
    if (!mode) return;
    const [call, message] = calls[mode];
    const ok = await run(mode, call, message);
    if (ok !== undefined) {
      setMode(null);
      reload();
    }
  }

  const needsPriority = mode === "priority" || (mode === "verify" && decision === "VERIFIED" && !incident.verified_priority);
  const valid =
    text.trim().length >= (mode === "info" ? 5 : MIN) &&
    (!needsPriority || priority !== "") &&
    (!(mode === "close" && hasDeps) || (override && overrideText.trim().length >= MIN));

  const titles: Record<Exclude<Mode, null>, string> = {
    verify: "Record verification decision",
    info: "Request more information",
    priority: "Set priority",
    resolve: "Mark resolved",
    close: "Close incident",
    reopen: "Reopen incident",
  };

  return (
    <Card title="Decisions" subtitle="Every decision is recorded with your name, time and rationale.">
      {awaitingResolution && (
        <div className="mb-3">
          <Notice tone="medium">
            {completed.length === 1 ? "A field team has" : `${completed.length} field teams have`} reported completion ({completed.map((d) => d.dispatch_ref).join(", ")}).
            The incident stays open until you confirm resolution.
          </Notice>
          <Button className="mt-2 w-full" variant="primary" onClick={() => open("resolve")}>Confirm resolution…</Button>
        </div>
      )}
      <div className="grid gap-2">
        {a.verify && <Button variant="primary" onClick={() => open("verify")}>Verify / reject…</Button>}
        {a.request_information && <Button onClick={() => open("info")}>Request information…</Button>}
        {a.set_priority && <Button onClick={() => open("priority")}>{incident.verified_priority ? "Change priority…" : "Set priority…"}</Button>}
        {a.resolve && <Button onClick={() => open("resolve")}>Mark resolved…</Button>}
        {incident.status !== "CLOSED" && (
          <Button variant="danger" disabled={!can("CLOSURE")} onClick={() => open("close")} title={can("CLOSURE") ? undefined : "Requires the closure permission"}>
            Close incident…
          </Button>
        )}
        {incident.status === "CLOSED" && (
          <Button disabled={!can("CLOSURE")} onClick={() => open("reopen")} title={can("CLOSURE") ? undefined : "Requires the closure permission"}>
            Reopen…
          </Button>
        )}
        {!can("CLOSURE") && <p className="text-xs text-muted">Closing and reopening require the closure permission.</p>}
      </div>

      <Dialog
        open={mode !== null}
        onClose={() => setMode(null)}
        title={mode ? titles[mode] : ""}
        footer={
          <>
            <Button onClick={() => setMode(null)}>Cancel</Button>
            <Button variant={mode === "close" ? "danger" : "primary"} disabled={!valid} busy={busy === mode} onClick={submit}>
              Confirm
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-muted">
            {incident.incident_ref} · currently <strong className="text-foreground">{label(incident.status)}</strong>
          </p>
          {mode === "verify" && (
            <fieldset className="space-y-2">
              <legend className="mb-1 text-xs font-medium text-muted">Decision</legend>
              {(["VERIFIED", "NEEDS_INFORMATION", "REJECTED"] as const).map((d) => (
                <label key={d} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="decision" checked={decision === d} onChange={() => setDecision(d)} />
                  {label(d)}
                </label>
              ))}
            </fieldset>
          )}
          {needsPriority || (mode === "verify" && decision === "VERIFIED") ? (
            <Field label={mode === "verify" ? "Priority (required to verify)" : "Priority"} hint={incident.verified_priority ? `Current: ${label(incident.verified_priority)}` : undefined}>
              {(id) => (
                <Select id={id} value={priority} onChange={(e) => setPriority(e.target.value)}>
                  <option value="">Select priority</option>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{label(p)}</option>)}
                </Select>
              )}
            </Field>
          ) : null}
          <Field
            label={
              mode === "info" ? "Question for the reporter" : mode === "close" ? "Closure reason (shown to the reporter)" : mode === "reopen" ? "Reason for reopening" : "Rationale"
            }
            hint="Required. Saved in the incident history and audit log."
          >
            {(id) => <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} required />}
          </Field>
          {mode === "close" && (
            <>
              <Field label="Public summary (optional)" hint="Sent to the reporter instead of the reason if given.">
                {(id) => <Textarea id={id} value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={2000} />}
              </Field>
              {hasDeps && (
                <Notice tone="high">
                  <p className="font-medium">Open dependencies</p>
                  <ul className="mt-1 list-disc pl-5">
                    {deps.dispatches.map((d) => <li key={d.dispatch_id}>Dispatch {d.dispatch_ref} — {label(d.status)}</li>)}
                    {deps.allocations.map((al) => <li key={al.contribution_id}>Aid {al.aid_type} × {al.quantity} {al.unit} — {label(al.status)}</li>)}
                  </ul>
                  <label className="mt-2 flex items-center gap-2">
                    <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} />
                    Close anyway with an explicit override
                  </label>
                </Notice>
              )}
              {override && (
                <Field label="Override rationale">
                  {(id) => <Textarea id={id} value={overrideText} onChange={(e) => setOverrideText(e.target.value)} maxLength={2000} />}
                </Field>
              )}
              <Notice tone="neutral">A closed incident becomes read-only until it is reopened.</Notice>
            </>
          )}
          {mode === "resolve" && hasDeps && <Notice tone="high">Active dispatches must be completed, rejected or failed before resolving.</Notice>}
        </div>
      </Dialog>
    </Card>
  );
}
