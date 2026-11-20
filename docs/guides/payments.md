# Payments and Donations Guide (S3-16, owner: Shlok)

This guide documents how donations move from a disaster relief campaign to an official receipt, every way a donation can end, the lazy expiry mechanism, how late captures work, what DM staff see in oversight, and what the sandbox gateway does and does not prove.

For API schema specifications, see [`docs/architecture/api_contracts.md`](../architecture/api_contracts.md) sections 7.4 and 7.5.

---

## 1. Core Principles & Invariants

* **Only the server confirms.** A donation transitions to `CONFIRMED` only after the backend verifies a cryptographic gateway signature: either via the client verification callback (`POST /api/v1/donations/{id}/verify`) or via an authentic gateway webhook (`POST /api/v1/payments/webhook/{gateway}`). Browser client claims of "success" are never trusted.
* **One official receipt.** An official receipt number (`REC-YYYY-NNNNNN` or `RCP-...`) is issued exactly once, inside the same database transaction that marks the donation `CONFIRMED`. Re-verifications or repeated webhooks are idempotent and return the existing receipt.
* **Every ending is recorded and audited.** State transitions go through [`backend/app/services/donation_endings.py`](../../backend/app/services/donation_endings.py) and write tamper-evident rows to the audit log.
* **A confirmed donation never changes status.** Cancelling a confirmed donation is refused (`409 DONATION_ALREADY_CONFIRMED`), and late failure events are ignored.
* **Captured money is never dropped.** If a payment gateway actually captures funds for an order that was marked `FAILED` (e.g. late network reconciliation after the donor abandoned or the order expired), a valid capture callback or webhook still transitions the order to `CONFIRMED` and issues a valid receipt.

---

## 2. Donation Lifecycle & Failure Endings (S3-11)

A donation starts as `PENDING` when created. It ends in one of three terminal states:

| State | Event / Trigger | Failure Reason | Behavior & Audit |
| :--- | :--- | :--- | :--- |
| **CONFIRMED** | Valid gateway signature on `/verify` or signed webhook `payment.captured` | `NULL` | Issues official receipt; records `DONATION_CONFIRMED`. |
| **FAILED (Abandoned)** | Donor cancels unpaid order via `POST /donations/{id}/cancel` | `ABANDONED` | Idempotent; records `DONATION_FAILED` (audit result: `FAILURE`, reason: `ABANDONED`). |
| **FAILED (Declined)** | Gateway webhook `payment.failed` (or sandbox decline simulation) | `GATEWAY_DECLINED` | Marks order failed; records `DONATION_FAILED` (audit result: `FAILURE`, reason: `GATEWAY_DECLINED`). |
| **FAILED (Expired)** | Order unpaid after `PENDING_TTL` (30 minutes) | `EXPIRED` | Marks order failed on next access; records `DONATION_EXPIRED`. |

### Lazy Expiry Architecture
Unlike legacy background workers that sweep databases periodically, expiration is implemented **lazily** in [`backend/app/services/donation_endings.py`](../../backend/app/services/donation_endings.py):
* `expire_stale_donations(conn)` is called automatically whenever donations are created, read, or summarized.
* The timeout is governed by `PENDING_TTL = timedelta(minutes=30)` (accessible via `ttl_minutes()`).
* Database partial index `idx_donations_pending_created` ensures zero-cost evaluation during scans.
* Schema constraints in [`backend/db/migrations/13_donation_endings.sql`](../../backend/db/migrations/13_donation_endings.sql) (`chk_donation_failure_reason`) enforce that only `FAILED` rows may hold a failure reason.

### Late Capture Guarantee
If a donor closes the checkout window or experiences a network delay, the server may mark the order `ABANDONED` or `EXPIRED`. However, if the bank or gateway subsequently captures the money, refusing the webhook would leave the donor charged without a receipt. DRCH handles this gracefully:
* A verified capture webhook or verify call on a `FAILED` order transitions it to `CONFIRMED`.
* The `failure_reason` is cleared to `NULL`, `confirmed_at` is stamped, and an official receipt number is generated.
* The donor is informed in user-facing copy: *"If money was deducted anyway, the donation is confirmed automatically when the payment provider reports it, and the receipt appears here."*

---

## 3. Citizen & DM Interfaces

### Citizen Donation & Receipts View
* **Donate Checkout:** [`frontend/src/app/donate/page.tsx`](../../frontend/src/app/donate/page.tsx) provides the contribution flow, allows cancellation, handles errors, and displays sandbox warnings.
* **My Donations & Receipts:** [`frontend/src/app/my-donations/page.tsx`](../../frontend/src/app/my-donations/page.tsx) consumes `GET /api/v1/me/donations` via the Next.js citizen BFF proxy:
  * Lists paginated donation history with live status badges.
  * For `CONFIRMED`: displays official receipt number, issue timestamp, and a browser Print / Save button.
  * For `PENDING`: indicates gateway confirmation is pending and that unpaid orders expire in 30 minutes.
  * For `FAILED`: translates backend enum reasons into clear, donor-friendly explanations (`ABANDONED` → *"You cancelled this donation"*, `GATEWAY_DECLINED` → *"Your payment was declined"*, `EXPIRED` → *"This donation expired before payment"*).

### DM Campaigns & Oversight
Disaster management staff monitor campaigns and donation metrics at `/dm/campaigns` (`GET /api/v1/dm/oversight/donations`):
* **Totals:** Live aggregates of `confirmed_amount`, `pending_amount`, and `failed_amount`.
* **Failure Breakdown (`failed_by_reason`):** Displays real-time counts and amounts for `ABANDONED`, `GATEWAY_DECLINED`, `EXPIRED`, and legacy/unclassified `UNKNOWN` failures.
* **Sandbox Indicator (`is_sandbox`):** Clearly alerts DM staff when the payment gateway is running in sandbox/mock mode so test contributions are never confused with real operational funds.
* **Pending Expiry Notice:** Indicates the oldest pending payment and references `pending_timeout_minutes` from `ttl_minutes()`.

---

## 4. Sandbox Gateway & Verification Limits

The default local and test gateway is `MockGateway` (`PAYMENT_GATEWAY=mock`):
* **Simulated Payments:** No real money moves. Banner notices appear on `/donate`, `/my-donations`, and `/dm/campaigns`.
* **Cryptographic Signatures:** Even in sandbox mode, HMAC-SHA256 signatures are calculated and verified with `MOCK_GATEWAY_SECRET`. Signature replay, tampered payloads, and mismatched amounts are fully tested.
* **What Sandbox Does NOT Test:** Real-world banking rails (UPI apps, NetBanking redirection, 3D-Secure OTPs, card fraud checks, and webhook network delays). Real credentials should only be used in staging environments.
* **Production Safety:** The `POST /donations/{id}/sandbox-payment` simulation endpoint is disabled in production environments (`APP_ENV=production`).

---

## 5. Verification & Automated Tests

All donation behavior is verified by automated test suites:
* **Backend Suite:** [`backend/tests/test_donation_endings.py`](../../backend/tests/test_donation_endings.py) validates cancel idempotency, lazy expiration sweeps, signature verification, late capture recovery, and DM oversight failure breakdowns against PostgreSQL.
* **Frontend E2E Suite:** [`frontend/e2e/donation-receipts.spec.ts`](../../frontend/e2e/donation-receipts.spec.ts) validates empty states, confirmed receipt presentation, and failure reason copy using Playwright.
