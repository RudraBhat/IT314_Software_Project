"use client";

import { useEffect, useState } from "react";

import { Button, Dialog, Field, Input, Notice, Select } from "@/components/ui";
import { useAction } from "@/components/use-action";
import {
  ROLE_LABEL,
  inviteAccount,
  listInvitationTeams,
  type InvitableRole,
  type InvitationTeam,
} from "@/services/invitationsApi";

import { ALL_PERMISSIONS, PermissionEditor } from "./PermissionEditor";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Props = {
  /** Roles this inviter may create; the first one is preselected. */
  roles: InvitableRole[];
  /** DM permissions this inviter may grant (a supervisor can only grant what they hold). */
  grantablePermissions?: readonly string[];
  onInvited: () => void;
  buttonLabel?: string;
};

/**
 * Invite an account by email (issue #100). No password is chosen for anyone and no MFA secret is
 * shown: the invitee opens the emailed /setup-account link, sets their own password and enrols TOTP.
 */
export function InviteAccountDialog({ roles, grantablePermissions = ALL_PERMISSIONS, onInvited, buttonLabel = "+ Invite account" }: Props) {
  const { run, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<InvitableRole>(roles[0]);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [designation, setDesignation] = useState("");
  const [permissions, setPermissions] = useState<string[]>([]);
  const [teamId, setTeamId] = useState("");
  const [callsign, setCallsign] = useState("");
  const [isLeader, setIsLeader] = useState(false);
  const [teams, setTeams] = useState<InvitationTeam[] | null>(null);
  const [teamsError, setTeamsError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const needsTeam = role === "FIELD_TEAM";

  useEffect(() => {
    if (!open || !needsTeam || teams !== null) return;
    listInvitationTeams()
      .then((res) => setTeams(res.items))
      .catch((e: unknown) => setTeamsError(e instanceof Error ? e.message : "Could not load teams."));
  }, [open, needsTeam, teams]);

  function reset() {
    setRole(roles[0]);
    setEmail(""); setFullName(""); setPhone(""); setDesignation("");
    setPermissions([]); setTeamId(""); setCallsign(""); setIsLeader(false); setErrors({});
  }

  function close() {
    setOpen(false);
    reset();
  }

  function validate(): Record<string, string> {
    const found: Record<string, string> = {};
    if (fullName.trim().length < 2) found.fullName = "Enter the person's full name.";
    if (!EMAIL_PATTERN.test(email.trim())) found.email = "Enter a valid email address.";
    if (needsTeam && !teamId) found.team = "Choose the team this responder joins.";
    return found;
  }

  async function submit() {
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length) return;
    const target = email.trim().toLowerCase();
    const result = await run(
      "invite",
      () =>
        inviteAccount({
          email: target,
          full_name: fullName.trim(),
          role,
          phone: phone.trim() || undefined,
          designation: designation.trim() || undefined,
          permissions: role === "DISASTER_MGMT" ? permissions : undefined,
          team_resource_id: needsTeam ? teamId : undefined,
          callsign: needsTeam ? callsign.trim() || undefined : undefined,
          is_leader: needsTeam ? isLeader : undefined,
        }),
      `Invitation sent to ${target}. They finish setup from the emailed link.`,
    );
    if (result) {
      close();
      onInvited();
    }
  }

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)} id="invite-account-btn">
        {buttonLabel}
      </Button>
      <Dialog
        open={open}
        onClose={close}
        title="Invite an account"
        footer={
          <>
            <Button onClick={close}>Cancel</Button>
            <Button id="invite-account-submit" variant="primary" busy={busy === "invite"} onClick={submit}>
              Send invitation
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Notice tone="info">
            An email with a one-time setup link is sent. The invitee chooses their own password and enrols an
            authenticator app; nobody else sees either.
          </Notice>

          {roles.length > 1 && (
            <Field label="Role">
              {(id) => (
                <Select id={id} value={role} onChange={(e) => setRole(e.target.value as InvitableRole)}>
                  {roles.map((r) => (
                    <option key={r} value={r}>{ROLE_LABEL[r]}</option>
                  ))}
                </Select>
              )}
            </Field>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Full name" error={errors.fullName}>
              {(id) => <Input id={id} value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={120} autoComplete="off" />}
            </Field>
            <Field label="Email" error={errors.email}>
              {(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} autoComplete="off" />}
            </Field>
            <Field label="Phone (optional)">
              {(id) => <Input id={id} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={32} />}
            </Field>
            <Field label="Designation (optional)">
              {(id) => <Input id={id} value={designation} onChange={(e) => setDesignation(e.target.value)} maxLength={120} />}
            </Field>
          </div>

          {role === "DISASTER_MGMT" && (
            <div>
              <p className="mb-2 text-xs font-medium text-muted">Permissions</p>
              <PermissionEditor value={permissions} onChange={setPermissions} available={grantablePermissions} />
            </div>
          )}

          {needsTeam && (
            <div className="space-y-3 rounded-lg border border-border p-3">
              <Field label="Team" error={errors.team ?? teamsError ?? undefined}>
                {(id) => (
                  <Select id={id} value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                    <option value="">{teams === null && !teamsError ? "Loading teams…" : "Select a team"}</option>
                    {teams?.map((t) => (
                      <option key={t.resource_id} value={t.resource_id}>
                        {t.name}{t.agency_name ? ` (${t.agency_name})` : ""}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Callsign (optional)">
                  {(id) => <Input id={id} value={callsign} onChange={(e) => setCallsign(e.target.value)} maxLength={100} />}
                </Field>
                <label className="flex items-center gap-2 self-end pb-2 text-sm">
                  <input type="checkbox" checked={isLeader} onChange={(e) => setIsLeader(e.target.checked)} />
                  Team leader
                </label>
              </div>
            </div>
          )}
        </div>
      </Dialog>
    </>
  );
}
