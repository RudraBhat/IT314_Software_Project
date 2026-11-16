"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingRows, Notice, PageHeader, Pagination, Select } from "@/components/ui";
import { useAction } from "@/components/use-action";
import { formatDateTime, label } from "@/lib/format";
import {
  listAudit,
  verifyAudit,
  type AuditEntry,
  type AuditPage,
  type AuditPerson,
  type AuditResult,
  type AuditVerification,
} from "@/services/adminApi";

import type { Tone } from "@/components/ui";

const RESULT_TONE: Record<AuditResult, Tone> = { SUCCESS: "low", FAILURE: "critical", DENIED: "high" };
const RESULT_LABEL: Record<AuditResult, string> = { SUCCESS: "Succeeded", FAILURE: "Failed", DENIED: "Denied" };
const ROLE_NAME: Record<string, string> = {
  NORMAL_USER: "Citizen",
  DISASTER_MGMT: "Dispatch staff",
  FIELD_TEAM: "Field responder",
  APP_MGMT: "Administrator",
};

type Result = { key: string; data?: AuditPage; error?: string };

function who(person: AuditPerson | null): string {
  if (!person) return "System";
  if (person.name) return `${person.name}${person.email ? ` (${person.email})` : ""}`;
  return person.role ? ROLE_NAME[person.role] ?? person.role : "Unknown";
}

/**
 * Account and security audit trail for administrators. Operational entries (incidents, dispatches,
 * donations) are never shown, and citizens are never named. Read-only, with a hash-chain check.
 */
export default function AdminAuditPage() {
  const { run, busy } = useAction();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [action, setAction] = useState("");
  const [result, setResult] = useState<AuditResult | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [state, setState] = useState<Result | null>(null);
  const [retry, setRetry] = useState(0);
  const [facets, setFacets] = useState<string[]>([]);
  const [verification, setVerification] = useState<AuditVerification | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const key = JSON.stringify({ q: debouncedSearch, action, result, from, to, page, retry });

  useEffect(() => {
    let active = true;
    listAudit({ q: debouncedSearch, action, result, from, to, page })
      .then((data) => {
        if (!active) return;
        setState({ key, data });
        setFacets(data.facets.actions);
      })
      .catch((e: unknown) => active && setState({ key, error: e instanceof Error ? e.message : "Could not load the audit log." }));
    return () => {
      active = false;
    };
    // `key` already contains every input of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const loading = !state || state.key !== key;
  const data = state?.data;
  const dateOrderWrong = Boolean(from && to && from > to);

  async function verify() {
    const outcome = await run("verify", () => verifyAudit());
    if (outcome) {
      setVerification(outcome);
      setRetry((n) => n + 1); // the check is itself an entry in the log
    }
  }

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Account changes, sign-ins and refused requests. Operational entries are not shown, and citizens are never named."
        actions={<Button onClick={verify} busy={busy === "verify"}>Verify log integrity</Button>}
      />

      {verification && (
        <div className="mb-4">
          <Notice tone={verification.valid ? "info" : "critical"}>
            {verification.valid ? "Intact. " : "Problem found. "}
            {verification.message} Checked {formatDateTime(verification.verified_at)}.
          </Notice>
        </div>
      )}

      <Card title="Entries" subtitle={data ? `${data.total} matching entries, newest first` : undefined} bodyClassName="p-0">
        <div className="grid gap-3 border-b border-border p-4 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Search" hint="Staff name, email or action">
            {(id) => <Input id={id} type="search" value={search} onChange={(e) => setSearch(e.target.value)} maxLength={100} />}
          </Field>
          <Field label="Action">
            {(id) => (
              <Select id={id} value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
                <option value="">All actions</option>
                {facets.map((a) => (
                  <option key={a} value={a}>{label(a)}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Outcome">
            {(id) => (
              <Select id={id} value={result} onChange={(e) => { setResult(e.target.value as AuditResult | ""); setPage(1); }}>
                <option value="">All outcomes</option>
                {(Object.keys(RESULT_LABEL) as AuditResult[]).map((r) => (
                  <option key={r} value={r}>{RESULT_LABEL[r]}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="From">
            {(id) => <Input id={id} type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} />}
          </Field>
          <Field label="To" error={dateOrderWrong ? "The end date is before the start date." : undefined}>
            {(id) => <Input id={id} type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} />}
          </Field>
        </div>

        {state?.error && !loading && <div className="p-4"><ErrorState message={state.error} onRetry={() => setRetry((n) => n + 1)} /></div>}
        {loading && !data && <div className="p-4"><LoadingRows rows={5} /></div>}
        {data && data.items.length === 0 && <div className="p-4"><EmptyState title="No entries match these filters." /></div>}
        {data && data.items.length > 0 && (
          <ul className={`divide-y divide-border ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
            {data.items.map((entry) => (
              <EntryRow key={entry.audit_id} entry={entry} />
            ))}
          </ul>
        )}
        {data && (
          <div className="border-t border-border px-5 py-3">
            <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
          </div>
        )}
      </Card>
    </>
  );
}

function EntryRow({ entry }: { entry: AuditEntry }) {
  const hasChange = entry.before !== null || entry.after !== null;
  return (
    <li className="flex flex-col gap-1.5 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{label(entry.action)}</span>
        <Badge tone={RESULT_TONE[entry.result]}>{RESULT_LABEL[entry.result]}</Badge>
        <span className="ml-auto text-xs text-muted">{formatDateTime(entry.occurred_at)}</span>
      </div>
      <p className="text-xs text-muted">
        By <span className="font-medium text-foreground">{who(entry.actor)}</span>
        {entry.target && (
          <>
            {" "}on <span className="font-medium text-foreground">{who(entry.target)}</span>
          </>
        )}
        {entry.ip ? ` · from ${entry.ip}` : ""}
      </p>
      {entry.rationale && <p className="text-sm">{entry.rationale}</p>}
      {hasChange && (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer select-none font-medium">What changed</summary>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            <dt>Before</dt>
            <dd className="break-all font-mono">{entry.before ? JSON.stringify(entry.before) : "—"}</dd>
            <dt>After</dt>
            <dd className="break-all font-mono">{entry.after ? JSON.stringify(entry.after) : "—"}</dd>
          </dl>
        </details>
      )}
    </li>
  );
}
