"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { CitizenDashboardView } from "@/components/role-views/CitizenDashboardView";
import { signOut } from "@/app/login/actions";

interface CitizenDashboardClientProps {
  user: {
    id: string;
    name: string;
    phone?: string;
  };
}

export function CitizenDashboardClient({ user }: CitizenDashboardClientProps) {
  const router = useRouter();

  return (
    <CitizenDashboardView
      currentUser={user}
      onViewPublicMap={() => router.push("/")}
      onSignOut={async () => {
        await signOut();
      }}
    />
  );
}
