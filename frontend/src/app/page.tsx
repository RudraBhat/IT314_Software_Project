"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { fetchPublicIncidents, fetchPublicAlerts, PublicIncident, PublicAlert } from "../services/citizenApi";
import { LiveOperationsLayer } from "../components/dm/LiveOperationsLayer";
import { signOut } from "./login/actions";
import { GUJARAT_BOUNDS, GUJARAT_CENTER, GUJARAT_DEFAULT_ZOOM, GUJARAT_DISTRICTS } from "../lib/geo";

interface SessionInfo {
  authenticated: boolean;
  dm: boolean;
  citizen: boolean;
  role: string | null;
  name: string | null;
}

const TILE_LAYERS = {
  streets: {
    name: "OpenStreetMap",
    base: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    subdomains: [],
    maxZoom: 19,
  },
  humanitarian: {
    name: "Humanitarian OSM",
    base: "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
    subdomains: ["a", "b"],
    maxZoom: 19,
  },
};

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "#ef4444",
  HIGH: "#f97316",
  MEDIUM: "#eab308",
  MODERATE: "#eab308",
  LOW: "#22c55e",
  UNASSIGNED: "#94a3b8",
};

export default function PublicPortalPage() {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const markersLayerRef = useRef<any>(null);

  const [incidents, setIncidents] = useState<PublicIncident[]>([]);
  const [alerts, setAlerts] = useState<PublicAlert[]>([]);
  const [selectedIncident, setSelectedIncident] = useState<PublicIncident | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [coordsText, setCoordsText] = useState("Gujarat, India");
  const [activeBaseLayer, setActiveBaseLayer] = useState<"streets" | "humanitarian">("streets");
  const [showAlertsDrawer, setShowAlertsDrawer] = useState(false);
  const [districtFilter, setDistrictFilter] = useState<string>("");
  const visibleIncidents = districtFilter ? incidents.filter((i) => i.district === districtFilter) : incidents;

  // 1. Fetch user session
  const checkSession = useCallback(async () => {
    try {
      const res = await fetch("/api/session", { cache: "no-store" });
      if (res.ok) {
        const data: SessionInfo = await res.json();
        setSession(data);
      }
    } catch {
      setSession({ authenticated: false, dm: false, citizen: false, role: null, name: null });
    }
  }, []);

  // 2. Fetch public data
  const loadData = useCallback(async () => {
    try {
      const [incRes, alertRes] = await Promise.all([
        fetchPublicIncidents(),
        fetchPublicAlerts(),
      ]);

      if (incRes.data) {
        setIncidents(incRes.data);
      } else if (incRes.error) {
        setError(incRes.error);
      }

      if (alertRes.data) {
        setAlerts(alertRes.data);
      }
    } catch {
      setError("Failed to load public disaster data.");
    }
  }, []);

  useEffect(() => {
    let isCancelled = false;
    const init = async () => {
      await checkSession();
      if (!isCancelled) {
        await loadData();
      }
    };
    init();
    const interval = setInterval(loadData, 30000);
    return () => {
      isCancelled = true;
      clearInterval(interval);
    };
  }, [checkSession, loadData]);

  // 3. Initialize Leaflet Map
  useEffect(() => {
    let isCancelled = false;

    const initMap = async () => {
      try {
        const L = (await import("leaflet")).default;
        (window as any).L = L;

        if (isCancelled || !mapContainerRef.current) return;

        if (mapRef.current) {
          mapRef.current.remove();
          mapRef.current = null;
        }

        const map = L.map(mapContainerRef.current, {
          zoomControl: false,
          attributionControl: true,
          minZoom: 6,
          maxZoom: 18,
          maxBounds: GUJARAT_BOUNDS,
          maxBoundsViscosity: 1.0,
        }).setView(GUJARAT_CENTER, GUJARAT_DEFAULT_ZOOM);

        mapRef.current = map;

        const cfg = TILE_LAYERS[activeBaseLayer];
        L.tileLayer(cfg.base, {
          maxZoom: cfg.maxZoom,
          subdomains: cfg.subdomains,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }).addTo(map);

        L.control.zoom({ position: "bottomright" }).addTo(map);
        L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

        markersLayerRef.current = L.layerGroup().addTo(map);

        map.on("mousemove", (e: any) => {
          setCoordsText(`${e.latlng.lat.toFixed(4)}°N, ${e.latlng.lng.toFixed(4)}°E`);
        });
      } catch (err) {
        console.error("Map initialization failed", err);
      }
    };

    initMap();

    return () => {
      isCancelled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [activeBaseLayer]);

  // 4. Update Incident Markers
  useEffect(() => {
    const map = mapRef.current;
    const layer = markersLayerRef.current;
    const L = (window as any).L;

    if (!map || !layer || !L) return;

    layer.clearLayers();

    visibleIncidents.forEach((inc) => {
      if (!inc.lat || !inc.lon) return;

      const color = SEVERITY_COLORS[inc.severity] ?? "#94a3b8";

      const icon = L.divIcon({
        className: "custom-incident-pin",
        html: `
          <div style="background-color: ${color}; width: 26px; height: 26px; border-radius: 50%; border: 2.5px solid white; box-shadow: 0 2px 6px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; color: white; font-size: 11px; font-weight: bold;">
            !
          </div>
        `,
        iconSize: [26, 26],
        iconAnchor: [13, 13],
      });

      const marker = L.marker([inc.lat, inc.lon], { icon }).addTo(layer);

      marker.on("click", () => {
        setSelectedIncident(inc);
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidents, districtFilter]);

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-slate-900 font-sans flex flex-col">
      {/* Top Header */}
      <header className="z-[1000] h-16 bg-[#0c4a75]/95 backdrop-blur-md border-b border-[#093554] px-4 md:px-6 flex items-center justify-between shadow-lg shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-sky-400/20 border border-white flex items-center justify-center text-xl shadow-inner">
            🛡️
          </div>
          <div>
            <div className="flex items-baseline gap-1.5 leading-tight">
              <span className="text-xl font-black text-white tracking-tight">ResQ</span>
              <span className="text-xs font-medium text-sky-200">Gujarat Emergency Portal</span>
            </div>
            <div className="text-[10px] text-sky-200/80">Disaster Response Coordination Hub · NDMA</div>
          </div>
        </div>

        {/* Action Controls & Navigation */}
        <div className="flex items-center gap-2.5">
          {/* Alerts button */}
          <button
            onClick={() => setShowAlertsDrawer(!showAlertsDrawer)}
            className="relative px-3 py-1.5 rounded-lg bg-sky-950/80 hover:bg-sky-900 border border-sky-700/60 text-white text-xs font-semibold flex items-center gap-1.5 transition"
          >
            <span>🔔</span>
            <span className="hidden sm:inline">Active Alerts</span>
            {alerts.length > 0 && (
              <span className="ml-1 px-1.5 py-0.2 bg-red-600 text-white text-[10px] rounded-full font-bold">
                {alerts.length}
              </span>
            )}
          </button>

          {/* Quick links */}
          <Link
            href="/report"
            className="px-3.5 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-bold flex items-center gap-1.5 shadow-md transition"
          >
            <span>🚨</span>
            <span>Report Incident</span>
          </Link>

          <Link
            href="/my-reports"
            className="hidden sm:flex px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white text-xs font-semibold items-center gap-1.5 transition"
          >
            <span>📋</span>
            <span>My Reports</span>
          </Link>

          <Link
            href="/about"
            className="hidden md:flex px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white text-xs font-semibold items-center gap-1.5 transition"
          >
            <span>ℹ️</span>
            <span>About</span>
          </Link>

          <Link
            href="/how-to"
            className="hidden md:flex px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white text-xs font-semibold items-center gap-1.5 transition"
          >
            <span>❓</span>
            <span>How to use</span>
          </Link>

          <Link
            href="/safety"
            className="hidden md:flex px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white text-xs font-semibold items-center gap-1.5 transition"
          >
            <span>🛟</span>
            <span>Safety</span>
          </Link>

          <Link
            href="/donate"
            className="hidden sm:flex px-3 py-1.5 rounded-lg bg-emerald-600/90 hover:bg-emerald-500 text-white text-xs font-semibold items-center gap-1.5 transition"
          >
            <span>🤝</span>
            <span>Donate</span>
          </Link>

          {/* User / Auth status */}
          {session?.authenticated ? (
            <div className="flex items-center gap-2 pl-2 border-l border-sky-800">
              <Link
                href={session.dm ? "/dm" : "/citizen/dashboard"}
                className="text-xs font-semibold text-sky-200 hover:text-white underline truncate max-w-[120px]"
              >
                {session.name || "My Account"}
              </Link>
              <button
                onClick={async () => {
                  await signOut();
                }}
                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition"
              >
                Sign Out
              </button>
            </div>
          ) : (
            <Link
              href="/login"
              className="px-3.5 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs font-bold flex items-center gap-1.5 shadow-md transition"
            >
              <span>🔐</span>
              <span>Sign In</span>
            </Link>
          )}
        </div>
      </header>

      {/* Main Map View */}
      <div className="relative flex-1 w-full h-full">
        <div ref={mapContainerRef} className="absolute inset-0 z-0 bg-slate-950" />

        {/* DM Operations Layer (only activates if session.dm === true) */}
        {session?.dm && <LiveOperationsLayer mapRef={mapRef} />}

        {/* Map Header Status Banner */}
        <div className="absolute top-3 left-3 z-[500] bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl px-3 py-2 text-white shadow-xl max-w-sm pointer-events-auto">
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-bold text-sky-300">Live Public Disaster Map</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">
            {visibleIncidents.length} verified public incidents displayed · Auto-refreshes every 30s
          </div>
          {error && (
            <div className="mt-1.5 text-[11px] text-red-300 bg-red-950/80 px-2 py-1 rounded border border-red-800">
              ⚠️ {error}
            </div>
          )}
        </div>

        {/* Coordinates indicator */}
        <div className="absolute bottom-3 left-14 z-[500] bg-slate-900/80 backdrop-blur px-2.5 py-1 rounded-md border border-slate-700/80 text-[10px] text-slate-300 font-mono shadow pointer-events-none">
          {coordsText}
        </div>


        {/* District filter + legend */}
        <div className="absolute bottom-12 left-3 z-[500] bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl p-3 text-white shadow-xl pointer-events-auto w-48">
          <label htmlFor="district-filter" className="block text-[10px] font-bold uppercase tracking-wide text-slate-400 mb-1">
            District
          </label>
          <select
            id="district-filter"
            value={districtFilter}
            onChange={(e) => setDistrictFilter(e.target.value)}
            className="w-full rounded-md bg-slate-800 border border-slate-600 text-xs px-2 py-1 mb-3"
          >
            <option value="">All Gujarat</option>
            {GUJARAT_DISTRICTS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400 mb-1">Priority</div>
          <ul className="space-y-1">
            {(["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNASSIGNED"] as const).map((k) => (
              <li key={k} className="flex items-center gap-2 text-[11px]">
                <span className="w-3 h-3 rounded-full border border-white" style={{ backgroundColor: SEVERITY_COLORS[k] }} />
                {k.charAt(0) + k.slice(1).toLowerCase()}
              </li>
            ))}
          </ul>
        </div>

        {/* Basemap switcher */}
        <div className="absolute top-3 right-3 z-[500] bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl p-1 text-xs text-white shadow-xl flex gap-1 pointer-events-auto">
          <button
            onClick={() => setActiveBaseLayer("streets")}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium transition ${
              activeBaseLayer === "streets" ? "bg-sky-600 text-white font-bold" : "text-slate-400 hover:text-white"
            }`}
          >
            Streets
          </button>
          <button
            onClick={() => setActiveBaseLayer("humanitarian")}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium transition ${
              activeBaseLayer === "humanitarian" ? "bg-sky-600 text-white font-bold" : "text-slate-400 hover:text-white"
            }`}
          >
            Humanitarian
          </button>
        </div>

        {/* Selected Incident Detail Card (Public Contract Only) */}
        {selectedIncident && (
          <div className="absolute bottom-6 right-6 z-[600] w-80 md:w-96 bg-slate-900/95 backdrop-blur-md border border-slate-700 rounded-2xl shadow-2xl p-5 text-white pointer-events-auto animate-in fade-in slide-in-from-bottom-4 duration-200">
            <div className="flex items-start justify-between">
              <div>
                <span
                  className="inline-block px-2 py-0.5 rounded text-[10px] font-extrabold tracking-wider uppercase mb-1"
                  style={{
                    backgroundColor: `${SEVERITY_COLORS[selectedIncident.severity] ?? "#94a3b8"}25`,
                    color: SEVERITY_COLORS[selectedIncident.severity] ?? "#94a3b8",
                    border: `1px solid ${SEVERITY_COLORS[selectedIncident.severity] ?? "#94a3b8"}`,
                  }}
                >
                  {selectedIncident.severity}
                </span>
                <h3 className="text-base font-bold text-white leading-snug">{selectedIncident.title}</h3>
                <p className="text-xs text-slate-400 mt-0.5">Ref: {selectedIncident.id}</p>
              </div>
              <button
                onClick={() => setSelectedIncident(null)}
                className="text-slate-400 hover:text-white text-lg p-1"
                aria-label="Close details"
              >
                ✕
              </button>
            </div>

            <div className="mt-4 space-y-2 text-xs border-t border-slate-800 pt-3">
              <div className="flex justify-between">
                <span className="text-slate-400">Scenario:</span>
                <span className="font-semibold text-slate-200 capitalize">{selectedIncident.scenario.replace(/_/g, " ")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">District:</span>
                <span className="font-semibold text-slate-200">{selectedIncident.district ?? "Gujarat"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Lifecycle Status:</span>
                <span className="font-semibold text-sky-400">{selectedIncident.lifecycle_status}</span>
              </div>
              {selectedIncident.detected_at && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Verified At:</span>
                  <span className="font-semibold text-slate-300">
                    {new Date(selectedIncident.detected_at).toLocaleString()}
                  </span>
                </div>
              )}
            </div>

            <div className="mt-4 pt-3 border-t border-slate-800 flex gap-2">
              <Link
                href="/report"
                className="flex-1 text-center py-2 bg-red-600 hover:bg-red-500 rounded-lg text-xs font-bold text-white transition"
              >
                Report Related Incident
              </Link>
            </div>
          </div>
        )}

        {/* Public Alerts Drawer */}
        {showAlertsDrawer && (
          <div className="absolute top-0 right-0 z-[700] w-80 md:w-96 h-full bg-slate-900/95 backdrop-blur-md border-l border-slate-700 shadow-2xl p-5 text-white flex flex-col pointer-events-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <span className="text-lg">🔔</span>
                <h2 className="text-sm font-bold text-white">Active Public Alerts</h2>
              </div>
              <button
                onClick={() => setShowAlertsDrawer(false)}
                className="text-slate-400 hover:text-white p-1"
                aria-label="Close drawer"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto mt-3 space-y-3">
              {alerts.length === 0 ? (
                <div className="text-xs text-slate-400 text-center py-8">
                  No active public alerts for Gujarat at this time.
                </div>
              ) : (
                alerts.map((alert) => (
                  <div
                    key={alert.id}
                    className="p-3 bg-slate-800/80 border border-slate-700 rounded-xl space-y-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold text-red-400 uppercase tracking-wide">
                        {alert.severity}
                      </span>
                      {alert.is_fallback && (
                        <span className="px-1.5 py-0.5 bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded text-[9px] font-semibold">
                          Sample alert
                        </span>
                      )}
                    </div>
                    <h4 className="text-xs font-bold text-white">{alert.title}</h4>
                    {alert.description && (
                      <p className="text-[11px] text-slate-300 leading-relaxed">{alert.description}</p>
                    )}
                    <div className="text-[10px] text-slate-500 flex justify-between pt-1 border-t border-slate-700/50">
                      <span>Source: {alert.source}</span>
                      {alert.timestamp && <span>{new Date(alert.timestamp).toLocaleTimeString()}</span>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
