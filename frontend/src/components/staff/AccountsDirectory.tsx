"use client";

import { useEffect, useState } from "react";

import { Badge, Card, EmptyState, ErrorState, Input, LoadingRows, Pagination, Select } from "@/components/ui";
import { formatDateTime, timeAgo } from "@/lib/format";
import { listAccounts, type AccountStatus, type AccountsPage, type StaffAccount } from "@/services/adminApi";
import { ROLE_LABEL, type InvitableRole } from "@/services/invitationsApi";

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
  const data = result?.data;
  const summary = data?.summary;
  const filtered = Boolean(debouncedSearch.trim() || role || status);

  return (
    <Card
      title="Staff accounts"
      subtitle={summary ? `${summary.total} accounts · ${summary.by_status.ACTIVE ?? 0} active · ${summary.by_status.PENDING_SETUP ?? 0} awaiting setup · ${summary.by_status.DISABLED ?? 0} disabled` : "Everyone who can sign in to the operations side"}
      bodyClassName="p-0"
    >
      <div className="grid gap-3 border-b border-border p-4 sm:grid-cols-[minmax(0,1fr)_14rem_12rem]">
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
      </div>

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
        <ul className={`divide-y divide-border ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
          {data.items.map((account) => (
            <AccountRow key={account.user_id} account={account} />
          ))}
        </ul>
      )}
      {data && (
        <div className="border-t border-border px-5 py-3">
          <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
        </div>
      )}
    </Card>
  );
}

function AccountRow({ account }: { account: StaffAccount }) {
  const never = !account.last_login_at;
  return (
    <li className="flex flex-col gap-2 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{account.full_name}</span>
        {account.is_you && <Badge tone="info">You</Badge>}
        <Badge tone="neutral">{ROLE_LABEL[account.role] ?? account.role}</Badge>
        <Badge tone={STATUS_TONE[account.status] ?? "neutral"}>{STATUS_LABEL[account.status] ?? account.status}</Badge>
        {account.is_locked && <Badge tone="high">Locked after failed sign-ins</Badge>}
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
        <span>Added {formatDateTime(account.created_at)}</span>
      </div>
      {account.permissions.length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="Permissions">
          {account.permissions.map((p) => (
            <Badge key={p} tone="neutral">{p.toLowerCase()}</Badge>
          ))}
        </div>
      )}
    </li>
  );
}
