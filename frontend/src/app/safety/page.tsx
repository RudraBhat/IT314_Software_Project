import type { Metadata } from "next";

import { PublicPage, Section } from "@/components/public/PublicPage";

export const metadata: Metadata = { title: "Safety guidance · ResQ Gujarat" };

type Guide = { title: string; before: string[]; during: string[]; after: string[]; sources: { name: string; url: string }[] };

// General public guidance, each block naming the authority it is based on.
// Dispatcher-published guidance (DM safety content) takes precedence when available.
const GUIDES: Guide[] = [
  {
    title: "Cyclone",
    before: ["Follow IMD warnings and local administration announcements.", "Keep a torch, radio, drinking water, medicines and documents ready.", "Move to a cyclone shelter if told to evacuate."],
    during: ["Stay indoors, away from windows.", "Do not go out until authorities declare it safe, even if the wind drops (the eye of the storm)."],
    after: ["Avoid fallen power lines and flooded roads.", "Drink only safe water and report damage to local authorities."],
    sources: [
      { name: "India Meteorological Department", url: "https://mausam.imd.gov.in" },
      { name: "NDMA – Cyclone guidelines", url: "https://ndma.gov.in" },
    ],
  },
  {
    title: "Flood",
    before: ["Know your nearest high ground and evacuation route.", "Keep documents and essentials in a waterproof bag."],
    during: ["Move to higher ground early. Do not walk or drive through floodwater.", "Switch off electricity at the mains if safe to do so."],
    after: ["Return only when authorities say it is safe.", "Treat all floodwater as contaminated and boil drinking water."],
    sources: [
      { name: "NDMA – Flood guidelines", url: "https://ndma.gov.in" },
      { name: "Gujarat State Disaster Management Authority", url: "https://gsdma.gujarat.gov.in" },
    ],
  },
  {
    title: "Earthquake",
    before: ["Secure heavy furniture and know safe spots in each room.", "Practise Drop, Cover and Hold On."],
    during: ["Drop, cover your head and hold on. Stay away from windows and heavy objects.", "If outdoors, move to an open area away from buildings and wires."],
    after: ["Expect aftershocks. Check for injuries and gas leaks.", "Use stairs, not lifts, and follow official instructions."],
    sources: [
      { name: "NDMA – Earthquake guidelines", url: "https://ndma.gov.in" },
      { name: "Gujarat State Disaster Management Authority", url: "https://gsdma.gujarat.gov.in" },
    ],
  },
  {
    title: "Fire",
    before: ["Know two exits from every room and where extinguishers are.", "Do not overload electrical sockets."],
    during: ["Raise the alarm and leave immediately. Crawl low under smoke.", "Do not use lifts. Call 101 (Fire) or 112 once you are safe."],
    after: ["Do not re-enter until the fire service says it is safe.", "Seek medical help for burns or smoke inhalation."],
    sources: [{ name: "NDMA – Fire safety guidance", url: "https://ndma.gov.in" }],
  },
];

const List = ({ title, items }: { title: string; items: string[] }) => (
  <div>
    <h3 className="font-semibold text-slate-900">{title}</h3>
    <ul className="list-disc pl-5">
      {items.map((i) => (
        <li key={i}>{i}</li>
      ))}
    </ul>
  </div>
);

export default function SafetyPage() {
  return (
    <PublicPage title="Safety guidance" intro="Basic guidance for the hazards most likely in Gujarat. Always follow instructions from local authorities first.">
      {GUIDES.map((g) => (
        <Section key={g.title} title={g.title}>
          <List title="Before" items={g.before} />
          <List title="During" items={g.during} />
          <List title="After" items={g.after} />
          <p className="pt-2 text-xs text-slate-500">
            Sources:{" "}
            {g.sources.map((s, i) => (
              <span key={s.name}>
                {i > 0 && " · "}
                <a className="text-sky-700 underline" href={s.url} target="_blank" rel="noreferrer">{s.name}</a>
              </span>
            ))}
          </p>
        </Section>
      ))}
    </PublicPage>
  );
}
