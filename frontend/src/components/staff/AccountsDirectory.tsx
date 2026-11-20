"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, Notice, Pagination, Select, Textarea } from "@/components/ui";
import { useAction } from "@/components/use-action";
import { formatDateTime, timeAgo } from "@/lib/format";
import { disableAccount, enableAccount, exportAccounts, listAccounts, resetCredentials, setPermissions, signOutAccount, updateProfile, type AccountStatus, type AccountsPage, type StaffAccount } from "@/services/adminApi";
import { ROLE_LABEL, type InvitableRole } from "@/services/invitationsApi";

import { BulkActionBar } from "./BulkActionBar";
import { PermissionChips } from "./PermissionChips";

import type { Tone } from "@/components/ui";

const STATUS_LABEL: Record<AccountStatus, string> = {
  ACTIVE: "Active",
  PENDING_SETUP: "Awaiting setup",
  DISABLED: "Disabled",
  LOCKED: "Locked",
  PENDING_VERIFICATION: "Pending verification",
};

const STATUS_TONE: Record<AccountStatus, Tone> = {
  ACTIVE: "low",
  PENDING_SETUP: "medium",
  DISABLED: "critical",
  LOCKED: "high",
  PENDING_VERIFICATION: "medium",
};

const ROLES = Object.keys(ROLE_LABEL) as InvitableRole[];
const STATUSES: AccountStatus[] = ["ACTIVE", "PENDING_SETUP", "DISABLED", "LOCKED"];

type Action = "disable" | "enable" | "reset" | "access" | "signout" | "details";

const PERMISSION_INFO: { code: string; name: string; hint: string }[] = [
  { code: "DISPATCH", name: "Dispatch", hint: "Dispatch field teams to verified incidents" },
  { code: "CLOSURE", name: "Closure", hint: "Close and reopen incidents" },
  { code: "PUBLISHER", name: "Publisher", hint: "Publish verified signals to the public" },
  { code: "MODERATOR", name: "Moderator", hint: "Review the evidence moderation queue" },
  { code: "SUPERVISOR", name: "Supervisor", hint: "Delete ingested signals; can also publish and manage ingestion" },
];

type Result = { key: string; data?: AccountsPage; error?: string };

/**
 * Every staff account (Disaster Management, Field Team, administrators) with its state, sign-in
 * activity and access. Read-only; citizens are never listed. Change `refreshKey` to reload after an
 * invitation. Typing in the search box waits a moment before it queries the server.
 */
export function AccountsDirectory({ refreshKey = 0 }: { refreshKey?: number }) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [role, setRole] = useState<InvitableRole | "">("");
  const [status, setStatus] = useState<AccountStatus | "">("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<Result | null>(null);
  const [retry, setRetry] = useState(0);
  const { run, busy } = useAction();
  const [changing, setChanging] = useState<{ account: StaffAccount; action: Action } | null>(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [granted, setGranted] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [designation, setDesignation] = useState("");
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const key = JSON.stringify({ q: debouncedSearch, role, status, page, refreshKey, retry });

  useEffect(() => {
    let active = true;
    listAccounts({ q: debouncedSearch, role, status, page })
      .then((data) => active && setResult({ key, data }))
      .catch((e: unknown) => active && setResult({ key, error: e instanceof Error ? e.message : "Could not load accounts." }));
    return () => {
      active = false;
    };
    // `key` already contains every input of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const loading = !result || result.key !== key;

  function ask(account: StaffAccount, action: Action) {
    setReason("");
    setGranted(account.permissions);
    setName(account.full_name);
    setDesignation(account.designation ?? "");
    setChanging({ account, action });
  }

  async function confirm() {
    if (!changing) return;
    const { account, action } = changing;
    if (action === "access") {
      const saved = await run(
        `access-${account.user_id}`,
        () => setPermissions(account.user_id, granted, reason.trim()),
        `${account.full_name}'s access was updated.`,
      );
      if (saved !== undefined) {
        setChanging(null);
        setRetry((n) => n + 1);
      }
      return;
    }
    if (action === "details") {
      const saved = await run(
        `details-${account.user_id}`,
        () => updateProfile(account.user_id, { full_name: name.trim(), designation: designation.trim() || null }, reason.trim()),
        `${name.trim()}'s details were updated.`,
      );
      if (saved !== undefined) {
        setChanging(null);
        setRetry((n) => n + 1);
      }
      return;
    }
    const call = { disable: disableAccount, enable: enableAccount, reset: resetCredentials, signout: signOutAccount }[action];
    const message = {
      disable: `${account.full_name} was disabled and signed out.`,
      enable: `${account.full_name} was enabled.`,
      signout: `${account.full_name} was signed out of every device.`,
      reset: `${account.full_name}'s sign-in was reset and they were emailed a setup link.`,
    }[action];
    const done = await run(`${action}-${account.user_id}`, () => call(account.user_id, reason.trim()), message);
    if (done !== undefined) {
      if (action === "reset" && "email_configured" in done && !done.email_configured) {
        setNote(`Email is not configured on this server, so no link was sent to ${account.email}. Invite them again once email is set up.`);
      }
      setChanging(null);
      setRetry((n) => n + 1);
    }
  }
  async function download() {
    const file = await run("export", () => exportAccounts({ q: debouncedSearch, role, status }), "Export downloaded.");
    if (!file) return;
    const url = URL.createObjectURL(file.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = file.filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  const data = result?.data;
  // Only accounts on the page being shown count, so a hidden selection is never acted on by surprise.
  const selectedHere = data?.items.filter((a) => selected.includes(a.user_id)) ?? [];
  const selectable = data?.items.filter((a) => !a.is_you) ?? [];
  const summary = data?.summary;
  const filtered = Boolean(debouncedSearch.trim() || role || status);

  return (
    <Card
      title="Staff accounts"
      subtitle={summary ? `${summary.total} accounts · ${summary.by_status.ACTIVE ?? 0} active · ${summary.by_status.PENDING_SETUP ?? 0} awaiting setup · ${summary.by_status.DISABLED ?? 0} disabled` : "Everyone who can sign in to the operations side"}
      bodyClassName="p-0"
    >
      <div className="grid gap-3 border-b border-border p-4 sm:grid-cols-[minmax(0,1fr)_14rem_12rem_auto]">
        <label className="block">
          <span className="sr-only">Search by name or email</span>
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or email"
            maxLength={100}
          />
        </label>
        <label className="block">
          <span className="sr-only">Filter by role</span>
          <Select
            value={role}
            onChange={(e) => {
              setRole(e.target.value as InvitableRole | "");
              setPage(1);
            }}
          >
            <option value="">All roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </Select>
        </label>
        <label className="block">
          <span className="sr-only">Filter by status</span>
          <Select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as AccountStatus | "");
              setPage(1);
            }}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </Select>
        </label>
        <Button variant="ghost" onClick={download} busy={busy === "export"} disabled={!data || data.total === 0} title="Download the accounts matching these filters as CSV. The export is recorded in the audit log.">
          Export CSV
        </Button>
      </div>

      <BulkActionBar accounts={selectedHere} onClear={() => setSelected([])} onDone={() => setRetry((n) => n + 1)} />
      {note && <div className="border-b border-border p-4"><Notice tone="high">{note}</Notice></div>}
      {result?.error && !loading && (
        <div className="p-4"><ErrorState message={result.error} onRetry={() => setRetry((n) => n + 1)} /></div>
      )}
      {loading && !data && <div className="p-4"><LoadingRows rows={4} /></div>}
      {data && data.items.length === 0 && (
        <div className="p-4">
          <EmptyState title={filtered ? "No accounts match these filters." : "No staff accounts yet."} />
        </div>
      )}
      {data && data.items.length > 0 && (
        <>
          {selectable.length > 1 && (
            <label className="flex items-center gap-2 border-b border-border px-5 py-2 text-xs text-muted">
              <input
                type="checkbox"
                checked={selectedHere.length === selectable.length}
                onChange={(e) => setSelected(e.target.checked ? selectable.map((a) => a.user_id) : [])}
              />
              Select everyone on this page
            </label>
          )}
          <ul className={`divide-y divide-border ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
            {data.items.map((account) => (
              <AccountRow
                key={account.user_id}
                account={account}
                onAction={ask}
                selected={selected.includes(account.user_id)}
                onSelect={(on) => setSelected((s) => (on ? [...s, account.user_id] : s.filter((id) => id !== account.user_id)))}
              />
            ))}
          </ul>
        </>
      )}
      {data && (
        <div className="border-t border-border px-5 py-3">
          <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
        </div>
      )}

      <Dialog
        open={changing !== null}
        onClose={() => setChanging(null)}
        title={changing?.action === "details" ? `Edit details for ${changing.account.full_name}` : changing?.action === "access" ? `Edit access for ${changing.account.full_name}` : changing?.action === "reset" ? `Reset sign-in for ${changing.account.full_name}?` : changing?.action === "signout" ? `Sign ${changing.account.full_name} out everywhere?` : changing?.action === "disable" ? `Disable ${changing.account.full_name}?` : `Enable ${changing?.account.full_name ?? ""}?`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setChanging(null)}>Cancel</Button>
            <Button
              variant={changing?.action === "enable" || changing?.action === "access" || changing?.action === "details" ? "primary" : "danger"}
              busy={busy !== null}
              disabled={
                reason.trim().length < 5 ||
                (changing?.action === "access" && sameSet(granted, changing.account.permissions)) ||
                (changing?.action === "details" &&
                  (name.trim().length < 2 || (name.trim() === changing.account.full_name && designation.trim() === (changing.account.designation ?? ""))))
              }
              onClick={confirm}
            >
              {changing?.action === "details" ? "Save details" : changing?.action === "access" ? "Save access" : changing?.action === "reset" ? "Reset sign-in" : changing?.action === "signout" ? "Sign out everywhere" : changing?.action === "disable" ? "Disable account" : "Enable account"}
            </Button>
          </>
        }
      >
        {changing && (
          <div className="space-y-4">
            {changing.action === "details" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Full name">{(id) => <Input id={id} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />}</Field>
                <Field label="Designation" hint="Optional, for example Duty Officer.">
                  {(id) => <Input id={id} value={designation} maxLength={120} onChange={(e) => setDesignation(e.target.value)} />}
                </Field>
              </div>
            )}
            {changing.action === "access" && (
              <fieldset className="space-y-2">
                <legend className="mb-1 text-sm font-medium">What {changing.account.full_name} can do</legend>
                {PERMISSION_INFO.map((p) => (
                  <label key={p.code} className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={granted.includes(p.code)}
                      onChange={(e) => setGranted((g) => (e.target.checked ? [...g, p.code] : g.filter((c) => c !== p.code)))}
                    />
                    <span>
                      <span className="font-medium">{p.name}</span>
                      <span className="block text-xs text-muted">{p.hint}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
            <Notice tone={changing.action === "enable" || changing.action === "access" || changing.action === "details" ? "info" : "high"}>
              {changing.action === "details"
                ? `The email address (${changing.account.email}) cannot be changed: it is how they sign in. The old and new values are recorded in the audit log.`
                : changing.action === "access"
                ? "The change applies on their next request; they are not signed out."
                : changing.action === "reset"
                ? `${changing.account.email} is signed out now and their password and authenticator stop working. They get an emailed link, valid once, to choose a new password and set up their authenticator again. You never see either.`
                : changing.action === "signout"
                ? `${changing.account.email} is signed out of every device on their next request. Their account keeps working: they sign in again with their password and authenticator. Use this after a lost or shared device.`
                : changing.action === "disable"
                ? `${changing.account.email} will be signed out on their next request and cannot sign in again until you enable the account. Nothing is deleted.`
                : changing.account.status === "DISABLED" && (!changing.account.mfa_enabled || changing.account.last_login_at === null)
                  ? `${changing.account.email} can sign in again if setup was finished. If they never completed setup, send a new invitation link from the pending list.`
                  : `${changing.account.email} will be able to sign in again. Their old sessions stay ended.`}
            </Notice>
            <Field label="Reason (recorded in the audit log)" hint="At least 5 characters.">
              {(id) => (
                <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
              )}
            </Field>
          </div>
        )}
      </Dialog>
    </Card>
  );
}

function AccountRow({ account, onAction, selected, onSelect }: {
  account: StaffAccount;
  onAction: (account: StaffAccount, action: Action) => void;
  selected: boolean;
  onSelect: (on: boolean) => void;
}) {
  const never = !account.last_login_at;
  return (
    <li className="flex flex-col gap-2 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        {!account.is_you && (
          <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label={`Select ${account.full_name}`} />
        )}
        <span className="text-sm font-semibold">{account.full_name}</span>
        {account.is_you && <Badge tone="info">You</Badge>}
        <Badge tone="neutral">{ROLE_LABEL[account.role] ?? account.role}</Badge>
        <Badge tone={STATUS_TONE[account.status] ?? "neutral"}>{STATUS_LABEL[account.status] ?? account.status}</Badge>
        {account.is_locked && <Badge tone="high">Locked after failed sign-ins</Badge>}
        <span className="ml-auto flex items-center gap-1">
          <Link
            href={`/admin/audit?user=${encodeURIComponent(account.user_id)}`}
            className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-surface-muted hover:text-foreground"
            aria-label={`See the audit history of ${account.full_name}`}
          >
            History
          </Link>
          <Button size="sm" variant="ghost" onClick={() => onAction(account, "details")} aria-label={`Edit details for ${account.full_name}`}>
            Edit details
          </Button>
          {!account.is_you && (
            <>
            {account.role === "DISASTER_MGMT" && account.status !== "DISABLED" && (
              <Button size="sm" variant="ghost" onClick={() => onAction(account, "access")} aria-label={`Edit access for ${account.full_name}`}>
                Edit access
              </Button>
            )}
            {account.status === "ACTIVE" && account.active_sessions > 0 && (
              <Button size="sm" variant="ghost" onClick={() => onAction(account, "signout")} aria-label={`Sign ${account.full_name} out everywhere`}>
                Sign out
              </Button>
            )}
            {account.status === "ACTIVE" && (
              <Button size="sm" variant="ghost" onClick={() => onAction(account, "reset")} aria-label={`Reset sign-in for ${account.full_name}`}>
                Reset sign-in
              </Button>
            )}
            {account.status === "DISABLED" ? (
              <Button size="sm" onClick={() => onAction(account, "enable")}>Enable</Button>
            ) : (
              <Button size="sm" variant="ghost" onClick={() => onAction(account, "disable")} aria-label={`Disable ${account.full_name}`}>
                Disable
              </Button>
            )}
            </>
          )}
        </span>
      </div>
      <p className="text-xs text-muted">
        {account.email}
        {account.designation ? ` · ${account.designation}` : ""}
        {account.team_name ? ` · Team: ${account.team_name}` : ""}
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>
          Authenticator:{" "}
          <span className={account.mfa_enabled ? "font-medium text-foreground" : "font-medium text-high"}>
            {account.mfa_enabled ? "set up" : "not set up"}
          </span>
        </span>
        <span title={account.last_login_at ? formatDateTime(account.last_login_at) : undefined}>
          Last sign-in: <span className="font-medium text-foreground">{never ? "never" : timeAgo(account.last_login_at)}</span>
        </span>
        <span>
          Signed in on:{" "}
          <span className={account.active_sessions > 0 ? "font-medium text-foreground" : undefined}>
            {account.active_sessions === 0 ? "no devices" : account.active_sessions === 1 ? "1 device" : `${account.active_sessions} devices`}
          </span>
        </span>
        <span>Added {formatDateTime(account.created_at)}</span>
      </div>
      {account.permissions.length > 0 && (
        <PermissionChips permissions={account.permissions} />
      )}
    </li>
  );
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}
