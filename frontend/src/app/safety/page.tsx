import type { Metadata } from "next";

import { PublicPage, Section } from "@/components/public/PublicPage";
import { API_URL } from "@/lib/config";

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
      { name: "India Meteorological Department (IMD)", url: "https://mausam.imd.gov.in" },
      { name: "NDMA – Guidelines for the Management of Cyclones", url: "https://ndma.gov.in/ndma-guidelines" },
    ],
  },
  {
    title: "Flood",
    before: ["Know your nearest high ground and evacuation route.", "Keep documents and essentials in a waterproof bag."],
    during: ["Move to higher ground early. Do not walk or drive through floodwater.", "Switch off electricity at the mains if safe to do so."],
    after: ["Return only when authorities say it is safe.", "Treat all floodwater as contaminated and boil drinking water."],
    sources: [
      { name: "NDMA – Guidelines for the Management of Floods", url: "https://ndma.gov.in/ndma-guidelines" },
      { name: "NDMA – Guidelines for the Management of Urban Flooding", url: "https://ndma.gov.in/ndma-guidelines" },
      { name: "Gujarat State Disaster Management Authority (GSDMA)", url: "https://gsdma.gujarat.gov.in" },
    ],
  },
  {
    title: "Fire",
    before: ["Know two exits from every room and where extinguishers are.", "Keep cords out from under rugs and do not overload sockets."],
    during: ["Raise the alarm and leave immediately. Crawl low under smoke.", "Do not use lifts. Call 101 (Fire) or 112 (ERSS) once you are safe."],
    after: ["Do not re-enter until the fire service says it is safe.", "Seek medical help for burns or smoke inhalation."],
    sources: [
      { name: "NDMA – Guidelines (fire and chemical disasters)", url: "https://ndma.gov.in/ndma-guidelines" },
      { name: "Emergency Response Support System (ERSS 112)", url: "https://112.gov.in" },
    ],
  },
];

type PublishedGuidance = { content_id: string; scenario: string; title: string; body: string; source: string | null; version: number };
type PublishedUpdate = { update_id: string; scenario: string; title: string; body: string; area_label: string | null; published_at: string | null };

const SCENARIO_NAME: Record<string, string> = { cyclone: "Cyclone", industrial_fire: "Fire", urban_flooding: "Flood" };

/** Dispatcher-published guidance and updates. null means the service could not be reached; the static guidance below still shows. */
async function loadPublished<T>(path: string): Promise<T[] | null> {
  try {
    const res = await fetch(`${API_URL}/api/v1/public/${path}`, { next: { revalidate: 60 }, signal: AbortSignal.timeout(5000) });
    return res.ok ? ((await res.json()) as T[]) : null;
  } catch {
    return null;
  }
}

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

export default async function SafetyPage() {
  const [guidance, updates] = await Promise.all([
    loadPublished<PublishedGuidance>("safety-content"),
    loadPublished<PublishedUpdate>("updates"),
  ]);
  return (
    <PublicPage activeHref="/safety" title="Safety guidance" intro="Basic guidance for the hazards most likely in Gujarat. Always follow instructions from local authorities first.">
      {updates && updates.length > 0 && (
        <Section title="Verified updates from Gujarat dispatchers">
          {updates.map((u) => (
            <div key={u.update_id}>
              <h3 className="font-semibold text-slate-900">{u.title}</h3>
              <p className="text-xs text-slate-500">
                {SCENARIO_NAME[u.scenario] ?? u.scenario}
                {u.area_label ? ` · ${u.area_label}` : ""}
                {u.published_at ? ` · ${new Date(u.published_at).toLocaleString("en-IN")}` : ""}
              </p>
              <p className="whitespace-pre-wrap">{u.body}</p>
            </div>
          ))}
        </Section>
      )}
      {guidance && guidance.length > 0 && (
        <Section title="Approved guidance from dispatchers">
          {guidance.map((g) => (
            <div key={g.content_id}>
              <h3 className="font-semibold text-slate-900">{g.title}</h3>
              <p className="text-xs text-slate-500">
                {SCENARIO_NAME[g.scenario] ?? g.scenario}
                {g.source ? ` · Source: ${g.source}` : ""}
              </p>
              <p className="whitespace-pre-wrap">{g.body}</p>
            </div>
          ))}
        </Section>
      )}
      {(guidance === null || updates === null) && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="status">
          Live dispatcher guidance could not be loaded right now. The general guidance below is still available.
        </p>
      )}
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
