"use client";

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { DisasterCategory } from "../../types/resq";
import * as CitizenApi from "../../services/citizenApi";

interface CitizenDashboardViewProps {
  currentUser?: { id: string; name: string; phone?: string; email?: string } | null;
  onOpenCitizenReport?: () => void;
  onViewPublicMap?: () => void;
  onSignOut?: () => void;
  onClose?: () => void;
}

type CitizenTabId = "overview" | "report" | "reports" | "safety";

const DISASTER_TYPES: { type: DisasterCategory; icon: string; title: string; color: string }[] = [
  { type: "Flood / Urban Flood", icon: "🌊", title: "Flood / Urban Flood", color: "sky" },
  { type: "Cyclone / Coastal Flooding", icon: "🌀", title: "Cyclone / Coastal Flooding", color: "violet" },
  { type: "Major Urban / Building Fire", icon: "🔥", title: "Major Urban / Building Fire", color: "amber" },
];

const URGENT_NEEDS_OPTIONS = [
  "Rescue Boats",
  "Medical Evacuation",
  "Drinking Water",
  "Temporary Shelter",
  "Water Tenders (Fire)",
  "Power Grid Cutoff",
];

function statusBadge(status: string) {
  switch (status) {
    case "VERIFIED":
      return { label: "Verified", bg: "bg-emerald-50 text-emerald-700 border-emerald-200" };
    case "LINKED_TO_INCIDENT":
      return { label: "Help Dispatched", bg: "bg-sky-50 text-sky-700 border-sky-200" };
    case "PENDING":
      return { label: "Under Review", bg: "bg-amber-50 text-amber-700 border-amber-200" };
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

function darkSeverityBadge(sev: string) {
  switch (sev) {
    case "CRITICAL":
      return "bg-red-950/80 text-red-200 border-red-700/60 font-bold";
    case "HIGH":
      return "bg-orange-950/80 text-orange-200 border-orange-700/60 font-semibold";
    case "MODERATE":
    case "WARNING":
      return "bg-amber-950/80 text-amber-200 border-amber-700/60 font-medium";
    default:
      return "bg-emerald-950/80 text-emerald-200 border-emerald-700/60 font-medium";
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
  onViewPublicMap,
  onSignOut,
  onClose,
}) => {
  const currentUser = useMemo(() => propUser ?? { id: "GUEST", name: "Citizen" }, [propUser]);
  const logout = onSignOut || (() => {});

  // Navigation tab
  const [activeTab, setActiveTab] = useState<CitizenTabId>("overview");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Data states
  const [myReports, setMyReports] = useState<CitizenApi.ReportData[]>([]);
  const [publicIncidents, setPublicIncidents] = useState<CitizenApi.PublicIncident[]>([]);
  const [publicAlerts, setPublicAlerts] = useState<CitizenApi.PublicAlert[]>([]);
  const [shelters, setShelters] = useState<CitizenApi.ShelterData[]>([]);
  const [notifications, setNotifications] = useState<CitizenApi.InAppNotification[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Form state
  const [formCategory, setFormCategory] = useState<DisasterCategory>("Flood / Urban Flood");
  const [formDescription, setFormDescription] = useState("");
  const [formLocation, setFormLocation] = useState("");
  const [formLat, setFormLat] = useState(20.5937);
  const [formLon, setFormLon] = useState(78.9629);
  const [formAffected, setFormAffected] = useState(1);
  const [formNeeds, setFormNeeds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<{ success: boolean; reportId?: string; error?: string } | null>(null);

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

  // Fetch live data. There is NO demo fallback: on failure the lists stay empty and the offline banner shows.
  useEffect(() => {
    if (!currentUser || currentUser.id === "GUEST-000") return;

    let isMounted = true;

    Promise.all([
      CitizenApi.fetchMyReports(),
      CitizenApi.fetchPublicIncidents(),
      CitizenApi.fetchPublicAlerts(),
      CitizenApi.fetchShelters(),
      CitizenApi.fetchMyNotifications(),
    ]).then(([reportsRes, incidentsRes, alertsRes, sheltersRes, notifRes]) => {
      if (!isMounted) return;
      setBackendOnline(!reportsRes.error && !incidentsRes.error && !alertsRes.error);
      setMyReports(reportsRes.data ?? []);
      setPublicIncidents(incidentsRes.data ?? []);
      setPublicAlerts(alertsRes.data ?? []);
      setShelters(sheltersRes.data ?? []);
      setNotifications(notifRes.data?.items ?? []);
      setIsLoading(false);
    });

    return () => {
      isMounted = false;
    };
  }, [currentUser, refreshKey]);

  const unreadCount = notifications.filter((n) => !n.read_at).length;

  const handleMarkAsRead = async (id: string) => {
    try {
      await CitizenApi.markNotificationRead(id);
      setNotifications((prev) =>
        prev.map((n) => (n.notification_id === id ? { ...n, read_at: new Date().toISOString() } : n))
      );
    } catch {
      // ignore
    }
  };

  // Geolocation for report form
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setFormLat(pos.coords.latitude);
          setFormLon(pos.coords.longitude);
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
          center: [22.5, 80],
          zoom: 5,
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
          const iconSymbol = inc.category.includes("Flood") ? "🌊" : inc.category.includes("Fire") ? "🔥" : "🌀";

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

  // Report Submission Handler
  const handleReportSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentUser) return;

    if (formDescription.trim().length < 10) {
      setSubmitResult({ success: false, error: "Please enter at least 10 characters describing the situation." });
      return;
    }
    if (!formLocation.trim()) {
      setSubmitResult({ success: false, error: "Please enter the location name or landmark." });
      return;
    }

    setSubmitting(true);
    setSubmitResult(null);

    const payload: CitizenApi.IncidentReportPayload = {
      scenario: CitizenApi.CATEGORY_TO_SCENARIO[formCategory],
      description: formDescription.trim(),
      people_affected: formAffected,
      location_source: "MAP_PIN",
      latitude: formLat,
      longitude: formLon,
      address_text: formLocation.trim(),
      details: { urgent_needs: formNeeds },
    };

    const res = await CitizenApi.createReport(payload, { idempotencyKey: crypto.randomUUID() });

    if (res.data) {
      setSubmitResult({ success: true, reportId: res.data.incident_ref });
      setFormDescription("");
      setFormLocation("");
      setFormAffected(1);
      setFormNeeds([]);
      handleRefresh();
    } else {
      setSubmitResult({ success: false, error: res.error || "Failed to submit disaster report. Please try again." });
    }

    setSubmitting(false);
  };

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
      <header className="h-14 bg-[#0c4a75] border-b border-[#093554] px-4 md:px-8 flex items-center justify-between text-white shadow-md sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-sky-400/20 border border-white/70 flex items-center justify-center text-lg shadow-inner">
            🛡️
          </div>
          <div>
            <div className="flex items-baseline gap-2 leading-none">
              <span className="text-lg font-extrabold tracking-tight text-white">ResQ</span>
              <span className="text-xs font-light text-sky-200">Citizen Safety Portal</span>
              <span className="hidden sm:inline-block text-[9.5px] uppercase font-bold bg-sky-900/90 text-sky-200 px-1.5 py-0.5 rounded border border-sky-700/60">
                Public User
              </span>
            </div>
            <div className="text-[10px] text-sky-200/80 leading-tight mt-0.5 hidden sm:block">
              ResQ • Emergency Services (112)
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {backendOnline !== null && (
            <span
              className={`hidden md:inline-flex items-center gap-1.5 text-[10.5px] px-2.5 py-0.5 rounded-full border font-medium ${
                backendOnline
                  ? "bg-emerald-950/40 text-emerald-300 border-emerald-600/40"
                  : "bg-amber-950/40 text-amber-300 border-amber-600/40"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${backendOnline ? "bg-emerald-400" : "bg-amber-400"}`} />
              {backendOnline ? "Backend Live" : "Local Storage"}
            </span>
          )}

          {/* Citizen Profile Pill */}
          <div className="flex items-center gap-2 bg-sky-900/50 border border-sky-700/50 px-3 py-1 rounded-full text-xs">
            <span className="w-5 h-5 rounded-full bg-sky-500/30 text-sky-200 flex items-center justify-center text-[11px] font-bold">
              {currentUser.name.charAt(0)}
            </span>
            <span className="font-medium text-white max-w-[120px] truncate">{currentUser.name}</span>
          </div>

          {/* Optional View Public Map Button */}
          {onViewPublicMap && (
            <button
              onClick={onViewPublicMap}
              className="hidden lg:flex items-center gap-1 bg-sky-800/60 hover:bg-sky-700 text-sky-100 px-3 py-1 rounded-full text-xs font-semibold border border-sky-600/50 transition cursor-pointer"
              title="Open Full National Bhuvan-Style Map"
            >
              <span>🗺️</span>
              <span>Full Map View</span>
            </button>
          )}

          {/* Optional Close Button */}
          {onClose && (
            <button
              onClick={onClose}
              className="bg-sky-800/60 hover:bg-sky-700 text-sky-100 px-3 py-1 rounded-full text-xs font-medium border border-sky-600/50 transition cursor-pointer"
              title="Close Dashboard"
            >
              ✕ Close
            </button>
          )}

          {/* Notification Bell */}
          <div className="relative">
            <button
              onClick={() => setShowNotifications(!showNotifications)}
              className="relative p-1.5 rounded-full hover:bg-sky-800/60 text-sky-100 transition cursor-pointer"
              title="Notifications"
              aria-label="View notifications"
            >
              <svg className="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 flex size-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white shadow-xs">
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </button>

            {/* Notification Dropdown Drawer */}
            {showNotifications && (
              <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-xl border border-slate-200 bg-white p-3 shadow-xl z-50 text-slate-900">
                <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-600">
                    Notifications ({unreadCount} unread)
                  </span>
                  <button
                    onClick={() => setShowNotifications(false)}
                    className="text-xs text-slate-400 hover:text-slate-600 cursor-pointer"
                  >
                    ✕
                  </button>
                </div>
                {notifications.length === 0 ? (
                  <p className="py-6 text-center text-xs text-slate-400">No notifications yet.</p>
                ) : (
                  <div className="max-h-72 overflow-y-auto space-y-2">
                    {notifications.map((item) => {
                      const isUnread = !item.read_at;
                      return (
                        <div
                          key={item.notification_id}
                          className={`p-2.5 rounded-lg border text-xs transition ${
                            isUnread
                              ? "bg-sky-50/60 border-sky-200"
                              : "bg-slate-50 border-slate-100 opacity-80"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-1">
                            <span className="font-semibold text-slate-900">{item.title}</span>
                            {isUnread && (
                              <button
                                onClick={() => handleMarkAsRead(item.notification_id)}
                                className="text-[10px] text-sky-600 hover:text-sky-800 font-medium shrink-0 cursor-pointer"
                              >
                                Mark read
                              </button>
                            )}
                          </div>
                          <p className="mt-1 text-slate-600 text-[11px]">{item.body}</p>
                          <span className="mt-1 block text-[10px] text-slate-400">
                            {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Sign Out Button */}
          <button
            onClick={onSignOut || logout}
            className="bg-red-700/80 hover:bg-red-600 text-white text-xs px-3 py-1 rounded-full font-medium transition cursor-pointer shadow-xs"
          >
            Sign Out
          </button>
        </div>
      </header>

      {/* ─── Top Welcome & Summary Section ─── */}
      <section className="bg-white border-b border-slate-200 px-4 md:px-8 py-5">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-slate-900">
              Welcome, {currentUser.name.split(" ")[0]} 👋
            </h1>
            <p className="text-xs md:text-sm text-slate-500 mt-0.5">
              Citizen Emergency & Disaster Response Workspace • Report emergencies and track real-time resolution
            </p>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {/* Primary Action Button: Report Disaster */}
            <button
              onClick={() => {
                setActiveTab("report");
                setSubmitResult(null);
                if (onOpenCitizenReport) onOpenCitizenReport();
              }}
              className="bg-red-600 hover:bg-red-500 text-white px-5 py-2.5 rounded-xl font-bold text-xs md:text-sm shadow-md hover:shadow-lg shadow-red-600/25 transition cursor-pointer flex items-center gap-2 group"
            >
              <span className="text-base group-hover:scale-110 transition-transform">🚨</span>
              <span>Report a Disaster</span>
            </button>

            <button
              onClick={handleRefresh}
              className="bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 px-3 py-2.5 rounded-xl text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
              title="Refresh reports and incident telemetry"
            >
              <span>↻</span>
              <span className="hidden sm:inline">Refresh</span>
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
              <div className="text-[11px] font-medium text-slate-500">My Reports</div>
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-100 border border-amber-200 text-amber-700 flex items-center justify-center text-lg">
              ⏳
            </div>
            <div>
              <div className="text-xl font-extrabold text-slate-900">{pendingReportsCount}</div>
              <div className="text-[11px] font-medium text-slate-500">Under Review</div>
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-100 border border-emerald-200 text-emerald-700 flex items-center justify-center text-lg">
              ✅
            </div>
            <div>
              <div className="text-xl font-extrabold text-slate-900">{verifiedReportsCount}</div>
              <div className="text-[11px] font-medium text-slate-500">Verified / Dispatched</div>
            </div>
          </div>

          <div className="bg-slate-50 border border-slate-200/90 rounded-xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-red-100 border border-red-200 text-red-700 flex items-center justify-center text-lg">
              ⚠️
            </div>
            <div>
              <div className="text-xl font-extrabold text-slate-900">{activeAlertsCount}</div>
              <div className="text-[11px] font-medium text-slate-500">Safety Advisories</div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Navigation Tabs ─── */}
      <div className="bg-white border-b border-slate-200 px-4 md:px-8">
        <div className="max-w-7xl mx-auto flex gap-2 overflow-x-auto">
          {[
            { id: "overview" as const, label: "Dashboard Overview", icon: "🏠" },
            { id: "report" as const, label: "Report a Disaster", icon: "🚨" },
            { id: "reports" as const, label: `My Reports (${myReports.length})`, icon: "📋" },
            { id: "safety" as const, label: "Public Safety & Shelters", icon: "🛡️" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                setSubmitResult(null);
              }}
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
              {/* Emergency Banner Card */}
              <div className="bg-gradient-to-r from-red-600 via-rose-600 to-orange-600 text-white rounded-2xl p-5 md:p-6 shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-xs font-semibold bg-white/20 backdrop-blur-xs px-2.5 py-0.5 rounded-full w-max">
                    <span>📢</span> Immediate Assistance Hotline: 112
                  </div>
                  <h2 className="text-lg md:text-xl font-bold">Experiencing a Life-Threatening Emergency?</h2>
                  <p className="text-xs text-white/90 max-w-xl">
                    Submit a geo-tagged incident distress signal directly into the NDMA Multi-Agency Coordination Hub.
                  </p>
                </div>
                <button
                  onClick={() => {
                    setActiveTab("report");
                    setSubmitResult(null);
                  }}
                  className="bg-white hover:bg-slate-100 text-red-700 font-bold px-5 py-2.5 rounded-xl text-xs md:text-sm shadow transition cursor-pointer shrink-0"
                >
                  Start SOS Report →
                </button>
              </div>

              {/* Recent Reports Overview */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-base">📋</span>
                    <h3 className="text-sm font-bold text-slate-800">Your Recent Disaster Reports</h3>
                  </div>
                  <button
                    onClick={() => setActiveTab("reports")}
                    className="text-xs font-semibold text-sky-700 hover:text-sky-800 cursor-pointer"
                  >
                    View All ({myReports.length}) →
                  </button>
                </div>

                {isLoading ? (
                  <div className="py-10 text-center text-xs text-slate-400">Loading your reports...</div>
                ) : myReports.length === 0 ? (
                  <div className="py-8 text-center space-y-2">
                    <div className="text-3xl">📭</div>
                    <div className="text-xs font-semibold text-slate-600">No reports submitted yet</div>
                    <p className="text-[11px] text-slate-400 max-w-sm mx-auto">
                      When you submit a report for floods, cyclones, or fires, its verification and response telemetry will appear here.
                    </p>
                    <button
                      onClick={() => setActiveTab("report")}
                      className="mt-2 text-xs font-bold text-sky-700 hover:text-sky-800 underline cursor-pointer"
                    >
                      Submit your first report now
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
                    <h3 className="text-sm font-bold text-slate-800">Official Public Safety Alerts</h3>
                  </div>
                  <button
                    onClick={() => setActiveTab("safety")}
                    className="text-xs font-semibold text-sky-700 hover:text-sky-800 cursor-pointer"
                  >
                    All Guidelines & Shelters →
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

          {/* TAB 2: REPORT A DISASTER */}
          {activeTab === "report" && (
            <div className="bg-white border border-slate-200/90 rounded-2xl p-5 md:p-7 shadow-xs">
              <div className="mb-5 pb-3 border-b border-slate-100">
                <h2 className="text-base md:text-lg font-bold text-slate-900 flex items-center gap-2">
                  <span>🚨</span> Report a Disaster Incident
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Your report will be authenticated and dispatched directly to local SDRF, NDRF, and fire/EMS command units.
                </p>
              </div>

              {submitResult?.success ? (
                <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-6 text-center space-y-3">
                  <div className="w-12 h-12 bg-emerald-600 text-white rounded-full flex items-center justify-center text-2xl mx-auto shadow-md">
                    ✓
                  </div>
                  <h3 className="text-base font-bold text-emerald-900">Emergency Report Successfully Registered</h3>
                  <p className="text-xs text-emerald-700 max-w-md mx-auto">
                    Your report has been confirmed and stored in the Disaster Response Hub database.
                  </p>
                  <div className="bg-white border border-emerald-300 rounded-xl p-3 max-w-xs mx-auto font-mono text-sm font-bold text-emerald-900 shadow-xs">
                    Reference ID: {submitResult.reportId}
                  </div>
                  <p className="text-[11px] text-slate-500">
                    Keep this ID handy to monitor triage status and dispatch telemetry.
                  </p>
                  <div className="flex justify-center gap-2 pt-2">
                    <button
                      onClick={() => {
                        setActiveTab("reports");
                        setSubmitResult(null);
                      }}
                      className="bg-[#0c4a75] hover:bg-[#075985] text-white px-4 py-2 rounded-xl text-xs font-bold cursor-pointer"
                    >
                      View in My Reports
                    </button>
                    <button
                      onClick={() => setSubmitResult(null)}
                      className="bg-slate-200 hover:bg-slate-300 text-slate-700 px-4 py-2 rounded-xl text-xs font-semibold cursor-pointer"
                    >
                      Submit Another Report
                    </button>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleReportSubmit} className="space-y-5">
                  {submitResult?.error && (
                    <div className="bg-red-50 border border-red-200 text-red-700 p-3 rounded-xl text-xs font-medium">
                      ⚠️ {submitResult.error}
                    </div>
                  )}

                  {/* 1. Category Selection */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
                      1. Disaster Category <span className="text-red-500">*</span>
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      {DISASTER_TYPES.map((dt) => (
                        <button
                          key={dt.type}
                          type="button"
                          onClick={() => setFormCategory(dt.type)}
                          className={`p-3.5 rounded-xl border text-left transition cursor-pointer flex items-center gap-3 ${
                            formCategory === dt.type
                              ? "bg-sky-50 border-sky-600 ring-2 ring-sky-500/20 text-slate-900 shadow-xs"
                              : "bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100"
                          }`}
                        >
                          <span className="text-2xl">{dt.icon}</span>
                          <div>
                            <div className="text-xs font-bold text-slate-900 leading-tight">{dt.title}</div>
                            <div className="text-[10px] text-slate-400">Emergency Priority</div>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 2. Description */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                      2. Incident Description <span className="text-red-500">*</span>
                    </label>
                    <textarea
                      value={formDescription}
                      onChange={(e) => setFormDescription(e.target.value)}
                      placeholder="Detail what is happening (e.g., Water rising above 4ft, several families stranded on rooftops, no electricity)..."
                      rows={3}
                      className="w-full bg-slate-50 border border-slate-300 rounded-xl p-3 text-xs focus:outline-none focus:border-sky-600 focus:bg-white text-slate-900 transition"
                      required
                    />
                    <div className="text-[10px] text-slate-400 mt-1 flex justify-between">
                      <span>Minimum 10 characters</span>
                      <span>{formDescription.length} characters</span>
                    </div>
                  </div>

                  {/* 3. Location and Coordinates */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                        3. Location / Landmark <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="text"
                        value={formLocation}
                        onChange={(e) => setFormLocation(e.target.value)}
                        placeholder="e.g., Sector 14 Metro Station, Near Civil Hospital"
                        className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs focus:outline-none focus:border-sky-600 focus:bg-white text-slate-900 transition"
                        required
                      />
                    </div>

                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                          GPS Coordinates
                        </label>
                        <button
                          type="button"
                          onClick={() => {
                            if (navigator.geolocation) {
                              navigator.geolocation.getCurrentPosition(
                                (pos) => {
                                  setFormLat(pos.coords.latitude);
                                  setFormLon(pos.coords.longitude);
                                },
                                () => alert("Could not access location."),
                                { enableHighAccuracy: true, timeout: 5000 }
                              );
                            }
                          }}
                          className="text-[10px] text-sky-700 hover:underline font-bold cursor-pointer"
                        >
                          📍 Detect My GPS
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          type="number"
                          step="0.0001"
                          value={formLat}
                          onChange={(e) => setFormLat(parseFloat(e.target.value) || 0)}
                          placeholder="Latitude"
                          className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs text-slate-900 font-mono"
                        />
                        <input
                          type="number"
                          step="0.0001"
                          value={formLon}
                          onChange={(e) => setFormLon(parseFloat(e.target.value) || 0)}
                          placeholder="Longitude"
                          className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs text-slate-900 font-mono"
                        />
                      </div>
                    </div>
                  </div>

                  {/* 4. Affected People & Urgent Needs */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                        Estimated Affected People
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="10000"
                        value={formAffected}
                        onChange={(e) => setFormAffected(parseInt(e.target.value) || 1)}
                        className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs text-slate-900"
                      />
                    </div>
                  </div>

                  {/* Urgent Needs Checkboxes */}
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
                      Urgent Supplies / Equipment Needed
                    </label>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                      {URGENT_NEEDS_OPTIONS.map((need) => (
                        <label
                          key={need}
                          className={`p-2.5 rounded-xl border text-xs cursor-pointer flex items-center gap-2 transition select-none ${
                            formNeeds.includes(need)
                              ? "bg-sky-50 border-sky-500 text-sky-900 font-bold"
                              : "bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={formNeeds.includes(need)}
                            onChange={(e) => {
                              if (e.target.checked) setFormNeeds([...formNeeds, need]);
                              else setFormNeeds(formNeeds.filter((n) => n !== need));
                            }}
                            className="rounded text-sky-600"
                          />
                          <span>{need}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Submit Button */}
                  <div className="pt-2">
                    <button
                      type="submit"
                      disabled={submitting}
                      className="w-full bg-red-600 hover:bg-red-500 text-white font-bold py-3 rounded-xl text-sm shadow-md hover:shadow-lg shadow-red-600/30 transition cursor-pointer flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                      {submitting ? (
                        <>
                          <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          <span>Persisting Report to Hub...</span>
                        </>
                      ) : (
                        <>
                          <span>🚨</span>
                          <span>Submit Emergency Disaster Report</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              )}
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
                    You have not submitted any emergency reports. Use the &ldquo;Report a Disaster&rdquo; form when in distress.
                  </p>
                  <button
                    onClick={() => setActiveTab("report")}
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
                              {report.category.includes("Flood") ? "🌊" : report.category.includes("Fire") ? "🔥" : "🌀"}
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
                  <h3 className="text-sm font-bold text-slate-900">Official Meteorological & Flood Advisories</h3>
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
                  <h3 className="text-sm font-bold text-slate-900">Emergency Response Guidelines</h3>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                  <div className="p-4 rounded-xl bg-sky-50 border border-sky-100">
                    <h4 className="font-bold text-xs text-sky-900 flex items-center gap-1.5 mb-2">
                      <span>🌊</span> Flash Flooding
                    </h4>
                    <ul className="text-[11px] text-sky-800 space-y-1 list-disc list-inside">
                      <li>Move immediately to upper stories or high ground.</li>
                      <li>Never attempt to walk or drive across flooded bridges.</li>
                      <li>Turn off main gas and electric supplies.</li>
                    </ul>
                  </div>

                  <div className="p-4 rounded-xl bg-violet-50 border border-violet-100">
                    <h4 className="font-bold text-xs text-violet-900 flex items-center gap-1.5 mb-2">
                      <span>🌀</span> Cyclone / Heavy Storm
                    </h4>
                    <ul className="text-[11px] text-violet-800 space-y-1 list-disc list-inside">
                      <li>Stay inside away from windows and glass facades.</li>
                      <li>Store 3 days of clean drinking water in sealed containers.</li>
                      <li>Disconnect non-essential electrical devices.</li>
                    </ul>
                  </div>

                  <div className="p-4 rounded-xl bg-amber-50 border border-amber-100">
                    <h4 className="font-bold text-xs text-amber-900 flex items-center gap-1.5 mb-2">
                      <span>🔥</span> Building Fire Safety
                    </h4>
                    <ul className="text-[11px] text-amber-800 space-y-1 list-disc list-inside">
                      <li>Crawl low under smoke toward marked fire stairs.</li>
                      <li>Never use elevators during emergency alarms.</li>
                      <li>Cover mouth with damp cloth to filter toxic smoke.</li>
                    </ul>
                  </div>
                </div>
              </div>

              {/* Public Shelters & Hospitals */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-base">🏥</span>
                    <h3 className="text-sm font-bold text-slate-900">Designated Relief Shelters & Facilities</h3>
                  </div>
                  <span className="text-xs text-slate-400">{shelters.length} locations</span>
                </div>

                {shelters.length === 0 ? (
                  <div className="py-6 text-center text-xs text-slate-400">
                    No public shelter capacity telemetry available.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
                    {shelters.map((shelter) => (
                      <div key={shelter.id} className="p-3.5 rounded-xl border border-slate-200 bg-slate-50 text-xs">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-bold text-slate-800">{shelter.name}</span>
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
                            Available Space:{" "}
                            <b className="text-slate-800">{shelter.available_beds ?? shelter.total_capacity ?? "Open"}</b>
                          </div>
                          {shelter.contact_number && (
                            <span className="text-sky-700 font-semibold">📞 {shelter.contact_number}</span>
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
          <div className="bg-[#0b1324] border border-slate-700/80 rounded-2xl p-4 shadow-xl sticky top-20 text-white">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-sky-950 border border-sky-500/50 flex items-center justify-center text-xs">
                  🗺️
                </div>
                <div>
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                    Active Disasters Near You
                  </h3>
                  <p className="text-[10px] text-slate-400">NDMA & State Command Telemetry</p>
                </div>
              </div>
              <span className="text-[10px] font-bold bg-sky-950/90 text-sky-400 border border-sky-500/50 px-2.5 py-0.5 rounded-full ring-1 ring-sky-500/30">
                {publicIncidents.length} Active
              </span>
            </div>

            {/* Expanded GIS Blue Map Container (360px - 420px tall) */}
            <div className="citizen-compact-blue-map mt-3 relative w-full h-[390px] md:h-[400px] lg:h-[410px] rounded-xl overflow-hidden border-2 border-sky-600/60 bg-[#070d18] shadow-md ring-1 ring-sky-500/20">
              <div ref={compactMapContainerRef} className="absolute inset-0 w-full h-full" />

              {/* Empty state when 0 active incidents */}
              {publicIncidents.length === 0 && (
                <div className="absolute inset-0 bg-[#0b1324]/95 flex flex-col items-center justify-center p-4 text-center z-10 border border-sky-500/20">
                  <div className="text-3xl mb-1">✅</div>
                  <div className="text-xs font-bold text-sky-200">No active disasters reported in this area.</div>
                  <p className="text-[10px] text-slate-400 mt-1">All monitored regional zones are currently normal.</p>
                </div>
              )}
            </div>

            {/* Compact Incident List Summary (matching login preset button styling) */}
            <div className="mt-3.5 space-y-2">
              <div className="text-[10.5px] font-bold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                <span>Confirmed Emergency Incidents</span>
                <span className="text-[9.5px] text-sky-400 font-semibold">{publicIncidents.length} listed</span>
              </div>
              {publicIncidents.length === 0 ? (
                <div className="text-[11px] text-slate-400 italic py-1">No active verified incidents.</div>
              ) : (
                <div className="space-y-1.5 max-h-[220px] overflow-y-auto pr-1">
                  {publicIncidents.map((inc) => (
                    <div
                      key={inc.id}
                      onClick={() => {
                        if (leafletCompactMapRef.current) {
                          leafletCompactMapRef.current.flyTo([inc.lat, inc.lon], 8, { duration: 0.8 });
                        }
                      }}
                      className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800 hover:border-sky-500/60 hover:bg-sky-950/40 transition text-xs cursor-pointer group"
                      title="Click to view on map"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-100 text-[11.5px] truncate max-w-[150px] group-hover:text-sky-300 transition">
                          {inc.title}
                        </span>
                        <span className={`text-[9px] px-2 py-0.5 rounded font-bold border ${darkSeverityBadge(inc.severity)}`}>
                          {inc.severity}
                        </span>
                      </div>
                      <div className="text-[10.5px] text-slate-400 truncate mt-0.5 flex items-center justify-between">
                        <span>{inc.location_name}</span>
                        <span className="text-[9.5px] text-sky-400 font-medium opacity-0 group-hover:opacity-100 transition">📍 Locate</span>
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
        ResQ AI Disaster Coordination Hub • Official Citizen Portal • Confidential & Secure
      </footer>
    </div>
  );
};
