import { redirectNonCitizens } from "@/lib/citizen-area";
import ReportForm from "./ReportForm";

// Citizens and guests report incidents. Staff and field responders triage and dispatch from their own
// workspace, so send them there on the server instead of showing a form and swapping it out later.
export default async function ReportPage() {
  await redirectNonCitizens();
  return <ReportForm />;
}
