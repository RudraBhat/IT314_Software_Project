"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { RESOURCE_ICON, SCENARIO_ICON } from "@/lib/format";

/**
 * Disaster Management overlay for the existing ResQ map.
 *
 * Draws real incidents and located resources from the operations database
 * (GET /api/v1/dm/map via the same-origin proxy) onto the portal's Leaflet map,
 * in a separate layer group. It renders nothing unless the visitor has a valid
 * Disaster Management session: the backend refuses everyone else.
 */

type MapIncident = {
  incident_id: string;
  incident_ref: string;
  scenario: string;
  status: string;
  verified_priority: string | null;
  latitude: string;
  longitude: string;
  address_text: string | null;
  people_affected: number | null;
};
type MapResource = {
  resource_id: string;
  name: string;
  type: string;
  status: string;
  quantity_available: string;
  quantity_total: string;
  agency_name: string | null;
  latitude: number;
  longitude: number;
};
type MapData = {
  generated_at: string;
  incidents: MapIncident[];
  incidents_without_coordinates: { incident_id: string }[];
  resources: MapResource[];
};

// Same palette and icons as the portal's own incident markers.
const PRIORITY_COLOR: Record<string, string> = { CRITICAL: "#dc2626", HIGH: "#ea580c", MEDIUM: "#d97706", LOW: "#16a34a" };
const REFRESH_MS = 60_000;

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function words(value: string) {
  return value.replace(/_/g, " ").toLowerCase();
}

// The portal loads Leaflet from its CDN as window.L, so there are no static types.
type LeafletMap = any;

/**
 * Round icon-only marker (details open on click, so the map stays readable). Leaflet centres it with
 * iconAnchor; the box is a fixed square so the shape never stretches.
 */
function markerHtml(icon: string, border: string, shape: "round" | "square"): string {
  return `<div style="box-sizing:border-box;width:30px;height:30px;border-radius:${shape === "round" ? "50%" : "8px"};
    background:#ffffff;border:3px solid ${border};box-shadow:0 2px 6px rgba(15,23,42,.35);display:flex;
    align-items:center;justify-content:center;font-size:15px;line-height:1;cursor:pointer">${icon}</div>`;
}

/** `visible` comes from the map's Public / Live operations switch. */
export function LiveOperationsLayer({ mapRef, visible }: { mapRef: RefObject<LeafletMap>; visible: boolean }) {
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState(false);
  const layerRef = useRef<LeafletMap>(null);
  const focusedRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const session = await fetch("/api/session", { cache: "no-store" });
      if (!session.ok || !(await session.json()).dm) {
        setData(null); // guests, citizens and other roles see the portal unchanged
        return;
      }
      const res = await fetch("/api/dm/map", { cache: "no-store" });
      if (res.status === 401 || res.status === 403) {
        setData(null); // not Disaster Management staff: show nothing
        return;
      }
      if (!res.ok) throw new Error(String(res.status));
      setData(await res.json());
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load and periodic refresh
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Draw markers once both the data and the portal's map (loaded asynchronously) are ready.
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    let attempts = 0;

    const draw = () => {
      const L = (window as any).L;
      const map = mapRef.current;
      if (!L || !map) {
        if (!cancelled && attempts++ < 60) setTimeout(draw, 250);
        return;
      }
      if (!layerRef.current) layerRef.current = L.layerGroup();
      const layer = layerRef.current;
      layer.clearLayers();
      if (visible) layer.addTo(map);
      else map.removeLayer(layer);

      const focusId = new URLSearchParams(window.location.search).get("incident");
      let focusMarker: LeafletMap = null;

      for (const inc of data.incidents) {
        const color = inc.verified_priority ? PRIORITY_COLOR[inc.verified_priority] : "#475569";
        const html = markerHtml(SCENARIO_ICON[inc.scenario] ?? "⚠️", color, "round");
        const marker = L.marker([Number(inc.latitude), Number(inc.longitude)], {
          icon: L.divIcon({ html, className: "dm-live-incident-marker", iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -14] }),
          zIndexOffset: 500,
        }).bindPopup(`
          <div style="font:12px system-ui,sans-serif;padding:3px;min-width:180px">
            <div style="font-size:9px;font-weight:700;color:#0284c7;letter-spacing:.05em">LIVE · OPERATIONS DATABASE</div>
            <b style="color:#0f172a">${esc(inc.incident_ref)}</b><br/>
            <span style="color:#475569">${esc(words(inc.scenario))} · ${esc(words(inc.status))}</span><br/>
            <span style="color:#475569">Priority: ${esc(inc.verified_priority ? words(inc.verified_priority) : "unassigned")}</span><br/>
            ${inc.address_text ? `<span style="font-size:11px;color:#64748b">${esc(inc.address_text)}</span><br/>` : ""}
            <a href="/dm/incidents/${encodeURIComponent(inc.incident_id)}" style="color:#0284c7;font-weight:600">Open incident →</a>
          </div>`);
        marker.addTo(layer);
        if (focusId === inc.incident_id) focusMarker = marker;
      }

      for (const r of data.resources) {
        const html = markerHtml(RESOURCE_ICON[r.type] ?? "📍", r.status === "AVAILABLE" ? "#059669" : "#d97706", "square");
        L.marker([r.latitude, r.longitude], { icon: L.divIcon({ html, className: "dm-live-resource-marker", iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -14] }) })
          .bindPopup(`
            <div style="font:12px system-ui,sans-serif;padding:3px">
              <b style="color:#0f172a">${esc(r.name)}</b><br/>
              <span style="color:#475569">${esc(words(r.type))} · ${esc(words(r.status))}</span><br/>
              <span style="font-size:11px;color:#0284c7">${Number(r.quantity_available)} of ${Number(r.quantity_total)} available</span>
              ${r.agency_name ? `<br/><span style="font-size:10px;color:#64748b">${esc(r.agency_name)}</span>` : ""}
            </div>`)
          .addTo(layer);
      }

      if (focusMarker && visible && !focusedRef.current) {
        focusedRef.current = true;
        // Wait for the portal's own intro flight over India (about 3.6 s) before focusing.
        setTimeout(() => {
          map.flyTo(focusMarker.getLatLng(), 15, { duration: 2.5 });
          setTimeout(() => focusMarker.openPopup(), 2700);
        }, 3800);
      }
    };

    draw();
    return () => {
      cancelled = true;
    };
  }, [data, visible, mapRef]);

  // Remove the layer when the portal unmounts.
  useEffect(() => () => layerRef.current?.remove(), []);

  if (!data || !visible) return null;
  const missing = data.incidents_without_coordinates.length;

  return (
    <div className="absolute left-2 top-2 z-[500] w-64 rounded-xl border border-slate-200 bg-white/95 p-3 font-sans text-slate-800 shadow-lg backdrop-blur sm:left-3 sm:top-3">
      <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-[#0c4a75]">
        <span className="size-2 animate-pulse rounded-full bg-emerald-500" aria-hidden /> Live operations
      </div>
      <p className="mt-2 text-sm text-slate-700">
        <span className="font-semibold text-slate-900">{data.incidents.length}</span> open incident{data.incidents.length === 1 ? "" : "s"} ·{" "}
        <span className="font-semibold text-slate-900">{data.resources.length}</span> resource{data.resources.length === 1 ? "" : "s"} placed
      </p>
      {missing > 0 && <p className="mt-0.5 text-xs font-medium text-amber-700">{missing} incident{missing === 1 ? "" : "s"} without coordinates</p>}
      <ul className="mt-2 space-y-1 text-xs text-slate-600">
        <li className="flex items-center gap-2"><span className="size-3 rounded-full border-[3px] border-slate-500 bg-white" aria-hidden /> Incident (ring = priority)</li>
        <li className="flex items-center gap-2"><span className="size-3 rounded-[3px] border-[3px] border-emerald-600 bg-white" aria-hidden /> Resource available</li>
        <li className="flex items-center gap-2"><span className="size-3 rounded-[3px] border-[3px] border-amber-600 bg-white" aria-hidden /> Resource committed</li>
      </ul>
      <p className="mt-2 text-xs text-slate-500">
        Click a marker for details · updated {new Date(data.generated_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
        {error && <span className="font-medium text-red-600"> · refresh failed</span>}
      </p>
    </div>
  );
}
