import { redirect } from "next/navigation";

import { homeFor } from "./roles";
import { currentUser, sessionToken } from "./session";

/**
 * Guard for citizen-only pages (My Reports, Account, My Donations). A signed-in staff member or field
 * responder is sent to their own area instead of a page whose API calls would all be refused. Guests
 * are left alone: the page or the proxy decides what they see. A slow backend falls through to the page.
 */
export async function redirectNonCitizens(): Promise<void> {
  if (!(await sessionToken())) return;
  const user = await currentUser().catch(() => null);
  if (user && user.role !== "NORMAL_USER") redirect(homeFor(user.role));
}
