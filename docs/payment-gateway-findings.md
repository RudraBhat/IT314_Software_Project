# Payment Gateway — Test-Account Findings

**Sprint 1, S1-16 · Author:** Shlok · **Date:** 2026-11-02

> **Note:** This memo records research findings only.  
> Live API keys are **never stored in this repo** (gitleaks runs on every push).  
> The team member responsible for the gateway account (Siddh) will supply keys  
> via a secrets manager or `.env` (git-ignored) when integration work begins.

---

## Razorpay

| Item | Finding |
|---|---|
| Free test-mode account | **Yes — available immediately.** Sign up at [dashboard.razorpay.com](https://dashboard.razorpay.com) with a business email; test mode is enabled by default, no KYC required. |
| Test credentials issued | Yes — `rzp_test_*` Key ID and Key Secret are shown in *Settings → API Keys* within seconds of sign-up. |
| Webhook secret | Generated per endpoint under *Settings → Webhooks*; test events can be triggered from the dashboard. |
| SDK / API | Official Python SDK (`razorpay` on PyPI); REST API documented at [razorpay.com/docs](https://razorpay.com/docs/). |
| Limits in test mode | Unlimited test orders/payments; INR-only for Indian merchants; no real money moves. |
| Production activation | Requires GST registration + business bank account verification (out of Sprint 1 scope). |
| **Verdict** | ✅ Test account can be opened **this week** with no blockers. |

---

## Stripe

| Item | Finding |
|---|---|
| Free test-mode account | **Yes.** Sign up at [dashboard.stripe.com](https://dashboard.stripe.com); test mode available immediately. |
| Test credentials issued | Yes — `sk_test_*` Secret Key and `pk_test_*` Publishable Key are available right after email verification. |
| Webhook secret | Provided by Stripe CLI (`stripe listen`) or dashboard endpoint registration. |
| INR / India support | Stripe does support INR, but an **Indian entity with a live Stripe account** is required for production; test mode works globally. |
| Limits in test mode | Unlimited test transactions using [test card numbers](https://stripe.com/docs/testing). |
| Production activation | Requires Stripe India entity or cross-border business setup — more complex than Razorpay for India-domiciled projects. |
| **Verdict** | ✅ Test account openable this week. For this project (INR, India focus) **Razorpay is the lower-friction choice** for production. |

---

## Recommendation

Start with **Razorpay** for integration:

1. Lower friction for INR / India production pathway.
2. Our `RazorpayGateway` stub (`backend/app/payments/razorpay_gateway.py`) already maps to Razorpay's order-create API shape.
3. `MockGateway` keeps CI green until Siddh wires in the real keys.

When Siddh opens the account, the only env vars needed are (already in `.env.example`):

```
PAYMENT_GATEWAY=RAZORPAY
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```
