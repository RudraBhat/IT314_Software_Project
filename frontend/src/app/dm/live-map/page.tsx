import type { Metadata } from "next";

import { PublicMap } from "@/components/map/PublicMap";

export const metadata: Metadata = { title: "Live map · Operations · ResQ" };

/**
 * The live map inside the Disaster Management workspace: the public incident and alert map with the
 * operations layer (incidents and located resources) drawn on top, without leaving /dm.
 */
export default function DmLiveMapPage() {
  return (
    <main className="absolute inset-0">
      <PublicMap />
    </main>
  );
}
