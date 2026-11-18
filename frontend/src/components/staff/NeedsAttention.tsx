"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Notice } from "@/components/ui";
import { getSystemStatus, type SystemStatus } from "@/services/adminApi";

import type { Tone } from "@/components/ui";

type Item = { key: string; tone: Tone; text: string };

/** What an administrator should look at now, taken from the platform health check. */
export function attentionItems(s: SystemStatus): Item[] {
  const items: Item[] = [];
  if (!s.mfa_key_valid) {
    items.push({ key: "key", tone: "critical", text: "The authenticator key is invalid, so no one can set up an authenticator until MFA_ENCRYPTION_KEY is fixed." });
  }
  if (s.audit.last_verification_ok === false) {
    items.push({ key: "audit", tone: "critical", text: "The last audit log integrity check found a problem." });
  }
  if (!s.email.configured) {
    items.push({ key: "email", tone: "high", text: "Email is not set up, so invitation and reset links are not delivered." });
  }
  if (s.accounts.active_without_mfa > 0) {
    items.push({ key: "mfa", tone: "high", text: `${s.accounts.active_without_mfa} active ${s.accounts.active_without_mfa === 1 ? "account has" : "accounts have"} no authenticator.` });
  }
  if (s.accounts.locked > 0) {
    items.push({ key: "locked", tone: "high", text: `${s.accounts.locked} ${s.accounts.locked === 1 ? "account is" : "accounts are"} locked after failed sign-ins (clears by itself).` });
  }
  if (s.accounts.invitations_expired > 0) {
    items.push({ key: "invites", tone: "medium", text: `${s.accounts.invitations_expired} ${s.accounts.invitations_expired === 1 ? "invitation has" : "invitations have"} expired. Resend ${s.accounts.invitations_expired === 1 ? "it" : "them"} from the pending list below.` });
  }
  return items;
}

/** Shown only when something needs attention. Stays silent if the check cannot be loaded: the System page reports errors. */
export function NeedsAttention({ refreshKey = 0 }: { refreshKey?: number }) {
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    let active = true;
    getSystemStatus()
      .then((data) => active && setStatus(data))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [refreshKey]);

  const items = status ? attentionItems(status) : [];
  if (items.length === 0) return null;

  return (
    <section aria-label="Needs attention" className="mb-6 space-y-2">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">Needs attention</h2>
        <Link href="/admin/system" className="text-xs text-muted underline hover:text-foreground">System status</Link>
      </div>
      {items.map((item) => (
        <Notice key={item.key} tone={item.tone}>{item.text}</Notice>
      ))}
    </section>
  );
}
