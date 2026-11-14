"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { SiteHeader, NavLink } from "@/components/Brand";
import { fetchPublicCampaigns, PublicCampaign } from "@/services/citizenApi";

type DonationStep = "select" | "order_created" | "confirmed" | "declined" | "abandoned" | "timed_out";

interface CreatedOrder {
  donation_id: string;
  gateway_name: string;
  gateway_order_id: string;
  amount: number | string;
  currency: string;
  status: string;
  is_sandbox?: boolean;
  /** Public Razorpay key id; null for the sandbox gateway. */
  checkout_key?: string | null;
}

interface RazorpaySuccess {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
}

interface RazorpayCheckout {
  open: () => void;
  on: (event: "payment.failed", handler: (response: { error?: { description?: string } }) => void) => void;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayCheckout;
  }
}

const RAZORPAY_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

/** Load Razorpay's hosted checkout script once; rejects when it cannot be fetched. */
function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = RAZORPAY_SCRIPT;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Could not load the payment window. Check your connection and retry."));
    document.body.appendChild(script);
  });
}

interface ConfirmedDonation {
  donation_id: string;
  status: string;
  receipt_no: string;
  receipt_issued_at: string;
}

const isSandbox = process.env.NEXT_PUBLIC_PAYMENT_SANDBOX === "true";

/** A gateway call that gets no answer in this time is treated as a timed-out payment. */
const REQUEST_TIMEOUT_MS = 20_000;

class PaymentStepError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

async function postJson(url: string, body?: unknown): Promise<Record<string, unknown>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & {
      error?: { code?: string; message?: string };
    };
    if (!res.ok) {
      throw new PaymentStepError(data.error?.message ?? `Request failed (${res.status})`, res.status, data.error?.code ?? "");
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

type PaymentFailure = { kind: "declined" | "timed_out" | "error"; message: string };

/** Map a failed payment call onto one of the payment ending states. */
function classifyFailure(err: unknown): PaymentFailure {
  if (err instanceof PaymentStepError) {
    if (err.code === "INVALID_SIGNATURE" || err.status === 400 || err.status === 402) {
      return { kind: "declined", message: err.message };
    }
    return { kind: "error", message: err.message };
  }
  // fetch rejects with AbortError on our timeout and with TypeError when the network is unreachable.
  if (err instanceof DOMException && err.name === "AbortError") {
    return { kind: "timed_out", message: "The gateway did not answer in time." };
  }
  if (err instanceof TypeError) {
    return { kind: "timed_out", message: "The connection to the payment gateway was lost." };
  }
  return { kind: "error", message: err instanceof Error ? err.message : "Payment processing failed" };
}

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

  // Flow state: confirmed plus the declined, abandoned and timed-out endings
  const [step, setStep] = useState<DonationStep>("select");
  const [createdOrder, setCreatedOrder] = useState<CreatedOrder | null>(null);
  const [confirmed, setConfirmed] = useState<ConfirmedDonation | null>(null);
  const [failureReason, setFailureReason] = useState<string>("");
  // True when an ending was triggered by the sandbox buttons, so nothing was sent to the gateway.
  const [simulated, setSimulated] = useState(false);
  const outcomeHeadingRef = useRef<HTMLHeadingElement>(null);

  // Move keyboard and screen-reader focus to the result when the flow ends in a failure state.
  useEffect(() => {
    if (step === "declined" || step === "abandoned" || step === "timed_out") outcomeHeadingRef.current?.focus();
  }, [step]);

  const goTo = (next: DonationStep) => {
    setFormError(null);
    setStep(next);
  };
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
    setSimulated(false);

    try {
      // 1. Request sandbox payment credentials
      const pay = await postJson(`/api/citizen/donations/${createdOrder.donation_id}/sandbox-payment`);
      const { gateway_payment_id, signature } = pay;

      // 2. Verify signature to confirm donation and generate official receipt
      const verified = await postJson(`/api/citizen/donations/${createdOrder.donation_id}/verify`, {
        gateway_payment_id,
        signature,
      });

      setConfirmed(verified as unknown as ConfirmedDonation);
      setStep("confirmed");
    } catch (err: unknown) {
      const failure = classifyFailure(err);
      if (failure.kind === "error") {
        setFormError(failure.message);
      } else {
        setFailureReason(failure.message);
        setStep(failure.kind);
      }
    } finally {
      setSandboxBusy(false);
    }
  };

  /** Open Razorpay Checkout for the created order, then let the server verify the signature. */
  const handleRazorpayPayment = async () => {
    if (!createdOrder?.checkout_key) return;
    const order = createdOrder;
    setSandboxBusy(true);
    setFormError(null);
    setSimulated(false);
    try {
      await loadRazorpay();
      if (!window.Razorpay) throw new Error("The payment window is unavailable. Please retry.");
      const checkout = new window.Razorpay({
        key: order.checkout_key,
        order_id: order.gateway_order_id,
        // Razorpay takes paise; the server created the order for this exact amount.
        amount: Math.round(Number(order.amount) * 100),
        currency: order.currency,
        name: "ResQ Gujarat Relief",
        description: "Disaster relief contribution",
        prefill: { name: isAnonymous ? "" : guestName.trim(), email: isAnonymous ? "" : guestEmail.trim() },
        handler: async (response: RazorpaySuccess) => {
          try {
            const verified = await postJson(`/api/citizen/donations/${order.donation_id}/verify`, {
              gateway_payment_id: response.razorpay_payment_id,
              signature: response.razorpay_signature,
            });
            setConfirmed(verified as unknown as ConfirmedDonation);
            setStep("confirmed");
          } catch (err: unknown) {
            const failure = classifyFailure(err);
            if (failure.kind === "error") {
              setFormError(failure.message);
            } else {
              setFailureReason(failure.message);
              setStep(failure.kind);
            }
          } finally {
            setSandboxBusy(false);
          }
        },
        modal: {
          ondismiss: () => {
            // Closed without paying: the order stays PENDING and can be retried.
            setSandboxBusy(false);
            setStep((current) => (current === "order_created" ? "abandoned" : current));
          },
        },
      });
      checkout.on("payment.failed", (response) => {
        setFailureReason(response.error?.description ?? "The payment was declined.");
        setSandboxBusy(false);
        setStep("declined");
      });
      checkout.open();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Could not start the payment");
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

      <SiteHeader subtitle="Disaster Relief Fund" maxWidth="max-w-5xl">
        <NavLink href="/">← Back to map</NavLink>
      </SiteHeader>

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
                    <div role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-xs text-red-700 border border-red-200">
                      {formError}
                    </div>
                  )}

                  <div className="mt-6 space-y-3">
                    {createdOrder.checkout_key ? (
                      <button
                        type="button"
                        disabled={sandboxBusy}
                        onClick={handleRazorpayPayment}
                        className="w-full rounded-lg bg-sky-600 px-4 py-3 text-sm font-semibold text-white shadow-xs hover:bg-sky-500 transition disabled:opacity-50 cursor-pointer"
                      >
                        {sandboxBusy ? "Waiting for payment..." : `Pay ₹${Number(createdOrder.amount).toLocaleString()} with Razorpay`}
                      </button>
                    ) : isSandbox ? (
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

                    {/* Sandbox only: preview the ending screens without calling the gateway */}
                    {isSandbox && (
                      <div className="pt-2 border-t border-slate-200">
                        <div className="text-[11px] font-bold uppercase tracking-wider text-slate-600 mb-1.5 text-center">
                          Sandbox: preview a payment ending
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            disabled={sandboxBusy}
                            onClick={() => {
                              setFailureReason("Transaction declined by the card issuer.");
                              setSimulated(true);
                              goTo("declined");
                            }}
                            className="min-h-11 rounded-lg border border-red-200 bg-red-50/70 hover:bg-red-100/80 px-2.5 py-1.5 text-xs font-semibold text-red-700 transition cursor-pointer text-center"
                          >
                            Preview Decline
                          </button>
                          <button
                            type="button"
                            disabled={sandboxBusy}
                            onClick={() => {
                              setFailureReason("The gateway did not answer in time.");
                              setSimulated(true);
                              goTo("timed_out");
                            }}
                            className="min-h-11 rounded-lg border border-amber-200 bg-amber-50/70 hover:bg-amber-100/80 px-2.5 py-1.5 text-xs font-semibold text-amber-700 transition cursor-pointer text-center"
                          >
                            Preview Timeout
                          </button>
                        </div>
                      </div>
                    )}

                    <button
                      type="button"
                      onClick={() => {
                        setSimulated(false);
                        goTo("abandoned");
                      }}
                      className="w-full min-h-11 rounded-lg border border-slate-200 px-4 py-2.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition cursor-pointer"
                    >
                      Cancel & Abandon Order
                    </button>
                  </div>
                </div>
              )}

              {/* S3-11: Declined Payment State */}
              {step === "declined" && createdOrder && (
                <div className="rounded-2xl border border-red-200 bg-white p-6 shadow-sm">
                  <div className="text-center">
                    <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-red-100 text-red-700 text-xl font-bold">
                      ✕
                    </span>
                    <h2 ref={outcomeHeadingRef} tabIndex={-1} className="mt-3 text-lg font-bold text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">Contribution Declined</h2>
                    <p className="mt-1 text-xs text-slate-500">
                      The payment gateway was unable to authorize this transaction.
                    </p>
                  </div>

                  <div className="mt-6 rounded-xl border border-red-100 bg-red-50/50 p-4 space-y-3">
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500">Order Reference</span>
                      <span className="font-mono font-bold text-slate-800">{createdOrder.gateway_order_id}</span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500">Amount Attempted</span>
                      <span className="font-bold text-slate-900">₹{Number(createdOrder.amount).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500">Status</span>
                      <span className="font-bold text-red-700">{simulated ? "DECLINED (preview)" : "DECLINED"}</span>
                    </div>
                    <div className="pt-2 border-t border-red-100 text-xs text-red-800">
                      <strong>Reason:</strong> {failureReason || "Gateway authorization failed. Please check payment details and retry."}
                    </div>
                  </div>

                  <div className="mt-3 rounded-lg bg-amber-50 p-2 text-center text-[11px] font-medium text-amber-800 border border-amber-200">
                    {simulated ? "⚠️ SANDBOX PREVIEW — nothing was sent to the gateway and no money moved." : createdOrder.is_sandbox === false ? "This payment was declined. Check with your bank before retrying." : "⚠️ SANDBOX — no real money was charged to your card or account."}
                  </div>

                  <div className="mt-6 flex flex-col gap-2 sm:flex-row">
                    <button
                      type="button"
                      onClick={() => goTo("order_created")}
                      className="flex-1 rounded-lg bg-sky-600 px-4 py-2.5 text-xs font-semibold text-white hover:bg-sky-500 transition cursor-pointer text-center"
                    >
                      Retry Payment
                    </button>
                    <button
                      type="button"
                      onClick={() => goTo("select")}
                      className="flex-1 rounded-lg border border-slate-200 px-4 py-2.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition cursor-pointer text-center"
                    >
                      Change Details
                    </button>
                  </div>
                </div>
              )}

              {/* S3-11: Abandoned / Cancelled Payment State */}
              {step === "abandoned" && createdOrder && (
                <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                  <div className="text-center">
                    <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-slate-100 text-slate-600 text-xl font-bold">
                      ⊘
                    </span>
                    <h2 ref={outcomeHeadingRef} tabIndex={-1} className="mt-3 text-lg font-bold text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">Contribution Cancelled</h2>
                    <p className="mt-1 text-xs text-slate-500">
                      You cancelled this payment request before authorization completed.
                    </p>
                  </div>

                  <div className="mt-6 rounded-xl border border-slate-100 bg-slate-50 p-4 space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Order ID</span>
                      <span className="font-mono text-slate-700">{createdOrder.gateway_order_id}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Amount</span>
                      <span className="font-semibold text-slate-800">₹{Number(createdOrder.amount).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Status</span>
                      <span className="font-medium text-slate-600">ABANDONED</span>
                    </div>
                    <p className="text-[11px] text-slate-500 pt-1 border-t border-slate-200">
                      No funds were captured. Your account has not been charged.
                    </p>
                  </div>

                  <div className="mt-3 rounded-lg bg-amber-50 p-2 text-center text-[11px] font-medium text-amber-800 border border-amber-200">
                    {simulated ? "⚠️ SANDBOX PREVIEW — nothing was sent to the gateway." : createdOrder.is_sandbox === false ? "Your payment was not confirmed. If you were charged, the donation is confirmed automatically once the gateway reports it." : "⚠️ SANDBOX — no real money moved."}
                  </div>

                  <div className="mt-6 flex flex-col gap-2 sm:flex-row">
                    <button
                      type="button"
                      onClick={() => goTo("select")}
                      className="flex-1 rounded-lg bg-sky-600 px-4 py-2.5 text-xs font-semibold text-white hover:bg-sky-500 transition cursor-pointer text-center"
                    >
                      Resume Contribution
                    </button>
                    <Link
                      href="/"
                      className="flex-1 rounded-lg border border-slate-200 px-4 py-2.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition cursor-pointer text-center"
                    >
                      Return to Map
                    </Link>
                  </div>
                </div>
              )}

              {/* S3-11: Timed Out Payment State */}
              {step === "timed_out" && createdOrder && (
                <div className="rounded-2xl border border-amber-200 bg-white p-6 shadow-sm">
                  <div className="text-center">
                    <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-amber-100 text-amber-700 text-xl font-bold">
                      ⏱
                    </span>
                    <h2 ref={outcomeHeadingRef} tabIndex={-1} className="mt-3 text-lg font-bold text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">Payment Session Timed Out</h2>
                    <p className="mt-1 text-xs text-slate-500">
                      The authorization window expired before a confirmation signal was received from the gateway.
                    </p>
                  </div>

                  <div className="mt-6 rounded-xl border border-amber-100 bg-amber-50/60 p-4 space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Order ID</span>
                      <span className="font-mono text-slate-700">{createdOrder.gateway_order_id}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Amount</span>
                      <span className="font-semibold text-slate-800">₹{Number(createdOrder.amount).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">State</span>
                      <span className="font-bold text-amber-800">{simulated ? "TIMED OUT (preview)" : "TIMED OUT"}</span>
                    </div>
                    <p className="text-[11px] text-amber-900/80 pt-1 border-t border-amber-200">
                      No payment is confirmed until the gateway reports it. If you were charged, quote this order ID to the relief fund team.
                    </p>
                  </div>

                  <div className="mt-3 rounded-lg bg-amber-50 p-2 text-center text-[11px] font-medium text-amber-800 border border-amber-200">
                    {simulated ? "⚠️ SANDBOX PREVIEW — nothing was sent to the gateway." : createdOrder.is_sandbox === false ? "Your payment was not confirmed. If you were charged, the donation is confirmed automatically once the gateway reports it." : "⚠️ SANDBOX — no real money moved."}
                  </div>

                  <div className="mt-6 flex flex-col gap-2 sm:flex-row">
                    <button
                      type="button"
                      disabled={sandboxBusy}
                      onClick={handleSandboxPayment}
                      className="flex-1 rounded-lg bg-amber-600 px-4 py-2.5 text-xs font-semibold text-white hover:bg-amber-500 transition cursor-pointer text-center"
                    >
                      {sandboxBusy ? "Verifying..." : "Check Status & Re-verify"}
                    </button>
                    <button
                      type="button"
                      onClick={() => goTo("select")}
                      className="flex-1 rounded-lg border border-slate-200 px-4 py-2.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition cursor-pointer text-center"
                    >
                      Start New Contribution
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
