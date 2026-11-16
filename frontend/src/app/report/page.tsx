import { redirect } from "next/navigation";
import { homeFor, currentUser, sessionToken } from "@/lib/session";
import ReportForm from "./ReportForm";

// Citizens and guests report incidents. Staff and field responders triage and dispatch from their own
// workspace, so send them there on the server instead of showing a form and swapping it out later.
export default async function ReportPage() {
  // A guest has no session cookie: nothing to look up, so the form renders straight away.
  if (await sessionToken()) {
    const user = await currentUser().catch(() => null);
    // A slow or unreachable backend falls through to the form; the API still refuses staff submissions.
    if (user && user.role !== "NORMAL_USER") redirect(homeFor(user.role));
  }
  return <ReportForm />;
}
