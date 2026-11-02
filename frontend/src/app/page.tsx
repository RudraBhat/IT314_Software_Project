"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { ResQProvider, useResQ } from "../context/ResQContext";
import CitizenReportModal from "../components/CitizenReportModal";
import IncidentDetailPanel from "../components/IncidentDetailPanel";
import { DispatchModal } from "../components/DispatchModal";
import { RoleWorkspaceModal } from "../components/RoleWorkspaceModal";
import { AlertsDrawer } from "../components/AlertsDrawer";
import { AnalyticsModal } from "../components/AnalyticsModal";
import { SimulationBar } from "../components/SimulationBar";
import { AuthModal } from "../components/AuthModal";
import { GeneralPublicDashboardView } from "../components/role-views/GeneralPublicDashboardView";
import { CitizenDashboardView } from "../components/role-views/CitizenDashboardView";
import { AdminDashboardView } from "../components/role-views/AdminDashboardView";
import { ServiceProviderDashboardView } from "../components/role-views/ServiceProviderDashboardView";
import { LiveOperationsLayer } from "../components/dm/LiveOperationsLayer";
import { IncidentRecord, PortalRoleCategory } from "../types/resq";
import { LiveIncidentsView } from "../components/views/LiveIncidentsView";
import { DispatchCenterView } from "../components/views/DispatchCenterView";
import { RespondersView } from "../components/views/RespondersView";
import { ResourcesView } from "../components/views/ResourcesView";
import { AnalyticsView } from "../components/views/AnalyticsView";

// Basemap layer configurations with maxNativeZoom to prevent labels disappearing at deep zoom
const TILE_LAYERS = {
  streets: {
    name: "OpenStreetMap (All Roads, Villages & Towns - No Key Needed)",
    base: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    subdomains: [],
    maxZoom: 19,
    maxNativeZoom: 19,
    isSatellite: false,
  },
  humanitarian: {
    name: "Humanitarian OSM (Disaster & Relief Focus - No Key Needed)",
    base: "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
    subdomains: ["a", "b"],
    maxZoom: 19,
    maxNativeZoom: 19,
    isSatellite: false,
  },
  esriStreets: {
    name: "Esri World Streets (Clean Cartography - No Key Needed)",
    base: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    subdomains: ["a", "b", "c"],
    maxZoom: 19,
    maxNativeZoom: 18,
    isSatellite: false,
  },
  esriHybrid: {
    name: "Esri Satellite + World Boundaries (No Key Needed)",
    base: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    overlay: "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    subdomains: ["a", "b", "c"],
    maxZoom: 19,
    maxNativeZoom: 18,
    isSatellite: true,
  },
  esriTopo: {
    name: "Topographic & Elevation Map (Esri Topo - No Key Needed)",
    base: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    subdomains: ["a", "b", "c"],
    maxZoom: 19,
    maxNativeZoom: 18,
    isSatellite: false,
  },
  satellitePure: {
    name: "Pure Satellite Imagery (No Labels - No Key Needed)",
    base: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    subdomains: ["a", "b", "c"],
    maxZoom: 19,
    maxNativeZoom: 18,
    isSatellite: true,
  },
};

export type DashboardTab =
  | "dashboard"
  | "incidents"
  | "dispatch"
  | "responders"
  | "resources"
  | "analytics";

function CommandDashboard({
  activeTab,
  setActiveTab,
  incidents,
  responders,
  dispatches,
  unreadAlertCount,
  onMap,
  onMapWithIncident,
  onMapWithTarget,
  onReport,
  onAlerts,
  onSelectIncident,
  showCitizenReport,
  showRoleWorkspace,
  showAlertsDrawer,
  showAnalytics,
  showDispatchModal,
  dispatchIncident,
  onCloseReport,
  onCloseWorkspace,
  onCloseAlerts,
  onCloseAnalytics,
  onCloseDispatch,
  onOpenDispatch,
}: {
  activeTab: DashboardTab;
  setActiveTab: (tab: DashboardTab) => void;
  incidents: IncidentRecord[];
  responders: any[];
  dispatches: any[];
  unreadAlertCount: number;
  onMap: () => void;
  onMapWithIncident: (incident?: IncidentRecord) => void;
  onMapWithTarget: (target?: { lat: number; lon: number; title: string }) => void;
  onReport: () => void;
  onAlerts: () => void;
  onSelectIncident: (incident: IncidentRecord) => void;
  showCitizenReport: boolean;
  showRoleWorkspace: boolean;
  showAlertsDrawer: boolean;
  showAnalytics: boolean;
  showDispatchModal: boolean;
  dispatchIncident: IncidentRecord | null;
  onCloseReport: () => void;
  onCloseWorkspace: () => void;
  onCloseAlerts: () => void;
  onCloseAnalytics: () => void;
  onCloseDispatch: () => void;
  onOpenDispatch: (incident: IncidentRecord) => void;
}) {
  const active = incidents.filter((incident) => !["RESOLVED", "CLOSED"].includes(incident.lifecycleStatus)).length;
  const critical = incidents.filter((incident) => incident.severity === "CRITICAL").length;
  const cards = [
    ["Active incidents", String(active), critical ? `${critical} critical` : "Live feed", "#eaf3ff", "#075cab"],
    ["Units deployed", String(responders.length), `${dispatches.length} dispatches`, "#e9f9f0", "#078753"],
    ["Response status", "Live", "Operations monitored", "#fff4e5", "#b45d00"],
    ["Alerts", String(unreadAlertCount), unreadAlertCount ? "Needs review" : "All clear", "#fff0f0", "#ca3131"],
  ];

  return (
    <main className="h-screen overflow-y-auto bg-[#f4f7fa] text-[#13263d]">
      <div className="flex h-9 items-center justify-between bg-[#07569c] px-4 text-[11px] text-white sm:px-7">
        <span>Emergency Response &amp; Coordination Platform</span>
        <span className="flex items-center gap-2 sm:gap-5">
          <span className="text-emerald-300">●</span> All systems operational <span className="hidden sm:inline">◎ English⌄</span>
        </span>
      </div>
      <header className="flex h-20 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-7">
        <div className="flex items-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-lg border border-sky-200 bg-sky-50 text-2xl text-[#07569c]" aria-hidden>
            🛡
          </div>
          <div>
            <h1 className="text-[27px] leading-none font-bold tracking-tight text-[#07569c]">
              ResQ <span className="font-light text-slate-700">AI</span>
            </h1>
            <p className="mt-1.5 text-[11px] text-slate-500">Integrated Emergency Management</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="flex items-center gap-1.5 rounded-lg bg-[#07569c] hover:bg-[#064782] px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition"
          >
            <span>🔐</span>
            <span>Sign In / Staff Portal</span>
          </Link>
          <div className="text-right hidden sm:block">
            <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Regional command</p>
            <p className="mt-0.5 text-sm font-semibold">National Operations Center</p>
          </div>
        </div>
      </header>

      <div className="flex min-h-[calc(100vh-116px)]">
        {/* Left Sidebar */}
        <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white px-3 py-5 lg:block">
          <p className="mb-3 px-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">Operations</p>
          <nav className="space-y-1 text-sm">
            <button
              onClick={() => setActiveTab("dashboard")}
              className={`w-full rounded-lg px-3 py-3 text-left transition cursor-pointer flex items-center justify-between ${
                activeTab === "dashboard"
                  ? "border-l-4 border-[#075cab] bg-[#e2f0ff] font-semibold text-[#075cab]"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <span>▦ &nbsp; Dashboard</span>
            </button>
            <button
              onClick={() => setActiveTab("incidents")}
              className={`w-full rounded-lg px-3 py-3 text-left transition cursor-pointer flex items-center justify-between ${
                activeTab === "incidents"
                  ? "border-l-4 border-[#075cab] bg-[#e2f0ff] font-semibold text-[#075cab]"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <span>◉ &nbsp; Live incidents</span>
              <span className={`rounded px-2 text-xs font-bold ${activeTab === "incidents" ? "bg-[#075cab] text-white" : "bg-slate-100 text-slate-600"}`}>
                {active}
              </span>
            </button>
            <button
              onClick={onMap}
              className="w-full rounded-lg px-3 py-3 text-left text-slate-600 transition hover:bg-slate-50 cursor-pointer"
            >
              ⌖ &nbsp; Incident map
            </button>
            <button
              onClick={() => setActiveTab("dispatch")}
              className={`w-full rounded-lg px-3 py-3 text-left transition cursor-pointer flex items-center justify-between ${
                activeTab === "dispatch"
                  ? "border-l-4 border-[#075cab] bg-[#e2f0ff] font-semibold text-[#075cab]"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <span>➤ &nbsp; Dispatch center</span>
            </button>
            <button
              onClick={onAlerts}
              className="w-full rounded-lg px-3 py-3 text-left text-slate-600 transition hover:bg-slate-50 cursor-pointer flex items-center justify-between"
            >
              <span>♧ &nbsp; Alerts</span>
              {unreadAlertCount > 0 && (
                <span className="rounded bg-red-50 px-2 text-xs font-bold text-red-600">
                  {unreadAlertCount}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("responders")}
              className={`w-full rounded-lg px-3 py-3 text-left transition cursor-pointer flex items-center justify-between ${
                activeTab === "responders"
                  ? "border-l-4 border-[#075cab] bg-[#e2f0ff] font-semibold text-[#075cab]"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <span>♙ &nbsp; Responders</span>
            </button>
            <div className="my-3 border-t border-slate-200" />
            <button
              onClick={() => setActiveTab("resources")}
              className={`w-full rounded-lg px-3 py-3 text-left transition cursor-pointer flex items-center justify-between ${
                activeTab === "resources"
                  ? "border-l-4 border-[#075cab] bg-[#e2f0ff] font-semibold text-[#075cab]"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <span>♙ &nbsp; Resources</span>
            </button>
            <button
              onClick={() => setActiveTab("analytics")}
              className={`w-full rounded-lg px-3 py-3 text-left transition cursor-pointer flex items-center justify-between ${
                activeTab === "analytics"
                  ? "border-l-4 border-[#075cab] bg-[#e2f0ff] font-semibold text-[#075cab]"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <span>▥ &nbsp; Analytics &amp; reports</span>
            </button>
          </nav>
        </aside>

        {/* Main Content Area */}
        <section className="min-w-0 flex-1 p-4 sm:p-6 lg:p-7">
          {/* Mobile Top Navigation */}
          <nav aria-label="Dashboard navigation" className="mb-4 flex gap-1 overflow-x-auto lg:hidden">
            <button
              onClick={() => setActiveTab("dashboard")}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-semibold cursor-pointer ${
                activeTab === "dashboard" ? "bg-[#e2f0ff] text-[#075cab]" : "text-slate-600 hover:bg-white"
              }`}
            >
              ▦ Dashboard
            </button>
            <button
              onClick={() => setActiveTab("incidents")}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-semibold cursor-pointer ${
                activeTab === "incidents" ? "bg-[#e2f0ff] text-[#075cab]" : "text-slate-600 hover:bg-white"
              }`}
            >
              ◉ Live incidents
            </button>
            <button
              onClick={onMap}
              className="shrink-0 rounded-lg px-3 py-2 text-xs text-slate-600 hover:bg-white cursor-pointer"
            >
              ⌖ Incident map
            </button>
            <button
              onClick={() => setActiveTab("dispatch")}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-semibold cursor-pointer ${
                activeTab === "dispatch" ? "bg-[#e2f0ff] text-[#075cab]" : "text-slate-600 hover:bg-white"
              }`}
            >
              ➤ Dispatch
            </button>
            <button
              onClick={onAlerts}
              className="shrink-0 rounded-lg px-3 py-2 text-xs text-slate-600 hover:bg-white cursor-pointer"
            >
              ♧ Alerts
            </button>
            <button
              onClick={() => setActiveTab("responders")}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-semibold cursor-pointer ${
                activeTab === "responders" ? "bg-[#e2f0ff] text-[#075cab]" : "text-slate-600 hover:bg-white"
              }`}
            >
              ♙ Responders
            </button>
            <button
              onClick={() => setActiveTab("resources")}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-semibold cursor-pointer ${
                activeTab === "resources" ? "bg-[#e2f0ff] text-[#075cab]" : "text-slate-600 hover:bg-white"
              }`}
            >
              ♙ Resources
            </button>
            <button
              onClick={() => setActiveTab("analytics")}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-semibold cursor-pointer ${
                activeTab === "analytics" ? "bg-[#e2f0ff] text-[#075cab]" : "text-slate-600 hover:bg-white"
              }`}
            >
              ▥ Analytics
            </button>
          </nav>

          {/* TAB 1: OVERVIEW DASHBOARD */}
          {activeTab === "dashboard" && (
            <div>
              <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Situational awareness
                  </p>
                  <h2 className="mt-1.5 text-2xl font-bold sm:text-3xl">Command Dashboard</h2>
                  <p className="mt-1.5 text-sm text-slate-500">
                    Real-time incident monitoring and coordinated emergency response.
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setActiveTab("analytics")}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold shadow-xs transition hover:bg-slate-50 cursor-pointer"
                  >
                    Analytics
                  </button>
                  <button
                    onClick={onReport}
                    className="rounded-lg bg-[#075cab] px-3 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-[#064a85] cursor-pointer"
                  >
                    + Situation report
                  </button>
                </div>
              </div>

              {critical > 0 && (
                <button
                  onClick={() => setActiveTab("incidents")}
                  className="mb-6 flex w-full items-center justify-between rounded-lg border border-red-200 border-l-4 border-l-red-500 bg-red-50 px-5 py-4 text-left text-sm text-red-700 cursor-pointer hover:bg-red-100/50 transition"
                >
                  <span>
                    <b>Priority attention required</b> &nbsp; {critical} critical incident
                    {critical === 1 ? "" : "s"} active.
                  </span>
                  <span>Review →</span>
                </button>
              )}

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {cards.map(([label, value, detail, tone, color]) => (
                  <article
                    key={label}
                    onClick={() => {
                      if (label === "Active incidents") setActiveTab("incidents");
                      if (label === "Units deployed") setActiveTab("responders");
                      if (label === "Alerts") onAlerts();
                    }}
                    className="rounded-lg border border-slate-200 bg-white p-4 shadow-xs sm:p-5 transition hover:shadow-sm cursor-pointer"
                  >
                    <div className="flex items-start justify-between">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{label}</p>
                      <span className="rounded-lg px-2 py-1" style={{ backgroundColor: tone, color }}>
                        ●
                      </span>
                    </div>
                    <p className="mt-4 text-3xl font-bold sm:text-4xl">{value}</p>
                    <p className="mt-2 text-xs text-slate-500">{detail}</p>
                  </article>
                ))}
              </div>

              <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.75fr)]">
                <article className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs">
                  <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5 sm:px-5">
                    <div>
                      <h3 className="font-semibold">⌖ &nbsp; Live incident map</h3>
                      <p className="mt-0.5 text-xs text-slate-500">Operational overview · India</p>
                    </div>
                    <button
                      onClick={onMap}
                      className="text-sm font-semibold text-[#075cab] hover:underline cursor-pointer"
                    >
                      Open full map →
                    </button>
                  </div>
                  <button
                    onClick={onMap}
                    aria-label="Open interactive incident map"
                    className="relative grid h-56 w-full place-items-center overflow-hidden bg-[#eaf2f3] text-center sm:h-64 cursor-pointer"
                  >
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 900 360"
                      preserveAspectRatio="xMidYMid slice"
                      className="absolute inset-0 h-full w-full"
                    >
                      <rect width="900" height="360" fill="#eaf2f3" />
                      <path
                        d="M0 55 150 20 270 65 390 20 520 70 650 25 900 60M0 160 130 115 260 175 390 120 510 170 660 115 900 165M0 285 150 240 280 300 420 245 570 310 720 245 900 300"
                        fill="none"
                        stroke="#d3e4df"
                        strokeWidth="34"
                      />
                      <path
                        d="M70-20 160 380M280-20 355 380M520-20 440 380M700-20 620 380M0 95 900 255M0 230 900 100"
                        fill="none"
                        stroke="#fff"
                        strokeWidth="11"
                      />
                      <path
                        d="M70-20 160 380M280-20 355 380M520-20 440 380M700-20 620 380M0 95 900 255M0 230 900 100"
                        fill="none"
                        stroke="#cbd5d7"
                        strokeWidth="2"
                      />
                      <path
                        d="M0 340Q160 250 300 330T600 320T900 345"
                        fill="none"
                        stroke="#89c7e0"
                        strokeWidth="20"
                      />
                    </svg>
                    {incidents.slice(0, 4).map((incident, index) => (
                      <span
                        key={incident.id}
                        className="absolute z-10 grid size-8 place-items-center rounded-full border-2 border-white bg-[#e9842a] text-xs font-bold text-white shadow-md"
                        style={{
                          left: `${24 + index * 17}%`,
                          top: `${25 + (index % 2) * 35}%`,
                        }}
                        aria-hidden
                      >
                        !
                      </span>
                    ))}
                    <span className="absolute bottom-3 left-3 z-10 rounded-md border border-slate-200 bg-white/95 px-3 py-1.5 text-[11px] font-semibold text-slate-700 shadow-xs">
                      <span className="mr-2 text-emerald-600">●</span>India · Operational area
                    </span>
                    <span className="relative z-10 rounded-full border border-sky-200 bg-white/95 px-4 py-2 text-sm font-semibold text-[#07569c] shadow-xs">
                      Open interactive map
                    </span>
                  </button>
                </article>

                <article className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between border-b border-sky-200 bg-[#e5f2ff] px-4 py-3.5 sm:px-5">
                      <h3 className="font-semibold text-[#07569c]">✦ AI incident triage</h3>
                      <span className="rounded border border-sky-200 bg-white/70 px-2 py-1 text-[10px] font-bold text-[#07569c]">
                        AI ASSIST
                      </span>
                    </div>
                    <div className="p-5">
                      <p className="text-xs text-slate-500">{incidents[0]?.id || "LATEST ASSESSMENT"}</p>
                      <h4 className="mt-3 text-lg font-bold">{incidents[0]?.title || "No active incident selected"}</h4>
                      <p className="mt-2 text-sm leading-6 text-slate-600">
                        AI-assisted prioritization is available to support the command team.
                      </p>
                      <div className="mt-4 flex items-center gap-2 text-xs">
                        <span className="rounded bg-red-50 px-2 py-1 font-semibold text-red-700">
                          {incidents[0]?.severity || "Monitoring"}
                        </span>
                        <span className="text-emerald-700 font-semibold">✓ Verified report</span>
                      </div>
                    </div>
                  </div>
                  <div className="p-5 pt-0">
                    <button
                      onClick={() => setActiveTab("incidents")}
                      className="text-sm font-semibold text-[#075cab] hover:underline cursor-pointer"
                    >
                      View in live incidents →
                    </button>
                  </div>
                </article>
              </div>
            </div>
          )}

          {/* TAB 2: LIVE INCIDENTS */}
          {activeTab === "incidents" && (
            <LiveIncidentsView
              onOpenMap={onMapWithIncident}
              onOpenDispatch={onOpenDispatch}
              onOpenReport={onReport}
              onSelectIncident={onSelectIncident}
            />
          )}

          {/* TAB 3: DISPATCH CENTER */}
          {activeTab === "dispatch" && (
            <DispatchCenterView
              onOpenMap={onMapWithIncident}
              onOpenDispatchModal={(inc) => {
                if (inc) onOpenDispatch(inc);
                else if (incidents.length > 0) onOpenDispatch(incidents[0]);
              }}
            />
          )}

          {/* TAB 4: RESPONDERS */}
          {activeTab === "responders" && (
            <RespondersView onOpenMap={onMapWithTarget} />
          )}

          {/* TAB 5: RESOURCES */}
          {activeTab === "resources" && <ResourcesView />}

          {/* TAB 6: ANALYTICS */}
          {activeTab === "analytics" && <AnalyticsView />}
        </section>
      </div>

      <CitizenReportModal isOpen={showCitizenReport} onClose={onCloseReport} />
      <RoleWorkspaceModal
        isOpen={showRoleWorkspace}
        onClose={onCloseWorkspace}
        onOpenCitizenReport={onReport}
        onOpenDispatch={onOpenDispatch}
      />
      <AlertsDrawer isOpen={showAlertsDrawer} onClose={onCloseAlerts} />
      <AnalyticsModal isOpen={showAnalytics} onClose={onCloseAnalytics} />
      <DispatchModal
        incident={dispatchIncident}
        isOpen={showDispatchModal}
        onClose={onCloseDispatch}
      />
    </main>
  );
}


// Permanent 100% watermark-free street & road labels overlay (Esri Reference Labels)
const STREET_LABELS_OVERLAY = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";

function ResQGeoPortalInner() {
  const {
    currentUser,
    roleCategory,
    isAuthenticated,
    switchRole,
    logout,
    incidents,
    selectedIncident,
    selectIncident,
    responders,
    dispatches,
    infrastructure,
    unreadAlertCount,
    mapFocusTarget,
    setMapFocusTarget,
  } = useResQ();

  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const baseLayerRef = useRef<any>(null);
  const secondaryOverlayRef = useRef<any>(null);
  const streetOverlayRef = useRef<any>(null);

  const activePinRef = useRef<any>(null);
  const measureLayerRef = useRef<any>(null);
  const locationLayerRef = useRef<any>(null);

  // Dynamic GIS feature layer groups
  const incidentsLayerRef = useRef<any>(null);
  const respondersLayerRef = useRef<any>(null);
  const routesLayerRef = useRef<any>(null);
  const infrastructureLayerRef = useRef<any>(null);

  // UI state
  const [coordsText, setCoordsText] = useState("Lat: -- | Lon: --");
  const [currentZoom, setCurrentZoom] = useState(5);
  const [visibleAreaName, setVisibleAreaName] = useState<string>("India");
  const [currentBaseLayer, setCurrentBaseLayer] = useState<keyof typeof TILE_LAYERS>("streets");
  const [streetOverlayActive, setStreetOverlayActive] = useState(false);
  const [showLayerMenu, setShowLayerMenu] = useState(false);
  const [showAboutModal, setShowAboutModal] = useState(false);
  const [showNavDrawer, setShowNavDrawer] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [isMeasuring, setIsMeasuring] = useState(false);
  const [measureDistance, setMeasureDistance] = useState<string | null>(null);
  const [selectedLang, setSelectedLang] = useState("English");

  // Splash screen & Dashboard panel
  const [activeTab, setActiveTab] = useState<DashboardTab>("dashboard");
  const [showSplash, setShowSplash] = useState(false);
  const [splashFading, setSplashFading] = useState(false);
  const [showDashboard, setShowDashboard] = useState(false);
  const [citizenViewPublicMap, setCitizenViewPublicMap] = useState(false);
  const [showMapView, setShowMapView] = useState(false);
  const [mapReady, setMapReady] = useState(false);

  // Auth & Role Modals visibility
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authModalMode, setAuthModalMode] = useState<"login" | "signup">("login");
  const [authModalCategory] = useState<PortalRoleCategory>("user");
  const [showRoleMenu, setShowRoleMenu] = useState(false);

  // Modals & Panels visibility
  const [showCitizenReport, setShowCitizenReport] = useState(false);
  const [showRoleWorkspace, setShowRoleWorkspace] = useState(false);
  const [showAlertsDrawer, setShowAlertsDrawer] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [showSimulationBar, setShowSimulationBar] = useState(false);
  const [dispatchIncident, setDispatchIncident] = useState<IncidentRecord | null>(null);
  const [showDispatchModal, setShowDispatchModal] = useState(false);

  // Measurement ref
  const measurePointsRef = useRef<any[]>([]);
  const reverseGeocodeTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Splash screen auto-dismiss
  useEffect(() => {
    const fadeTimer = setTimeout(() => setSplashFading(true), 2800);
    return () => clearTimeout(fadeTimer);
  }, []);


  // Fetch real-world place name on zoom/move (0 API keys required)
  const fetchRealPlaceName = useCallback(async (lat: number, lon: number, zoom: number) => {
    if (zoom < 5) {
      setVisibleAreaName("India (National Overview)");
      return;
    }

    try {
      const zoomLevel = Math.min(Math.max(zoom, 8), 18);
      const url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=${zoomLevel}&addressdetails=1`;
      const response = await fetch(url, { headers: { "Accept-Language": "en" } });
      if (!response.ok) return;

      const data = await response.json();
      if (data && data.address) {
        const addr = data.address;
        const parts = [
          addr.road || addr.suburb || addr.neighbourhood || addr.village || addr.hamlet || addr.town || addr.locality,
          addr.city || addr.county || addr.district,
          addr.state,
        ].filter(Boolean);

        const label = parts.length > 0 ? parts.join(", ") : data.display_name.split(",").slice(0, 3).join(",");
        setVisibleAreaName(label);
      }
    } catch {
      // Offline fallback
    }
  }, []);

  // Initialize Map
  useEffect(() => {
    if (!showMapView) return;

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

        // Initialize Map with Crisp Integer Zoom and deep zoom allowance (maxZoom: 21)
        const map = L.map(mapContainerRef.current, {
          zoomControl: false,
          attributionControl: false,
          minZoom: 2,
          maxZoom: 21,
          worldCopyJump: true,
          fadeAnimation: true,
          zoomAnimation: true,
          zoomAnimationThreshold: 8,
          zoomSnap: 1,
          zoomDelta: 1,
          wheelPxPerZoomLevel: 100,
          wheelDebounceTime: 40,
          inertia: true,
          inertiaDeceleration: 3000,
          inertiaMaxSpeed: 2000,
          easeLinearity: 0.22,
        }).setView([22.6, 79.1], 5);

        mapRef.current = map;

        // Base Layer: OpenStreetMap (Standard 100% Free Open GIS - Zero Keys Required)
        const initialCfg = TILE_LAYERS.streets;
        const baseLayer = L.tileLayer(initialCfg.base, {
          maxZoom: 19,
          maxNativeZoom: 19,
          subdomains: initialCfg.subdomains,
          updateWhenZooming: false,
          updateWhenIdle: true,
          keepBuffer: 2,
        }).addTo(map);
        baseLayerRef.current = baseLayer;

        // Watermark-Free Street & Place Names Overlay
        const streetOverlay = L.tileLayer(STREET_LABELS_OVERLAY, {
          subdomains: ["a", "b", "c"],
          maxZoom: 19,
          maxNativeZoom: 18,
          opacity: 1.0,
        });
        streetOverlayRef.current = streetOverlay;

        // Scale bar in bottom-left
        L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

        // Feature Layer Groups
        measureLayerRef.current = L.layerGroup().addTo(map);
        locationLayerRef.current = L.layerGroup().addTo(map);
        incidentsLayerRef.current = L.layerGroup().addTo(map);
        respondersLayerRef.current = L.layerGroup().addTo(map);
        routesLayerRef.current = L.layerGroup().addTo(map);
        infrastructureLayerRef.current = L.layerGroup().addTo(map);

        // Coordinates mousemove tracking
        map.on("mousemove", (e: any) => {
          const lat = e.latlng.lat.toFixed(4);
          const lon = e.latlng.lng.toFixed(4);
          const latDir = e.latlng.lat >= 0 ? "N" : "S";
          const lonDir = e.latlng.lng >= 0 ? "E" : "W";
          setCoordsText(`Lat: ${Math.abs(Number(lat))}° ${latDir} | Lon: ${Math.abs(Number(lon))}° ${lonDir}`);
        });

        // Dynamic Zoom & Move event listener
        map.on("zoomend", () => {
          setCurrentZoom(map.getZoom());
        });

        map.on("moveend", () => {
          const center = map.getCenter();
          const zoom = map.getZoom();
          if (reverseGeocodeTimeoutRef.current) {
            clearTimeout(reverseGeocodeTimeoutRef.current);
          }
          reverseGeocodeTimeoutRef.current = setTimeout(() => {
            fetchRealPlaceName(center.lat, center.lng, zoom);
          }, 500);
        });

        setMapReady(true);

        // Ensure canvas dimensions are refreshed for the layout
        setTimeout(() => {
          if (!isCancelled && mapRef.current) {
            mapRef.current.invalidateSize();
          }
        }, 100);

        setTimeout(() => {
          if (!isCancelled && mapRef.current) {
            mapRef.current.invalidateSize();
          }
        }, 500);

        // Initial smooth glide into India
        setTimeout(() => {
          if (!isCancelled && mapRef.current) {
            mapRef.current.flyTo([23.5, 80.5], 5, {
              duration: 3.2,
              easeLinearity: 0.22,
              noMoveStart: true,
            });
            mapRef.current.invalidateSize();
          }
        }, 400);
      } catch (err) {
        console.error("Map initialization failed:", err);
      }
    };

    initMap();

    return () => {
      isCancelled = true;
      if (reverseGeocodeTimeoutRef.current) {
        clearTimeout(reverseGeocodeTimeoutRef.current);
      }
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [fetchRealPlaceName, showMapView]);

  // Handle map navigation requests from context
  useEffect(() => {
    if (!showMapView || !mapReady || !mapFocusTarget || !mapRef.current) return;
    mapRef.current.flyTo([mapFocusTarget.lat, mapFocusTarget.lon], mapFocusTarget.zoom, {
      duration: 2.5,
      easeLinearity: 0.22,
    });
    setMapFocusTarget(null);
  }, [mapFocusTarget, setMapFocusTarget, mapReady, showMapView]);

  // Render Incident Markers on Map
  useEffect(() => {
    const L = (window as any).L;
    if (!showMapView || !mapReady || !L || !mapRef.current || !incidentsLayerRef.current) return;

    incidentsLayerRef.current.clearLayers();

    incidents.forEach((inc) => {
      const getCategoryIcon = () => {
        if (inc.category === "Major Urban / Building Fire") return "🔥";
        if (inc.category === "Cyclone / Coastal Flooding") return "🌀";
        return "🌊";
      };

      const getSeverityColor = () => {
        if (inc.severity === "CRITICAL") return "#dc2626";
        if (inc.severity === "HIGH") return "#ea580c";
        if (inc.severity === "MODERATE") return "#d97706";
        return "#16a34a";
      };

      const iconHtml = `
        <div style="
          background: ${getSeverityColor()};
          color: white;
          font-family: system-ui, -apple-system, sans-serif;
          font-size: 11px;
          font-weight: 700;
          padding: 3px 8px;
          border-radius: 9999px;
          border: 2px solid white;
          box-shadow: 0 4px 10px rgba(0,0,0,0.5);
          display: flex;
          align-items: center;
          gap: 4px;
          white-space: nowrap;
          cursor: pointer;
          transform: translate(-50%, -50%);
        ">
          <span>${getCategoryIcon()}</span>
          <span>${inc.id}</span>
          <span style="font-size: 9px; opacity: 0.9; background: rgba(0,0,0,0.25); padding: 1px 4px; border-radius: 4px;">
            ${inc.lifecycleStatus}
          </span>
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: "resq-incident-marker",
        iconSize: [0, 0],
      });

      const marker = L.marker([inc.lat, inc.lon], { icon: customIcon });

      marker.on("click", () => {
        selectIncident(inc);
      });

      marker.addTo(incidentsLayerRef.current);
    });
  }, [incidents, selectIncident, mapReady, showMapView]);

  // Render Responder Unit Markers on Map
  useEffect(() => {
    const L = (window as any).L;
    if (!showMapView || !mapReady || !L || !mapRef.current || !respondersLayerRef.current) return;

    respondersLayerRef.current.clearLayers();

    responders.forEach((unit) => {
      const getUnitIcon = () => {
        if (unit.callsign.includes("AMB")) return "🚑";
        if (unit.callsign.includes("FIRE")) return "🚒";
        if (unit.callsign.includes("RESCUE")) return "🚤";
        return "🚁";
      };

      const getStatusColor = () => {
        if (unit.status === "AVAILABLE") return "#10b981";
        if (unit.status === "EN ROUTE") return "#f59e0b";
        if (unit.status === "ON SCENE") return "#ef4444";
        return "#64748b";
      };

      const iconHtml = `
        <div style="
          background: #0f172a;
          color: #f8fafc;
          font-family: monospace;
          font-size: 10px;
          font-weight: 700;
          padding: 2px 6px;
          border-radius: 6px;
          border: 1.5px solid ${getStatusColor()};
          box-shadow: 0 2px 8px rgba(0,0,0,0.6);
          display: flex;
          align-items: center;
          gap: 3px;
          white-space: nowrap;
          cursor: pointer;
          transform: translate(-50%, -50%);
        ">
          <span>${getUnitIcon()}</span>
          <span style="color: #38bdf8;">${unit.callsign}</span>
          <span style="font-size: 8px; color: ${getStatusColor()};">●</span>
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: "resq-unit-marker",
        iconSize: [0, 0],
      });

      const marker = L.marker([unit.currentLat, unit.currentLon], { icon: customIcon });

      marker.bindPopup(`
        <div style="font-family: system-ui, sans-serif; font-size: 12px; padding: 3px;">
          <b style="color: #0f172a;">${unit.callsign} (${unit.personnelName})</b><br/>
          <span style="color: #475569;">Agency: ${unit.agency}</span><br/>
          <span style="color: #0284c7; font-weight: 600;">Status: ${unit.status}</span><br/>
          <span style="font-size: 10px; color: #64748b;">Vehicle: ${unit.vehicleType}</span>
        </div>
      `);

      marker.addTo(respondersLayerRef.current);
    });
  }, [responders, mapReady, showMapView]);

  // Render Infrastructure Markers on Map (Hospitals, Shelters, Blocked Roads)
  useEffect(() => {
    const L = (window as any).L;
    if (!showMapView || !mapReady || !L || !mapRef.current || !infrastructureLayerRef.current) return;

    infrastructureLayerRef.current.clearLayers();

    infrastructure.forEach((item) => {
      const getIcon = () => {
        if (item.type === "HOSPITAL") return "🏥";
        if (item.type === "SHELTER") return "⛺";
        if (item.type === "FIRE_STATION") return "🚒";
        if (item.type === "BLOCKED_ROAD") return "🚧";
        return "🏢";
      };

      const iconHtml = `
        <div style="
          background: #1e293b;
          color: white;
          font-size: 11px;
          padding: 2px 4px;
          border-radius: 6px;
          border: 1px solid #475569;
          box-shadow: 0 2px 6px rgba(0,0,0,0.4);
          cursor: pointer;
          transform: translate(-50%, -50%);
        ">
          ${getIcon()}
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: "resq-infra-marker",
        iconSize: [0, 0],
      });

      const marker = L.marker([item.lat, item.lon], { icon: customIcon });

      marker.bindPopup(`
        <div style="font-family: system-ui, sans-serif; font-size: 12px; padding: 2px;">
          <b style="color: #0f172a;">${getIcon()} ${item.name}</b><br/>
          <span style="color: #475569;">${item.address}</span><br/>
          <span style="color: #059669; font-weight: 600;">Status: ${item.status}</span><br/>
          ${item.availableBeds ? `<span style="font-size: 11px; color: #0284c7;">Available Beds: ${item.availableBeds}</span><br/>` : ""}
          <span style="font-size: 10px; color: #64748b;">Phone: ${item.contactNumber}</span>
        </div>
      `);

      marker.addTo(infrastructureLayerRef.current);
    });
  }, [infrastructure, mapReady, showMapView]);

  // Render Route Polylines for Active Dispatches
  useEffect(() => {
    const L = (window as any).L;
    if (!showMapView || !mapReady || !L || !mapRef.current || !routesLayerRef.current) return;

    routesLayerRef.current.clearLayers();

    dispatches.forEach((d) => {
      if (d.status !== "COMPLETED" && d.status !== "CANCELLED" && d.routeCoordinates.length > 1) {
        L.polyline(d.routeCoordinates, {
          color: "#38bdf8",
          weight: 4,
          opacity: 0.85,
          dashArray: "6, 6",
        }).addTo(routesLayerRef.current);
      }
    });
  }, [dispatches, mapReady, showMapView]);

  // Switch Base Layer
  const switchBaseLayer = (key: keyof typeof TILE_LAYERS) => {
    const L = (window as any).L;
    if (!L || !mapRef.current || !baseLayerRef.current) return;

    mapRef.current.removeLayer(baseLayerRef.current);
    if (secondaryOverlayRef.current) {
      mapRef.current.removeLayer(secondaryOverlayRef.current);
      secondaryOverlayRef.current = null;
    }

    const layerCfg = TILE_LAYERS[key] as any;
    const newLayer = L.tileLayer(layerCfg.base, {
      maxZoom: 21,
      maxNativeZoom: layerCfg.maxNativeZoom || 19,
      subdomains: layerCfg.subdomains,
      updateWhenZooming: false,
      updateWhenIdle: true,
      keepBuffer: 2,
    }).addTo(mapRef.current);

    baseLayerRef.current = newLayer;
    newLayer.bringToBack();

    if (layerCfg.overlay) {
      const newOverlay = L.tileLayer(layerCfg.overlay, {
        maxZoom: 21,
        maxNativeZoom: layerCfg.maxNativeZoom || 18,
        subdomains: layerCfg.subdomains,
        updateWhenZooming: false,
        updateWhenIdle: true,
        keepBuffer: 2,
      }).addTo(mapRef.current);
      secondaryOverlayRef.current = newOverlay;
    }

    setCurrentBaseLayer(key);
    setShowLayerMenu(false);
  };

  // Toggle Street Names Overlay
  const toggleStreetOverlay = () => {
    if (!mapRef.current || !streetOverlayRef.current) return;
    if (streetOverlayActive) {
      mapRef.current.removeLayer(streetOverlayRef.current);
      setStreetOverlayActive(false);
    } else {
      streetOverlayRef.current.addTo(mapRef.current);
      streetOverlayRef.current.bringToFront();
      setStreetOverlayActive(true);
    }
  };

  // Real-time Search using OpenStreetMap Nominatim
  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const query = searchQuery.trim();
    if (!query || !mapRef.current) return;

    const coordMatch = query.match(/^([-+]?[0-9]*\.?[0-9]+)[,\s]+([-+]?[0-9]*\.?[0-9]+)$/);
    if (coordMatch) {
      const lat = parseFloat(coordMatch[1]);
      const lon = parseFloat(coordMatch[2]);
      if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
        flyToAndPin(lat, lon, 16, `Coordinates (${lat.toFixed(4)}, ${lon.toFixed(4)})`, `Direct GPS input: ${lat}, ${lon}`);
        return;
      }
    }

    setIsSearching(true);

    try {
      const url = `https://nominatim.openstreetmap.org/search?format=json&countrycodes=in&limit=1&q=${encodeURIComponent(
        query
      )}`;
      const res = await fetch(url, { headers: { "Accept-Language": "en" } });

      if (res.ok) {
        const results = await res.json();
        if (results && results.length > 0) {
          const item = results[0];
          const lat = parseFloat(item.lat);
          const lon = parseFloat(item.lon);
          const displayName = item.display_name;
          const shortTitle = displayName.split(",")[0];

          let zoomLevel = 15;
          if (item.type === "administrative" || item.addresstype === "state") zoomLevel = 7;
          else if (item.addresstype === "city" || item.addresstype === "district") zoomLevel = 11;
          else zoomLevel = 16;

          flyToAndPin(lat, lon, zoomLevel, shortTitle, displayName);
          setIsSearching(false);
          return;
        }
      }
    } catch {
      // Offline fallback
    }

    alert(`Location "${searchQuery}" not found. Try searching a major city or road name.`);
    setIsSearching(false);
  };

  // Fly to location with a clean interactive highlight pin
  const flyToAndPin = (lat: number, lon: number, zoom: number, title: string, fullDetails: string) => {
    const L = (window as any).L;
    if (!mapRef.current || !L) return;

    mapRef.current.flyTo([lat, lon], zoom, {
      duration: 2.8,
      easeLinearity: 0.22,
      noMoveStart: true,
    });

    if (activePinRef.current) {
      mapRef.current.removeLayer(activePinRef.current);
    }

    const pinMarker = L.circleMarker([lat, lon], {
      radius: 8,
      color: "#ffffff",
      weight: 2.5,
      fillColor: "#0284c7",
      fillOpacity: 1,
    });

    pinMarker.bindPopup(`
      <div style="font-family:'Segoe UI',sans-serif; padding:4px 6px; max-width:260px;">
        <b style="font-size:13.5px; color:#0f172a;">📍 ${title}</b><br/>
        <span style="font-size:11px; color:#475569; display:block; margin:4px 0;">${fullDetails}</span>
        <div style="margin-top:6px; font-size:10.5px; color:#0369a1; font-weight:600; background:#f0f9ff; padding:2px 6px; border-radius:4px; border:1px solid #bae6fd;">
          Lat: ${lat.toFixed(5)}° | Lon: ${lon.toFixed(5)}° (Zoom ${zoom}x)
        </div>
      </div>
    `);

    pinMarker.addTo(mapRef.current);
    setTimeout(() => pinMarker.openPopup(), 1200);
    activePinRef.current = pinMarker;
  };

  // Geodesic measurement tool
  const toggleMeasurement = () => {
    const L = (window as any).L;
    if (!mapRef.current || !measureLayerRef.current || !L) return;

    if (isMeasuring) {
      setIsMeasuring(false);
      measureLayerRef.current.clearLayers();
      measurePointsRef.current = [];
      setMeasureDistance(null);
      mapRef.current.off("click", onMeasureClick);
    } else {
      setIsMeasuring(true);
      measureLayerRef.current.clearLayers();
      measurePointsRef.current = [];
      setMeasureDistance("Click any 2 or more points to measure distance");
      mapRef.current.on("click", onMeasureClick);
    }
  };

  const onMeasureClick = (e: any) => {
    const L = (window as any).L;
    if (!L || !measureLayerRef.current) return;

    const latlng = e.latlng;
    measurePointsRef.current.push(latlng);

    L.circleMarker(latlng, {
      radius: 5,
      color: "#0284c7",
      fillColor: "#fff",
      fillOpacity: 1,
      weight: 2,
    }).addTo(measureLayerRef.current);

    if (measurePointsRef.current.length > 1) {
      L.polyline(measurePointsRef.current, {
        color: "#0284c7",
        weight: 3,
        dashArray: "6, 6",
      }).addTo(measureLayerRef.current);

      let totalMeters = 0;
      for (let i = 0; i < measurePointsRef.current.length - 1; i++) {
        totalMeters += measurePointsRef.current[i].distanceTo(measurePointsRef.current[i + 1]);
      }

      const km = (totalMeters / 1000).toFixed(2);
      setMeasureDistance(`Total Distance: ${km} km (${Math.round(totalMeters)} m)`);
    }
  };

  // User Geolocation
  const handleLocateMe = () => {
    const L = (window as any).L;
    if (!mapRef.current || !locationLayerRef.current || !navigator.geolocation) {
      alert("Geolocation is not permitted or supported in this browser.");
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        locationLayerRef.current.clearLayers();

        L.circle([latitude, longitude], {
          radius: accuracy,
          color: "#0284c7",
          fillColor: "#38bdf8",
          fillOpacity: 0.25,
          weight: 1.5,
        }).addTo(locationLayerRef.current);

        const marker = L.circleMarker([latitude, longitude], {
          radius: 8,
          color: "#ffffff",
          weight: 2.5,
          fillColor: "#0284c7",
          fillOpacity: 1,
        }).addTo(locationLayerRef.current);

        marker.bindPopup(`<b>Your Current Location</b><br/>Lat: ${latitude.toFixed(4)}, Lon: ${longitude.toFixed(4)}<br/>Accuracy: ±${Math.round(accuracy)}m`).openPopup();
        mapRef.current.flyTo([latitude, longitude], 16, { duration: 2.5, easeLinearity: 0.22 });
      },
      (err) => alert(`Location error: ${err.message}`),
      { enableHighAccuracy: true }
    );
  };

  const handleOpenMap = () => {
    setShowSplash(false);
    setMapReady(false);
    setShowMapView(true);
    setTimeout(() => {
      mapRef.current?.invalidateSize();
    }, 200);
  };

  const handleOpenMapWithIncident = (inc?: IncidentRecord) => {
    if (inc) {
      setMapFocusTarget({ lat: inc.lat, lon: inc.lon, zoom: 15, title: inc.title });
      selectIncident(inc);
    }
    setShowSplash(false);
    setMapReady(false);
    setShowMapView(true);
    setTimeout(() => {
      mapRef.current?.invalidateSize();
      if (inc && mapRef.current) {
        mapRef.current.flyTo([inc.lat, inc.lon], 15, { duration: 1.5 });
      }
    }, 200);
  };

  const handleOpenMapWithTarget = (target?: { lat: number; lon: number; title: string }) => {
    if (target) {
      setMapFocusTarget({ lat: target.lat, lon: target.lon, zoom: 15, title: target.title });
    }
    setShowSplash(false);
    setMapReady(false);
    setShowMapView(true);
    setTimeout(() => {
      mapRef.current?.invalidateSize();
      if (target && mapRef.current) {
        mapRef.current.flyTo([target.lat, target.lon], 15, { duration: 1.5 });
      }
    }, 200);
  };

  if (!showMapView) {
    return (
      <CommandDashboard
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        incidents={incidents}
        responders={responders}
        dispatches={dispatches}
        unreadAlertCount={unreadAlertCount}
        onMap={handleOpenMap}
        onMapWithIncident={handleOpenMapWithIncident}
        onMapWithTarget={handleOpenMapWithTarget}
        onReport={() => setShowCitizenReport(true)}
        onAlerts={() => setShowAlertsDrawer(true)}
        onSelectIncident={(incident) => selectIncident(incident)}
        showCitizenReport={showCitizenReport}
        showRoleWorkspace={showRoleWorkspace}
        showAlertsDrawer={showAlertsDrawer}
        showAnalytics={showAnalytics}
        showDispatchModal={showDispatchModal}
        dispatchIncident={dispatchIncident}
        onCloseReport={() => setShowCitizenReport(false)}
        onCloseWorkspace={() => setShowRoleWorkspace(false)}
        onCloseAlerts={() => setShowAlertsDrawer(false)}
        onCloseAnalytics={() => setShowAnalytics(false)}
        onCloseDispatch={() => {
          setShowDispatchModal(false);
          setDispatchIncident(null);
        }}
        onOpenDispatch={(incident) => {
          setDispatchIncident(incident);
          setShowDispatchModal(true);
        }}
      />
    );
  }

  // Post-login Citizen experience: Functionality-first, no full-screen map background
  if (isAuthenticated && roleCategory === "user" && !citizenViewPublicMap) {
    return (
      <>
        <CitizenDashboardView
          onOpenCitizenReport={() => setShowCitizenReport(true)}
          onViewPublicMap={() => setCitizenViewPublicMap(true)}
          onSignOut={() => logout()}
        />
        {showCitizenReport && (
          <CitizenReportModal
            isOpen={showCitizenReport}
            onClose={() => setShowCitizenReport(false)}
          />
        )}
      </>
    );
  }

  return (
    <div className="relative w-screen h-screen overflow-hidden select-none font-sans bg-slate-900 text-slate-800">

      {/* ============ SPLASH SCREEN ============ */}
      {showSplash && (
        <div
          className="fixed inset-0 z-[9999] flex flex-col items-center justify-center pointer-events-none"
          style={{
            background: "linear-gradient(135deg, #020d1a 0%, #0c2340 40%, #0c4a75 70%, #0369a1 100%)",
            transition: splashFading ? "opacity 0.8s ease-out, transform 0.8s ease-out" : "none",
            opacity: splashFading ? 0 : 1,
            transform: splashFading ? "scale(1.04)" : "scale(1)",
            pointerEvents: "none",
          }}
          onTransitionEnd={() => {
            if (splashFading) setShowSplash(false);
          }}
        >
          {/* Animated glowing rings */}
          <div className="absolute inset-0 overflow-hidden pointer-events-none">
            <div style={{
              position: "absolute", top: "50%", left: "50%",
              transform: "translate(-50%, -50%)",
              width: 700, height: 700,
              borderRadius: "50%",
              border: "1.5px solid rgba(56,189,248,0.12)",
              animation: "splashRing 4s ease-in-out infinite",
            }} />
            <div style={{
              position: "absolute", top: "50%", left: "50%",
              transform: "translate(-50%, -50%)",
              width: 500, height: 500,
              borderRadius: "50%",
              border: "1.5px solid rgba(56,189,248,0.18)",
              animation: "splashRing 3s ease-in-out infinite 0.5s",
            }} />
            <div style={{
              position: "absolute", top: "50%", left: "50%",
              transform: "translate(-50%, -50%)",
              width: 320, height: 320,
              borderRadius: "50%",
              border: "1.5px solid rgba(56,189,248,0.25)",
              animation: "splashRing 2.5s ease-in-out infinite 1s",
            }} />
          </div>

          {/* Main content */}
          <div
            style={{
              display: "flex", flexDirection: "column", alignItems: "center", gap: 24,
              animation: "splashFadeUp 0.9s cubic-bezier(0.22,1,0.36,1) both",
            }}
          >
            {/* Shield logo */}
            <div style={{
              width: 100, height: 100, borderRadius: "50%",
              background: "radial-gradient(circle at 35% 35%, #38bdf8, #0369a1 70%)",
              border: "3px solid rgba(255,255,255,0.25)",
              boxShadow: "0 0 60px rgba(56,189,248,0.5), 0 0 120px rgba(56,189,248,0.2)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 48,
              animation: "splashPulse 2s ease-in-out infinite",
            }}>🛡️</div>

            {/* Brand */}
            <div style={{ textAlign: "center" }}>
              <div style={{
                fontSize: 52, fontWeight: 900, letterSpacing: "-2px",
                color: "#ffffff",
                lineHeight: 1,
                textShadow: "0 0 40px rgba(56,189,248,0.6)",
              }}>ResQ</div>
              <div style={{
                fontSize: 18, fontWeight: 300, letterSpacing: 8,
                color: "#7dd3fc",
                textTransform: "uppercase",
                marginTop: 4,
              }}>GeoPlatform</div>
              <div style={{
                fontSize: 12, fontWeight: 500, letterSpacing: 2,
                color: "rgba(186,230,253,0.7)",
                textTransform: "uppercase",
                marginTop: 10,
                padding: "5px 16px",
                border: "1px solid rgba(56,189,248,0.25)",
                borderRadius: 999,
                background: "rgba(56,189,248,0.08)",
              }}>NDMA Incident Triage &amp; GIS Coordination</div>
            </div>

            {/* Loading bar */}
            <div style={{
              width: 240, height: 3, borderRadius: 99,
              background: "rgba(56,189,248,0.15)",
              overflow: "hidden",
              marginTop: 12,
            }}>
              <div style={{
                height: "100%",
                background: "linear-gradient(90deg, #38bdf8, #0ea5e9, #38bdf8)",
                backgroundSize: "200% 100%",
                borderRadius: 99,
                animation: "splashLoader 2.2s ease-in-out forwards, splashLoaderShimmer 1.5s linear infinite",
              }} />
            </div>

            {/* Tagline */}
            <div style={{
              fontSize: 12, color: "rgba(148,163,184,0.8)",
              fontStyle: "italic",
              animation: "splashFadeUp 1.2s 0.3s cubic-bezier(0.22,1,0.36,1) both",
            }}>Initializing emergency operations dashboard&hellip;</div>
          </div>

          {/* Splash keyframes via style tag */}
          <style>{`
            @keyframes splashRing {
              0%, 100% { opacity: 0.3; transform: translate(-50%,-50%) scale(1); }
              50% { opacity: 0.7; transform: translate(-50%,-50%) scale(1.04); }
            }
            @keyframes splashFadeUp {
              from { opacity: 0; transform: translateY(28px); }
              to { opacity: 1; transform: translateY(0); }
            }
            @keyframes splashPulse {
              0%, 100% { box-shadow: 0 0 60px rgba(56,189,248,0.5), 0 0 120px rgba(56,189,248,0.2); }
              50% { box-shadow: 0 0 90px rgba(56,189,248,0.8), 0 0 180px rgba(56,189,248,0.35); }
            }
            @keyframes splashLoader {
              from { width: 0%; }
              to { width: 100%; }
            }
            @keyframes splashLoaderShimmer {
              0% { background-position: 200% 0; }
              100% { background-position: -200% 0; }
            }
            @keyframes fadeInUp {
              from { opacity: 0; transform: translateY(16px); }
              to { opacity: 1; transform: translateY(0); }
            }
          `}</style>
        </div>
      )}
      {/* ============ HEADER (Clean Whitish Unified Navbar) ============ */}
      <header className="fixed top-3 left-3 right-3 h-12 z-[1000] rounded-2xl bg-white/95 backdrop-blur-md flex items-center justify-between px-3.5 text-slate-800 shadow-md border border-slate-200/90">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => mapRef.current?.flyTo([23.5, 80.5], 5, { duration: 3, easeLinearity: 0.22 })}
            className="flex h-8 w-8 items-center justify-center rounded-xl border border-sky-300 text-base shadow-sm transition-transform hover:scale-105 cursor-pointer"
            style={{
              background: "radial-gradient(circle at 35% 35%, #38bdf8, #0369a1 70%)",
            }}
            title="Center map on India"
            aria-label="Center map on India"
          >
            🛡️
          </button>

          <div>
            <div className="flex items-baseline gap-1.5 leading-tight">
              <span className="text-[17px] font-extrabold tracking-tight text-[#07569c]">ResQ</span>
              <span className="text-[11px] font-semibold tracking-wide text-slate-500">Operations</span>
            </div>
          </div>
        </div>

        <nav className="flex items-center gap-2">
          <button
            onClick={() => {
              setShowMapView(false);
              setShowDashboard(false);
            }}
            className="flex items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-[#07569c] transition hover:bg-sky-100 cursor-pointer pointer-events-auto shadow-xs"
            title="Return to the command dashboard"
          >
            <span aria-hidden>▦</span>
            <span>‹ Back to Dashboard</span>
          </button>
          {/* Role-specific dashboard panel */}
          <button
            onClick={() => setShowDashboard((prev) => !prev)}
            className={`hidden md:flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full border transition cursor-pointer ${showDashboard
              ? "bg-sky-500/30 border-sky-400/60 text-sky-200"
              : "bg-slate-900/60 border-slate-700/60 text-slate-300 hover:text-white hover:border-sky-600/50"
              }`}
            title="Toggle role-specific dashboard panel"
          >
            <span>📊</span>
            <span>My workspace</span>
          </button>
          <Link
            href="/report"
            className="flex items-center gap-1.5 rounded-lg bg-red-600 hover:bg-red-500 px-3 py-1.5 text-xs font-bold text-white shadow-xs transition"
            title="File an emergency disaster report"
          >
            <span>🚨</span>
            <span>Report Incident</span>
          </Link>
          <Link
            href="/my-reports"
            className="hidden sm:flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 hover:bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700 transition"
            title="View status of my reported incidents"
          >
            <span>📋</span>
            <span>My Reports</span>
          </Link>
          {!isAuthenticated ? (
            <Link
              href="/login"
              className="flex items-center gap-1.5 rounded-lg bg-[#07569c] hover:bg-[#064782] px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition"
              title="Sign In to Staff or Citizen Portal"
            >
              <span>🔐</span>
              <span>Sign In</span>
            </Link>
          ) : (
            /* Unified Role Display & Switcher Dropdown */
            <div className="relative">
              <button
                onClick={() => {
                  if (roleCategory === "user") {
                    setCitizenViewPublicMap(false);
                  } else {
                    setShowRoleWorkspace(true);
                  }
                }}
                className={`bg-slate-900/90 hover:bg-slate-900 border px-3 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 shadow-sm transition ${roleCategory === "user"
                  ? "border-sky-500/70 text-sky-200"
                  : roleCategory === "admin"
                    ? "border-blue-500/70 text-blue-200"
                    : "border-amber-500/70 text-amber-200"
                  }`}
                title="Open Operational Role Workspace"
              >
                <span
                  className={`w-2 h-2 rounded-full ${roleCategory === "user"
                    ? "bg-sky-400"
                    : roleCategory === "admin"
                      ? "bg-blue-400 animate-pulse"
                      : "bg-amber-400 animate-pulse"
                    }`}
                />
                <span className="font-semibold text-slate-800">
                  {roleCategory === "user"
                    ? "Citizen"
                    : roleCategory === "admin"
                    ? "Command HQ"
                    : "Field Responder"}
                </span>
                <span className="text-[11px] text-slate-500 font-normal hidden md:inline">
                  ({currentUser.name.split(" ")[0]}
                  {currentUser.assignedUnitCallsign ? ` • ${currentUser.assignedUnitCallsign}` : ""})
                </span>
                <span className="text-[9px] text-slate-400 ml-0.5">▼</span>
              </button>

              {showRoleMenu && (
                <div className="absolute right-0 mt-2 w-64 bg-white border border-slate-200 rounded-xl shadow-xl p-2 z-[1100] text-xs space-y-1 text-slate-700">
                  <div className="px-2.5 py-1 text-[10px] text-slate-400 font-bold uppercase tracking-wider border-b border-slate-100 flex items-center justify-between">
                    <span>Select Operational Role</span>
                    <span className="text-[9px] text-sky-600 font-medium">Active: {roleCategory}</span>
                  </div>

                  <button
                    onClick={() => {
                      switchRole("Public / Citizen");
                      setShowRoleMenu(false);
                    }}
                    className={`w-full text-left px-2.5 py-2 rounded-lg flex items-center justify-between transition cursor-pointer ${
                      roleCategory === "user"
                        ? "bg-sky-50 text-[#07569c] font-semibold"
                        : "hover:bg-slate-50 text-slate-700"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span>👤</span> Citizen / Public
                    </span>
                    {roleCategory === "user" && <span className="text-[10px] text-sky-600 font-bold">✓ Active</span>}
                  </button>

                  <button
                    onClick={() => {
                      switchRole("Command Officer / Incident Commander");
                      setShowRoleMenu(false);
                    }}
                    className={`w-full text-left px-2.5 py-2 rounded-lg flex items-center justify-between transition cursor-pointer ${
                      roleCategory === "admin"
                        ? "bg-sky-50 text-[#07569c] font-semibold"
                        : "hover:bg-slate-50 text-slate-700"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span>🛡️</span> Incident Commander (Admin)
                    </span>
                    {roleCategory === "admin" && <span className="text-[10px] text-sky-600 font-bold">✓ Active</span>}
                  </button>

                  <button
                    onClick={() => {
                      switchRole("Medic / Ambulance Team");
                      setShowRoleMenu(false);
                    }}
                    className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-slate-50 text-slate-700 flex items-center justify-between transition cursor-pointer"
                  >
                    <span className="flex items-center gap-2">
                      <span>🚑</span> Paramedic Medic
                    </span>
                  </button>

                  <button
                    onClick={() => {
                      switchRole("Firefighter / Fire Service Officer");
                      setShowRoleMenu(false);
                    }}
                    className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-slate-50 text-slate-700 flex items-center justify-between transition cursor-pointer"
                  >
                    <span className="flex items-center gap-2">
                      <span>🚒</span> Firefighter
                    </span>
                  </button>

                  <button
                    onClick={() => {
                      switchRole("NDRF / SDRF Team Leader or Responder");
                      setShowRoleMenu(false);
                    }}
                    className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-slate-50 text-slate-700 flex items-center justify-between transition cursor-pointer"
                  >
                    <span className="flex items-center gap-2">
                      <span>🚤</span> NDRF Rescue
                    </span>
                  </button>

                  <div className="pt-1.5 border-t border-slate-100 space-y-1">
                    <Link
                      href="/login"
                      onClick={() => setShowRoleMenu(false)}
                      className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-sky-50 text-[#07569c] flex items-center gap-2 transition cursor-pointer font-medium"
                    >
                      <span>🔐</span> Staff &amp; Citizen Sign In (/login)
                    </Link>

                    <button
                      onClick={() => {
                        setShowRoleWorkspace(true);
                        setShowRoleMenu(false);
                      }}
                      className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-sky-50 text-[#07569c] flex items-center gap-2 transition cursor-pointer font-medium"
                    >
                      <span>📋</span> Open Role Workspace
                    </button>

                    <button
                      onClick={() => {
                        logout();
                        setShowRoleMenu(false);
                      }}
                      className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-red-50 text-red-600 flex items-center gap-2 transition cursor-pointer font-semibold"
                    >
                      <span>🚪</span> Sign Out
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Emergency SOS Distress Intake (Single button) */}
          <button
            onClick={() => setShowCitizenReport(true)}
            className="flex items-center gap-1.5 bg-red-600 hover:bg-red-700 text-white text-xs font-bold px-3 py-1.5 rounded-lg cursor-pointer transition shadow-xs"
            title="Citizen Distress & SOS Reporting"
          >
            <span className="inline-block w-2 h-2 rounded-full bg-white animate-ping" />
            <span>REPORT SOS</span>
          </button>

          {/* Notifications Bell (Single) */}
          <button
            onClick={() => setShowAlertsDrawer(true)}
            aria-label={`Open alerts${unreadAlertCount ? `, ${unreadAlertCount} unread` : ""}`}
            className="relative grid size-8 place-items-center rounded-lg border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 transition cursor-pointer shadow-xs"
            title="Open Emergency Alerts"
          >
            <span className="text-sm">🔔</span>
            {unreadAlertCount > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-600 text-white text-[9px] font-bold rounded-full size-4 flex items-center justify-center shadow-xs">
                {unreadAlertCount}
              </span>
            )}
          </button>

          {/* Language Selector */}
          <select
            value={selectedLang}
            onChange={(e) => setSelectedLang(e.target.value)}
            className="border border-slate-200 bg-white text-slate-700 rounded-lg px-2 py-1 text-xs font-medium cursor-pointer shadow-xs outline-none hidden sm:block hover:border-slate-300"
          >
            <option>English</option>
            <option>हिन्दी</option>
            <option>বাংলা</option>
            <option>தமிழ்</option>
            <option>తెలుగు</option>
            <option>मराठी</option>
          </select>
        </nav>
      </header>

      {/* ============ RETURN TO CITIZEN DASHBOARD (When citizen views public map) ============ */}
      {isAuthenticated && roleCategory === "user" && citizenViewPublicMap && (
        <div className="fixed top-14 left-1/2 -translate-x-1/2 z-[1100] bg-[#0c4a75] border border-sky-400 text-white px-4 py-1.5 rounded-full shadow-2xl flex items-center gap-3 text-xs animate-fadeIn">
          <span>🗺️ Viewing National Bhuvan Map</span>
          <button
            onClick={() => setCitizenViewPublicMap(false)}
            className="bg-sky-500 hover:bg-sky-400 text-white font-bold px-3 py-0.5 rounded-full text-xs transition cursor-pointer shadow-xs"
          >
            ← Back to Citizen Dashboard
          </button>
        </div>
      )}

      {/* ============ SEARCH PANEL ============ */}
      <button
        onClick={() => setShowNavDrawer(true)}
        aria-label="Open navigation sidebar"
        title="Open navigation"
        className="fixed left-0 top-1/2 z-[1050] grid h-12 w-7 -translate-y-1/2 place-items-center rounded-r-lg border border-l-0 border-sky-200 bg-white/95 text-lg font-semibold text-[#07569c] shadow-lg transition hover:w-9 hover:bg-white cursor-pointer pointer-events-auto"
      >
        ›
      </button>
      <div className="fixed left-4 top-[72px] z-[900] flex items-center overflow-hidden rounded-xl border border-slate-200/80 bg-white/95 shadow-lg backdrop-blur-sm">
        <form onSubmit={handleSearch} className="flex items-center">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search city, district, village, or coordinates..."
            className="w-52 sm:w-72 px-2 py-2.5 text-sm text-slate-800 placeholder-slate-400 outline-none bg-transparent"
          />
          <button
            type="submit"
            disabled={isSearching}
            title="Search Real Location"
            className="p-2.5 text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors text-sm cursor-pointer"
          >
            {isSearching ? "⏳" : "🔍"}
          </button>
        </form>

        <button
          onClick={() => setShowLayerMenu(!showLayerMenu)}
          title="Choose map layer"
          aria-label="Choose map layer"
          className={`p-2.5 px-3 transition-colors text-sm font-bold cursor-pointer ${showLayerMenu ? "bg-sky-100 text-[#0c4a75]" : "text-[#0c4a75] hover:bg-slate-100"
            }`}
        >
          ◆
        </button>
      </div>

      {/* ============ BASEMAP SWITCHER ============ */}
      {showLayerMenu && (
        <div className="fixed top-[110px] left-3 z-[1050] w-84 bg-white rounded-xl shadow-2xl border border-slate-200 p-3.5 animate-fadeIn">
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-100">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-slate-700 block">Basemap Views</span>
              <span className="text-[10px] text-sky-600 font-medium">Deep Zoom Supported (Up to 21x)</span>
            </div>
            <button
              onClick={() => setShowLayerMenu(false)}
              className="text-slate-400 hover:text-slate-600 text-sm font-bold cursor-pointer"
            >
              ✕
            </button>
          </div>

          <div className="text-xs font-semibold text-slate-500 mb-1.5">CHOOSE BASEMAP</div>
          <div className="space-y-1 mb-3">
            {Object.entries(TILE_LAYERS).map(([key, config]) => (
              <button
                key={key}
                onClick={() => switchBaseLayer(key as keyof typeof TILE_LAYERS)}
                className={`w-full text-left px-2.5 py-2 rounded text-xs flex items-center justify-between transition-colors cursor-pointer ${currentBaseLayer === key
                  ? "bg-sky-50 text-[#0c4a75] font-semibold border border-sky-200"
                  : "hover:bg-slate-50 text-slate-700"
                  }`}
              >
                <span>{config.name}</span>
                {currentBaseLayer === key && <span className="text-sky-600 font-bold">✓</span>}
              </button>
            ))}
          </div>

          <div className="text-xs font-semibold text-slate-500 mb-1.5">STREET DETAIL OVERLAYS</div>
          <div className="space-y-1">
            <label className="flex items-center justify-between p-1.5 rounded hover:bg-slate-50 cursor-pointer text-xs">
              <span className="flex items-center gap-1.5 font-medium text-slate-700">
                <span>🏷️</span> Keep Street & Road Names Visible
              </span>
              <input
                type="checkbox"
                checked={streetOverlayActive}
                onChange={toggleStreetOverlay}
                className="rounded text-sky-600 w-4 h-4 cursor-pointer"
              />
            </label>
          </div>
        </div>
      )}

      {/* ============ MAP CANVAS ============ */}
      <div id="map" ref={mapContainerRef} className="fixed inset-0 bg-[#b6b6b6]" />

      {/* Measurement Status */}
      {isMeasuring && (
        <div className="fixed top-[60px] left-1/2 -translate-x-1/2 z-[1050] bg-blue-900/90 text-white backdrop-blur px-4 py-1.5 rounded-full shadow-lg border border-blue-400/40 text-xs flex items-center gap-3">
          <span>📏 <b>Measuring:</b> {measureDistance}</span>
          <button
            onClick={toggleMeasurement}
            className="bg-blue-600 hover:bg-blue-500 px-2.5 py-0.5 rounded text-[11px] font-semibold cursor-pointer"
          >
            Done
          </button>
        </div>
      )}

      {/* ============ MAP TOOLS ============ */}
      <div className="fixed right-4 top-1/2 z-[1050] flex -translate-y-1/2 flex-col gap-1 rounded-xl border border-slate-200/80 bg-white/95 p-1 shadow-lg backdrop-blur pointer-events-auto">
        <button
          onClick={() => mapRef.current?.zoomIn(1, { animate: true })}
          title="Zoom In"
          aria-label="Zoom in"
          className="grid size-9 place-items-center rounded-lg text-lg font-semibold text-slate-700 transition hover:bg-slate-100 cursor-pointer"
        >
          ＋
        </button>
        <button
          onClick={() => mapRef.current?.zoomOut(1, { animate: true })}
          title="Zoom Out"
          aria-label="Zoom out"
          className="grid size-9 place-items-center rounded-lg text-lg font-semibold text-slate-700 transition hover:bg-slate-100 cursor-pointer"
        >
          －
        </button>
        <button
          onClick={handleLocateMe}
          title="My Location"
          aria-label="Show my location"
          className="grid size-9 place-items-center rounded-lg text-base text-slate-700 transition hover:bg-slate-100 cursor-pointer"
        >
          📍
        </button>
      </div>


      {/* ============ BOTTOM STATUS & AREA ============ */}
      <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-[900] hidden sm:flex items-center gap-2 bg-slate-950/85 backdrop-blur text-white text-[11px] px-3 py-1.5 rounded-full shadow-xl border border-white/10 pointer-events-none">
        <div className="flex items-center gap-1.5 text-sky-300 font-semibold">
          <span>📍 Viewing:</span>
          <span className="text-white font-normal truncate max-w-xs sm:max-w-md">{visibleAreaName}</span>
          <span className="text-[10.5px] text-sky-400 font-mono">[{currentZoom}x Zoom]</span>
        </div>
        <div className="hidden sm:block w-[1px] h-3.5 bg-slate-600 mx-1" />
        <div className="font-mono text-slate-300 text-[11px]">{coordsText}</div>
      </div>

      {/* ============ ABOUT RESQ MODAL ============ */}
      {showAboutModal && (
        <div className="fixed inset-0 z-[2000] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 shadow-2xl border border-slate-200 relative animate-scaleUp">
            <button
              onClick={() => setShowAboutModal(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-700 text-lg font-bold cursor-pointer"
            >
              ✕
            </button>

            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-full bg-linear-to-tr from-[#0284c7] to-[#38bdf8] flex items-center justify-center text-2xl border-2 border-white shadow">
                🛡️
              </div>
              <div>
                <h2 className="text-xl font-bold text-slate-900 leading-tight">
                  ResQ GeoPlatform
                </h2>
                <p className="text-xs text-sky-700 font-medium">
                  NDMA Incident Triage & GIS Coordination
                </p>
              </div>
            </div>

            <div className="space-y-3 text-sm text-slate-600 leading-relaxed border-t border-slate-100 pt-3">
              <p>
                <b>ResQ</b> provides operational emergency response across 8 operational agency roles, compliant with the National Disaster Management Authority (NDMA) Incident Response System (IRS).
              </p>
              <div className="bg-sky-50 border border-sky-200 rounded-lg p-3 text-xs text-sky-950 space-y-1">
                <p className="font-semibold text-sky-900 mb-1">🗺️ Supported Disasters:</p>
                <div>• <b>Flood / Urban Flood:</b> Inundation modeling, boat rescue deployment.</div>
                <div>• <b>Cyclone / Coastal Flooding:</b> Surge tracking, storm shelters, evacuation.</div>
                <div>• <b>Major Urban / Building Fire:</b> Smoke plume assessment, hydrants, hazmat.</div>
              </div>
            </div>

            <div className="mt-5 flex justify-end">
              <button
                onClick={() => setShowAboutModal(false)}
                className="bg-[#0c4a75] hover:bg-[#083452] text-white px-4 py-2 rounded-lg text-xs font-semibold shadow transition-colors cursor-pointer"
              >
                Close Info
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ============ NAVIGATION DRAWER ============ */}
      {showNavDrawer && (
        <div className="fixed inset-0 z-[2000] bg-black/50 backdrop-blur-xs flex">
          <div className="bg-white w-80 max-w-full h-full shadow-2xl p-5 flex flex-col justify-between overflow-y-auto">
            <div>
              <div className="flex items-center justify-between pb-4 border-b border-slate-200 mb-4">
                <div className="flex items-center gap-2">
                  <span className="text-2xl">🛡️</span>
                  <div>
                    <h3 className="font-bold text-slate-900 text-base leading-none">ResQ Hub</h3>
                    <span className="text-[11px] text-slate-500">Emergency Operations</span>
                  </div>
                </div>
                <button
                  onClick={() => setShowNavDrawer(false)}
                  aria-label="Close navigation sidebar"
                  title="Close navigation"
                  className="grid size-9 place-items-center rounded-lg bg-sky-50 text-lg font-bold text-[#07569c] transition hover:bg-sky-100"
                >
                  ‹
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">Navigate</h4>
                  <div className="space-y-1 text-sm">
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowDashboard(false);
                        setShowMapView(false);
                        setActiveTab("dashboard");
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100 flex items-center gap-2"
                    >
                      <span aria-hidden className="text-[#07569c]">▦</span> Home dashboard
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowDashboard(false);
                        setShowMapView(false);
                        setActiveTab("incidents");
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100 flex items-center gap-2"
                    >
                      <span aria-hidden className="text-blue-600">◉</span> Live incidents
                    </button>
                    <div aria-current="page" className="w-full rounded-lg bg-sky-50 px-3 py-2 font-semibold text-[#07569c] flex items-center gap-2">
                      <span aria-hidden>⌖</span> Incident map
                    </div>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowDashboard(false);
                        setShowMapView(false);
                        setActiveTab("dispatch");
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100 flex items-center gap-2"
                    >
                      <span aria-hidden className="text-amber-600">➤</span> Dispatch center
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowDashboard(false);
                        setShowMapView(false);
                        setActiveTab("responders");
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100 flex items-center gap-2"
                    >
                      <span aria-hidden className="text-purple-600">♙</span> Responders
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowDashboard(false);
                        setShowMapView(false);
                        setActiveTab("resources");
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100 flex items-center gap-2"
                    >
                      <span aria-hidden className="text-emerald-600">📦</span> Resources &amp; Inventory
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowDashboard(false);
                        setShowMapView(false);
                        setActiveTab("analytics");
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100 flex items-center gap-2"
                    >
                      <span aria-hidden className="text-indigo-600">▥</span> Analytics &amp; reports
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowAlertsDrawer(true);
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100 flex items-center justify-between"
                    >
                      <span className="flex items-center gap-2">
                        <span aria-hidden className="text-red-500">♧</span> Alerts
                      </span>
                      {unreadAlertCount > 0 && (
                        <span className="rounded-full bg-red-50 px-2 text-xs font-bold text-red-600">
                          {unreadAlertCount}
                        </span>
                      )}
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        setShowCitizenReport(true);
                      }}
                      className="w-full cursor-pointer rounded-lg px-3 py-2 text-left font-semibold text-red-700 transition-colors hover:bg-red-50 flex items-center gap-2"
                    >
                      <span aria-hidden>!</span> Report an emergency
                    </button>

                  </div>
                </div>
                <details className="rounded-lg border border-slate-200 px-3 py-2">
                  <summary className="cursor-pointer list-none text-xs font-semibold text-slate-600">Switch operational role</summary>
                  <div className="space-y-1.5 text-sm">
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        switchRole("Command Officer / Incident Commander");
                        setShowRoleWorkspace(true);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 flex items-center gap-2.5 text-slate-700 transition-colors cursor-pointer"
                    >
                      <span>🎖️</span> Command Officer / Commander
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        switchRole("Dispatcher");
                        setShowRoleWorkspace(true);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 flex items-center gap-2.5 text-slate-700 transition-colors cursor-pointer"
                    >
                      <span>🗺️</span> Dispatcher & Report Queue
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        switchRole("NDRF / SDRF Team Leader or Responder");
                        setShowRoleWorkspace(true);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 flex items-center gap-2.5 text-slate-700 transition-colors cursor-pointer"
                    >
                      <span>🚤</span> NDRF / SDRF Search & Rescue
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        switchRole("Medic / Ambulance Team");
                        setShowRoleWorkspace(true);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 flex items-center gap-2.5 text-slate-700 transition-colors cursor-pointer"
                    >
                      <span>🚑</span> Field Medic & Hospital Triage
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        switchRole("Firefighter / Fire Service Officer");
                        setShowRoleWorkspace(true);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 flex items-center gap-2.5 text-slate-700 transition-colors cursor-pointer"
                    >
                      <span>🚒</span> Firefighter & Water Hydrants
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        switchRole("Logistics Officer");
                        setShowRoleWorkspace(true);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 flex items-center gap-2.5 text-slate-700 transition-colors cursor-pointer"
                    >
                      <span>📦</span> Logistics & Warehouse Supplies
                    </button>
                    <button
                      onClick={() => {
                        setShowNavDrawer(false);
                        switchRole("System Administrator");
                        setShowRoleWorkspace(true);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 flex items-center gap-2.5 text-slate-700 transition-colors cursor-pointer"
                    >
                      <span>⚙️</span> System Admin & Audit Logs
                    </button>
                  </div>
                </details>
              </div>
            </div>

            <div className="space-y-4 border-t border-slate-200 pt-4 text-xs text-slate-500">
              {isAuthenticated ? (
                <div>
                  <p className="font-semibold text-slate-800">{currentUser.name}</p>
                  <p className="mt-0.5">{currentUser.agency}</p>
                  <button onClick={() => { logout(); setShowNavDrawer(false); }} className="mt-2 font-semibold text-red-600 hover:text-red-700">Sign out</button>
                </div>
              ) : (
                <button onClick={() => { setShowNavDrawer(false); setAuthModalMode("login"); setShowAuthModal(true); }} className="font-semibold text-[#07569c] hover:underline">Sign in to your account</button>
              )}
              <div className="font-semibold text-slate-700 mb-1">Emergency Helplines (India):</div>
              <div>• National Emergency: <b>112</b></div>
              <div>• Disaster Management (NDMA): <b>1070 / 1077</b></div>
              <div>• Ambulance Service: <b>108</b></div>
            </div>
          </div>
          <div className="flex-1" onClick={() => setShowNavDrawer(false)} />
        </div>
      )}

      {/* Disaster Management: real incidents from the operations database (DM staff only) */}
      <LiveOperationsLayer mapRef={mapRef} />

      {/* ============ CITIZEN REPORT MODAL ============ */}
      <CitizenReportModal
        isOpen={showCitizenReport}
        onClose={() => setShowCitizenReport(false)}
      />

      {/* ============ INCIDENT DETAIL & COMMAND PANEL ============ */}
      <IncidentDetailPanel
        incident={selectedIncident}
        onClose={() => selectIncident(null)}
        onOpenDispatch={(incidentId: string) => {
          const inc = incidents.find((i) => i.id === incidentId) || selectedIncident;
          setDispatchIncident(inc);
          setShowDispatchModal(true);
        }}
      />

      {/* ============ DISPATCH MODAL ============ */}
      <DispatchModal
        incident={dispatchIncident}
        isOpen={showDispatchModal}
        onClose={() => {
          setShowDispatchModal(false);
          setDispatchIncident(null);
        }}
      />

      {/* ============ ROLE CONTEXTUAL WORKSPACE ============ */}
      <RoleWorkspaceModal
        isOpen={showRoleWorkspace}
        onClose={() => setShowRoleWorkspace(false)}
        onOpenCitizenReport={() => setShowCitizenReport(true)}
        onOpenDispatch={(inc) => {
          setDispatchIncident(inc);
          setShowDispatchModal(true);
        }}
      />

      {/* ============ ALERTS DRAWER ============ */}
      <AlertsDrawer
        isOpen={showAlertsDrawer}
        onClose={() => setShowAlertsDrawer(false)}
      />

      {/* ============ ANALYTICS MODAL ============ */}
      <AnalyticsModal
        isOpen={showAnalytics}
        onClose={() => setShowAnalytics(false)}
      />

      {/* ============ 12-STEP SIMULATION CONTROLLER ============ */}
      <SimulationBar
        isOpen={showSimulationBar}
        onClose={() => setShowSimulationBar(false)}
      />

      {/* ============ DYNAMIC ROLE-BASED DASHBOARD VIEWS ============ */}
      {/* Only show when user explicitly opens via nav Dashboard button */}
      {showDashboard && !isAuthenticated && (
        <GeneralPublicDashboardView
          onOpenAuth={() => {
            setAuthModalMode("login");
            setShowAuthModal(true);
          }}
          onOpenCitizenReport={() => setShowCitizenReport(true)}
          onClose={() => setShowDashboard(false)}
        />
      )}

      {showDashboard && isAuthenticated && roleCategory === "user" && (
        <CitizenDashboardView
          onOpenCitizenReport={() => setShowCitizenReport(true)}
          onClose={() => setShowDashboard(false)}
        />
      )}

      {showDashboard && isAuthenticated && roleCategory === "admin" && (
        <AdminDashboardView
          onOpenWorkspace={() => setShowRoleWorkspace(true)}
          onOpenDispatch={(inc) => {
            setDispatchIncident(inc);
            setShowDispatchModal(true);
          }}
          onOpenSimulation={() => setShowSimulationBar(true)}
          onOpenAnalytics={() => setShowAnalytics(true)}
          onClose={() => setShowDashboard(false)}
        />
      )}

      {showDashboard && isAuthenticated && roleCategory === "service_provider" && (
        <ServiceProviderDashboardView
          onOpenWorkspace={() => setShowRoleWorkspace(true)}
          onClose={() => setShowDashboard(false)}
        />
      )}

      {/* ============ AUTHENTICATION MODAL ============ */}
      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        initialMode={authModalMode}
        initialRoleCategory={authModalCategory}
      />
    </div>
  );
}

export default function ResQGeoPortal() {
  return (
    <ResQProvider>
      <ResQGeoPortalInner />
    </ResQProvider>
  );
}
