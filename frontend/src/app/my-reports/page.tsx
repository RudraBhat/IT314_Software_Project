"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { fetchMyReports, ReportData } from "@/services/citizenApi";

const STATUS_CONFIG: Record<
  string,
  { label: string; badgeClass: string; step: number; color: string }
> = {
  SUBMITTED: {
    label: "Awaiting Verification",
    badgeClass: "bg-amber-950/60 text-amber-300 border-amber-700/60",
    step: 1,
    color: "#f59e0b",
  },
  VERIFIED: {
    label: "Verified by SEOC",
    badgeClass: "bg-sky-950/60 text-sky-300 border-sky-700/60",
    step: 2,
    color: "#0284c7",
  },
  DISPATCHED: {
    label: "Response Team En Route",
    badgeClass: "bg-purple-950/60 text-purple-300 border-purple-700/60",
    step: 3,
    color: "#a855f7",
  },
  RESOLVED: {
    label: "Incident Resolved",
    badgeClass: "bg-emerald-950/60 text-emerald-300 border-emerald-700/60",
    step: 4,
    color: "#10b981",
  },
  CLOSED: {
    label: "Closed",
    badgeClass: "bg-slate-800 text-slate-300 border-slate-700",
    step: 4,
    color: "#64748b",
  },
  REJECTED: {
    label: "Dismissed / Duplicate",
    badgeClass: "bg-rose-950/60 text-rose-300 border-rose-700/60",
    step: 1,
    color: "#f43f5e",
  },
  NEEDS_INFORMATION: {
    label: "Additional Info Requested",
    badgeClass: "bg-orange-950/60 text-orange-300 border-orange-700/60",
    step: 1,
    color: "#f97316",
  },
};

const STAGES = [
  { id: 1, name: "Submitted", desc: "Logged in queue" },
  { id: 2, name: "Verified", desc: "Assessed by Command" },
  { id: 3, name: "Dispatched", desc: "Field Team assigned" },
  { id: 4, name: "Resolved", desc: "Emergency cleared" },
];

export default function MyReportsPage() {
  const [reports, setReports] = useState<ReportData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());
  const [selectedReport, setSelectedReport] = useState<ReportData | null>(null);

  const loadReports = useCallback(async () => {
    try {
      const res = await fetchMyReports();
      if (res.error) {
        setError(res.error);
      } else if (res.data) {
        setReports(res.data);
        setError(null);
      }
      setLastRefreshed(new Date());
    } catch {
      setError("Unable to connect to reports service.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load & Polling every 15 seconds (SRS Requirement S1-06)
  useEffect(() => {
    let mounted = true;
    const fetchReports = async () => {
      try {
        const res = await fetchMyReports();
        if (!mounted) return;
        if (res.error) {
          setError(res.error);
        } else if (res.data) {
          setReports(res.data);
          setError(null);
        }
        setLastRefreshed(new Date());
      } catch {
        if (mounted) setError("Unable to connect to reports service.");
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchReports();
    const interval = setInterval(fetchReports, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const getStatusInfo = (statusStr?: string) => {
    const key = (statusStr || "SUBMITTED").toUpperCase();
    return STATUS_CONFIG[key] || STATUS_CONFIG.SUBMITTED;
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
          <span className="text-xs uppercase tracking-wider font-semibold text-sky-400 bg-sky-400/10 px-2 py-0.5 rounded border border-sky-400/20">
            My Incident Reports
          </span>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-[11px] text-slate-500 font-mono hidden sm:flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
            Auto-refreshes every 15s • Updated {lastRefreshed.toLocaleTimeString()}
          </div>
          <Link
            href="/report"
            className="bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold px-4 py-2 rounded-lg shadow-md shadow-sky-600/30 transition flex items-center gap-1.5"
          >
            <span>+</span>
            <span>Report Incident</span>
          </Link>
          <Link href="/citizen/dashboard" className="text-xs text-slate-400 hover:text-white transition">
            Dashboard
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-5xl w-full mx-auto p-6 md:p-8">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-white flex items-center gap-2">
              <span>📋</span> Active Emergency Reports
            </h1>
            <p className="text-slate-400 text-xs md:text-sm mt-0.5">
              Live status progression and verification timeline from Gujarat Disaster Management operations.
            </p>
          </div>
          <button
            type="button"
            onClick={() => loadReports()}
            className="text-xs text-slate-400 hover:text-white bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg transition flex items-center gap-1.5 cursor-pointer"
          >
            <span>🔄</span> Refresh Now
          </button>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-950/60 border border-red-700/60 rounded-xl text-red-200 text-sm flex items-center gap-3">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {loading ? (
          <div className="py-20 text-center text-slate-500 space-y-3">
            <div className="w-8 h-8 border-2 border-sky-500 border-t-transparent rounded-full animate-spin mx-auto" />
            <div className="text-sm">Retrieving your reported incidents...</div>
          </div>
        ) : reports.length === 0 ? (
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-12 text-center shadow-lg">
            <div className="text-4xl mb-3">📍</div>
            <h2 className="text-lg font-bold text-white mb-1">No Incidents Reported</h2>
            <p className="text-slate-400 text-sm max-w-md mx-auto mb-6">
              You haven&apos;t filed any emergency incident reports yet. If you are experiencing a disaster in Gujarat, file a report directly with emergency operations.
            </p>
            <Link
              href="/report"
              className="inline-flex items-center gap-2 bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold px-6 py-2.5 rounded-xl shadow-lg shadow-sky-600/30 transition"
            >
              <span>🚨</span>
              <span>Report An Emergency</span>
            </Link>
          </div>
        ) : (
          <div className="space-y-4">
            {reports.map((report) => {
              const currentStatus = report.status || report.verification_status || "SUBMITTED";
              const statusInfo = getStatusInfo(currentStatus);
              const isSelected = selectedReport?.id === report.id;

              return (
                <div
                  key={report.id}
                  className="bg-slate-900 border border-slate-800 hover:border-slate-700/80 rounded-2xl p-5 md:p-6 shadow-md transition"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono font-bold text-sky-400 text-sm">
                          {report.incident_ref || report.id}
                        </span>
                        <span className="text-xs uppercase tracking-wider font-semibold bg-slate-800 text-slate-300 px-2 py-0.5 rounded border border-slate-700">
                          {report.category || "Incident"}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 flex items-center gap-2">
                        <span>📍 {report.location_name || `${report.lat.toFixed(4)}, ${report.lon.toFixed(4)}`}</span>
                        <span>•</span>
                        <span>
                          {report.submitted_at
                            ? new Date(report.submitted_at).toLocaleString()
                            : "Recently logged"}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <span
                        className={`text-xs font-semibold px-3 py-1 rounded-full border ${statusInfo.badgeClass}`}
                      >
                        {statusInfo.label}
                      </span>
                      <button
                        type="button"
                        onClick={() => setSelectedReport(isSelected ? null : report)}
                        className="text-xs text-slate-400 hover:text-slate-200 bg-slate-800/80 px-2.5 py-1 rounded-lg border border-slate-700 transition cursor-pointer"
                      >
                        {isSelected ? "Hide Details" : "Timeline View"}
                      </button>
                    </div>
                  </div>

                  <p className="text-sm text-slate-300 mb-5 leading-relaxed bg-slate-950/50 p-3 rounded-xl border border-slate-800/60">
                    {report.description}
                  </p>

                  {/* Visual 4-Stage Progression Timeline */}
                  <div className="pt-2">
                    <div className="grid grid-cols-4 gap-2 relative">
                      {STAGES.map((stage) => {
                        const isPast = statusInfo.step > stage.id;
                        const isCurrent = statusInfo.step === stage.id;

                        return (
                          <div key={stage.id} className="text-center relative">
                            {/* Connector Bar */}
                            {stage.id < 4 && (
                              <div
                                className={`hidden sm:block absolute top-3.5 left-1/2 w-full h-0.5 z-0 ${
                                  isPast ? "bg-sky-500" : "bg-slate-800"
                                }`}
                              />
                            )}

                            {/* Node Icon */}
                            <div
                              className={`w-7 h-7 rounded-full flex items-center justify-center mx-auto mb-1.5 text-xs font-bold relative z-10 transition ${
                                isPast
                                  ? "bg-sky-500 text-white shadow-md shadow-sky-500/30"
                                  : isCurrent
                                  ? "bg-amber-500 text-slate-950 ring-4 ring-amber-500/20 shadow-md shadow-amber-500/30 font-extrabold"
                                  : "bg-slate-800 text-slate-500 border border-slate-700"
                              }`}
                            >
                              {isPast ? "✓" : stage.id}
                            </div>

                            <div
                              className={`text-xs font-semibold truncate ${
                                isCurrent ? "text-amber-400 font-bold" : isPast ? "text-slate-200" : "text-slate-500"
                              }`}
                            >
                              {stage.name}
                            </div>
                            <div className="text-[10px] text-slate-500 hidden md:block">
                              {stage.desc}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Detailed Timeline Drawer */}
                  {isSelected && (
                    <div className="mt-5 pt-4 border-t border-slate-800 text-xs space-y-2">
                      <div className="font-semibold text-slate-300 mb-2">Detailed Event Audit:</div>
                      <div className="space-y-1.5 font-mono text-[11px] text-slate-400">
                        <div className="flex items-center gap-2">
                          <span className="text-emerald-400">●</span>
                          <span>Report received by Gujarat Gateway:</span>
                          <span className="text-slate-300">
                            {report.submitted_at || "Initial Timestamp recorded"}
                          </span>
                        </div>
                        {report.timeline &&
                          report.timeline.map((item, tIdx) => (
                            <div key={tIdx} className="flex items-center gap-2">
                              <span className="text-sky-400">●</span>
                              <span>Status updated to {item.status}:</span>
                              <span className="text-slate-300">
                                {new Date(item.timestamp).toLocaleString()}
                              </span>
                            </div>
                          ))}
                        <div className="flex items-center gap-2 text-slate-500">
                          <span>ℹ️</span>
                          <span>Coordinates: {(report.lat ?? (report as unknown as { latitude?: number }).latitude ?? 22.2587).toFixed(4)}°N, {(report.lon ?? (report as unknown as { longitude?: number }).longitude ?? 71.1924).toFixed(4)}°E (Gujarat)</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
