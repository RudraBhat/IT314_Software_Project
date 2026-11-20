import type { ReactNode } from "react";

import { redirectNonCitizens } from "@/lib/citizen-area";

export default async function CitizenOnlyLayout({ children }: { children: ReactNode }) {
  await redirectNonCitizens();
  return children;
}
