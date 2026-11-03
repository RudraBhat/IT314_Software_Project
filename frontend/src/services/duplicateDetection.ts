import type { PublicIncident, Scenario } from "./citizenApi";

/** Haversine geodesic distance in metres. */
export function calculateDistanceMeters(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371e3;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const deltaPhi = ((lat2 - lat1) * Math.PI) / 180;
  const deltaLambda = ((lon2 - lon1) * Math.PI) / 180;

  const a =
    Math.sin(deltaPhi / 2) * Math.sin(deltaPhi / 2) +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(deltaLambda / 2) * Math.sin(deltaLambda / 2);
  return Math.round(R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
}

export interface NearbyIncident {
  incident: PublicIncident;
  distanceMeters: number;
}

const NEARBY_RADIUS_METERS = 2500;

/**
 * Hint for a citizen who is about to file a report: verified public incidents of the same
 * scenario close to the chosen point. Advisory only - the server and the dispatcher decide
 * what is a duplicate, and the citizen can still submit.
 */
export function findNearbyIncidents(
  lat: number,
  lon: number,
  scenario: Scenario,
  incidents: PublicIncident[],
): NearbyIncident[] {
  return incidents
    .filter((i) => i.scenario === scenario && i.lifecycle_status !== "RESOLVED")
    .map((incident) => ({ incident, distanceMeters: calculateDistanceMeters(lat, lon, incident.lat, incident.lon) }))
    .filter((n) => n.distanceMeters <= NEARBY_RADIUS_METERS)
    .sort((a, b) => a.distanceMeters - b.distanceMeters)
    .slice(0, 3);
}
