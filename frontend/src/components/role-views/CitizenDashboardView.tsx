"use client";

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { UnifiedSiteHeader } from "../navigation/UnifiedSiteHeader";
import { InformationRequestReply } from "@/components/citizen/InformationRequestReply";
import * as CitizenApi from "../../services/citizenApi";
import { LanguageCode, TRANSLATIONS } from "@/lib/citizenI18n";
import { isInGujarat } from "@/lib/geo";

interface CitizenDashboardViewProps {
  currentUser?: { id: string; name: string; phone?: string; email?: string } | null;
  onOpenCitizenReport?: () => void;
  onSignOut?: () => void;
  onClose?: () => void;
}

type CitizenTabId = "overview" | "reports" | "safety";

function statusBadge(status: string) {
  switch (status) {
    case "VERIFIED":
      return { label: "Verified", bg: "bg-emerald-50 text-emerald-700 border-emerald-200" };
    case "LINKED_TO_INCIDENT":
      return { label: "Help Dispatched", bg: "bg-sky-50 text-sky-700 border-sky-200" };
    case "PENDING":
    case "SUBMITTED":
      return { label: "Under Review", bg: "bg-amber-50 text-amber-700 border-amber-200" };
    case "NEEDS_INFORMATION":
      return { label: "Info Requested", bg: "bg-orange-50 text-orange-700 border-orange-300" };
    case "NEEDS_FIELD_CHECK":
      return { label: "Field Check", bg: "bg-purple-50 text-purple-700 border-purple-200" };
    case "REJECTED":
      return { label: "Rejected", bg: "bg-red-50 text-red-700 border-red-200" };
    default:
      return { label: status, bg: "bg-slate-50 text-slate-700 border-slate-200" };
  }
}

function severityBadge(sev: string) {
  switch (sev) {
    case "CRITICAL":
      return "bg-red-100 text-red-800 border-red-200 font-bold";
    case "HIGH":
      return "bg-orange-100 text-orange-800 border-orange-200 font-semibold";
    case "MODERATE":
    case "WARNING":
      return "bg-amber-100 text-amber-800 border-amber-200 font-medium";
    default:
      return "bg-sky-100 text-sky-800 border-sky-200 font-medium";
  }
}

function formatRelativeTime(dateStr: string) {
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return dateStr;
  }
}

export const CitizenDashboardView: React.FC<CitizenDashboardViewProps> = ({
  currentUser: propUser,
  onOpenCitizenReport,
  onClose,
}) => {
  const currentUser = useMemo(() => propUser ?? { id: "GUEST", name: "Citizen" }, [propUser]);

  // Language state (persisted)
  const [lang, setLang] = useState<LanguageCode>("en");

  useEffect(() => {
    try {
      const saved = localStorage.getItem("resq_lang") as LanguageCode | null;
      if (saved && (saved === "en" || saved === "hi" || saved === "gu")) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- restore the saved language after mount (localStorage is client-only)
        setLang(saved);
      }
    } catch {
      // ignore
    }
  }, []);

  const changeLang = (l: LanguageCode) => {
    setLang(l);
    try {
      localStorage.setItem("resq_lang", l);
    } catch {
      // ignore
    }
  };

  const t = TRANSLATIONS[lang];

  // Navigation tab
  const [activeTab, setActiveTab] = useState<CitizenTabId>("overview");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Data states
  const [myReports, setMyReports] = useState<CitizenApi.ReportData[]>([]);
  const [publicIncidents, setPublicIncidents] = useState<CitizenApi.PublicIncident[]>([]);
  const [publicAlerts, setPublicAlerts] = useState<CitizenApi.PublicAlert[]>([]);
  const [shelters, setShelters] = useState<CitizenApi.ShelterData[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // SOS state
  const [sosLoading, setSosLoading] = useState(false);
  const [sosBanner, setSosBanner] = useState<{ message: string; ref?: string; isError?: boolean } | null>(null);

  // Last real device position inside Gujarat, used for SOS if a fresh fix is not available. Never a default.
  const [lastFix, setLastFix] = useState<{ lat: number; lon: number } | null>(null);

  // Expanded report detail
  const [expandedReportId, setExpandedReportId] = useState<string | null>(null);

  // Compact map refs
  const compactMapContainerRef = useRef<HTMLDivElement>(null);
  const leafletCompactMapRef = useRef<any>(null);

  // Trigger refresh
  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    setRefreshKey((k) => k + 1);
  }, []);

  // Fetch live data on mount and refreshKey change
  useEffect(() => {
    if (!currentUser || currentUser.id === "GUEST-000") return;

    let isMounted = true;

    Promise.all([
      CitizenApi.fetchMyReports(),
      CitizenApi.fetchPublicIncidents(),
      CitizenApi.fetchPublicAlerts(),
      CitizenApi.fetchShelters(),
    ]).then(([reportsRes, incidentsRes, alertsRes, sheltersRes]) => {
      if (!isMounted) return;
      setBackendOnline(!reportsRes.error && !incidentsRes.error && !alertsRes.error);
      setMyReports(reportsRes.data ?? []);
      setPublicIncidents(incidentsRes.data ?? []);
      setPublicAlerts(alertsRes.data ?? []);
      setShelters(sheltersRes.data ?? []);
      setIsLoading(false);
    });

    return () => {
      isMounted = false;
    };
  }, [currentUser, refreshKey]);

  // Real-time polling for public alerts every 20 seconds (notifications are polled by the header's bell)
  useEffect(() => {
    if (!currentUser || currentUser.id === "GUEST-000") return;
    const interval = setInterval(() => {
      CitizenApi.fetchPublicAlerts().then((res) => {
        if (res.data) setPublicAlerts(res.data);
      });
    }, 20000);

    return () => clearInterval(interval);
  }, [currentUser]);

  // SOS Emergency Broadcast Handler
  const handleBroadcastSos = async () => {
    const confirmPrompt =
      t.sosDisclaimer +
      "\n\n" +
      (lang === "gu"
        ? "શું તમે તાત્કાલિક આપાતકાલીન SOS મોકલવા માંગો છો?"
        : lang === "hi"
        ? "क्या आप तत्काल आपातकालीन SOS भेजना चाहते हैं?"
        : "Do you want to broadcast an emergency SOS now?");

    if (!window.confirm(confirmPrompt)) {
      return;
    }

    setSosLoading(true);
    setSosBanner(null);

    let fix = lastFix;

    if (typeof navigator !== "undefined" && navigator.geolocation) {
      try {
        const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 5000,
          });
        });
        fix = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      } catch {
        // keep the last real fix, if any
      }
    }

    // An SOS must carry where the person really is: never send a made-up location.
    if (!fix || !isInGujarat(fix.lat, fix.lon)) {
      setSosBanner({
        message: fix
          ? "Your location is outside Gujarat, so the SOS was not sent. Please dial 112."
          : "Turn on location access so the SOS can include where you are, or dial 112 now.",
        isError: true,
      });
      setSosLoading(false);
      return;
    }
    const { lat, lon } = fix;

    try {
      const payload: CitizenApi.IncidentReportPayload = {
        scenario: "urban_flooding",
        description: `CRITICAL SOS BROADCAST: Citizen ${currentUser.name} triggered one-tap emergency distress signal via ResQ citizen dashboard. Immediate response / rescue required.`,
        people_affected: 1,
        location_source: "GPS",
        latitude: lat,
        longitude: lon,
        address_text: "Device location at SOS time",
        details: { urgent_needs: [] },
      };

      const res = await CitizenApi.createReport(payload, { idempotencyKey: crypto.randomUUID() });
      if (res.data?.incident_ref) {
        setSosBanner({
          message: `${t.sosSuccess} (Ref: ${res.data.incident_ref})`,
          ref: res.data.incident_ref,
        });
        handleRefresh();
      } else {
        setSosBanner({
          message: res.error || "Failed to transmit SOS broadcast. Please dial 112 directly.",
          isError: true,
        });
      }
    } catch {
      setSosBanner({
        message: "Network error sending SOS. Please dial 112 immediately.",
        isError: true,
      });
    } finally {
      setSosLoading(false);
    }
  };

  // Remember a real position early (inside Gujarat only), so SOS still has one if a fresh fix is slow.
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (isInGujarat(pos.coords.latitude, pos.coords.longitude)) {
            setLastFix({ lat: pos.coords.latitude, lon: pos.coords.longitude });
          }
        },
        () => {},
        { enableHighAccuracy: false, timeout: 5000 }
      );
    }
  }, []);

  // Initialize Compact Map
  useEffect(() => {
    if (!compactMapContainerRef.current || leafletCompactMapRef.current) return;

    let isMounted = true;

    const setupMap = async () => {
      try {
        if (typeof window !== "undefined" && !(window as any).L) {
          await new Promise<void>((resolve, reject) => {
            if (document.querySelector('script[src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"]')) {
              const check = setInterval(() => {
                if ((window as any).L) {
                  clearInterval(check);
                  resolve();
                }
              }, 50);
              setTimeout(() => { clearInterval(check); resolve(); }, 3000);
              return;
            }
            const script = document.createElement("script");
            script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
            script.async = true;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error("Failed to load Leaflet"));
            document.head.appendChild(script);
          });
        }

        if (!isMounted || !compactMapContainerRef.current) return;
        const L = (window as any).L;
        if (!L) return;

        const map = L.map(compactMapContainerRef.current, {
          center: [22.2587, 71.1924],
          zoom: 7,
          zoomControl: true,
          attributionControl: false,
        });

        // Restored working OpenStreetMap tile source (reliable, 100% no API key required)
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          subdomains: ["a", "b", "c"],
        }).addTo(map);

        leafletCompactMapRef.current = map;

        // Invalidate size to guarantee enlarged map viewport fills container smoothly
        setTimeout(() => {
          if (map) map.invalidateSize();
        }, 250);

        // Render strictly verified public incidents with clearly distinguishable severity markers
        publicIncidents.forEach((inc) => {
          // Preserve red for critical, orange for high, amber for moderate
          const color =
            inc.severity === "CRITICAL" ? "#dc2626" : inc.severity === "HIGH" ? "#ea580c" : "#d97706";
          const iconSymbol = inc.category === "Cyclone / Coastal Flooding" ? "🌀" : inc.category.includes("Fire") ? "🔥" : "🌊";

          const icon = L.divIcon({
            className: "",
            html: `<div style="width:30px;height:30px;border-radius:50%;background:${color};border:2.5px solid #ffffff;box-shadow:0 0 10px ${color}, 0 2px 8px rgba(0,0,0,0.45);display:flex;align-items:center;justify-content:center;font-size:14px;cursor:pointer">${iconSymbol}</div>`,
            iconSize: [30, 30],
            iconAnchor: [15, 15],
          });

          L.marker([inc.lat, inc.lon], { icon })
            .addTo(map)
            .bindPopup(
              `<div style="font-size:12px;font-family:sans-serif;color:#f8fafc;padding:3px 2px">
                <b style="color:#38bdf8;font-size:12.5px">${inc.title}</b><br/>
                <span style="color:#94a3b8;font-size:11px">${inc.location_name}</span><br/>
                <div style="display:flex;align-items:center;gap:6px;margin-top:6px">
                  <span style="display:inline-block;padding:2px 7px;border-radius:9999px;background:${color};color:#ffffff;font-size:9.5px;font-weight:bold">${inc.severity}</span>
                  <span style="color:#38bdf8;font-size:10px;font-weight:600">Active Incident</span>
                </div>
              </div>`
            );
        });

        if (publicIncidents.length > 0) {
          const bounds = L.latLngBounds(publicIncidents.map((i) => [i.lat, i.lon]));
          map.fitBounds(bounds, { padding: [25, 25], maxZoom: 8 });
        }
      } catch {
        // Fallback gracefully
      }
    };

    setupMap();

    return () => {
      isMounted = false;
      if (leafletCompactMapRef.current) {
        leafletCompactMapRef.current.remove();
        leafletCompactMapRef.current = null;
      }
    };
  }, [publicIncidents]);

  // Metrics (real data only)
  const pendingReportsCount = myReports.filter((r) => r.verification_status === "PENDING").length;
  const verifiedReportsCount = myReports.filter(
    (r) => r.verification_status === "VERIFIED" || r.verification_status === "LINKED_TO_INCIDENT"
  ).length;
  const activeAlertsCount = publicAlerts.length;

  return (
    <div className="min-h-screen bg-[#f8fafc] text-slate-800 flex flex-col font-sans">
      {/* Scoped Blue Theme for Compact Disaster Map (Coordinated with Login Page Palette) */}
      <style>{`
        .citizen-compact-blue-map {
          background-color: #070d18 !important;
        }
        .citizen-compact-blue-map .leaflet-tile-pane {
          /* Subtle cooling and contrast: light-blue water, cool light-gray land, high-contrast labels */
          filter: saturate(0.85) contrast(1.06) brightness(0.99);
        }
        .citizen-compact-blue-map .leaflet-container {
          background: #070d18 !important;
          font-family: inherit;
        }
        .citizen-compact-blue-map .leaflet-control-zoom {
          border: 1.5px solid #0284c7 !important;
          border-radius: 8px !important;
          overflow: hidden !important;
          box-shadow: 0 4px 14px rgba(7, 13, 24, 0.6) !important;
        }
        .citizen-compact-blue-map .leaflet-control-zoom a {
          background-color: #0c4a75 !important;
          color: #38bdf8 !important;
          border-bottom: 1px solid #0284c7 !important;
          transition: all 0.15s ease !important;
          font-weight: bold !important;
        }
        .citizen-compact-blue-map .leaflet-control-zoom a:hover {
          background-color: #0284c7 !important;
          color: #ffffff !important;
        }
        .citizen-compact-blue-map .leaflet-popup-content-wrapper {
          background-color: #0b1324 !important;
          color: #f8fafc !important;
          border: 1.5px solid #0284c7 !important;
          border-radius: 12px !important;
          box-shadow: 0 8px 24px rgba(2, 132, 199, 0.4) !important;
        }
        .citizen-compact-blue-map .leaflet-popup-tip {
          background-color: #0b1324 !important;
        }
        .citizen-compact-blue-map .leaflet-popup-close-button {
          color: #94a3b8 !important;
          padding: 4px 6px 0 0 !important;
        }
        .citizen-compact-blue-map .leaflet-popup-close-button:hover {
          color: #38bdf8 !important;
        }
      `}</style>

      {/* ─── Blue Header (ResQ AI Bhuvan-inspired Identity) ─── */}
      {/* Shared navigation (issue #172); the header shows the citizen's notification bell on every page. */}
      <UnifiedSiteHeader
        activeHref="/citizen/dashboard"
        session={{ authenticated: true, citizen: true, role: "NORMAL_USER", name: currentUser.name, email: currentUser.email || null }}
      >
        <div className="flex items-center gap-2.5">
          {backendOnline === false && (
            <span
              className="hidden xl:inline-flex items-center gap-1.5 text-[10.5px] px-2.5 py-0.5 rounded-full border font-medium bg-amber-950/40 text-amber-300 border-amber-600/40"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              {t.backendUnreachable}
            </span>
          )}

          {/* Optional Close Button */}
          {onClose && (
            <button
              onClick={onClose}
              className="bg-sky-800/60 hover:bg-sky-700 text-sky-100 px-3 py-1 rounded-full text-xs font-medium border border-sky-600/50 transition cursor-pointer"
              title="Close Dashboard"
            >
              ✕ {t.close}
            </button>
          )}

        </div>
      </UnifiedSiteHeader>

      {/* ─── Active Critical Advisory Top Banner ─── */}
      {publicAlerts.length > 0 && (
        <div className="bg-amber-50 border-b border-amber-200 text-amber-900 px-4 md:px-8 py-2 text-xs font-medium flex items-center justify-between">
          <div className="max-w-7xl mx-auto w-full flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-base">⚠️</span>
              <span className="truncate">
                <strong className="font-bold text-amber-950">{t.activeAdvisories}:</strong> {publicAlerts[0].title} — {publicAlerts[0].description}
              </span>
            </div>
            <button
              onClick={() => setActiveTab("safety")}
              className="text-[11px] font-bold bg-amber-600 hover:bg-amber-700 text-white px-3 py-1 rounded-full shrink-0 transition"
            >
              {t.tabSafety} →
            </button>
          </div>
        </div>
      )}

      {/* ─── SOS Feedback Banner (if triggered) ─── */}
      {sosBanner && (
        <div
          className={`px-4 md:px-8 py-3 text-xs md:text-sm font-semibold border-b ${
            sosBanner.isError
              ? "bg-red-900 text-white border-red-950"
              : "bg-emerald-800 text-white border-emerald-900"
          }`}
        >
          <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="text-base">{sosBanner.isError ? "❌" : "✅"}</span>
              <span>{sosBanner.message}</span>
            </div>
            <div className="flex items-center gap-2">
              <a
                href="tel:112"
                className="bg-white text-red-700 font-black px-3 py-1 rounded-md text-xs hover:bg-red-50 transition"
              >
                📞 Dial 112
              </a>
              <button
                onClick={() => setSosBanner(null)}
                className="text-white hover:text-slate-200 text-xs px-1.5"
              >
                ✕
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Top Welcome & Summary Section ─── */}
      <section className="bg-white border-b border-slate-200 px-4 md:px-8 py-5">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-slate-900">
              {t.welcome}, {currentUser.name.split(" ")[0]} 👋
            </h1>
            <p className="text-xs md:text-sm text-slate-500 mt-0.5">
              {t.workspaceSubtitle}
            </p>
          </div>

          <div className="flex items-center gap-2.5 sm:gap-3 shrink-0">
            {/* Trilingual Language Selector */}
            <div className="flex items-center rounded-full bg-slate-100 p-0.5 border border-slate-300 text-[11px] font-bold">
              {(["en", "hi", "gu"] as const).map((code) => (
                <button
                  key={code}
                  onClick={() => changeLang(code)}
                  className={`px-2 py-0.5 rounded-full transition cursor-pointer text-[10.5px] ${
                    lang === code
                      ? "bg-[#0c4a75] text-white shadow-xs font-black"
                      : "text-slate-600 hover:text-slate-900 font-medium"
                  }`}
                  title={code === "en" ? "English" : code === "hi" ? "हिन्दी" : "ગુજરાતી"}
                >
                  {code === "en" ? "EN" : code === "hi" ? "हिन्दी" : "ગુજરાતી"}
                </button>
              ))}
            </div>

            {/* Quick Emergency SOS Broadcast Button */}
            <button
              onClick={handleBroadcastSos}
              disabled={sosLoading}
              className="flex items-center gap-1.5 bg-red-600 hover:bg-red-500 active:scale-95 text-white px-3 sm:px-4 py-2.5 rounded-xl text-xs font-bold shadow-xs transition cursor-pointer shrink-0"
              title={t.sosDisclaimer}
            >
              <span className="text-xs">🚨</span>
              <span className="hidden sm:inline">{sosLoading ? t.sosBroadcasting : t.sosButton}</span>
              <span className="sm:hidden">SOS</span>
            </button>

            <button
              onClick={handleRefresh}
              className="bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 px-3 py-2.5 rounded-xl text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
              title="Refresh reports and incident telemetry"
            >
              <span>↻</span>
              <span className="hidden sm:inline">{t.refreshBtn}</span>
            </button>
          </div>
        </div>

        {/* Real-Data Summary Cards */}
        <div className="max-w-7xl mx-auto grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4 mt-5">
          <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-sky-100 border border-sky-200 text-sky-700 flex items-center justify-center text-lg">
              📋
            </div>
            <div>
              <div className="text-xl font-extrabold text-slate-900">{myReports.length}</div>
              <div className="text-[11px] font-medium text-slate-500">{t.myReportsCount}</div>
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-100 border border-amber-200 text-amber-700 flex items-center justify-center text-lg">
              ⏳
            </div>
            <div>
              <div className="text-xl font-extrabold text-slate-900">{pendingReportsCount}</div>
              <div className="text-[11px] font-medium text-slate-500">{t.underReviewCount}</div>
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-100 border border-emerald-200 text-emerald-700 flex items-center justify-center text-lg">
              ✅
            </div>
            <div>
              <div className="text-xl font-extrabold text-slate-900">{verifiedReportsCount}</div>
              <div className="text-[11px] font-medium text-slate-500">{t.verifiedCount}</div>
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-red-100 border border-red-200 text-red-700 flex items-center justify-center text-lg">
              ⚠️
            </div>
            <div>
              <div className="text-xl font-extrabold text-slate-900">{activeAlertsCount}</div>
              <div className="text-[11px] font-medium text-slate-500">{t.activeAlertsCount}</div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Navigation Tabs ─── */}
      <div className="bg-white border-b border-slate-200 px-4 md:px-8">
        <div className="max-w-7xl mx-auto flex gap-2 overflow-x-auto">
          {[
            { id: "overview" as const, label: t.tabOverview, icon: "🏠" },
            { id: "reports" as const, label: `${t.tabMyReports} (${myReports.length})`, icon: "📋" },
            { id: "safety" as const, label: t.tabSafety, icon: "🛡️" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-3 px-3.5 text-xs font-bold whitespace-nowrap border-b-2 transition-all cursor-pointer flex items-center gap-2 ${
                activeTab === tab.id
                  ? "border-[#0c4a75] text-[#0c4a75] bg-sky-50/60"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-50"
              }`}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ─── Lower Content Area: Two-Column Layout (Left/Center Citizen Functionality + Far Right Compact Map) ─── */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 md:px-8 py-6 flex flex-col lg:flex-row items-start justify-between gap-6 lg:gap-8">
        {/* ── Left and Center — Main Citizen Functionality ── */}
        <div className="w-full lg:flex-1 min-w-0 space-y-6">
          {/* TAB 1: OVERVIEW */}
          {activeTab === "overview" && (
            <div className="space-y-6">
              {/* 24x7 Gujarat Emergency Helplines Quick-Dial Card */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100 mb-4">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">📞</span>
                    <div>
                      <h3 className="text-sm font-bold text-slate-900">{t.helplineTitle}</h3>
                      <p className="text-[11px] text-slate-500">Official toll-free dispatch lines across Gujarat</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-700 border border-emerald-200 px-2.5 py-0.5 rounded-full">
                    {t.tollFree} • 24x7
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <a
                    href="tel:112"
                    className="p-3.5 rounded-xl bg-slate-50 hover:bg-red-50/60 border border-slate-200/90 hover:border-red-200 transition flex items-center justify-between group"
                  >
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-extrabold text-base text-red-600">112</span>
                        <span className="text-[10px] uppercase font-bold text-red-700 bg-red-100/70 px-1.5 py-0.2 rounded">Primary</span>
                      </div>
                      <div className="text-[11px] text-slate-600 mt-0.5">National Emergency (Police, Fire, Medical)</div>
                    </div>
                    <span className="text-xs bg-red-600 hover:bg-red-700 text-white font-bold px-3 py-1.5 rounded-lg shadow-2xs group-hover:scale-105 transition-transform">
                      Call
                    </span>
                  </a>
                  <a
                    href="tel:108"
                    className="p-3.5 rounded-xl bg-slate-50 hover:bg-emerald-50/60 border border-slate-200/90 hover:border-emerald-200 transition flex items-center justify-between group"
                  >
                    <div>
                      <div className="font-extrabold text-base text-emerald-700">108</div>
                      <div className="text-[11px] text-slate-600 mt-0.5">Gujarat Emergency Medical & Ambulance</div>
                    </div>
                    <span className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white font-bold px-3 py-1.5 rounded-lg shadow-2xs group-hover:scale-105 transition-transform">
                      Call
                    </span>
                  </a>
                  <a
                    href="tel:1077"
                    className="p-3.5 rounded-xl bg-slate-50 hover:bg-sky-50/60 border border-slate-200/90 hover:border-sky-200 transition flex items-center justify-between group"
                  >
                    <div>
                      <div className="font-extrabold text-base text-sky-800">1077</div>
                      <div className="text-[11px] text-slate-600 mt-0.5">District Disaster Control Room</div>
                    </div>
                    <span className="text-xs bg-sky-700 hover:bg-sky-800 text-white font-bold px-3 py-1.5 rounded-lg shadow-2xs group-hover:scale-105 transition-transform">
                      Call
                    </span>
                  </a>
                  <a
                    href="tel:1070"
                    className="p-3.5 rounded-xl bg-slate-50 hover:bg-sky-50/60 border border-slate-200/90 hover:border-sky-200 transition flex items-center justify-between group"
                  >
                    <div>
                      <div className="font-extrabold text-base text-sky-800">1070</div>
                      <div className="text-[11px] text-slate-600 mt-0.5">Gujarat State Disaster Mgmt (GSDMA)</div>
                    </div>
                    <span className="text-xs bg-sky-700 hover:bg-sky-800 text-white font-bold px-3 py-1.5 rounded-lg shadow-2xs group-hover:scale-105 transition-transform">
                      Call
                    </span>
                  </a>
                </div>
              </div>

              {/* Recent Reports Overview */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-base">📋</span>
                    <h3 className="text-sm font-bold text-slate-800">{t.recentActivityTitle}</h3>
                  </div>
                  <button
                    onClick={() => setActiveTab("reports")}
                    className="text-xs font-semibold text-sky-700 hover:text-sky-800 cursor-pointer"
                  >
                    {t.tabMyReports} ({myReports.length}) →
                  </button>
                </div>

                {isLoading ? (
                  <div className="py-10 text-center text-xs text-slate-400">Loading your reports...</div>
                ) : myReports.length === 0 ? (
                  <div className="py-8 text-center space-y-2">
                    <div className="text-3xl">📭</div>
                    <div className="text-xs font-semibold text-slate-600">{t.noReportsYet}</div>
                    <p className="text-[11px] text-slate-400 max-w-sm mx-auto">
                      When you submit a report for floods, cyclones, or fires, its verification and response telemetry will appear here.
                    </p>
                    <button
                      onClick={() => onOpenCitizenReport?.()}
                      className="mt-2 text-xs font-bold text-sky-700 hover:text-sky-800 underline cursor-pointer"
                    >
                      {t.reportNow}
                    </button>
                  </div>
                ) : (
                  <div className="divide-y divide-slate-100 mt-2">
                    {myReports.slice(0, 3).map((r) => {
                      const badge = statusBadge(r.verification_status);
                      return (
                        <div key={r.id} className="py-3 flex items-center justify-between gap-3">
                          <div className="space-y-0.5">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs font-bold text-slate-800">{r.id}</span>
                              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badge.bg}`}>
                                {badge.label}
                              </span>
                            </div>
                            <div className="text-xs text-slate-600">{r.category} • {r.location_name}</div>
                          </div>
                          <div className="text-right">
                            <div className="text-[11px] text-slate-400">{formatRelativeTime(r.submitted_at)}</div>
                            <button
                              onClick={() => {
                                setExpandedReportId(r.id);
                                setActiveTab("reports");
                              }}
                              className="text-[10.5px] text-sky-700 hover:underline cursor-pointer"
                            >
                              Details
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Active Public Safety Advisories Snippet */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-base">⚠️</span>
                    <h3 className="text-sm font-bold text-slate-800">{t.activeAdvisories}</h3>
                  </div>
                  <button
                    onClick={() => setActiveTab("safety")}
                    className="text-xs font-semibold text-sky-700 hover:text-sky-800 cursor-pointer"
                  >
                    {t.tabSafety} →
                  </button>
                </div>

                {publicAlerts.length === 0 ? (
                  <div className="py-6 text-center text-xs text-slate-400">
                    No active meteorological warnings in your area.
                  </div>
                ) : (
                  <div className="space-y-2.5 mt-3">
                    {publicAlerts.slice(0, 2).map((alert) => (
                      <div key={alert.id} className="p-3 rounded-xl bg-slate-50 border border-slate-200/70 text-xs">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-bold text-slate-800">{alert.title}</span>
                          <span className={`text-[9.5px] px-2 py-0.5 rounded border ${severityBadge(alert.severity)}`}>
                            {alert.severity}
                          </span>
                        </div>
                        <p className="text-slate-600 text-[11.5px] line-clamp-2">{alert.description}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 3: MY REPORTS */}
          {activeTab === "reports" && (
            <div className="bg-white border border-slate-200/90 rounded-2xl p-5 md:p-7 shadow-xs space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <div>
                  <h2 className="text-base md:text-lg font-bold text-slate-900 flex items-center gap-2">
                    <span>📋</span> My Disaster Reports
                  </h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Track report triage, authority verification, and resource dispatch.
                  </p>
                </div>
                <button
                  onClick={handleRefresh}
                  className="text-xs font-semibold text-sky-700 bg-sky-50 hover:bg-sky-100 px-3 py-1.5 rounded-xl border border-sky-200 transition cursor-pointer"
                >
                  ↻ Refresh Reports
                </button>
              </div>

              {isLoading ? (
                <div className="py-16 text-center text-xs text-slate-400">Loading your reports...</div>
              ) : myReports.length === 0 ? (
                <div className="py-16 text-center space-y-3">
                  <div className="text-4xl">📭</div>
                  <h3 className="text-sm font-bold text-slate-700">No Disaster Reports Found</h3>
                  <p className="text-xs text-slate-400 max-w-sm mx-auto">
                    You have not submitted any emergency reports. Use &ldquo;Report Incident&rdquo; in the top bar when in distress.
                  </p>
                  <button
                    onClick={() => onOpenCitizenReport?.()}
                    className="bg-red-600 hover:bg-red-500 text-white text-xs font-bold px-4 py-2 rounded-xl transition cursor-pointer shadow-xs"
                  >
                    Report Disaster Now
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  {myReports.map((report) => {
                    const badge = statusBadge(report.verification_status);
                    const isExpanded = expandedReportId === report.id;

                    return (
                      <div
                        key={report.id}
                        className="border border-slate-200 rounded-xl overflow-hidden hover:border-slate-300 transition-all bg-white"
                      >
                        <div
                          onClick={() => setExpandedReportId(isExpanded ? null : report.id)}
                          className="p-4 flex items-center justify-between cursor-pointer hover:bg-slate-50 transition"
                        >
                          <div className="flex items-center gap-3">
                            <span className="text-2xl">
                              {report.category === "Cyclone / Coastal Flooding" ? "🌀" : report.category.includes("Fire") ? "🔥" : "🌊"}
                            </span>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs font-bold text-slate-900">{report.id}</span>
                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${badge.bg}`}>
                                  {badge.label}
                                </span>
                              </div>
                              <div className="text-xs text-slate-600 font-medium mt-0.5">
                                {report.category} • <span className="text-slate-500">{report.location_name}</span>
                              </div>
                            </div>
                          </div>

                          <div className="flex items-center gap-3">
                            <span className="text-[11px] text-slate-400 hidden sm:inline">
                              {formatRelativeTime(report.submitted_at)}
                            </span>
                            <span className="text-xs text-slate-400 font-bold">{isExpanded ? "▲" : "▼"}</span>
                          </div>
                        </div>

                        {/* Reply to a dispatcher's information request (issue #99); shown without expanding */}
                        <InformationRequestReply report={report} onReplied={handleRefresh} theme="light" className="mx-4 mb-4" />

                        {/* Expandable Details */}
                        {isExpanded && (
                          <div className="px-4 pb-4 pt-1 bg-slate-50/70 border-t border-slate-100 space-y-3 text-xs">
                            <div>
                              <span className="font-bold text-slate-700">Description: </span>
                              <span className="text-slate-600">{report.description}</span>
                            </div>

                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                              <div>
                                <span className="text-slate-400">Affected: </span>
                                <span className="font-bold text-slate-700">~{report.affected_people_count} people</span>
                              </div>
                              <div>
                                <span className="text-slate-400">Coordinates: </span>
                                <span className="font-mono font-bold text-slate-700">
                                  {report.lat.toFixed(3)}, {report.lon.toFixed(3)}
                                </span>
                              </div>
                              <div>
                                <span className="text-slate-400">Submitted: </span>
                                <span className="font-medium text-slate-700">
                                  {new Date(report.submitted_at).toLocaleDateString()}
                                </span>
                              </div>
                              <div>
                                <span className="text-slate-400">Source: </span>
                                <span className="font-medium text-slate-700">{report.source}</span>
                              </div>
                            </div>

                            {report.urgent_needs && report.urgent_needs.length > 0 && (
                              <div>
                                <span className="text-slate-400 text-[11px] block mb-1">Urgent Needs Requested:</span>
                                <div className="flex flex-wrap gap-1">
                                  {report.urgent_needs.map((need) => (
                                    <span
                                      key={need}
                                      className="text-[10px] bg-red-50 text-red-700 border border-red-200 px-2 py-0.5 rounded-full font-medium"
                                    >
                                      {need}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}

                            {report.linked_incident_id && (
                              <div className="bg-sky-50 border border-sky-200 rounded-lg p-2.5 text-xs text-sky-800 font-medium">
                                🚨 <b>Active Response:</b> Escalated to confirmed incident{" "}
                                <span className="font-mono font-bold">{report.linked_incident_id}</span>. Response units deployed.
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 4: SAFETY & SHELTERS */}
          {activeTab === "safety" && (
            <div className="space-y-6">
              {/* Official Safety Advisories */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
                  <span className="text-base">⚠️</span>
                  <h3 className="text-sm font-bold text-slate-900">{t.activeAdvisories}</h3>
                </div>

                {publicAlerts.length === 0 ? (
                  <div className="py-6 text-center text-xs text-slate-400">
                    No active advisories issued at this time.
                  </div>
                ) : (
                  <div className="space-y-3 mt-3">
                    {publicAlerts.map((alert) => (
                      <div key={alert.id} className="p-3.5 rounded-xl border border-slate-200 bg-slate-50 text-xs">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="font-bold text-slate-900">{alert.title}</span>
                          <span className={`text-[10px] px-2.5 py-0.5 rounded border ${severityBadge(alert.severity)}`}>
                            {alert.severity}
                          </span>
                        </div>
                        <p className="text-slate-600 text-[11.5px] leading-relaxed">{alert.description}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Safety Instructions & Guidelines */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
                  <span className="text-base">📖</span>
                  <h3 className="text-sm font-bold text-slate-900">{t.dosAndDonts}</h3>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                  <div className="p-4 rounded-xl bg-sky-50 border border-sky-100">
                    <h4 className="font-bold text-xs text-sky-900 flex items-center gap-1.5 mb-2">
                      <span>🌊</span> {t.catFlood}
                    </h4>
                    <ul className="text-[11px] text-sky-800 space-y-1 list-disc list-inside">
                      {lang === "gu" ? (
                        <>
                          <li>તાત્કાલિક ઊંચા માળ અથવા સલામત ઊંચા સ્થળે પહોંચો.</li>
                          <li>પૂરના પાણીમાં ચાલવાનો કે વાહન ચલાવવાનો પ્રયાસ ન કરો.</li>
                          <li>ઘરનું મુખ્ય વીજળી કનેક્શન અને ગેસ સપ્લાય બંધ કરો.</li>
                        </>
                      ) : lang === "hi" ? (
                        <>
                          <li>तुरंत ऊपरी मंजिल या ऊंचे सुरक्षित स्थान पर जाएं।</li>
                          <li>बाढ़ के पानी में पैदल चलने या गाड़ी चलाने का प्रयास न करें।</li>
                          <li>घर का मुख्य बिजली स्विच और गैस आपूर्ति बंद करें।</li>
                        </>
                      ) : (
                        <>
                          <li>Move immediately to upper stories or high ground.</li>
                          <li>Never attempt to walk or drive across flooded bridges.</li>
                          <li>Turn off main gas and electric supplies.</li>
                        </>
                      )}
                    </ul>
                  </div>

                  <div className="p-4 rounded-xl bg-violet-50 border border-violet-100">
                    <h4 className="font-bold text-xs text-violet-900 flex items-center gap-1.5 mb-2">
                      <span>🌀</span> {t.catCyclone}
                    </h4>
                    <ul className="text-[11px] text-violet-800 space-y-1 list-disc list-inside">
                      {lang === "gu" ? (
                        <>
                          <li>બારીઓ અને કાચના દરવાજાથી દૂર મકાનની અંદર રહો.</li>
                          <li>ઓછામાં ઓછું 3 દિવસનું પીવાનું સ્વચ્છ પાણી સંગ્રહ કરો.</li>
                          <li>બિનજરૂરી વીજ ઉપકરણો બંધ રાખો અને મોબાઈલ ચાર્જ રાખો.</li>
                        </>
                      ) : lang === "hi" ? (
                        <>
                          <li>खिड़कियों और कांच के दरवाजों से दूर सुरक्षित रहें।</li>
                          <li>कम से कम 3 दिनों के लिए स्वच्छ पीने का पानी रखें।</li>
                          <li>बिजली के उपकरण बंद रखें और मोबाइल चार्ज रखें।</li>
                        </>
                      ) : (
                        <>
                          <li>Stay inside away from windows and glass facades.</li>
                          <li>Store 3 days of clean drinking water in sealed containers.</li>
                          <li>Disconnect non-essential electrical devices.</li>
                        </>
                      )}
                    </ul>
                  </div>

                  <div className="p-4 rounded-xl bg-amber-50 border border-amber-100">
                    <h4 className="font-bold text-xs text-amber-900 flex items-center gap-1.5 mb-2">
                      <span>🔥</span> {t.catFire}
                    </h4>
                    <ul className="text-[11px] text-amber-800 space-y-1 list-disc list-inside">
                      {lang === "gu" ? (
                        <>
                          <li>ધૂમાડાથી બચવા નીચે નમીને ફાયર સીડી તરફ આગળ વધો.</li>
                          <li>આગ સમયે લિફ્ટનો ઉપયોગ ક્યારેય ન કરવો, માત્ર સીડી વાપરો.</li>
                          <li>ઝેરી ધૂમાડાથી બચવા ભીના કપડાથી મોં અને નાક ઢાંકો.</li>
                        </>
                      ) : lang === "hi" ? (
                        <>
                          <li>धुएं से बचने के लिए नीचे झुककर आपातकालीन सीढ़ियों की ओर बढ़ें।</li>
                          <li>आग लगने पर कभी भी लिफ्ट का उपयोग न करें, केवल सीढ़ियां लें।</li>
                          <li>विषाक्त धुएं को रोकने के लिए मुंह को गीले कपड़े से ढकें।</li>
                        </>
                      ) : (
                        <>
                          <li>Crawl low under smoke toward marked fire stairs.</li>
                          <li>Never use elevators during emergency alarms.</li>
                          <li>Cover mouth with damp cloth to filter toxic smoke.</li>
                        </>
                      )}
                    </ul>
                  </div>
                </div>
              </div>

              {/* Public Shelters & Hospitals */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-base">🏥</span>
                    <h3 className="text-sm font-bold text-slate-900">{t.reliefShelters}</h3>
                  </div>
                  <span className="text-xs text-slate-400">{shelters.length} locations</span>
                </div>

                {shelters.length === 0 ? (
                  <div className="py-6 text-center text-xs text-slate-400">
                    {t.noSheltersFound}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
                    {shelters.map((shelter) => (
                      <div key={shelter.id} className="p-3.5 rounded-xl border border-slate-200 bg-slate-50 text-xs">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-bold text-slate-800">
                            {shelter.name}
                            {shelter.is_simulated && <span className="ml-1.5 text-[9.5px] font-semibold text-slate-400">(sample data)</span>}
                          </span>
                          <span
                            className={`text-[9.5px] px-2 py-0.5 rounded-full font-bold border ${
                              shelter.status === "OPERATIONAL"
                                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                : "bg-red-50 text-red-700 border-red-200"
                            }`}
                          >
                            {shelter.status}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-500">{shelter.address}</div>
                        <div className="mt-2.5 pt-2 border-t border-slate-200/70 flex items-center justify-between text-[11px]">
                          <div>
                            {t.capacityLabel}:{" "}
                            <b className="text-slate-800">{shelter.available_beds ?? shelter.total_capacity ?? "Open"}</b>
                          </div>
                          {shelter.contact_number && (
                            <a href={`tel:${shelter.contact_number}`} className="text-sky-700 font-semibold hover:underline">
                              📞 {shelter.contact_number}
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Far Right — Expanded Disaster GIS Map & Confirmed Incidents ── */}
        <div className="w-full lg:w-[380px] xl:w-[420px] shrink-0 space-y-4">
          <div className="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-xs sticky top-20 text-slate-800">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-sky-50 border border-sky-100 flex items-center justify-center text-xs text-sky-700">
                  🗺️
                </div>
                <div>
                  <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                    {t.liveMapTitle}
                  </h3>
                  <p className="text-[10px] text-slate-500">Gujarat SEOC & NDMA Feeds</p>
                </div>
              </div>
              <span className="text-[10px] font-bold bg-sky-50 text-sky-700 border border-sky-200 px-2.5 py-0.5 rounded-full">
                {publicIncidents.length} Active
              </span>
            </div>

            {/* Expanded GIS Blue Map Container (360px - 420px tall) */}
            <div className="citizen-compact-blue-map relative w-full h-[360px] md:h-[380px] lg:h-[390px] rounded-xl overflow-hidden border border-slate-200 bg-[#070d18] shadow-inner">
              <div ref={compactMapContainerRef} className="absolute inset-0 w-full h-full" />

              {/* Empty state when 0 active incidents */}
              {publicIncidents.length === 0 && (
                <div className="absolute inset-0 bg-white/95 flex flex-col items-center justify-center p-4 text-center z-10 border border-slate-200">
                  <div className="text-3xl mb-1">✅</div>
                  <div className="text-xs font-bold text-slate-800">No active disasters reported in this area.</div>
                  <p className="text-[10px] text-slate-500 mt-1">All monitored regional zones in Gujarat are normal.</p>
                </div>
              )}
            </div>

            {/* Compact Incident List Summary */}
            <div className="mt-3.5 space-y-2">
              <div className="text-[10.5px] font-bold text-slate-600 uppercase tracking-wider flex items-center justify-between">
                <span>Confirmed Emergency Incidents</span>
                <span className="text-[9.5px] text-sky-700 font-semibold">{publicIncidents.length} listed</span>
              </div>
              {publicIncidents.length === 0 ? (
                <div className="text-[11px] text-slate-400 italic py-1">No active verified incidents.</div>
              ) : (
                <div className="space-y-1.5 max-h-[200px] overflow-y-auto pr-1">
                  {publicIncidents.map((inc) => (
                    <div
                      key={inc.id}
                      onClick={() => {
                        if (leafletCompactMapRef.current) {
                          leafletCompactMapRef.current.flyTo([inc.lat, inc.lon], 8, { duration: 0.8 });
                        }
                      }}
                      className="p-2.5 rounded-xl bg-slate-50 border border-slate-200 hover:border-sky-400 hover:bg-sky-50/50 transition text-xs cursor-pointer group"
                      title="Click to view on map"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-800 text-[11.5px] truncate max-w-[150px] group-hover:text-sky-800 transition">
                          {inc.title}
                        </span>
                        <span className={`text-[9px] px-2 py-0.5 rounded font-bold border ${severityBadge(inc.severity)}`}>
                          {inc.severity}
                        </span>
                      </div>
                      <div className="text-[10.5px] text-slate-500 truncate mt-0.5 flex items-center justify-between">
                        <span>{inc.location_name}</span>
                        <span className="text-[9.5px] text-sky-700 font-medium opacity-0 group-hover:opacity-100 transition">📍 Locate</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* ─── Footer ─── */}
      <footer className="py-4 text-center text-xs text-slate-500 border-t border-slate-200 bg-white mt-auto">
        ResQ AI Disaster Coordination Hub • Official Gujarat Citizen Portal • Confidential & Secure
      </footer>
    </div>
  );
};
