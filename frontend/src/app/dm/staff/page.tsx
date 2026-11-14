"use client";

import { useState } from "react";
import { useAction } from "@/components/use-action";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingRows,
  Notice,
  PageHeader,
} from "@/components/ui";
import { InviteAccountDialog } from "@/components/staff/InviteAccountDialog";
import { PendingInvitations } from "@/components/staff/PendingInvitations";
import { PermissionEditor } from "@/components/staff/PermissionEditor";
import { api, useQuery } from "@/lib/api";
import { useStaff } from "../shell";

// ─── Types ───────────────────────────────────────────────────────────────────

type StaffMember = {
  user_id: string;
  email: string;
  full_name: string;
  designation: string | null;
  status: string;
  mfa_enabled: boolean;
  last_login_at: string | null;
  is_locked: boolean;
  permissions: string[];
  created_at: string;
};

function MfaRevealBox({ secret, uri, onClose }: { secret: string; uri: string; onClose: () => void }) {
  return (
    <div className="space-y-4">
      <Notice tone="critical">
        This secret is shown <strong>only once</strong>. Copy it now and share it securely with the new staff member to add to their authenticator app (Google Authenticator, Authy, etc.).
      </Notice>
      <div>
        <p className="mb-1 text-xs font-semibold text-muted">TOTP Secret Key</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 rounded-lg border border-border bg-surface-muted px-3 py-2 font-mono text-sm tracking-widest text-foreground break-all">
            {secret}
          </code>
          <Button
            size="sm"
            onClick={() => navigator.clipboard.writeText(secret)}
          >
            Copy
          </Button>
        </div>
      </div>
      <div>
        <p className="mb-1 text-xs font-semibold text-muted">OTPAuth URI (scan with QR generator)</p>
        <code className="block rounded-lg border border-border bg-surface-muted px-3 py-2 font-mono text-[11px] text-muted break-all">
          {uri}
        </code>
      </div>
      <Button variant="primary" onClick={onClose} className="w-full">
        I have saved the secret — Close
      </Button>
    </div>
  );
}

// ─── Edit Permissions Dialog ──────────────────────────────────────────────────

function EditPermissionsDialog({
  member,
  onDone,
}: {
  member: StaffMember;
  onDone: () => void;
}) {
  const { run, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [permissions, setPermissions] = useState<string[]>(member.permissions);

  async function handleSave() {
    const ok = await run(
      `perms-${member.user_id}`,
      () => api(`staff/${member.user_id}/permissions`, { method: "PUT", body: { permissions } }),
      "Permissions updated",
    );
    if (ok !== undefined) { setOpen(false); onDone(); }
  }

  return (
    <>
      <Button size="sm" onClick={() => { setPermissions(member.permissions); setOpen(true); }}>
        Edit
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={`Permissions — ${member.full_name}`}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" busy={busy === `perms-${member.user_id}`} onClick={handleSave}>
              Save
            </Button>
          </>
        }
      >
        <PermissionEditor value={permissions} onChange={setPermissions} />
      </Dialog>
    </>
  );
}

// ─── Reset MFA Dialog ────────────────────────────────────────────────────────

function ResetMfaDialog({ member, onDone }: { member: StaffMember; onDone: () => void }) {
  const { run, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<{ mfa_secret: string; mfa_uri: string } | null>(null);

  async function handleReset() {
    const res = await run<{ mfa_secret: string; mfa_uri: string; message: string }>(
      `mfa-${member.user_id}`,
      () => api(`staff/${member.user_id}/reset-mfa`, { method: "POST" }),
      undefined, // don't show default toast — we show the MFA box instead
    );
    if (res) { setResult(res); onDone(); }
  }

  return (
    <>
      <Button size="sm" variant="danger" onClick={() => setOpen(true)}>
        Reset MFA
      </Button>

      {/* Confirm dialog */}
      <Dialog
        open={open && !result}
        onClose={() => setOpen(false)}
        title={`Reset MFA — ${member.full_name}`}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="danger" busy={busy === `mfa-${member.user_id}`} onClick={handleReset}>
              Yes, reset MFA
            </Button>
          </>
        }
      >
        <Notice tone="critical">
          This will <strong>revoke all active sessions</strong> for <strong>{member.email}</strong> and generate a new TOTP secret. They will be unable to sign in until they re-enrol.
        </Notice>
      </Dialog>

      {/* New secret reveal */}
      <Dialog open={!!result} onClose={() => { setResult(null); setOpen(false); }} title={`New MFA secret — ${member.full_name}`}>
        {result && (
          <MfaRevealBox
            secret={result.mfa_secret}
            uri={result.mfa_uri}
            onClose={() => { setResult(null); setOpen(false); }}
          />
        )}
      </Dialog>
    </>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function StaffManagementPage() {
  const { can, email: myEmail, permissions: myPermissions } = useStaff();
  const [invitedCount, setInvitedCount] = useState(0);
  const { data, error, loading, reload } = useQuery<StaffMember[]>(
    can("SUPERVISOR") ? "staff" : null,
  );

  if (!can("SUPERVISOR")) {
    return (
      <>
        <PageHeader title="Staff Management" />
        <Notice tone="medium">
          Only staff members with the <strong>SUPERVISOR</strong> permission can manage accounts.
        </Notice>
      </>
    );
  }

  const members = data ?? [];

  return (
    <>
      <PageHeader
        title="Staff Management"
        description={`${members.length} Disaster Management account${members.length !== 1 ? "s" : ""}`}
        actions={
          <div className="flex items-center gap-2">
            <Button onClick={reload} busy={loading && !!data}>Refresh</Button>
            {/* Supervisors invite DM staff (only with permissions they hold) and Field Team responders. */}
            <InviteAccountDialog
              roles={["DISASTER_MGMT", "FIELD_TEAM"]}
              grantablePermissions={myPermissions}
              onInvited={() => { setInvitedCount((n) => n + 1); reload(); }}
            />
          </div>
        }
      />

      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingRows />}

      {data && members.length === 0 && (
        <EmptyState title="No staff accounts yet.">Invite the first one with the button above.</EmptyState>
      )}

      {data && members.length > 0 && (
        <Card bodyClassName="p-0" className="mt-4">
          <ul className="divide-y divide-border">
            {members.map((m) => {
              const isMe = m.email === myEmail;
              return (
                <li key={m.user_id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
                  {/* Avatar */}
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-full border border-border bg-surface-muted text-sm font-bold text-foreground">
                    {m.full_name.charAt(0).toUpperCase()}
                  </div>

                  {/* Info */}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-sm">{m.full_name}</span>
                      {isMe && <Badge tone="info">You</Badge>}
                      {m.is_locked && <Badge tone="critical">Locked</Badge>}
                      {!m.mfa_enabled && <Badge tone="high">MFA not set</Badge>}
                      {m.status !== "ACTIVE" && <Badge tone="medium">{m.status}</Badge>}
                    </div>
                    <p className="text-xs text-muted mt-0.5">{m.email}{m.designation ? ` · ${m.designation}` : ""}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {m.permissions.length === 0 ? (
                        <span className="text-[11px] text-muted italic">No permissions assigned</span>
                      ) : (
                        m.permissions.map((p) => (
                          <Badge key={p} tone="info">{p}</Badge>
                        ))
                      )}
                    </div>
                    <p className="mt-1 text-[11px] text-muted">
                      Last login: {m.last_login_at ? new Date(m.last_login_at).toLocaleString() : "Never"}
                      {" · "}Added {new Date(m.created_at).toLocaleDateString()}
                    </p>
                  </div>

                  {/* Actions — disabled for own account */}
                  {!isMe && (
                    <div className="flex shrink-0 gap-2">
                      <EditPermissionsDialog member={m} onDone={reload} />
                      {/* A pending invitee has no authenticator yet: resend or revoke it below instead. */}
                      {m.status !== "PENDING_SETUP" && <ResetMfaDialog member={m} onDone={reload} />}
                    </div>
                  )}
                  {isMe && (
                    <span className="text-[11px] text-muted italic shrink-0">Cannot edit your own account</span>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      <PendingInvitations refreshKey={invitedCount} />
    </>
  );
}
