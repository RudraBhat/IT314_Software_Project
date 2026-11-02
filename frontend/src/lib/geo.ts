/**
 * Gujarat Geographic Bounds & Map Configuration (SRS / Disaster Management).
 * Bounding box: ~20.1°N to 24.7°N, 68.1°E to 74.5°E.
 */

export const GUJARAT_BOUNDS: [[number, number], [number, number]] = [
  [20.1, 68.1], // South-West
  [24.7, 74.5], // North-East
];

export const GUJARAT_CENTER: [number, number] = [22.2587, 71.1924];
export const GUJARAT_DEFAULT_ZOOM = 7;

export function isInGujarat(lat: number, lon: number): boolean {
  return lat >= 20.1 && lat <= 24.7 && lon >= 68.1 && lon <= 74.5;
}

export function clampToGujarat(lat: number, lon: number): [number, number] {
  const clampedLat = Math.min(Math.max(lat, GUJARAT_BOUNDS[0][0]), GUJARAT_BOUNDS[1][0]);
  const clampedLon = Math.min(Math.max(lon, GUJARAT_BOUNDS[0][1]), GUJARAT_BOUNDS[1][1]);
  return [clampedLat, clampedLon];
}

export const GUJARAT_DISTRICTS = [
  "Ahmedabad",
  "Amreli",
  "Anand",
  "Aravalli",
  "Banaskantha",
  "Bharuch",
  "Bhavnagar",
  "Botad",
  "Chhota Udaipur",
  "Dahod",
  "Dang",
  "Devbhoomi Dwarka",
  "Gandhinagar",
  "Gir Somnath",
  "Jamnagar",
  "Junagadh",
  "Kheda",
  "Kutch",
  "Mahisagar",
  "Mehsana",
  "Morbi",
  "Narmada",
  "Navsari",
  "Panchmahal",
  "Patan",
  "Porbandar",
  "Rajkot",
  "Sabarkantha",
  "Surat",
  "Surendranagar",
  "Tapi",
  "Vadodara",
  "Valsad",
] as const;

export type GujaratDistrict = (typeof GUJARAT_DISTRICTS)[number];
