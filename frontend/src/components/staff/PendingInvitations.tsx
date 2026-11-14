"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, Dialog, EmptyState, ErrorState, LoadingRows, Notice } from "@/components/ui";
import { useAction } from "@/components/use-action";
import {
  ROLE_LABEL,
  listInvitations,
  resendInvitation,
  revokeInvitation,
  type PendingInvitation,
} from "@/services/invitationsApi";

/**
 * Accounts invited but not yet set up, with resend and revoke (issue #100).
 * The backend only returns invitations for roles the caller may manage.
 * Change `refreshKey` to reload after inviting someone.
 */
export function PendingInvitations({ refreshKey = 0 }: { refreshKey?: number }) {
  const { run, busy } = useAction();
  const [items, setItems] = useState<PendingInvitation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<PendingInvitation | null>(null);

  const load = useCallback(() => {
    listInvitations()
      .then((res) => { setItems(res.items); setError(null); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load invitations."));
  }, []);

  useEffect(load, [load, refreshKey]);

  async function resend(invite: PendingInvitation) {
    const ok = await run(`resend-${invite.user_id}`, () => resendInvitation(invite.user_id), `New setup link sent to ${invite.email}.`);
    if (ok !== undefined) load();
  }

  async function revoke(invite: PendingInvitation) {
    await run(`revoke-${invite.user_id}`, () => revokeInvitation(invite.user_id), `Invitation for ${invite.email} revoked.`);
    setRevoking(null);
    load();
  }

  return (
    <Card title="Pending invitations" subtitle="Invited accounts that have not finished setup" className="mt-6" bodyClassName="p-0">
      {error && <div className="p-4"><ErrorState message={error} onRetry={load} /></div>}
      {!error && items === null && <div className="p-4"><LoadingRows rows={2} /></div>}
      {items?.length === 0 && <div className="p-4"><EmptyState title="No pending invitations." /></div>}
      {items && items.length > 0 && (
        <ul className="divide-y divide-border">
          {items.map((invite) => (
            <li key={invite.user_id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">{invite.full_name}</span>
                  <Badge tone="neutral">{ROLE_LABEL[invite.role] ?? invite.role}</Badge>
                  {invite.expired ? <Badge tone="high">Link expired</Badge> : <Badge tone="medium">Awaiting setup</Badge>}
                </div>
                <p className="mt-0.5 text-xs text-muted">
                  {invite.email}
                  {invite.team_name ? ` · Team: ${invite.team_name}` : ""}
                  {invite.permissions.length ? ` · ${invite.permissions.join(", ")}` : ""}
                </p>
                <p className="mt-1 text-[11px] text-muted">
                  Invited {new Date(invite.created_at).toLocaleDateString()}
                  {invite.invited_by_name ? ` by ${invite.invited_by_name}` : ""}
                  {invite.invitation_expires_at && !invite.expired
                    ? ` · link valid until ${new Date(invite.invitation_expires_at).toLocaleString()}`
                    : ""}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button size="sm" busy={busy === `resend-${invite.user_id}`} onClick={() => resend(invite)}>
                  Resend
                </Button>
                <Button size="sm" variant="danger" onClick={() => setRevoking(invite)}>
                  Revoke
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title="Revoke invitation"
        footer={
          <>
            <Button onClick={() => setRevoking(null)}>Cancel</Button>
            <Button
              variant="danger"
              busy={revoking ? busy === `revoke-${revoking.user_id}` : false}
              onClick={() => revoking && revoke(revoking)}
            >
              Revoke invitation
            </Button>
          </>
        }
      >
        <Notice tone="critical">
          The setup link for <strong>{revoking?.email}</strong> stops working and the pending account is removed.
          You can invite the same email again later.
        </Notice>
      </Dialog>
    </Card>
  );
}
