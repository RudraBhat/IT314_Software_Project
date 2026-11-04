import type { Metadata } from "next";

import { PublicPage, Section } from "@/components/public/PublicPage";

export const metadata: Metadata = { title: "How to use · ResQ Gujarat" };

const Steps = ({ items }: { items: string[] }) => (
  <ol className="list-decimal space-y-1 pl-5">
    {items.map((i) => (
      <li key={i}>{i}</li>
    ))}
  </ol>
);

export default function HowToPage() {
  return (
    <PublicPage title="How to use ResQ" intro="Step-by-step guides for the three ways people use the platform.">
      <Section title="Citizens: register, report, track">
        <Steps
          items={[
            "Create an account from Sign up, then sign in.",
            "Choose Report Incident and pick the scenario (cyclone, flood, fire or earthquake).",
            "Describe what is happening, how many people are affected and how urgent it is.",
            "Set the location with GPS, by placing a pin inside Gujarat, or by searching an address.",
            "Submit and note your reference number.",
            "Open My Reports to follow the status. If a dispatcher asks for more information, answer there.",
          ]}
        />
      </Section>
      <Section title="Dispatchers: sign in, verify, assign">
        <Steps
          items={[
            "Sign in at Staff login with your password and the one-time MFA code.",
            "Open Incidents and review new reports. Check for duplicates before verifying.",
            "Verify, reject, or request more information. Set the priority.",
            "Review the recommended teams. Recommendations need your confirmation and never dispatch on their own.",
            "Confirm the assignment, track progress, and mark the incident resolved once field teams complete.",
          ]}
        />
      </Section>
      <Section title="Field teams: acknowledge, update, complete">
        <Steps
          items={[
            "Sign in to see only the dispatches assigned to your team.",
            "Acknowledge the dispatch, or reject it with a reason.",
            "Update status to En route and On scene as you move.",
            "Request an additional team if you need one.",
            "Submit a completion summary. The dispatcher confirms resolution.",
          ]}
        />
      </Section>
    </PublicPage>
  );
}
