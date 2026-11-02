"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Card, cx } from "@/components/ui";
import { scenarioLabel } from "@/lib/format";

type Step = { title: string; text: string; href: string };

const FLOW: Record<string, Step[]> = {
  cyclone: [
    { title: "Check warnings", text: "Review cyclone alerts and signals for the coastal districts.", href: "/dm/signals" },
    { title: "Verify reports", text: "Open reports from the affected coast and confirm or request information.", href: "/dm/incidents?status=SUBMITTED" },
    { title: "Prepare resources", text: "Confirm shelter teams, vehicles and supplies are available.", href: "/dm/resources" },
    { title: "Dispatch", text: "Assign the agency on the verified incident. You approve every dispatch.", href: "/dm/dispatches" },
    { title: "Inform the public", text: "Publish a safety update for residents.", href: "/dm/updates" },
  ],
  industrial_fire: [
    { title: "Verify the report", text: "Confirm location and hazards (chemicals, trapped people).", href: "/dm/incidents?status=SUBMITTED" },
    { title: "Check duplicates", text: "Merge reports of the same fire on the incident page.", href: "/dm/incidents" },
    { title: "Dispatch fire and medical", text: "Request the fire brigade and ambulance agencies.", href: "/dm/dispatches" },
    { title: "Track acknowledgement", text: "Escalate dispatches nobody has acknowledged.", href: "/dm/dispatches?overdue=1" },
    { title: "Resolve and close", text: "Resolve once the scene is safe; close with a recorded reason.", href: "/dm/incidents" },
  ],
  urban_flooding: [
    { title: "Verify reports", text: "Cluster flood reports and confirm the worst-hit areas.", href: "/dm/incidents?status=SUBMITTED" },
    { title: "Find rescue capacity", text: "Look for boats and pumps among available resources.", href: "/dm/resources" },
    { title: "Dispatch", text: "Assign rescue teams; quantities are reserved automatically.", href: "/dm/dispatches" },
    { title: "Aid and needs", text: "Verify aid contributions and post open needs.", href: "/dm/aid" },
    { title: "Review the day", text: "Check response times in analytics.", href: "/dm/analytics" },
  ],
};

/** Training checklist for a scenario drill. It links to the real pages and never changes data. */
export function ScenarioWalkthrough() {
  const [scenario, setScenario] = useState("cyclone");
  const [done, setDone] = useState<Record<string, boolean>>({});
  const steps = FLOW[scenario];

  return (
    <Card
      title="Scenario walkthrough"
      subtitle="A guided drill for staff. It only links to pages; nothing is created or changed."
      actions={<Badge tone="info">Training aid</Badge>}
    >
      <div className="mb-3 flex flex-wrap gap-2" role="tablist" aria-label="Scenario">
        {Object.keys(FLOW).map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={scenario === s}
            onClick={() => setScenario(s)}
            className={cx("rounded-full px-3 py-1 text-xs", scenario === s ? "bg-sky-500/15 font-semibold text-sky-300" : "text-muted hover:bg-surface-muted")}
          >
            {scenarioLabel[s]}
          </button>
        ))}
      </div>
      <ol className="space-y-2">
        {steps.map((step, i) => {
          const key = `${scenario}-${i}`;
          return (
            <li key={key} className="flex items-start gap-3 text-sm">
              <input type="checkbox" className="mt-1" checked={!!done[key]} onChange={(e) => setDone({ ...done, [key]: e.target.checked })} aria-label={`Step ${i + 1} done`} />
              <div className={cx(done[key] && "text-muted line-through")}>
                <Link href={step.href} className="font-medium text-info hover:underline">{i + 1}. {step.title}</Link>
                <p className="text-xs text-muted">{step.text}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
