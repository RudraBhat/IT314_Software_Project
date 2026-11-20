"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { PublicMap } from "@/components/map/PublicMap";
import { UnifiedSiteHeader } from "@/components/navigation/UnifiedSiteHeader";
import { useSession } from "@/components/auth/SessionProvider";
import { homeFor } from "@/lib/roles";

/**
 * Public home: the live disaster map for visitors who are not signed in. Signed-in people are sent to
 * their own dashboard, which carries the map for their role (the citizen dashboard map, or the
 * Disaster Management live map).
 */
export default function PublicPortalPage() {
  const router = useRouter();
  const { session } = useSession();
  const home = session?.authenticated ? homeFor(session.role) : null;

  useEffect(() => {
    if (home && home !== "/login") router.replace(home);
  }, [home, router]);

  return (
    <div className="app-screen flex flex-col bg-slate-900 font-sans">
      <UnifiedSiteHeader activeHref="/" />
      <div className="relative min-h-0 flex-1">
        <PublicMap />
      </div>
    </div>
  );
}
