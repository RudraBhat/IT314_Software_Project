"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { fetchPublicIncidents, fetchPublicAlerts, PublicIncident, PublicAlert } from "@/services/citizenApi";
import { LiveOperationsLayer } from "@/components/dm/LiveOperationsLayer";
import { useSession } from "@/components/auth/SessionProvider";
import { GUJARAT_CENTER, GUJARAT_DEFAULT_ZOOM, GUJARAT_DISTRICTS, INDIA_BOUNDS } from "@/lib/geo";
import { SCENARIO_ICON, hazardIcon } from "@/lib/format";

// Last public data this browser tab loaded. Coming back to the map shows it on the first frame while a
// fresh copy loads in the background (stale-while-revalidate). Public data only; nothing personal.
let publicDataCache: { incidents: PublicIncident[]; alerts: PublicAlert[] } | null = null;

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

type BaseLayer = keyof typeof TILE_LAYERS;

/** Severity colour of an official alert. */
function alertColor(severity: string): string {
  return severity === "CRITICAL" || severity === "EXTREME" ? "#dc2626" : severity === "HIGH" || severity === "SEVERE" ? "#ea580c" : "#ca8a04";
}

/**
 * Map marker showing the disaster itself (cyclone, flood, fire...) rather than a generic warning sign.
 * Incidents are round; official early-warning alerts are rounded squares with a pulse. On the
 * Humanitarian (HOT) base map the marker turns flat and white-filled so it reads like the map's own symbols.
 */
function hazardMarkerHtml(icon: string, color: string, baseLayer: BaseLayer, kind: "incident" | "alert"): string {
  const radius = kind === "incident" ? "50%" : "9px";
  const humanitarian = baseLayer === "humanitarian";
  const fill = humanitarian ? "#ffffff" : color;
  const ring = humanitarian ? `3px solid ${color}` : "2.5px solid #ffffff";
  const pulse =
    kind === "alert" && !humanitarian
      ? `<span style="position:absolute;inset:0;border-radius:${radius};background:${color};opacity:.35;animation:ping 1.6s cubic-bezier(0,0,.2,1) infinite;"></span>`
      : "";
  return `
    <div style="position:relative;width:34px;height:34px;display:flex;align-items:center;justify-content:center;cursor:pointer;">
      ${pulse}
      <div style="position:relative;width:30px;height:30px;border-radius:${radius};background:${fill};border:${ring};box-shadow:0 2px 6px rgba(15,23,42,.45);display:flex;align-items:center;justify-content:center;font-size:16px;line-height:1;">
        ${icon}
      </div>
    </div>
  `;
}

/**
 * The live public disaster map: incidents, early-warning alerts, district filter and legend. It fills its
 * parent (which must be positioned and sized). Used by the public home page and, inside the Disaster
 * Management workspace, by /dm/live-map, where the operations layer is drawn on top.
 */
export function PublicMap() {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const markersLayerRef = useRef<any>(null);
  const alertsLayerRef = useRef<any>(null);
  const tileLayerRef = useRef<any>(null);
  // Last map position, so switching the base map keeps where you are zoomed in.
  const viewRef = useRef<{ center: [number, number]; zoom: number } | null>(null);

  const [incidents, setIncidents] = useState<PublicIncident[]>(() => publicDataCache?.incidents ?? []);
  const [alerts, setAlerts] = useState<PublicAlert[]>(() => publicDataCache?.alerts ?? []);
  // True only until the first answer when nothing is cached; later refreshes stay silent.
  const [loadingIncidents, setLoadingIncidents] = useState(() => publicDataCache === null);
  const [selectedIncident, setSelectedIncident] = useState<PublicIncident | null>(null);
  const { session } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [coordsText, setCoordsText] = useState("Gujarat, India");
  const [mapReadyVersion, setMapReadyVersion] = useState(0);
  const [showAlertsLayer, setShowAlertsLayer] = useState(true);
  // Disaster Management staff switch between the public map and the live operations map; the two overlap,
  // so only one is drawn at a time. Everyone else only has the public map.
  const isDm = !!session?.dm;
  const [view, setView] = useState<"public" | "operations">("operations");
  const showPublic = !isDm || view === "public";
  const [showAlertsDrawer, setShowAlertsDrawer] = useState(false);
  const [showMobileLegend, setShowMobileLegend] = useState(false);
  const [districtFilter, setDistrictFilter] = useState<string>("");
  const [activeBaseLayer, setActiveBaseLayer] = useState<BaseLayer>("streets");
  const visibleIncidents = districtFilter ? incidents.filter((i) => i.district === districtFilter) : incidents;

  // Public map data. It does not wait for the session check: the two load in parallel.
  const loadData = useCallback(async () => {
    try {
      const [incRes, alertRes] = await Promise.all([
        fetchPublicIncidents(),
        fetchPublicAlerts(),
      ]);

      if (incRes.data) {
        setIncidents(incRes.data);
        setError(null);
      } else if (incRes.error) {
        setError(incRes.error);
      }

      if (alertRes.data) {
        setAlerts(alertRes.data);
      }
      if (incRes.data) {
        publicDataCache = { incidents: incRes.data, alerts: alertRes.data ?? publicDataCache?.alerts ?? [] };
      }
    } catch {
      setError("Failed to load public disaster data.");
    } finally {
      setLoadingIncidents(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loadData() only sets state after the requests resolve
    void loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

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
      tileLayerRef.current = null;
    };
  }, []);

  // Base map: swap only the tile layer, so markers, popups, position and zoom all stay as they are.
  useEffect(() => {
    const map = mapRef.current;
    const L = (window as any).L;
    if (!map || !L) return;
    if (tileLayerRef.current) map.removeLayer(tileLayerRef.current);
    const cfg = TILE_LAYERS[activeBaseLayer];
    tileLayerRef.current = L.tileLayer(cfg.base, {
      maxZoom: 19,
      maxNativeZoom: cfg.maxNativeZoom,
      // Leaflet's default tile updating while zooming is kept: turning it off (updateWhenZooming) makes zooming look blurrier.
      // detectRetina is not used: it asks OSM for zoom 20 tiles, which do not exist, and blanks the map.
      subdomains: cfg.subdomains,
      attribution: OSM_ATTRIBUTION,
    }).addTo(map);
    tileLayerRef.current.bringToBack();
  }, [activeBaseLayer, mapReadyVersion]);

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
    if (!showPublic) return;

    visibleIncidents.forEach((inc) => {
      if (!inc.lat || !inc.lon) return;

      const color = SEVERITY_COLORS[inc.severity] ?? "#94a3b8";

      const icon = L.divIcon({
        className: "custom-incident-pin",
        html: hazardMarkerHtml(SCENARIO_ICON[inc.scenario] ?? "⚠️", color, activeBaseLayer, "incident"),
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      });

      const marker = L.marker([inc.lat, inc.lon], { icon }).addTo(layer);

      marker.on("click", () => {
        setSelectedIncident(inc);
        // Zoom in to street level around the incident so its surroundings and street names are visible.
        map.flyTo([inc.lat, inc.lon], Math.max(map.getZoom(), 16), { duration: 0.8 });
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidents, districtFilter, mapReadyVersion, activeBaseLayer, showPublic]);

  // 5. Update Public Alerts Layer (SRS Requirement S2-11)
  useEffect(() => {
    const map = mapRef.current;
    const layer = alertsLayerRef.current;
    const L = (window as any).L;

    if (!map || !layer || !L) return;

    layer.clearLayers();

    if (!showAlertsLayer || !showPublic) return;

    alerts.forEach((alert) => {
      // Only alerts the feed placed are drawn; the rest are listed under "Active alerts" (no guessed positions).
      const lat = alert.lat;
      const lon = alert.lon;
      if (lat == null || lon == null) return;

      const bg = alertColor(alert.severity);

      const icon = L.divIcon({
        className: "custom-alert-pin",
        html: hazardMarkerHtml(hazardIcon(alert.type), bg, activeBaseLayer, "alert"),
        iconSize: [34, 34],
        iconAnchor: [17, 17],
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
  }, [alerts, showAlertsLayer, mapReadyVersion, activeBaseLayer, showPublic]);

  const unplacedAlerts = alerts.filter((a) => a.lat == null || a.lon == null).length;
  // Light, solid panels so text stays readable over any part of either base map.
  const panel = "rounded-xl border border-slate-200 bg-white/95 text-slate-800 shadow-lg backdrop-blur";

  return (
    <div className="relative h-full w-full bg-slate-100 font-sans">
      <div ref={mapContainerRef} className="absolute inset-0 z-0 bg-slate-200" />

      {/* Top bar: map status on the left, map controls on the right */}
      <div className="pointer-events-none absolute left-2 right-2 top-2 z-[500] flex flex-col gap-2 sm:left-3 sm:right-3 sm:top-3 sm:flex-row sm:items-start sm:justify-between">
        {/* In the operations view the operations summary takes this spot. */}
        <div className={`${panel} pointer-events-auto w-fit max-w-sm px-3 py-2 ${showPublic ? "" : "invisible"}`}>
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <span className="size-2.5 shrink-0 animate-pulse rounded-full bg-emerald-500" aria-hidden />
            Live disaster map
          </div>
          <p className="mt-0.5 text-xs text-slate-600">
            <span className="font-semibold text-slate-900">{visibleIncidents.length}</span> verified incident
            {visibleIncidents.length === 1 ? "" : "s"}
            {districtFilter ? ` in ${districtFilter}` : " in Gujarat"}
            <span className="hidden sm:inline"> · updates every 30s</span>
          </p>
          {loadingIncidents && (
            <p role="status" className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-semibold text-sky-700">
              <span className="size-3 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" aria-hidden />
              Loading incidents…
            </p>
          )}
          {error && (
            <p role="alert" className="mt-1.5 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs font-medium text-red-700">
              {error}
            </p>
          )}
        </div>

        <div className="pointer-events-auto flex flex-wrap items-center gap-2 self-start sm:self-auto">
          {/* Alert controls come first so the view switch and base map keep their place when they appear. */}
          {showPublic && (
          <>
          <button
            onClick={() => setShowAlertsDrawer(!showAlertsDrawer)}
            aria-expanded={showAlertsDrawer}
            className={`${panel} flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition hover:bg-white`}
          >
            <span aria-hidden>🔔</span>
            Active alerts
            {alerts.length > 0 && <span className="rounded-full bg-red-600 px-1.5 text-[11px] font-bold text-white">{alerts.length}</span>}
          </button>
          <button
            onClick={() => setShowAlertsLayer(!showAlertsLayer)}
            aria-pressed={showAlertsLayer}
            className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold shadow-lg transition ${
              showAlertsLayer ? "border-amber-500 bg-amber-500 text-white" : `${panel} text-slate-600 hover:bg-white`
            }`}
            title="Show or hide official early-warning alerts on the map"
          >
            Alerts on map: {showAlertsLayer ? "On" : "Off"}
          </button>
          </>
          )}
          {isDm && (
            <div className={`${panel} flex gap-1 p-1 text-xs`} role="group" aria-label="Map view">
              {(
                [
                  ["operations", "Live operations"],
                  ["public", "Public map"],
                ] as const
              ).map(([key, text]) => (
                <button
                  key={key}
                  onClick={() => setView(key)}
                  aria-pressed={view === key}
                  className={`rounded-lg px-2.5 py-1 font-semibold transition ${
                    view === key ? "bg-[#0c4a75] text-white" : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  {text}
                </button>
              ))}
            </div>
          )}
          <div className={`${panel} flex gap-1 p-1 text-xs`} role="group" aria-label="Base map">
            {(
              [
                ["streets", "Streets"],
                ["humanitarian", "Humanitarian"],
              ] as const
            ).map(([layer, text]) => (
              <button
                key={layer}
                onClick={() => setActiveBaseLayer(layer)}
                aria-pressed={activeBaseLayer === layer}
                className={`rounded-lg px-2.5 py-1 font-semibold transition ${
                  activeBaseLayer === layer ? "bg-[#0c4a75] text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {text}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Disaster Management operations layer (draws only for a DM session) */}
      {isDm && <LiveOperationsLayer mapRef={mapRef} visible={view === "operations"} />}

      {/* Cursor position (desktop only) */}
      <div className={`${panel} pointer-events-none absolute bottom-3 left-14 z-[500] hidden px-2.5 py-1 font-mono text-[11px] text-slate-700 sm:block`}>
        {coordsText}
      </div>

      {/* District filter + legend (public view) */}
      <div className={`pointer-events-auto absolute bottom-12 left-2 z-[500] sm:left-3 ${showPublic ? "" : "hidden"}`}>
        <button
          type="button"
          onClick={() => setShowMobileLegend((prev) => !prev)}
          className={`${panel} mb-1.5 flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold sm:hidden`}
          aria-expanded={showMobileLegend}
        >
          {showMobileLegend ? "Hide filters" : "Filters & legend"}
          {districtFilter && <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[11px] font-bold text-sky-800">{districtFilter}</span>}
        </button>

        <div className={`${showMobileLegend ? "block" : "hidden"} ${panel} max-h-[55vh] w-52 overflow-y-auto p-3 sm:block`}>
          <label htmlFor="district-filter" className="mb-1 block text-[11px] font-bold uppercase tracking-wide text-slate-500">
            District
          </label>
          <select
            id="district-filter"
            value={districtFilter}
            onChange={(e) => setDistrictFilter(e.target.value)}
            className="mb-3 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800"
          >
            <option value="">All Gujarat</option>
            {GUJARAT_DISTRICTS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>

          <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-slate-500">Disaster</div>
          <ul className="mb-3 space-y-1 text-xs">
            <li className="flex items-center gap-2"><span aria-hidden>🌀</span> Cyclone</li>
            <li className="flex items-center gap-2"><span aria-hidden>🌊</span> Urban flooding</li>
            <li className="flex items-center gap-2"><span aria-hidden>🔥</span> Industrial fire</li>
          </ul>

          <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-slate-500">Priority (marker colour)</div>
          <ul className="space-y-1 text-xs">
            {(["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNASSIGNED"] as const).map((k) => (
              <li key={k} className="flex items-center gap-2">
                <span className="size-3 shrink-0 rounded-full ring-1 ring-slate-300" style={{ backgroundColor: SEVERITY_COLORS[k] }} />
                {k.charAt(0) + k.slice(1).toLowerCase()}
              </li>
            ))}
          </ul>

          <div className="mt-3 border-t border-slate-200 pt-2 text-xs text-slate-600">
            <span className="mr-1 inline-block size-3 rounded-[3px] bg-amber-500 align-middle" aria-hidden /> Square markers are official
            early warnings{showAlertsLayer ? "" : " (hidden)"}.
            {unplacedAlerts > 0 && <span className="block text-slate-500">{unplacedAlerts} without a map position: see Active alerts.</span>}
          </div>
        </div>
      </div>

      {/* Selected incident (public fields only) */}
      {selectedIncident && (
        <div className={`${panel} pointer-events-auto absolute inset-x-2 bottom-3 z-[600] max-h-[80vh] overflow-y-auto p-4 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:w-80 sm:p-5 md:w-96`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <span
                className="mb-1 inline-block rounded px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-wider"
                style={{
                  backgroundColor: `${SEVERITY_COLORS[selectedIncident.severity] ?? "#94a3b8"}1f`,
                  color: SEVERITY_COLORS[selectedIncident.severity] ?? "#475569",
                  border: `1px solid ${SEVERITY_COLORS[selectedIncident.severity] ?? "#94a3b8"}`,
                }}
              >
                {selectedIncident.severity}
              </span>
              <h3 className="text-base font-bold leading-snug text-slate-900">
                <span aria-hidden className="mr-1">{SCENARIO_ICON[selectedIncident.scenario] ?? "⚠️"}</span>
                {selectedIncident.title}
              </h3>
              <p className="mt-0.5 text-xs text-slate-500">Ref: {selectedIncident.id}</p>
            </div>
            <button onClick={() => setSelectedIncident(null)} className="p-1 text-lg text-slate-400 hover:text-slate-700" aria-label="Close details">
              ✕
            </button>
          </div>

          <dl className="mt-4 space-y-2 border-t border-slate-200 pt-3 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-slate-500">Disaster</dt>
              <dd className="font-semibold capitalize text-slate-800">{selectedIncident.scenario.replace(/_/g, " ")}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-500">District</dt>
              <dd className="font-semibold text-slate-800">{selectedIncident.district ?? "Gujarat"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-slate-500">Status</dt>
              <dd className="font-semibold text-sky-700">{selectedIncident.lifecycle_status.replace(/_/g, " ").toLowerCase()}</dd>
            </div>
            {selectedIncident.detected_at && (
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Verified</dt>
                <dd className="font-semibold text-slate-800">{new Date(selectedIncident.detected_at).toLocaleString()}</dd>
              </div>
            )}
          </dl>

          {/* Reporting is for the public; inside the operations workspace the card is information only. */}
          {!session?.dm && (
            <Link
              href="/report"
              className="mt-4 block rounded-lg bg-red-600 py-2 text-center text-sm font-bold text-white transition hover:bg-red-500"
            >
              Report related incident
            </Link>
          )}
        </div>
      )}

      {/* Active alerts drawer */}
      {showAlertsDrawer && (
        <div className="pointer-events-auto absolute right-0 top-0 z-[700] flex h-full w-full flex-col border-l border-slate-200 bg-white p-4 text-slate-800 shadow-2xl sm:w-80 sm:p-5 md:w-96">
          <div className="flex items-center justify-between border-b border-slate-200 pb-3">
            <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
              <span aria-hidden>🔔</span> Active public alerts
            </h2>
            <button onClick={() => setShowAlertsDrawer(false)} className="p-1 text-slate-400 hover:text-slate-700" aria-label="Close alerts">
              ✕
            </button>
          </div>

          <div className="mt-3 flex-1 space-y-3 overflow-y-auto">
            {alerts.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">No active public alerts for Gujarat at this time.</p>
            ) : (
              alerts.map((alert) => (
                <div key={alert.id} className="space-y-1.5 rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: alertColor(alert.severity) }}>
                      {alert.severity}
                    </span>
                    {alert.is_fallback && (
                      <span className="rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[11px] font-semibold text-amber-800">
                        Sample alert
                      </span>
                    )}
                  </div>
                  <h4 className="text-sm font-bold text-slate-900">
                    <span aria-hidden className="mr-1">{hazardIcon(alert.type)}</span>
                    {alert.title}
                  </h4>
                  {alert.description && <p className="text-xs leading-relaxed text-slate-600">{alert.description}</p>}
                  <div className="flex justify-between border-t border-slate-200 pt-1 text-[11px] text-slate-500">
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
  );
}
