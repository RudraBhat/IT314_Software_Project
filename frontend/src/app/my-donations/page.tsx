"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { UnifiedSiteHeader } from "@/components/navigation/UnifiedSiteHeader";
import { Button, EmptyState, ErrorState, LoadingRows, Notice, Pagination } from "@/components/ui";
import { formatDateTime, formatMoney } from "@/lib/format";
import { DonationRecord, fetchMyDonations, PaginatedDonations } from "@/services/citizenApi";

const isSandboxEnv = process.env.NEXT_PUBLIC_PAYMENT_SANDBOX === "true";

export default function MyDonationsPage() {
  const [data, setData] = useState<PaginatedDonations | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const loadDonations = useCallback(async (targetPage: number) => {
    setLoading(true);
    try {
      const res = await fetchMyDonations(targetPage);
      if (res.error) {
        setError(res.error);
        setData(null);
      } else if (res.data) {
        setData(res.data);
        setError(null);
      }
    } catch {
      setError("Unable to connect to donation records service.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDonations(page);
  }, [loadDonations, page]);

  const anySandbox = isSandboxEnv || (data?.items?.some((d) => d.is_sandbox) ?? false);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col font-sans">
      <UnifiedSiteHeader activeHref="/my-donations" />

      <main className="mx-auto w-full max-w-4xl flex-1 p-4 sm:p-6 md:p-8 space-y-6">
        {anySandbox && (
          <Notice tone="medium">
            ⚠️ SANDBOX — no real money. All payments simulated for testing purposes.
          </Notice>
        )}

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-slate-900 flex items-center gap-2">
              <span aria-hidden="true">🧾</span> My Donations &amp; Receipts
            </h1>
            <p className="text-slate-600 text-xs md:text-sm mt-0.5">
              Official receipts for verified contributions to Gujarat Disaster Management operations.
            </p>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void loadDonations(page)}
            disabled={loading}
          >
            ↻ Refresh
          </Button>
        </div>

        {error && (
          <div className="space-y-3">
            <ErrorState message={error} onRetry={() => void loadDonations(page)} />
            {(error.includes("session") || error.includes("Sign in") || error.includes("401")) && (
              <div className="text-center">
                <Link
                  href="/login?next=/my-donations"
                  className="text-xs font-semibold text-sky-600 hover:underline"
                >
                  Sign in with your citizen account →
                </Link>
              </div>
            )}
          </div>
        )}

        {loading && !data && <LoadingRows rows={4} />}

        {!loading && !error && data && data.items.length === 0 && (
          <EmptyState title="No donations yet.">
            <p className="text-xs text-slate-500 mt-1 mb-4">
              You have not made any donations with this account yet. Contributions help provide vital relief supplies during active emergencies.
            </p>
            <Link
              href="/donate"
              className="inline-flex items-center gap-2 min-h-[40px] bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold px-5 py-2 rounded-xl shadow-xs transition"
            >
              Support Disaster Relief
            </Link>
          </EmptyState>
        )}

        {data && data.items.length > 0 && (
          <div className="space-y-4">
            <ul className="space-y-4" role="list">
              {data.items.map((item) => (
                <DonationCard key={item.donation_id} item={item} />
              ))}
            </ul>

            {data.pages > 1 && (
              <div className="pt-4 flex justify-center">
                <Pagination
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  onPage={(p) => setPage(p)}
                />
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function DonationCard({ item }: { item: DonationRecord }) {
  const statusConfig = {
    CONFIRMED: {
      label: "Confirmed",
      badgeClass: "bg-emerald-50 text-emerald-800 border-emerald-200",
      symbol: "✓",
    },
    PENDING: {
      label: "Pending",
      badgeClass: "bg-amber-50 text-amber-800 border-amber-200",
      symbol: "⏳",
    },
    FAILED: {
      label: "Failed",
      badgeClass: "bg-rose-50 text-rose-800 border-rose-200",
      symbol: "✕",
    },
  }[item.status] || {
    label: item.status,
    badgeClass: "bg-slate-100 text-slate-700 border-slate-200",
    symbol: "•",
  };

  const failureText =
    item.failure_reason === "ABANDONED"
      ? "You cancelled this donation"
      : item.failure_reason === "GATEWAY_DECLINED"
        ? "Your payment was declined"
        : item.failure_reason === "EXPIRED"
          ? "This donation expired before payment"
          : "This donation did not complete";

  return (
    <li className="bg-white border border-slate-200/90 rounded-2xl p-5 md:p-6 shadow-xs transition hover:border-slate-300">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${statusConfig.badgeClass}`}
            >
              <span aria-hidden="true">{statusConfig.symbol}</span>
              {statusConfig.label}
            </span>
            {item.is_sandbox && (
              <span className="text-[10px] font-mono uppercase bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded font-semibold">
                Sandbox
              </span>
            )}
          </div>
          <h2 className="mt-2 text-base md:text-lg font-bold text-slate-900">
            {item.campaign_title || "Disaster Relief Campaign"}
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Initiated on {formatDateTime(item.created_at)}
          </p>
        </div>

        <div className="text-right">
          <div className="text-lg md:text-xl font-bold text-slate-900 tabular-nums">
            {formatMoney(item.amount, item.currency)}
          </div>
          <div className="text-[11px] text-slate-500 uppercase tracking-wider font-semibold">
            {item.currency}
          </div>
        </div>
      </div>

      {item.status === "CONFIRMED" && (
        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50/70 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-800">
                Official Receipt Number
              </div>
              <div className="mt-1 font-mono text-base md:text-lg font-bold text-slate-900 tracking-wide">
                {item.receipt_no}
              </div>
              {item.receipt_issued_at && (
                <div className="mt-0.5 text-xs text-slate-600">
                  Issued at {formatDateTime(item.receipt_issued_at)}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => window.print()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 bg-white hover:bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 transition cursor-pointer shadow-2xs"
            >
              <span aria-hidden="true">🖨️</span> Print / Save Receipt
            </button>
          </div>
        </div>
      )}

      {item.status === "PENDING" && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-4 text-xs text-amber-900">
          <p className="font-semibold text-amber-800">
            Awaiting payment confirmation from the gateway.
          </p>
          <p className="mt-1 text-slate-600">
            Unpaid orders expire automatically after 30 minutes. Once confirmed by the gateway callback, your official receipt will appear here.
          </p>
        </div>
      )}

      {item.status === "FAILED" && (
        <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50/70 p-4 text-xs space-y-1.5 text-rose-950">
          <p className="font-semibold text-rose-800">{failureText}</p>
          <p className="text-slate-600">
            If money was deducted anyway, the donation is confirmed automatically when the payment provider reports it, and the receipt appears here.
          </p>
        </div>
      )}
    </li>
  );
}
