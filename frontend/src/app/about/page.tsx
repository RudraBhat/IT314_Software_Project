import type { Metadata } from "next";

import { PublicPage, Section } from "@/components/public/PublicPage";

export const metadata: Metadata = { title: "About · ResQ Gujarat" };

export default function AboutPage() {
  return (
    <PublicPage
      title="About ResQ"
      intro="A disaster response coordination platform for Gujarat that connects citizens, dispatchers and field teams."
    >
      <Section title="What it does">
        <p>
          Citizens report cyclones, floods, fires and earthquakes. Trained dispatchers verify each report, and only
          verified incidents appear on the public map. Dispatchers then assign response teams, and field teams update
          their progress until the incident is resolved.
        </p>
      </Section>
      <Section title="What is real and what is simulated">
        <ul className="list-disc space-y-1 pl-5">
          <li>Incident reports, verification and dispatch run on the live platform.</li>
          <li>Some map entries and alerts are marked <strong>simulated</strong> or <strong>sample</strong> for demonstration.</li>
          <li>AI suggestions are advisory only. A human dispatcher always makes the decision.</li>
          <li>Donations run in a <strong>sandbox</strong>; no real money moves.</li>
        </ul>
      </Section>
      <Section title="Privacy">
        <p>
          The public map shows only the reference, scenario, district, status, priority and an approximate location.
          Reporter identity and free-text descriptions are never published.
        </p>
      </Section>
      <Section title="Emergency numbers">
        <ul className="list-disc space-y-1 pl-5">
          <li>112 – National emergency response</li>
          <li>108 – Ambulance</li>
          <li>101 – Fire</li>
          <li>1070 – Gujarat State Disaster helpline</li>
        </ul>
        <p className="text-slate-500">
          This portal does not replace emergency services. In immediate danger, call 112.
        </p>
      </Section>
      <Section title="Map data">
        <p>
          Map tiles © <a className="text-sky-700 underline" href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>{" "}
          contributors.
        </p>
      </Section>
    </PublicPage>
  );
}
