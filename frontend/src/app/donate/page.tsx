"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchPublicCampaigns, PublicCampaign } from "@/services/citizenApi";

type DonationStep = "select" | "order_created" | "confirmed";

interface CreatedOrder {
  donation_id: string;
  gateway_name: string;
  gateway_order_id: string;
  amount: number | string;
  currency: string;
  status: string;
}

interface ConfirmedDonation {
  donation_id: string;
  status: string;
  receipt_no: string;
  receipt_issued_at: string;
}

const isSandbox = process.env.NEXT_PUBLIC_PAYMENT_SANDBOX === "true";

export default function DonatePage() {
  const [campaigns, setCampaigns] = useState<PublicCampaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>("");
  const [amount, setAmount] = useState<number>(500);
  const [guestName, setGuestName] = useState("");
  const [guestEmail, setGuestEmail] = useState("");
  const [isAnonymous, setIsAnonymous] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Flow state
  const [step, setStep] = useState<DonationStep>("select");
  const [createdOrder, setCreatedOrder] = useState<CreatedOrder | null>(null);
  const [confirmed, setConfirmed] = useState<ConfirmedDonation | null>(null);
  const [sandboxBusy, setSandboxBusy] = useState(false);

  useEffect(() => {
    let ignore = false;
    const load = async () => {
      try {
        const res = await fetchPublicCampaigns();
        if (ignore) return;
        if (res.data) {
          setCampaigns(res.data);
          const firstActive = res.data.find((c) => c.status === "ACTIVE");
          if (firstActive) setSelectedCampaignId(firstActive.campaign_id);
          else if (res.data.length > 0) setSelectedCampaignId(res.data[0].campaign_id);
        } else if (res.error) {
          setError(res.error);
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load donation campaigns");
        }
      } finally {
        if (!ignore) setLoading(false);
      }
    };
    load();
    return () => {
      ignore = true;
    };
  }, []);

  const selectedCampaign = campaigns.find((c) => c.campaign_id === selectedCampaignId);
  const isCampaignActive = selectedCampaign?.status === "ACTIVE";

  const handleCreateDonation = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!selectedCampaignId) {
      setFormError("Please select a campaign.");
      return;
    }
    if (!isCampaignActive) {
      setFormError("This campaign is not accepting donations.");
      return;
    }
    if (amount < 1) {
      setFormError("Donation amount must be at least ₹1.");
      return;
    }
    if (!isAnonymous && !guestEmail.trim()) {
      setFormError("Guests must provide an email address, or choose to donate anonymously.");
      return;
    }

    setSubmitting(true);
    try {
      const idempotencyKey = crypto.randomUUID();
      const res = await fetch("/api/citizen/donations", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": idempotencyKey,
        },
        body: JSON.stringify({
          campaign_id: selectedCampaignId,
          amount: Number(amount),
          currency: "INR",
          guest_name: isAnonymous ? null : guestName.trim() || null,
          guest_email: isAnonymous ? null : guestEmail.trim() || null,
          is_anonymous: isAnonymous,
        }),
      });

      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body?.error?.message ?? `Donation creation failed (${res.status})`);
      }

      setCreatedOrder(body);
      setStep("order_created");
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Donation request failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSandboxPayment = async () => {
    if (!createdOrder) return;
    setSandboxBusy(true);
    setFormError(null);

    try {
      // 1. Request sandbox payment credentials
      const payRes = await fetch(`/api/citizen/donations/${createdOrder.donation_id}/sandbox-payment`, {
        method: "POST",
        headers: { "content-type": "application/json" },
      });
      const payBody = await payRes.json().catch(() => ({}));
      if (!payRes.ok) {
        throw new Error(payBody?.error?.message ?? "Sandbox payment failed");
      }

      const { gateway_payment_id, signature } = payBody;

      // 2. Verify signature to confirm donation and generate official receipt
      const verifyRes = await fetch(`/api/citizen/donations/${createdOrder.donation_id}/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ gateway_payment_id, signature }),
      });
      const verifyBody = await verifyRes.json().catch(() => ({}));
      if (!verifyRes.ok) {
        throw new Error(verifyBody?.error?.message ?? "Payment verification failed");
      }

      setConfirmed(verifyBody);
      setStep("confirmed");
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Payment processing failed");
    } finally {
      setSandboxBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-12">
      {/* Top Banner if Sandbox */}
      {isSandbox && (
        <div className="bg-amber-500 text-slate-950 px-4 py-2 text-center text-xs sm:text-sm font-bold tracking-wide shadow-xs">
          ⚠️ SANDBOX — no real money. All payments simulated for testing purposes.
        </div>
      )}

      {/* Header */}
      <header className="border-b border-slate-200 bg-white shadow-xs">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2 group">
              <span className="flex size-8 items-center justify-center rounded-lg bg-red-600 text-white font-bold text-sm shadow-xs group-hover:bg-red-700 transition">
                RQ
              </span>
              <span className="text-base font-bold tracking-tight text-slate-900">
                ResQ Disaster Relief Fund
              </span>
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="text-xs sm:text-sm font-medium text-slate-600 hover:text-slate-900 transition"
            >
              Back to Operations
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 pt-8 sm:px-6">
        <div className="mb-8">
          <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-slate-900">
            Relief & Response Donations
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Support targeted disaster management campaigns in Gujarat. 100% of verified contributions fund emergency operations and relief logistics.
          </p>
        </div>

        {loading && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            Loading active campaigns...
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {!loading && !error && campaigns.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-500">
            No donation campaigns are available at this moment.
          </div>
        )}

        {!loading && !error && campaigns.length > 0 && (
          <div className="grid grid-cols-1 gap-8 md:grid-cols-12">
            {/* Campaign Selection Column */}
            <div className="space-y-4 md:col-span-5">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Active Campaigns
              </h2>
              <div className="space-y-3">
                {campaigns.map((camp) => {
                  const isSelected = camp.campaign_id === selectedCampaignId;
                  const isActive = camp.status === "ACTIVE";
                  return (
                    <button
                      key={camp.campaign_id}
                      type="button"
                      onClick={() => {
                        setSelectedCampaignId(camp.campaign_id);
                        setFormError(null);
                      }}
                      className={`w-full text-left rounded-xl p-4 border transition-all cursor-pointer ${
                        isSelected
                          ? "border-sky-600 bg-sky-50/50 shadow-xs"
                          : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-semibold text-slate-900 text-sm">{camp.title}</span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                            isActive
                              ? "bg-emerald-100 text-emerald-800"
                              : "bg-slate-200 text-slate-700"
                          }`}
                        >
                          {isActive ? "ACTIVE" : "CLOSED"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-600 line-clamp-2">{camp.purpose}</p>
                      {camp.scenario && (
                        <div className="mt-2 text-[11px] font-mono font-medium text-slate-500">
                          Scenario: {camp.scenario.replace(/_/g, " ")}
                        </div>
                      )}
                      {camp.target_amount && (
                        <div className="mt-1 text-xs text-slate-700">
                          Target: <span className="font-medium">₹{Number(camp.target_amount).toLocaleString()}</span>
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Donation Action Column */}
            <div className="md:col-span-7">
              {step === "select" && (
                <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                  <h2 className="text-base font-bold text-slate-900">
                    Make a Contribution
                  </h2>
                  {selectedCampaign && (
                    <p className="mt-0.5 text-xs text-slate-500">
                      To: <span className="font-medium text-slate-800">{selectedCampaign.title}</span>
                    </p>
                  )}

                  {!isCampaignActive ? (
                    <div className="mt-6 rounded-xl border border-amber-300 bg-amber-50 p-4 text-center">
                      <p className="text-sm font-semibold text-amber-900">
                        This campaign is not accepting donations
                      </p>
                      <p className="mt-1 text-xs text-amber-700">
                        This campaign has concluded or has been closed by disaster management administrators. Please choose an active campaign.
                      </p>
                    </div>
                  ) : (
                    <form onSubmit={handleCreateDonation} className="mt-5 space-y-4">
                      {formError && (
                        <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700 border border-red-200">
                          {formError}
                        </div>
                      )}

                      {/* Amount */}
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1.5">
                          Amount (INR ₹)
                        </label>
                        <div className="relative">
                          <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-sm font-bold text-slate-400">
                            ₹
                          </span>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            required
                            value={amount}
                            onChange={(e) => setAmount(Number(e.target.value))}
                            className="w-full rounded-lg border border-slate-300 pl-8 pr-3 py-2.5 text-base font-semibold text-slate-900 focus:border-sky-600 focus:outline-none"
                            placeholder="500"
                          />
                        </div>
                        <div className="mt-2 flex gap-2">
                          {[250, 500, 1000, 5000].map((preset) => (
                            <button
                              key={preset}
                              type="button"
                              onClick={() => setAmount(preset)}
                              className={`rounded-md border px-2.5 py-1 text-xs font-medium transition cursor-pointer ${
                                amount === preset
                                  ? "border-sky-600 bg-sky-50 text-sky-700 font-bold"
                                  : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100"
                              }`}
                            >
                              ₹{preset}
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* Guest Details */}
                      <div className="border-t border-slate-100 pt-4 space-y-3">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={isAnonymous}
                            onChange={(e) => setIsAnonymous(e.target.checked)}
                            className="size-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                          />
                          <span className="text-xs font-medium text-slate-700">
                            Donate anonymously (no name or email required)
                          </span>
                        </label>

                        {!isAnonymous && (
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <div>
                              <label className="block text-xs font-medium text-slate-600 mb-1">
                                Full Name (Optional)
                              </label>
                              <input
                                type="text"
                                value={guestName}
                                onChange={(e) => setGuestName(e.target.value)}
                                placeholder="Your name"
                                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sky-600 focus:outline-none"
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-slate-600 mb-1">
                                Email Address (Required for receipt)
                              </label>
                              <input
                                type="email"
                                required={!isAnonymous}
                                value={guestEmail}
                                onChange={(e) => setGuestEmail(e.target.value)}
                                placeholder="name@example.com"
                                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sky-600 focus:outline-none"
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="pt-2">
                        <button
                          type="submit"
                          disabled={submitting}
                          className="w-full rounded-lg bg-sky-600 px-4 py-3 text-sm font-semibold text-white shadow-xs hover:bg-sky-500 transition disabled:opacity-50 cursor-pointer"
                        >
                          {submitting ? "Initiating..." : `Proceed to Contribute ₹${amount}`}
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              )}

              {step === "order_created" && createdOrder && (
                <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                  <div className="flex items-center gap-3">
                    <span className="flex size-8 items-center justify-center rounded-full bg-sky-100 text-sky-700 font-bold">
                      ✓
                    </span>
                    <div>
                      <h2 className="text-base font-bold text-slate-900">Contribution Order Created</h2>
                      <p className="text-xs text-slate-500">Order ID: {createdOrder.gateway_order_id}</p>
                    </div>
                  </div>

                  <div className="mt-5 rounded-xl bg-slate-50 p-4 space-y-2 text-sm border border-slate-100">
                    <div className="flex justify-between">
                      <span className="text-xs text-slate-500">Amount</span>
                      <span className="font-bold text-slate-900">₹{Number(createdOrder.amount).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-xs text-slate-500">Gateway</span>
                      <span className="font-mono text-xs text-slate-700">{createdOrder.gateway_name}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-xs text-slate-500">Status</span>
                      <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                        {createdOrder.status}
                      </span>
                    </div>
                  </div>

                  {formError && (
                    <div className="mt-4 rounded-lg bg-red-50 p-3 text-xs text-red-700 border border-red-200">
                      {formError}
                    </div>
                  )}

                  <div className="mt-6 space-y-3">
                    {isSandbox ? (
                      <button
                        type="button"
                        disabled={sandboxBusy}
                        onClick={handleSandboxPayment}
                        className="w-full rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-xs hover:bg-emerald-500 transition disabled:opacity-50 cursor-pointer"
                      >
                        {sandboxBusy ? "Authorizing in Sandbox..." : "Pay in Sandbox (Mock Authorization)"}
                      </button>
                    ) : (
                      <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800 border border-amber-200">
                        Live production gateway integration required to process cards/UPI.
                      </div>
                    )}

                    <button
                      type="button"
                      onClick={() => setStep("select")}
                      className="w-full rounded-lg border border-slate-200 px-4 py-2.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition cursor-pointer"
                    >
                      Cancel & Return
                    </button>
                  </div>
                </div>
              )}

              {step === "confirmed" && confirmed && (
                <div className="rounded-2xl border border-emerald-200 bg-white p-6 shadow-sm">
                  <div className="text-center">
                    <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 text-xl font-bold">
                      ✓
                    </span>
                    <h2 className="mt-3 text-lg font-bold text-slate-900">Contribution Confirmed</h2>
                    <p className="mt-1 text-xs text-slate-500">
                      Thank you for supporting emergency operations. Your contribution has been verified.
                    </p>
                  </div>

                  <div className="mt-6 rounded-xl border border-emerald-100 bg-emerald-50/50 p-4 space-y-3">
                    <div className="text-center border-b border-emerald-100 pb-3">
                      <div className="text-xs font-semibold uppercase tracking-wider text-emerald-800">Official Receipt Number</div>
                      <div className="mt-1 font-mono text-xl font-extrabold text-emerald-950">
                        {confirmed.receipt_no}
                      </div>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500">Issued At</span>
                      <span className="font-medium text-slate-800">{new Date(confirmed.receipt_issued_at).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500">Status</span>
                      <span className="font-bold text-emerald-700">{confirmed.status}</span>
                    </div>
                  </div>

                  <div className="mt-6 flex flex-col gap-2 sm:flex-row">
                    <button
                      type="button"
                      onClick={() => {
                        setStep("select");
                        setCreatedOrder(null);
                        setConfirmed(null);
                      }}
                      className="flex-1 rounded-lg border border-slate-200 px-4 py-2.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition cursor-pointer text-center"
                    >
                      Make Another Contribution
                    </button>
                    <Link
                      href="/"
                      className="flex-1 rounded-lg bg-sky-600 px-4 py-2.5 text-xs font-semibold text-white hover:bg-sky-500 transition text-center"
                    >
                      View Live Operations Map
                    </Link>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
