"use client";

import { useState } from "react";

import { Button, Dialog, Field, Notice, Textarea } from "@/components/ui";
import { useAction } from "@/components/use-action";
import { bulkChange, type BulkAction, type BulkResult, type StaffAccount } from "@/services/adminApi";

const COPY: Record<BulkAction, { verb: string; title: string; button: string; warning: string }> = {
  disable: {
    verb: "Disabled",
    title: "Disable these accounts?",
    button: "Disable accounts",
    warning: "They are signed out on their next request and cannot sign in until you enable each account again. Nothing is deleted.",
  },
  "sign-out": {
    verb: "Signed out",
    title: "Sign these accounts out everywhere?",
    button: "Sign out everywhere",
    warning: "Every session they have ends. Their accounts keep working: they sign in again with their password and authenticator.",
  },
};

type Summary = { result: BulkResult; names: Record<string, string> };

/**
 * Acts on the accounts ticked in the directory. Each account is handled on its own by the server with the
 * same rules as the single action, so accounts that cannot be changed (you, the last administrator, ones
 * already disabled) are listed as skipped without stopping the rest.
 */
export function BulkActionBar({ accounts, onClear, onDone }: { accounts: StaffAccount[]; onClear: () => void; onDone: () => void }) {
  const { run, busy } = useAction();
  const [action, setAction] = useState<BulkAction | null>(null);
  const [reason, setReason] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);

  function ask(next: BulkAction) {
    setReason("");
    setAction(next);
  }

  async function confirm() {
    if (!action) return;
    const names = Object.fromEntries(accounts.map((a) => [a.user_id, a.full_name]));
    const result = await run("bulk", () => bulkChange(action, accounts.map((a) => a.user_id), reason.trim()));
    if (result) {
      setSummary({ result, names });
      setAction(null);
      onClear();
      onDone();
    }
  }

  const skipped = summary?.result.results.filter((r) => !r.ok) ?? [];

  return (
    <>
      {summary && (
        <div className="border-b border-border p-4">
          <Notice tone={summary.result.skipped > 0 ? "high" : "info"}>
            <p className="font-medium">
              {COPY[summary.result.action].verb} {summary.result.done} {summary.result.done === 1 ? "account" : "accounts"}
              {skipped.length > 0 ? `; ${skipped.length} skipped:` : "."}
              <button type="button" className="ml-3 text-xs font-normal underline" onClick={() => setSummary(null)}>Dismiss</button>
            </p>
            {skipped.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs">
                {skipped.map((r) => (
                  <li key={r.user_id}>{summary.names[r.user_id] ?? "An account"}: {r.message ?? r.code}</li>
                ))}
              </ul>
            )}
          </Notice>
        </div>
      )}

      {accounts.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface-muted px-4 py-2" role="region" aria-label="Selected accounts">
          <span className="text-sm font-medium">{accounts.length} selected</span>
          <Button size="sm" variant="ghost" onClick={() => ask("sign-out")}>Sign out everywhere</Button>
          <Button size="sm" variant="ghost" onClick={() => ask("disable")}>Disable</Button>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear}>Clear selection</Button>
        </div>
      )}

      <Dialog
        open={action !== null}
        onClose={() => setAction(null)}
        title={action ? COPY[action].title : ""}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAction(null)}>Cancel</Button>
            <Button variant="danger" busy={busy === "bulk"} disabled={reason.trim().length < 5} onClick={confirm}>
              {action ? COPY[action].button : ""}
            </Button>
          </>
        }
      >
        {action && (
          <div className="space-y-4">
            <Notice tone="high">{COPY[action].warning}</Notice>
            <ul className="max-h-40 list-disc space-y-0.5 overflow-y-auto pl-5 text-sm">
              {accounts.map((a) => (
                <li key={a.user_id}>{a.full_name} <span className="text-xs text-muted">({a.email})</span></li>
              ))}
            </ul>
            <Field label="Reason (recorded in the audit log for each account)" hint="At least 5 characters.">
              {(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}
            </Field>
          </div>
        )}
      </Dialog>
    </>
  );
}
