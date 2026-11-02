"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { isInGujarat, clampToGujarat, GUJARAT_CENTER } from "@/lib/geo";
import { createReport } from "@/services/citizenApi";

const SCENARIOS = [
  { id: "urban_flooding", label: "Urban Flooding", icon: "🌊", desc: "Waterlogging, rising flood water, stranded residents" },
  { id: "cyclone", label: "Cyclone / Storm", icon: "🌀", desc: "High winds, structural damage, coastal surges" },
  { id: "industrial_fire", label: "Fire Emergency", icon: "🔥", desc: "Building, chemical, or industrial fires" },
  { id: "earthquake", label: "Earthquake", icon: "🏚️", desc: "Structural collapse, tremors, trapped victims" },
];

const SCENARIO_TO_CATEGORY: Record<string, string> = {
  urban_flooding: "Flood / Urban Flood",
  cyclone: "Cyclone / Coastal Flooding",
  industrial_fire: "Major Urban / Building Fire",
  earthquake: "Earthquake / Structural Collapse",
};

const URGENCIES = [
  { id: "LOW", label: "Low", color: "border-slate-600 text-slate-300" },
  { id: "MEDIUM", label: "Medium", color: "border-amber-600 text-amber-300" },
  { id: "HIGH", label: "High", color: "border-orange-600 text-orange-300" },
  { id: "CRITICAL", label: "Critical / Life Threat", color: "border-red-600 text-red-400 bg-red-950/30" },
];

export default function ReportIncidentPage() {
  // Form State
  const [scenario, setScenario] = useState("urban_flooding");
  const [description, setDescription] = useState("");
  const [peopleAffected, setPeopleAffected] = useState(1);
  const [urgency, setUrgency] = useState("HIGH");
  const [latitude, setLatitude] = useState(GUJARAT_CENTER[0]);
  const [longitude, setLongitude] = useState(GUJARAT_CENTER[1]);
  const [addressText, setAddressText] = useState("");
  const [landmark, setLandmark] = useState("");
  const [locationSource, setLocationSource] = useState<"GPS" | "MAP_PIN" | "ADDRESS">("MAP_PIN");

  // Idempotency key per form session (initialized lazily)
  const [idempotencyKey, setIdempotencyKey] = useState<string>(() => {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return `idemp-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
  });

  // Address search states
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Array<{ display_name: string; lat: string; lon: string }>>([]);
  const [isSearching, setIsSearching] = useState(false);
  const searchCacheRef = useRef<Record<string, Array<{ display_name: string; lat: string; lon: string }>>>({});

  // Submission States
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successResult, setSuccessResult] = useState<{ reference: string; status: string } | null>(null);

  // Validation
  const validLocation = isInGujarat(latitude, longitude);

  // GPS Geolocation Handler
  const handleUseGPS = () => {
    if (!navigator.geolocation) {
      setErrorMessage("Geolocation is not supported by your browser.");
      return;
    }
    setErrorMessage(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const rawLat = pos.coords.latitude;
        const rawLon = pos.coords.longitude;
        if (!isInGujarat(rawLat, rawLon)) {
          const [clampedLat, clampedLon] = clampToGujarat(rawLat, rawLon);
          setLatitude(clampedLat);
          setLongitude(clampedLon);
          setErrorMessage(
            `Your detected GPS location (${rawLat.toFixed(4)}, ${rawLon.toFixed(4)}) is outside Gujarat. Coordinates were adjusted to the nearest Gujarat border.`
          );
        } else {
          setLatitude(Number(rawLat.toFixed(5)));
          setLongitude(Number(rawLon.toFixed(5)));
        }
        setLocationSource("GPS");
      },
      (err) => {
        setErrorMessage(`Unable to retrieve GPS location: ${err.message}`);
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  };

  // Debounced Address Search
  useEffect(() => {
    if (!searchQuery.trim() || searchQuery.trim().length < 3) {
      return;
    }

    const queryKey = searchQuery.trim().toLowerCase();
    if (searchCacheRef.current[queryKey]) {
      const cached = searchCacheRef.current[queryKey];
      const timer = setTimeout(() => setSearchResults(cached), 0);
      return () => clearTimeout(timer);
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
            searchQuery + ", Gujarat, India"
          )}&limit=5&countrycodes=in`,
          {
            headers: {
              "Accept-Language": "en",
            },
          }
        );
        if (res.ok) {
          const data = await res.json();
          searchCacheRef.current[queryKey] = data;
          setSearchResults(data);
        }
      } catch {
        // Fallback gracefully on search error
      } finally {
        setIsSearching(false);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleSelectSearchResult = (result: { display_name: string; lat: string; lon: string }) => {
    const lat = parseFloat(result.lat);
    const lon = parseFloat(result.lon);
    if (!isInGujarat(lat, lon)) {
      setErrorMessage("Selected location falls outside Gujarat state boundaries.");
      return;
    }
    setLatitude(lat);
    setLongitude(lon);
    setAddressText(result.display_name);
    setLocationSource("ADDRESS");
    setSearchResults([]);
    setSearchQuery("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!description.trim()) {
      setErrorMessage("Please describe the emergency incident.");
      return;
    }

    if (!validLocation) {
      setErrorMessage("Incident coordinates must be within Gujarat State boundaries.");
      return;
    }

    setIsSubmitting(true);

    try {
      const resolvedCategory = SCENARIO_TO_CATEGORY[scenario] || "Flood / Urban Flood";
      const payload = {
        scenario,
        description: description.trim(),
        reported_urgency: urgency,
        people_affected: Number(peopleAffected),
        location_source: locationSource,
        latitude,
        longitude,
        address_text: addressText.trim() || undefined,
        landmark: landmark.trim() || undefined,
        // Stand-in compatible fields
        category: resolvedCategory,
        location_name: addressText || landmark || "Gujarat Incident Location",
        lat: latitude,
        lon: longitude,
        affected_people_count: Number(peopleAffected),
        urgent_needs: [urgency],
        reporter_name: "Citizen Reporter",
        reporter_phone: "",
      };

      const res = await createReport(payload, { idempotencyKey });

      if (res.error) {
        setErrorMessage(res.error);
        setIsSubmitting(false);
        return;
      }

      const refNumber = res.data?.incident_ref || res.data?.id || `INC-GUJ-${Date.now().toString().slice(-6)}`;
      const status = res.data?.status || res.data?.verification_status || "SUBMITTED";

      setSuccessResult({ reference: refNumber, status });
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to submit report. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans overflow-y-auto">
      {/* Header */}
      <header className="h-16 bg-slate-900 border-b border-slate-800 px-6 flex items-center justify-between sticky top-0 z-20">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2 hover:opacity-90 transition">
            <span className="text-xl">🛡️</span>
            <span className="font-bold text-white text-base tracking-wide">DRCH Gujarat</span>
          </Link>
          <span className="text-slate-600">/</span>
          <span className="text-xs uppercase tracking-wider font-semibold text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded border border-amber-400/20">
            Citizen Emergency Dispatch
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs font-medium">
          <Link href="/my-reports" className="text-slate-300 hover:text-white transition flex items-center gap-1.5">
            📋 My Reports
          </Link>
          <Link href="/citizen/dashboard" className="text-slate-300 hover:text-white transition flex items-center gap-1.5">
            🏠 Citizen Dashboard
          </Link>
          <Link href="/" className="text-slate-400 hover:text-slate-200 transition">
            Public Map
          </Link>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto p-6 md:p-8">
        {successResult ? (
          <div className="bg-slate-900 border border-emerald-500/30 rounded-2xl p-8 text-center shadow-xl space-y-6">
            <div className="w-16 h-16 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto text-3xl">
              ✓
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white mb-2">Emergency Report Submitted</h2>
              <p className="text-slate-400 text-sm max-w-md mx-auto">
                Your incident report has been securely registered in the Gujarat Disaster Response Operations Hub.
              </p>
            </div>

            <div className="inline-block bg-slate-950 border border-slate-800 rounded-xl px-6 py-4 text-left">
              <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold mb-1">
                Incident Reference
              </div>
              <div className="text-xl font-mono font-bold text-sky-400">{successResult.reference}</div>
              <div className="text-xs text-emerald-400 mt-1 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                Status: {successResult.status}
              </div>
            </div>

            <div className="flex items-center justify-center gap-4 pt-4">
              <Link
                href="/my-reports"
                className="bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold px-6 py-2.5 rounded-xl shadow-lg shadow-sky-600/30 transition"
              >
                Track Status in My Reports →
              </Link>
              <button
                type="button"
                onClick={() => {
                  setSuccessResult(null);
                  setDescription("");
                  if (typeof crypto !== "undefined" && crypto.randomUUID) {
                    setIdempotencyKey(crypto.randomUUID());
                  }
                }}
                className="bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium px-5 py-2.5 rounded-xl transition"
              >
                File Another Report
              </button>
            </div>
          </div>
        ) : (
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 md:p-8 shadow-xl">
            <div className="border-b border-slate-800 pb-5 mb-6">
              <h1 className="text-xl md:text-2xl font-bold text-white flex items-center gap-2.5">
                <span>📢</span> Report Emergency Incident
              </h1>
              <p className="text-slate-400 text-xs md:text-sm mt-1">
                Direct dispatch link to State Emergency Operations Center (SEOC) & Local Responders.
              </p>
            </div>

            {errorMessage && (
              <div className="mb-6 p-4 bg-red-950/60 border border-red-700/60 rounded-xl text-red-200 text-sm flex items-start gap-3">
                <span className="text-lg">⚠️</span>
                <div>
                  <div className="font-semibold">Unable to submit report</div>
                  <div className="text-xs mt-0.5 text-red-300">{errorMessage}</div>
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Scenario Picker */}
              <div>
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wider mb-2.5">
                  1. Disaster Scenario
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {SCENARIOS.map((item) => {
                    const isSelected = scenario === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setScenario(item.id)}
                        className={`p-3.5 rounded-xl border text-left flex items-start gap-3 transition cursor-pointer ${
                          isSelected
                            ? "bg-sky-950/40 border-sky-500 shadow-md shadow-sky-500/10"
                            : "bg-slate-950/60 border-slate-800 hover:border-slate-700 text-slate-400"
                        }`}
                      >
                        <span className="text-2xl">{item.icon}</span>
                        <div>
                          <div className={`text-sm font-bold ${isSelected ? "text-white" : "text-slate-300"}`}>
                            {item.label}
                          </div>
                          <div className="text-xs text-slate-500 mt-0.5">{item.desc}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Urgency and People Affected */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div>
                  <label className="block text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">
                    2. Urgency Level
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {URGENCIES.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setUrgency(item.id)}
                        className={`px-3 py-2 rounded-lg text-xs font-semibold border text-center transition ${
                          urgency === item.id
                            ? `${item.color} bg-slate-800 shadow`
                            : "border-slate-800 text-slate-500 hover:border-slate-700"
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">
                    3. Estimated People Affected
                  </label>
                  <div className="flex items-center gap-3">
                    <input
                      type="number"
                      min={1}
                      max={10000}
                      value={peopleAffected}
                      onChange={(e) => setPeopleAffected(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-28 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white font-mono text-center focus:outline-none focus:border-sky-500"
                    />
                    <div className="flex items-center gap-1.5">
                      {[1, 5, 10, 25].map((cnt) => (
                        <button
                          key={cnt}
                          type="button"
                          onClick={() => setPeopleAffected(cnt)}
                          className="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition"
                        >
                          {cnt}+
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">
                  4. Situation Description
                </label>
                <textarea
                  rows={3}
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe the current hazard, trapped individuals, water depth, road blockages, or urgent medical needs..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-sky-500 transition resize-none"
                />
              </div>

              {/* Location Picker Section */}
              <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-5 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <label className="block text-xs font-bold text-slate-200 uppercase tracking-wider">
                      5. Gujarat Location Verification
                    </label>
                    <span className="text-xs text-slate-500">
                      Coordinates must fall within Gujarat State (20.1°N - 24.7°N, 68.1°E - 74.5°E)
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={handleUseGPS}
                    className="flex items-center gap-1.5 bg-sky-950/80 hover:bg-sky-900 border border-sky-700/60 text-sky-200 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer"
                  >
                    <span>📍</span> Use Device GPS
                  </button>
                </div>

                {/* Address Search Bar */}
                <div className="relative">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      if (!e.target.value.trim() || e.target.value.trim().length < 3) {
                        setSearchResults([]);
                      }
                    }}
                    placeholder="Search Gujarat city, locality, village or landmark (e.g. Navrangpura, Ahmedabad)..."
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3.5 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                  />
                  {isSearching && (
                    <div className="absolute right-3 top-2.5 text-xs text-slate-400 animate-spin">⌛</div>
                  )}

                  {/* Search Dropdown */}
                  {searchResults.length > 0 && (
                    <div className="absolute top-full left-0 right-0 mt-1 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl z-30 overflow-hidden">
                      {searchResults.map((item, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => handleSelectSearchResult(item)}
                          className="w-full px-3.5 py-2 text-left text-xs text-slate-300 hover:bg-slate-800 hover:text-white border-b border-slate-800/60 last:border-b-0 transition flex items-center gap-2"
                        >
                          <span>📌</span>
                          <span className="truncate">{item.display_name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Coordinate Fields & Verification Badge */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[11px] font-semibold text-slate-400 mb-1">
                      Latitude (°N)
                    </label>
                    <input
                      type="number"
                      step="0.0001"
                      value={latitude}
                      onChange={(e) => {
                        setLatitude(parseFloat(e.target.value) || 0);
                        setLocationSource("MAP_PIN");
                      }}
                      className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-sky-500"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-semibold text-slate-400 mb-1">
                      Longitude (°E)
                    </label>
                    <input
                      type="number"
                      step="0.0001"
                      value={longitude}
                      onChange={(e) => {
                        setLongitude(parseFloat(e.target.value) || 0);
                        setLocationSource("MAP_PIN");
                      }}
                      className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-sky-500"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between text-xs pt-1">
                  <div className="flex items-center gap-2">
                    {validLocation ? (
                      <span className="text-emerald-400 flex items-center gap-1 font-medium">
                        ✓ Inside Gujarat Boundary
                      </span>
                    ) : (
                      <span className="text-red-400 flex items-center gap-1 font-medium">
                        ✕ Coordinates Outside Gujarat
                      </span>
                    )}
                  </div>
                  <span className="text-slate-500 font-mono text-[11px]">
                    Source: {locationSource}
                  </span>
                </div>

                {/* Address Text & Landmark */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                  <div>
                    <input
                      type="text"
                      value={addressText}
                      onChange={(e) => setAddressText(e.target.value)}
                      placeholder="Address / Locality (e.g. Near Usmanpura Underpass)"
                      className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                  <div>
                    <input
                      type="text"
                      value={landmark}
                      onChange={(e) => setLandmark(e.target.value)}
                      placeholder="Landmark (e.g. Opposite Jain Temple)"
                      className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                </div>
              </div>

              {/* Submit Button */}
              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isSubmitting || !validLocation}
                  className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold py-3.5 px-6 rounded-xl text-sm transition shadow-lg shadow-sky-600/30 flex items-center justify-center gap-2 cursor-pointer"
                >
                  {isSubmitting ? (
                    <>
                      <span className="animate-spin text-base">⏳</span>
                      <span>Transmitting Report to SEOC...</span>
                    </>
                  ) : (
                    <>
                      <span>🚨</span>
                      <span>Dispatch Incident Report</span>
                      <span>→</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        )}
      </main>
    </div>
  );
}
