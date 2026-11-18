"use client";

import React, { useState, useEffect, useCallback } from "react";
import { UnifiedSiteHeader } from "@/components/navigation/UnifiedSiteHeader";
import Link from "next/link";
import { latestInformationRequest, REPLY_MAX_LENGTH, REPLY_MIN_LENGTH } from "@/components/citizen/InformationRequestReply";
import { fetchMyReports, replyToInformationRequest, requestWithdrawal, ReportData } from "@/services/citizenApi";
import { ReportPhotos } from "@/components/ReportPhotos";
import { isInGujarat } from "@/lib/geo";

const STATUS_CONFIG: Record<
  string,
  { label: string; badgeClass: string; step: number; color: string }
> = {
  SUBMITTED: {
    label: "Awaiting Verification",
    badgeClass: "bg-amber-50 text-amber-800 border-amber-200",
    step: 1,
    color: "#f59e0b",
  },
  VERIFIED: {
    label: "Verified by SEOC",
    badgeClass: "bg-sky-50 text-sky-800 border-sky-200",
    step: 2,
    color: "#0284c7",
  },
  DISPATCHED: {
    label: "Response Team En Route",
    badgeClass: "bg-purple-50 text-purple-800 border-purple-200",
    step: 3,
    color: "#a855f7",
  },
  RESOLVED: {
    label: "Incident Resolved",
    badgeClass: "bg-emerald-50 text-emerald-800 border-emerald-200",
    step: 4,
    color: "#10b981",
  },
  CLOSED: {
    label: "Closed",
    badgeClass: "bg-slate-100 text-slate-700 border-slate-200",
    step: 4,
    color: "#64748b",
  },
  REJECTED: {
    label: "Dismissed / Duplicate",
    badgeClass: "bg-rose-50 text-rose-800 border-rose-200",
    step: 1,
    color: "#f43f5e",
  },
  NEEDS_INFORMATION: {
    label: "Additional Info Requested",
    badgeClass: "bg-orange-50 text-orange-800 border-orange-200",
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
  // Null until the first load finishes: a time rendered on the server never matches the browser locale (hydration error).
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [selectedReport, setSelectedReport] = useState<ReportData | null>(null);

  // Information response state (SRS Requirement S2-13)
  const [replyText, setReplyText] = useState<Record<string, string>>({});
  const [replyingId, setReplyingId] = useState<string | null>(null);
  const [replyError, setReplyError] = useState<{ id: string; message: string } | null>(null);
  const [replySuccess, setReplySuccess] = useState<string | null>(null);
  const [replyPlace, setReplyPlace] = useState<Record<string, { latitude: number; longitude: number } | undefined>>({});
  const [withdrawing, setWithdrawing] = useState<string | null>(null);
  const [withdrawError, setWithdrawError] = useState<{ id: string; message: string } | null>(null);
  const [placeError, setPlaceError] = useState<{ id: string; message: string } | null>(null);

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
    <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col font-sans">
      {/* Header */}
      <UnifiedSiteHeader activeHref="/my-reports">
        <span aria-live="polite" className="hidden items-center gap-1.5 font-mono text-[11px] text-sky-200/80 xl:flex">
          <span aria-hidden="true" className="size-1.5 animate-ping rounded-full bg-emerald-400" />
          Auto-refresh 15s · {lastRefreshed ? lastRefreshed.toLocaleTimeString() : "…"}
        </span>
      </UnifiedSiteHeader>

      {/* Main Content */}
      <main className="flex-1 max-w-5xl w-full mx-auto p-4 sm:p-6 md:p-8">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-slate-900 flex items-center gap-2">
              <span aria-hidden="true">📋</span> Active Emergency Reports
            </h1>
            <p className="text-slate-600 text-xs md:text-sm mt-0.5">
              Live status progression and verification timeline from Gujarat Disaster Management operations.
            </p>
          </div>
          <button
            type="button"
            onClick={() => loadReports()}
            className="min-h-[44px] text-xs font-semibold text-slate-700 hover:text-slate-900 bg-white hover:bg-slate-50 border border-slate-300 px-3.5 py-1.5 rounded-lg transition flex items-center gap-1.5 cursor-pointer shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          >
            <span aria-hidden="true">🔄</span> Refresh Now
          </button>
        </div>

        {error && (
          <div role="alert" aria-live="assertive" className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-800 text-sm flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span aria-hidden="true">⚠️</span>
              <span>{error}</span>
            </div>
            <button
              type="button"
              onClick={() => loadReports()}
              className="text-xs font-semibold bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded-lg transition cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
            >
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <div role="status" aria-label="Loading incident reports" className="space-y-4">
            <span className="sr-only">Loading your incident reports...</span>
            {[1, 2, 3].map((skeletonId) => (
              <div key={skeletonId} className="bg-white border border-slate-200 rounded-2xl p-5 md:p-6 animate-pulse space-y-4 shadow-xs">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-2">
                    <div className="h-5 w-36 bg-slate-200 rounded" />
                    <div className="h-3 w-48 bg-slate-100 rounded" />
                  </div>
                  <div className="h-6 w-28 bg-slate-200 rounded-full" />
                </div>
                <div className="h-14 w-full bg-slate-50 rounded-xl border border-slate-100" />
                <div className="grid grid-cols-4 gap-2 pt-2">
                  {[1, 2, 3, 4].map((stepId) => (
                    <div key={stepId} className="text-center space-y-1.5">
                      <div className="w-7 h-7 rounded-full bg-slate-200 mx-auto" />
                      <div className="h-3 w-12 bg-slate-100 rounded mx-auto" />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : reports.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-2xl p-8 sm:p-12 text-center shadow-sm">
            <div className="text-4xl mb-3" aria-hidden="true">📍</div>
            <h2 className="text-lg font-bold text-slate-900 mb-1">No Incidents Reported</h2>
            <p className="text-slate-600 text-sm max-w-md mx-auto mb-6">
              You haven&apos;t filed any emergency incident reports yet. If you are experiencing a disaster in Gujarat, file a report directly with emergency operations.
            </p>
            <Link
              href="/report"
              className="inline-flex items-center gap-2 min-h-[44px] bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold px-6 py-2.5 rounded-xl shadow-md shadow-sky-600/20 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2"
            >
              <span aria-hidden="true">🚨</span>
              <span>Report An Emergency</span>
            </Link>
          </div>
        ) : (
          <div className="space-y-4">
            {reports.map((report) => {
              const currentStatus = report.status || report.verification_status || "SUBMITTED";
              const statusInfo = getStatusInfo(currentStatus);
              const isSelected = selectedReport?.id === report.id;
              const informationRequest = latestInformationRequest(report.timeline);
              const replyLength = (replyText[report.id] || "").trim().length;
              const hasReplyLocation = Boolean(replyPlace[report.id]);

              return (
                <div
                  key={report.id}
                  className="bg-white border border-slate-200/90 hover:border-slate-300 rounded-2xl p-5 md:p-6 shadow-xs transition"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono font-bold text-sky-700 text-sm">
                          {report.incident_ref || report.id}
                        </span>
                        <span className="text-xs uppercase tracking-wider font-semibold bg-slate-100 text-slate-700 px-2 py-0.5 rounded border border-slate-200">
                          {report.category || "Incident"}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 flex flex-wrap items-center gap-2">
                        <span>📍 {report.location_name || `${report.lat.toFixed(4)}, ${report.lon.toFixed(4)}`}</span>
                        <span aria-hidden="true">•</span>
                        <span>
                          {report.submitted_at
                            ? new Date(report.submitted_at).toLocaleString()
                            : "Recently logged"}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={`text-xs font-semibold px-3 py-1 rounded-full border ${statusInfo.badgeClass}`}
                      >
                        {statusInfo.label}
                      </span>
                      <button
                        type="button"
                        onClick={() => setSelectedReport(isSelected ? null : report)}
                        className="min-h-[44px] text-xs font-medium text-slate-700 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 px-3 py-1 rounded-lg border border-slate-200 transition cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 flex items-center justify-center"
                      >
                        {isSelected ? "Hide Details" : "Timeline View"}
                      </button>
                    </div>
                  </div>

                  <p className="text-sm text-slate-700 mb-5 leading-relaxed bg-slate-50 p-3.5 rounded-xl border border-slate-200/80">
                    {report.description}
                  </p>

                  {/* Citizen Information Response Form (SRS S2-13) */}
                  {(currentStatus === "NEEDS_INFORMATION" || replySuccess === report.id) && (
                    <section aria-label="Reply to the information request" className="mb-5 p-4 rounded-xl border border-orange-200 bg-orange-50/80 text-orange-950">
                      {replySuccess === report.id ? (
                        <div role="status" aria-live="polite" className="text-xs text-emerald-700 font-semibold py-1">
                          ✓ Your reply was sent. The report is back in the verification queue.
                        </div>
                      ) : (
                        <>
                          <div className="flex items-center gap-2 mb-2 font-bold text-xs text-orange-800">
                            <span aria-hidden="true">⚠️</span>
                            <span>Action Required: Command Center requested additional information</span>
                          </div>
                          {informationRequest ? (
                            <blockquote className="mb-3 rounded-lg border border-orange-200 bg-white px-3 py-2 text-xs text-orange-900">
                              <span className="sr-only">Dispatcher asked: </span>
                              {informationRequest}
                            </blockquote>
                          ) : (
                            <p className="text-xs text-orange-800 mb-3">
                              Please clarify situation details, stranded counts, or nearby landmarks to assist response dispatchers.
                            </p>
                          )}
                          <form
                            onSubmit={async (e) => {
                              e.preventDefault();
                              const text = replyText[report.id]?.trim();
                              const place = replyPlace[report.id];
                              if ((!text || text.length < 3) && !place) return;
                              setReplyingId(report.id);
                              setReplyError(null);
                              const res = await replyToInformationRequest(report.id, text && text.length >= 3 ? text : undefined, place);
                              setReplyingId(null);
                              if (res.error) {
                                setReplyError({ id: report.id, message: res.error });
                              } else {
                                setReplySuccess(report.id);
                                setReplyText((prev) => ({ ...prev, [report.id]: "" }));
                                setReplyPlace((prev) => ({ ...prev, [report.id]: undefined }));
                                loadReports();
                              }
                            }}
                            className="space-y-2"
                          >
                            <label htmlFor={`reply-text-${report.id}`} className="sr-only">
                              Your reply to the dispatcher
                            </label>
                            <textarea
                              id={`reply-text-${report.id}`}
                              value={replyText[report.id] || ""}
                              onChange={(e) => setReplyText((prev) => ({ ...prev, [report.id]: e.target.value }))}
                              placeholder="Provide additional details or landmark info..."
                              rows={2}
                              maxLength={REPLY_MAX_LENGTH}
                              className="w-full min-h-[60px] rounded-lg bg-white border border-orange-300 p-2.5 text-xs text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-orange-500 focus-visible:ring-2 focus-visible:ring-orange-500"
                              required={!hasReplyLocation}
                            />
                            <div className="flex flex-wrap items-center gap-2 text-[11px]">
                              <button
                                type="button"
                                onClick={() => {
                                  setPlaceError(null);
                                  if (!navigator.geolocation) {
                                    setPlaceError({ id: report.id, message: "This device cannot share its location." });
                                    return;
                                  }
                                  navigator.geolocation.getCurrentPosition(
                                    (pos) => {
                                      const { latitude, longitude } = pos.coords;
                                      if (!isInGujarat(latitude, longitude)) {
                                        setPlaceError({ id: report.id, message: "Your current location is outside Gujarat." });
                                        return;
                                      }
                                      setReplyPlace((prev) => ({ ...prev, [report.id]: { latitude, longitude } }));
                                    },
                                    () => setPlaceError({ id: report.id, message: "Could not read your location. Allow location access and try again." }),
                                    { enableHighAccuracy: true, timeout: 10000 }
                                  );
                                }}
                                className="min-h-[44px] px-3 rounded-lg border border-orange-300 bg-white text-orange-800 hover:bg-orange-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
                              >
                                <span aria-hidden="true">📍</span> Send my current location
                              </button>
                              {replyPlace[report.id] && (
                                <span role="status" className="text-emerald-700">
                                  Location added ({replyPlace[report.id]!.latitude.toFixed(4)}, {replyPlace[report.id]!.longitude.toFixed(4)}){" "}
                                  <button
                                    type="button"
                                    onClick={() => setReplyPlace((prev) => ({ ...prev, [report.id]: undefined }))}
                                    className="underline cursor-pointer"
                                  >
                                    Remove
                                  </button>
                                </span>
                              )}
                              {placeError?.id === report.id && <span role="alert" className="text-red-600">{placeError.message}</span>}
                            </div>
                            {replyError?.id === report.id && (
                              <div role="alert" className="text-[11px] text-red-600 font-medium">{replyError.message}</div>
                            )}
                            <div className="flex justify-end">
                              <button
                                type="submit"
                                disabled={replyingId === report.id || (!hasReplyLocation && replyLength < REPLY_MIN_LENGTH)}
                                className="min-h-[44px] px-4 py-1.5 rounded-lg bg-orange-600 hover:bg-orange-500 text-white text-xs font-semibold shadow transition disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
                              >
                                {replyingId === report.id ? "Sending..." : "Send reply"}
                              </button>
                            </div>
                          </form>
                        </>
                      )}
                    </section>
                  )}

                  {/* Visual 4-Stage Progression Timeline */}
                  <div className="pt-2">
                    <div className="grid grid-cols-4 gap-1.5 sm:gap-2 relative">
                      {STAGES.map((stage) => {
                        const isPast = statusInfo.step > stage.id;
                        const isCurrent = statusInfo.step === stage.id;

                        return (
                          <div
                            key={stage.id}
                            className="text-center relative"
                            aria-current={isCurrent ? "step" : undefined}
                          >
                            {/* Connector Bar */}
                            {stage.id < 4 && (
                              <div
                                className={`hidden sm:block absolute top-3.5 left-1/2 w-full h-0.5 z-0 ${
                                  isPast ? "bg-sky-500" : "bg-slate-200"
                                }`}
                                aria-hidden="true"
                              />
                            )}

                            {/* Node Icon */}
                            <div
                              className={`w-7 h-7 rounded-full flex items-center justify-center mx-auto mb-1.5 text-xs font-bold relative z-10 transition ${isPast
                                  ? "bg-sky-600 text-white shadow-xs"
                                  : isCurrent
                                    ? "bg-amber-500 text-white ring-4 ring-amber-100 shadow-xs font-extrabold"
                                    : "bg-slate-100 text-slate-400 border border-slate-300"
                                }`}
                            >
                              {isPast ? "✓" : stage.id}
                            </div>

                            <div
                              className={`text-[11px] sm:text-xs font-semibold truncate ${
                                isCurrent ? "text-amber-800 font-bold" : isPast ? "text-slate-800" : "text-slate-400"
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
                    <div className="mt-5 pt-4 border-t border-slate-200 text-xs space-y-2">
                      <ReportPhotos incidentId={report.id} closed={["CLOSED", "REJECTED"].includes(report.status)} />
                      {["SUBMITTED", "NEEDS_INFORMATION", "VERIFIED"].includes(currentStatus) && (
                        <div className="pt-2 text-xs">
                          {report.withdrawal_requested ? (
                            <p role="status" className="text-amber-700">
                              You asked to withdraw this report. A dispatcher will review it; until then it stays active.
                            </p>
                          ) : (
                            <button
                              type="button"
                              disabled={withdrawing === report.id}
                              onClick={async () => {
                                if (!window.confirm("Ask the dispatchers to withdraw this report? Use this for a false alarm or a duplicate.")) return;
                                setWithdrawing(report.id);
                                setWithdrawError(null);
                                const res = await requestWithdrawal(report.id);
                                setWithdrawing(null);
                                if (res.error) setWithdrawError({ id: report.id, message: res.error });
                                else loadReports();
                              }}
                              className="min-h-[44px] px-3 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 cursor-pointer disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
                            >
                              {withdrawing === report.id ? "Sending…" : "Ask to withdraw this report"}
                            </button>
                          )}
                          {withdrawError?.id === report.id && <p role="alert" className="mt-1 text-red-600">{withdrawError.message}</p>}
                        </div>
                      )}
                      <div className="font-semibold text-slate-900 mb-2">Detailed Event Audit:</div>
                      <div className="space-y-1.5 font-mono text-[11px] text-slate-600">
                        <div className="flex items-center gap-2">
                          <span className="text-emerald-600" aria-hidden="true">●</span>
                          <span>Report received by Gujarat Gateway:</span>
                          <span className="text-slate-900 font-medium">
                            {report.submitted_at || "Initial Timestamp recorded"}
                          </span>
                        </div>
                        {report.timeline &&
                          report.timeline.map((item, tIdx) => (
                            <div key={tIdx} className="flex items-center gap-2">
                              <span className="text-sky-600" aria-hidden="true">●</span>
                              <span>Status updated to {item.status}:</span>
                              <span className="text-slate-900 font-medium">
                                {new Date(item.timestamp).toLocaleString()}
                              </span>
                            </div>
                          ))}
                        <div className="flex items-center gap-2 text-slate-500">
                          <span aria-hidden="true">ℹ️</span>
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
