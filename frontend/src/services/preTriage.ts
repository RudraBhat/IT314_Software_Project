import type { Scenario } from "./citizenApi";

/** Needs a reporter can tick; sent to the dispatcher as part of the description. */
export const URGENT_NEEDS: Record<Scenario, string[]> = {
  urban_flooding: ["Rescue boat", "Drinking water", "Medical aid", "Evacuation transport", "Food"],
  cyclone: ["Shelter", "Medical aid", "Power restoration", "Road clearance", "Drinking water"],
  industrial_fire: ["Fire brigade", "Ambulance", "Evacuation", "Hazmat team", "Police cordon"],
};

export interface PreTriageHint {
  level: "CRITICAL" | "HIGH" | null;
  reasons: string[];
}

const LIFE_THREAT = /\b(trapped|stuck|stranded|collapse[d]?|drown\w*|unconscious|bleeding|explosion|rooftop|burn\w*)\b/i;
const HAZMAT = /\b(chemical|gas leak|toxic|ammonia|chlorine|cylinder|blast)\b/i;

/**
 * Instant, rule-based hint shown while a citizen writes a report. It is advisory: it never
 * changes the urgency the citizen picked, and the dispatcher alone assigns the verified priority.
 */
export function preTriage(scenario: Scenario, description: string, peopleAffected: number, needs: string[]): PreTriageHint {
  const reasons: string[] = [];
  if (LIFE_THREAT.test(description)) reasons.push("The description mentions people who may be trapped or in direct danger.");
  if (peopleAffected >= 25) reasons.push(`${peopleAffected} people are affected.`);
  if (needs.some((n) => /medical|ambulance/i.test(n))) reasons.push("Medical help is needed.");
  if (scenario === "industrial_fire" && HAZMAT.test(description)) reasons.push("Chemicals or gas may be involved.");
  if (scenario === "urban_flooding" && /\b(current|flash|overflow\w*|rising)\b/i.test(description)) reasons.push("Flood water appears to be rising or moving fast.");

  const level = reasons.length >= 2 || LIFE_THREAT.test(description) ? "CRITICAL" : reasons.length === 1 ? "HIGH" : null;
  return { level, reasons };
}
