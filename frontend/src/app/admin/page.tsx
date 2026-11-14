"use client";

import { useState } from "react";

import { InviteAccountDialog } from "@/components/staff/InviteAccountDialog";
import { PendingInvitations } from "@/components/staff/PendingInvitations";
import { Notice, PageHeader } from "@/components/ui";

export default function AdminAccountsPage() {
  const [invitedCount, setInvitedCount] = useState(0);

  return (
    <>
      <PageHeader
        title="Platform accounts"
        description="Invite Disaster Management staff, Field Team responders and other administrators."
        actions={
          <InviteAccountDialog
            roles={["DISASTER_MGMT", "FIELD_TEAM", "APP_MGMT"]}
            onInvited={() => setInvitedCount((n) => n + 1)}
          />
        }
      />
      <Notice tone="info">
        Every invitee sets their own password and authenticator from the emailed link. Field Team
        responders are linked to their team at invitation time, so they can see assignments as soon
        as setup is complete.
      </Notice>
      <PendingInvitations refreshKey={invitedCount} />
    </>
  );
}
