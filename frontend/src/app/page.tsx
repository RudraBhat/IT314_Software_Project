"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { fetchPublicIncidents, fetchPublicAlerts, PublicIncident, PublicAlert } from "../services/citizenApi";
import { LiveOperationsLayer } from "../components/dm/LiveOperationsLayer";
import { signOut } from "./login/actions";
import { NavLink, SiteHeader } from "../components/Brand";
import { GUJARAT_CENTER, GUJARAT_DEFAULT_ZOOM, GUJARAT_DISTRICTS, INDIA_BOUNDS } from "../lib/geo";

interface SessionInfo {
  authenticated: boolean;
  dm: boolean;
  citizen: boolean;
  role: string | null;
  name: string | null;
}

// Two base maps, both OpenStreetMap data. The map keeps its position and zoom when you switch between them.
const TILE_LAYERS = {
  streets: {
    name: "OpenStreetMap",
    base: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    subdomains: [] as string[],
    maxNativeZoom: 19,
  },
  humanitarian: {
    name: "Humanitarian OSM",
    base: "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
    subdomains: ["a", "b"],
    maxNativeZoom: 19,
  },
};
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

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
  const alertsLayerRef = useRef<any>(null);
  // Last map position, so switching the base map keeps where you are zoomed in.
  const viewRef = useRef<{ center: [number, number]; zoom: number } | null>(null);

  const [incidents, setIncidents] = useState<PublicIncident[]>([]);
  const [alerts, setAlerts] = useState<PublicAlert[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectedIncident, setSelectedIncident] = useState<PublicIncident | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [coordsText, setCoordsText] = useState("Gujarat, India");
  const [mapReadyVersion, setMapReadyVersion] = useState(0);
  const [showAlertsLayer, setShowAlertsLayer] = useState(true);
  const [showAlertsDrawer, setShowAlertsDrawer] = useState(false);
  const [showMobileLegend, setShowMobileLegend] = useState(false);
  const [districtFilter, setDistrictFilter] = useState<string>("");
  const [activeBaseLayer, setActiveBaseLayer] = useState<"streets" | "humanitarian">("streets");
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
          minZoom: 4,
          maxZoom: 19,
          // Panning limit: India plus a wide margin. It must be roomy, because a Gujarat-centred view on a wide screen reaches
          // well west of India's edge; a tight limit pushed the opening view east so Gujarat sat on the left. The lowest zoom
          // (fitIndiaZoom below) still shows exactly all of India.
          maxBounds: L.latLngBounds(INDIA_BOUNDS).pad(0.4),
          maxBoundsViscosity: 1.0,
        }).setView(viewRef.current?.center ?? GUJARAT_CENTER, viewRef.current?.zoom ?? GUJARAT_DEFAULT_ZOOM);

        mapRef.current = map;
        // The lowest zoom is the one at which all of India just fits the screen, so it stays centred at any window size.
        const fitIndiaZoom = () => map.setMinZoom(map.getBoundsZoom(INDIA_BOUNDS));
        fitIndiaZoom();
        map.on("resize", fitIndiaZoom);
        map.on("moveend", () => {
          const c = map.getCenter();
          viewRef.current = { center: [c.lat, c.lng], zoom: map.getZoom() };
        });

        const cfg = TILE_LAYERS[activeBaseLayer];
        L.tileLayer(cfg.base, {
          maxZoom: 19,
          maxNativeZoom: cfg.maxNativeZoom,
          // Leaflet's default tile updating while zooming is kept: turning it off (updateWhenZooming) makes zooming look blurrier.
          // detectRetina is not used: it asks OSM for zoom 20 tiles, which do not exist, and blanks the map.
          subdomains: cfg.subdomains,
          attribution: OSM_ATTRIBUTION,
        }).addTo(map);

        const zoomControl = L.control.zoom({ position: "bottomright" }).addTo(map);
        // From the all-India view the middle of the screen is central India, so zooming in there would leave Gujarat
        // stuck on the left. While zoomed out further than the Gujarat view, the + button zooms in towards Gujarat instead.
        zoomControl.getContainer()?.addEventListener(
          "click",
          (event: Event) => {
            const button = (event.target as HTMLElement).closest(".leaflet-control-zoom-in");
            if (!button || button.classList.contains("leaflet-disabled") || map.getZoom() >= GUJARAT_DEFAULT_ZOOM) return;
            event.stopPropagation();
            event.preventDefault();
            map.flyTo(GUJARAT_CENTER, Math.min(map.getZoom() + 1, GUJARAT_DEFAULT_ZOOM), { duration: 0.6 });
          },
          true
        );
        L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

        markersLayerRef.current = L.layerGroup().addTo(map);
        alertsLayerRef.current = L.layerGroup().addTo(map);

        map.on("mousemove", (e: any) => {
          setCoordsText(`${e.latlng.lat.toFixed(4)}°N, ${e.latlng.lng.toFixed(4)}°E`);
        });

        // Click anywhere to see the address down to street level (society, street, locality) from OpenStreetMap.
        // Incident markers handle their own clicks. Nominatim allows about one request per second.
        let lastLookup = 0;
        map.on("click", async (e: any) => {
          if (Date.now() - lastLookup < 1100) return;
          lastLookup = Date.now();
          const box = document.createElement("div");
          box.style.cssText = "max-width:240px;font-size:12px;line-height:1.4;color:#0f172a";
          box.textContent = "Looking up the address…";
          const popup = L.popup().setLatLng(e.latlng).setContent(box).openOn(map);
          try {
            const res = await fetch(
              `https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=18&accept-language=en&lat=${e.latlng.lat.toFixed(6)}&lon=${e.latlng.lng.toFixed(6)}`
            );
            const data = await res.json();
            box.textContent = data?.display_name || "No named place or street is mapped at this spot.";
          } catch {
            box.textContent = "Could not look up this address. Try again in a moment.";
          }
          popup.update();
        });
        setMapReadyVersion((version) => version + 1);
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

  // Zoom to the chosen district's incidents, or back to the overview for "All Gujarat".
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const points = incidents.filter((i) => i.district === districtFilter && i.lat && i.lon).map((i) => [i.lat, i.lon] as [number, number]);
    if (!districtFilter) {
      map.flyTo(GUJARAT_CENTER, GUJARAT_DEFAULT_ZOOM, { duration: 0.8 });
    } else if (points.length) {
      map.flyToBounds(points, { padding: [60, 60], maxZoom: 13, duration: 0.8 });
    }
    // Only when the district choice changes; new incident data should not move the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [districtFilter]);

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
        // Zoom in to street level around the incident so its surroundings and street names are visible.
        map.flyTo([inc.lat, inc.lon], Math.max(map.getZoom(), 16), { duration: 0.8 });
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidents, districtFilter, mapReadyVersion]);

  // 5. Update Public Alerts Layer (SRS Requirement S2-11)
  useEffect(() => {
    const map = mapRef.current;
    const layer = alertsLayerRef.current;
    const L = (window as any).L;

    if (!map || !layer || !L) return;

    layer.clearLayers();

    if (!showAlertsLayer) return;

    alerts.forEach((alert) => {
      let lat = alert.lat;
      let lon = alert.lon;

      if (!lat || !lon) {
        if (alert.description.includes("Saurashtra") || alert.description.includes("Kutch")) {
          lat = 22.3;
          lon = 69.6;
        } else if (alert.description.includes("Ahmedabad") || alert.description.includes("Gandhinagar")) {
          lat = 23.0225;
          lon = 72.5714;
        } else if (alert.description.includes("Bharuch") || alert.description.includes("Dahej")) {
          lat = 21.71;
          lon = 72.98;
        } else {
          return;
        }
      }

      const isCrit = alert.severity === "CRITICAL";
      const bg = isCrit ? "#dc2626" : alert.severity === "HIGH" ? "#ea580c" : "#eab308";

      const icon = L.divIcon({
        className: "custom-alert-pin",
        html: `
          <div style="position: relative; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; cursor: pointer;">
            <span style="position: absolute; width: 100%; height: 100%; border-radius: 50%; background: ${bg}; opacity: 0.4; animation: ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;"></span>
            <div style="background-color: ${bg}; width: 28px; height: 28px; border-radius: 8px; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; font-size: 13px; color: white;">
              ⚠️
            </div>
          </div>
        `,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      });

      const marker = L.marker([lat, lon], { icon }).addTo(layer);

      const popup = document.createElement("div");
      popup.style.cssText = "color: #0f172a; font-family: sans-serif; font-size: 12px; min-width: 220px; padding: 4px;";

      const header = document.createElement("div");
      header.style.cssText = "display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px;";

      const severity = document.createElement("strong");
      severity.textContent = `${alert.severity} ALERT`;
      severity.style.cssText = `color: ${bg}; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px;`;
      header.appendChild(severity);

      const badge = document.createElement("span");
      badge.textContent = alert.is_fallback ? "SAMPLE DATA" : "OFFICIAL";
      badge.style.cssText = alert.is_fallback
        ? "background: #fef3c7; color: #92400e; font-size: 9px; font-weight: bold; padding: 2px 6px; border-radius: 4px; border: 1px solid #fde68a;"
        : "background: #dbeafe; color: #1e40af; font-size: 9px; font-weight: bold; padding: 2px 6px; border-radius: 4px;";
      header.appendChild(badge);
      popup.appendChild(header);

      const title = document.createElement("div");
      title.textContent = alert.title;
      title.style.cssText = "font-weight: 700; font-size: 13px; margin-bottom: 4px; color: #0f172a;";
      popup.appendChild(title);

      const description = document.createElement("div");
      description.textContent = alert.description;
      description.style.cssText = "color: #475569; margin-bottom: 6px; line-height: 1.4;";
      popup.appendChild(description);

      const source = document.createElement("div");
      source.textContent = `Source: ${alert.source}`;
      source.style.cssText = "font-size: 10px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 4px;";
      popup.appendChild(source);

      marker.bindPopup(popup);
    });
  }, [alerts, showAlertsLayer, mapReadyVersion]);

  return (
    <div className="app-screen relative bg-slate-900 font-sans flex flex-col">
      {/* Top Header */}
      <SiteHeader subtitle="Gujarat Emergency Portal · NDMA" maxWidth="max-w-none">
        <button
          onClick={() => setShowAlertsDrawer(!showAlertsDrawer)}
          className="relative inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-sky-700/60 bg-sky-950/80 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-sky-900"
        >
          <span aria-hidden>🔔</span>
          <span className="hidden sm:inline">Active Alerts</span>
          {alerts.length > 0 && (
            <span className="rounded-full bg-red-600 px-1.5 text-[10px] font-bold">{alerts.length}</span>
          )}
        </button>
        <NavLink href="/report" variant="primary">Report<span className="hidden sm:inline"> Incident</span></NavLink>
        <NavLink href="/my-reports" hideBelow="lg">My Reports</NavLink>
        <NavLink href="/about" hideBelow="lg">About</NavLink>
        <NavLink href="/how-to" hideBelow="lg">How to use</NavLink>
        <NavLink href="/safety" hideBelow="lg">Safety</NavLink>
        <NavLink href="/donate" hideBelow="lg" variant="success">Donate</NavLink>
        {session?.authenticated ? (
          <div className="hidden items-center gap-2 border-l border-sky-800 pl-2 sm:flex">
            <Link
              href={session.dm ? "/dm" : "/citizen/dashboard"}
              className="max-w-[120px] truncate text-xs font-semibold text-sky-200 underline hover:text-white"
            >
              {session.name || "My Account"}
            </Link>
            <button
              onClick={async () => {
                await signOut();
              }}
              className="rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-white/20"
            >
              Sign Out
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-bold text-slate-950 transition hover:bg-sky-400"
          >
            Sign In
          </Link>
        )}
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="rounded-lg bg-white/10 px-2.5 py-1.5 text-sm text-white hover:bg-white/20 lg:hidden"
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
        >
          {menuOpen ? "✕" : "☰"}
        </button>
      </SiteHeader>
      {menuOpen && (
        <nav className="absolute inset-x-0 top-14 z-[1000] flex flex-col gap-1 border-b border-[#093554] bg-[#0c4a75] p-3 text-sm text-white shadow-xl lg:hidden" aria-label="Menu">
          {[
            ["/my-reports", "My Reports"],
            ["/about", "About"],
            ["/how-to", "How to use"],
            ["/safety", "Safety"],
            ["/donate", "Donate"],
          ].map(([href, label]) => (
            <Link key={href} href={href} className="rounded-lg px-3 py-2 font-semibold hover:bg-white/10" onClick={() => setMenuOpen(false)}>
              {label}
            </Link>
          ))}
          {session?.authenticated && (
            <button onClick={async () => { await signOut(); }} className="rounded-lg px-3 py-2 text-left font-semibold hover:bg-white/10">
              Sign Out
            </button>
          )}
        </nav>
      )}

      {/* Main Map View */}
      <div className="relative flex-1 w-full h-full">
        <div ref={mapContainerRef} className="absolute inset-0 z-0 bg-slate-950" />

        {/* DM Operations Layer (only activates if session.dm === true) */}
        {session?.dm && <LiveOperationsLayer mapRef={mapRef} />}

        {/* Top Controls Container (Unified Flex Layout to Prevent Any Overlap) */}
        <div className="absolute top-2 left-2 right-2 sm:top-3 sm:left-3 sm:right-3 z-[500] flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 pointer-events-none">
          {/* Status Banner */}
          <div className="bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl px-2.5 py-1.5 sm:px-3 sm:py-2 text-white shadow-xl max-w-sm pointer-events-auto">
            <div className="flex items-center gap-2 text-xs">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
              <span className="font-bold text-sky-300">Live Public Disaster Map</span>
            </div>
            <div className="text-[10px] sm:text-[11px] text-slate-400 mt-0.5">
              <span className="font-semibold text-slate-200">{visibleIncidents.length}</span> verified public incidents
              <span className="hidden sm:inline"> displayed · Auto-refreshes every 30s</span>
            </div>
            {error && (
              <div className="mt-1.5 text-[10px] sm:text-[11px] text-red-300 bg-red-950/80 px-2 py-1 rounded border border-red-800">
                ⚠️ {error}
              </div>
            )}
          </div>

          {/* Layer Controls: Basemap & Alerts Layer Toggle */}
          <div className="flex flex-wrap items-center gap-1.5 sm:gap-2 pointer-events-auto self-start sm:self-auto">
            <button
              onClick={() => setShowAlertsLayer(!showAlertsLayer)}
              className={`px-2.5 sm:px-3 py-1 sm:py-1.5 rounded-xl text-xs font-semibold shadow-xl border transition flex items-center gap-1.5 ${
                showAlertsLayer
                  ? "bg-amber-600 text-white border-amber-400 shadow-amber-900/40"
                  : "bg-slate-900/90 text-slate-400 border-slate-700 hover:text-white"
              }`}
              title="Toggle Early Warning Alerts map layer (SRS S2-11)"
            >
              <span>⚠️</span>
              <span>Alerts: {showAlertsLayer ? "ON" : "OFF"}</span>
            </button>

            <div className="bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl p-0.5 sm:p-1 text-xs text-white shadow-xl flex gap-1">
              <button
                onClick={() => setActiveBaseLayer("streets")}
                className={`px-2 sm:px-2.5 py-1 rounded-lg text-xs font-medium transition ${
                  activeBaseLayer === "streets" ? "bg-sky-600 text-white font-bold" : "text-slate-400 hover:text-white"
                }`}
              >
                Streets
              </button>
              <button
                onClick={() => setActiveBaseLayer("humanitarian")}
                className={`px-2 sm:px-2.5 py-1 rounded-lg text-xs font-medium transition ${
                  activeBaseLayer === "humanitarian" ? "bg-sky-600 text-white font-bold" : "text-slate-400 hover:text-white"
                }`}
              >
                Humanitarian
              </button>
            </div>
          </div>
        </div>

        {/* Coordinates indicator (desktop only to prevent mobile overlap) */}
        <div className="hidden sm:block absolute bottom-3 left-14 z-[500] bg-slate-900/80 backdrop-blur px-2.5 py-1 rounded-md border border-slate-700/80 text-[10px] text-slate-300 font-mono shadow pointer-events-none">
          {coordsText}
        </div>

        {/* District filter + legend */}
        <div className="absolute bottom-12 left-2 sm:left-3 z-[500] pointer-events-auto">
          {/* Mobile toggle button */}
          <button
            type="button"
            onClick={() => setShowMobileLegend((prev) => !prev)}
            className="sm:hidden px-2.5 py-1.5 rounded-lg bg-slate-900/90 backdrop-blur border border-slate-700 text-xs font-semibold text-white shadow-xl flex items-center gap-1.5 mb-1.5"
            aria-expanded={showMobileLegend}
            aria-label="Toggle map filters and legend"
          >
            <span>📊</span>
            <span>{showMobileLegend ? "Hide Filters" : "Filters & Legend"}</span>
            {districtFilter && (
              <span className="px-1.5 py-0.5 rounded bg-sky-600 text-[10px] font-bold">
                {districtFilter}
              </span>
            )}
          </button>

          <div
            className={`${
              showMobileLegend ? "block" : "hidden"
            } sm:block bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl p-3 text-white shadow-xl w-48 max-h-[50vh] overflow-y-auto`}
          >
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
                  <span className="w-3 h-3 rounded-full border border-white shrink-0" style={{ backgroundColor: SEVERITY_COLORS[k] }} />
                  {k.charAt(0) + k.slice(1).toLowerCase()}
                </li>
              ))}
            </ul>

            <div className="mt-3 pt-2 border-t border-slate-800">
              <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400 mb-1">Layers</div>
              <div className="flex items-center gap-2 text-[11px] text-amber-300">
                <span className="w-4 h-4 rounded bg-amber-600 border border-white flex items-center justify-center text-[10px] leading-none shrink-0">
                  ⚠️
                </span>
                <span>Early Warnings {showAlertsLayer ? "(On)" : "(Off)"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Selected Incident Detail Card (Public Contract Only) */}
        {selectedIncident && (
          <div className="absolute bottom-3 inset-x-2 sm:inset-x-auto sm:bottom-6 sm:right-6 z-[600] w-auto sm:w-80 md:w-96 max-w-[calc(100vw-16px)] bg-slate-900/95 backdrop-blur-md border border-slate-700 rounded-2xl shadow-2xl p-4 sm:p-5 text-white pointer-events-auto animate-in fade-in slide-in-from-bottom-4 duration-200 max-h-[80vh] overflow-y-auto">
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
          <div className="absolute top-0 right-0 z-[700] w-full sm:w-80 md:w-96 h-full bg-slate-900/95 backdrop-blur-md border-l border-slate-700 shadow-2xl p-4 sm:p-5 text-white flex flex-col pointer-events-auto">
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
