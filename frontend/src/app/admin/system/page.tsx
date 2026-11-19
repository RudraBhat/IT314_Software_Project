"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Card, ErrorState, LoadingRows, PageHeader } from "@/components/ui";
import { formatDateTime, timeAgo } from "@/lib/format";
import { getSystemStatus, type SystemStatus } from "@/services/adminApi";

import type { Tone } from "@/components/ui";

type State = { key: number; data?: SystemStatus; error?: string };

function Row({ name, tone, value, hint }: { name: string; tone: Tone; value: string; hint?: string }) {
  return (
    <li className="flex flex-wrap items-center gap-2 px-5 py-3">
      <span className="text-sm font-medium">{name}</span>
      <Badge tone={tone}>{value}</Badge>
      {hint && <span className="basis-full text-xs text-muted">{hint}</span>}
    </li>
  );
}

/** Read-only health of the platform for administrators: no secrets, addresses or personal data. */
export default function AdminSystemPage() {
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<State | null>(null);

  useEffect(() => {
    let active = true;
    getSystemStatus()
      .then((data) => active && setState({ key: reload, data }))
      .catch((e: unknown) => active && setState({ key: reload, error: e instanceof Error ? e.message : "Could not load system status." }));
    return () => {
      active = false;
    };
  }, [reload]);

  const loading = !state || state.key !== reload;
  const s = state?.data;

  return (
    <>
      <PageHeader
        title="System status"
        description="Whether sign-in, email and the audit trail are in working order."
        actions={<Button onClick={() => setReload((n) => n + 1)} busy={loading}>Refresh</Button>}
      />
      {state?.error && !loading && <ErrorState message={state.error} onRetry={() => setReload((n) => n + 1)} />}
      {loading && !s && <LoadingRows rows={5} />}
      {s && (
        <Card title="Checks" subtitle={`Checked ${formatDateTime(s.checked_at)} · version ${s.version}`} bodyClassName="p-0">
          <ul className={`divide-y divide-border ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
            <Row
              name="Database"
              tone={s.database.status === "ok" ? "low" : "critical"}
              value={s.database.status === "ok" ? `Reachable · ${s.database.latency_ms} ms` : "Unavailable"}
            />
            <Row
              name="Email"
              tone={s.email.configured ? "low" : "high"}
              value={s.email.configured ? "Configured" : "Simulated"}
              hint={s.email.configured ? undefined : "No mail server is set, so invitation and reset links are not delivered."}
            />
            <Row
              name="Authenticator key"
              tone={s.mfa_key_valid ? "low" : "critical"}
              value={s.mfa_key_valid ? "Valid" : "Invalid"}
              hint={s.mfa_key_valid ? undefined : "New authenticator set-up will fail until MFA_ENCRYPTION_KEY is fixed."}
            />
            <Row
              name="Invitations"
              tone={s.accounts.invitations_expired > 0 ? "medium" : "low"}
              value={`${s.accounts.invitations_open} open · ${s.accounts.invitations_expired} expired`}
              hint={s.accounts.invitations_expired > 0 ? "Resend expired invitations from the Accounts page." : undefined}
            />
            <Row
              name="Locked accounts"
              tone={s.accounts.locked > 0 ? "high" : "low"}
              value={String(s.accounts.locked)}
              hint="Locked after repeated failed sign-ins; clears by itself."
            />
            <Row
              name="Active without authenticator"
              tone={s.accounts.active_without_mfa > 0 ? "high" : "low"}
              value={String(s.accounts.active_without_mfa)}
            />
            <Row
              name="Audit log integrity"
              tone={s.audit.last_verification_ok === null ? "medium" : s.audit.last_verification_ok ? "low" : "critical"}
              value={s.audit.last_verification_ok === null ? "Never checked" : s.audit.last_verification_ok ? "Intact at last check" : "Problem at last check"}
              hint={s.audit.last_verified_at ? `Last checked ${timeAgo(s.audit.last_verified_at)}. Run a check from the Audit log page.` : "Run a check from the Audit log page."}
            />
          </ul>
        </Card>
      )}
    </>
  );
}
