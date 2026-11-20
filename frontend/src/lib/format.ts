import type { Tone } from "@/components/ui";

export const SCENARIOS = ["cyclone", "industrial_fire", "urban_flooding"] as const;
export const INCIDENT_STATUSES = [
  "SUBMITTED",
  "NEEDS_INFORMATION",
  "VERIFIED",
  "DISPATCHED",
  "RESOLVED",
  "CLOSED",
  "REJECTED",
] as const;
export const PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const;

export const scenarioLabel: Record<string, string> = {
  cyclone: "Cyclone",
  industrial_fire: "Industrial fire",
  urban_flooding: "Urban flooding",
};

/** Icon for each resource type (resources.type). */
export const RESOURCE_ICON: Record<string, string> = { TEAM: "👷", VEHICLE: "🚒", SUPPLY: "📦", SUPPORT: "🛠️" };

/** Agency types the backend accepts (agencies.agency_type), in the order dispatchers usually reach for them. */
export const AGENCY_TYPES = ["FIRE", "MEDICAL", "NDRF", "POLICE", "MUNICIPAL", "NGO"] as const;

export const AGENCY_TYPE_LABEL: Record<string, string> = {
  FIRE: "Fire",
  POLICE: "Police",
  NDRF: "NDRF / SDRF",
  MEDICAL: "Medical",
  MUNICIPAL: "Municipal / state",
  NGO: "NGO",
};

export const AGENCY_TYPE_ICON: Record<string, string> = {
  FIRE: "🚒",
  POLICE: "🚓",
  NDRF: "🛟",
  MEDICAL: "🚑",
  MUNICIPAL: "🏛️",
  NGO: "🤝",
};

/**
 * Disaster Management permissions in plain words, most senior first, with what each one allows and a
 * colour so the same permission looks the same everywhere.
 */
export const PERMISSION_INFO: Record<string, { label: string; description: string; tone: string; icon: string }> = {
  SUPERVISOR: { label: "Supervisor", description: "Full oversight + staff management", tone: "bg-violet-100 text-violet-800 ring-violet-200", icon: "★" },
  DISPATCH: { label: "Dispatch", description: "Assign & dispatch responder units", tone: "bg-sky-100 text-sky-800 ring-sky-200", icon: "➜" },
  CLOSURE: { label: "Closure", description: "Close & archive incidents", tone: "bg-emerald-100 text-emerald-800 ring-emerald-200", icon: "✓" },
  MODERATOR: { label: "Moderator", description: "Verify/reject evidence uploads", tone: "bg-amber-100 text-amber-800 ring-amber-200", icon: "◐" },
  PUBLISHER: { label: "Publisher", description: "Publish incidents & public alerts", tone: "bg-rose-100 text-rose-800 ring-rose-200", icon: "✎" },
};

/** Permissions sorted most senior first (unknown ones last). */
export function sortPermissions(permissions: readonly string[]): string[] {
  const order = Object.keys(PERMISSION_INFO);
  const rank = (p: string) => (order.includes(p) ? order.indexOf(p) : order.length);
  return [...permissions].sort((a, b) => rank(a) - rank(b));
}

/** Disaster icon for each supported scenario, used on maps and assignment cards. */
export const SCENARIO_ICON: Record<string, string> = {
  cyclone: "🌀",
  industrial_fire: "🔥",
  urban_flooding: "🌊",
};

/**
 * Disaster icon for an official alert, read from its event type (free text from the feed, for example
 * "Very Severe Cyclonic Storm" or "Heavy Rainfall"). Unknown hazards get a plain warning sign.
 */
export function hazardIcon(eventType: string | null | undefined): string {
  const t = (eventType ?? "").toLowerCase();
  if (/cyclon|storm|depression|wind|gale/.test(t)) return "🌀";
  if (/flood|rain|inundat|tsunami|surge|water/.test(t)) return "🌊";
  if (/fire|chemical|industrial|explosion|gas|hazmat/.test(t)) return "🔥";
  if (/thunder|lightning/.test(t)) return "⛈️";
  if (/heat|hot/.test(t)) return "🌡️";
  if (/landslide/.test(t)) return "⛰️";
  return "⚠️";
}

export const statusTone: Record<string, Tone> = {
  SUBMITTED: "medium",
  NEEDS_INFORMATION: "medium",
  VERIFIED: "info",
  REQUESTED: "info",
  ACKNOWLEDGED: "info",
  DISPATCHED: "high",
  ACTIVE: "low",
  AVAILABLE: "low",
  RESOLVED: "low",
  COMPLETED: "low",
  CLOSED: "neutral",
  REJECTED: "critical",
  FAILED: "critical",
  UNAVAILABLE: "neutral",
  MAINTENANCE: "medium",
};

export const priorityTone: Record<string, Tone> = {
  CRITICAL: "critical",
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
};

const labels: Record<string, string> = {
  NEEDS_INFORMATION: "Needs information",
  INDUSTRIAL_FIRE: "Industrial fire",
  URBAN_FLOODING: "Urban flooding",
  EN_ROUTE: "En route",
  IN_PROGRESS: "In progress",
  UNAVAILABLE: "Unavailable",
};

export function label(value: string): string {
  return labels[value] ?? value.toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatNumber(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(number)
    : "—";
}

export function formatMoney(value: number | string, currency = "INR"): string {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(number)
    : "—";
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return "—";
  const totalSeconds = Math.floor(seconds);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m`;
  return `${totalSeconds}s`;
}

export function timeAgo(value: string | null | undefined): string {
  if (!value) return "—";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "—";

  const difference = timestamp - Date.now();
  const absoluteSeconds = Math.abs(difference) / 1000;
  if (absoluteSeconds < 60) return "just now";

  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  const [unit, seconds] = units.find(([, unitSeconds]) => absoluteSeconds >= unitSeconds) ?? ["minute", 60];
  const count = Math.round(difference / (seconds * 1000));
  return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(count, unit);
}
