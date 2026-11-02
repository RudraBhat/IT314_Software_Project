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
import { api, useQuery, newIdempotencyKey } from "@/lib/api";
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

type CreateResult = {
  user_id: string;
  email: string;
  full_name: string;
  permissions: string[];
  mfa_secret: string;
  mfa_uri: string;
  message: string;
};

const ALL_PERMISSIONS = ["PUBLISHER", "MODERATOR", "CLOSURE", "DISPATCH", "SUPERVISOR"] as const;

const PERMISSION_DESC: Record<string, string> = {
  PUBLISHER: "Publish incidents & public alerts",
  MODERATOR: "Verify/reject evidence uploads",
  CLOSURE: "Close & archive incidents",
  DISPATCH: "Assign & dispatch responder units",
  SUPERVISOR: "Full oversight + staff management",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function PermissionChip({ perm, active, onClick }: { perm: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={PERMISSION_DESC[perm]}
      className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition cursor-pointer select-none ${
        active
          ? "bg-sky-500/20 border-sky-500/60 text-sky-300"
          : "bg-surface-muted border-border text-muted hover:border-sky-500/40 hover:text-foreground"
      }`}
    >
      {perm}
    </button>
  );
}

function PermissionEditor({
  value,
  onChange,
}: {
  value: string[];
  onChange: (perms: string[]) => void;
}) {
  const toggle = (p: string) =>
    onChange(value.includes(p) ? value.filter((x) => x !== p) : [...value, p]);
  return (
    <div className="flex flex-wrap gap-2">
      {ALL_PERMISSIONS.map((p) => (
        <PermissionChip key={p} perm={p} active={value.includes(p)} onClick={() => toggle(p)} />
      ))}
    </div>
  );
}

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

// ─── Create Staff Dialog ──────────────────────────────────────────────────────

function CreateStaffDialog({ onCreated }: { onCreated: () => void }) {
  const { run, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [mfaResult, setMfaResult] = useState<CreateResult | null>(null);

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [designation, setDesignation] = useState("");
  const [permissions, setPermissions] = useState<string[]>([]);
  const [showPass, setShowPass] = useState(false);

  function reset() {
    setEmail(""); setFullName(""); setPassword(""); setConfirmPassword("");
    setPhone(""); setDesignation(""); setPermissions([]); setShowPass(false);
  }

  async function handleCreate() {
    if (password !== confirmPassword) {
      alert("Passwords do not match.");
      return;
    }
    if (password.length < 12) {
      alert("Password must be at least 12 characters.");
      return;
    }
    const result = await run<CreateResult>(
      "create-staff",
      () =>
        api<CreateResult>("staff", {
          method: "POST",
          body: { email, full_name: fullName, password, phone: phone || undefined, designation: designation || undefined, permissions },
          idempotencyKey: newIdempotencyKey(),
        }),
      undefined, // don't show default toast — we show the MFA box instead
    );
    if (result) {
      setMfaResult(result);
      reset();
      onCreated();
    }
  }

  const inputClass = "w-full rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm text-foreground placeholder-muted focus:outline-none focus:border-sky-500 transition";

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)} id="add-staff-btn">
        + Add Staff Account
      </Button>

      {/* MFA reveal dialog — shown after creation */}
      <Dialog
        open={!!mfaResult}
        onClose={() => setMfaResult(null)}
        title={`Account created — ${mfaResult?.full_name}`}
      >
        {mfaResult && (
          <MfaRevealBox
            secret={mfaResult.mfa_secret}
            uri={mfaResult.mfa_uri}
            onClose={() => setMfaResult(null)}
          />
        )}
      </Dialog>

      {/* Create form dialog */}
      <Dialog
        open={open && !mfaResult}
        onClose={() => { setOpen(false); reset(); }}
        title="Add Disaster Management Staff"
        footer={
          <>
            <Button onClick={() => { setOpen(false); reset(); }}>Cancel</Button>
            <Button
              id="create-staff-submit"
              variant="primary"
              busy={busy === "create-staff"}
              disabled={!email || !fullName || !password || !confirmPassword}
              onClick={handleCreate}
            >
              Create Account
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Notice tone="info">
            The new account will require <strong>MFA enrolment</strong>. The TOTP secret will be shown once after creation.
          </Notice>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="cs-name" className="block text-xs font-semibold text-muted mb-1">Full Name *</label>
              <input id="cs-name" type="text" value={fullName} onChange={e => setFullName(e.target.value)} placeholder="e.g. Asha Rao" className={inputClass} autoComplete="off" />
            </div>
            <div>
              <label htmlFor="cs-email" className="block text-xs font-semibold text-muted mb-1">Email *</label>
              <input id="cs-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="asha@resq.gov.in" className={inputClass} autoComplete="off" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="cs-phone" className="block text-xs font-semibold text-muted mb-1">Phone</label>
              <input id="cs-phone" type="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+91 98765 00000" className={inputClass} />
            </div>
            <div>
              <label htmlFor="cs-designation" className="block text-xs font-semibold text-muted mb-1">Designation</label>
              <input id="cs-designation" type="text" value={designation} onChange={e => setDesignation(e.target.value)} placeholder="e.g. Dispatcher" className={inputClass} />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label htmlFor="cs-password" className="text-xs font-semibold text-muted">Password * (min 12 chars)</label>
              <button type="button" onClick={() => setShowPass(v => !v)} className="text-[11px] text-sky-400 hover:text-sky-300 cursor-pointer">
                {showPass ? "Hide" : "Show"}
              </button>
            </div>
            <input id="cs-password" type={showPass ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)} placeholder="Minimum 12 characters" className={inputClass} autoComplete="new-password" />
          </div>

          <div>
            <label htmlFor="cs-confirm" className="block text-xs font-semibold text-muted mb-1">Confirm Password *</label>
            <input id="cs-confirm" type={showPass ? "text" : "password"} value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} placeholder="Re-enter password" className={inputClass} autoComplete="new-password" />
          </div>

          <div>
            <p className="text-xs font-semibold text-muted mb-2">Permissions</p>
            <PermissionEditor value={permissions} onChange={setPermissions} />
            <p className="mt-2 text-[10px] text-muted">Click to toggle. Hover a permission to see what it grants.</p>
          </div>
        </div>
      </Dialog>
    </>
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
  const { can, email: myEmail } = useStaff();
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
            <CreateStaffDialog onCreated={reload} />
          </div>
        }
      />

      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <LoadingRows />}

      {data && members.length === 0 && (
        <EmptyState title="No staff accounts yet.">Create the first one with the button above.</EmptyState>
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
                      <ResetMfaDialog member={m} onDone={reload} />
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
    </>
  );
}
